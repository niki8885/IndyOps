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
import math
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
    EsiMarketOrder, EsiIndustryJob, EsiContract, EsiContractItem, EsiSkill, EsiStructure,
    BankLedgerEntry, EsiWalletEntry, EsiWalletTransaction, EsiBlueprintCopy, ContractAnnotation,
    CourierRouteCache, LootAppraisal, EsiNameCache, EsiMiningLedger, InventoryItem,
    JobCostOverride, TrackingExclusion, EsiPlanet, CorpTrackingPref,
)
from app.core.database_eve import (
    EveSessionLocal, EveStation, EveRegion, EvePlanet, EveSolarSystem, EveType,
)
from app.services import pi as pi_svc
from app.core.security import get_current_user
from app.core.timeutil import utcnow
from app.repositories import eve as eve_repo
from app.services import (
    orders as orders_svc, currency, skills, ratelimit, income, loot, trade_profits,
    industry_ledger,
)
# Reuse the SDE name resolvers + single-character sync kick from the Personal File router,
# plus the mining-ledger valuation stack (refine → Jita) that powers the per-character
# mining journal — the Tracking → Mining tab is the same report across a scope.
from app.api.characters_router import (
    _type_names, _station_names, _system_names, _structure_names, _kick_sync,
    _mining_value, _ledger_entries, _settings_for,
)

router = APIRouter()

_ORDERS_SCOPE = "esi-markets.read_character_orders.v1"
_WALLET_SCOPE = "esi-wallet.read_character_wallet.v1"
_MINING_SCOPE = "esi-industry.read_character_mining.v1"
_THE_FORGE_REGION = 10000002  # Jita — for allocating a contract-buy price across its items
# ESI industry-job activity_id → (SDE activity for the BOM lookup, display name, whether the
# output is a sellable lot that feeds Manufacturing Profit). Manufacturing applies blueprint
# ME; reactions/invention don't. Copying/research/invention show in the jobs table only.
_ACT_META = {
    1:  (1,  "Manufacturing", True),
    3:  (3,  "TE Research",   False),
    4:  (4,  "ME Research",   False),
    5:  (5,  "Copying",       False),
    8:  (8,  "Invention",     False),
    9:  (11, "Reactions",     True),
    11: (11, "Reactions",     True),
}
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


def _untracked_corp_ids(db: Session, user: UserDB) -> set:
    """Corporations the user has explicitly toggled OFF (``CorpTrackingPref.tracked=False``).
    Absence of a row = tracked, so this returns only the opted-out corp ids."""
    return {p.corporation_id for p in db.query(CorpTrackingPref)
            .filter(CorpTrackingPref.user_id == user.id, CorpTrackingPref.tracked.is_(False)).all()}


def _scoped_chars(db: Session, user: UserDB, scope: Optional[str]) -> list:
    """Resolve a ``scope`` string to the user's matching characters.

    ``all`` (default) → every linked character, MINUS those whose corporation the user has
    toggled off in ``CorpTrackingPref`` (chars with no corp stay); ``char:<id>`` → one
    (matched on the LinkedCharacter PK or the EVE character_id); ``group:<name>`` → all
    characters whose Character-Settings group_name equals ``<name>``; ``corp:<corp_id>`` →
    all characters in that EVE corporation. Always filtered to the user's own characters —
    a corp scope never reaches into other users' data."""
    chars = _user_chars(db, user)
    if not scope or scope == "all":
        untracked = _untracked_corp_ids(db, user)
        return [c for c in chars if c.corporation_id not in untracked] if untracked else chars
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
    if scope.startswith("corp:"):
        try:
            corp_id = int(scope.split(":", 1)[1])
        except ValueError:
            return chars
        return [c for c in chars if c.corporation_id == corp_id]
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


