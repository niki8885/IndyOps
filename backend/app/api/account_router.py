"""Tracking → Orders + the account dashboard (mounted at /api/v1/account).

The nav tab is called "Tracking", but /api/v1/tracking is already the Analysis
watch-list, so the order/dashboard endpoints live under /account instead. Everything
here is scoped to the current user's linked characters; the character/group selector
is driven by the ``scope`` argument (``all`` | ``char:<id>`` | ``group:<name>``).

Competitive pricing (Price Status / Difference) and the manual resync both hit ESI,
so they're button-triggered and rate-limited per user (see ``services/ratelimit``).
"""
import datetime
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.adapters import market, esi
from app.core.database import (
    get_db, UserDB, LinkedCharacter, CharacterSettings,
    EsiMarketOrder, EsiIndustryJob, EsiContract, EsiSkill, EsiStructure, BankLedgerEntry,
    EsiWalletEntry, ContractAnnotation, CourierRouteCache, LootAppraisal, EsiNameCache,
)
from app.core.database_eve import EveSessionLocal, EveStation, EveRegion
from app.core.security import get_current_user
from app.core.timeutil import utcnow
from app.repositories import eve as eve_repo
from app.services import orders as orders_svc, currency, skills, ratelimit, income, loot
# Reuse the SDE name resolvers + single-character sync kick from the Personal File router.
from app.api.characters_router import (
    _type_names, _station_names, _system_names, _structure_names, _kick_sync,
)

router = APIRouter()

_ORDERS_SCOPE = "esi-markets.read_character_orders.v1"
_WALLET_SCOPE = "esi-wallet.read_character_wallet.v1"
_SYNC_COOLDOWN_S = 60
_PRICE_COOLDOWN_S = 60
_LOOT_COOLDOWN_S = 5
_THE_FORGE = 10000002   # Jita's region — used for loot appraisal pricing

# Courier contract status → normalized state for the Deliverly tracker.
_COURIER_ACTIVE = {"in_progress"}
_COURIER_DONE = {"finished", "finished_issuer", "finished_contractor"}
_COURIER_FAILED = {"failed"}

# Active industry jobs still hold a slot in these states (mirrors services.skills).
_OCCUPYING = {"active", "ready", "paused"}
# Activity id → dashboard job bucket.
_JOB_BUCKETS = {1: "manufacturing", 9: "reactions", 11: "reactions",
                3: "research", 4: "research", 5: "copying", 8: "invention"}
_JOB_BUCKET_NAMES = ("manufacturing", "reactions", "research", "copying", "invention")
# Contracts considered "open" for the dashboard counter.
_OPEN_CONTRACT_STATUSES = {"outstanding", "in_progress"}


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _region_names(eve_db: Session, region_ids) -> dict:
    ids = {i for i in region_ids if i}
    if not ids:
        return {}
    rows = eve_db.query(EveRegion.region_id, EveRegion.region_name).filter(EveRegion.region_id.in_(ids)).all()
    return {rid: name for rid, name in rows}


# ── character scoping ────────────────────────────────────────────────────────

def _user_chars(db: Session, user: UserDB) -> list:
    return db.query(LinkedCharacter).filter(LinkedCharacter.user_id == user.id).all()


def _scoped_chars(db: Session, user: UserDB, scope: Optional[str]) -> list:
    """Resolve a ``scope`` string to the user's matching characters.

    ``all`` (default) → every linked character; ``char:<id>`` → one (matched on the
    LinkedCharacter PK or the EVE character_id); ``group:<name>`` → all characters
    whose Character-Settings group_name equals ``<name>``."""
    chars = _user_chars(db, user)
    if not scope or scope == "all":
        return chars
    if scope.startswith("char:"):
        try:
            cid = int(scope.split(":", 1)[1])
        except ValueError:
            return chars
        return [c for c in chars if c.id == cid or c.character_id == cid]
    if scope.startswith("group:"):
        gname = scope.split(":", 1)[1]
        settings = {
            s.character_id: s
            for s in db.query(CharacterSettings)
            .filter(CharacterSettings.character_id.in_([c.character_id for c in chars] or [-1])).all()
        }
        return [c for c in chars
                if settings.get(c.character_id) and settings[c.character_id].group_name == gname]
    return chars


