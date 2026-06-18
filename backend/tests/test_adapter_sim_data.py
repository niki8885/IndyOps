"""Offline unit tests for ``app.adapters.sim_data``.

``sim_data.gather_history`` assembles a per-type :class:`TypeHistory` for the
profit simulator from two sources: tracked prices (``market_repo.track_prices_df``)
and, as a fallback, ESI daily history (``market.esi_region_history``). Both are
monkeypatched here so no DB or network is touched. The private ``_from_tracked``
and ``_from_esi`` mappers are also exercised directly with small DataFrames.
"""
import pandas as pd
import pytest

from app.adapters import sim_data
from app.services.profit_sim import TypeHistory


def _tracked_df(rows):
    """rows: list of (timestamp, place_id, buy, sell, volume)."""
    return pd.DataFrame(rows, columns=["timestamp", "place_id", "buy", "sell", "volume"])


# ── _from_tracked ────────────────────────────────────────────────────────────

def test_from_tracked_empty_df_returns_none():
    assert sim_data._from_tracked(_tracked_df([])) is None


def test_from_tracked_too_few_points_returns_none():
    df = _tracked_df([(i, 1, 10.0, 12.0, 5.0) for i in range(3)])  # < _MIN_POINTS
    assert sim_data._from_tracked(df) is None


def test_from_tracked_picks_most_populated_place():
    # place 1 has 9 points (>= _MIN_POINTS=8), place 2 only 2 → place 1 chosen
    rows = [(i, 1, 10.0 + i, 12.0 + i, 100.0) for i in range(9)]
    rows += [(i, 2, 999.0, 999.0, 1.0) for i in range(2)]
    th = sim_data._from_tracked(_tracked_df(rows))
    assert isinstance(th, TypeHistory)
    assert len(th.buy) == 9
    assert th.last_buy == pytest.approx(18.0)  # 10 + 8
    assert th.last_sell == pytest.approx(20.0)  # 12 + 8
    assert 999.0 not in th.buy  # the noisy place was not chosen


def test_from_tracked_skips_nan_values():
    rows = [(i, 1, (10.0 + i if i != 0 else float("nan")), 12.0 + i, 100.0) for i in range(9)]
    th = sim_data._from_tracked(_tracked_df(rows))
    # the NaN buy is dropped → 8 finite buys (still >= _MIN_POINTS)
    assert len(th.buy) == 8


# ── _from_esi ────────────────────────────────────────────────────────────────

def test_from_esi_none_when_empty():
    assert sim_data._from_esi([]) is None
    assert sim_data._from_esi(None) is None


def test_from_esi_too_few_points_returns_none():
    rows = [{"lowest": 1.0, "highest": 2.0, "volume": 10} for _ in range(3)]
    assert sim_data._from_esi(rows) is None


def test_from_esi_happy_path():
    rows = [{"lowest": 1.0 + i, "highest": 2.0 + i, "volume": 10 + i} for i in range(10)]
    th = sim_data._from_esi(rows)
    assert isinstance(th, TypeHistory)
    assert th.buy[0] == pytest.approx(1.0) and th.buy[-1] == pytest.approx(10.0)
    assert th.sell[0] == pytest.approx(2.0) and th.sell[-1] == pytest.approx(11.0)
    assert th.last_buy == pytest.approx(10.0)
    assert th.last_sell == pytest.approx(11.0)


def test_from_esi_falls_back_to_low_when_no_high():
    # highest missing → sell mirrors buy (low)
    rows = [{"lowest": 1.0 + i, "volume": 5} for i in range(10)]
    th = sim_data._from_esi(rows)
    assert th.sell == th.buy
    assert th.last_sell == th.last_buy == pytest.approx(10.0)


# ── gather_history (orchestration) ───────────────────────────────────────────

@pytest.fixture
def _patch_sources(monkeypatch):
    """Provide controllable tracked/ESI sources keyed by type_id."""
    state = {"tracked": {}, "esi": {}}

    def fake_track(db, user_id, tid):
        return state["tracked"].get(tid, _tracked_df([]))

    def fake_esi(region_id, tid):
        return state["esi"].get(tid)

    monkeypatch.setattr(sim_data.market_repo, "track_prices_df", fake_track)
    monkeypatch.setattr(sim_data.market, "esi_region_history", fake_esi)
    return state


