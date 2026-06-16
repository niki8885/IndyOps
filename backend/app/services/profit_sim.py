from __future__ import annotations
import math
from dataclasses import dataclass, field, replace
from typing import Optional
import numpy as np
from app.services import _special, market_model
from app.services.market_model import QGRID_POINTS

# normal CDF (Gaussian copula)

_erf = np.frompyfunc(math.erf, 1, 1)


def norm_cdf(z: np.ndarray) -> np.ndarray:
    """Standard-normal CDF Φ, elementwise. Exact ``math.erf`` (matches gfortran's
    intrinsic ``erf`` used by the native engine)."""
    return 0.5 * (1.0 + _erf(np.asarray(z, dtype=float) / math.sqrt(2.0)).astype(float))


# contract: request

@dataclass
class LegInput:
    """One bought material (a chain shopping line / a recipe material)."""
    type_id: int
    qty: int
    mu: float  # lognormal log-mean of acquire price
    sigma: float  # lognormal log-std
    qgrid: list[float]  # 101-pt empirical quantile grid of acquire price
    vol_mean: float = 0.0
    vol_sigma: float = 0.5
    spread_mean: float = 0.0
    spread_sigma: float = 0.5
    group_id: int = 0
    # AR(1)/OU + GARCH process params (path mode); 0 ⇒ unused in static mode
    ar_phi: float = 0.0
    step_sigma: float = 0.0
    theta: float = 0.0
    x0: float = 0.0
    garch_omega: float = 0.0


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
    ar_phi: float = 0.0
    step_sigma: float = 0.0
    theta: float = 0.0
    x0: float = 0.0
    garch_omega: float = 0.0


@dataclass
class SimParams:
    n_iterations: int = 25_000
    seed: int = 42
    horizon_days: float = 1.0
    corr_mode: int = 0  # 0 = Cholesky matrix, 1 = factor model
    dist_mode: int = 0  # 0 = empirical (copula), 1 = lognormal
    participation_cap: float = 0.10  # max fraction of period volume we can execute
    shortfall_premium: float = 0.25  # extra cost to source an unfilled material
    slippage: float = 0.50  # how much of the spread we cross
    haul_delay_prob: float = 0.0
    haul_delay_hours_mean: float = 0.0
    holding_daily_rate: float = 0.0  # capital holding cost per day of delay
    slots: int = 1
    risk_lambda: float = 1.0  # risk-aversion in risk_adjusted = E − λσ
    # tail dependence (copula) + price-path dynamics (IO-22 hardening)
    copula: int = 0  # 0 = Gaussian, 1 = Student-t (tail dependence)
    t_df: float = 8.0  # Student-t degrees of freedom (copula heaviness)
    path_steps: int = 1  # 1 = static one-shot; >1 = AR(1)/OU price path
    garch: int = 0  # 0 = constant vol, 1 = GARCH(1,1) clustering
    garch_alpha: float = 0.08
    garch_beta: float = 0.90


@dataclass
class SimRequest:
    label: str
    legs: list[LegInput]
    product: ProductInput
    fixed_cost: float  # install + bpc — deterministic conversion cost
    production_time_s: int
    params: SimParams = field(default_factory=SimParams)

    cholesky_L: Optional[list[list[float]]] = None
    loadings: Optional[list[list[float]]] = None
    factor_sigma: Optional[list[float]] = None
    idio_sigma: Optional[list[float]] = None


# contract: result

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
    # MC sampling error via batch means (IO-22 hardening) — defaults keep old
    # stored runs loadable.
    standard_error: dict = field(default_factory=dict)  # {expected_profit, var5, var1, cvar5}
    ci95: dict = field(default_factory=dict)  # {metric: [lo, hi]} (95%)
    mc_rel_error: float = 0.0  # SE(E)/|E| — relative MC error
    converged: bool = True  # CI half-width(E)/|E| < 1%
    n_batches: int = 1


@dataclass
class SimResult:
    label: str
    metrics: SimMetrics
    engine: str = "python"


# simulation core

