"""
Markowitz mean-variance portfolio optimisation for the trade-haul planner.

Pure math (no I/O / ORM) — the Python oracle behind the native ``portfolio-opt``
Fortran binary (``adapters/portfolio.py``) and the parity baseline.

The model is long-only, fully-invested, with a DIAGONAL covariance (per-item return
volatility, items assumed independent — "Markowitz for now"):

    maximise   sum(mu_i w_i) - (lambda/2) * sum(sigma_i^2 w_i^2)
    s.t.       sum(w) = 1,   w_i >= 0

which has the closed-form "water-filling" solution
``w_i = max(0, (mu_i - nu) / (lambda sigma_i^2))`` with ``nu`` set so ``sum(w)=1``
(found by bisection, since ``sum(w(nu))`` is monotone non-increasing in ``nu``).
This mirrors ``fortran/analytics-engine/src/portfolio.f90`` exactly (deterministic
parity). :func:`build_portfolio` then turns the weights into integer buy quantities
that fit the ISK budget, capped by each item's liquidity.
"""
from __future__ import annotations

import math

SIGMA_FLOOR = 1.0e-6     # avoid div-by-zero on (near-)riskless items
LAMBDA_FLOOR = 1.0e-9    # keep the QP well-defined at lambda ~ 0


def _metrics(weights: list[float], mu: list[float], sigma: list[float]) -> dict:
    var = sum((max(s, SIGMA_FLOOR) ** 2) * (w * w) for w, s in zip(weights, sigma))
    exp_ret = sum(m * w for m, w in zip(mu, weights))
    return {"exp_return": exp_ret, "variance": var, "stddev": math.sqrt(max(var, 0.0))}


def optimize(mu, sigma, risk_aversion: float) -> tuple[list[float], dict]:
    """Optimal long-only weights on the budget simplex (diagonal Sigma).

    Returns ``(weights, metrics)`` where ``metrics`` = ``{exp_return, variance,
    stddev}``. Deterministic — matches the Fortran ``portfolio-opt`` engine."""
    mu = [float(x) for x in mu]
    sigma = [float(x) for x in sigma]
    n = len(mu)
    if n == 0:
        return [], {"exp_return": 0.0, "variance": 0.0, "stddev": 0.0}
    if n == 1:
        return [1.0], _metrics([1.0], mu, sigma)

    lam = max(float(risk_aversion), LAMBDA_FLOOR)
    s2 = [max(s, SIGMA_FLOOR) ** 2 for s in sigma]

    def wsum(nu: float) -> float:
        return sum(max(0.0, (m - nu) / (lam * c)) for m, c in zip(mu, s2))

    nu_hi = max(mu)                       # sum(w) -> 0 at nu = max(mu)
    step = lam * max(s2)
    if step <= 0.0:
        step = 1.0
    nu_lo = nu_hi - step
    while wsum(nu_lo) < 1.0:               # expand down until sum >= 1
        step *= 2.0
        nu_lo -= step

    for _ in range(200):                  # bisection (matches the Fortran loop count)
        nu = 0.5 * (nu_lo + nu_hi)
        if wsum(nu) > 1.0:
            nu_lo = nu
        else:
            nu_hi = nu
    nu = 0.5 * (nu_lo + nu_hi)

    w = [max(0.0, (m - nu) / (lam * c)) for m, c in zip(mu, s2)]
    total = sum(w)
    if total > 0.0:
        w = [x / total for x in w]        # clean tiny residual so sum == 1
    return w, _metrics(w, mu, sigma)


def frontier_lambdas(n: int = 24, lo: float = 0.3, hi: float = 300.0) -> list[float]:
    """Log-spaced risk-aversion λ sweep for tracing the efficient frontier."""
    if n < 2:
        return [lo]
    r = (hi / lo) ** (1.0 / (n - 1))
    return [lo * (r ** i) for i in range(n)]


