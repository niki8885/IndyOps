"""JSON-safe numeric coercion helpers."""
import numpy as np
import pandas as pd

from app.services._numeric import clean, series


def test_clean_passthrough():
    assert clean(None) is None
    assert clean("x") == "x"
    assert clean(5) == 5


def test_clean_nan_and_inf_become_none():
    assert clean(float("nan")) is None
    assert clean(float("inf")) is None
    assert clean(np.float64("nan")) is None


def test_clean_coerces_numpy_scalars_to_python():
    v = clean(np.float64(1.5))
    assert v == 1.5 and isinstance(v, float)
    i = clean(np.int64(3))
    assert i == 3 and isinstance(i, int)


def test_series_cleans_each_element():
    assert series(pd.Series([1.0, float("nan"), 3.0])) == [1.0, None, 3.0]
