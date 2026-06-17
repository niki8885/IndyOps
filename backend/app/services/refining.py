"""
Pure reprocessing/refining yield maths for the Ore-Acquisition feature.

EVE reprocessing yield is the product of four independent factors applied to the
perfect (invTypeMaterials) mineral output of an ore batch:

    base structure/station yield               (e.g. NPC station 0.50, Athanor 0.50)
  × skills   (1+0.03·Reprocessing)(1+0.02·ReprocessingEfficiency)(1+0.02·OreSpecific)
  × implant  (1+0.01·implant%)                 (RX-80x: 1 / 2 / 4 %)
  × rigs     (1 + Σ rig_yield% · security_mod)  (hi 1.0 / low 1.9 / null 2.1)

and the facility/station **tax** then takes a slice of the resulting minerals:

    effective_yield = base · skills · implant · (1 + rigs) · (1 − tax)

No DB / HTTP here — the router loads the base yield, skill levels, rigs (SDE) and
tax, then feeds plain numbers in. Stdlib only, so it is unit-testable and shared by
the standalone reprocessing calculator and the acquisition comparison.
See [[indyops-service-layering]] and [[indyops-chain-calculator]].
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from app.services import skills as skills_svc


@dataclass(frozen=True)
class RigYield:
    """One structure reprocessing-yield rig (from ``EveReprocessingRig``)."""
    name: str
    yield_bonus: float           # positive %, e.g. 2.0 = +2% yield (hi-sec base)
    hisec_mod: float = 1.0
    lowsec_mod: float = 1.9
    nullsec_mod: float = 2.1

    def effective_pct(self, band: str) -> float:
        """The rig's yield bonus % after the system's security modifier."""
        mod = {"hi": self.hisec_mod, "low": self.lowsec_mod, "null": self.nullsec_mod}.get(band, 1.0)
        return (self.yield_bonus or 0.0) * (mod if mod is not None else 1.0)


@dataclass(frozen=True)
class RefineSetup:
    """A character + facility reprocessing configuration."""
    base_yield: float                       # structure/station base, 0..1
    reprocessing_lvl: int = 0
    efficiency_lvl: int = 0
    ore_specific_lvl: int = 0
    implant_pct: float = 0.0                 # 0 / 1 / 2 / 4
    rigs: tuple[RigYield, ...] = ()
    security: str = "hi"                     # hi | low | null (rig modifier band)
    tax_pct: float = 0.0                     # facility/station take on output, %


@dataclass(frozen=True)
class RefineYield:
    """The resolved effective yield and the factors that produced it."""
    base_yield: float
    skill_mult: float
    implant_mult: float
    rig_bonus_pct: float                     # summed effective rig bonus %, post sec-mod
    gross_yield: float                       # base · skills · implant · (1+rigs)
    tax_pct: float
    effective_yield: float                   # gross · (1 − tax), clamped to [0, 1]


@dataclass(frozen=True)
class MineralOut:
    type_id: int
    name: str
    perfect_qty: int                         # 100% yield for the given input
    qty: int                                 # after effective yield (floored)


@dataclass(frozen=True)
class ReprocessResult:
    input_type_id: Optional[int]
    input_qty: int
    portion_size: int
    batches: int
    leftover: int                            # units below a whole batch — not refined
    refined_units: int
    refine_yield: RefineYield
    minerals: list[MineralOut] = field(default_factory=list)


def effective_rig_bonus_pct(rigs: tuple[RigYield, ...], band: str) -> float:
    """Total reprocessing-yield bonus % from all fitted rigs after the sec modifier."""
    return sum(r.effective_pct(band) for r in rigs)


def compute_yield(setup: RefineSetup) -> RefineYield:
    """Resolve a :class:`RefineSetup` into an effective yield fraction."""
    skill_mult = skills_svc.reprocessing_skill_mult(
        setup.reprocessing_lvl, setup.efficiency_lvl, setup.ore_specific_lvl)
    implant_mult = 1 + 0.01 * max(0.0, setup.implant_pct)
    rig_pct = effective_rig_bonus_pct(tuple(setup.rigs), setup.security)
    gross = max(0.0, setup.base_yield) * skill_mult * implant_mult * (1 + rig_pct / 100.0)
    taxed = gross * (1 - max(0.0, setup.tax_pct) / 100.0)
    effective = min(1.0, max(0.0, taxed))
    return RefineYield(
        base_yield=round(setup.base_yield, 4),
        skill_mult=round(skill_mult, 4),
        implant_mult=round(implant_mult, 4),
        rig_bonus_pct=round(rig_pct, 4),
        gross_yield=round(gross, 6),
        tax_pct=round(setup.tax_pct, 4),
        effective_yield=round(effective, 6),
    )


def reprocess(input_qty: int, portion_size: int, portion_materials: list[dict],
              ry: RefineYield, input_type_id: Optional[int] = None) -> ReprocessResult:
    """Reprocess ``input_qty`` units, refining only whole ``portion_size`` batches.

    ``portion_materials`` is the perfect output per batch: ``[{type_id, name,
    quantity}]`` (from ``eve_repo.reprocessing_yields``). Per-mineral output is
    floored, matching the game.
    """
    portion_size = max(1, int(portion_size or 1))
    batches = int(input_qty) // portion_size
    refined_units = batches * portion_size
    leftover = int(input_qty) - refined_units
    minerals: list[MineralOut] = []
    for m in portion_materials:
        perfect = batches * int(m.get("quantity") or 0)
        minerals.append(MineralOut(
            type_id=m["type_id"],
            name=m.get("name", str(m["type_id"])),
            perfect_qty=perfect,
            qty=int(math.floor(perfect * ry.effective_yield)),
        ))
    return ReprocessResult(
        input_type_id=input_type_id,
        input_qty=int(input_qty),
        portion_size=portion_size,
        batches=batches,
        leftover=leftover,
        refined_units=refined_units,
        refine_yield=ry,
        minerals=minerals,
    )


# Common base reprocessing yields, for UI presets. Real per-structure numbers come
# from the SDE (NPC stations) or the structure type; these are the standard planning
# figures for player structures with no rigs.
BASE_YIELD_PRESETS = {
    "npc_station": 0.50,     # most modern NPC stations
    "athanor": 0.50,         # Athanor refinery, no rigs
    "tatara": 0.55,          # Tatara refinery role bonus, no rigs
}