def efficient_frontier(mu, sigma, lambdas=None) -> list[dict]:
    """Trace the Markowitz efficient frontier: the optimal ``(stddev, exp_return)``
    for a sweep of risk aversions, sorted by risk and de-duplicated (small universes
    collapse to a point). Each entry = ``{risk_aversion, stddev, exp_return}``."""
    mu = [float(x) for x in mu]
    sigma = [float(x) for x in sigma]
    if not mu:
        return []
    lambdas = lambdas if lambdas is not None else frontier_lambdas()
    pts = []
    for lam in lambdas:
        _, m = optimize(mu, sigma, lam)
        pts.append({"risk_aversion": lam,
                    "stddev": round(m["stddev"], 8), "exp_return": round(m["exp_return"], 8)})
    pts.sort(key=lambda p: (p["stddev"], p["exp_return"]))
    out: list[dict] = []
    for p in pts:
        if (not out or abs(p["stddev"] - out[-1]["stddev"]) > 1e-9
                or abs(p["exp_return"] - out[-1]["exp_return"]) > 1e-9):
            out.append(p)
    return out


def _liquidity_cap(asset: dict, horizon_days: int) -> int | None:
    dv = asset.get("daily_volume")
    if not dv:
        return None
    return int(math.floor(float(dv) * max(horizon_days, 0)))


def build_portfolio(assets: list[dict], weights: list[float], budget: float, *,
                    horizon_days: int = 7) -> dict:
    """Turn optimal weights into integer buy quantities that fit the ISK ``budget``.

    Each ``asset``: ``{type_id, name, unit_cost, unit_profit, roi, sigma,
    unit_vol_m3, daily_volume, best_method, ...}`` (unit_cost = per-unit capital incl.
    shipping; unit_profit = per-unit net). ``qty_i = floor(w_i*budget / unit_cost_i)``
    capped by liquidity (``daily_volume * horizon_days``); leftover budget is then
    greedily topped up by descending ROI (single pass), respecting the caps."""
    budget = max(float(budget or 0.0), 0.0)
    allocs: list[dict] = []
    for a, w in zip(assets, weights):
        unit_cost = float(a.get("unit_cost") or 0.0)
        cap = _liquidity_cap(a, horizon_days)
        qty = int(math.floor((w * budget) / unit_cost)) if unit_cost > 0 else 0
        if cap is not None:
            qty = min(qty, cap)
        allocs.append({
            "type_id": a.get("type_id"), "name": a.get("name"),
            "category_id": a.get("category_id"), "best_method": a.get("best_method"),
            "unit_cost": round(unit_cost, 2), "unit_profit": round(float(a.get("unit_profit") or 0.0), 2),
            "roi": float(a.get("roi") or 0.0), "weight": float(w),
            "unit_vol_m3": float(a.get("unit_vol_m3") or 0.0), "qty": max(qty, 0),
        })

    spent = sum(al["qty"] * al["unit_cost"] for al in allocs)
    leftover = budget - spent
    # greedy top-up by descending ROI, one shot per asset
    for i in sorted(range(len(allocs)), key=lambda j: allocs[j]["roi"], reverse=True):
        unit_cost = allocs[i]["unit_cost"]
        if unit_cost <= 0 or unit_cost > leftover:
            continue
        cap = _liquidity_cap(assets[i], horizon_days)
        room = (cap - allocs[i]["qty"]) if cap is not None else None
        extra = int(math.floor(leftover / unit_cost))
        if room is not None:
            extra = min(extra, max(room, 0))
        if extra <= 0:
            continue
        allocs[i]["qty"] += extra
        leftover -= extra * unit_cost
        spent += extra * unit_cost

    for al in allocs:
        al["capital"] = round(al["qty"] * al["unit_cost"], 2)
        al["expected_profit"] = round(al["qty"] * al["unit_profit"], 2)
        al["volume_m3"] = round(al["qty"] * al["unit_vol_m3"], 2)
    allocs.sort(key=lambda x: x["capital"], reverse=True)

    capital_used = round(sum(al["capital"] for al in allocs), 2)
    expected_profit = round(sum(al["expected_profit"] for al in allocs), 2)
    total_volume = round(sum(al["volume_m3"] for al in allocs), 2)
    chosen = [al for al in allocs if al["qty"] > 0]
    totals = {
        "budget": round(budget, 2),
        "capital_used": capital_used,
        "leftover": round(budget - capital_used, 2),
        "expected_profit": expected_profit,
        "portfolio_roi": round(expected_profit / capital_used, 6) if capital_used > 0 else 0.0,
        "total_volume_m3": total_volume,
        "n_assets": len(chosen),
        "n_considered": len(allocs),
    }
    return {"allocations": allocs, "totals": totals}
