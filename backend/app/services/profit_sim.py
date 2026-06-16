"""
Monte-Carlo profit simulator — the pure Python core (oracle + fallback).

Wraps the deterministic profit calc (``services.chain.ChainPlan`` /
``services.manufacturing.CalcResult``) in a market-uncertainty model: it samples
correlated buy/sell prices, liquidity, spread, execution risk and logistics delay
over thousands of scenarios and reduces them to risk-adjusted metrics
(E[Profit], VaR/CVaR, σ, CV, P(loss), percentiles, time) plus the inputs for
strategy ranking.

This module is the **oracle**: the native Fortran engine
(``fortran/analytics-engine`` → ``profit-sim``) must match it statistically
(``tests/test_profit_sim_fortran_parity.py``), and the adapter falls back to it
when the binary is missing. Pure numpy/stdlib, no I/O — see
[[indyops-service-layering]] and the same contract as
[[indyops-fortran-analytics-engine]].

The model (one strategy, iteration k); ``j`` ranges over buy-legs + the product:

    z   ~ correlated N(0,1)              (Cholesky L·ε  | factor loadings·F + idio·η)
    price_j = qgrid_j(Φ(z_j))            (empirical)  | exp(mu_j + sigma_j·z_j)  (lognormal)
    acquire_j = price_j·(1 + slippage·spread_j)        sell = price·(1 − slippage·spread)
    fill_j  = min(1, participation_cap·volume_j·horizon / qty_j)
    material_cost = Σ acquire_j·qty_j·(1 + (1−fill_j)·shortfall_premium)
    revenue       = product_qty·sell·fill_product
    net_profit    = revenue − revenue·(broker+tax)/100 − material_cost − fixed_cost − logistics
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.services import market_model
from app.services.market_model import QGRID_POINTS

# ── normal CDF (Gaussian copula) ────────────────────────────────────────────────

_erf = np.frompyfunc(math.erf, 1, 1)


def norm_cdf(z: np.ndarray) -> np.ndarray:
    """Standard-normal CDF Φ, elementwise. Exact ``math.erf`` (matches gfortran's
    intrinsic ``erf`` used by the native engine)."""
    return 0.5 * (1.0 + _erf(np.asarray(z, dtype=float) / math.sqrt(2.0)).astype(float))


# ── contract: request ───────────────────────────────────────────────────────────

@dataclass
class LegInput:
    """One bought material (a chain shopping line / a recipe material)."""
    type_id: int
    qty: int
    mu: float          # lognormal log-mean of acquire price
    sigma: float       # lognormal log-std
    qgrid: list[float]  # 101-pt empirical quantile grid of acquire price
    vol_mean: float = 0.0
    vol_sigma: float = 0.5
    spread_mean: float = 0.0
    spread_sigma: float = 0.5
    group_id: int = 0


@dataclass
class ProductInput:
    """The manufactured product we sell."""
    type_id: int
    qty: int
    mu: float
    sigma: float
    qgrid: list[float]
    vol_mean: float = 0.0
    vol_sigma: float = 0.5
    spread_mean: float = 0.0
    spread_sigma: float = 0.5
    group_id: int = 0
    broker_fee_pct: float = 0.0
    sales_tax_pct: float = 0.0


@dataclass
class SimParams:
    n_iterations: int = 25_000
    seed: int = 42
    horizon_days: float = 1.0
    corr_mode: int = 0          # 0 = Cholesky matrix, 1 = factor model
    dist_mode: int = 0          # 0 = empirical (copula), 1 = lognormal
    participation_cap: float = 0.10   # max fraction of period volume we can execute
    shortfall_premium: float = 0.25   # extra cost to source an unfilled material
    slippage: float = 0.50            # how much of the spread we cross
    haul_delay_prob: float = 0.0
    haul_delay_hours_mean: float = 0.0
    holding_daily_rate: float = 0.0   # capital holding cost per day of delay
    slots: int = 1
    risk_lambda: float = 1.0          # risk-aversion in risk_adjusted = E − λσ


@dataclass
class SimRequest:
    label: str
    legs: list[LegInput]
    product: ProductInput
    fixed_cost: float            # install + bpc — deterministic conversion cost
    production_time_s: int
    params: SimParams = field(default_factory=SimParams)
    # dependency structure (var order = legs…, product last). Both are pre-built so
    # the engine can switch corr_mode without re-estimating.
    cholesky_L: Optional[list[list[float]]] = None
    loadings: Optional[list[list[float]]] = None
    factor_sigma: Optional[list[float]] = None
    idio_sigma: Optional[list[float]] = None


# ── contract: result ─────────────────────────────────────────────────────────────

@dataclass
class SimMetrics:
    n_iterations: int
    expected_profit: float
    median_profit: float
    std: float
    cv: float
    var5: float
    var1: float
    cvar5: float
    worst1: float
    prob_loss: float
    percentiles: dict[str, float]
    best: float
    worst: float
    hist_counts: list[int]
    hist_edges: list[float]
    breakdown: dict[str, dict]
    time_mean_h: float
    time_median_h: float
    time_p95_h: float
    time_per_job_h: float
    time_hist_counts: list[int]
    time_hist_edges: list[float]
    sharpe_like: float
    risk_adjusted: float
    return_per_slot: float
    return_per_time: float


@dataclass
class SimResult:
    label: str
    metrics: SimMetrics
    engine: str = "python"


# ── simulation core ──────────────────────────────────────────────────────────────

def _draw_shocks(req: SimRequest, rng: np.random.Generator, n: int, nvars: int) -> np.ndarray:
    """Correlated standard-normal price shocks ``[n × nvars]`` (marginally N(0,1))."""
    if req.params.corr_mode == 1 and req.loadings is not None:
        loadings = np.asarray(req.loadings, dtype=float)            # [nvars × K]
        k = loadings.shape[1]
        fsig = np.asarray(req.factor_sigma, dtype=float) if req.factor_sigma else np.ones(k)
        idio = np.asarray(req.idio_sigma, dtype=float) if req.idio_sigma else np.zeros(nvars)
        factors = rng.standard_normal((n, k)) * fsig
        eta = rng.standard_normal((n, nvars))
        return factors @ loadings.T + eta * idio
    L = np.asarray(req.cholesky_L, dtype=float) if req.cholesky_L is not None else np.eye(nvars)
    return rng.standard_normal((n, nvars)) @ L.T


def _interp_grids(grids: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Per-column linear interpolation of uniforms ``u`` ``[n × nvars]`` through each
    variable's quantile grid ``grids`` ``[nvars × K]`` (matches the engine's grid)."""
    k = grids.shape[1]
    pos = np.clip(u, 0.0, 1.0) * (k - 1)
    lo = np.clip(np.floor(pos).astype(int), 0, k - 2)
    frac = pos - lo
    out = np.empty_like(u)
    for j in range(grids.shape[0]):
        g = grids[j]
        out[:, j] = g[lo[:, j]] + frac[:, j] * (g[lo[:, j] + 1] - g[lo[:, j]])
    return out


