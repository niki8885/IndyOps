"""Tracking → Orders + the account dashboard (mounted at /api/v1/account).

The nav tab is called "Tracking", but /api/v1/tracking is already the Analysis
watch-list, so the order/dashboard endpoints live under /account instead. Everything
here is scoped to the current user's linked characters; the character/group selector
is driven by the ``scope`` argument (``all`` | ``char:<id>`` | ``group:<name>``).

Competitive pricing (Price Status / Difference) and the manual resync both hit ESI,
so they're button-triggered and rate-limited per user (see ``services/ratelimit``).
"""
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters import market
from app.core.database import (
    get_db, UserDB, LinkedCharacter, CharacterSettings,
    EsiMarketOrder, EsiIndustryJob, EsiContract, EsiSkill, EsiStructure, BankLedgerEntry,
)
from app.core.database_eve import EveSessionLocal, EveStation, EveRegion
from app.core.security import get_current_user
from app.core.timeutil import utcnow
from app.services import orders as orders_svc, currency, skills, ratelimit
# Reuse the SDE name resolvers + single-character sync kick from the Personal File router.
from app.api.characters_router import (
    _type_names, _station_names, _system_names, _structure_names, _kick_sync,
)

router = APIRouter()

_ORDERS_SCOPE = "esi-markets.read_character_orders.v1"
_SYNC_COOLDOWN_S = 60
_PRICE_COOLDOWN_S = 60

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
