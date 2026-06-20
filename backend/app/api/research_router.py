"""
Blueprint-research endpoints: copying cost/time and ME/TE research payback.

Mounted under ``/api/v1/manufacturing/research``. Pulls the chosen character's
skills (time multipliers) and the chosen facility's per-activity system cost
index (persisted by the cost-index worker, see [[indyops-io13-ore-refining]]),
then runs the pure ``services.research`` math.
"""
from __future__ import annotations
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market
from app.core.database import get_db, Facility, LinkedCharacter, EsiSkill, UserDB
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.repositories import cost_index_repo as ci_repo
from app.services import research as research_svc
from app.services import skills as skills_svc
from app.services import invention as inv_svc
from app.services.invention import Material
from app.services.invention_opt import OptInput
from app.adapters import invention_optimizer as inv_opt

router = APIRouter()

# ESI cost-index activity keys per industry activity.
_INDEX_KEY = {
    eve_repo.MANUFACTURING: ci_repo.ACT_MANUFACTURING,
    eve_repo.COPYING: ci_repo.ACT_COPYING,
    eve_repo.ME_RESEARCH: ci_repo.ACT_ME_RESEARCH,
    eve_repo.TE_RESEARCH: ci_repo.ACT_TE_RESEARCH,
    eve_repo.INVENTION: ci_repo.ACT_INVENTION,
}


class MaterialPrice(BaseModel):
    type_id: int
    unit_cost: float


class CopyRequest(BaseModel):
    product_type_id: Optional[int] = None
    blueprint_type_id: Optional[int] = None
    facility_id: Optional[int] = None
    character_id: Optional[int] = None       # LinkedCharacter.id
    runs_per_copy: Optional[int] = None       # default = blueprint max runs
    copies: int = 1


class MeTeRequest(BaseModel):
    product_type_id: Optional[int] = None
    blueprint_type_id: Optional[int] = None
    facility_id: Optional[int] = None
    character_id: Optional[int] = None
    from_me: int = 0
    to_me: int = 10
    from_te: int = 0
    to_te: int = 20
    material_prices: List[MaterialPrice] = []  # optional overrides; else ESI adjusted


# ── shared resolution helpers ─────────────────────────────────────────────────

class _BP:
    """Resolved blueprint context (manufacturing side) + research/copy base times."""
    def __init__(self, eve_db, product_type_id, blueprint_type_id):
        bp = None
        if product_type_id:
            bp = eve_repo.blueprint_for_product(eve_db, product_type_id)
            if not bp:
                raise HTTPException(404, "No manufacturing blueprint for that product")
            blueprint_type_id = bp.blueprint_type_id
            qty_per_run = bp.qty_per_run
        elif blueprint_type_id:
            prod = eve_repo.product_for_blueprint(eve_db, blueprint_type_id)
            if not prod:
                raise HTTPException(404, "Blueprint not found")
            product_type_id = prod["product_type_id"]
            qty_per_run = prod["qty_per_run"]
        else:
            raise HTTPException(400, "Provide product_type_id or blueprint_type_id")

        self.blueprint_type_id = blueprint_type_id
        self.product_type_id = product_type_id
        self.qty_per_run = qty_per_run
        self.materials = eve_repo.materials(eve_db, blueprint_type_id, eve_repo.MANUFACTURING)
        self.manuf_time = eve_repo.base_time(eve_db, blueprint_type_id, eve_repo.MANUFACTURING)
        self.me_time = eve_repo.base_time(eve_db, blueprint_type_id, eve_repo.ME_RESEARCH)
        self.te_time = eve_repo.base_time(eve_db, blueprint_type_id, eve_repo.TE_RESEARCH)
        self.copy_time = eve_repo.base_time(eve_db, blueprint_type_id, eve_repo.COPYING)
        self.max_runs = eve_repo.max_runs(eve_db, blueprint_type_id)
        names = eve_repo.type_names(eve_db, [blueprint_type_id, product_type_id])
        self.blueprint_name = names.get(blueprint_type_id)
        self.product_name = names.get(product_type_id)


def _skill_levels(db: Session, user_id: int, character_id: Optional[int]) -> dict[int, int]:
    """Raw ``{skill_id: trained_level}`` for one of the user's characters ({} if none)."""
    if not character_id:
        return {}
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == character_id, LinkedCharacter.user_id == user_id).first()
    if not char:
        return {}
    return {s.skill_id: (s.trained_level or 0)
            for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}


