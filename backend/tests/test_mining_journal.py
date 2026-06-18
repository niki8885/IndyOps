"""Tests for the pure mining-journal period/tax helpers."""
import datetime

import pytest

from app.services import mining_journal as mj


def test_day_bounds_and_offset():
    anchor = datetime.date(2026, 6, 18)
    assert mj.period_bounds("day", anchor, 0) == (anchor, anchor)
    assert mj.period_bounds("day", anchor, -1) == (datetime.date(2026, 6, 17),) * 2


def test_month_bounds():
    anchor = datetime.date(2026, 6, 18)
    assert mj.period_bounds("month", anchor, 0) == (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    # previous month rolls the year boundary correctly
    assert mj.period_bounds("month", datetime.date(2026, 1, 10), -1) == (
        datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))


def test_quarter_bounds():
    # June is in Q2 (Apr–Jun)
    assert mj.period_bounds("quarter", datetime.date(2026, 6, 18), 0) == (
        datetime.date(2026, 4, 1), datetime.date(2026, 6, 30))
    # previous quarter = Q1
    assert mj.period_bounds("quarter", datetime.date(2026, 6, 18), -1) == (
        datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))


def test_year_bounds():
    assert mj.period_bounds("year", datetime.date(2026, 6, 18), 0) == (
        datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))


def test_period_keys():
    d = datetime.date(2026, 6, 1)
    assert mj.period_key("day", datetime.date(2026, 6, 18)) == "2026-06-18"
    assert mj.period_key("month", d) == "2026-06"
    assert mj.period_key("quarter", datetime.date(2026, 4, 1)) == "2026-Q2"
    assert mj.period_key("year", d) == "2026"


def test_apply_tax():
    assert mj.apply_tax(1000.0, 10.0) == (100.0, 900.0)
    assert mj.apply_tax(0.0, 10.0) == (0.0, 0.0)
    assert mj.apply_tax(500.0, 0.0) == (0.0, 500.0)


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        mj.period_bounds("week", datetime.date(2026, 6, 18))
