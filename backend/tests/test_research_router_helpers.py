"""Research-router cost-bonus helper: research/copy/invention apply the structure's
effective job-cost reduction (manual Cost Bonus % floored by the EC role bonus)."""
from types import SimpleNamespace

from app.api import research_router as rr
from app.core.schemas import FacilityType
from app.services.facility_bonus import EC_COST_ROLE


def _fac(facility_type, cost_bonus):
    return SimpleNamespace(facility_type=facility_type, cost_bonus=cost_bonus)


def test_cost_role_none_facility():
    assert rr._cost_role(None) == 0.0


def test_cost_role_manual_wins_when_higher():
    # User entered their structure's full rig+role reduction (e.g. 25) — it's applied.
    assert rr._cost_role(_fac(FacilityType.SOTIYO, 25.0)) == 25.0


def test_cost_role_ec_role_floor_when_no_manual():
    # EC with no manual bonus still gets the structure role bonus (not zero).
    assert rr._cost_role(_fac(FacilityType.RAITARU, 0.0)) == EC_COST_ROLE
    assert rr._cost_role(_fac(FacilityType.AZBEL, None)) == EC_COST_ROLE


def test_cost_role_non_ec_no_floor():
    # A non-EC structure (e.g. Athanor) gets only the manual value.
    assert rr._cost_role(_fac(FacilityType.ATHANOR, 0.0)) == 0.0
    assert rr._cost_role(_fac(FacilityType.ATHANOR, 12.0)) == 12.0
