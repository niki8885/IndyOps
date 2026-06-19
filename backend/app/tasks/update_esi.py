import datetime
import logging
import time

import requests
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
    EsiStanding,
    EsiStructure,
    EsiImplant,
    EsiMiningLedger,
    EsiBlueprintCopy,
    CharacterWealthSnapshot,
)
from app.core.timeutil import utcnow
from app.services import asset_location

logger = logging.getLogger(__name__)

_STRUCTURE_SCOPE = "esi-universe.read_structures.v1"
_LOCATION_SCOPE = "esi-location.read_location.v1"
_SHIP_SCOPE = "esi-location.read_ship_type.v1"
_ONLINE_SCOPE = "esi-location.read_online.v1"
_IMPLANTS_SCOPE = "esi-clones.read_implants.v1"
_MINING_SCOPE = "esi-industry.read_character_mining.v1"
_BLUEPRINTS_SCOPE = "esi-characters.read_blueprints.v1"
_STRUCTURE_NAME_TTL = datetime.timedelta(days=7)     # names rarely change
_STRUCTURE_RETRY_TTL = datetime.timedelta(hours=6)   # back off after a 403/404

# CCP market-wide average prices — fetched once and shared across the sync run
# (it's ~13k rows; refetching per character would be wasteful).
_PRICE_TTL = datetime.timedelta(hours=1)
_price_cache: dict = {"prices": None, "ts": None}


def _has_scope(char: LinkedCharacter, scope: str) -> bool:
    return scope in (char.scopes or "").split()


def _market_prices() -> dict:
    """``{type_id: average_price}`` from ESI, cached for an hour. {} on failure."""
    now = utcnow()
    if _price_cache["prices"] is not None and _price_cache["ts"] and now - _price_cache["ts"] < _PRICE_TTL:
        return _price_cache["prices"]
    try:
        rows = esi.fetch_market_prices()
        prices = {r["type_id"]: (r.get("average_price") or r.get("adjusted_price") or 0.0) for r in rows}
        _price_cache["prices"] = prices
        _price_cache["ts"] = now
        return prices
    except Exception as exc:  # noqa: BLE001
        logger.warning("market prices fetch failed: %s", exc)
        return _price_cache["prices"] or {}

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


