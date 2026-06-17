"""
Ore Acquisition & Refining Optimization (IO-13).

Compares three ways to acquire a basket of minerals at a target system — buy the
minerals, buy raw ore and refine, or buy compressed ore and refine — with transport
and refining yield/tax folded in, and recommends the cheapest path. Also exposes a
standalone reprocessing calculator and the ore/mineral/rig catalogs the UI needs.

Market prices come from Fuzzwork (trade hubs, per region) and the C-J6MT scrape
(``market.gnf_local``); the buy/sell basis + scam-guard fallback is the shared
``pricing.resolve_price``. Transport reuses the delivery service; refining yield is
``refining.compute_yield``; the comparison maths is ``ore_acquisition.compare``.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market
from app.core.database import UserDB, get_db, LinkedCharacter, EsiSkill
from app.core.database_eve import EveSessionLocal, EveSolarSystem, EveType
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.services import delivery as dsvc
from app.services import facility_bonus
from app.services import ore_acquisition as oa
from app.services import pricing
from app.services import skills as skills_svc
from app.services.refining import RefineSetup, RigYield, compute_yield, reprocess

router = APIRouter()
logger = logging.getLogger(__name__)

# Preset trade hubs (region id + hub system for distance). The UI offers these plus
# C-J6MT and free-text region/system search; the request carries whatever was picked.
HUBS = [
    {"key": "jita", "label": "Jita (The Forge)", "region_id": 10000002, "system_name": "Jita"},
    {"key": "amarr", "label": "Amarr (Domain)", "region_id": 10000043, "system_name": "Amarr"},
    {"key": "dodixie", "label": "Dodixie (Sinq Laison)", "region_id": 10000032, "system_name": "Dodixie"},
    {"key": "rens", "label": "Rens (Heimatar)", "region_id": 10000030, "system_name": "Rens"},
    {"key": "hek", "label": "Hek (Metropolis)", "region_id": 10000042, "system_name": "Hek"},
]
CJ_SOURCE = {"key": "cj", "label": "C-J6MT", "region_id": None, "system_name": "C-J6MT-A", "cj": True}


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_system(eve_db: Session, name: Optional[str]) -> Optional[EveSolarSystem]:
    if not name:
        return None
    return (
        eve_db.query(EveSolarSystem)
        .filter(EveSolarSystem.solar_system_name.ilike(name.strip()))
        .first()
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SourceIn(BaseModel):
    key: str
    label: str
    region_id: Optional[int] = None        # Fuzzwork region (None for the C-J scrape)
    system_name: Optional[str] = None      # for transport distance to target
    cj: bool = False                       # use the C-J6MT local-market scrape


class NeedIn(BaseModel):
    type_id: int
    qty: float = 0.0


class RefineIn(BaseModel):
    base_yield: float = 0.50               # structure/station base, 0..1
    reprocessing_lvl: int = 0
    efficiency_lvl: int = 0
    ore_specific_lvl: int = 0
    implant_pct: float = 0.0               # 0 / 1 / 2 / 4
    rig_type_ids: List[int] = []
    tax_pct: float = 0.0


class ShippingIn(BaseModel):
    mode: str = "regular"                  # regular | jf
    isk_per_jump_m3: float = 0.0
    jf_ship: Optional[str] = None
    isotopes_per_ly: float = 0.0
    isotope_price: float = 0.0
    round_trip: bool = False


class CompareRequest(BaseModel):
    target_system: Optional[str] = None
    needs: List[NeedIn]
    sources: List[SourceIn]
    analyze_mode: str = "all"              # minerals | raw | compressed | all
    basis: str = "sell"                    # buy | sell (price side you pay)
    refine: RefineIn = RefineIn()
    shipping: ShippingIn = ShippingIn()
    unrealistic_ratio: float = 0.3
    volatility_alert: bool = True
    low_vol_threshold: float = 0.02        # daily-return stdev below this → alert


class GasCompareRequest(BaseModel):
    target_system: Optional[str] = None
    needs: List[NeedIn]                    # type_id = the regular gas
    sources: List[SourceIn]
    basis: str = "sell"
    decompression_loss_pct: float = 5.0    # % lost decompressing (editable; ~5 typical)
    shipping: ShippingIn = ShippingIn()
    unrealistic_ratio: float = 0.3
    volatility_alert: bool = True
    low_vol_threshold: float = 0.02


class ReprocessItem(BaseModel):
    type_id: int
    qty: int


class ReprocessRequest(BaseModel):
    items: List[ReprocessItem]
    refine: RefineIn = RefineIn()
    system_name: Optional[str] = None      # derives the rig security band (else hi)
    region_id: Optional[int] = None        # value minerals at this region (optional)
    basis: str = "sell"


# ---------------------------------------------------------------------------
# Pricing helpers (mirror the chain calculator's multi-source flow)
# ---------------------------------------------------------------------------

def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _region_two_sided(region_id: int, type_ids: list[int]) -> dict[int, dict]:
    """Per-type ``{'buy','sell'}`` from one region's Fuzzwork aggregate (one fetch)."""
    agg = market.fuzzwork_aggregates_or_empty(region_id, type_ids)
    out: dict[int, dict] = {}
    for tid in type_ids:
        s = agg.get(str(tid)) or {}
        b = s.get("buy") or {}
        se = s.get("sell") or {}
        out[tid] = {
            "buy": _fnum(b.get("percentile") or b.get("max")),
            "sell": _fnum(se.get("percentile") or se.get("min")),
        }
    return out


