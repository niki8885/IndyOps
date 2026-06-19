import datetime
import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.adapters import esi, market
from app.api.responses import ERR_400, ERR_404, ERR_500
from app.core import config
from app.core.database import (
    get_db, SessionLocal, UserDB,
    LinkedCharacter, EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract, EsiIndustryJob,
    EsiStanding, EsiStructure, EsiImplant, EsiMiningLedger, EsiBlueprintCopy,
    CharacterWealthSnapshot, CharacterSettings, MiningTaxWriteoff, InventoryItem, ProductionJob,
)
from app.core.database_eve import EveSessionLocal, EveType, EveStation, EveSolarSystem, EveTypeMaterial
from app.core.schemas import ProductionStatus
from app.core.security import get_current_user
from app.core.timeutil import utcnow
from app.repositories import eve as eve_repo
from app.services import asset_location, skills, mining_journal
from app.services.refining import RefineSetup, compute_yield, reprocess

logger = logging.getLogger(__name__)
router = APIRouter()

_ACTIVITY_NAMES = {
    1: "Manufacturing", 3: "TE Research", 4: "ME Research",
    5: "Copying", 8: "Invention", 9: "Reactions", 11: "Reactions",
}
_JOB_STATUS_MAP = {
    "active": ProductionStatus.IN_PROGRESS, "ready": ProductionStatus.IN_PROGRESS,
    "paused": ProductionStatus.PREPARING, "delivered": ProductionStatus.COMPLETED,
    "cancelled": ProductionStatus.CANCELLED, "reverted": ProductionStatus.CANCELLED,
}


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# SDE name helpers
# ---------------------------------------------------------------------------

def _type_names(eve_db: Session, type_ids) -> dict:
    ids = {t for t in type_ids if t}
    if not ids:
        return {}
    rows = eve_db.query(EveType.type_id, EveType.type_name, EveType.volume).filter(EveType.type_id.in_(ids)).all()
    return {tid: {"name": name, "volume": vol} for tid, name, vol in rows}


def _station_names(eve_db: Session, location_ids) -> dict:
    ids = {i for i in location_ids if i and i < 100_000_000}  # stations; citadels are huge ids
    if not ids:
        return {}
    rows = eve_db.query(EveStation.station_id, EveStation.station_name).filter(EveStation.station_id.in_(ids)).all()
    return {sid: name for sid, name in rows}


def _system_names(eve_db: Session, system_ids) -> dict:
    ids = {i for i in system_ids if i}
    if not ids:
        return {}
    rows = (
        eve_db.query(EveSolarSystem.solar_system_id, EveSolarSystem.solar_system_name)
        .filter(EveSolarSystem.solar_system_id.in_(ids)).all()
    )
    return {sid: name for sid, name in rows}


def _structure_names(db: Session, structure_ids) -> dict:
    """Resolved Upwell-structure names from the shared ESI cache (sync populates it)."""
    ids = {i for i in structure_ids if i}
    if not ids:
        return {}
    rows = (
        db.query(EsiStructure.structure_id, EsiStructure.name)
        .filter(EsiStructure.structure_id.in_(ids), EsiStructure.name.isnot(None)).all()
    )
    return {sid: name for sid, name in rows}


# ---------------------------------------------------------------------------
# SSO state token (CSRF + user binding)
# ---------------------------------------------------------------------------

