"""
Pure EVE character-skill / standings math for industry planning.

Given a character's trained skill levels (``{skill_id: level}``) and NPC standings,
derive the job-time multipliers a *producing* character gets and the market fees a
*selling* character pays. Stdlib only (no ORM/web) — the router loads the levels and
standings from the synced ESI tables and passes them in as plain values, so this
stays unit-testable. See [[indyops-service-layering]] and [[indyops-io24-esi-integration]].
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

# ── industry/market skill type_ids (SDE) ──────────────────────────────────────
SKILL_INDUSTRY = 3380           # −4%/level manufacturing job time
SKILL_ADVANCED_INDUSTRY = 3388  # −3%/level job time (manufacturing + reactions + …)
SKILL_ACCOUNTING = 16622        # −11%/level sales (transaction) tax
SKILL_BROKER_RELATIONS = 3446   # −0.30%/level broker fee

# ── industry job-slot skills (each +1 concurrent job per level; base 1 slot) ──
SKILL_MASS_PRODUCTION = 3387                # +1 manufacturing slot / level
SKILL_ADVANCED_MASS_PRODUCTION = 24625      # +1 manufacturing slot / level
SKILL_LABORATORY_OPERATION = 3406           # +1 science slot / level
SKILL_ADVANCED_LABORATORY_OPERATION = 24624  # +1 science slot / level
SKILL_MASS_REACTIONS = 45748                # +1 reaction slot / level
SKILL_ADVANCED_MASS_REACTIONS = 45749       # +1 reaction slot / level

_MAX_SLOTS = 11  # 1 base + 5 + 5 with both skills at V

# Industry activity_id → slot category. Manufacturing(1); research/copy/invention
# share the science slots (3 TE, 4 ME, 5 copy, 8 invention); reactions (9, 11).
_ACTIVITY_CATEGORY = {1: "manufacturing", 3: "science", 4: "science",
                      5: "science", 8: "science", 9: "reaction", 11: "reaction"}
# A job ties up its slot until it's delivered — count everything not finished/cancelled.
_OCCUPYING_STATUSES = {"active", "ready", "paused"}
_SLOT_CATEGORIES = ("manufacturing", "science", "reaction")

# ── reprocessing / refining skills ────────────────────────────────────────────
SKILL_REPROCESSING = 3385             # +3%/level reprocessing yield
SKILL_REPROCESSING_EFFICIENCY = 3389  # +2%/level reprocessing yield
# Ore-specific *Processing* skills (+2%/level, applies only to that ore family).
SKILL_ORE_PROCESSING = {
    "Veldspar": 12180, "Scordite": 12181, "Pyroxeres": 12182, "Plagioclase": 12183,
    "Omber": 12184, "Kernite": 12185, "Jaspet": 12186, "Hemorphite": 12187,
    "Hedbergite": 12188, "Gneiss": 12189, "Dark Ochre": 12190, "Crokite": 12192,
    "Bistot": 12193, "Arkonor": 12194, "Mercoxit": 12195, "Spodumain": 12191,
    "Ice": 18025,
}
_REPROCESSING_PER_LVL = 0.03
_REPROCESSING_EFF_PER_LVL = 0.02
_ORE_PROCESSING_PER_LVL = 0.02

# Job-time reductions per skill level (fraction of base time).
_INDUSTRY_PER_LVL = 0.04
_ADV_INDUSTRY_PER_LVL = 0.03

# Market-fee model (percentage points). Bases are the NPC defaults; players selling
# in Upwell structures may pay less, but these are the standard planning figures.
SALES_TAX_BASE_PCT = 7.5
SALES_TAX_PER_ACCOUNTING = 0.11        # 11% *relative* cut per Accounting level
BROKER_BASE_PCT = 3.0
BROKER_PER_RELATIONS_PCT = 0.30        # absolute % cut per Broker Relations level
BROKER_PER_FACTION_STANDING_PCT = 0.03  # absolute % cut per point of faction standing
BROKER_PER_CORP_STANDING_PCT = 0.02     # absolute % cut per point of corp standing
BROKER_MIN_PCT = 1.0                    # NPC broker fee floor


def _lvl(skills: Mapping[int, int], skill_id: int) -> int:
    return int(skills.get(skill_id, 0) or 0)


def manufacturing_time_mult(skills: Mapping[int, int]) -> float:
    """Job-time multiplier for manufacturing: Industry (−4%/lvl) × Advanced Industry
    (−3%/lvl), stacked multiplicatively like EVE."""
    return ((1 - _INDUSTRY_PER_LVL * _lvl(skills, SKILL_INDUSTRY))
            * (1 - _ADV_INDUSTRY_PER_LVL * _lvl(skills, SKILL_ADVANCED_INDUSTRY)))


def reaction_time_mult(skills: Mapping[int, int]) -> float:
    """Job-time multiplier for reactions: Advanced Industry only (the Industry skill
    is manufacturing-only)."""
    return 1 - _ADV_INDUSTRY_PER_LVL * _lvl(skills, SKILL_ADVANCED_INDUSTRY)


def sales_tax_pct(skills: Mapping[int, int]) -> float:
    """Transaction (sales) tax %, cut 11% per Accounting level."""
    return SALES_TAX_BASE_PCT * (1 - SALES_TAX_PER_ACCOUNTING * _lvl(skills, SKILL_ACCOUNTING))


def broker_fee_pct(skills: Mapping[int, int],
                   faction_standing: float = 0.0, corp_standing: float = 0.0) -> float:
    """Broker fee %, cut by Broker Relations and by standings toward the station's
    faction/corp. Floored at ``BROKER_MIN_PCT``. Standings below 0 give no benefit."""
    fee = (BROKER_BASE_PCT
           - BROKER_PER_RELATIONS_PCT * _lvl(skills, SKILL_BROKER_RELATIONS)
           - BROKER_PER_FACTION_STANDING_PCT * max(0.0, faction_standing)
           - BROKER_PER_CORP_STANDING_PCT * max(0.0, corp_standing))
    return max(BROKER_MIN_PCT, fee)


def job_slots(skills: Mapping[int, int]) -> dict:
    """
    Max concurrent industry jobs per category from the slot skills (each +1/level,
    base 1, capped at 11). Manufacturing ← Mass Production + Advanced Mass
    Production; science (research / copy / invention) ← Laboratory Operation +
    Advanced Laboratory Operation; reactions ← Mass Reactions + Advanced Mass
    Reactions.
    """
    man = 1 + _lvl(skills, SKILL_MASS_PRODUCTION) + _lvl(skills, SKILL_ADVANCED_MASS_PRODUCTION)
    sci = 1 + _lvl(skills, SKILL_LABORATORY_OPERATION) + _lvl(skills, SKILL_ADVANCED_LABORATORY_OPERATION)
    rea = 1 + _lvl(skills, SKILL_MASS_REACTIONS) + _lvl(skills, SKILL_ADVANCED_MASS_REACTIONS)
    return {
        "manufacturing": min(man, _MAX_SLOTS),
        "science": min(sci, _MAX_SLOTS),
        "reaction": min(rea, _MAX_SLOTS),
    }


def job_slot_usage(jobs, skills: Mapping[int, int]) -> dict:
    """
    Used vs. available industry slots per category. ``jobs`` is an iterable of
    ``(activity_id, status)`` pairs; only jobs still occupying a slot (active /
    ready / paused) are counted. Returns ``{category: {"used", "max"}}``.
    """
    maxes = job_slots(skills)
    used = {cat: 0 for cat in _SLOT_CATEGORIES}
    for activity_id, status in jobs:
        if (status or "").lower() not in _OCCUPYING_STATUSES:
            continue
        cat = _ACTIVITY_CATEGORY.get(activity_id)
        if cat:
            used[cat] += 1
    return {cat: {"used": used[cat], "max": maxes[cat]} for cat in _SLOT_CATEGORIES}


def reprocessing_skill_mult(reprocessing_lvl: int, efficiency_lvl: int,
                            ore_specific_lvl: int = 0) -> float:
    """Multiplicative skill bonus to reprocessing yield, stacked like EVE:
    ``(1+0.03·Reprocessing)·(1+0.02·ReprocessingEfficiency)·(1+0.02·OreSpecific)``.
    Perfect skills (5/5/5) give ×1.15·1.10·1.10 ≈ ×1.391."""
    return ((1 + _REPROCESSING_PER_LVL * max(0, reprocessing_lvl))
            * (1 + _REPROCESSING_EFF_PER_LVL * max(0, efficiency_lvl))
            * (1 + _ORE_PROCESSING_PER_LVL * max(0, ore_specific_lvl)))


def reprocessing_yield_mult(skills: Mapping[int, int],
                            ore_specific_skill_id: int | None = None) -> float:
    """Reprocessing skill multiplier from a ``{skill_id: level}`` map. Looks up the
    general Reprocessing/Reprocessing Efficiency levels and, if given, the supplied
    ore-specific Processing skill."""
    return reprocessing_skill_mult(
        _lvl(skills, SKILL_REPROCESSING),
        _lvl(skills, SKILL_REPROCESSING_EFFICIENCY),
        _lvl(skills, ore_specific_skill_id) if ore_specific_skill_id else 0,
    )


@dataclass(frozen=True)
class IndustryProfile:
    """Everything a chosen character contributes to a plan, derived once from its
    skills + standings. Time multipliers for the producer; market fees for the seller."""
    character_id: int
    character_name: str
    industry_lvl: int = 0
    advanced_industry_lvl: int = 0
    accounting_lvl: int = 0
    broker_relations_lvl: int = 0
    best_faction_standing: float = 0.0
    best_corp_standing: float = 0.0
    man_time_mult: float = 1.0
    react_time_mult: float = 1.0
    sales_tax_pct: float = SALES_TAX_BASE_PCT
    broker_fee_pct: float = BROKER_BASE_PCT


def profile_from(character_id: int, character_name: str,
                 skills: Mapping[int, int],
                 best_faction_standing: float = 0.0,
                 best_corp_standing: float = 0.0) -> IndustryProfile:
    """Build an :class:`IndustryProfile` from a character's skill levels + standings."""
    return IndustryProfile(
        character_id=character_id,
        character_name=character_name,
        industry_lvl=_lvl(skills, SKILL_INDUSTRY),
        advanced_industry_lvl=_lvl(skills, SKILL_ADVANCED_INDUSTRY),
        accounting_lvl=_lvl(skills, SKILL_ACCOUNTING),
        broker_relations_lvl=_lvl(skills, SKILL_BROKER_RELATIONS),
        best_faction_standing=best_faction_standing,
        best_corp_standing=best_corp_standing,
        man_time_mult=manufacturing_time_mult(skills),
        react_time_mult=reaction_time_mult(skills),
        sales_tax_pct=round(sales_tax_pct(skills), 4),
        broker_fee_pct=round(broker_fee_pct(skills, best_faction_standing, best_corp_standing), 4),
    )