async def _cj_two_sided(type_ids: list[int]) -> dict[int, dict]:
    """{'buy','sell'} per type from the C-J6MT scrape (parallel, best-effort)."""
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = await asyncio.gather(
            *[loop.run_in_executor(ex, market.gnf_local, tid) for tid in type_ids]
        )
    out: dict[int, dict] = {}
    for tid, p in zip(type_ids, results):
        if p:
            out[tid] = {"buy": _fnum(p.get("buy")), "sell": _fnum(p.get("sell"))}
    return out


def _cost_per_m3(eve_db: Session, src_system: Optional[str], dst: Optional[EveSolarSystem],
                 shipping: ShippingIn) -> tuple[float, Optional[str]]:
    """Transport rate (ISK/m³) from a source system to the target. (rate, warning)."""
    src = _resolve_system(eve_db, src_system)
    if not src or not dst:
        return 0.0, "system not found in SDE — transport = 0"
    if src.solar_system_id == dst.solar_system_id:
        return 0.0, None
    if shipping.mode == "jf":
        ly = dsvc.light_years(src.x, src.y, src.z, dst.x, dst.y, dst.z)
        # marginal rate for a full jump-freighter hold
        rate = ly * (shipping.isotopes_per_ly or 0.0) * (shipping.isotope_price or 0.0) / dsvc.JF_CARGO_M3
        if shipping.round_trip:
            rate *= 2
        return round(rate, 4), None
    route = market.esi_route(src.solar_system_id, dst.solar_system_id)
    if not route:
        return 0.0, "ESI route unavailable — transport = 0"
    jumps = len(route) - 1
    return round(jumps * (shipping.isk_per_jump_m3 or 0.0), 4), None


def _build_rigs(eve_db: Session, rig_type_ids: list[int]) -> tuple[RigYield, ...]:
    if not rig_type_ids:
        return ()
    catalog = {r["type_id"]: r for r in eve_repo.reprocessing_rigs(eve_db)}
    rigs = []
    for rid in rig_type_ids:
        r = catalog.get(rid)
        if r and r.get("yield_bonus"):
            rigs.append(RigYield(
                name=r["name"], yield_bonus=r["yield_bonus"],
                hisec_mod=r.get("hisec_mod") or 1.0,
                lowsec_mod=r.get("lowsec_mod") or 1.9,
                nullsec_mod=r.get("nullsec_mod") or 2.1,
            ))
    return tuple(rigs)


