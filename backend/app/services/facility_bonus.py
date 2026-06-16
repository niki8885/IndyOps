"""
Pure industry-bonus logic: match engineering rigs to a product and roll their
ME/TE/cost bonuses up to effective percentages, scaled by the structure system's
security band.

Lives in ``services/`` so it stays import-light (stdlib + dataclasses only — no
ORM/web): the rig rows, security band and product category are resolved by the
caller (router) and passed in as plain values. Shared by the ``/facility-bonuses``
endpoint and the recursive chain calculator, so a facility's rigs are applied the
same way in both. See [[indyops-service-layering]].
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# Engineering Complex (Raitaru/Azbel/Sotiyo) role bonuses — a flat material and
# job-cost reduction every EC grants, on top of its rigs.
EC_MATERIAL_ROLE = 1.0
EC_COST_ROLE = 3.0

# invCategories used to decide whether a rig applies to a product.
_CAT_SHIP, _CAT_MODULE, _CAT_CHARGE, _CAT_DRONE = 6, 7, 8, 18
_CAT_IMPLANT, _CAT_FIGHTER, _CAT_POS_STRUCT = 20, 87, 23
_CAT_UPWELL, _CAT_STRUCT_MODULE = 65, 66

# metaGroupIDs treated as "advanced" for the Basic/Advanced rig split:
# 2 = Tech II, 14 = Tech III. Everything else (Tech I, faction, storyline,
# or no meta entry at all) counts as basic for rig purposes.
ADVANCED_META = frozenset({2, 14})


@dataclass(frozen=True)
class RigBonus:
    """One engineering rig's raw industry bonus (as stored in eve_rig_bonuses).

    Bonuses are stored negative (e.g. me_bonus -2.0 = 2% saving); the rollup uses
    their magnitude. ``has_industry_bonus`` is False for a fitted rig that carries
    no industry attributes at all (so the caller can report "no industry bonus").
    """
    type_id: int
    name: str
    me_bonus: Optional[float] = None
    te_bonus: Optional[float] = None
    cost_bonus: Optional[float] = None
    hisec_mod: Optional[float] = None
    lowsec_mod: Optional[float] = None
    nullsec_mod: Optional[float] = None
    has_industry_bonus: bool = True


@dataclass(frozen=True)
class EffectiveBonus:
    """Rig-only effective percentages for one product at one structure.

    EC role bonuses are *not* folded in here (the ``/facility-bonuses`` endpoint
    reports them separately); callers that want the combined figure add
    ``EC_MATERIAL_ROLE``/``EC_COST_ROLE`` themselves.
    """
    me_pct: float = 0.0
    te_pct: float = 0.0
    cost_pct: float = 0.0
    rigs: list[dict] = field(default_factory=list)  # per-rig detail for display


def band_of(security: Optional[float]) -> str:
    """Security band for rig scaling: hi ≥ 0.45, low > 0.0, else null/WH."""
    if security is not None and security >= 0.45:
        return "hi"
    if security is not None and security > 0.0:
        return "low"
    return "null"


def _ship_size(group_name: Optional[str]) -> Optional[str]:
    g = (group_name or "").lower()
    if any(k in g for k in ("frigate", "destroyer", "shuttle", "corvette", "capsule")):
        return "small"
    if any(k in g for k in ("cruiser", "battlecruiser")):
        return "medium"
    if any(k in g for k in ("battleship", "freighter", "dreadnought", "carrier",
                            "capital", "titan", "supercarrier", "industrial ship")):
        return "large"
    return None


def rig_applies(rig_name: str, cat_id: Optional[int], group_name: Optional[str],
                is_reaction: bool = False, meta_group_id: Optional[int] = None) -> bool:
    """
    Match an industry rig to a product, based on the official affected-category
    lists from the SDE rig multiplier attribute descriptions, then gate by the
    product's tech level.

    Reactions are a separate world: only **reactor** rigs (refinery rigs) apply to
    reaction outputs, and a subtype rig (composite/hybrid/biochemical) only covers
    its own family — a plain "Reactor Efficiency" rig covers every reaction. Reactor
    rigs never apply to manufacturing, and manufacturing rigs never apply to reactions.

    Tech-level gate (manufacturing only): a **Basic** rig only affects Tech I products
    and an **Advanced** rig only affects Tech II/III (``ADVANCED_META``). This stops a
    facility fitted with both a Basic and an Advanced ship/component rig from stacking
    both on the same item — e.g. a T2 cruiser (Basilisk) gets the Advanced rig only.
    A rig whose name carries neither word is not tech-split and applies regardless.
    """
    n = (rig_name or "").lower()
    if not _base_rig_applies(n, cat_id, group_name, is_reaction):
        return False
    if not is_reaction:
        advanced = meta_group_id in ADVANCED_META
        if "advanced" in n:
            return advanced
        if "basic" in n:
            return not advanced
    return True


def _base_rig_applies(n: str, cat_id: Optional[int], group_name: Optional[str],
                      is_reaction: bool) -> bool:
    """Category/size match for a rig (``n`` is the lowercased rig name), before the
    Basic/Advanced tech-level gate."""
    gn = (group_name or "").lower()
    is_reactor_rig = "reactor" in n or "reaction" in n
    if is_reaction:
        if not is_reactor_rig:
            return False
        if "composite" in n: return "composite" in gn
        if "hybrid" in n:    return "hybrid" in gn
        if "biochem" in n:   return "biochem" in gn or "organic" in gn
        return True
    if is_reactor_rig:
        return False
    if "equipment" in n:
        return cat_id in (_CAT_MODULE, _CAT_IMPLANT) or "cargo container" in gn or "deployable" in gn
    if "ammunition" in n:
        return cat_id == _CAT_CHARGE
    if "drone" in n or "fighter" in n:
        return cat_id in (_CAT_DRONE, _CAT_FIGHTER)
    if "capital component" in n:
        return "component" in gn
    if "component" in n:
        return "component" in gn or "tool" in gn or "data interface" in gn
    if "structure" in n:
        return (cat_id in (_CAT_UPWELL, _CAT_STRUCT_MODULE, _CAT_POS_STRUCT)
                or "fuel block" in gn or "structure" in gn or "component" in gn)
    if "ship" in n:
        if cat_id != _CAT_SHIP:
            return False
        size = _ship_size(group_name)
        if "small" in n:  return size == "small"
        if "medium" in n: return size == "medium"
        if "large" in n:  return size == "large"
        return True
    return False


def effective_bonuses(
        rigs: list[RigBonus], band: str,
        cat_id: Optional[int], group_name: Optional[str],
        is_reaction: bool = False, meta_group_id: Optional[int] = None,
) -> EffectiveBonus:
    """Roll a structure's rigs up to effective ME/TE/cost % for one product.

    Only rigs whose affected-category list covers the product contribute to the
    totals; every rig still appears in ``rigs`` so callers can show why one was
    skipped. ``is_reaction`` switches to reactor-rig matching (see ``rig_applies``);
    ``meta_group_id`` gates Basic vs Advanced rigs by the product's tech level.
    EC role bonuses are intentionally excluded (added by the caller).
    """
    tot_me = tot_te = tot_cost = 0.0
    detail: list[dict] = []
    for rb in rigs:
        if not rb.has_industry_bonus:
            detail.append({"type_id": rb.type_id, "name": rb.name,
                           "applies": False, "reason": "no industry bonus"})
            continue
        mod = {"hi": rb.hisec_mod, "low": rb.lowsec_mod, "null": rb.nullsec_mod}[band] or 1.0
        applies = rig_applies(rb.name, cat_id, group_name, is_reaction, meta_group_id)
        eff_me = abs(rb.me_bonus or 0) * mod
        eff_te = abs(rb.te_bonus or 0) * mod
        eff_cost = abs(rb.cost_bonus or 0) * mod
        if applies:
            tot_me += eff_me
            tot_te += eff_te
            tot_cost += eff_cost
        detail.append({
            "type_id": rb.type_id, "name": rb.name, "applies": applies,
            "me_pct": round(eff_me, 2), "te_pct": round(eff_te, 2), "cost_pct": round(eff_cost, 2),
        })
    return EffectiveBonus(round(tot_me, 4), round(tot_te, 4), round(tot_cost, 4), detail)
