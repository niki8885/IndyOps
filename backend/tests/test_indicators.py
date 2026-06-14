"""Technical indicators against hand-computed reference series."""
import pandas as pd

from app.services.indicators import compute

RAMP = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)


def test_sma_reference():
    ind = compute(RAMP, 3)
    assert ind.sma.dropna().tolist() == [2.0, 3.0, 4.0, 5.0]


def test_bollinger_reference():
    ind = compute(RAMP, 3)
    # window-3 sample std of [1,2,3] == 1.0 → bands at sma ± 2·std
    assert ind.std.iloc[2] == 1.0
    assert ind.bb_upper.iloc[2] == 4.0
    assert ind.bb_lower.iloc[2] == 0.0


def test_ema_reference():
    # span=3 → alpha 0.5; ewm(adjust=False) of 1..6 ends at 5.03125
    ind = compute(RAMP, 3)
    assert ind.ema.iloc[-1] == 5.03125


def test_window_clamped_to_two():
    ind = compute(pd.Series([1.0, 2.0, 3.0]), 1)
    assert ind.sma.iloc[1] == 1.5   # rolling(2) mean of [1,2]


def test_constant_series_invariants():
    ind = compute(pd.Series([42.0] * 60), 5)
    assert (ind.std.dropna() == 0).all()
    assert (ind.sma.dropna() == 42.0).all()
    assert (ind.ema == 42.0).all()
    assert (ind.bb_upper.dropna() == 42.0).all()
    assert (ind.macd.abs() < 1e-9).all()         # ema12 == ema26 for a flat line
