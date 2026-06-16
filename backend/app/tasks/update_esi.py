import datetime
import logging
import time

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters import esi
from app.core.database import (
    SessionLocal,
    LinkedCharacter,
    EsiWalletTransaction,
    EsiSkill,
    EsiAsset,
    EsiContract,
    EsiIndustryJob,
)

logger = logging.getLogger(__name__)

_CHUNK = 1000


def _chunks(rows, n=_CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _upsert(db, model, rows, conflict_cols, update_cols):
    """INSERT ... ON CONFLICT DO UPDATE in chunks. No-op on empty input."""
    for batch in _chunks(rows):
        stmt = pg_insert(model).values(batch)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={c: stmt.excluded[c] for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
        db.execute(stmt)
    db.commit()


def _replace(db, model, character_id, rows):
    """Replace the whole per-character set (delete then insert) — for state-like data."""
    db.query(model).filter(model.character_id == character_id).delete(synchronize_session=False)
    for batch in _chunks(rows):
        db.execute(pg_insert(model).values(batch))
    db.commit()


# Row mappers (ESI json -> table dict)

def _map_transaction(cid, t):
    return {
        "character_id": cid,
        "transaction_id": t.get("transaction_id"),
        "date": esi.parse_dt(t.get("date")),
        "type_id": t.get("type_id"),
        "quantity": t.get("quantity"),
        "unit_price": t.get("unit_price"),
        "is_buy": t.get("is_buy"),
        "is_personal": t.get("is_personal"),
        "client_id": t.get("client_id"),
        "location_id": t.get("location_id"),
        "journal_ref_id": t.get("journal_ref_id"),
    }


def _map_skill(cid, s):
    return {
        "character_id": cid,
        "skill_id": s.get("skill_id"),
        "skillpoints": s.get("skillpoints_in_skill"),
        "trained_level": s.get("trained_skill_level"),
        "active_level": s.get("active_skill_level"),
    }


def _map_asset(cid, a):
    return {
        "character_id": cid,
        "item_id": a.get("item_id"),
        "type_id": a.get("type_id"),
        "quantity": a.get("quantity"),
        "location_id": a.get("location_id"),
        "location_flag": a.get("location_flag"),
        "location_type": a.get("location_type"),
        "is_singleton": a.get("is_singleton"),
        "is_blueprint_copy": a.get("is_blueprint_copy"),
    }


def _map_contract(cid, c):
    return {
        "character_id": cid,
        "contract_id": c.get("contract_id"),
        "type": c.get("type"),
        "status": c.get("status"),
        "for_corp": c.get("for_corp"),
        "issuer_id": c.get("issuer_id"),
        "assignee_id": c.get("assignee_id"),
        "acceptor_id": c.get("acceptor_id"),
        "date_issued": esi.parse_dt(c.get("date_issued")),
        "date_expired": esi.parse_dt(c.get("date_expired")),
        "date_accepted": esi.parse_dt(c.get("date_accepted")),
        "date_completed": esi.parse_dt(c.get("date_completed")),
        "price": c.get("price"),
        "reward": c.get("reward"),
        "collateral": c.get("collateral"),
        "volume": c.get("volume"),
        "title": c.get("title"),
        "availability": c.get("availability"),
        "start_location_id": c.get("start_location_id"),
        "end_location_id": c.get("end_location_id"),
    }


def _map_job(cid, j):
    return {
        "character_id": cid,
        "job_id": j.get("job_id"),
        "activity_id": j.get("activity_id"),
        "blueprint_type_id": j.get("blueprint_type_id"),
        "blueprint_id": j.get("blueprint_id"),
        "product_type_id": j.get("product_type_id"),
        "runs": j.get("runs"),
        "licensed_runs": j.get("licensed_runs"),
        "status": j.get("status"),
        "start_date": esi.parse_dt(j.get("start_date")),
        "end_date": esi.parse_dt(j.get("end_date")),
        "facility_id": j.get("facility_id"),
        "station_id": j.get("station_id"),
        "cost": j.get("cost"),
        "probability": j.get("probability"),
    }


# Per-character sync

def sync_character(db, char: LinkedCharacter) -> dict:
    """Pull + persist all ESI data for one character. Returns a per-endpoint summary."""
    cid = char.character_id
    summary: dict = {"character_id": cid, "name": char.character_name, "counts": {}, "errors": []}

    token = esi.valid_access_token(db, char)  # raises if refresh fails

    def step(name, fn):
        try:
            summary["counts"][name] = fn()
        except Exception as exc:  # noqa: BLE001 — best effort per endpoint
            logger.warning("esi sync %s/%s failed: %s", cid, name, exc)
            summary["errors"].append(f"{name}: {exc}")

    def _affiliation():
        aff = esi.fetch_affiliation(cid)
        char.corporation_id = aff.get("corporation_id")
        char.alliance_id = aff.get("alliance_id")
        db.commit()
        return 1

    def _wallet():
        char.wallet_balance = esi.fetch_wallet_balance(cid, token)
        db.commit()
        rows = [_map_transaction(cid, t) for t in esi.fetch_transactions(cid, token)]
        _upsert(db, EsiWalletTransaction, rows, ["character_id", "transaction_id"], [])
        return len(rows)

    def _skills():
        data = esi.fetch_skills(cid, token)
        char.total_sp = data.get("total_sp")
        db.commit()
        rows = [_map_skill(cid, s) for s in data.get("skills", [])]
        _upsert(db, EsiSkill, rows, ["character_id", "skill_id"],
                ["skillpoints", "trained_level", "active_level"])
        return len(rows)

    def _assets():
        rows = [_map_asset(cid, a) for a in esi.fetch_assets(cid, token)]
        _replace(db, EsiAsset, cid, rows)
        return len(rows)

    def _contracts():
        rows = [_map_contract(cid, c) for c in esi.fetch_contracts(cid, token)]
        _upsert(db, EsiContract, rows, ["character_id", "contract_id"],
                ["status", "date_accepted", "date_completed", "acceptor_id"])
        return len(rows)

    def _jobs():
        rows = [_map_job(cid, j) for j in esi.fetch_industry_jobs(cid, token)]
        _replace(db, EsiIndustryJob, cid, rows)
        return len(rows)

    step("affiliation", _affiliation)
    step("wallet", _wallet)
    step("skills", _skills)
    step("assets", _assets)
    step("contracts", _contracts)
    step("industry_jobs", _jobs)

    char.last_sync_at = datetime.datetime.utcnow()
    db.commit()
    return summary


def sync_all_active() -> dict:
    """Sync every active linked character. Entry point for the scheduled worker job."""
    db = SessionLocal()
    summary: dict = {"characters": 0, "results": [], "errors": []}
    try:
        chars = (
            db.query(LinkedCharacter)
            .filter(LinkedCharacter.is_active.is_(True), LinkedCharacter.status == "active")
            .all()
        )
        summary["characters"] = len(chars)
        for char in chars:
            t0 = time.time()
            try:
                res = sync_character(db, char)
                res["seconds"] = round(time.time() - t0, 1)
                summary["results"].append(res)
            except Exception as exc:  # noqa: BLE001
                logger.error("esi sync for %s failed: %s", char.character_id, exc)
                summary["errors"].append(f"{char.character_id}: {exc}")
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
    result = sync_all_active()
    print(f"Synced {result['characters']} character(s); errors: {len(result['errors'])}")