async def _resolve_sources(eve_db: Session, src_list: list[SourceIn], all_ids: list[int],
                           basis: str, ratio: float, dst: Optional[EveSolarSystem],
                           shipping: ShippingIn, adjusted: dict):
    """Resolve every source's per-type acquire price (basis + scam guard) and its
    transport rate to the target. Shared by /compare and /gas-compare.

    Returns ``(sources, item_prices, flags, source_meta, warnings)``.
    """
    sources: list[oa.Source] = []
    item_prices: dict[str, dict[int, Optional[float]]] = {}
    flags: dict[tuple, dict] = {}
    source_meta: list[dict] = []
    warnings: list[str] = []

    for src in src_list:
        if src.cj:
            sides = await _cj_two_sided(all_ids)
        elif src.region_id:
            sides = _region_two_sided(src.region_id, all_ids)
        else:
            warnings.append(f"{src.label}: no region — skipped")
            continue

        resolved: dict[int, Optional[float]] = {}
        for tid in all_ids:
            two = sides.get(tid) or {}
            price, _lbl, flag = pricing.resolve_price(
                [(two.get("buy"), src.key)], [(two.get("sell"), src.key)],
                adjusted.get(tid), ratio, basis)
            resolved[tid] = price
            if flag:
                flags[(src.key, tid)] = flag
        item_prices[src.key] = resolved

        cpm3, warn = _cost_per_m3(eve_db, src.system_name, dst, shipping)
        if warn:
            warnings.append(f"{src.label}: {warn}")
        sources.append(oa.Source(key=src.key, label=src.label, cost_per_m3=cpm3))
        source_meta.append({"key": src.key, "label": src.label, "cost_per_m3": cpm3})

    return sources, item_prices, flags, source_meta, warnings


def _volatility_alerts(region_id: Optional[int], type_ids: list[int],
                       threshold: float) -> dict[int, dict]:
    """Per-type daily-return volatility + liquidity at one region (best-effort).

    Flags a type when its 30-day return stdev is below ``threshold`` (a stable/thin
    market the user should double-check) or it has effectively no traded volume.
    """
    if not region_id:
        return {}
    alerts: dict[int, dict] = {}
    for tid in type_ids:
        hist = market.esi_region_history(region_id, tid)
        if not hist or len(hist) < 5:
            alerts[tid] = {"volatility": None, "avg_volume": 0.0, "alert": True,
                           "reason": "no recent market history"}
            continue
        prices = [h.get("average") for h in hist if h.get("average")]
        vols = [h.get("volume") or 0 for h in hist]
        rets = [math.log(prices[i] / prices[i - 1])
                for i in range(1, len(prices)) if prices[i - 1] and prices[i]]
        vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        avg_volume = sum(vols) / len(vols) if vols else 0.0
        low = vol < threshold or avg_volume <= 0
        alerts[tid] = {
            "volatility": round(vol, 4), "avg_volume": round(avg_volume, 1),
            "alert": low,
            "reason": ("low volatility — stable/thin market" if vol < threshold
                       else ("no traded volume" if avg_volume <= 0 else "ok")),
        }
    return alerts


# ---------------------------------------------------------------------------
# Catalog endpoints
# ---------------------------------------------------------------------------

@router.get("/hubs")
async def list_hubs(current_user: UserDB = Depends(get_current_user)):
    """Preset buy locations the UI offers out of the box."""
    return {"hubs": HUBS, "cj": CJ_SOURCE}