def simulate(req: SimRequest) -> SimResult:
    """Run the Monte-Carlo and reduce it to :class:`SimMetrics`. Vectorised numpy."""
    p = req.params
    n = max(1, int(p.n_iterations))
    legs = req.legs
    m = len(legs)
    nvars = m + 1
    rng = np.random.default_rng(p.seed)

    mu = np.array([l.mu for l in legs] + [req.product.mu])
    sigma = np.array([l.sigma for l in legs] + [req.product.sigma])
    vol_mean = np.array([l.vol_mean for l in legs] + [req.product.vol_mean])
    vol_sig = np.array([l.vol_sigma for l in legs] + [req.product.vol_sigma])
    spr_mean = np.array([l.spread_mean for l in legs] + [req.product.spread_mean])
    spr_sig = np.array([l.spread_sigma for l in legs] + [req.product.spread_sigma])
    qty = np.array([l.qty for l in legs], dtype=float)

    # 1. correlated price shocks → 2. marginal prices
    z = _draw_shocks(req, rng, n, nvars)
    if p.dist_mode == 1:
        price = np.exp(mu + sigma * z)
    else:
        grids = np.array([l.qgrid for l in legs] + [req.product.qgrid])
        price = _interp_grids(grids, norm_cdf(z))

    # 3. spread / execution price
    spread = spr_mean * np.exp(spr_sig * rng.standard_normal((n, nvars)))
    buy_price = price[:, :m] * (1.0 + p.slippage * spread[:, :m])
    sell_price = price[:, m] * (1.0 - p.slippage * spread[:, m])

    # 4. liquidity / fill (market-execution risk)
    volume = vol_mean * np.exp(vol_sig * rng.standard_normal((n, nvars)))
    exec_cap = p.participation_cap * volume * p.horizon_days
    with np.errstate(divide="ignore", invalid="ignore"):
        fill_mat = np.where(qty > 0, np.minimum(1.0, exec_cap[:, :m] / qty), 1.0)
        fill_prod = np.where(req.product.qty > 0,
                             np.minimum(1.0, exec_cap[:, m] / req.product.qty), 1.0)

    # 5. P&L per scenario
    base_mat = buy_price * qty
    material_cost = (base_mat * (1.0 + (1.0 - fill_mat) * p.shortfall_premium)).sum(axis=1)
    revenue = req.product.qty * sell_price * fill_prod
    taxes = revenue * (req.product.broker_fee_pct + req.product.sales_tax_pct) / 100.0

    delayed = rng.random(n) < p.haul_delay_prob
    extra_h = np.where(delayed & (p.haul_delay_hours_mean > 0),
                       rng.exponential(max(p.haul_delay_hours_mean, 1e-9), n), 0.0)
    logistics = material_cost * p.holding_daily_rate * (extra_h / 24.0)

    net_profit = revenue - taxes - material_cost - req.fixed_cost - logistics
    time_h = req.production_time_s / 3600.0 + extra_h

    breakdown = {
        "material_cost": material_cost, "revenue": revenue,
        "taxes_fees": taxes, "logistics": logistics,
    }
    metrics = _metrics(req, net_profit, time_h, breakdown)
    return SimResult(label=req.label, metrics=metrics)


