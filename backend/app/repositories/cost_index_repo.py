from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SystemCostIndex

# ESI activity keys (as returned by /industry/systems/cost_indices[].activity)
ACT_MANUFACTURING = "manufacturing"
ACT_REACTION = "reaction"
ACT_COPYING = "copying"
ACT_INVENTION = "invention"
ACT_ME_RESEARCH = "researching_material_efficiency"
ACT_TE_RESEARCH = "researching_time_efficiency"


def indices_for_system(db: Session, solar_system_id: int | None) -> dict[str, float]:
    """``{activity: cost_index}`` for one system (``{}`` if unknown/None)."""
    if not solar_system_id:
        return {}
    rows = (
        db.query(SystemCostIndex.activity, SystemCostIndex.cost_index)
        .filter(SystemCostIndex.solar_system_id == solar_system_id)
        .all()
    )
    return {act: float(idx) for act, idx in rows}


def index_for(
    db: Session, solar_system_id: int | None, activity: str, default: float = 0.0
) -> float:
    """Persisted cost index for ``(system, activity)``; ``default`` if absent."""
    if not solar_system_id:
        return default
    row = (
        db.query(SystemCostIndex.cost_index)
        .filter(
            SystemCostIndex.solar_system_id == solar_system_id,
            SystemCostIndex.activity == activity,
        )
        .first()
    )
    return float(row[0]) if row else default
