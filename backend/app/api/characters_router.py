import datetime
import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import esi
from app.core import config
from app.core.database import (
    get_db, SessionLocal, UserDB,
    LinkedCharacter, EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract, EsiIndustryJob,
    InventoryItem, ProductionJob,
)
from app.core.database_eve import EveSessionLocal, EveType, EveStation
from app.core.schemas import ProductionStatus
from app.core.security import get_current_user

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

@router.get("/sso/login", summary="Get the EVE SSO login URL")
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

    now = datetime.datetime.utcnow()
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

def _char_out(c: LinkedCharacter) -> dict:
    return {
        "id": c.id,
        "character_id": c.character_id,
        "character_name": c.character_name,
        "corporation_id": c.corporation_id,
        "alliance_id": c.alliance_id,
        "portrait": f"https://images.evetech.net/characters/{c.character_id}/portrait?size=128",
        "is_active": c.is_active,
        "status": c.status,
        "scopes": (c.scopes or "").split() if c.scopes else [],
        "wallet_balance": c.wallet_balance,
        "total_sp": c.total_sp,
        "last_sync_at": c.last_sync_at,
        "added_at": c.added_at,
    }


@router.get("/", summary="List my linked EVE characters")
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
    return [_char_out(c) for c in chars]


class CharacterPatch(BaseModel):
    is_active: Optional[bool] = None


@router.patch("/{char_id}", summary="Toggle a character's activation status")
async def patch_character(
    char_id: int,
    patch: CharacterPatch,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    if patch.is_active is not None:
        char.is_active = patch.is_active
        char.updated_at = datetime.datetime.utcnow()
        db.commit()
    return _char_out(char)


@router.delete("/{char_id}", status_code=204, summary="Unlink a character (and its synced data)")
async def delete_character(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _owned_char(db, char_id, current_user)
    cid = char.character_id
    for model in (EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract, EsiIndustryJob):
        db.query(model).filter(model.character_id == cid).delete(synchronize_session=False)
    db.delete(char)
    db.commit()
    return None


@router.post("/{char_id}/sync", summary="Trigger an ESI sync for one character now")
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

@router.get("/{char_id}/wallet", summary="Wallet balance + transactions")
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


@router.get("/{char_id}/skills", summary="Trained skills")
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


@router.get("/{char_id}/assets", summary="Assets (inventory)")
async def get_assets(
    char_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    eve_db: Session = Depends(_get_eve_db),
):
    char = _owned_char(db, char_id, current_user)
    assets = db.query(EsiAsset).filter(EsiAsset.character_id == char.character_id).all()
    names = _type_names(eve_db, [a.type_id for a in assets])
    stations = _station_names(eve_db, [a.location_id for a in assets])
    return [
        {
            "item_id": a.item_id, "type_id": a.type_id,
            "type_name": names.get(a.type_id, {}).get("name"),
            "quantity": a.quantity, "location_id": a.location_id,
            "location_name": stations.get(a.location_id),
            "location_flag": a.location_flag,
        }
        for a in assets
    ]


@router.get("/{char_id}/contracts", summary="Contracts")
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


@router.get("/{char_id}/industry-jobs", summary="Industry jobs (production chains)")
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
    return [
        {
            "job_id": j.job_id, "activity_id": j.activity_id,
            "activity": _ACTIVITY_NAMES.get(j.activity_id, "Other"),
            "blueprint_type_id": j.blueprint_type_id,
            "blueprint_name": names.get(j.blueprint_type_id, {}).get("name"),
            "product_type_id": j.product_type_id,
            "product_name": names.get(j.product_type_id, {}).get("name"),
            "runs": j.runs, "status": j.status, "cost": j.cost,
            "start_date": j.start_date, "end_date": j.end_date,
        }
        for j in jobs
    ]


# ---------------------------------------------------------------------------
# Deep integration — import ESI data into the user's own tables
# ---------------------------------------------------------------------------

@router.post("/{char_id}/import/assets", summary="Import assets into IndyOps inventory")
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
    now = datetime.datetime.utcnow()
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


@router.post("/{char_id}/import/industry-jobs", summary="Import industry jobs into production")
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
    now = datetime.datetime.utcnow()
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