def _profile(db: Session, user_id: int, character_id: Optional[int]):
    """IndustryProfile (skill time multipliers) for one of the user's characters, or None."""
    if not character_id:
        return None
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == character_id, LinkedCharacter.user_id == user_id).first()
    if not char:
        return None
    levels = {s.skill_id: (s.trained_level or 0)
              for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}
    return skills_svc.profile_from(char.character_id, char.character_name, levels)


def _facility(db: Session, user_id: int, facility_id: Optional[int]):
    if not facility_id:
        return None
    return db.query(Facility).filter(
        Facility.id == facility_id, Facility.user_id == user_id).first()


def _index_for(db: Session, fac: Optional[Facility], activity: int) -> float:
    """Per-activity system cost index for a facility: persisted table → manual SCI → 0."""
    if not fac:
        return 0.0
    key = _INDEX_KEY.get(activity)
    if fac.solar_system_id and key:
        idx = ci_repo.index_for(db, fac.solar_system_id, key, default=-1.0)
        if idx >= 0:
            return idx
    return float(fac.system_cost_index or 0.0)  # manual fallback (manufacturing index)


def _adjusted_prices() -> dict:
    try:
        return market.esi_adjusted_prices()
    except Exception:
        return {}


def _eiv_1run(materials: list[dict], adjusted: dict) -> float:
    """Estimated Item Value for one run: Σ base material qty × ESI adjusted price."""
    return sum(m["base_qty"] * adjusted.get(m["type_id"], 0.0) for m in materials)