def _pcts(a: np.ndarray, qs: list[float]) -> list[float]:
    return [float(x) for x in np.percentile(a, qs)]


def _hist(a: np.ndarray, bins: int = 40) -> tuple[list[int], list[float]]:
    counts, edges = np.histogram(a, bins=bins)
    return [int(c) for c in counts], [float(e) for e in edges]


def _metrics(req: SimRequest, profit: np.ndarray, time_h: np.ndarray, breakdown: dict) -> SimMetrics:
    n = profit.size
    mean = float(profit.mean())
    std = float(profit.std(ddof=0))
    p1, p5, p25, p50, p75, p95, p99 = _pcts(profit, [1, 5, 25, 50, 75, 95, 99])
    cvar5 = float(profit[profit <= p5].mean()) if np.any(profit <= p5) else p5
    worst1 = float(profit[profit <= p1].mean()) if np.any(profit <= p1) else p1
    hc, he = _hist(profit)
    thc, the = _hist(time_h)

    n_jobs = max(1, int(req.params.slots))
    time_mean = float(time_h.mean())

    def stat(a: np.ndarray) -> dict:
        q5, q50, q95 = _pcts(a, [5, 50, 95])
        return {"mean": float(a.mean()), "p5": q5, "p50": q50, "p95": q95}

    return SimMetrics(
        n_iterations=n,
        expected_profit=mean,
        median_profit=p50,
        std=std,
        cv=(std / abs(mean)) if mean else 0.0,
        var5=p5, var1=p1, cvar5=cvar5, worst1=worst1,
        prob_loss=float(np.mean(profit < 0.0)),
        percentiles={"p1": p1, "p5": p5, "p25": p25, "p50": p50, "p75": p75, "p95": p95, "p99": p99},
        best=float(profit.max()), worst=float(profit.min()),
        hist_counts=hc, hist_edges=he,
        breakdown={k: stat(v) for k, v in breakdown.items()},
        time_mean_h=time_mean,
        time_median_h=float(np.median(time_h)),
        time_p95_h=_pcts(time_h, [95])[0],
        time_per_job_h=req.production_time_s / 3600.0 / n_jobs,
        time_hist_counts=thc, time_hist_edges=the,
        sharpe_like=(mean / std) if std else 0.0,
        risk_adjusted=mean - req.params.risk_lambda * std,
        return_per_slot=mean / max(1, int(req.params.slots)),
        return_per_time=(mean / time_mean) if time_mean else 0.0,
    )


# ── strategy ranking (Python fallback for the Haskell risk-engine) ───────────────

