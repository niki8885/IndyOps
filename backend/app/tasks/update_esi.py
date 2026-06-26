import datetime
import logging
import time

import requests
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters import esi
from app.core import config
from app.core.database import (
    SessionLocal,
    LinkedCharacter,
    EsiWalletTransaction,
    EsiSkill,
    EsiAsset,
    EsiContract,
    EsiContractItem,
    EsiIndustryJob,
    EsiStanding,
    EsiStructure,
    EsiImplant,
    EsiMiningLedger,
    EsiBlueprintCopy,
    EsiMarketOrder,
    EsiPlanet,
    AgendaNotification,
    BankLedgerEntry,
    EsiWalletEntry,
    CharacterWealthSnapshot,
)
from app.core.database_eve import EveSessionLocal, EveType, EvePlanet
from app.core.timeutil import utcnow
from app.services import asset_location, currency, pi

logger = logging.getLogger(__name__)

_STRUCTURE_SCOPE = "esi-universe.read_structures.v1"
_LOCATION_SCOPE = "esi-location.read_location.v1"
_SHIP_SCOPE = "esi-location.read_ship_type.v1"
_ONLINE_SCOPE = "esi-location.read_online.v1"
_IMPLANTS_SCOPE = "esi-clones.read_implants.v1"
_MINING_SCOPE = "esi-industry.read_character_mining.v1"
_BLUEPRINTS_SCOPE = "esi-characters.read_blueprints.v1"
_MARKET_ORDERS_SCOPE = "esi-markets.read_character_orders.v1"
_CONTRACTS_SCOPE = "esi-contracts.read_character_contracts.v1"
_PLANETS_SCOPE = "esi-planets.manage_planets.v1"
_PI_FULL_PCT = 90.0                               # storage-full notification threshold
_PI_EXPIRY_WARN = datetime.timedelta(hours=24)    # "extractor stops soon" lead time

# Wallet-journal ref_types captured into EsiWalletEntry for the Tracking income
# ledgers: mission rewards (main + time bonus) and ratting income (bounty + ESS).
_INCOME_REF_TYPES = {
    "agent_mission_reward",
    "agent_mission_time_bonus_reward",
    "bounty_prizes",
    "ess_escrow_transfer",
}

# Bank corporation id (donations to it credit the in-app Aureus/Penny balance).
# Resolved once from the configured name via ESI and cached for the process.
_bank_corp_cache: dict = {"id": None}


def _bank_corp_id():
    """The bank corporation id — from config, else resolved by name (cached).
    Returns None (without caching) on a transient resolve failure, so a later sync
    retries."""
    if config.BANK_CORP_ID:
        return config.BANK_CORP_ID
    if _bank_corp_cache["id"]:
        return _bank_corp_cache["id"]
    try:
        corps = (esi.resolve_ids([config.BANK_CORP_NAME]) or {}).get("corporations") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("bank corp '%s' resolve failed: %s", config.BANK_CORP_NAME, exc)
        return None
    cid = corps[0].get("id") if corps else None
    if cid:
        _bank_corp_cache["id"] = cid
    return cid
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