@router.get("/catalog")
async def catalog(
        compressed: Optional[bool] = None,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Minerals + ore types (for the resource selector). ``compressed`` filters ores."""
    return {
        "minerals": eve_repo.mineral_catalog(eve_db),
        "ores": eve_repo.ore_catalog(eve_db, compressed=compressed),
    }


def _try_num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


_QTY_LINE = re.compile(r"^(.*?)(?:\s+|\s*x\s*)([\d.,\s]+)$", re.IGNORECASE)


def _parse_need_lines(text: str) -> list[tuple[str, float]]:
    """Parse pasted lines into (name, qty). Handles EVE clipboard / multibuy / fitting
    formats: ``Name<tab>Qty``, ``Qty<tab>Name``, ``Name 1000``, ``Name x1000``,
    ``Name 1,000`` and bare ``Name`` (qty 0)."""
    out: list[tuple[str, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\t" in line:
            a, b = (line.split("\t") + [""])[:2]
            a, b = a.strip(), b.strip()
            qa, qb = _try_num(a), _try_num(b)
            if qa is not None and qb is None:
                out.append((b, qa))
            elif qb is not None:
                out.append((a, qb))
            else:
                out.append((a, 0.0))
            continue
        m = _QTY_LINE.match(line)
        if m and _try_num(m.group(2)) is not None:
            out.append((m.group(1).strip(), _try_num(m.group(2))))
        else:
            out.append((line, 0.0))
    return out


class ParseNeedsRequest(BaseModel):
    text: str


@router.post("/parse-minerals")
async def parse_minerals(
        body: ParseNeedsRequest,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Parse a pasted list and keep only the minerals (summing duplicates).

    Returns ``needs`` ready to feed the comparison, plus the names it skipped
    (recognised but not a mineral) and the ones it could not match.
    """
    parsed = _parse_need_lines(body.text or "")
    if not parsed:
        return {"needs": [], "skipped_non_mineral": [], "unmatched": []}

    resolved = eve_repo.types_by_name(eve_db, [n for n, _ in parsed])
    tids = [r["type_id"] for r in resolved.values()]
    groups = {tid: gid for tid, gid in
              eve_db.query(EveType.type_id, EveType.group_id).filter(EveType.type_id.in_(tids or [-1])).all()}

    agg: dict[int, dict] = {}
    skipped: list[str] = []
    unmatched: list[str] = []
    for name, qty in parsed:
        r = resolved.get(name.lower())
        if not r:
            unmatched.append(name)
            continue
        if groups.get(r["type_id"]) != eve_repo.GROUP_MINERAL:
            skipped.append(r["name"])
            continue
        a = agg.setdefault(r["type_id"], {"type_id": r["type_id"], "name": r["name"], "qty": 0.0})
        a["qty"] += qty

    return {
        "needs": sorted(agg.values(), key=lambda x: x["type_id"]),
        "skipped_non_mineral": sorted(set(skipped)),
        "unmatched": sorted(set(unmatched)),
    }


@router.get("/character-skills")
async def character_skills(
        character_id: int = Query(..., description="LinkedCharacter.id"),
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Reprocessing-relevant skill levels for one of the user's linked characters,
    to prefill the refining form. ``ore_specific_max`` is the highest ore-processing
    level trained (a reasonable single value for the multi-ore comparison)."""
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == character_id, LinkedCharacter.user_id == current_user.id).first()
    if not char:
        raise HTTPException(404, "Character not found")
    levels = {s.skill_id: (s.trained_level or 0)
              for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}
    ore_specific = [
        {"ore": ore, "skill_id": sid, "level": levels.get(sid, 0)}
        for ore, sid in skills_svc.SKILL_ORE_PROCESSING.items()
    ]
    return {
        "character_id": char.id,
        "character_name": char.character_name,
        "reprocessing_lvl": levels.get(skills_svc.SKILL_REPROCESSING, 0),
        "efficiency_lvl": levels.get(skills_svc.SKILL_REPROCESSING_EFFICIENCY, 0),
        "ore_specific": ore_specific,
        "ore_specific_max": max((o["level"] for o in ore_specific), default=0),
    }


@router.get("/rigs")
async def list_rigs(
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Structure reprocessing-yield rigs (data-driven, from the SDE)."""
    return {"rigs": eve_repo.reprocessing_rigs(eve_db)}


@router.get("/gas/catalog")
async def gas_catalog(
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Harvestable gases + their compressed variant (for the gas resource selector)."""
    return {"gases": eve_repo.gas_catalog(eve_db)}


@router.get("/yields")
async def yields(
        type_ids: str = Query(..., description="Comma-separated ore type IDs"),
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Perfect (100%) reprocessing yields for the given ore type_ids."""
    ids = [int(t) for t in type_ids.split(",") if t.strip().isdigit()]
    return eve_repo.reprocessing_yields(eve_db, ids)


# ---------------------------------------------------------------------------
# Standalone reprocessing calculator
# ---------------------------------------------------------------------------

@router.post("/reprocess")
async def reprocess_calc(
        body: ReprocessRequest,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Reprocess a list of items at a given skill/structure/rig/tax setup."""
    if not body.items:
        raise HTTPException(400, "No items to reprocess")
    sys = _resolve_system(eve_db, body.system_name)
    band = facility_bonus.band_of(sys.security) if sys else "hi"
    rigs = _build_rigs(eve_db, body.refine.rig_type_ids)
    ry = compute_yield(RefineSetup(
        base_yield=body.refine.base_yield,
        reprocessing_lvl=body.refine.reprocessing_lvl,
        efficiency_lvl=body.refine.efficiency_lvl,
        ore_specific_lvl=body.refine.ore_specific_lvl,
        implant_pct=body.refine.implant_pct,
        rigs=rigs, security=band, tax_pct=body.refine.tax_pct,
    ))

    type_ids = [it.type_id for it in body.items]
    yld = eve_repo.reprocessing_yields(eve_db, type_ids)

    results = []
    aggregate: dict[int, dict] = {}
    for it in body.items:
        info = yld.get(it.type_id) or {"portion_size": 1, "materials": []}
        res = reprocess(it.qty, info["portion_size"], info["materials"], ry,
                        input_type_id=it.type_id)
        results.append(asdict(res))
        for m in res.minerals:
            agg = aggregate.setdefault(m.type_id, {"type_id": m.type_id, "name": m.name, "qty": 0})
            agg["qty"] += m.qty

    # optional ISK valuation of the refined minerals
    total_value = None
    if body.region_id and aggregate:
        sides = _region_two_sided(body.region_id, list(aggregate))
        total_value = 0.0
        for tid, agg in aggregate.items():
            px = (sides.get(tid) or {}).get(body.basis)
            if px:
                agg["unit_price"] = round(px, 2)
                agg["value"] = round(px * agg["qty"], 2)
                total_value += agg["value"]
        total_value = round(total_value, 2)

    return {
        "refine_yield": asdict(ry),
        "security_band": band,
        "items": results,
        "minerals": sorted(aggregate.values(), key=lambda a: a["type_id"]),
        "total_value": total_value,
    }


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

@router.post("/compare")
async def compare_acquisition(
        body: CompareRequest,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Compare mineral vs raw-ore vs compressed-ore acquisition and recommend the cheapest."""
    if not body.needs:
        raise HTTPException(400, "Select at least one mineral you need")
    if not body.sources:
        raise HTTPException(400, "Select at least one buy location")

    dst = _resolve_system(eve_db, body.target_system)
    band = facility_bonus.band_of(dst.security) if dst else "hi"

    mineral_ids = [n.type_id for n in body.needs]

    # ----- ore candidates per analyze mode ------------------------------------
    ore_rows: list[dict] = []
    if body.analyze_mode in ("raw", "all"):
        ore_rows += eve_repo.ores_yielding(eve_db, mineral_ids, compressed=False)
    if body.analyze_mode in ("compressed", "all"):
        ore_rows += eve_repo.ores_yielding(eve_db, mineral_ids, compressed=True)
    ore_ids = [o["type_id"] for o in ore_rows]
    ore_yields = eve_repo.reprocessing_yields(eve_db, ore_ids)

    all_ids = list({*mineral_ids, *ore_ids})
    volumes = eve_repo.volumes(eve_db, all_ids)
    names = eve_repo.type_names(eve_db, all_ids)

    try:
        adjusted = market.esi_adjusted_prices()
    except Exception:
        adjusted = {}

    # ----- prices + transport per source --------------------------------------
    sources, item_prices, flags, source_meta, warnings = await _resolve_sources(
        eve_db, body.sources, all_ids, body.basis, body.unrealistic_ratio, dst,
        body.shipping, adjusted)
    if not sources:
        raise HTTPException(400, "No usable buy locations after resolving")

    # ----- refining yield -----------------------------------------------------
    rigs = _build_rigs(eve_db, body.refine.rig_type_ids)
    ry = compute_yield(RefineSetup(
        base_yield=body.refine.base_yield,
        reprocessing_lvl=body.refine.reprocessing_lvl,
        efficiency_lvl=body.refine.efficiency_lvl,
        ore_specific_lvl=body.refine.ore_specific_lvl,
        implant_pct=body.refine.implant_pct,
        rigs=rigs, security=band, tax_pct=body.refine.tax_pct,
    ))

    # ----- reference mineral price (cheapest resolved across sources) ---------
    mineral_ref_price: dict[int, Optional[float]] = {}
    for tid in mineral_ids:
        cands = [item_prices[s.key].get(tid) for s in sources]
        cands = [c for c in cands if c is not None]
        mineral_ref_price[tid] = min(cands) if cands else (adjusted.get(tid) or None)

    # ----- ore inputs ---------------------------------------------------------
    ores = [
        oa.OreInfo(
            type_id=o["type_id"], name=o["name"], compressed=o["compressed"],
            portion_size=(ore_yields.get(o["type_id"], {}).get("portion_size") or 1),
            materials=tuple(ore_yields.get(o["type_id"], {}).get("materials") or []),
        )
        for o in ore_rows
    ]

    needs = [oa.Need(n.type_id, names.get(n.type_id, str(n.type_id)), n.qty) for n in body.needs]

    result = oa.compare(
        target=body.target_system or "target",
        basis=body.basis, needs=needs, sources=sources,
        item_prices=item_prices, volumes=volumes, ores=ores,
        effective_yield=ry.effective_yield, mineral_ref_price=mineral_ref_price,
        flags=flags,
    )

    # ----- optional volatility / liquidity alerts -----------------------------
    alerts: dict[int, dict] = {}
    if body.volatility_alert:
        region = next((s.region_id for s in body.sources if s.region_id), None)
        alerts = _volatility_alerts(region, mineral_ids, body.low_vol_threshold)

    payload = asdict(result)
    payload.update({
        "refine_yield": asdict(ry),
        "security_band": band,
        "sources": source_meta,
        "alerts": alerts,
        "warnings": warnings,
        "ore_candidates": len(ores),
    })
    return payload


@router.post("/gas-compare")
async def compare_gas(
        body: GasCompareRequest,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Compare buying each gas compressed vs regular (decompression loss + transport)."""
    if not body.needs:
        raise HTTPException(400, "Select at least one gas you need")
    if not body.sources:
        raise HTTPException(400, "Select at least one buy location")

    dst = _resolve_system(eve_db, body.target_system)
    reg_ids = [n.type_id for n in body.needs]

    # pull the gas catalog and keep only the requested gases
    catalog = {g["reg_type_id"]: g for g in eve_repo.gas_catalog(eve_db)}
    gas_infos = []
    for tid in reg_ids:
        g = catalog.get(tid)
        if not g:
            continue
        gas_infos.append(oa.GasInfo(
            reg_type_id=g["reg_type_id"], reg_name=g["reg_name"], reg_volume=g["reg_volume"],
            comp_type_id=g["comp_type_id"], comp_name=g["comp_name"], comp_volume=g["comp_volume"],
            units_per_compressed=g["units_per_compressed"],
        ))
    if not gas_infos:
        raise HTTPException(404, "None of the selected types are recognised gases")

    all_ids = list({g.reg_type_id for g in gas_infos} | {g.comp_type_id for g in gas_infos if g.comp_type_id})
    volumes = eve_repo.volumes(eve_db, all_ids)

    try:
        adjusted = market.esi_adjusted_prices()
    except Exception:
        adjusted = {}

    sources, item_prices, flags, source_meta, warnings = await _resolve_sources(
        eve_db, body.sources, all_ids, body.basis, body.unrealistic_ratio, dst,
        body.shipping, adjusted)
    if not sources:
        raise HTTPException(400, "No usable buy locations after resolving")

    qty_by_id = {n.type_id: n.qty for n in body.needs}
    needs = [oa.Need(g.reg_type_id, g.reg_name, qty_by_id.get(g.reg_type_id, 0.0))
             for g in gas_infos]

    result = oa.compare_gas(
        target=body.target_system or "target", basis=body.basis, needs=needs,
        sources=sources, item_prices=item_prices, volumes=volumes,
        gas_infos=gas_infos, decompression_loss=body.decompression_loss_pct / 100.0,
        flags=flags,
    )

    alerts: dict[int, dict] = {}
    if body.volatility_alert:
        region = next((s.region_id for s in body.sources if s.region_id), None)
        alerts = _volatility_alerts(region, reg_ids, body.low_vol_threshold)

    payload = asdict(result)
    payload.update({"sources": source_meta, "alerts": alerts, "warnings": warnings})
    return payload