# metric → (+1 higher-is-better / −1 lower-is-better, default weight)
_RANK_METRICS = {
    "expected_profit": (1.0, 1.0),
    "sharpe_like": (1.0, 1.0),
    "var5": (1.0, 1.0),
    "return_per_slot": (1.0, 0.5),
    "return_per_time": (1.0, 0.5),
    "prob_loss": (-1.0, 1.0),
}


@dataclass
class RankInput:
    label: str
    expected_profit: float
    sharpe_like: float
    var5: float
    return_per_slot: float
    return_per_time: float
    prob_loss: float

    @classmethod
    def from_metrics(cls, label: str, m: SimMetrics) -> "RankInput":
        return cls(label, m.expected_profit, m.sharpe_like, m.var5,
                   m.return_per_slot, m.return_per_time, m.prob_loss)

    @classmethod
    def from_metrics_dict(cls, label: str, m: dict) -> "RankInput":
        """Build from a stored SimMetrics JSON dict (a persisted run)."""
        return cls(label, float(m.get("expected_profit", 0.0)), float(m.get("sharpe_like", 0.0)),
                   float(m.get("var5", 0.0)), float(m.get("return_per_slot", 0.0)),
                   float(m.get("return_per_time", 0.0)), float(m.get("prob_loss", 0.0)))


@dataclass
class RankedStrategy:
    rank: int
    label: str
    score: float


def rank_strategies(items: list[RankInput], weights: Optional[dict[str, float]] = None) -> list[RankedStrategy]:
    """Composite risk-adjusted ranking. Each metric is z-scored across the
    candidate set (population std; constant metric → 0 contribution), signed so
    higher is better, then weighted-summed. Sorted by score desc; ties broken by
    expected_profit desc, then label asc. Deterministic — the Haskell risk-engine
    reproduces it exactly (rank), bit-close (score)."""
    if not items:
        return []
    w = {**{k: dw for k, (_, dw) in _RANK_METRICS.items()}, **(weights or {})}
    scores = np.zeros(len(items))
    for metric, (sign, _) in _RANK_METRICS.items():
        col = np.array([getattr(it, metric) for it in items], dtype=float)
        sd = col.std(ddof=0)
        if sd > 0:
            scores += w.get(metric, 0.0) * sign * (col - col.mean()) / sd
    order = sorted(range(len(items)),
                   key=lambda i: (-scores[i], -items[i].expected_profit, items[i].label))
    return [RankedStrategy(rank=r + 1, label=items[i].label, score=float(scores[i]))
            for r, i in enumerate(order)]


# ── contract assembly: deterministic plan/calc + history → SimRequest ────────────

@dataclass
class TypeHistory:
    """Raw market history for one type (oldest-first, time-aligned by the caller)."""
    buy: list[float] = field(default_factory=list)
    sell: list[float] = field(default_factory=list)
    volume: list[float] = field(default_factory=list)
    group_id: int = 0
    last_buy: Optional[float] = None
    last_sell: Optional[float] = None


def _leg_marginals(side_hist: list[float], point: Optional[float], default_sigma: float):
    """(mu, sigma, qgrid) for one side. Falls back to a degenerate lognormal at the
    point price when history is missing, so a leg is always sampleable."""
    mu, sigma = market_model.lognormal_params(side_hist)
    grid = market_model.quantile_grid(side_hist)
    if sigma == 0.0 and point and point > 0:          # no usable history → point price
        mu, sigma = math.log(point), default_sigma
        grid = [float(point)] * QGRID_POINTS
    return mu, sigma, grid


def _build_dependency(price_columns: list[list[float]], group_ids: list[int]):
    """Both dependency structures from aligned price columns (var order preserved)."""
    nvars = len(price_columns)
    rets = market_model.align_returns(price_columns)
    corr = market_model.correlation_matrix(rets, n=nvars)
    L = market_model.nearest_psd_cholesky(corr)
    loadings, fsig, idio = market_model.factor_decompose(corr, group_ids)
    return (
        [[float(x) for x in row] for row in L],
        [[float(x) for x in row] for row in loadings],
        [float(x) for x in fsig],
        [float(x) for x in idio],
    )


