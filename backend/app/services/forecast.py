"""Demand/price forecasting — the Python oracle (IO-49 phase 2).

Pure numpy (no statsmodels/scipy — dependency-free, like the rest of the native
stack). Defines the contract the Fortran ``forecast-engine`` must reproduce, and
serves as its fallback. Per target (volume *and* price) it fits a small panel of
deterministic models, picks the best by a walk-forward backtest (MASE), and emits
a P10/P50/P90 path with error metrics. The native port matches the point paths
tightly; the bands are deterministic here so they parity-check tightly too.

Models: seasonal-naive (the MASE benchmark), Holt linear, Holt-Winters additive
(weekly), Croston (intermittent demand), and ARIMA(p,d,0) = AR on the differenced
series. Full SARIMA (seasonal AR/MA via CSS) lands in the dedicated sub-phase.
"""
from __future__ import annotations
from typing import Callable, Optional

import numpy as np
import pandas as pd

from . import sarima
from ._numeric import clean
from .market_browser import _history_frame

SEASON = 7                       # weekly seasonality on daily candles
Z80 = 1.2815515594465777         # P10/P90 → 80% central interval
_GRID = (0.1, 0.3, 0.5, 0.7, 0.9)
_AR_P = 7
_FOLDS = 4


# ── individual models: fit_predict(train) → point forecast of length h ──

def f_snaive(y: np.ndarray, h: int, m: int = SEASON) -> np.ndarray:
    n = len(y)
    if n == 0:
        return np.zeros(h)
    if n < m:
        return np.full(h, y[-1])
    return np.array([y[n - m + (i % m)] for i in range(h)])


def _holt_run(y, alpha, beta):
    """Additive Holt (level+trend); return one-step in-sample SSE + final l,b."""
    level = y[0]
    trend = y[1] - y[0] if len(y) > 1 else 0.0
    sse = 0.0
    for t in range(1, len(y)):
        fitted = level + trend
        sse += (y[t] - fitted) ** 2
        prev_level = level
        level = alpha * y[t] + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return sse, level, trend


def f_holt(y: np.ndarray, h: int) -> np.ndarray:
    if len(y) < 3:
        return f_snaive(y, h)
    best = None
    for a in _GRID:
        for b in _GRID:
            sse, lvl, tr = _holt_run(y, a, b)
            if best is None or sse < best[0]:
                best = (sse, lvl, tr)
    _, lvl, tr = best
    return np.array([lvl + (i + 1) * tr for i in range(h)])


def _hw_run(y, alpha, beta, gamma, m):
    """Additive Holt-Winters; one-step SSE + final state for forecasting."""
    n = len(y)
    level = float(np.mean(y[:m]))
    trend = float((np.mean(y[m:2 * m]) - np.mean(y[:m])) / m)
    season = [y[i] - level for i in range(m)]
    sse = 0.0
    for t in range(m, n):
        s = season[t % m]
        fitted = level + trend + s
        sse += (y[t] - fitted) ** 2
        prev_level = level
        level = alpha * (y[t] - s) + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        season[t % m] = gamma * (y[t] - level) + (1 - gamma) * s
    return sse, level, trend, season, n


def f_hw(y: np.ndarray, h: int, m: int = SEASON) -> np.ndarray:
    if len(y) < 2 * m:
        return f_holt(y, h)
    best = None
    for a in _GRID:
        for b in _GRID:
            for g in _GRID:
                state = _hw_run(y, a, b, g, m)
                if best is None or state[0] < best[0]:
                    best = state
    _, level, trend, season, n = best
    return np.array([level + (i + 1) * trend + season[(n + i) % m] for i in range(h)])


def f_croston(y: np.ndarray, h: int, alpha: float = 0.1) -> np.ndarray:
    """Croston's method for intermittent demand → constant-rate forecast."""
    nz = np.flatnonzero(y > 0)
    if nz.size == 0:
        return np.zeros(h)
    z = y[nz[0]]                  # demand size estimate
    p = 1.0                       # inter-arrival interval estimate
    q = 1
    for t in range(nz[0] + 1, len(y)):
        if y[t] > 0:
            z = alpha * y[t] + (1 - alpha) * z
            p = alpha * q + (1 - alpha) * p
            q = 1
        else:
            q += 1
    rate = z / p if p else 0.0
    return np.full(h, rate)


