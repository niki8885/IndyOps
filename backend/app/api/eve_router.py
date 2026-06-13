from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database_eve import EveSessionLocal, EveSolarSystem, EveType

router = APIRouter()


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


class SystemOut(BaseModel):
    solar_system_id: int
    solar_system_name: str
    security: Optional[float]
    region_id: Optional[int]

    class Config:
        from_attributes = True


class TypeOut(BaseModel):
    type_id: int
    type_name: str
    volume: Optional[float]
    portion_size: Optional[int]
    market_group_id: Optional[int]

    class Config:
        from_attributes = True


@router.get("/systems", response_model=list[SystemOut])
async def search_systems(
    q: str = Query(..., min_length=2),
    limit: int = Query(15, le=50),
    eve_db: Session = Depends(_get_eve_db),
):
    """Autocomplete search for EVE solar systems."""
    results = (
        eve_db.query(EveSolarSystem)
        .filter(EveSolarSystem.solar_system_name.ilike(f"{q}%"))
        .order_by(EveSolarSystem.solar_system_name)
        .limit(limit)
        .all()
    )
    return results


@router.get("/types/search", response_model=list[TypeOut])
async def search_types(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, le=30),
    eve_db: Session = Depends(_get_eve_db),
):
    """Autocomplete search for EVE item types."""
    results = (
        eve_db.query(EveType)
        .filter(EveType.type_name.ilike(f"%{q}%"))
        .order_by(EveType.type_name)
        .limit(limit)
        .all()
    )
    return results