def _correlated_normals(req: SimRequest, rng: np.random.Generator, lead: tuple, nvars: int) -> np.ndarray:
    """Correlated standard normals, shape ``(*lead, nvars)``, marginally N(0,1).
    Cholesky (``corr_mode 0``) or factor model (``1``). ``lead`` is ``(n,)`` for the
    static draw, ``(n, H)`` for a path."""
    p = req.params
    if p.corr_mode == 1 and req.loadings is not None:
        loadings = np.asarray(req.loadings, dtype=float)  # [nvars × K]
        k = loadings.shape[1]
        fsig = np.asarray(req.factor_sigma, dtype=float) if req.factor_sigma else np.ones(k)
        idio = np.asarray(req.idio_sigma, dtype=float) if req.idio_sigma else np.zeros(nvars)
        factors = rng.standard_normal((*lead, k)) * fsig
        eta = rng.standard_normal((*lead, nvars))
        return factors @ loadings.T + eta * idio
    L = np.asarray(req.cholesky_L, dtype=float) if req.cholesky_L is not None else np.eye(nvars)
    return rng.standard_normal((*lead, nvars)) @ L.T


def _t_scale(rng: np.random.Generator, lead: tuple, df: float) -> np.ndarray:
    """Shared Student-t scaling ``√(ν/W)``, ``W~χ²_ν`` — one per draw, broadcast over
    variables ``(*lead, 1)``. The common factor is what creates tail dependence."""
    w = rng.chisquare(df, size=(*lead, 1))
    return np.sqrt(df / np.maximum(w, 1e-12))


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