# ── orders ───────────────────────────────────────────────────────────────────

def _enrich_orders(db: Session, eve_db: Session, chars: list) -> tuple:
    """Build name-enriched selling/buying row dicts for the given characters, plus
    the list of characters missing the orders scope (so the UI can prompt a re-link)."""
    cids = [c.character_id for c in chars]
    owner = {c.character_id: c.character_name for c in chars}
    orders = (
        db.query(EsiMarketOrder)
        .filter(EsiMarketOrder.character_id.in_(cids or [-1]))
        .all()
    )

    type_names = _type_names(eve_db, [o.type_id for o in orders])
    loc_ids = {o.location_id for o in orders if o.location_id}
    station_names = _station_names(eve_db, loc_ids)
    structure_names = _structure_names(db, loc_ids)
    region_names = _region_names(eve_db, {o.region_id for o in orders})

    # location → solar system (stations from SDE, structures from the ESI name cache)
    sys_by_loc: dict = {}
    station_ids = [i for i in loc_ids if i and i < 100_000_000]
    for sid, sysid in (eve_db.query(EveStation.station_id, EveStation.solar_system_id)
                       .filter(EveStation.station_id.in_(station_ids or [-1])).all()):
        sys_by_loc[sid] = sysid
    struct_ids = [i for i in loc_ids if i and i >= 100_000_000]
    for sid, sysid in (db.query(EsiStructure.structure_id, EsiStructure.solar_system_id)
                       .filter(EsiStructure.structure_id.in_(struct_ids or [-1])).all()):
        sys_by_loc[sid] = sysid
    system_names = _system_names(eve_db, set(sys_by_loc.values()))

    now = utcnow()
    selling, buying = [], []
    for o in orders:
        loc = o.location_id
        station = station_names.get(loc) or structure_names.get(loc) or (f"#{loc}" if loc else None)
        sysid = sys_by_loc.get(loc)
        flags = orders_svc.classify(
            {"issued": o.issued, "duration": o.duration,
             "volume_remain": o.volume_remain, "volume_total": o.volume_total}, now)
        row = {
            "order_id": o.order_id,
            "is_buy": bool(o.is_buy_order),
            "type_id": o.type_id,
            "type_name": type_names.get(o.type_id, {}).get("name") or f"#{o.type_id}",
            "price": o.price,
            "price_status": None,        # filled in by /orders/price-check
            "price_difference": None,
            "price_difference_pct": None,
            "volume_remain": o.volume_remain,
            "volume_total": o.volume_total,
            "total": (o.price or 0) * (o.volume_remain or 0),
            "owner": owner.get(o.character_id),
            "owner_id": o.character_id,
            "expires_at": flags["expires_at"],
            "expiring_soon": flags["expiring_soon"],
            "low_volume": flags["low_volume"],
            "station": station,
            "system": system_names.get(sysid) if sysid else None,
            "region": region_names.get(o.region_id) if o.region_id else None,
            "min_volume": o.min_volume,
            "range": o.range,
            "escrow": o.escrow,
        }
        (buying if row["is_buy"] else selling).append(row)

    needs_scope = [c.character_name for c in chars if _ORDERS_SCOPE not in (c.scopes or "").split()]
    return selling, buying, needs_scope