def _map_blueprint(cid, b):
    return {
        "character_id": cid,
        "item_id": b.get("item_id"),
        "type_id": b.get("type_id"),
        "material_efficiency": b.get("material_efficiency"),
        "time_efficiency": b.get("time_efficiency"),
        "runs": b.get("runs"),
        "quantity": b.get("quantity"),
        "location_id": b.get("location_id"),
        "location_flag": b.get("location_flag"),
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


def _map_standing(cid, s):
    return {
        "character_id": cid,
        "from_id": s.get("from_id"),
        "from_type": s.get("from_type"),
        "standing": s.get("standing"),
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


# Structure (Upwell) name resolution — turns numeric asset location ids into names

def _resolve_structures(db, token, structure_ids) -> int:
    """
    Fetch + cache names for the given Upwell structure ids (shared esi_structures
    table). Skips ones with a fresh name or a recent failure so we don't re-hammer
    ESI, and records 403/404 so a structure we can't dock at backs off but can be
    retried later (possibly by a different character). Returns how many names were
    freshly resolved this run.
    """
    structure_ids = {s for s in structure_ids if s}
    if not structure_ids:
        return 0

    now = utcnow()
    existing = {
        s.structure_id: s
        for s in db.query(EsiStructure).filter(EsiStructure.structure_id.in_(structure_ids)).all()
    }
    resolved = 0
    for sid in structure_ids:
        cur = existing.get(sid)
        if cur and cur.updated_at:
            if cur.name and now - cur.updated_at < _STRUCTURE_NAME_TTL:
                continue  # fresh name on file
            if cur.error and now - cur.updated_at < _STRUCTURE_RETRY_TTL:
                continue  # recent failure — back off

        name = sys_id = type_id = error = None
        try:
            info = esi.fetch_structure(sid, token)
            name = info.get("name")
            sys_id = info.get("solar_system_id")
            type_id = info.get("type_id")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code == 403:
                error = "forbidden"
            elif code in (404, 422):
                error = "not_found"
            else:
                error = "error"
        except Exception:  # noqa: BLE001
            error = "error"

        row = {
            "structure_id": sid, "name": name, "solar_system_id": sys_id,
            "type_id": type_id, "error": error, "updated_at": now,
        }
        stmt = pg_insert(EsiStructure).values(row).on_conflict_do_update(
            index_elements=["structure_id"],
            set_={k: row[k] for k in ("name", "solar_system_id", "type_id", "error", "updated_at")},
        )
        db.execute(stmt)
        if name:
            resolved += 1
    db.commit()
    return resolved


def _asset_structure_ids(db, character_id) -> set:
    """Terminus Upwell-structure ids across a character's synced assets."""
    rows = (
        db.query(EsiAsset.item_id, EsiAsset.location_id, EsiAsset.location_type)
        .filter(EsiAsset.character_id == character_id).all()
    )
    _, by_kind = asset_location.terminus_ids(rows)
    return by_kind["structure"]


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
        if char.corporation_id:
            try:
                char.corporation_name = esi.fetch_corporation(char.corporation_id).get("name")
            except Exception:  # noqa: BLE001
                pass
        char.alliance_name = None
        if char.alliance_id:
            try:
                char.alliance_name = esi.fetch_alliance(char.alliance_id).get("name")
            except Exception:  # noqa: BLE001
                pass
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

    def _location():
        if not _has_scope(char, _LOCATION_SCOPE):
            return 0
        loc = esi.fetch_location(cid, token)
        char.location_system_id = loc.get("solar_system_id")
        if loc.get("station_id"):
            char.location_id, char.location_type = loc["station_id"], "station"
        elif loc.get("structure_id"):
            char.location_id, char.location_type = loc["structure_id"], "structure"
        else:
            char.location_id, char.location_type = None, "system"
        if _has_scope(char, _SHIP_SCOPE):
            try:
                ship = esi.fetch_ship(cid, token)
                char.ship_type_id, char.ship_name = ship.get("ship_type_id"), ship.get("ship_name")
            except Exception:  # noqa: BLE001
                pass
        if _has_scope(char, _ONLINE_SCOPE):
            try:
                on = esi.fetch_online(cid, token)
                char.online, char.last_login = on.get("online"), esi.parse_dt(on.get("last_login"))
            except Exception:  # noqa: BLE001
                pass
        db.commit()
        return 1

    def _implants():
        if not _has_scope(char, _IMPLANTS_SCOPE):
            return 0
        rows = [{"character_id": cid, "type_id": t} for t in esi.fetch_implants(cid, token)]
        _replace(db, EsiImplant, cid, rows)
        return len(rows)

    def _mining():
        # upsert (NOT replace) — ESI only returns ~30 days; keeping old rows lets the
        # journal's month/quarter/year reports build history beyond that window
        if not _has_scope(char, _MINING_SCOPE):
            return 0
        def _date(s):
            try:
                return datetime.date.fromisoformat(s) if s else None
            except (ValueError, TypeError):
                return None
        rows = [
            {
                "character_id": cid,
                "date": _date(m.get("date")),
                "type_id": m.get("type_id"),
                "solar_system_id": m.get("solar_system_id"),
                "quantity": m.get("quantity"),
            }
            for m in esi.fetch_mining(cid, token)
        ]
        rows = [r for r in rows if r["date"] and r["type_id"]]
        _upsert(db, EsiMiningLedger, rows,
                ["character_id", "date", "type_id", "solar_system_id"], ["quantity"])
        return len(rows)

    def _structures():
        # needs the read_structures scope — skip (no pointless 403s) until re-linked
        if not _has_scope(char, _STRUCTURE_SCOPE):
            return 0
        ids = set(_asset_structure_ids(db, cid))
        if char.location_type == "structure" and char.location_id:
            ids.add(char.location_id)  # also name the citadel the character is docked in
        return _resolve_structures(db, token, ids)

    def _wealth():
        prices = _market_prices()
        rows = db.query(EsiAsset.type_id, EsiAsset.quantity).filter(EsiAsset.character_id == cid).all()
        assets_value = sum(prices.get(tid, 0.0) * (qty or 0) for tid, qty in rows if tid)
        liquid = char.wallet_balance or 0.0
        char.assets_value = assets_value
        db.add(CharacterWealthSnapshot(
            character_id=cid, timestamp=utcnow(),
            liquid=liquid, assets_value=assets_value, total=liquid + assets_value,
        ))
        db.commit()
        return 1

    def _contracts():
        rows = [_map_contract(cid, c) for c in esi.fetch_contracts(cid, token)]
        _upsert(db, EsiContract, rows, ["character_id", "contract_id"],
                ["status", "date_accepted", "date_completed", "acceptor_id"])
        return len(rows)

    def _jobs():
        rows = [_map_job(cid, j) for j in esi.fetch_industry_jobs(cid, token)]
        _replace(db, EsiIndustryJob, cid, rows)
        return len(rows)

    def _standings():
        rows = [_map_standing(cid, s) for s in esi.fetch_standings(cid, token)]
        _replace(db, EsiStanding, cid, rows)
        return len(rows)

    def _blueprints():
        # needs the read_blueprints scope — no-op until the character re-links to grant it
        if not _has_scope(char, _BLUEPRINTS_SCOPE):
            return 0
        rows = [_map_blueprint(cid, b) for b in esi.fetch_blueprints(cid, token)]
        rows = [r for r in rows if r["item_id"]]
        _replace(db, EsiBlueprintCopy, cid, rows)
        return len(rows)

    step("affiliation", _affiliation)
    step("wallet", _wallet)
    step("skills", _skills)
    step("assets", _assets)
    step("location", _location)
    step("implants", _implants)
    step("mining", _mining)
    step("structures", _structures)
    step("contracts", _contracts)
    step("industry_jobs", _jobs)
    step("standings", _standings)
    step("blueprints", _blueprints)
    step("wealth", _wealth)

    char.last_sync_at = utcnow()
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
                logger.exception("esi sync for %s failed", char.character_id)
                summary["errors"].append(f"{char.character_id}: {exc}")
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
    result = sync_all_active()
    print(f"Synced {result['characters']} character(s); errors: {len(result['errors'])}")