def _static_prices(req: SimRequest, rng: np.random.Generator, n: int, nvars: int,
                   mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """One-shot terminal prices ``[n × nvars]`` via the (Gaussian or Student-t)
    copula and the empirical/lognormal marginals."""
    p = req.params
    z = _correlated_normals(req, rng, (n,), nvars)
    grids = np.array([l.qgrid for l in req.legs] + [req.product.qgrid])
    if p.copula == 1:  # Student-t copula
        df = max(2.5, float(p.t_df))
        t = z * _t_scale(rng, (n,), df)
        u = _special.student_t_cdf(t, df)
        if p.dist_mode == 1:
            return np.exp(mu + sigma * _special.norm_ppf(u))
        return _interp_grids(grids, u)
    if p.dist_mode == 1:  # Gaussian copula
        return np.exp(mu + sigma * z)
    return _interp_grids(grids, norm_cdf(z))


def _path_prices(req: SimRequest, rng: np.random.Generator, n: int, m: int, nvars: int) -> np.ndarray:
    """AR(1)/OU log-price paths (optional GARCH(1,1) vol) driven by correlated
    innovations. Materials are priced at step 1 (bought now), the product at the
    terminal step H (sold after the holding horizon). Returns ``[n × nvars]``."""
    p = req.params
    h = int(p.path_steps)
    legs = req.legs
    ar_phi = np.array([l.ar_phi for l in legs] + [req.product.ar_phi])
    step_sig = np.array([l.step_sigma for l in legs] + [req.product.step_sigma])
    theta = np.array([l.theta for l in legs] + [req.product.theta])
    x0 = np.array([l.x0 for l in legs] + [req.product.x0])
    omega = np.array([l.garch_omega for l in legs] + [req.product.garch_omega])

    innov = _correlated_normals(req, rng, (n, h), nvars)
    if p.copula == 1:  # fat-tailed shocks
        df = max(2.5, float(p.t_df))
        innov = innov * _t_scale(rng, (n, h), df)
        innov = innov / math.sqrt(df / (df - 2.0))  # standardise to unit var

    x = np.repeat(x0[None, :], n, axis=0)
    sig2 = np.repeat((step_sig ** 2)[None, :], n, axis=0)
    prev_eps = np.zeros((n, nvars))
    prev_sig = np.broadcast_to(step_sig, (n, nvars)).copy()
    x_step1 = x.copy()
    for tau in range(h):
        eps_t = innov[:, tau, :]
        if p.garch == 1:
            if tau > 0:
                sig2 = omega[None, :] + p.garch_alpha * (prev_sig * prev_eps) ** 2 + p.garch_beta * sig2
            sig = np.sqrt(np.maximum(sig2, 1e-300))
        else:
            sig = step_sig[None, :] + np.zeros((n, nvars))
        x = x + ar_phi[None, :] * (theta[None, :] - x) + sig * eps_t
        prev_eps, prev_sig = eps_t, sig
        if tau == 0:
            x_step1 = x.copy()

    price = np.exp(x_step1)  # legs: bought at step 1
    price[:, m] = np.exp(x[:, m])  # product: sold at terminal step H
    return price


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

    # 1. correlated price shocks → 2. marginal/terminal prices
    if p.path_steps > 1:
        price = _path_prices(req, rng, n, m, nvars)  # AR(1)/OU (+GARCH) path
    else:
        price = _static_prices(req, rng, n, nvars, mu, sigma)  # one-shot copula draw

    # 3. spread / execution price
    spread = spr_mean * np.exp(spr_sig * rng.standard_normal((n, nvars)))
    buy_price = price[:, :m] * (1.0 + p.slippage * spread[:, :m])
    sell_price = price[:, m] * (1.0 - p.slippage * spread[:, m])

    # 4. liquidity / fill (market-execution risk) — **materials only**. A zero
    #    ``vol_mean`` means we have *no* volume history for that leg (degenerate /
    #    point-price fallback), not an empty market — so impose no constraint (fill=1).
    #    An under-fill does not lose the material, it adds the shortfall premium (you
    #    pay up to source it faster).
    volume = vol_mean[:m] * np.exp(vol_sig[:m] * rng.standard_normal((n, m)))
    exec_cap = p.participation_cap * volume * p.horizon_days
    known = vol_mean[:m] > 0.0  # do we actually have liquidity data for this leg?
    with np.errstate(divide="ignore", invalid="ignore"):
        fill_mat = np.where((qty > 0) & known,
                            np.minimum(1.0, exec_cap / qty), 1.0)

    # 5. P&L per scenario
    base_mat = buy_price * qty
    material_cost = (base_mat * (1.0 + (1.0 - fill_mat) * p.shortfall_premium)).sum(axis=1)
    # The product sells in FULL. Thin product liquidity means the batch takes longer to
    # sell — that is price risk over the holding horizon (already in the price model), it
    # does NOT forfeit units. The old ``* fill_prod`` kept only the fraction sellable in a
    # single ``horizon_days`` and threw the rest away, so a low-volume capital (Anshar
    # ~3.5/day) lost ~65% of its revenue and a clearly-profitable build read as a near-
    # certain loss (E[profit] went negative, P(loss) ~76%).
    revenue = req.product.qty * sell_price
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


def _metric_on(sub: np.ndarray, name: str) -> float:
    """One ranking/risk metric on a (batch) sub-sample — used by batch-means CIs."""
    if name == "expected_profit":
        return float(sub.mean())
    if name == "var5":
        return float(np.percentile(sub, 5))
    if name == "var1":
        return float(np.percentile(sub, 1))
    q5 = np.percentile(sub, 5)  # cvar5
    tail = sub[sub <= q5]
    return float(tail.mean()) if tail.size else float(q5)


def _batch_ci(profit: np.ndarray, point: dict) -> tuple[dict, dict, int]:
    """Batch-means MC standard error + 95% CI for {E, VaR5, VaR1, CVaR5}."""
    n = profit.size
    b = min(40, max(2, n // 500))
    batches = np.array_split(profit, b)
    se, ci = {}, {}
    for name, centre in point.items():
        vals = np.array([_metric_on(bt, name) for bt in batches if bt.size])
        s = float(vals.std(ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0
        se[name] = s
        ci[name] = [centre - 1.96 * s, centre + 1.96 * s]
    return se, ci, b


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

    se, ci, n_batches = _batch_ci(profit, {"expected_profit": mean, "var5": p5, "var1": p1, "cvar5": cvar5})
    mc_rel_error = se["expected_profit"] / abs(mean) if mean else 0.0
    converged = (1.96 * se["expected_profit"]) < 0.01 * abs(mean) if mean else False

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
        standard_error=se, ci95=ci, mc_rel_error=mc_rel_error,
        converged=converged, n_batches=n_batches,
    )


# strategy ranking

# metric -> (+1 higher-is-better / −1 lower-is-better, default weight)
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
    """Composite risk-adjusted ranking."""
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


# contract assembly

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
    """(mu, sigma, qgrid) for one side."""
    mu, sigma = market_model.lognormal_params(side_hist)
    grid = market_model.quantile_grid(side_hist)
    if sigma == 0.0 and point and point > 0:  # no usable history → point price
        mu, sigma = math.log(point), default_sigma
        grid = [float(point)] * QGRID_POINTS
    return mu, sigma, grid


def _fit_process(series: list[float], mu_fb: float, sigma_fb: float, params: SimParams):
    """AR(1)/OU + GARCH(1,1)"""
    phi, step_sigma, theta, x0 = market_model.fit_ar1(series)
    if step_sigma <= 0.0:
        step_sigma = sigma_fb if sigma_fb > 0 else 0.30
    if not series:
        theta, x0 = mu_fb, mu_fb
    omega = market_model.garch_omega(step_sigma, params.garch_alpha, params.garch_beta)
    return phi, step_sigma, theta, x0, omega


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
    legs: list[LegInput] = []
    price_columns: list[list[float]] = []
    group_ids: list[int] = []
    for tid, qty in leg_specs:
        h = hist.get(tid) or TypeHistory()
        mu, sigma, grid = _leg_marginals(h.buy, h.last_buy, default_sigma)
        series = h.buy if h.buy else ([h.last_buy] if h.last_buy else [])
        phi, step_sigma, theta, x0, omega = _fit_process(series, mu, sigma, params)
        legs.append(LegInput(
            type_id=tid, qty=int(qty), mu=mu, sigma=sigma, qgrid=grid,
            vol_mean=float(np.mean(h.volume)) if h.volume else 0.0,
            vol_sigma=market_model.lognormal_params(h.volume)[1] or 0.5,
            spread_mean=market_model.relative_spread(h.buy, h.sell),
            group_id=h.group_id,
            ar_phi=phi, step_sigma=step_sigma, theta=theta, x0=x0, garch_omega=omega,
        ))
        price_columns.append([float(x) for x in (h.buy or [h.last_buy or 0.0])])
        group_ids.append(h.group_id)

    ph = hist.get(product_type_id) or TypeHistory()
    pmu, psigma, pgrid = _leg_marginals(ph.sell, ph.last_sell, default_sigma)
    pseries = ph.sell if ph.sell else ([ph.last_sell] if ph.last_sell else [])
    pphi, pstep, ptheta, px0, pomega = _fit_process(pseries, pmu, psigma, params)
    product = ProductInput(
        type_id=product_type_id, qty=int(product_qty), mu=pmu, sigma=psigma, qgrid=pgrid,
        vol_mean=float(np.mean(ph.volume)) if ph.volume else 0.0,
        vol_sigma=market_model.lognormal_params(ph.volume)[1] or 0.5,
        spread_mean=market_model.relative_spread(ph.buy, ph.sell),
        group_id=ph.group_id, broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
        ar_phi=pphi, step_sigma=pstep, theta=ptheta, x0=px0, garch_omega=pomega,
    )
    price_columns.append([float(x) for x in (ph.sell or [ph.last_sell or 0.0])])
    group_ids.append(ph.group_id)

    # Auto-estimate the Student-t copula df.
    if params.copula == 1 and params.t_df <= 0.0:
        df = market_model.estimate_t_df(market_model.align_returns(price_columns))
        params = replace(params, t_df=df)

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
    """Build a request from a ``services.manufacturing.CalcResult``."""
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
