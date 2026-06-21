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


def _item_caps(asset: dict, budget: float, *, participation: float, horizon_days: int,
               max_weight_frac: float) -> tuple[float, int | None]:
    """The most you may deploy in one item — the tighter of a realistic LIQUIDITY limit
    (``participation · daily_volume · horizon_days`` units) and a DIVERSIFICATION limit
    (``max_weight_frac · budget`` ISK). Returns ``(cap_isk, cap_units)`` (cap_units None
    when the item has no volume data → only the diversification cap applies)."""
    c = float(asset.get("unit_cost") or 0.0)
    dv = asset.get("daily_volume")
    cap_units = (int(math.floor(float(dv) * max(participation, 0.0) * max(horizon_days, 0)))
                 if dv else None)
    liq_isk = (cap_units * c) if (cap_units is not None and c > 0) else math.inf
    div_isk = max(max_weight_frac, 0.0) * budget
    return max(0.0, min(liq_isk, div_isk)), cap_units


def build_portfolio(assets: list[dict], weights: list[float], budget: float, *,
                    horizon_days: int = 7, participation: float = 0.10,
                    max_weight: float = 0.25) -> dict:
    """Turn optimal weights into integer buy quantities that fit the ISK ``budget``,
    bounded so the plan is actually *sellable*.

    Each ``asset``: ``{type_id, name, unit_cost, unit_profit, roi, sigma, unit_vol_m3,
    daily_volume, best_method}`` (unit_cost = per-unit capital incl. shipping).

    Two caps bound every position: a LIQUIDITY cap (``participation·daily_volume·
    horizon_days`` units — you can't offload more than a slice of market volume) and a
    DIVERSIFICATION cap (``max_weight`` of budget, floored at ``1/N`` so a small basket
    can still spend the budget). The budget is distributed proportionally to the
    optimizer weights via **capped water-filling** (when an item hits a cap its share
    flows to the rest), leftover is topped up by best ROI under the same caps, and the
    reported ``weight`` is the REALIZED capital share (so it matches the quantities)."""
    budget = max(float(budget or 0.0), 0.0)
    n = len(assets)
    weights = list(weights) + [0.0] * max(0, n - len(weights))
    eff_maxw = max(max_weight, 1.0 / n) if n else 0.0

    cap_isk: list[float] = []
    cap_units: list[int | None] = []
    for a in assets:
        ci, cu = _item_caps(a, budget, participation=participation,
                            horizon_days=horizon_days, max_weight_frac=eff_maxw)
        cap_isk.append(ci)
        cap_units.append(cu)

    # 1) capped water-filling: distribute the budget proportionally to the weights,
    #    never past a cap; a capped item's share redistributes to the others.
    alloc_isk = [0.0] * n
    active = [i for i in range(n)
              if weights[i] > 0 and cap_isk[i] > 0 and float(assets[i].get("unit_cost") or 0) > 0]
    remaining = budget
    for _ in range(n + 2):
        if remaining <= 1.0 or not active:
            break
        wsum = sum(weights[i] for i in active)
        if wsum <= 0:
            break
        full_fill = remaining / wsum                       # ISK-per-weight if nobody caps
        min_fill = min((cap_isk[i] - alloc_isk[i]) / weights[i] for i in active)
        fill = min(full_fill, min_fill)
        for i in active:
            alloc_isk[i] += fill * weights[i]
        remaining -= fill * wsum
        if full_fill <= min_fill:
            break
        active = [i for i in active if alloc_isk[i] < cap_isk[i] - 1e-6]

    # 2) integer quantities (floored), clamped to the liquidity unit cap
    allocs: list[dict] = []
    for i, a in enumerate(assets):
        c = float(a.get("unit_cost") or 0.0)
        q = int(math.floor(alloc_isk[i] / c)) if c > 0 else 0
        if cap_units[i] is not None:
            q = min(q, cap_units[i])
        allocs.append({
            "type_id": a.get("type_id"), "name": a.get("name"),
            "category_id": a.get("category_id"), "best_method": a.get("best_method"),
            "unit_cost": round(c, 2), "unit_profit": round(float(a.get("unit_profit") or 0.0), 2),
            "roi": float(a.get("roi") or 0.0), "sigma": float(a.get("sigma") or 0.0),
            "unit_vol_m3": float(a.get("unit_vol_m3") or 0.0), "qty": max(q, 0),
        })

    # 3) deploy leftover budget into the best-ROI items still under their caps
    spent = sum(al["qty"] * al["unit_cost"] for al in allocs)
    leftover = budget - spent
    for i in sorted(range(n), key=lambda j: allocs[j]["roi"], reverse=True):
        c = allocs[i]["unit_cost"]
        if c <= 0 or c > leftover:
            continue
        cap_q = int(math.floor(cap_isk[i] / c))
        if cap_units[i] is not None:
            cap_q = min(cap_q, cap_units[i])
        room = cap_q - allocs[i]["qty"]
        if room <= 0:
            continue
        extra = min(int(math.floor(leftover / c)), room)
        if extra <= 0:
            continue
        allocs[i]["qty"] += extra
        leftover -= extra * c
        spent += extra * c

    # 4) derived fields + REALIZED capital weights (so chart == table)
    for al in allocs:
        al["capital"] = round(al["qty"] * al["unit_cost"], 2)
        al["expected_profit"] = round(al["qty"] * al["unit_profit"], 2)
        al["volume_m3"] = round(al["qty"] * al["unit_vol_m3"], 2)
    capital_used = sum(al["capital"] for al in allocs)
    for al in allocs:
        al["weight"] = (al["capital"] / capital_used) if capital_used > 0 else 0.0
    allocs.sort(key=lambda x: x["capital"], reverse=True)

    expected_profit = sum(al["expected_profit"] for al in allocs)
    realized_return = sum(al["weight"] * al["roi"] for al in allocs)
    realized_var = sum((al["weight"] ** 2) * (al["sigma"] ** 2) for al in allocs)
    chosen = [al for al in allocs if al["qty"] > 0]
    totals = {
        "budget": round(budget, 2),
        "capital_used": round(capital_used, 2),
        "leftover": round(budget - capital_used, 2),
        "expected_profit": round(expected_profit, 2),
        "portfolio_roi": round(expected_profit / capital_used, 6) if capital_used > 0 else 0.0,
        "total_volume_m3": round(sum(al["volume_m3"] for al in allocs), 2),
        "stddev": round(math.sqrt(max(realized_var, 0.0)), 8),
        "exp_return": round(realized_return, 8),
        "n_assets": len(chosen),
        "n_considered": n,
    }
    for al in allocs:
        al.pop("sigma", None)
    return {"allocations": allocs, "totals": totals}
