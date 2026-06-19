"""
IO-23 Scenario Simulation — pure scenario layer.

Unlike the IO-22 Monte-Carlo simulator (stochastic uncertainty around a single
baseline), a *scenario* is a deterministic "what-if" stress test: a fixed set of
multiplicative/additive shifts applied to the simulation inputs (prices,
volatility, volume, spread, taxes, costs, time, slots). Each scenario is then run
through the **same Monte-Carlo machinery** so every scenario still yields the full
risk-metric set (E[Profit], VaR 5/1 %, CVaR, P(loss), worst case), which is what
lets us *compare* scenarios against the baseline and rank strategies.

This module is **pure** (stdlib + dataclasses + the pure ``profit_sim`` service —
no sqlalchemy / fastapi / requests), per the service-layering rule. It is the
contract the native Fortran ``scenario-sim`` engine mirrors and the oracle the
adapter falls back to:

* ``ScenarioParams`` — the modifier vector (no-op defaults).
* ``SCENARIOS`` — the predefined catalog (>=12, across all 5 categories).
* ``apply`` / ``compose`` — turn a baseline ``SimRequest`` into a scenario request,
  and combine scenarios into a composite stress test.
* ``compare`` — diff a scenario's metrics against the baseline (profit/risk/ROI).
* ``simulate_oracle`` — run baseline + scenarios with the pure ``profit_sim`` MC
  (the Python fallback; the native engine does the same math much faster).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

from app.services import profit_sim as ps
from app.services.profit_sim import SimMetrics, SimRequest

# scenario categories (IO-23 taxonomy)
EXOGENOUS = "exogenous"
LOGISTICS = "logistics"
DEMAND = "demand"
COUNTERFACTUAL = "counterfactual"
ENDOGENOUS = "endogenous"
COMPOSITE = "composite"


# modifier vector

@dataclass
class ScenarioParams:
    """How a scenario perturbs the baseline simulation inputs. Defaults are the
    identity (no-op) transform, so an all-default ``ScenarioParams`` reproduces the
    baseline. Multiplicative knobs are ``*_mult`` (1.0 = unchanged); additive ones
    are ``*_add`` (0.0 = unchanged, in the same unit as the target: percent-points
    for fees, fraction for premiums/rates). ``haul_*`` are absolute overrides
    (``None`` = keep the baseline value)."""
    material_price_mult: float = 1.0   # raw-material acquire prices
    product_price_mult: float = 1.0    # product sell price
    volatility_mult: float = 1.0       # price σ / per-step σ (volatility regime)
    volume_mult: float = 1.0           # market volume (liquidity / fill)
    spread_mult: float = 1.0           # bid/ask spread
    production_cost_mult: float = 1.0  # install + bpc (fixed conversion cost)
    tax_mult: float = 1.0              # scales BOTH sales tax and broker fee
    sales_tax_add: float = 0.0         # +percent-points sales tax
    broker_fee_add: float = 0.0        # +percent-points broker fee
    shortfall_premium_add: float = 0.0  # +fraction material-shortfall premium
    holding_rate_add: float = 0.0      # +fraction/day capital holding cost
    haul_delay_prob: Optional[float] = None        # absolute override [0,1]
    haul_delay_hours_mean: Optional[float] = None  # absolute override (hours)
    time_mult: float = 1.0             # manufacturing time
    slots_mult: float = 1.0            # production slots (throughput)
    horizon_mult: float = 1.0          # selling horizon (time-to-sell)


@dataclass
class Scenario:
    key: str
    name: str
    category: str
    description: str
    params: ScenarioParams = field(default_factory=ScenarioParams)


# predefined catalog — IO-23 requires >=12 across exogenous/logistics/demand/
# counterfactual/endogenous. Endogenous ones are parameter approximations of a
# structural decision (we don't re-solve the chain), labelled as such.

def _sc(key, name, category, description, **kw) -> Scenario:
    return Scenario(key, name, category, description, ScenarioParams(**kw))


_CATALOG: list[Scenario] = [
    # ── Exogenous ─────────────────────────────────────────────────────────────
    _sc("market_shock_up", "Market Shock (up)", EXOGENOUS,
        "Sudden market-wide price surge: materials and products jump, volatility rises.",
        material_price_mult=1.15, product_price_mult=1.20, volatility_mult=1.5),
    _sc("market_shock_down", "Market Shock (down)", EXOGENOUS,
        "Sudden market-wide sell-off: materials and products drop, volatility rises.",
        material_price_mult=0.85, product_price_mult=0.80, volatility_mult=1.5),
    _sc("resource_shortage", "Resource Shortage", EXOGENOUS,
        "Supply constraint on critical materials: buy prices and spread up, volume down.",
        material_price_mult=1.25, volume_mult=0.5, spread_mult=1.8,
        shortfall_premium_add=0.25),
    _sc("industry_disruption", "Industry Disruption", EXOGENOUS,
        "Large-scale production interruption: product prices up, supply/volume down, bottlenecks.",
        product_price_mult=1.18, volume_mult=0.7, time_mult=1.2),
    _sc("tax_increase", "Tax Increase", EXOGENOUS,
        "Higher sales tax / broker / structure fees: thinner margins.",
        tax_mult=1.5, production_cost_mult=1.05),
    _sc("tax_reduction", "Tax Reduction", EXOGENOUS,
        "Lower sales tax / broker fees: fatter margins, more market activity.",
        tax_mult=0.5, volume_mult=1.15),
    _sc("inflation", "Inflation", EXOGENOUS,
        "General cost inflation across materials, logistics and manufacturing.",
        material_price_mult=1.12, product_price_mult=1.08,
        production_cost_mult=1.12, holding_rate_add=0.0005),
    # ── Logistics ─────────────────────────────────────────────────────────────
    _sc("hauling_cost_spike", "Hauling Cost Spike", LOGISTICS,
        "Shipping costs spike; regional arbitrage shrinks.",
        production_cost_mult=1.10, material_price_mult=1.05, holding_rate_add=0.0005),
    _sc("logistics_disruption", "Logistics Disruption", LOGISTICS,
        "Longer hauling times and delivery delays reduce material availability.",
        volume_mult=0.8, haul_delay_prob=0.6, haul_delay_hours_mean=48.0,
        holding_rate_add=0.001),
    _sc("freighter_risk", "Freighter Risk Increase", LOGISTICS,
        "Higher hauling losses and insurance/risk premiums on every shipment.",
        material_price_mult=1.08, shortfall_premium_add=0.15, holding_rate_add=0.0008),
    # ── Market demand ─────────────────────────────────────────────────────────
    _sc("capital_meta_shift", "Capital Ship Meta Shift", DEMAND,
        "Surging capital demand lifts product prices and volume; mineral pressure.",
        product_price_mult=1.25, volume_mult=1.4, material_price_mult=1.10),
    _sc("t2_boom", "T2 Manufacturing Boom", DEMAND,
        "T2 demand boom raises product prices and volume; T2 materials / moon goo up.",
        product_price_mult=1.15, volume_mult=1.3, material_price_mult=1.12),
    _sc("market_recession", "Market Recession", DEMAND,
        "Reduced demand and volumes; orders take much longer to complete.",
        product_price_mult=0.80, volume_mult=0.5, horizon_mult=1.5),
    # ── Counterfactual ────────────────────────────────────────────────────────
    _sc("jita_plus_20", "What if Jita prices +20%?", COUNTERFACTUAL,
        "Counterfactual: product sell prices 20% higher than today.",
        product_price_mult=1.20),
    _sc("taxes_half", "What if taxes were 50% lower?", COUNTERFACTUAL,
        "Counterfactual: all sales/broker taxes halved.",
        tax_mult=0.5),
    _sc("hauling_doubled", "What if hauling costs doubled?", COUNTERFACTUAL,
        "Counterfactual: logistics/handling cost doubled.",
        production_cost_mult=1.20, material_price_mult=1.05, holding_rate_add=0.001),
    _sc("minerals_minus_15", "What if minerals were 15% cheaper?", COUNTERFACTUAL,
        "Counterfactual: mineral/material costs 15% below current (≈ last month's levels).",
        material_price_mult=0.85),
    # ── Endogenous (parameter approximations of a structural decision) ─────────
    _sc("production_expansion", "Production Expansion", ENDOGENOUS,
        "Scale up: more job slots (throughput) but more capital tied up (approx).",
        slots_mult=2.0, production_cost_mult=1.30, holding_rate_add=0.0005),
    _sc("vertical_integration", "Vertical Integration", ENDOGENOUS,
        "Make intermediates in-house: less market exposure / spread, longer build (approx).",
        material_price_mult=0.90, spread_mult=0.7, production_cost_mult=1.05, time_mult=1.15),
    _sc("market_concentration", "Market Concentration", ENDOGENOUS,
        "Focus on fewer products: thinner liquidity, more single-market exposure (approx).",
        volume_mult=0.7, volatility_mult=1.2),
]

SCENARIOS: dict[str, Scenario] = {s.key: s for s in _CATALOG}


def catalog() -> list[Scenario]:
    """The predefined scenarios, catalog order (used by the API)."""
    return list(_CATALOG)


# apply a scenario to a baseline SimRequest

def _ln(mult: float) -> float:
    """log of a price multiplier (for the log-space mu/theta/x0 level shift)."""
    return math.log(mult) if mult and mult > 0 else 0.0


def _shift_var(v, price_mult: float, sp: ScenarioParams):
    """Apply price-level + volatility + volume + spread shifts to one leg/product
    (shared by ``LegInput`` and ``ProductInput`` — same field names)."""
    lm = _ln(price_mult)
    vol = max(0.0, sp.volatility_mult)
    return replace(
        v,
        mu=v.mu + lm,
        sigma=v.sigma * vol,
        qgrid=[g * price_mult for g in v.qgrid],
        vol_mean=v.vol_mean * sp.volume_mult,
        spread_mean=v.spread_mean * sp.spread_mult,
        step_sigma=v.step_sigma * vol,
        theta=v.theta + lm,
        x0=v.x0 + lm,
        garch_omega=v.garch_omega * vol * vol,
    )


def apply(req: SimRequest, sp: ScenarioParams) -> SimRequest:
    """Return a new ``SimRequest`` with the scenario's shifts applied. Pure
    (``dataclasses.replace``); the correlation structure (``cholesky_L``/
    ``loadings``) is intentionally untouched — a price level/scale shift does not
    change cross-asset correlation."""
    legs = [_shift_var(leg, sp.material_price_mult, sp) for leg in req.legs]
    product = _shift_var(req.product, sp.product_price_mult, sp)
    product = replace(
        product,
        broker_fee_pct=req.product.broker_fee_pct * sp.tax_mult + sp.broker_fee_add,
        sales_tax_pct=req.product.sales_tax_pct * sp.tax_mult + sp.sales_tax_add,
    )
    p = req.params
    params = replace(
        p,
        slots=max(1, int(round(p.slots * sp.slots_mult))),
        horizon_days=p.horizon_days * sp.horizon_mult,
        shortfall_premium=max(0.0, p.shortfall_premium + sp.shortfall_premium_add),
        holding_daily_rate=max(0.0, p.holding_daily_rate + sp.holding_rate_add),
        haul_delay_prob=(p.haul_delay_prob if sp.haul_delay_prob is None
                         else float(sp.haul_delay_prob)),
        haul_delay_hours_mean=(p.haul_delay_hours_mean if sp.haul_delay_hours_mean is None
                               else float(sp.haul_delay_hours_mean)),
    )
    return replace(
        req,
        legs=legs,
        product=product,
        params=params,
        fixed_cost=req.fixed_cost * sp.production_cost_mult,
        production_time_s=int(round(req.production_time_s * sp.time_mult)),
    )


def compose(parts: list[ScenarioParams]) -> ScenarioParams:
    """Combine several scenarios into one composite stress test: multipliers
    multiply, additive terms add, absolute overrides take the worst (max)."""
    out = ScenarioParams()
    for sp in parts:
        out.material_price_mult *= sp.material_price_mult
        out.product_price_mult *= sp.product_price_mult
        out.volatility_mult *= sp.volatility_mult
        out.volume_mult *= sp.volume_mult
        out.spread_mult *= sp.spread_mult
        out.production_cost_mult *= sp.production_cost_mult
        out.tax_mult *= sp.tax_mult
        out.time_mult *= sp.time_mult
        out.slots_mult *= sp.slots_mult
        out.horizon_mult *= sp.horizon_mult
        out.sales_tax_add += sp.sales_tax_add
        out.broker_fee_add += sp.broker_fee_add
        out.shortfall_premium_add += sp.shortfall_premium_add
        out.holding_rate_add += sp.holding_rate_add
        if sp.haul_delay_prob is not None:
            out.haul_delay_prob = max(out.haul_delay_prob or 0.0, sp.haul_delay_prob)
        if sp.haul_delay_hours_mean is not None:
            out.haul_delay_hours_mean = max(out.haul_delay_hours_mean or 0.0,
                                            sp.haul_delay_hours_mean)
    return out


def composite_scenario(keys: list[str]) -> Optional[Scenario]:
    """Build a composite ``Scenario`` from predefined keys (skips unknown keys)."""
    found = [SCENARIOS[k] for k in keys if k in SCENARIOS]
    if not found:
        return None
    return Scenario(
        key="+".join(s.key for s in found),
        name=" + ".join(s.name for s in found),
        category=COMPOSITE,
        description="Composite stress test: " + ", ".join(s.name for s in found),
        params=compose([s.params for s in found]),
    )


# comparison vs baseline

@dataclass
class ScenarioComparison:
    abs_profit_change: float
    pct_profit_change: float
    std_change: float
    var5_change: float
    prob_loss_change: float
    roi_baseline: float
    roi_scenario: float
    roi_change: float
    viable: bool  # E[Profit] > 0 and P(loss) < 0.5 under the scenario


def _metric(m, key: str, default: float = 0.0) -> float:
    """Read a metric whether ``m`` is a ``SimMetrics`` or a plain dict."""
    if isinstance(m, dict):
        return float(m.get(key, default) or default)
    return float(getattr(m, key, default) or default)


def _capital(m, fixed_cost: float) -> float:
    """Invested capital ≈ E[material cost] + fixed (install+bpc) — the ROI base."""
    if isinstance(m, dict):
        bd = m.get("breakdown") or {}
    else:
        bd = getattr(m, "breakdown", {}) or {}
    mat = float((bd.get("material_cost") or {}).get("mean", 0.0) or 0.0)
    return mat + max(0.0, fixed_cost)


def compare(base, scen, *, base_fixed_cost: float, scen_fixed_cost: float) -> ScenarioComparison:
    """Diff a scenario's metrics against the baseline. ``base``/``scen`` are
    ``SimMetrics`` or their asdict()."""
    bp = _metric(base, "expected_profit")
    spv = _metric(scen, "expected_profit")
    abs_change = spv - bp
    base_cap = _capital(base, base_fixed_cost)
    scen_cap = _capital(scen, scen_fixed_cost)
    roi_b = bp / base_cap if base_cap else 0.0
    roi_s = spv / scen_cap if scen_cap else 0.0
    return ScenarioComparison(
        abs_profit_change=abs_change,
        pct_profit_change=(abs_change / abs(bp)) if bp else 0.0,
        std_change=_metric(scen, "std") - _metric(base, "std"),
        var5_change=_metric(scen, "var5") - _metric(base, "var5"),
        prob_loss_change=_metric(scen, "prob_loss") - _metric(base, "prob_loss"),
        roi_baseline=roi_b,
        roi_scenario=roi_s,
        roi_change=roi_s - roi_b,
        viable=(spv > 0.0 and _metric(scen, "prob_loss", 1.0) < 0.5),
    )


# pure Monte-Carlo oracle (the fallback when the native engine is unavailable)

def simulate_oracle(baseline_req: SimRequest,
                    paramsets: list[ScenarioParams]) -> tuple[SimMetrics, list[SimMetrics]]:
    """Run the baseline and every scenario through the pure ``profit_sim`` MC.

    Each scenario is simulated with the *same* RNG seed (``profit_sim.simulate``
    re-seeds from ``params.seed`` on every call), i.e. common random numbers, so
    the scenario-vs-baseline differences reflect the parameter shifts, not Monte-
    Carlo noise — exactly what the native engine does too."""
    base = ps.simulate(baseline_req).metrics
    scen = [ps.simulate(apply(baseline_req, sp)).metrics for sp in paramsets]
    return base, scen