def _make_state(user_id: int) -> str:
    payload = {
        "sso_uid": user_id,
        "purpose": "sso_state",
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=config.SSO_STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def _read_state(state: str) -> int:
    claims = jwt.decode(state, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    if claims.get("purpose") != "sso_state":
        raise JWTError("not an sso state token")
    return int(claims["sso_uid"])


def _frontend_redirect(**params) -> RedirectResponse:
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(url=f"{config.FRONTEND_URL}/personal?{qs}", status_code=302)


# ---------------------------------------------------------------------------
# Background sync
# ---------------------------------------------------------------------------

def _sync_one_bg(character_id: int) -> None:
    from app.tasks.update_esi import sync_character
    db = SessionLocal()
    try:
        char = db.query(LinkedCharacter).filter(LinkedCharacter.character_id == character_id).first()
        if char:
            sync_character(db, char)
    except Exception:  # noqa: BLE001
        logger.exception("background sync failed for %s", character_id)
    finally:
        db.close()


def _kick_sync(character_id: int) -> None:
    threading.Thread(target=_sync_one_bg, args=(character_id,), daemon=True).start()


def _owned_char(db: Session, char_id: int, user: UserDB) -> LinkedCharacter:
    char = db.query(LinkedCharacter).filter(LinkedCharacter.id == char_id).first()
    if not char or char.user_id != user.id:
        raise HTTPException(404, "Character not found")
    return char


# ---------------------------------------------------------------------------
# SSO
# ---------------------------------------------------------------------------

@router.get("/sso/login", summary="Get the EVE SSO login URL", responses={**ERR_500})
async def sso_login(current_user: UserDB = Depends(get_current_user)):
    if not config.ESI_CLIENT_ID or not config.ESI_CALLBACK_URL:
        raise HTTPException(500, "ESI is not configured on the server (CLIENT_ID/CALLBACK_URL)")
    return {"url": esi.authorize_url(_make_state(current_user.id))}


@router.get("/sso/callback", summary="EVE SSO redirect target", include_in_schema=False)
async def sso_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    try:
        user_id = _read_state(state)
    except JWTError:
        return _frontend_redirect(error="bad_state")

    try:
        tokens = esi.exchange_code(code)
        claims = esi.verify_access_token(tokens["access_token"])
        info = esi.parse_character_claims(claims)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSO callback failed: %s", exc)
        return _frontend_redirect(error="sso_failed")

    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.character_id == info["character_id"]).first()
    if char and char.user_id != user_id:
        return _frontend_redirect(error="owned_by_other")

    now = utcnow()
    if not char:
        char = LinkedCharacter(user_id=user_id, character_id=info["character_id"], added_at=now)
        db.add(char)
    char.character_name = info["character_name"]
    char.owner_hash = info["owner_hash"]
    char.scopes = info["scopes"]
    char.status = "active"
    char.is_active = True
    char.updated_at = now
    esi.store_tokens(char, tokens)
    db.commit()

    _kick_sync(char.character_id)
    return _frontend_redirect(linked=char.character_name)


# ---------------------------------------------------------------------------
# Character management
# ---------------------------------------------------------------------------

def _corp_logo(corp_id):
    return f"https://images.evetech.net/corporations/{corp_id}/logo?size=64" if corp_id else None


def _alliance_logo(alliance_id):
    return f"https://images.evetech.net/alliances/{alliance_id}/logo?size=64" if alliance_id else None


def _char_out(c: LinkedCharacter, settings=None) -> dict:
    s = settings
    return {
        "id": c.id,
        "character_id": c.character_id,
        "character_name": c.character_name,
        "corporation_id": c.corporation_id,
        "corporation_name": c.corporation_name,
        "corporation_logo": _corp_logo(c.corporation_id),
        "alliance_id": c.alliance_id,
        "alliance_name": c.alliance_name,
        "alliance_logo": _alliance_logo(c.alliance_id),
        "portrait": f"https://images.evetech.net/characters/{c.character_id}/portrait?size=128",
        "is_active": c.is_active,
        "status": c.status,
        "online": c.online,
        "scopes": c.scopes.split() if c.scopes else [],
        "wallet_balance": c.wallet_balance,
        "assets_value": c.assets_value,
        "total_sp": c.total_sp,
        "last_sync_at": c.last_sync_at,
        "added_at": c.added_at,
        "favorite": bool(s.favorite) if s else False,
        "group_name": (s.group_name if s else None) or None,
        "is_manufacturer": bool(s.is_manufacturer) if s else False,
        "is_trader": bool(s.is_trader) if s else False,
    }


@router.get("", summary="List my linked EVE characters")
async def list_characters(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = (
        db.query(LinkedCharacter)
        .filter(LinkedCharacter.user_id == current_user.id)
        .order_by(LinkedCharacter.added_at)
        .all()
    )
    settings = {s.character_id: s for s in
                db.query(CharacterSettings)
                .filter(CharacterSettings.character_id.in_([c.character_id for c in chars] or [-1])).all()}
    out = [_char_out(c, settings.get(c.character_id)) for c in chars]
    out.sort(key=lambda c: (not c["favorite"], (c["character_name"] or "").lower()))
    return out


class CharacterPatch(BaseModel):
    is_active: Optional[bool] = None


@router.patch("/{char_id}", summary="Toggle a character's activation status", responses={**ERR_404})
async def patch_character(
    char_id: int,
    patch: CharacterPatch,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    if patch.is_active is not None:
        char.is_active = patch.is_active
        char.updated_at = utcnow()
        db.commit()
    return _char_out(char)


@router.delete("/{char_id}", status_code=204, summary="Unlink a character (and its synced data)", responses={**ERR_404})
async def delete_character(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    cid = char.character_id
    for model in (EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract, EsiIndustryJob,
                  EsiStanding, EsiImplant, EsiMiningLedger, EsiBlueprintCopy,
                  CharacterWealthSnapshot, CharacterSettings, MiningTaxWriteoff):
        db.query(model).filter(model.character_id == cid).delete(synchronize_session=False)
    db.delete(char)
    db.commit()
    return None


@router.post("/{char_id}/sync", summary="Trigger an ESI sync for one character now", responses={**ERR_404})
async def sync_now(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    _kick_sync(char.character_id)
    return {"status": "started", "message": "ESI sync started — refresh in a few seconds"}


# ---------------------------------------------------------------------------
# Read endpoints (synced data, name-enriched)
# ---------------------------------------------------------------------------

@router.get("/{char_id}/wallet", summary="Wallet balance + transactions", responses={**ERR_404})
async def get_wallet(
    char_id: int,
    limit: int = Query(200, le=2500),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    txs = (
        db.query(EsiWalletTransaction)
        .filter(EsiWalletTransaction.character_id == char.character_id)
        .order_by(EsiWalletTransaction.date.desc())
        .limit(limit)
        .all()
    )
    names = _type_names(eve_db, [t.type_id for t in txs])
    return {
        "balance": char.wallet_balance,
        "transactions": [
            {
                "transaction_id": t.transaction_id, "date": t.date,
                "type_id": t.type_id, "type_name": names.get(t.type_id, {}).get("name"),
                "quantity": t.quantity, "unit_price": t.unit_price,
                "total": (t.unit_price or 0) * (t.quantity or 0),
                "is_buy": t.is_buy, "location_id": t.location_id,
            }
            for t in txs
        ],
    }


@router.get("/{char_id}/skills", summary="Trained skills", responses={**ERR_404})
async def get_skills(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    skills = db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()
    names = _type_names(eve_db, [s.skill_id for s in skills])
    rows = [
        {
            "skill_id": s.skill_id, "skill_name": names.get(s.skill_id, {}).get("name"),
            "trained_level": s.trained_level, "active_level": s.active_level,
            "skillpoints": s.skillpoints,
        }
        for s in skills
    ]
    rows.sort(key=lambda r: (r["skill_name"] or ""))
    return {"total_sp": char.total_sp, "skills": rows}


@router.get("/{char_id}/assets", summary="Assets (inventory)", responses={**ERR_404})
async def get_assets(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    assets = db.query(EsiAsset).filter(EsiAsset.character_id == char.character_id).all()
    names = _type_names(eve_db, [a.type_id for a in assets])

    # Walk each asset's location chain to its real terminus (a nested module
    # resolves to the station/structure that holds its ship), then name it.
    roots, by_kind = asset_location.terminus_ids(assets)
    station_names = _station_names(eve_db, by_kind["station"])
    system_names = _system_names(eve_db, by_kind["system"])
    structure_names = _structure_names(db, by_kind["structure"])

    def _location_name(a):
        kind, rid = roots.get(a.item_id, (None, None))
        if kind == "station":
            return station_names.get(rid) or f"Station #{rid}"
        if kind == "system":
            return system_names.get(rid) or f"System #{rid}"
        if kind == "structure":
            return structure_names.get(rid) or f"Structure #{rid}"
        return f"#{a.location_id}" if a.location_id else None

    return [
        {
            "item_id": a.item_id, "type_id": a.type_id,
            "type_name": names.get(a.type_id, {}).get("name"),
            "quantity": a.quantity, "location_id": a.location_id,
            "location_name": _location_name(a),
            "location_flag": a.location_flag,
        }
        for a in assets
    ]


@router.get("/{char_id}/blueprints", summary="Owned blueprints (BPOs/BPCs)", responses={**ERR_404})
async def get_blueprints(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    bps = db.query(EsiBlueprintCopy).filter(EsiBlueprintCopy.character_id == char.character_id).all()

    bp_names = _type_names(eve_db, [b.type_id for b in bps])
    products = eve_repo.products_for_blueprints(eve_db, [b.type_id for b in bps])
    prod_names = _type_names(eve_db, [p["product_type_id"] for p in products.values()])

    loc_ids = {b.location_id for b in bps if b.location_id}
    station_names = _station_names(eve_db, loc_ids)
    structure_names = _structure_names(db, loc_ids)

    def _loc_name(b):
        if not b.location_id:
            return None
        return station_names.get(b.location_id) or structure_names.get(b.location_id) or f"#{b.location_id}"

    out = []
    for b in bps:
        prod = products.get(b.type_id)
        is_bpo = (b.runs is not None and b.runs < 0) or b.quantity == -1
        out.append({
            "item_id": b.item_id, "type_id": b.type_id,
            "type_name": bp_names.get(b.type_id, {}).get("name"),
            "product_type_id": prod["product_type_id"] if prod else None,
            "product_name": prod_names.get(prod["product_type_id"], {}).get("name") if prod else None,
            "activity_id": prod["activity_id"] if prod else None,
            "is_bpo": is_bpo,
            "me": b.material_efficiency, "te": b.time_efficiency,
            "runs": None if is_bpo else b.runs, "quantity": b.quantity,
            "location_id": b.location_id, "location_name": _loc_name(b),
            "location_flag": b.location_flag,
        })
    out.sort(key=lambda r: ((r["location_name"] or "~"), (r["type_name"] or "")))
    return out


@router.get("/{char_id}/contracts", summary="Contracts", responses={**ERR_404})
async def get_contracts(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    rows = (
        db.query(EsiContract)
        .filter(EsiContract.character_id == char.character_id)
        .order_by(EsiContract.date_issued.desc())
        .all()
    )
    return [
        {
            "contract_id": c.contract_id, "type": c.type, "status": c.status,
            "title": c.title, "price": c.price, "reward": c.reward,
            "collateral": c.collateral, "volume": c.volume,
            "date_issued": c.date_issued, "date_expired": c.date_expired,
            "for_corp": c.for_corp,
        }
        for c in rows
    ]


@router.get("/{char_id}/industry-jobs", summary="Industry jobs (production chains)", responses={**ERR_404})
async def get_industry_jobs(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    jobs = (
        db.query(EsiIndustryJob)
        .filter(EsiIndustryJob.character_id == char.character_id)
        .order_by(EsiIndustryJob.start_date.desc())
        .all()
    )
    names = _type_names(eve_db, [j.product_type_id for j in jobs] + [j.blueprint_type_id for j in jobs])

    # resolve the facility each job runs in (NPC station from SDE, else Upwell cache)
    loc_ids = [(j.facility_id or j.station_id) for j in jobs]
    station_loc = _station_names(eve_db, loc_ids)
    structure_loc = _structure_names(db, loc_ids)

    def _job_location(j):
        lid = j.facility_id or j.station_id
        if not lid:
            return None
        return station_loc.get(lid) or structure_loc.get(lid) or f"#{lid}"

    # used vs. available job slots, from the character's synced skills
    skill_levels = {
        s.skill_id: s.trained_level
        for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()
    }
    slots = skills.job_slot_usage([(j.activity_id, j.status) for j in jobs], skill_levels)

    return {
        "slots": slots,
        "jobs": [
            {
                "job_id": j.job_id, "activity_id": j.activity_id,
                "activity": _ACTIVITY_NAMES.get(j.activity_id, "Other"),
                "blueprint_type_id": j.blueprint_type_id,
                "blueprint_name": names.get(j.blueprint_type_id, {}).get("name"),
                "product_type_id": j.product_type_id,
                "product_name": names.get(j.product_type_id, {}).get("name"),
                "runs": j.runs, "status": j.status, "cost": j.cost,
                "location_name": _job_location(j),
                "start_date": j.start_date, "end_date": j.end_date,
            }
            for j in jobs
        ],
    }


@router.get("/{char_id}/overview", summary="Character page overview (location, ship, wealth, implants)", responses={**ERR_404})
async def get_overview(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    cid = char.character_id

    # current location → name (system from SDE, station from SDE, structure from cache)
    system_name = _system_names(eve_db, [char.location_system_id]).get(char.location_system_id)
    location_name = None
    if char.location_type == "station" and char.location_id:
        location_name = _station_names(eve_db, [char.location_id]).get(char.location_id) or f"Station #{char.location_id}"
    elif char.location_type == "structure" and char.location_id:
        location_name = _structure_names(db, [char.location_id]).get(char.location_id) or f"Structure #{char.location_id}"

    # ship + implant type names (one SDE lookup)
    implant_ids = [r.type_id for r in db.query(EsiImplant.type_id).filter(EsiImplant.character_id == cid).all()]
    type_names = _type_names(eve_db, implant_ids + ([char.ship_type_id] if char.ship_type_id else []))

    liquid, assets_value = char.wallet_balance, char.assets_value
    total = None if liquid is None and assets_value is None else (liquid or 0) + (assets_value or 0)

    granted = set((char.scopes or "").split())
    missing = [s for s in ("esi-location.read_location.v1", "esi-clones.read_implants.v1") if s not in granted]

    return {
        "id": char.id, "character_id": cid, "character_name": char.character_name,
        "portrait": f"https://images.evetech.net/characters/{cid}/portrait?size=256",
        "corporation_id": char.corporation_id, "corporation_name": char.corporation_name,
        "corporation_logo": _corp_logo(char.corporation_id),
        "alliance_id": char.alliance_id, "alliance_name": char.alliance_name,
        "alliance_logo": _alliance_logo(char.alliance_id),
        "online": char.online, "last_login": char.last_login, "last_sync_at": char.last_sync_at,
        "total_sp": char.total_sp,
        "location": {
            "system_id": char.location_system_id, "system_name": system_name,
            "location_id": char.location_id, "location_type": char.location_type,
            "location_name": location_name,
        },
        "ship": {
            "ship_type_id": char.ship_type_id,
            "ship_type_name": type_names.get(char.ship_type_id, {}).get("name") if char.ship_type_id else None,
            "ship_name": char.ship_name,
        },
        "wealth": {"liquid": liquid, "assets_value": assets_value, "total": total},
        "implants": [{"type_id": t, "name": type_names.get(t, {}).get("name")} for t in implant_ids],
        "missing_scopes": missing,
    }


@router.get("/{char_id}/standings", summary="NPC standings (faction / corp / agent)", responses={**ERR_404})
async def get_standings(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    rows = (
        db.query(EsiStanding)
        .filter(EsiStanding.character_id == char.character_id)
        .order_by(EsiStanding.standing.desc())
        .all()
    )
    # best-effort name resolution (public /universe/names/) — fall back to ids
    try:
        names = esi.resolve_names([s.from_id for s in rows])
    except Exception:  # noqa: BLE001
        names = {}
    return [
        {
            "from_id": s.from_id, "from_type": s.from_type,
            "name": names.get(s.from_id, {}).get("name"),
            "standing": s.standing,
        }
        for s in rows
    ]


@router.get("/{char_id}/wealth-history", summary="Wealth snapshots (liquid / assets / total) over time", responses={**ERR_404})
async def get_wealth_history(
    char_id: int,
    limit: int = Query(365, le=2000),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    rows = (
        db.query(CharacterWealthSnapshot)
        .filter(CharacterWealthSnapshot.character_id == char.character_id)
        .order_by(CharacterWealthSnapshot.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {"timestamp": r.timestamp, "liquid": r.liquid, "assets_value": r.assets_value, "total": r.total}
        for r in reversed(rows)
    ]


# ---------------------------------------------------------------------------
# Mining journal — ledger → refine → Jita value, by category, over a period
# ---------------------------------------------------------------------------

JITA_REGION = 10000002          # The Forge — mineral/ore valuation hub
_ORE_CATEGORY = 25              # invCategories: asteroid (ore / ice / moon ore)
_MOON_MATERIAL_GROUP = 427      # invGroups: raw moon materials (moon-ore output)
_CATEGORIES = ("ore", "moon_ore", "ice", "gas", "other")


def _jita_two_sided(type_ids) -> dict:
    """Per-type ``{'buy','sell'}`` from Jita (The Forge) Fuzzwork aggregates."""
    ids = [t for t in type_ids if t]
    if not ids:
        return {}
    agg = market.fuzzwork_aggregates_or_empty(JITA_REGION, ids)
    out = {}
    for tid in ids:
        s = agg.get(str(tid)) or {}
        b, se = s.get("buy") or {}, s.get("sell") or {}
        out[tid] = {"buy": b.get("percentile") or b.get("max"),
                    "sell": se.get("percentile") or se.get("min")}
    return out


def _basis_of(two: dict, basis: str):
    """Pick buy / sell / split (mid) from a ``{'buy','sell'}`` pair."""
    b, s = two.get("buy"), two.get("sell")
    if basis == "split":
        if b is not None and s is not None:
            return (b + s) / 2
        return b if b is not None else s
    return two.get(basis)


def _category_of(name, group_name, category_id, is_moon) -> str:
    n = name or ""
    if n.startswith("Fullerite-") or "Cytoserocin" in n or "Mykoserocin" in n:
        return "gas"
    if category_id == _ORE_CATEGORY:
        if group_name == "Ice":
            return "ice"
        if is_moon:
            return "moon_ore"
        return "ore"
    return "other"


def _categorize_types(eve_db: Session, type_ids: list) -> dict[int, str]:
    """{type_id: category} — ore / moon_ore / ice / gas / other. Same rules as the
    profit report's valuation, factored out so the raw ledger can tag entries too."""
    type_ids = list({t for t in type_ids if t})
    if not type_ids:
        return {}
    names = eve_repo.type_names(eve_db, type_ids)
    groups = eve_repo.type_groups(eve_db, type_ids)
    moon_mat_subq = eve_db.query(EveType.type_id).filter(EveType.group_id == _MOON_MATERIAL_GROUP)
    moon_ore_ids = {
        tid for (tid,) in eve_db.query(EveTypeMaterial.type_id)
        .filter(EveTypeMaterial.type_id.in_(type_ids),
                EveTypeMaterial.material_type_id.in_(moon_mat_subq)).distinct().all()
    }
    out = {}
    for t in type_ids:
        g = groups.get(t) or {}
        out[t] = _category_of(names.get(t), g.get("group_name"), g.get("category_id"), t in moon_ore_ids)
    return out


def _mining_value(eve_db: Session, qty_by_type: dict, basis: str,
                  base_yield: float, levels: dict) -> dict:
    """Refine each mined type → minerals (or value gas/raw directly) → Jita value,
    grouped by category. Returns ``{categories, items, total}``."""
    type_ids = [t for t, q in qty_by_type.items() if q]
    if not type_ids:
        return {"categories": {}, "items": [], "total": 0.0}

    names = eve_repo.type_names(eve_db, type_ids)
    groups = eve_repo.type_groups(eve_db, type_ids)
    moon_mat_subq = eve_db.query(EveType.type_id).filter(EveType.group_id == _MOON_MATERIAL_GROUP)
    moon_ore_ids = {
        tid for (tid,) in eve_db.query(EveTypeMaterial.type_id)
        .filter(EveTypeMaterial.type_id.in_(type_ids),
                EveTypeMaterial.material_type_id.in_(moon_mat_subq)).distinct().all()
    }
    yields = eve_repo.reprocessing_yields(eve_db, type_ids)
    ore_lvl = max((levels.get(sid, 0) for sid in skills.SKILL_ORE_PROCESSING.values()), default=0)
    ry = compute_yield(RefineSetup(
        base_yield=base_yield,
        reprocessing_lvl=levels.get(skills.SKILL_REPROCESSING, 0),
        efficiency_lvl=levels.get(skills.SKILL_REPROCESSING_EFFICIENCY, 0),
        ore_specific_lvl=ore_lvl, security="hi", tax_pct=0.0,
    ))

    # refined output per mined type (gas/unreprocessable → value the raw type)
    outputs: dict[int, dict] = {}
    for t in type_ids:
        info = yields.get(t)
        if info and info["materials"]:
            res = reprocess(qty_by_type[t], info["portion_size"], info["materials"], ry, input_type_id=t)
            outputs[t] = {m.type_id: m.qty for m in res.minerals}
        else:
            outputs[t] = {t: qty_by_type[t]}

    sides = _jita_two_sided(list({oid for outs in outputs.values() for oid in outs}))

    categories: dict[str, dict] = {}
    items = []
    total = 0.0
    for t in type_ids:
        val = sum(q * (_basis_of(sides.get(oid) or {}, basis) or 0.0) for oid, q in outputs[t].items())
        g = groups.get(t) or {}
        cat = _category_of(names.get(t), g.get("group_name"), g.get("category_id"), t in moon_ore_ids)
        c = categories.setdefault(cat, {"value": 0.0, "qty": 0})
        c["value"] += val
        c["qty"] += qty_by_type[t]
        total += val
        items.append({"type_id": t, "name": names.get(t, str(t)),
                      "category": cat, "qty": qty_by_type[t], "value": round(val, 2)})
    for c in categories.values():
        c["value"] = round(c["value"], 2)
    items.sort(key=lambda x: -x["value"])
    return {"categories": categories, "items": items, "total": round(total, 2)}


def _scope_character_ids(db: Session, user: UserDB, viewed: LinkedCharacter, scope: str) -> list[int]:
    if scope == "all":
        return [c.character_id for c in
                db.query(LinkedCharacter).filter(LinkedCharacter.user_id == user.id).all()]
    return [viewed.character_id]


def _settings_for(db: Session, character_id: int):
    return db.query(CharacterSettings).filter(CharacterSettings.character_id == character_id).first()


def _ledger_agg(db: Session, char_ids, start, end) -> dict:
    rows = (
        db.query(EsiMiningLedger.type_id, func.sum(EsiMiningLedger.quantity))
        .filter(EsiMiningLedger.character_id.in_(char_ids or [-1]),
                EsiMiningLedger.date >= start, EsiMiningLedger.date <= end)
        .group_by(EsiMiningLedger.type_id).all()
    )
    return {tid: int(q or 0) for tid, q in rows}


def _ledger_entries(db: Session, eve_db: Session, char_ids, start, end, limit: int) -> list[dict]:
    """Raw mining-ledger rows (one per day × ore × system), newest first, with type /
    system / character names resolved. ``start``/``end`` are optional date bounds."""
    q = db.query(EsiMiningLedger).filter(EsiMiningLedger.character_id.in_(char_ids or [-1]))
    if start is not None:
        q = q.filter(EsiMiningLedger.date >= start)
    if end is not None:
        q = q.filter(EsiMiningLedger.date <= end)
    rows = (q.order_by(EsiMiningLedger.date.desc(), EsiMiningLedger.quantity.desc())
            .limit(limit).all())

    names = eve_repo.type_names(eve_db, [r.type_id for r in rows])
    cats = _categorize_types(eve_db, [r.type_id for r in rows])
    sys_ids = list({r.solar_system_id for r in rows if r.solar_system_id})
    sys_names = dict(
        eve_db.query(EveSolarSystem.solar_system_id, EveSolarSystem.solar_system_name)
        .filter(EveSolarSystem.solar_system_id.in_(sys_ids or [-1])).all()
    )
    char_names = {
        c.character_id: c.character_name for c in
        db.query(LinkedCharacter).filter(LinkedCharacter.character_id.in_(char_ids or [-1])).all()
    }
    return [{
        "date": r.date.isoformat(),
        "type_id": r.type_id,
        "name": names.get(r.type_id, str(r.type_id)),
        "category": cats.get(r.type_id, "other"),
        "solar_system_id": r.solar_system_id,
        "system_name": sys_names.get(r.solar_system_id),
        "quantity": int(r.quantity or 0),
        "character_id": r.character_id,
        "character_name": char_names.get(r.character_id),
    } for r in rows]


def _compute_journal(db, eve_db, user, viewed, period_type, offset, scope, basis=None):
    s = _settings_for(db, viewed.character_id)
    tax_pct = s.mining_tax_pct if s else 0.0
    base_yield = s.refine_base_yield if s else 0.50
    use_basis = basis or (s.price_basis if s else "sell")

    char_ids = _scope_character_ids(db, user, viewed, scope)
    today = utcnow().date()
    start, end = mining_journal.period_bounds(period_type, today, offset)
    key = mining_journal.period_key(period_type, start)

    qty_by_type = _ledger_agg(db, char_ids, start, end)
    levels = {sk.skill_id: (sk.trained_level or 0)
              for sk in db.query(EsiSkill).filter(EsiSkill.character_id == viewed.character_id).all()}
    valued = _mining_value(eve_db, qty_by_type, use_basis, base_yield, levels)

    gross = valued["total"]
    tax_amount, net = mining_journal.apply_tax(gross, tax_pct)

    wo = (
        db.query(MiningTaxWriteoff)
        .filter(MiningTaxWriteoff.user_id == user.id, MiningTaxWriteoff.scope == scope,
                MiningTaxWriteoff.character_id == (None if scope == "all" else viewed.character_id),
                MiningTaxWriteoff.period_type == period_type, MiningTaxWriteoff.period_key == key)
        .first()
    )
    return {
        "period": {"type": period_type, "offset": offset, "key": key,
                   "start": start.isoformat(), "end": end.isoformat(), "scope": scope},
        "basis": use_basis, "tax_pct": tax_pct,
        "categories": {c: valued["categories"].get(c, {"value": 0.0, "qty": 0}) for c in _CATEGORIES},
        "items": valued["items"],
        "gross_value": gross, "tax_amount": tax_amount, "net_value": net,
        "written_off": wo is not None,
        "writeoff": ({"id": wo.id, "tax_pct": wo.tax_pct, "tax_amount": wo.tax_amount,
                      "net_value": wo.net_value, "created_at": wo.created_at} if wo else None),
    }


class SettingsIn(BaseModel):
    mining_tax_pct: float = 0.0
    price_basis: str = "sell"
    refine_base_yield: float = 0.50
    favorite: bool = False
    track_wealth: bool = True
    track_production: bool = True
    is_manufacturer: bool = False
    is_trader: bool = False
    group_name: Optional[str] = None


class WriteoffIn(BaseModel):
    period: str = "month"
    offset: int = 0
    scope: str = "character"


def _settings_out(s) -> dict:
    return {
        "mining_tax_pct": s.mining_tax_pct if s else 0.0,
        "price_basis": s.price_basis if s else "sell",
        "refine_base_yield": s.refine_base_yield if s else 0.50,
        "favorite": bool(s.favorite) if s else False,
        "track_wealth": bool(s.track_wealth) if s else True,
        "track_production": bool(s.track_production) if s else True,
        "is_manufacturer": bool(s.is_manufacturer) if s else False,
        "is_trader": bool(s.is_trader) if s else False,
        "group_name": (s.group_name if s else None) or None,
    }


@router.get("/groups", summary="Distinct custom group names across the user's characters")
async def list_groups(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char_ids = [c.character_id for c in
                db.query(LinkedCharacter).filter(LinkedCharacter.user_id == current_user.id).all()]
    rows = (db.query(CharacterSettings.group_name)
            .filter(CharacterSettings.character_id.in_(char_ids or [-1]),
                    CharacterSettings.group_name.isnot(None))
            .distinct().all())
    return sorted({g for (g,) in rows if g})


@router.get("/{char_id}/settings", summary="Character settings (journal knobs + role flags)", responses={**ERR_404})
async def get_settings(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    return _settings_out(_settings_for(db, char.character_id))


@router.put("/{char_id}/settings", summary="Update character settings", responses={**ERR_400, **ERR_404})
async def put_settings(
    char_id: int,
    body: SettingsIn,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    if body.price_basis not in ("buy", "sell", "split"):
        raise HTTPException(400, "price_basis must be buy | sell | split")
    s = _settings_for(db, char.character_id)
    if not s:
        s = CharacterSettings(character_id=char.character_id)
        db.add(s)
    s.mining_tax_pct = max(0.0, body.mining_tax_pct)
    s.price_basis = body.price_basis
    s.refine_base_yield = min(1.0, max(0.0, body.refine_base_yield))
    s.favorite = body.favorite
    s.track_wealth = body.track_wealth
    s.track_production = body.track_production
    s.is_manufacturer = body.is_manufacturer
    s.is_trader = body.is_trader
    s.group_name = (body.group_name or "").strip()[:60] or None
    db.commit()
    return _settings_out(s)


@router.get("/{char_id}/mining-journal", summary="Mining ledger → refine → Jita profit, by category/period", responses={**ERR_404})
async def get_mining_journal(
    char_id: int,
    period: str = Query("month", pattern="^(day|month|quarter|year)$"),
    offset: int = Query(0, ge=-120, le=0),
    scope: str = Query("character", pattern="^(character|all)$"),
    basis: Optional[str] = Query(None, pattern="^(buy|sell|split)$"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    payload = _compute_journal(db, eve_db, current_user, char, period, offset, scope, basis)

    # rolling 30-day stats (always available from ESI's window)
    s = _settings_for(db, char.character_id)
    today = utcnow().date()
    char_ids = _scope_character_ids(db, current_user, char, scope)
    levels = {sk.skill_id: (sk.trained_level or 0)
              for sk in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}
    qty30 = _ledger_agg(db, char_ids, today - datetime.timedelta(days=30), today)
    v30 = _mining_value(eve_db, qty30, payload["basis"], s.refine_base_yield if s else 0.50, levels)
    payload["stats_30d"] = {
        "total": v30["total"],
        "categories": {c: v30["categories"].get(c, {"value": 0.0, "qty": 0}) for c in _CATEGORIES},
    }
    return payload


@router.get("/{char_id}/mining-ledger", summary="Raw mining ledger entries (date × ore × system), newest first", responses={**ERR_404})
async def get_mining_ledger(
    char_id: int,
    period: Optional[str] = Query(None, pattern="^(day|month|quarter|year)$"),
    offset: int = Query(0, ge=-120, le=0),
    scope: str = Query("character", pattern="^(character|all)$"),
    limit: int = Query(500, ge=1, le=2000),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    char_ids = _scope_character_ids(db, current_user, char, scope)

    start = end = key = None
    if period:
        start, end = mining_journal.period_bounds(period, utcnow().date(), offset)
        key = mining_journal.period_key(period, start)

    entries = _ledger_entries(db, eve_db, char_ids, start, end, limit)
    return {
        "scope": scope,
        "period": ({"type": period, "offset": offset, "key": key,
                    "start": start.isoformat(), "end": end.isoformat()} if period else None),
        "count": len(entries),
        "total_quantity": sum(e["quantity"] for e in entries),
        "entries": entries,
    }


@router.post("/{char_id}/mining-journal/writeoff", summary="Write off (record) tax for a period", responses={**ERR_400, **ERR_404})
async def writeoff_tax(
    char_id: int,
    body: WriteoffIn,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    if body.period not in mining_journal.PERIODS:
        raise HTTPException(400, "bad period")
    if body.scope not in ("character", "all"):
        raise HTTPException(400, "bad scope")
    char = _owned_char(db, char_id, current_user)
    j = _compute_journal(db, eve_db, current_user, char, body.period, body.offset, body.scope)

    rec = (
        db.query(MiningTaxWriteoff)
        .filter(MiningTaxWriteoff.user_id == current_user.id, MiningTaxWriteoff.scope == body.scope,
                MiningTaxWriteoff.character_id == (None if body.scope == "all" else char.character_id),
                MiningTaxWriteoff.period_type == body.period,
                MiningTaxWriteoff.period_key == j["period"]["key"])
        .first()
    )
    if not rec:
        rec = MiningTaxWriteoff(
            user_id=current_user.id,
            character_id=(None if body.scope == "all" else char.character_id),
            scope=body.scope, period_type=body.period, period_key=j["period"]["key"],
        )
        db.add(rec)
    rec.gross_value = j["gross_value"]
    rec.tax_pct = j["tax_pct"]
    rec.tax_amount = j["tax_amount"]
    rec.net_value = j["net_value"]
    rec.created_at = utcnow()
    db.commit()
    return {"id": rec.id, "period_key": rec.period_key, "tax_pct": rec.tax_pct,
            "tax_amount": rec.tax_amount, "net_value": rec.net_value, "created_at": rec.created_at}


@router.delete("/{char_id}/mining-journal/writeoff", status_code=204, summary="Undo a tax write-off", responses={**ERR_404})
async def undo_writeoff(
    char_id: int,
    period: str = Query(...),
    offset: int = Query(0),
    scope: str = Query("character"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    today = utcnow().date()
    start, _ = mining_journal.period_bounds(period, today, offset)
    key = mining_journal.period_key(period, start)
    (db.query(MiningTaxWriteoff)
     .filter(MiningTaxWriteoff.user_id == current_user.id, MiningTaxWriteoff.scope == scope,
             MiningTaxWriteoff.character_id == (None if scope == "all" else char.character_id),
             MiningTaxWriteoff.period_type == period, MiningTaxWriteoff.period_key == key)
     .delete(synchronize_session=False))
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Deep integration — import ESI data into the user's own tables
# ---------------------------------------------------------------------------

@router.post("/{char_id}/import/assets", summary="Import assets into IndyOps inventory", responses={**ERR_400, **ERR_404})
async def import_assets(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    assets = db.query(EsiAsset).filter(EsiAsset.character_id == char.character_id).all()
    if not assets:
        raise HTTPException(400, "No synced assets to import — run a sync first")

    # aggregate by type so we create one inventory line per item type, not per stack
    agg: dict = {}
    for a in assets:
        if not a.type_id:
            continue
        agg[a.type_id] = agg.get(a.type_id, 0) + (a.quantity or 0)

    names = _type_names(eve_db, list(agg))
    now = utcnow()
    imported = 0
    for type_id, qty in agg.items():
        meta = names.get(type_id, {})
        db.add(InventoryItem(
            user_id=current_user.id,
            eve_type_id=type_id,
            name=meta.get("name") or f"Type {type_id}",
            volume=meta.get("volume"),
            quantity=qty,
            flow="input",
            item_status="in_stock",
            place=f"{char.character_name} (EVE)",
            note="Imported from EVE assets",
            created_at=now,
        ))
        imported += 1
    db.commit()
    return {"imported": imported, "source_stacks": len(assets)}


@router.post("/{char_id}/import/industry-jobs", summary="Import industry jobs into production", responses={**ERR_400, **ERR_404})
async def import_industry_jobs(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    jobs = db.query(EsiIndustryJob).filter(EsiIndustryJob.character_id == char.character_id).all()
    if not jobs:
        raise HTTPException(400, "No synced industry jobs to import — run a sync first")

    names = _type_names(eve_db, [j.product_type_id for j in jobs] + [j.blueprint_type_id for j in jobs])
    now = utcnow()
    imported, skipped = 0, 0
    for j in jobs:
        if not j.product_type_id:
            skipped += 1
            continue
        code = f"ESI-{j.job_id}"
        if db.query(ProductionJob).filter(
                ProductionJob.user_id == current_user.id, ProductionJob.code == code).first():
            skipped += 1
            continue
        db.add(ProductionJob(
            user_id=current_user.id,
            blueprint_type_id=j.blueprint_type_id,
            blueprint_name=names.get(j.blueprint_type_id, {}).get("name"),
            product_type_id=j.product_type_id,
            product_name=names.get(j.product_type_id, {}).get("name") or f"Type {j.product_type_id}",
            runs=j.runs or 1,
            status=_JOB_STATUS_MAP.get(j.status, ProductionStatus.PLANNING),
            code=code,
            note=f"Imported from EVE industry job {j.job_id} ({_ACTIVITY_NAMES.get(j.activity_id, 'Other')})",
            date_planned=j.start_date or now,
            created_at=now,
        ))
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped}