def _map_market_order(cid, o, now):
    return {
        "character_id": cid,
        "order_id": o.get("order_id"),
        "type_id": o.get("type_id"),
        "region_id": o.get("region_id"),
        "location_id": o.get("location_id"),
        "is_buy_order": bool(o.get("is_buy_order")),
        "price": o.get("price"),
        "volume_total": o.get("volume_total"),
        "volume_remain": o.get("volume_remain"),
        "min_volume": o.get("min_volume"),
        "range": o.get("range"),
        "duration": o.get("duration"),
        "escrow": o.get("escrow"),
        "issued": esi.parse_dt(o.get("issued")),
        "synced_at": now,
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


def _blueprint_structure_ids(db, character_id) -> set:
    rows = (
        db.query(EsiBlueprintCopy.location_id)
        .filter(EsiBlueprintCopy.character_id == character_id).all()
    )
    return {loc for (loc,) in rows if asset_location.maybe_structure_id(loc)}


# Planetary interaction (PI) helpers

def _pi_eve_context(type_ids: set, planet_ids: set) -> tuple[dict, dict]:
    """One SDE read for a colony batch: ``({type_id: {volume, capacity}}, {planet_id:
    planet_name})``. Volume/capacity feed the storage calc; planet names label the
    notifications. Empty dicts if the SDE hasn't been synced with eve_planets yet."""
    eve = EveSessionLocal()
    try:
        type_info: dict = {}
        if type_ids:
            for tid, vol, cap in (eve.query(EveType.type_id, EveType.volume, EveType.capacity)
                                  .filter(EveType.type_id.in_(type_ids)).all()):
                type_info[tid] = {"volume": vol or 0.0, "capacity": cap or 0.0}
        names: dict = {}
        if planet_ids:
            for pid, pname in (eve.query(EvePlanet.planet_id, EvePlanet.planet_name)
                               .filter(EvePlanet.planet_id.in_(planet_ids)).all()):
                names[pid] = pname
        return type_info, names
    finally:
        eve.close()


def _pi_notify(db, char, label, summary, row, now) -> None:
    """Emit Agenda notifications on colony state changes, latched on the row so each
    fires once until the condition clears: extraction stopped, storage ≥90%, extractor
    stopping within 24h."""
    notes: list = []
    # extraction stopped (had an extractor, no head still running)
    if summary["has_extractor"] and not summary["extracting"]:
        if not row.notified_stopped:
            notes.append(("down", "PI: добыча остановилась",
                          f"{label}: экстрактор закончил цикл — планета простаивает."))
            row.notified_stopped = True
    else:
        row.notified_stopped = False

    # extractor stops within 24h (only while still running)
    exp = summary["extractor_expiry"]
    if summary["extracting"] and exp and (exp - now) <= _PI_EXPIRY_WARN:
        if not row.notified_expiring:
            hrs = max(0, int((exp - now).total_seconds() // 3600))
            notes.append(("info", "PI: экстрактор скоро встанет",
                          f"{label}: добыча остановится примерно через {hrs} ч."))
            row.notified_expiring = True
    elif summary["extracting"]:
        row.notified_expiring = False     # re-armed once a fresh (>24h) cycle starts

    # storage ≥ 90% full
    pct = pi.storage_pct(summary["storage_used"], summary["storage_capacity"])
    if pct is not None and pct >= _PI_FULL_PCT:
        if not row.notified_full:
            notes.append(("down", "PI: склад заполнен",
                          f"{label}: хранилище заполнено на {pct:.0f}% — добыча скоро встанет."))
            row.notified_full = True
    elif pct is not None:
        row.notified_full = False

    for severity, title, body in notes:
        db.add(AgendaNotification(user_id=char.user_id, alert_id=None,
                                  severity=severity, title=title, body=body))


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
        ids |= _blueprint_structure_ids(db, cid)  # blueprints can live outside synced assets
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

    def _contract_items():
        # Items for finished item-exchange contracts I issued OR accepted (sells feed
        # Contract-Profit, buys feed cost basis). Immutable once finished, so fetch once
        # (skip already-itemized) and cap per sync.
        if not _has_scope(char, _CONTRACTS_SCOPE):
            return 0
        done = [c for (c,) in db.query(EsiContract.contract_id).filter(
            EsiContract.character_id == cid, EsiContract.type == "item_exchange",
            EsiContract.status == "finished",
            or_(EsiContract.issuer_id == cid, EsiContract.acceptor_id == cid)).all()]
        have = {c for (c,) in db.query(EsiContractItem.contract_id).filter(
            EsiContractItem.character_id == cid).distinct()}
        todo = [c for c in done if c not in have][:50]
        n = 0
        for contract_id in todo:
            rows = [{"character_id": cid, "contract_id": contract_id, "record_id": it.get("record_id"),
                     "type_id": it.get("type_id"), "quantity": it.get("quantity"),
                     "is_included": it.get("is_included"), "is_singleton": it.get("is_singleton")}
                    for it in esi.fetch_contract_items(cid, contract_id, token) if it.get("record_id")]
            _upsert(db, EsiContractItem, rows, ["character_id", "contract_id", "record_id"], [])
            n += len(rows)
        return n

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

    def _orders():
        # needs the read_character_orders scope — no-op until the character re-links.
        # Active orders are a full snapshot, so replace the character's set.
        if not _has_scope(char, _MARKET_ORDERS_SCOPE):
            return 0
        now = utcnow()
        rows = [_map_market_order(cid, o, now) for o in esi.fetch_market_orders(cid, token)]
        rows = [r for r in rows if r["order_id"]]
        _replace(db, EsiMarketOrder, cid, rows)
        return len(rows)

    def _planets():
        # PI colonies: list endpoint + one detail call each, reduced to extraction +
        # storage state (services/pi.py). Upsert (not replace) so the notification
        # latches survive between syncs; prune colonies the character abandoned.
        if not _has_scope(char, _PLANETS_SCOPE):
            return 0
        colonies = esi.fetch_planets(cid, token) or []
        if not colonies:
            db.query(EsiPlanet).filter(EsiPlanet.character_id == cid).delete(synchronize_session=False)
            db.commit()
            return 0
        now = utcnow()
        # fetch every colony's layout, collecting the type/planet ids to resolve in one SDE read
        details: dict = {}
        type_ids: set = set()
        for col in colonies:
            pid = col.get("planet_id")
            try:
                d = esi.fetch_planet_detail(cid, pid, token)
            except Exception as exc:  # noqa: BLE001 — a single bad colony shouldn't fail the step
                logger.warning("esi sync %s/planet %s detail failed: %s", cid, pid, exc)
                d = {"pins": []}
            details[pid] = d
            for p in d.get("pins") or []:
                if p.get("type_id"):
                    type_ids.add(p["type_id"])
                for c in p.get("contents") or []:
                    if c.get("type_id"):
                        type_ids.add(c["type_id"])
        type_info, names = _pi_eve_context(type_ids, {c.get("planet_id") for c in colonies})

        seen: list = []
        for col in colonies:
            pid = col.get("planet_id")
            summary = pi.summarize_colony(details[pid].get("pins") or [], type_info, now)
            row = db.query(EsiPlanet).filter_by(character_id=cid, planet_id=pid).first()
            if row is None:
                row = EsiPlanet(character_id=cid, planet_id=pid,
                                notified_stopped=False, notified_full=False, notified_expiring=False)
                db.add(row)
            _pi_notify(db, char, names.get(pid) or f"Planet {pid}", summary, row, now)
            row.solar_system_id = col.get("solar_system_id")
            row.planet_type = col.get("planet_type")
            row.upgrade_level = col.get("upgrade_level")
            row.num_pins = col.get("num_pins")
            row.last_update = esi.parse_dt(col.get("last_update"))
            row.has_extractor = summary["has_extractor"]
            row.extracting = summary["extracting"]
            row.extractor_expiry = summary["extractor_expiry"]
            row.products = summary["products"]
            row.storage_used = summary["storage_used"]
            row.storage_capacity = summary["storage_capacity"]
            row.synced_at = now
            seen.append(pid)
        db.query(EsiPlanet).filter(
            EsiPlanet.character_id == cid, ~EsiPlanet.planet_id.in_(seen)
        ).delete(synchronize_session=False)
        db.commit()
        return len(colonies)

    # The wallet journal feeds both the bank-donation credit and the income ledger;
    # fetch it once per character and memoize so we don't paginate it twice.
    _journal: dict = {}

    def _get_journal():
        if "rows" not in _journal:
            _journal["rows"] = esi.fetch_wallet_journal(cid, token)
        return _journal["rows"]

    def _bank():
        # Credit the user's Aureus/Penny balance from ISK donated to the bank corp.
        # Idempotent on the journal entry id; only outgoing donations (amount<0) count.
        bank_corp = _bank_corp_id()
        if not bank_corp:
            return 0
        now = utcnow()
        rows = []
        for e in _get_journal():
            if e.get("ref_type") != "player_donation":
                continue
            if e.get("second_party_id") != bank_corp:
                continue
            amount = e.get("amount") or 0
            if amount >= 0:
                continue  # money leaving the donor's wallet is negative
            rows.append({
                "user_id": char.user_id,
                "character_id": cid,
                "ref_id": e.get("id"),
                "amount_penny": currency.isk_to_penny(abs(amount)),
                "amount_isk": abs(amount),
                "date": esi.parse_dt(e.get("date")),
                "description": (e.get("reason") or e.get("description") or "")[:255] or None,
                "created_at": now,
            })
        rows = [r for r in rows if r["ref_id"]]
        _upsert(db, BankLedgerEntry, rows, ["ref_id"], [])  # do-nothing on conflict
        return len(rows)

    def _income():
        # Capture mission/bounty/ESS income from the wallet journal into the income
        # ledger (Tracking → Mission / Ratting). Append-only, idempotent per ref_id.
        now = utcnow()
        rows = []
        for e in _get_journal():
            if e.get("ref_type") not in _INCOME_REF_TYPES:
                continue
            rows.append({
                "user_id": char.user_id,
                "character_id": cid,
                "ref_id": e.get("id"),
                "ref_type": e.get("ref_type"),
                "amount": e.get("amount"),
                "balance": e.get("balance"),
                "date": esi.parse_dt(e.get("date")),
                "first_party_id": e.get("first_party_id"),
                "second_party_id": e.get("second_party_id"),
                "description": (e.get("reason") or e.get("description") or "")[:255] or None,
                "created_at": now,
            })
        rows = [r for r in rows if r["ref_id"]]
        _upsert(db, EsiWalletEntry, rows, ["character_id", "ref_id"], [])  # do-nothing on conflict
        return len(rows)

    step("affiliation", _affiliation)
    step("wallet", _wallet)
    step("skills", _skills)
    step("assets", _assets)
    step("location", _location)
    step("implants", _implants)
    step("mining", _mining)
    step("contracts", _contracts)
    step("contract_items", _contract_items)   # after contracts: needs the finished set
    step("industry_jobs", _jobs)
    step("standings", _standings)
    step("blueprints", _blueprints)
    step("market_orders", _orders)
    step("planets", _planets)
    step("bank_donations", _bank)
    step("wallet_income", _income)   # mission/bounty/ESS income (shares the journal fetch)
    step("structures", _structures)  # after blueprints: resolves their location ids too
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