def f_ar(y: np.ndarray, h: int, p: int = _AR_P, d: int = 1) -> np.ndarray:
    """ARIMA(p,d,0): AR(p) (OLS, with intercept) on the d-differenced series."""
    if len(y) < p + d + 3:
        return f_holt(y, h)
    z = np.diff(y, n=d) if d > 0 else y.astype(float)
    if len(z) <= p + 1:
        return f_holt(y, h)
    rows = len(z) - p
    X = np.empty((rows, p + 1))
    X[:, 0] = 1.0
    for k in range(1, p + 1):
        X[:, k] = z[p - k:p - k + rows]
    target = z[p:]
    coef, *_ = np.linalg.lstsq(X, target, rcond=None)
    hist = list(z[-p:])
    zf = []
    for _ in range(h):
        nxt = coef[0] + sum(coef[k + 1] * hist[-1 - k] for k in range(p))
        zf.append(nxt)
        hist.append(nxt)
    if d > 0:
        return y[-1] + np.cumsum(zf)
    return np.array(zf)


def f_sarima(y: np.ndarray, h: int) -> np.ndarray:
    """Auto-SARIMA (services.sarima); falls back to Holt if nothing fits/diverges."""
    fc = sarima.f_sarima(y, h, SEASON)
    return fc if fc is not None else f_holt(y, h)


_MODELS: dict[str, Callable] = {
    "seasonal_naive": f_snaive, "holt": f_holt, "holt_winters": f_hw,
    "croston": f_croston, "arima": f_ar, "sarima": f_sarima,
}
_VOLUME_PANEL = ("seasonal_naive", "holt_winters", "arima", "croston", "sarima")
_PRICE_PANEL = ("seasonal_naive", "holt", "holt_winters", "arima", "sarima")


# ── backtest + selection ──

def _mase_scale(train: np.ndarray, m: int) -> float:
    if len(train) <= m:
        return float("nan")
    d = np.abs(train[m:] - train[:-m])
    s = float(np.mean(d)) if d.size else float("nan")
    return s if s > 0 else float("nan")


def _backtest(y: np.ndarray, model: Callable, h: int, m: int) -> dict:
    """Rolling-origin walk-forward; pooled metrics + per-step residual sigma."""
    n = len(y)
    min_train = max(2 * m, 10)
    resid_by_step = [[] for _ in range(h)]
    fc_all, act_all = [], []
    for k in range(1, _FOLDS + 1):
        cut = n - k * h
        if cut < min_train:
            break
        fc = model(y[:cut], h)
        act = y[cut:cut + h]
        L = len(act)
        for i in range(L):
            resid_by_step[i].append(fc[i] - act[i])
        fc_all.extend(fc[:L]); act_all.extend(act)
    if not fc_all:
        return {"mase": float("nan"), "mape": float("nan"), "smape": float("nan"),
                "rmse": float("nan"), "dir_acc": float("nan"), "sigma_step": None}
    fc_a = np.array(fc_all); act_a = np.array(act_all)
    err = fc_a - act_a
    scale = _mase_scale(y, m)
    mae = float(np.mean(np.abs(err)))
    nz = act_a != 0
    mape = float(np.mean(np.abs(err[nz] / act_a[nz]))) if nz.any() else float("nan")
    denom = np.abs(fc_a) + np.abs(act_a)
    sm = denom != 0
    smape = float(np.mean(2 * np.abs(err[sm]) / denom[sm])) if sm.any() else float("nan")
    rmse = float(np.sqrt(np.mean(err ** 2)))
    dir_acc = float(np.mean(np.sign(fc_a) == np.sign(act_a))) if len(act_a) else float("nan")
    overall_sigma = float(np.std(err)) if err.size else float("nan")
    sigma_step = [float(np.std(r)) if len(r) >= 2 else overall_sigma for r in resid_by_step]
    return {"mase": mae / scale if scale == scale and scale else float("nan"),
            "mape": mape, "smape": smape, "rmse": rmse, "dir_acc": dir_acc,
            "sigma_step": sigma_step}


def _forecast_one(y: np.ndarray, h: int, panel: tuple[str, ...], m: int = SEASON) -> dict:
    candidates = []
    for name in panel:
        bt = _backtest(y, _MODELS[name], h, m)
        candidates.append({"model": name, "mase": clean(bt["mase"]),
                           "mape": clean(bt["mape"]), "rmse": clean(bt["rmse"]), "_bt": bt})

    def keyf(c):
        v = c["mase"]
        return v if (v is not None and v == v) else float("inf")
    best = min(candidates, key=keyf)
    bt = best["_bt"]

    p50 = _MODELS[best["model"]](y, h)
    sigma = bt["sigma_step"] or [float(np.std(y))] * h
    sig = np.array([sigma[i] if i < len(sigma) else sigma[-1] for i in range(h)])
    p10 = p50 - Z80 * sig
    p90 = p50 + Z80 * sig
    if panel is _VOLUME_PANEL:                # volume cannot go negative
        p50 = np.clip(p50, 0, None); p10 = np.clip(p10, 0, None); p90 = np.clip(p90, 0, None)

    return {
        "model": best["model"],
        "p50": [clean(v) for v in p50],
        "p10": [clean(v) for v in p10],
        "p90": [clean(v) for v in p90],
        "backtest": {"mase": clean(bt["mase"]), "mape": clean(bt["mape"]),
                     "smape": clean(bt["smape"]), "rmse": clean(bt["rmse"]),
                     "dir_acc": clean(bt["dir_acc"])},
        "candidates": [{"model": c["model"], "mase": c["mase"], "mape": c["mape"]}
                       for c in candidates],
    }