@router.get("/orders", summary="Active market orders for the selected characters")
async def get_orders(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    chars = _scoped_chars(db, current_user, scope)
    selling, buying, needs_scope = _enrich_orders(db, eve_db, chars)
    summary = orders_svc.summarize(selling, buying)

    # market-order slot capacity (Trade/Retail/Wholesale/Tycoon) across the selection
    skl = _group_by_char(db.query(EsiSkill)
                         .filter(EsiSkill.character_id.in_([c.character_id for c in chars] or [-1])).all())
    max_slots = sum(
        skills.market_order_capacity({s.skill_id: s.trained_level for s in skl.get(c.character_id, [])})
        for c in chars
    )
    summary["order_slots"] = {"used": len(selling) + len(buying), "max": max_slots}

    return {
        "selling": selling,
        "buying": buying,
        "summary": summary,
        "needs_scope": needs_scope,
        "scope": scope,
    }


class ScopeBody(BaseModel):
    scope: str = "all"


@router.post("/orders/price-check", summary="Live competitive price status (rate-limited)")
async def price_check(
    body: ScopeBody,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ratelimit.check(current_user.id, "price_check", _PRICE_COOLDOWN_S)
    except ratelimit.CooldownError as e:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Competitor prices were just checked — wait {e.retry_after}s."},
            headers={"Retry-After": str(e.retry_after)},
        )

    chars = _scoped_chars(db, current_user, body.scope)
    cids = [c.character_id for c in chars]
    orders = db.query(EsiMarketOrder).filter(EsiMarketOrder.character_id.in_(cids or [-1])).all()

    book_cache: dict = {}
    prices: dict = {}
    for o in orders:
        if not o.region_id or not o.type_id or o.price is None:
            continue
        key = (o.region_id, o.type_id)
        book = book_cache.get(key)
        if book is None:
            book = market.esi_region_orders(o.region_id, o.type_id)  # cached 3 min in the adapter
            book_cache[key] = book
        competing = [
            b.get("price") for b in book
            if bool(b.get("is_buy_order")) == bool(o.is_buy_order) and b.get("order_id") != o.order_id
        ]
        prices[str(o.order_id)] = orders_svc.price_compare(o.price, bool(o.is_buy_order), competing)
    return {"prices": prices, "checked": len(prices)}


@router.post("/sync", summary="Trigger an ESI resync of the selected characters (rate-limited)")
async def sync_orders(
    body: ScopeBody,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ratelimit.check(current_user.id, "sync", _SYNC_COOLDOWN_S)
    except ratelimit.CooldownError as e:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Already syncing — wait {e.retry_after}s before refreshing again."},
            headers={"Retry-After": str(e.retry_after)},
        )
    chars = [c for c in _scoped_chars(db, current_user, body.scope)
             if c.is_active and c.status == "active"]
    for c in chars:
        _kick_sync(c.character_id)
    return {"status": "started", "characters": len(chars)}


# ── dashboard ────────────────────────────────────────────────────────────────

def _group_by_char(rows, key="character_id"):
    out: dict = {}
    for r in rows:
        out.setdefault(getattr(r, key), []).append(r)
    return out


@router.get("/dashboard", summary="Per-character + overall account metrics (Agenda)")
async def dashboard(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = _user_chars(db, current_user)
    cids = [c.character_id for c in chars]

    orders_by = _group_by_char(db.query(EsiMarketOrder).filter(EsiMarketOrder.character_id.in_(cids or [-1])).all())
    jobs_by = _group_by_char(db.query(EsiIndustryJob).filter(EsiIndustryJob.character_id.in_(cids or [-1])).all())
    skills_by = _group_by_char(db.query(EsiSkill).filter(EsiSkill.character_id.in_(cids or [-1])).all())
    contracts_by = _group_by_char(
        db.query(EsiContract.character_id, EsiContract.status)
        .filter(EsiContract.character_id.in_(cids or [-1])).all())

    per_char = []
    totals = {"wallet": 0.0, "sell_isk": 0.0, "buy_isk": 0.0, "escrow": 0.0,
              "contracts": 0, "jobs": {b: 0 for b in _JOB_BUCKET_NAMES},
              "slots": {cat: {"used": 0, "max": 0} for cat in ("manufacturing", "science", "reaction")}}

    for c in chars:
        cid = c.character_id
        c_orders = orders_by.get(cid, [])
        sell_isk = sum((o.price or 0) * (o.volume_remain or 0) for o in c_orders if not o.is_buy_order)
        buy_isk = sum((o.price or 0) * (o.volume_remain or 0) for o in c_orders if o.is_buy_order)
        escrow = sum(o.escrow or 0 for o in c_orders if o.is_buy_order)

        c_jobs = jobs_by.get(cid, [])
        skill_levels = {s.skill_id: s.trained_level for s in skills_by.get(cid, [])}
        slots = skills.job_slot_usage([(j.activity_id, j.status) for j in c_jobs], skill_levels)
        job_counts = {b: 0 for b in _JOB_BUCKET_NAMES}
        for j in c_jobs:
            if (j.status or "").lower() in _OCCUPYING:
                bucket = _JOB_BUCKETS.get(j.activity_id)
                if bucket:
                    job_counts[bucket] += 1

        contracts = sum(1 for (_cid, status) in contracts_by.get(cid, [])
                        if (status or "").lower() in _OPEN_CONTRACT_STATUSES)

        per_char.append({
            "character_id": cid, "id": c.id, "name": c.character_name,
            "portrait": f"https://images.evetech.net/characters/{cid}/portrait?size=64",
            "is_active": c.is_active, "status": c.status,
            "wallet": c.wallet_balance, "sell_isk": sell_isk, "buy_isk": buy_isk, "escrow": escrow,
            "contracts": contracts, "jobs": job_counts, "slots": slots,
            "needs_scope": _ORDERS_SCOPE not in (c.scopes or "").split(),
        })

        totals["wallet"] += c.wallet_balance or 0
        totals["sell_isk"] += sell_isk
        totals["buy_isk"] += buy_isk
        totals["escrow"] += escrow
        totals["contracts"] += contracts
        for b in _JOB_BUCKET_NAMES:
            totals["jobs"][b] += job_counts[b]
        for cat in totals["slots"]:
            totals["slots"][cat]["used"] += slots[cat]["used"]
            totals["slots"][cat]["max"] += slots[cat]["max"]

    total_penny = db.query(func.coalesce(func.sum(BankLedgerEntry.amount_penny), 0)).filter(
        BankLedgerEntry.user_id == current_user.id).scalar() or 0

    return {
        "characters": per_char,
        "totals": totals,
        "currency": currency.penny_to_coins(int(total_penny)),
    }


@router.get("/currency", summary="Bank currency balance + deposit history (Aureus/Penny)")
async def get_currency(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(BankLedgerEntry)
        .filter(BankLedgerEntry.user_id == current_user.id)
        .order_by(BankLedgerEntry.date.desc())
        .limit(200)
        .all()
    )
    total_penny = sum(r.amount_penny or 0 for r in rows)
    return {
        "balance": currency.penny_to_coins(int(total_penny)),
        "deposits": [
            {
                "ref_id": r.ref_id, "character_id": r.character_id,
                "amount_isk": r.amount_isk, "coins": currency.penny_to_coins(int(r.amount_penny or 0)),
                "date": r.date, "description": r.description,
            }
            for r in rows
        ],
    }


# ── shared helpers for the income trackers ─────────────────────────────────────

def _parse_date(value: Optional[str], end: bool = False) -> Optional[datetime.datetime]:
    """ISO ``YYYY-MM-DD`` → naive UTC datetime (start or end of day). None if blank/bad."""
    if not value:
        return None
    try:
        d = datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return datetime.datetime.combine(d, datetime.time.max if end else datetime.time.min)


def _resolve_names(db: Session, ids) -> dict:
    """``{id: name}`` for EVE ids, served from the EsiNameCache, resolving misses via
    ESI /universe/names/ and caching them. Best-effort: a failed batch leaves names blank."""
    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    cached = {r.id: r.name for r in db.query(EsiNameCache).filter(EsiNameCache.id.in_(ids)).all()}
    missing = [i for i in ids if i not in cached]
    if missing:
        try:
            resolved = esi.resolve_names(missing)
        except Exception:  # noqa: BLE001 — names are cosmetic; never fail the request
            resolved = {}
        now = utcnow()
        for i, info in resolved.items():
            row = {"id": i, "name": info.get("name"), "category": info.get("category"), "updated_at": now}
            db.execute(pg_insert(EsiNameCache).values(row).on_conflict_do_update(
                index_elements=["id"], set_={k: row[k] for k in ("name", "category", "updated_at")}))
            cached[i] = info.get("name")
        db.commit()
    return cached


def _systems_for_locations(eve_db: Session, db: Session, loc_ids) -> dict:
    """``{location_id: solar_system_id}`` — stations from the SDE, structures from the
    ESI structure-name cache (mirrors orders enrichment)."""
    sys_by_loc: dict = {}
    station_ids = [i for i in loc_ids if i and i < 100_000_000]
    for sid, sysid in (eve_db.query(EveStation.station_id, EveStation.solar_system_id)
                       .filter(EveStation.station_id.in_(station_ids or [-1])).all()):
        sys_by_loc[sid] = sysid
    struct_ids = [i for i in loc_ids if i and i >= 100_000_000]
    for sid, sysid in (db.query(EsiStructure.structure_id, EsiStructure.solar_system_id)
                       .filter(EsiStructure.structure_id.in_(struct_ids or [-1])).all()):
        sys_by_loc[sid] = sysid
    return sys_by_loc


def _courier_state(status: Optional[str]) -> str:
    s = (status or "").lower()
    if s in _COURIER_ACTIVE:
        return "active"
    if s in _COURIER_DONE:
        return "completed"
    if s in _COURIER_FAILED:
        return "failed"
    return "other"


def _courier_jumps(db: Session, eve_db: Session, contracts) -> dict:
    """``{contract_id: jumps}`` for the given courier contracts, using CourierRouteCache
    and computing (then caching) any missing route via ESI. Routes are static so the ESI
    call happens at most once per (start, end) location pair."""
    pairs = {(c.start_location_id, c.end_location_id) for c in contracts
             if c.start_location_id and c.end_location_id}
    if not pairs:
        return {}
    starts = {p[0] for p in pairs}
    ends = {p[1] for p in pairs}
    jumps_by_pair = {
        (r.start_location_id, r.end_location_id): r.jumps
        for r in db.query(CourierRouteCache).filter(
            CourierRouteCache.start_location_id.in_(starts),
            CourierRouteCache.end_location_id.in_(ends),
        ).all()
        if (r.start_location_id, r.end_location_id) in pairs
    }
    missing = [p for p in pairs if p not in jumps_by_pair]
    if missing:
        sys_by_loc = _systems_for_locations(eve_db, db, {x for p in missing for x in p})
        now = utcnow()
        for (s_loc, e_loc) in missing:
            s_sys, e_sys = sys_by_loc.get(s_loc), sys_by_loc.get(e_loc)
            jumps = None
            if s_sys and e_sys:
                if s_sys == e_sys:
                    jumps = 0
                else:
                    route = market.esi_route(s_sys, e_sys)
                    jumps = (len(route) - 1) if route else None
            row = {"start_location_id": s_loc, "end_location_id": e_loc,
                   "start_system_id": s_sys, "end_system_id": e_sys,
                   "jumps": jumps, "computed_at": now}
            db.execute(pg_insert(CourierRouteCache).values(row).on_conflict_do_update(
                index_elements=["start_location_id", "end_location_id"],
                set_={k: row[k] for k in ("start_system_id", "end_system_id", "jumps", "computed_at")}))
            jumps_by_pair[(s_loc, e_loc)] = jumps
        db.commit()
    return {c.contract_id: jumps_by_pair.get((c.start_location_id, c.end_location_id))
            for c in contracts}


def _split_tags(value: Optional[str]) -> list:
    return [t.strip() for t in (value or "").split(",") if t.strip()]


# ── Deliverly (courier delivery tracker) ───────────────────────────────────────

@router.get("/deliveries", summary="Courier deliveries the selected characters hauled (Deliverly)")
async def get_deliveries(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    status: str = Query("all", description="all | active | completed"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    chars = _scoped_chars(db, current_user, scope)
    cids = [c.character_id for c in chars]
    # Courier contracts this user actually hauled = where they are the acceptor.
    rows = (
        db.query(EsiContract)
        .filter(EsiContract.type == "courier", EsiContract.acceptor_id.in_(cids or [-1]))
        .all()
    )
    # de-dup: the same contract can be synced under several of the user's characters
    rows = list({c.contract_id: c for c in rows}.values())

    start_dt, end_dt = _parse_date(start), _parse_date(end, end=True)

    def effective_date(c):
        return c.date_completed or c.date_accepted or c.date_issued

    filtered = []
    for c in rows:
        state = _courier_state(c.status)
        if status == "active" and state != "active":
            continue
        if status == "completed" and state not in ("completed", "failed"):
            continue
        ed = effective_date(c)
        if start_dt and ed and ed < start_dt:
            continue
        if end_dt and ed and ed > end_dt:
            continue
        filtered.append(c)

    jumps_by_contract = _courier_jumps(db, eve_db, filtered)

    loc_ids = {c.start_location_id for c in filtered} | {c.end_location_id for c in filtered}
    station_names = _station_names(eve_db, loc_ids)
    structure_names = _structure_names(db, loc_ids)
    sys_by_loc = _systems_for_locations(eve_db, db, loc_ids)
    system_names = _system_names(eve_db, set(sys_by_loc.values()))
    name_by_id = _resolve_names(db, {c.issuer_id for c in filtered})

    ann = {
        a.contract_id: a
        for a in db.query(ContractAnnotation).filter(
            ContractAnnotation.user_id == current_user.id,
            ContractAnnotation.contract_id.in_([c.contract_id for c in filtered] or [-1]),
        ).all()
    }

    def loc_name(loc):
        return station_names.get(loc) or structure_names.get(loc) or (f"#{loc}" if loc else None)

    def loc_system(loc):
        return system_names.get(sys_by_loc.get(loc))

    out = []
    for c in filtered:
        state = _courier_state(c.status)
        jumps = jumps_by_contract.get(c.contract_id)
        duration = None
        if c.date_completed and c.date_accepted:
            duration = (c.date_completed - c.date_accepted).total_seconds()
        a = ann.get(c.contract_id)
        out.append({
            "contract_id": c.contract_id,
            "title": c.title,
            "state": state,
            "status": c.status,
            "reward": c.reward,
            "collateral": c.collateral,
            "volume": c.volume,
            "jumps": jumps,
            "reward_per_jump": (c.reward / jumps) if (c.reward and jumps) else None,
            "start_location": loc_name(c.start_location_id),
            "start_system": loc_system(c.start_location_id),
            "end_location": loc_name(c.end_location_id),
            "end_system": loc_system(c.end_location_id),
            "issuer": name_by_id.get(c.issuer_id) or (f"#{c.issuer_id}" if c.issuer_id else None),
            "date_issued": c.date_issued,
            "date_accepted": c.date_accepted,
            "date_completed": c.date_completed,
            "date_expired": c.date_expired,
            "duration_seconds": duration,
            "tags": _split_tags(a.tags) if a else [],
            "note": a.note if a else None,
        })

    # summary (completed contracts drive the income totals)
    done = [r for r in out if r["state"] in ("completed", "failed")]
    active = [r for r in out if r["state"] == "active"]
    durations = [r["duration_seconds"] for r in done if r["duration_seconds"] is not None]
    jump_vals = [r["jumps"] for r in done if r["jumps"] is not None]
    reward_total = sum(r["reward"] or 0 for r in done)
    summary = {
        "active_count": len(active),
        "completed_count": len(done),
        "reward_total": round(reward_total, 2),
        "collateral_total": round(sum(r["collateral"] or 0 for r in done), 2),
        "volume_total": round(sum(r["volume"] or 0 for r in done), 2),
        "jumps_total": sum(jump_vals),
        "avg_duration_seconds": (sum(durations) / len(durations)) if durations else None,
        "reward_per_jump": (reward_total / sum(jump_vals)) if jump_vals else None,
        "active_collateral": round(sum(r["collateral"] or 0 for r in active), 2),
    }

    needs_scope = [c.character_name for c in chars if _WALLET_SCOPE not in (c.scopes or "").split()]
    return {"deliveries": out, "summary": summary, "needs_scope": needs_scope, "scope": scope}


class AnnotationBody(BaseModel):
    tags: Optional[str] = None
    note: Optional[str] = None


@router.put("/deliveries/{contract_id}/annotation", summary="Set tags/note on a delivery")
async def set_delivery_annotation(
    contract_id: int,
    body: AnnotationBody,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tags = ", ".join(_split_tags(body.tags))[:255] or None
    row = {
        "user_id": current_user.id, "contract_id": contract_id,
        "tags": tags, "note": (body.note or None), "updated_at": utcnow(),
    }
    db.execute(pg_insert(ContractAnnotation).values(row).on_conflict_do_update(
        index_elements=["user_id", "contract_id"],
        set_={k: row[k] for k in ("tags", "note", "updated_at")}))
    db.commit()
    return {"contract_id": contract_id, "tags": _split_tags(tags), "note": body.note}


@router.get("/deliveries/tags", summary="Distinct delivery tags for the current user")
async def get_delivery_tags(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(ContractAnnotation.tags).filter(
        ContractAnnotation.user_id == current_user.id, ContractAnnotation.tags.isnot(None)).all()
    tags = sorted({t for (val,) in rows for t in _split_tags(val)}, key=str.lower)
    return {"tags": tags}


# ── Mission rewards ────────────────────────────────────────────────────────────

@router.get("/missions", summary="Mission reward income (main + time bonus)")
async def get_missions(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = _scoped_chars(db, current_user, scope)
    cids = [c.character_id for c in chars]
    q = db.query(EsiWalletEntry).filter(
        EsiWalletEntry.character_id.in_(cids or [-1]),
        EsiWalletEntry.ref_type.in_(income.MISSION_REF_TYPES),
    )
    start_dt, end_dt = _parse_date(start), _parse_date(end, end=True)
    if start_dt:
        q = q.filter(EsiWalletEntry.date >= start_dt)
    if end_dt:
        q = q.filter(EsiWalletEntry.date <= end_dt)
    rows = q.all()
    entries = [{"ref_type": r.ref_type, "amount": r.amount, "date": r.date,
                "first_party_id": r.first_party_id} for r in rows]
    summary = income.summarize_missions(entries)

    names = _resolve_names(db, [a["agent_id"] for a in summary["by_agent"]])
    for a in summary["by_agent"]:
        a["agent_name"] = names.get(a["agent_id"]) or (
            f"Agent #{a['agent_id']}" if a["agent_id"] else "Unknown")

    needs_scope = [c.character_name for c in chars if _WALLET_SCOPE not in (c.scopes or "").split()]
    return {"summary": summary, "needs_scope": needs_scope, "scope": scope}


# ── Ratting (bounty + ESS + loot) ──────────────────────────────────────────────

def _scoped_loot_query(db, user, chars, scope, start_dt, end_dt):
    q = db.query(LootAppraisal).filter(LootAppraisal.user_id == user.id)
    if scope and scope != "all":
        q = q.filter(LootAppraisal.character_id.in_([c.character_id for c in chars] or [-1]))
    if start_dt:
        q = q.filter(LootAppraisal.date >= start_dt)
    if end_dt:
        q = q.filter(LootAppraisal.date <= end_dt)
    return q


@router.get("/ratting", summary="Ratting income: bounty + ESS + saved loot value")
async def get_ratting(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = _scoped_chars(db, current_user, scope)
    cids = [c.character_id for c in chars]
    start_dt, end_dt = _parse_date(start), _parse_date(end, end=True)

    q = db.query(EsiWalletEntry).filter(
        EsiWalletEntry.character_id.in_(cids or [-1]),
        EsiWalletEntry.ref_type.in_(income.RATTING_REF_TYPES),
    )
    if start_dt:
        q = q.filter(EsiWalletEntry.date >= start_dt)
    if end_dt:
        q = q.filter(EsiWalletEntry.date <= end_dt)
    wallet_rows = [{"ref_type": r.ref_type, "amount": r.amount, "date": r.date} for r in q.all()]

    loot_rows = [{"value_isk": r.value_isk, "date": r.date}
                 for r in _scoped_loot_query(db, current_user, chars, scope, start_dt, end_dt).all()]

    summary = income.summarize_ratting(wallet_rows, loot_rows)
    needs_scope = [c.character_name for c in chars if _WALLET_SCOPE not in (c.scopes or "").split()]
    return {"summary": summary, "needs_scope": needs_scope, "scope": scope}


def _appraise_text(eve_db: Session, text: str, pricing: str) -> dict:
    """Parse a loot paste, resolve names → type_ids, price at Jita and total it."""
    parsed = loot.parse_lines(text)
    warnings: list = []
    items: list = []
    for name, qty, warns in parsed:
        warnings.extend(warns)
        if not name:
            continue
        items.append({"name": name, "qty": qty})

    resolved = eve_repo.types_by_name(eve_db, [it["name"] for it in items])
    for it in items:
        info = resolved.get(it["name"].strip().lower())
        it["type_id"] = info["type_id"] if info else None

    type_ids = [it["type_id"] for it in items if it["type_id"]]
    agg = market.fuzzwork_aggregates_or_empty(_THE_FORGE, type_ids)

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    prices = {}
    for tid in type_ids:
        d = agg.get(str(tid)) or {}
        prices[tid] = {"sell": _num((d.get("sell") or {}).get("min")),
                       "buy": _num((d.get("buy") or {}).get("max"))}

    result = loot.appraise(items, prices, pricing)
    result["warnings"] = warnings
    return result


class LootAppraiseBody(BaseModel):
    text: str
    pricing: str = "jita_sell"


@router.post("/loot/appraise", summary="Parse + value a loot paste at Jita (no save)")
async def appraise_loot(
    body: LootAppraiseBody,
    current_user: UserDB = Depends(get_current_user),
    eve_db: Session = Depends(_get_eve_db),
):
    try:
        ratelimit.check(current_user.id, "loot_appraise", _LOOT_COOLDOWN_S)
    except ratelimit.CooldownError as e:
        return JSONResponse(status_code=429,
                            content={"detail": f"Appraising too fast — wait {e.retry_after}s."},
                            headers={"Retry-After": str(e.retry_after)})
    return _appraise_text(eve_db, body.text, body.pricing)


class LootSaveBody(BaseModel):
    text: str
    pricing: str = "jita_sell"
    title: Optional[str] = None
    tags: Optional[str] = None
    character_id: Optional[int] = None
    date: Optional[str] = None


@router.post("/loot", summary="Save a valued loot paste (Ratting tracker)")
async def save_loot(
    body: LootSaveBody,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    result = _appraise_text(eve_db, body.text, body.pricing)
    when = _parse_date(body.date) or utcnow()
    row = LootAppraisal(
        user_id=current_user.id,
        character_id=body.character_id,
        date=when,
        title=(body.title or None),
        tags=(", ".join(_split_tags(body.tags))[:255] or None),
        raw_text=body.text,
        pricing=body.pricing,
        value_isk=result["total_value"],
        items_json=json.dumps(result["items"]),
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "value_isk": row.value_isk, "date": row.date,
            "unpriced": result["unpriced"], "warnings": result["warnings"]}


@router.get("/loot", summary="Saved loot appraisals")
async def list_loot(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = _scoped_chars(db, current_user, scope)
    start_dt, end_dt = _parse_date(start), _parse_date(end, end=True)
    rows = (_scoped_loot_query(db, current_user, chars, scope, start_dt, end_dt)
            .order_by(LootAppraisal.date.desc()).limit(500).all())
    char_name = {c.character_id: c.character_name for c in _user_chars(db, current_user)}
    return {
        "loot": [
            {
                "id": r.id, "date": r.date, "title": r.title,
                "tags": _split_tags(r.tags), "value_isk": r.value_isk, "pricing": r.pricing,
                "character_id": r.character_id, "character_name": char_name.get(r.character_id),
            }
            for r in rows
        ],
    }


@router.delete("/loot/{loot_id}", summary="Delete a saved loot appraisal", status_code=204)
async def delete_loot(
    loot_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(LootAppraisal).filter(
        LootAppraisal.id == loot_id, LootAppraisal.user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Loot appraisal not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/loot/tags", summary="Distinct loot tags for the current user")
async def get_loot_tags(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(LootAppraisal.tags).filter(
        LootAppraisal.user_id == current_user.id, LootAppraisal.tags.isnot(None)).all()
    tags = sorted({t for (val,) in rows for t in _split_tags(val)}, key=str.lower)
    return {"tags": tags}