def test_gather_history_uses_tracked_first(_patch_sources):
    _patch_sources["tracked"][34] = _tracked_df([(i, 1, 10.0 + i, 12.0 + i, 100.0) for i in range(9)])
    # ESI also present but tracked wins
    _patch_sources["esi"][34] = [{"lowest": 999, "highest": 1000, "volume": 1} for _ in range(10)]
    out = sim_data.gather_history(db=None, user_id=1, type_ids=[34], region_id=10000002)
    th = out[34]
    assert th.last_buy == pytest.approx(18.0)          # from tracked, not ESI
    assert 999.0 not in th.buy


def test_gather_history_falls_back_to_esi(_patch_sources):
    # tracked is empty → ESI used
    _patch_sources["esi"][34] = [{"lowest": 5.0 + i, "highest": 7.0 + i, "volume": 1} for i in range(10)]
    out = sim_data.gather_history(db=None, user_id=1, type_ids=[34], region_id=10000002)
    th = out[34]
    assert th.buy[0] == pytest.approx(5.0)
    assert th.last_sell == pytest.approx(16.0)


def test_gather_history_empty_typehistory_when_no_data(_patch_sources):
    # neither source has data → a bare TypeHistory, but anchors/last filled from points
    out = sim_data.gather_history(
        db=None, user_id=1, type_ids=[34], region_id=10000002,
        group_of={34: 7}, point_buy={34: 3.0}, point_sell={34: 4.0})
    th = out[34]
    assert th.buy == [] and th.sell == []
    assert th.group_id == 7
    assert th.last_buy == pytest.approx(3.0)
    assert th.last_sell == pytest.approx(4.0)
    assert th.anchor_buy == pytest.approx(3.0)
    assert th.anchor_sell == pytest.approx(4.0)


def test_gather_history_point_sell_defaults_to_point_buy(_patch_sources):
    out = sim_data.gather_history(
        db=None, user_id=1, type_ids=[34], region_id=10000002, point_buy={34: 9.0})
    th = out[34]
    assert th.last_sell == pytest.approx(9.0)    # falls back to point_buy
    assert th.anchor_sell == pytest.approx(9.0)


def test_gather_history_swallows_tracked_exception(_patch_sources, monkeypatch):
    def boom(db, user_id, tid):
        raise RuntimeError("db down")

    monkeypatch.setattr(sim_data.market_repo, "track_prices_df", boom)
    _patch_sources["esi"][34] = [{"lowest": 2.0, "highest": 3.0, "volume": 1} for _ in range(10)]
    out = sim_data.gather_history(db=None, user_id=1, type_ids=[34], region_id=10000002)
    # falls through to ESI despite the tracked-source error
    assert out[34].buy[0] == pytest.approx(2.0)


def test_gather_history_swallows_esi_exception(_patch_sources, monkeypatch):
    def boom(region_id, tid):
        raise RuntimeError("esi down")

    monkeypatch.setattr(sim_data.market, "esi_region_history", boom)
    out = sim_data.gather_history(
        db=None, user_id=1, type_ids=[34], region_id=10000002, point_buy={34: 1.0})
    # both sources failed → empty TypeHistory anchored on the point
    assert out[34].buy == []
    assert out[34].last_buy == pytest.approx(1.0)


def test_gather_history_multiple_types(_patch_sources):
    _patch_sources["esi"][34] = [{"lowest": 1.0, "highest": 2.0, "volume": 1} for _ in range(10)]
    out = sim_data.gather_history(db=None, user_id=1, type_ids=[34, 35], region_id=10000002,
                                  point_buy={35: 50.0})
    assert set(out.keys()) == {34, 35}
    assert out[34].buy[0] == pytest.approx(1.0)          # ESI-backed
    assert out[35].buy == []              # no data → empty
    assert out[35].last_buy == pytest.approx(50.0)       # point fallback