def _profile_out(p) -> Optional[dict]:
    if not p:
        return None
    return {
        "character_id": p.character_id, "character_name": p.character_name,
        "advanced_industry_lvl": p.advanced_industry_lvl,
        "science_lvl": p.science_lvl, "research_lvl": p.research_lvl,
        "metallurgy_lvl": p.metallurgy_lvl,
        "copy_time_mult": round(p.copy_time_mult, 4),
        "me_research_time_mult": round(p.me_research_time_mult, 4),
        "te_research_time_mult": round(p.te_research_time_mult, 4),
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/copy")
async def copy_cost(body: CopyRequest,
                    current_user: UserDB = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    eve_db = EveSessionLocal()
    try:
        bp = _BP(eve_db, body.product_type_id, body.blueprint_type_id)
    finally:
        eve_db.close()

    prof = _profile(db, current_user.id, body.character_id)
    fac = _facility(db, current_user.id, body.facility_id)
    adjusted = _adjusted_prices()

    runs_per_copy = body.runs_per_copy or bp.max_runs or 1
    time_mult = prof.copy_time_mult if prof else 1.0
    copy_index = _index_for(db, fac, eve_repo.COPYING)
    cost_role = float(fac.cost_bonus or 0.0) if fac else 0.0
    tax = float(fac.tax or 0.0) if fac else 0.0

    plan = research_svc.copy_plan(
        base_copy_time_per_run=bp.copy_time,
        manuf_eiv_1run=_eiv_1run(bp.materials, adjusted),
        runs_per_copy=runs_per_copy, copies=body.copies,
        copy_index=copy_index, cost_role_pct=cost_role,
        facility_tax_pct=tax, time_mult=time_mult,
    )
    return {
        "blueprint_type_id": bp.blueprint_type_id, "blueprint_name": bp.blueprint_name,
        "product_type_id": bp.product_type_id, "product_name": bp.product_name,
        "base_copy_time_per_run_s": bp.copy_time, "max_runs": bp.max_runs,
        "facility": _facility_out(fac, copy_index), "character": _profile_out(prof),
        "copy": plan,
        "prices_available": bool(adjusted),
    }


@router.post("/me-te")
async def me_te_payback(body: MeTeRequest,
                        current_user: UserDB = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    eve_db = EveSessionLocal()
    try:
        bp = _BP(eve_db, body.product_type_id, body.blueprint_type_id)
    finally:
        eve_db.close()

    prof = _profile(db, current_user.id, body.character_id)
    fac = _facility(db, current_user.id, body.facility_id)
    adjusted = _adjusted_prices()

    # Material valuation: client overrides, else ESI adjusted price.
    overrides = {p.type_id: p.unit_cost for p in body.material_prices}
    priced = [{**m, "unit_price": overrides.get(m["type_id"], adjusted.get(m["type_id"], 0.0))}
              for m in bp.materials]
    eiv = _eiv_1run(bp.materials, adjusted)

    cost_role = float(fac.cost_bonus or 0.0) if fac else 0.0
    tax = float(fac.tax or 0.0) if fac else 0.0
    me_index = _index_for(db, fac, eve_repo.ME_RESEARCH)
    te_index = _index_for(db, fac, eve_repo.TE_RESEARCH)
    me_mult = prof.me_research_time_mult if prof else 1.0
    te_mult = prof.te_research_time_mult if prof else 1.0

    from_me = _clamp(body.from_me, 0, research_svc.MAX_ME)
    to_me = _clamp(body.to_me, 0, research_svc.MAX_ME)
    from_te = _clamp(body.from_te, 0, research_svc.MAX_TE)
    to_te = _clamp(body.to_te, 0, research_svc.MAX_TE)

    # ── ME ──
    mat_rows, saving = research_svc.me_material_savings(priced, from_me, to_me)
    me_cost = research_svc.research_cost(eiv, from_me, to_me, me_index, cost_role, tax)
    me_time = research_svc.research_time(bp.me_time, from_me, to_me, me_mult)
    me_block = {
        "from": from_me, "to": to_me,
        "research_time_s": me_time,
        "research_cost": vars(me_cost),
        "materials": mat_rows,
        "saving_per_run": saving,
        "payback_runs": research_svc.payback_runs(me_cost.install_cost, saving),
        "no_effect_materials": [r["name"] for r in mat_rows if r["me_no_effect"]],
    }

    # ── TE ── (TE levels step 2%: te value = 2 × research level; 10 levels → TE 20)
    te_cost = research_svc.research_cost(eiv, from_te // 2, to_te // 2, te_index, cost_role, tax)
    te_time = research_svc.research_time(bp.te_time, from_te // 2, to_te // 2, te_mult)
    per_run_time_saving = research_svc.te_time_saving_per_run(bp.manuf_time, from_te, to_te)
    te_block = {
        "from": from_te, "to": to_te,
        "research_time_s": te_time,
        "research_cost": vars(te_cost),
        "manuf_time_from_s": research_svc.adj_time(bp.manuf_time, 1, from_te),
        "manuf_time_to_s": research_svc.adj_time(bp.manuf_time, 1, to_te),
        "saving_per_run_s": per_run_time_saving,
        "time_payback_runs": research_svc.time_payback_runs(te_time, per_run_time_saving),
    }

    return {
        "blueprint_type_id": bp.blueprint_type_id, "blueprint_name": bp.blueprint_name,
        "product_type_id": bp.product_type_id, "product_name": bp.product_name,
        "estimated_item_value": round(eiv, 2),
        "facility": _facility_out(fac, None, me_index, te_index),
        "character": _profile_out(prof),
        "me": me_block, "te": te_block,
        "prices_available": bool(adjusted),
    }


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _facility_out(fac, copy_index=None, me_index=None, te_index=None) -> Optional[dict]:
    if not fac:
        return None
    out = {"id": fac.id, "name": fac.name, "system_name": fac.system_name,
           "cost_bonus_pct": fac.cost_bonus or 0.0, "tax_pct": fac.tax or 0.0}
    if copy_index is not None:
        out["copy_index"] = copy_index
    if me_index is not None:
        out["me_index"] = me_index
    if te_index is not None:
        out["te_index"] = te_index
    return out


# ── invention ─────────────────────────────────────────────────────────────────

class InventionRequest(BaseModel):
    product_type_id: Optional[int] = None       # T1 item or blueprint to invent from
    blueprint_type_id: Optional[int] = None
    final_product_type_id: Optional[int] = None  # chosen T2 item (default: first)
    decryptor: str = "No Decryptor"
    runs: int = 10
    facility_id: Optional[int] = None
    character_id: Optional[int] = None
    reference_bpc_price: Optional[float] = None  # contract price of the T2 BPC to compare


class OptimizeRequest(BaseModel):
    product_type_id: Optional[int] = None
    blueprint_type_id: Optional[int] = None
    facility_id: Optional[int] = None
    character_id: Optional[int] = None
    weights: Optional[dict] = None


_DISP_2 = ("cost_per_attempt", "cost_per_bpc", "cost_per_run", "manuf_cost_per_run",
           "sell_per_unit", "cost_per_unit", "profit_per_unit", "profit_per_run",
           "margin_pct", "score")


def _round_row(r: dict) -> dict:
    out = dict(r)
    if out.get("probability") is not None:
        out["probability"] = round(out["probability"], 4)
    for k in _DISP_2:
        if out.get(k) is not None:
            out[k] = round(out[k], 2)
    return out


def _classify_invention_skills(skill_ids, names, levels) -> tuple[int, int, int]:
    """Split a blueprint's invention skills into (encryption lvl, science1 lvl, science2 lvl)."""
    enc, sci = 0, []
    for sid in skill_ids:
        lvl = int(levels.get(sid, 0) or 0)
        if "Encryption" in (names.get(sid) or ""):
            enc = lvl
        else:
            sci.append(lvl)
    return enc, (sci[0] if sci else 0), (sci[1] if len(sci) > 1 else 0)


def _invention_ctx(eve_db, db, user_id, bp, fac, levels, adjusted):
    """Build the per-product :class:`OptInput` list + datacore/skill context for a
    T1 blueprint. Raises 404 if the blueprint has no invention products."""
    inv_products = eve_repo.invention_products(eve_db, bp.blueprint_type_id)
    if not inv_products:
        raise HTTPException(404, "This blueprint is not a T1 invention source")

    datacores = eve_repo.materials(eve_db, bp.blueprint_type_id, eve_repo.INVENTION)
    datacore_cost = sum(d["base_qty"] * adjusted.get(d["type_id"], 0.0) for d in datacores)

    skill_ids = eve_repo.invention_skill_ids(eve_db, bp.blueprint_type_id)
    skill_names = eve_repo.type_names(eve_db, skill_ids)
    enc, sci1, sci2 = _classify_invention_skills(skill_ids, skill_names, levels)

    manuf_index = _index_for(db, fac, eve_repo.MANUFACTURING)
    inv_index = _index_for(db, fac, eve_repo.INVENTION)
    cost_role = float(fac.cost_bonus or 0.0) if fac else 0.0
    tax = float(fac.tax or 0.0) if fac else 0.0

    products: list[OptInput] = []
    for ip in inv_products:
        t2_bpc = ip["product_type_id"]
        t2 = eve_repo.product_for_blueprint(eve_db, t2_bpc)
        if not t2:
            continue
        t2_item = t2["product_type_id"]
        t2_mats = eve_repo.materials(eve_db, t2_bpc, eve_repo.MANUFACTURING)
        t2_eiv = sum(m["base_qty"] * adjusted.get(m["type_id"], 0.0) for m in t2_mats)
        name = eve_repo.type_names(eve_db, [t2_item]).get(t2_item, str(t2_item))
        manuf_install = t2_eiv * (manuf_index * (1 - cost_role / 100)
                                  + tax / 100 + inv_svc.SCC_SURCHARGE)
        products.append(OptInput(
            product_type_id=t2_item, product_name=name,
            base_prob=ip["probability"], base_runs=ip["base_runs"],
            units_per_run=t2["qty_per_run"],
            datacore_cost=datacore_cost,
            invention_install_cost=inv_svc.invention_install(t2_eiv, inv_index, cost_role, tax),
            manuf_install_per_run=manuf_install,
            sell_per_unit=adjusted.get(t2_item, 0.0),
            materials=[Material(qty=m["base_qty"], price=adjusted.get(m["type_id"], 0.0)) for m in t2_mats],
            mat_extra_mult=1.0, encryption=enc, sci1=sci1, sci2=sci2,
        ))
    if not products:
        raise HTTPException(404, "Invention products have no manufacturing recipe")

    meta = {
        "datacores": [{"type_id": d["type_id"], "name": d["name"], "qty": d["base_qty"]} for d in datacores],
        "datacore_cost": round(datacore_cost, 2),
        "skills": {"encryption": enc, "science_1": sci1, "science_2": sci2},
        "invention_index": inv_index, "manufacturing_index": manuf_index,
    }
    return products, meta


@router.post("/invention/options")
async def invention_options(body: OptimizeRequest,
                            current_user: UserDB = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Available T2 products + decryptors + the character's invention skills."""
    eve_db = EveSessionLocal()
    try:
        bp = _BP(eve_db, body.product_type_id, body.blueprint_type_id)
        levels = _skill_levels(db, current_user.id, body.character_id)
        fac = _facility(db, current_user.id, body.facility_id)
        products, meta = _invention_ctx(eve_db, db, current_user.id, bp, fac, levels, _adjusted_prices())
    finally:
        eve_db.close()
    return {
        "blueprint_type_id": bp.blueprint_type_id, "blueprint_name": bp.blueprint_name,
        "products": [{"product_type_id": p.product_type_id, "product_name": p.product_name,
                      "base_runs": p.base_runs, "base_probability": p.base_prob} for p in products],
        "decryptors": [d.name for d in inv_svc.DECRYPTORS],
        **meta,
    }


@router.post("/invention")
async def invention(body: InventionRequest,
                    current_user: UserDB = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Economics of one invention config (product + decryptor) over ``runs`` attempts."""
    eve_db = EveSessionLocal()
    try:
        bp = _BP(eve_db, body.product_type_id, body.blueprint_type_id)
        levels = _skill_levels(db, current_user.id, body.character_id)
        fac = _facility(db, current_user.id, body.facility_id)
        adjusted = _adjusted_prices()
        products, meta = _invention_ctx(eve_db, db, current_user.id, bp, fac, levels, adjusted)
    finally:
        eve_db.close()

    prod = next((p for p in products if p.product_type_id == body.final_product_type_id), products[0])
    dec = inv_svc.DECRYPTOR_BY_NAME.get(body.decryptor, inv_svc.DECRYPTORS[0])
    dprice = adjusted.get(dec.type_id, 0.0) if dec.type_id else 0.0

    row = inv_svc.evaluate(
        base_prob=prod.base_prob, base_runs=prod.base_runs, units_per_run=prod.units_per_run,
        datacore_cost=prod.datacore_cost, decryptor_price=dprice,
        invention_install_cost=prod.invention_install_cost,
        manuf_install_per_run=prod.manuf_install_per_run, sell_per_unit=prod.sell_per_unit,
        materials=prod.materials, mat_extra_mult=prod.mat_extra_mult,
        encryption=prod.encryption, sci1=prod.sci1, sci2=prod.sci2, decryptor=dec)

    runs = max(1, int(body.runs))
    prob = row["probability"]
    expected = runs * prob
    total_cost = runs * row["cost_per_attempt"]

    compare = None
    ref = body.reference_bpc_price
    if ref and row["cost_per_bpc"] is not None:
        compare = {
            "reference_bpc_price": round(ref, 2),
            "our_cost_per_bpc": round(row["cost_per_bpc"], 2),
            "savings_per_bpc": round(ref - row["cost_per_bpc"], 2),
            "cheaper_to_invent": row["cost_per_bpc"] < ref,
        }

    return {
        "blueprint_type_id": bp.blueprint_type_id, "blueprint_name": bp.blueprint_name,
        "final_product_type_id": prod.product_type_id, "final_product_name": prod.product_name,
        "decryptor": dec.name, "runs": runs,
        "expected_successful_bpcs": round(expected, 2),
        "total_cost": round(total_cost, 2),
        "datacore_cost_per_attempt": meta["datacore_cost"],
        "decryptor_price": round(dprice, 2),
        "result": _round_row(row),
        "reference": compare,
        "facility": _facility_out(fac),
        "skills": meta["skills"],
        "products": [{"product_type_id": p.product_type_id, "product_name": p.product_name} for p in products],
        "decryptors": [d.name for d in inv_svc.DECRYPTORS],
    }


@router.post("/invention/optimize")
async def invention_optimize(body: OptimizeRequest,
                             current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Sweep every (T2 product × decryptor) and rank by production profitability."""
    eve_db = EveSessionLocal()
    try:
        bp = _BP(eve_db, body.product_type_id, body.blueprint_type_id)
        levels = _skill_levels(db, current_user.id, body.character_id)
        fac = _facility(db, current_user.id, body.facility_id)
        adjusted = _adjusted_prices()
        products, meta = _invention_ctx(eve_db, db, current_user.id, bp, fac, levels, adjusted)
    finally:
        eve_db.close()

    prices = {tid: adjusted.get(tid, 0.0) for tid in inv_svc.DECRYPTOR_TYPE_IDS}
    ranked, engine = inv_opt.optimize(products, inv_svc.DECRYPTORS, prices, body.weights)
    return {
        "blueprint_type_id": bp.blueprint_type_id, "blueprint_name": bp.blueprint_name,
        "engine": engine,
        "facility": _facility_out(fac),
        "skills": meta["skills"], "datacore_cost": meta["datacore_cost"],
        "ranked": [_round_row(r) for r in ranked],
        "prices_available": bool(adjusted),
    }