def _signal(vol_fc: dict, price_fc: dict, recent_adv: float) -> dict:
    """produce / hold / avoid from forecast direction vs recent demand."""
    vp = np.array([v for v in vol_fc["p50"] if v is not None], dtype=float)
    pp = np.array([v for v in price_fc["p50"] if v is not None], dtype=float)
    if vp.size == 0 or not recent_adv:
        return {"action": "hold", "score": clean(50.0), "reason": "insufficient history"}
    vol_ratio = float(np.mean(vp)) / recent_adv          # future demand vs recent ADV
    price_trend = (float(pp[-1] / pp[0] - 1.0) if pp.size > 1 and pp[0] else 0.0)
    score = float(np.clip(50 + 50 * (vol_ratio - 1.0) + 40 * price_trend, 0, 100))
    if vol_ratio >= 0.9 and price_trend > -0.1:
        action, reason = "produce", f"demand {vol_ratio:.0%} of ADV, price {price_trend:+.0%}"
    elif vol_ratio < 0.6 or price_trend < -0.15:
        action, reason = "avoid", f"demand {vol_ratio:.0%} of ADV, price {price_trend:+.0%}"
    else:
        action, reason = "hold", f"demand {vol_ratio:.0%} of ADV, price {price_trend:+.0%}"
    return {"action": action, "score": clean(score), "reason": reason}


def clean_series(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """ESI history → model-ready (volume, price): missing volume = 0 (no trade),
    missing price interpolated. Shared by the Python path and the native adapter."""
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).to_numpy(float)
    price = df["price"].astype(float).interpolate().bfill().ffill().to_numpy(float)
    return vol, price


def forecast_targets(vol: np.ndarray, price: np.ndarray, h: int) -> tuple[dict, dict]:
    """The heavy half (the native forecast-engine replaces this): per-target panel
    fit + backtest + bands for volume and price."""
    return _forecast_one(vol, h, _VOLUME_PANEL), _forecast_one(price, h, _PRICE_PANEL)


def assemble(df: pd.DataFrame, type_id: int, label: str, region_name: Optional[str],
             h: int, vol: np.ndarray, price: np.ndarray, vol_fc: dict, price_fc: dict,
             hist_tail: int = 90) -> dict:
    """The trivial glue (engine-agnostic): future dates, history tail, turnover, signal."""
    last_ts = df["timestamp"].iloc[-1]
    future = [(last_ts + pd.Timedelta(days=i + 1)).isoformat() for i in range(h)]
    vp = np.array([v if v is not None else 0.0 for v in vol_fc["p50"]])
    pp = np.array([v if v is not None else 0.0 for v in price_fc["p50"]])
    turnover = {"p50": [clean(v) for v in vp * pp]}
    recent_adv = float(np.mean(vol[-30:])) if len(vol) else 0.0
    tail = min(len(df), hist_tail)
    history = {
        "timestamps": [t.isoformat() for t in df["timestamp"].iloc[-tail:]],
        "volume": [clean(v) for v in vol[-tail:]],
        "price": [clean(v) for v in price[-tail:]],
    }
    return {
        "type_id": type_id,
        "label": label,
        "region_name": region_name,
        "horizon": h,
        "future": future,
        "history": history,
        "volume": vol_fc,
        "price": price_fc,
        "isk_turnover": turnover,
        "signal": _signal(vol_fc, price_fc, recent_adv),
        "points": int(len(df)),
    }


def forecast_payload(history: list[dict], type_id: int, label: str,
                     region_name: Optional[str], horizon: int) -> dict:
    """Forecast volume + price `horizon` days ahead with bands, metrics and a signal."""
    h = max(1, int(horizon))
    df = _history_frame(history)
    vol, price = clean_series(df)
    vol_fc, price_fc = forecast_targets(vol, price, h)
    return assemble(df, type_id, label, region_name, h, vol, price, vol_fc, price_fc)