def request_from_legs(label: str, leg_specs: list[tuple[int, int]], product_type_id: int,
                      product_qty: int, hist: dict[int, TypeHistory], fixed_cost: float,
                      production_time_s: int, params: SimParams, *,
                      broker_fee_pct: float = 0.0, sales_tax_pct: float = 0.0,
                      default_sigma: float = 0.30) -> SimRequest:
    """Assemble a :class:`SimRequest` from buy legs ``[(type_id, qty)]`` + a product,
    using market ``hist`` per type. Pure — the caller (adapter) fetches the history.
    This is the seam both ``request_from_chain`` and ``request_from_calc`` go through."""
    legs: list[LegInput] = []
    price_columns: list[list[float]] = []
    group_ids: list[int] = []
    for tid, qty in leg_specs:
        h = hist.get(tid) or TypeHistory()
        mu, sigma, grid = _leg_marginals(h.buy, h.last_buy, default_sigma)
        legs.append(LegInput(
            type_id=tid, qty=int(qty), mu=mu, sigma=sigma, qgrid=grid,
            vol_mean=float(np.mean(h.volume)) if h.volume else 0.0,
            vol_sigma=market_model.lognormal_params(h.volume)[1] or 0.5,
            spread_mean=market_model.relative_spread(h.buy, h.sell),
            group_id=h.group_id,
        ))
        price_columns.append([float(x) for x in (h.buy or [h.last_buy or 0.0])])
        group_ids.append(h.group_id)

    ph = hist.get(product_type_id) or TypeHistory()
    pmu, psigma, pgrid = _leg_marginals(ph.sell, ph.last_sell, default_sigma)
    product = ProductInput(
        type_id=product_type_id, qty=int(product_qty), mu=pmu, sigma=psigma, qgrid=pgrid,
        vol_mean=float(np.mean(ph.volume)) if ph.volume else 0.0,
        vol_sigma=market_model.lognormal_params(ph.volume)[1] or 0.5,
        spread_mean=market_model.relative_spread(ph.buy, ph.sell),
        group_id=ph.group_id, broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
    )
    price_columns.append([float(x) for x in (ph.sell or [ph.last_sell or 0.0])])
    group_ids.append(ph.group_id)

    L, loadings, fsig, idio = _build_dependency(price_columns, group_ids)
    return SimRequest(
        label=label, legs=legs, product=product, fixed_cost=float(fixed_cost),
        production_time_s=int(production_time_s), params=params,
        cholesky_L=L, loadings=loadings, factor_sigma=fsig, idio_sigma=idio,
    )


def request_from_chain(plan, hist: dict[int, TypeHistory], params: SimParams,
                       production_time_s: int, *, broker_fee_pct: float = 0.0,
                       sales_tax_pct: float = 0.0, label: Optional[str] = None) -> SimRequest:
    """Build a request from a ``services.chain.ChainPlan``: buy legs = the shopping
    list, product = the target, fixed cost = the in-house conversion (install+bpc)."""
    leg_specs = sorted(((s.type_id, s.qty) for s in plan.shopping_list), key=lambda x: x[0])
    conversion = float(sum(float(j.install_cost) + float(j.bpc_cost) for j in plan.jobs))
    return request_from_legs(
        label or f"chain:{plan.target_type_id}", leg_specs, plan.target_type_id,
        plan.target_qty, hist, conversion, production_time_s, params,
        broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
    )


def request_from_calc(calc, product_type_id: int, hist: dict[int, TypeHistory],
                      params: SimParams, *, label: Optional[str] = None) -> SimRequest:
    """Build a request from a ``services.manufacturing.CalcResult``: buy legs = the
    materials, product = the output, fixed cost = install + bpc, broker fee from
    the calc. Sell distribution comes from the product's market history."""
    leg_specs = sorted(((m.type_id, m.adj_qty) for m in calc.materials), key=lambda x: x[0])
    fixed = float(calc.job_cost.net_install_cost) + float(calc.bpc_cost)
    broker = 0.0
    if calc.output.gross_sell:
        broker = round((1.0 - calc.output.net_sell / calc.output.gross_sell) * 100.0, 4)
    return request_from_legs(
        label or f"calc:{product_type_id}", leg_specs, product_type_id,
        calc.output.quantity, hist, fixed, calc.job_time.seconds, params,
        broker_fee_pct=broker, sales_tax_pct=0.0,
    )