def _parse_day(value: Optional[str]) -> Optional[datetime.date]:
    """ISO ``YYYY-MM-DD`` → ``date`` (the mining ledger is keyed by date, not datetime).
    None if blank/bad."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


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


# ── Mining (mined ore → refined Jita value) ────────────────────────────────────

# EVE released 2003-05-06; a safe lower bound for "all of the accumulated ledger".
_LEDGER_EPOCH = datetime.date(2003, 5, 6)


def _mining_summary(db: Session, eve_db: Session, chars: list,
                    start_d: datetime.date, end_d: datetime.date,
                    basis_override: Optional[str], limit: int) -> tuple:
    """The Tracking → Mining payload: value each character's mined ore (refine → Jita,
    using *that* character's own reprocessing skills + journal settings), aggregate
    across the scope by ore type, and attach a per-day ISK series plus the raw ledger
    (date × ore × system). Returns ``(summary, entries)``."""
    cids = [c.character_id for c in chars]

    # One grouped pass — date × character × ore type → summed quantity. Drives both the
    # per-character valuation (own skills) and the per-day series in a single query.
    grouped = (
        db.query(EsiMiningLedger.date, EsiMiningLedger.character_id,
                 EsiMiningLedger.type_id, func.sum(EsiMiningLedger.quantity))
        .filter(EsiMiningLedger.character_id.in_(cids or [-1]),
                EsiMiningLedger.date >= start_d, EsiMiningLedger.date <= end_d)
        .group_by(EsiMiningLedger.date, EsiMiningLedger.character_id, EsiMiningLedger.type_id)
        .all()
    )

    qty_by_char: dict = {}
    for d, cid, tid, q in grouped:
        inner = qty_by_char.setdefault(cid, {})
        inner[tid] = inner.get(tid, 0) + int(q or 0)

    items_by_type: dict = {}
    unit_value: dict = {}     # (character_id, type_id) → refined ISK per mined unit
    for c in chars:
        per_type = qty_by_char.get(c.character_id)
        if not per_type:
            continue
        s = _settings_for(db, c.character_id)
        base_yield = s.refine_base_yield if s else 0.50
        use_basis = basis_override or (s.price_basis if s else "sell")
        levels = {sk.skill_id: (sk.trained_level or 0)
                  for sk in db.query(EsiSkill).filter(EsiSkill.character_id == c.character_id).all()}
        valued = _mining_value(eve_db, per_type, use_basis, base_yield, levels)
        for it in valued["items"]:
            agg = items_by_type.setdefault(it["type_id"], {
                "type_id": it["type_id"], "name": it["name"],
                "category": it["category"], "qty": 0, "value": 0.0})
            agg["qty"] += it["qty"]
            agg["value"] += it["value"]
            if it["qty"]:
                unit_value[(c.character_id, it["type_id"])] = it["value"] / it["qty"]

    items = [{**it, "value": round(it["value"], 2)} for it in items_by_type.values()]

    # per-day ISK: value each day's mined qty at its own character's unit value
    daily = [{"date": d.isoformat(), "value": int(q or 0) * unit_value.get((cid, tid), 0.0),
              "quantity": int(q or 0)} for d, cid, tid, q in grouped]

    summary = income.summarize_mining(items, daily)

    # raw ledger rows (newest first) with per-row refined value
    entries = _ledger_entries(db, eve_db, cids, start_d, end_d, limit)
    for e in entries:
        e["value"] = round(e["quantity"] * unit_value.get((e["character_id"], e["type_id"]), 0.0), 2)
    return summary, entries


@router.get("/mining", summary="Mining income: mined ore refined → Jita value, by category/type/day")
async def get_mining(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    basis: Optional[str] = Query(None, pattern="^(buy|sell|split)$",
                                 description="Jita price basis (defaults to each char's setting)"),
    limit: int = Query(500, ge=1, le=2000),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    chars = _scoped_chars(db, current_user, scope)
    start_d = _parse_day(start) or _LEDGER_EPOCH
    end_d = _parse_day(end) or utcnow().date()
    summary, entries = _mining_summary(db, eve_db, chars, start_d, end_d, basis, limit)
    needs_scope = [c.character_name for c in chars if _MINING_SCOPE not in (c.scopes or "").split()]
    return {
        "summary": summary, "entries": entries,
        "period": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        "needs_scope": needs_scope, "scope": scope,
    }


# ── Market: Trade Profits (FIFO realized P&L) ──────────────────────────────────

def _char_fee_rates(db: Session, character_id: int) -> tuple:
    """The character's (broker_fee_pct, sales_tax_pct) from its Accounting + Broker
    Relations skills. Station-standing discounts are not modelled (treated as 0), so
    broker fee is the conservative skill-only rate."""
    levels = {sk.skill_id: (sk.trained_level or 0)
              for sk in db.query(EsiSkill).filter(EsiSkill.character_id == character_id).all()}
    return skills.broker_fee_pct(levels), skills.sales_tax_pct(levels)


@router.get("/trade-profits", summary="Realized trade profit (FIFO buy↔sell) with broker fee + sales tax")
async def get_trade_profits(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (sell date)"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (sell date)"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    chars = _scoped_chars(db, current_user, scope)
    start_dt, end_dt = _parse_day(start), _parse_day(end)

    # FIFO runs over the *pooled* transaction history of every character in scope: an alt
    # may buy (e.g. in Jita) while another character sells, so a buy on one char must be
    # able to back a sell on another. Cost basis needs buys from before the window, so the
    # full history is matched and the date filter is applied to the realized rows after.
    # Each txn keeps its own character's fee rates: buy-side broker uses the buyer's rate,
    # sell-side broker + sales tax use the seller's; the row is attributed to the seller.
    rows_in: list = []
    for c in chars:
        txns = (db.query(EsiWalletTransaction)
                .filter(EsiWalletTransaction.character_id == c.character_id).all())
        if not txns:
            continue
        broker_pct, tax_pct = _char_fee_rates(db, c.character_id)
        rows_in.extend({"type_id": t.type_id, "is_buy": t.is_buy, "quantity": t.quantity,
                        "unit_price": t.unit_price, "date": t.date,
                        "transaction_id": t.transaction_id,
                        "broker_pct": broker_pct, "tax_pct": tax_pct,
                        "character_id": c.character_id, "character_name": c.character_name}
                       for t in txns)

    res = trade_profits.match_trades(rows_in)
    all_rows = res["rows"]
    unmatched_total = res["unmatched"]

    # resolve item names
    type_ids = {r["type_id"] for r in all_rows} | set(unmatched_total)
    names = _type_names(eve_db, type_ids)
    for r in all_rows:
        r["name"] = (names.get(r["type_id"]) or {}).get("name") or f"Type #{r['type_id']}"

    def _in_window(r) -> bool:
        if not r["date"]:
            return False
        d = datetime.date.fromisoformat(r["date"])
        if start_dt and d < start_dt:
            return False
        if end_dt and d > end_dt:
            return False
        return True

    rows = sorted((r for r in all_rows if _in_window(r)),
                  key=lambda r: (r["date"], r["name"]), reverse=True)

    # per-row opt-outs: excluded trades stay in the table (the UI dims them) but are left
    # out of the summary metrics — same mechanism as Tracking → Industry (kind 'trade',
    # keyed on the sell transaction id).
    excl_trades = {e.ref_id for e in db.query(TrackingExclusion).filter(
        TrackingExclusion.user_id == current_user.id, TrackingExclusion.kind == "trade").all()}
    for r in rows:
        r["excluded"] = r.get("sell_tx_id") in excl_trades
    summary = trade_profits.summarize_trades([r for r in rows if not r["excluded"]])

    unmatched = sorted(
        ({"type_id": tid, "name": (names.get(tid) or {}).get("name") or f"Type #{tid}", "units": u}
         for tid, u in unmatched_total.items()),
        key=lambda x: -x["units"])

    needs_scope = [c.character_name for c in chars if _WALLET_SCOPE not in (c.scopes or "").split()]
    return {
        "rows": rows, "summary": summary, "unmatched": unmatched,
        "period": {"start": start_dt.isoformat() if start_dt else None,
                   "end": end_dt.isoformat() if end_dt else None},
        "needs_scope": needs_scope, "scope": scope,
    }


# ── Industry: completed jobs + manufacturing profit (FIFO cost ledger) ──────────

def _job_bom(eve_db: Session, job, me: int, sde_activity: int) -> tuple:
    """(inputs, product_type_id, produced, bom_known) for an industry job — its ME-adjusted
    material consumption (from the SDE activity's BOM) + output quantity. ``inputs`` =
    [{type_id, qty}]; consumed qty per material = ``max(runs, ceil(base_qty·runs·(1−ME/100)))``
    (rig/structure ME is not known per ESI job, so blueprint ME only; ME is 0 for
    non-manufacturing). ``bom_known`` is False when no blueprint id / no SDE BOM rows were
    found — the caller must NOT treat such a job as a zero-cost (free) build."""
    bt = job.blueprint_type_id
    runs = job.runs or 0
    prod = eve_repo.product_for_blueprint(eve_db, bt) if bt else None
    qty_per_run = (prod or {}).get("qty_per_run") or 1
    product_type_id = job.product_type_id or (prod or {}).get("product_type_id")
    mats = eve_repo.materials(eve_db, bt, sde_activity) if bt else []
    inputs = [
        {"type_id": m["type_id"],
         "qty": max(runs, math.ceil((m["base_qty"] or 0) * runs * (1 - me / 100.0)))}
        for m in mats
    ]
    return inputs, product_type_id, runs * qty_per_run, bool(bt) and bool(mats)


def _in_window(day: Optional[str], start_d, end_d) -> bool:
    if not day:
        return False
    d = datetime.date.fromisoformat(day)
    return not ((start_d and d < start_d) or (end_d and d > end_d))


def _jita_sell(type_ids) -> dict:
    """{type_id: Jita sell price} for allocating a contract-buy price across its items."""
    ids = [t for t in type_ids if t]
    if not ids:
        return {}
    agg = market.fuzzwork_aggregates_or_empty(_THE_FORGE_REGION, ids)
    out = {}
    for tid in ids:
        se = (agg.get(str(tid)) or {}).get("sell") or {}
        out[tid] = se.get("percentile") or se.get("min")
    return out


def _contract_buy_events(items, price: float, date, jita: dict) -> list:
    """A contract I paid ``price`` for → buy events, the price allocated across the acquired
    items by Jita value (equal split if no prices), so they become tracked cost basis."""
    vals = {it.type_id: (jita.get(it.type_id) or 0.0) * int(it.quantity or 0) for it in items}
    total = sum(vals.values())
    n = len([it for it in items if (it.quantity or 0) > 0]) or 1
    out = []
    for it in items:
        qty = int(it.quantity or 0)
        if qty <= 0:
            continue
        share = (vals[it.type_id] / total) if total > 0 else (1.0 / n)
        out.append({"kind": "buy", "date": date, "type_id": it.type_id,
                    "qty": qty, "unit_cost": (price * share) / qty})
    return out


@router.get("/industry", summary="Completed manufacturing jobs + realized manufacturing profit")
async def get_industry(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    start: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    include_missing: bool = Query(False, description="count manufacturing/contract sales whose cost basis is incomplete (overstated margin)"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    chars = _scoped_chars(db, current_user, scope)
    cids = [c.character_id for c in chars]
    char_name = {c.character_id: c.character_name for c in chars}
    start_d, end_d = _parse_day(start), _parse_day(end)
    rates = {cid: _char_fee_rates(db, cid) for cid in cids}

    # market buys (material cost basis) + sells (manufacturing realization)
    events: list = []
    name_ids: set = set()
    txns = (db.query(EsiWalletTransaction)
            .filter(EsiWalletTransaction.character_id.in_(cids or [-1])).all())
    for t in txns:
        broker_pct, tax_pct = rates.get(t.character_id, (3.0, 7.5))
        if t.type_id:
            name_ids.add(t.type_id)
        if t.is_buy:
            events.append({"kind": "buy", "date": t.date, "type_id": t.type_id,
                           "qty": t.quantity, "unit_cost": (t.unit_price or 0.0) * (1 + broker_pct / 100.0)})
        else:
            events.append({"kind": "sell", "date": t.date, "type_id": t.type_id,
                           "qty": t.quantity, "unit_price": t.unit_price,
                           "broker_pct": broker_pct, "tax_pct": tax_pct})

    # minerals refined from your own ore (Inventory → Reprocess) are owned cost basis:
    # feed them in as acquisitions so own-ore builds aren't flagged "missing inputs".
    for it in (db.query(InventoryItem)
               .filter(InventoryItem.user_id == current_user.id, InventoryItem.source == "reprocess",
                       InventoryItem.eve_type_id.isnot(None)).all()):
        if it.eve_type_id:
            name_ids.add(it.eve_type_id)
        events.append({"kind": "buy", "date": it.created_at, "type_id": it.eve_type_id,
                       "qty": it.quantity, "unit_cost": it.price or 0.0})

    # completed industry jobs of every activity → build events (manufacturing + reactions
    # produce a sellable lot and feed Manufacturing Profit; copying/research/invention just
    # show their cost in the jobs table).
    jobs = (db.query(EsiIndustryJob)
            .filter(EsiIndustryJob.character_id.in_(cids or [-1]),
                    EsiIndustryJob.status == "delivered",
                    EsiIndustryJob.activity_id.in_(list(_ACT_META))).all())
    bp_me = {b.item_id: (b.material_efficiency or 0)
             for b in db.query(EsiBlueprintCopy)
             .filter(EsiBlueprintCopy.character_id.in_(cids or [-1])).all()}
    overrides = {o.job_id: o.custom_unit_price for o in db.query(JobCostOverride)
                 .filter(JobCostOverride.user_id == current_user.id).all()}
    job_meta: list = []
    for j in jobs:
        sde_act, act_name, produces = _ACT_META.get(j.activity_id, (j.activity_id, "Other", False))
        me = bp_me.get(j.blueprint_id, 0) if j.activity_id == 1 else 0   # ME only on manufacturing
        inputs, product_type_id, produced, bom_known = _job_bom(eve_db, j, me, sde_act)
        job_meta.append((j, inputs, product_type_id, produced, act_name, produces, bom_known))
        name_ids.update(m["type_id"] for m in inputs)
        for tid in (product_type_id, j.blueprint_type_id):
            if tid:
                name_ids.add(tid)

    names = eve_repo.type_names(eve_db, name_ids)
    for ev in events:
        if ev["kind"] == "sell":
            ev["name"] = names.get(ev["type_id"]) or f"Type #{ev['type_id']}"
    for j, inputs, product_type_id, produced, act_name, produces, bom_known in job_meta:
        events.append({
            "kind": "build", "date": j.end_date,
            "completed_at": j.end_date.isoformat() if j.end_date else None,
            "job_id": j.job_id, "owner": char_name.get(j.character_id) or "Personal",
            "activity": act_name, "blueprint_name": names.get(j.blueprint_type_id),
            "product_type_id": product_type_id,
            "product_name": names.get(product_type_id) or (f"Type #{product_type_id}" if product_type_id else None),
            "runs": j.runs or 0, "product_qty": produced, "produces": produces,
            "job_cost": j.cost or 0.0, "copy_cost": 0.0, "inputs": inputs, "bom_known": bom_known,
            "custom_unit_price": overrides.get(j.job_id),
        })

    # finished item-exchange contracts touching my chars (issued or accepted). A SELL (I gave
    # items for a price) → contract_sell (profit, consumes cost basis); a BUY (I paid for items)
    # → buy events so the acquired items become tracked cost basis for later builds/sales.
    cset = set(cids)
    contracts = [c for c in db.query(EsiContract).filter(
        EsiContract.character_id.in_(cids or [-1]), EsiContract.type == "item_exchange",
        EsiContract.status == "finished").all() if c.issuer_id in cset or c.acceptor_id in cset]
    if contracts:
        contract_ids = [c.contract_id for c in contracts]
        incl_by: dict = {}
        excl_by: dict = {}
        for it in (db.query(EsiContractItem)
                   .filter(EsiContractItem.contract_id.in_(contract_ids or [-1])).all()):
            (incl_by if it.is_included else excl_by).setdefault(it.contract_id, []).append(it)
        annos = {a.contract_id: a for a in db.query(ContractAnnotation)
                 .filter(ContractAnnotation.user_id == current_user.id,
                         ContractAnnotation.contract_id.in_(contract_ids or [-1])).all()}
        acceptor_names = _resolve_names(db, [c.acceptor_id for c in contracts if c.acceptor_id])
        buy_specs: list = []      # (items, price, date) for contract purchases
        for c in contracts:
            if not (c.price and c.price > 0):
                continue
            issued = c.issuer_id in cset
            accepted = (c.acceptor_id in cset) and not issued
            incl = incl_by.get(c.contract_id) or []     # offered by the issuer
            excl = excl_by.get(c.contract_id) or []      # requested from the acceptor
            if issued and incl:                          # I issued a sell → gave items for ISK
                broker_pct, _tax = rates.get(c.character_id, (3.0, 7.5))
                anno = annos.get(c.contract_id)
                events.append({
                    "kind": "contract_sell", "date": c.date_completed, "contract_id": c.contract_id,
                    "character": char_name.get(c.character_id) or "Personal",
                    "acceptor": acceptor_names.get(c.acceptor_id) or (f"#{c.acceptor_id}" if c.acceptor_id else "—"),
                    "title": c.title or "—", "note": (anno.note if anno else None),
                    "price": c.price, "broker": (c.price or 0.0) * broker_pct / 100.0,
                    "items": [{"type_id": it.type_id, "qty": int(it.quantity or 0)} for it in incl],
                })
            elif issued and excl:                        # I issued a buy-request → received items
                buy_specs.append((excl, c.price, c.date_completed))
            elif accepted and incl:                      # I accepted someone's sell → bought items
                buy_specs.append((incl, c.price, c.date_completed))
        if buy_specs:
            jita = _jita_sell({it.type_id for items, _p, _d in buy_specs for it in items})
            for items, price, date in buy_specs:
                events.extend(_contract_buy_events(items, price, date, jita))

    ledger = industry_ledger.run_ledger(events, include_missing=include_missing)
    job_rows = sorted((r for r in ledger["jobs"] if _in_window(r["date"], start_d, end_d)),
                      key=lambda r: r["completed_at"] or "", reverse=True)
    mfg_rows = sorted((r for r in ledger["manufacturing"] if _in_window(r["date"], start_d, end_d)),
                      key=lambda r: (r["date"], r["name"]), reverse=True)
    # contracts with an incomplete cost basis (margin overstated) are dropped from the
    # totals unless include_missing is on — mirrors the manufacturing side.
    ctr_rows = sorted((r for r in ledger["contracts"]
                       if _in_window(r["date"], start_d, end_d) and (include_missing or not r.get("missing"))),
                      key=lambda r: r["date"], reverse=True)

    # per-user row opt-outs: excluded jobs/contracts stay in their table (the UI dims them)
    # but are left out of the summary metrics.
    excl = db.query(TrackingExclusion).filter(TrackingExclusion.user_id == current_user.id).all()
    excl_jobs = {e.ref_id for e in excl if e.kind == "job"}
    excl_contracts = {e.ref_id for e in excl if e.kind == "contract"}
    for r in job_rows:
        r["excluded"] = r["job_id"] in excl_jobs
    for r in ctr_rows:
        r["excluded"] = r["contract_id"] in excl_contracts

    needs_scope = [c.character_name for c in chars if _WALLET_SCOPE not in (c.scopes or "").split()]
    return {
        "jobs": job_rows, "jobs_summary": industry_ledger.summarize_jobs([r for r in job_rows if not r["excluded"]]),
        "manufacturing": mfg_rows, "mfg_summary": industry_ledger.summarize_manufacturing(mfg_rows),
        "contracts": ctr_rows,
        "contracts_summary": industry_ledger.summarize_contracts([r for r in ctr_rows if not r["excluded"]]),
        "period": {"start": start_d.isoformat() if start_d else None,
                   "end": end_d.isoformat() if end_d else None},
        "needs_scope": needs_scope, "scope": scope,
    }


class JobOverrideIn(BaseModel):
    job_id: int
    custom_unit_price: Optional[float] = None     # null clears the override (Re-process Job)


@router.post("/industry/job-override", summary="Set/clear a job's Custom Unit Price (detail panel)")
async def set_job_override(
    body: JobOverrideIn,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (db.query(JobCostOverride)
           .filter(JobCostOverride.user_id == current_user.id, JobCostOverride.job_id == body.job_id).first())
    if body.custom_unit_price is None or body.custom_unit_price < 0:
        if row:                                   # Re-process Job — drop the manual cost
            db.delete(row)
            db.commit()
        return {"job_id": body.job_id, "custom_unit_price": None}
    if not row:
        row = JobCostOverride(user_id=current_user.id, job_id=body.job_id, created_at=utcnow())
        db.add(row)
    row.custom_unit_price = body.custom_unit_price
    row.updated_at = utcnow()
    db.commit()
    return {"job_id": body.job_id, "custom_unit_price": row.custom_unit_price}


class ExclusionIn(BaseModel):
    kind: str                  # 'job' | 'contract' | 'trade'
    ref_id: int                # job_id, contract_id, or sell transaction_id (trade)
    excluded: bool             # True = exclude from totals, False = re-include


@router.post("/industry/exclude", summary="Include/exclude a job, contract or market trade from the totals")
async def set_exclusion(
    body: ExclusionIn,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.kind not in ("job", "contract", "trade"):
        raise HTTPException(status_code=400, detail="kind must be 'job', 'contract' or 'trade'")
    row = (db.query(TrackingExclusion)
           .filter(TrackingExclusion.user_id == current_user.id,
                   TrackingExclusion.kind == body.kind, TrackingExclusion.ref_id == body.ref_id).first())
    if body.excluded and not row:
        db.add(TrackingExclusion(user_id=current_user.id, kind=body.kind,
                                 ref_id=body.ref_id, created_at=utcnow()))
        db.commit()
    elif not body.excluded and row:
        db.delete(row)
        db.commit()
    return {"kind": body.kind, "ref_id": body.ref_id, "excluded": body.excluded}


# ── Tracking summary (unified income/profit across all streams — Agenda) ─────────

@router.get("/tracking-summary", summary="Unified income/profit across every tracking stream (Agenda)")
async def tracking_summary(
    days: int = Query(30, ge=1, le=365, description="window size ending today"),
    scope: str = Query("all", description="all | char:<id> | group:<name> | corp:<corp_id>"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    """One call that runs every Tracking stream over the last ``days`` for the given
    ``scope`` and returns each stream's headline number plus the grand total — the data the
    individual tabs each compute in isolation, unified for the Agenda / corp summary card.
    Profit streams (Market/Manufacturing/Contracts) report realized profit; the rest
    report income (Missions/Ratting/Deliveries) or refined value (Mining)."""
    end_d = utcnow().date()
    start = (end_d - datetime.timedelta(days=days - 1)).isoformat()

    trade = await get_trade_profits(scope=scope, start=start, end=None,
                                    current_user=current_user, db=db, eve_db=eve_db)
    industry = await get_industry(scope=scope, start=start, end=None,
                                  current_user=current_user, db=db, eve_db=eve_db)
    missions = await get_missions(scope=scope, start=start, end=None, current_user=current_user, db=db)
    ratting = await get_ratting(scope=scope, start=start, end=None, current_user=current_user, db=db)
    mining = await get_mining(scope=scope, start=start, end=None, basis=None, limit=500,
                              current_user=current_user, db=db, eve_db=eve_db)
    deliveries = await get_deliveries(scope=scope, status="completed", start=start, end=None,
                                      current_user=current_user, db=db, eve_db=eve_db)

    streams = [
        {"key": "trade", "label": "Market (trade)", "kind": "profit", "value": trade["summary"]["total_profit"]},
        {"key": "manufacturing", "label": "Manufacturing", "kind": "profit", "value": industry["mfg_summary"]["total_profit"]},
        {"key": "contracts", "label": "Contracts", "kind": "profit", "value": industry["contracts_summary"]["total_profit"]},
        {"key": "missions", "label": "Missions", "kind": "income", "value": missions["summary"]["total"]},
        {"key": "ratting", "label": "Ratting", "kind": "income", "value": ratting["summary"]["grand_total"]},
        {"key": "mining", "label": "Mining (refined)", "kind": "value", "value": mining["summary"]["total_value"]},
        {"key": "deliveries", "label": "Deliveries", "kind": "income", "value": deliveries["summary"]["reward_total"]},
    ]
    grand_total = round(sum(s["value"] or 0 for s in streams), 2)
    return {
        "period": {"start": start, "end": end_d.isoformat(), "days": days},
        "streams": streams,
        "grand_total": grand_total,
        "per_day": round(grand_total / days, 2) if days else 0.0,
    }


# ── PI: planetary-interaction colonies + manual PI-stock warehouse ───────────────

_PLANETS_SCOPE = "esi-planets.manage_planets.v1"


@router.get("/pi", summary="Planetary-interaction colonies (planet, extraction status, storage) per character")
async def get_pi(
    scope: str = Query("all", description="all | char:<id> | group:<name>"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    """Colony cards for the selected characters: planet (name/type/radius/location from the
    SDE), command-center level + pin count, extraction status (running/idle + when the last
    head stops), storage fill %, and the extracted products valued at Jita sell."""
    chars = _scoped_chars(db, current_user, scope)
    owner = {c.character_id: c.character_name for c in chars}
    rows = (db.query(EsiPlanet)
            .filter(EsiPlanet.character_id.in_([c.character_id for c in chars] or [-1]))
            .all())

    # SDE enrichment: planet (name/radius/celestial type), system name + security, region
    planet_ids = {r.planet_id for r in rows}
    planets = {p.planet_id: p for p in eve_db.query(EvePlanet)
               .filter(EvePlanet.planet_id.in_(planet_ids or [-1])).all()}
    sys_ids = {r.solar_system_id for r in rows if r.solar_system_id}
    systems = {s.solar_system_id: s for s in eve_db.query(EveSolarSystem)
               .filter(EveSolarSystem.solar_system_id.in_(sys_ids or [-1])).all()}
    region_names = _region_names(eve_db, {p.region_id for p in planets.values()})

    # value the extracted products at Jita sell + resolve their names
    prod_ids = {tid for r in rows for tid in (r.products or [])}
    prod_names = _type_names(eve_db, prod_ids)
    prod_jita = _jita_sell(prod_ids)

    colonies = []
    for r in rows:
        pl = planets.get(r.planet_id)
        sysm = systems.get(r.solar_system_id)
        colonies.append({
            "character_id": r.character_id,
            "character_name": owner.get(r.character_id),
            "planet_id": r.planet_id,
            "planet_name": (pl.planet_name if pl else None) or f"Planet #{r.planet_id}",
            "planet_type": r.planet_type,                       # ESI string (temperate/…)
            "planet_type_id": pl.type_id if pl else None,        # celestial type → image
            "radius": pl.radius if pl else None,                 # metres
            "system": sysm.solar_system_name if sysm else None,
            "security": round(sysm.security, 1) if sysm and sysm.security is not None else None,
            "region": region_names.get(pl.region_id) if pl else None,
            "upgrade_level": r.upgrade_level,
            "num_pins": r.num_pins,
            "has_extractor": r.has_extractor,
            "extracting": r.extracting,
            "extractor_expiry": r.extractor_expiry.isoformat() if r.extractor_expiry else None,
            "storage_used": r.storage_used,
            "storage_capacity": r.storage_capacity,
            "storage_pct": pi_svc.storage_pct(r.storage_used, r.storage_capacity),
            "products": [{"type_id": tid,
                          "name": (prod_names.get(tid) or {}).get("name") or f"#{tid}",
                          "value": prod_jita.get(tid)}
                         for tid in (r.products or [])],
            "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        })
    colonies.sort(key=lambda c: (c["character_name"] or "", c["planet_name"]))

    needs_scope = [c.character_name for c in chars if _PLANETS_SCOPE not in (c.scopes or "").split()]
    return {"colonies": colonies, "needs_scope": needs_scope, "scope": scope}


class PiStockBody(BaseModel):
    text: str                       # EVE clipboard paste: "Name<tab>Qty" or "Qty<tab>Name"
    place: Optional[str] = None     # optional storage/system label


def _pi_stock_rows(db: Session, eve_db: Session, user: UserDB) -> tuple[list, float]:
    """Current PI-sourced warehouse lots (source='pi', in stock) re-valued at Jita sell.
    Returns (rows, total_value). The total is the realized-on-sale worth of extracted PI."""
    items = (db.query(InventoryItem)
             .filter(InventoryItem.user_id == user.id, InventoryItem.source == "pi",
                     InventoryItem.item_status == "in_stock").all())
    jita = _jita_sell({it.eve_type_id for it in items if it.eve_type_id})
    rows, total = [], 0.0
    for it in items:
        unit = jita.get(it.eve_type_id)
        value = (unit or 0.0) * int(it.quantity or 0)
        total += value
        rows.append({
            "id": it.id, "type_id": it.eve_type_id, "name": it.name,
            "quantity": int(it.quantity or 0), "place": it.place,
            "unit_value": unit, "value": round(value, 2),
            "created_at": it.created_at.isoformat() if it.created_at else None,
        })
    rows.sort(key=lambda r: -r["value"])
    return rows, round(total, 2)


@router.get("/pi/stock", summary="PI-sourced warehouse lots valued at Jita (extraction profit)")
async def get_pi_stock(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    rows, total = _pi_stock_rows(db, eve_db, current_user)
    return {"rows": rows, "total_value": total}


@router.post("/pi/stock", summary="Parse a PI material paste into the warehouse (source='pi')")
async def add_pi_stock(
    body: PiStockBody,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    """Parse an EVE clipboard paste of extracted PI products, resolve names → type_ids,
    and add each as a warehouse lot tagged ``source='pi'`` (flow=output, in stock). The
    Jita value of these lots is the PI extraction profit, summed in GET /pi/stock."""
    parsed = loot.parse_lines(body.text)
    warnings: list = []
    items: list = []
    for name, qty, warns in parsed:
        warnings.extend(warns)
        if name:
            items.append({"name": name, "qty": qty})

    resolved = eve_repo.types_by_name(eve_db, [it["name"] for it in items])
    type_ids = [info["type_id"] for info in resolved.values()]
    volumes = {tid: vol for tid, vol in eve_db.query(EveType.type_id, EveType.volume)
               .filter(EveType.type_id.in_(type_ids or [-1])).all()}
    jita = _jita_sell(type_ids)

    now = utcnow()
    added = 0
    for it in items:
        info = resolved.get(it["name"].strip().lower())
        if not info:
            warnings.append(f"Unknown item, skipped: {it['name']}")
            continue
        tid = info["type_id"]
        db.add(InventoryItem(
            user_id=current_user.id, eve_type_id=tid, name=info["name"],
            volume=volumes.get(tid), quantity=it["qty"], price=jita.get(tid),
            place=(body.place or None), flow="output", item_status="in_stock",
            source="pi", created_at=now,
        ))
        added += 1
    db.commit()

    rows, total = _pi_stock_rows(db, eve_db, current_user)
    return {"added": added, "warnings": warnings, "rows": rows, "total_value": total}


@router.delete("/pi/stock/{item_id}", summary="Remove a PI warehouse lot", status_code=204)
async def delete_pi_stock(
    item_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (db.query(InventoryItem)
            .filter(InventoryItem.id == item_id, InventoryItem.user_id == current_user.id,
                    InventoryItem.source == "pi").first())
    if not item:
        raise HTTPException(status_code=404, detail="PI stock lot not found")
    db.delete(item)
    db.commit()
    return Response(status_code=204)
