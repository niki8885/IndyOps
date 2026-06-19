from __future__ import annotations
from app.core.timeutil import utcnow
from dataclasses import asdict
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import profit_sim as sim_engine
from app.adapters import risk_engine
from app.adapters import scenario_sim as scenario_engine
from app.api.responses import ERR_404
from app.core.database import ScenarioAnalysis, SimulationRun, UserDB, get_db
from app.core.security import get_current_user
from app.services import profit_sim as core
from app.services import scenario_report_pdf, scenarios, sim_report_pdf
from app.services.profit_sim import RankInput, SimParams
from app.services.scenarios import Scenario, ScenarioParams

router = APIRouter()

_SUMMARY_KEYS = (
    "expected_profit", "median_profit", "std", "cv", "var5", "var1", "cvar5", "worst1",
    "prob_loss", "sharpe_like", "risk_adjusted", "return_per_slot", "return_per_time",
    "best", "worst",
)


class SimParamsIn(BaseModel):
    n_iterations: int = 25_000  # AC: 10k–50k; clamped to [1000, 200000]
    seed: int = 42
    horizon_days: float = 1.0
    corr_mode: int = 0
    dist_mode: int = 0
    participation_cap: float = 0.10
    shortfall_premium: float = 0.25
    slippage: float = 0.50
    haul_delay_prob: float = 0.0
    haul_delay_hours_mean: float = 0.0
    holding_daily_rate: float = 0.0
    slots: int = 1
    risk_lambda: float = 1.0
    broker_fee_pct: float = 3.6
    sales_tax_pct: float = 2.0
    copula: int = 0
    t_df: float = 0.0
    path_steps: int = 1
    garch: int = 0

    def to_params(self) -> SimParams:
        return SimParams(
            n_iterations=max(1000, min(200_000, int(self.n_iterations))),
            seed=int(self.seed), horizon_days=float(self.horizon_days),
            corr_mode=1 if self.corr_mode == 1 else 0,
            dist_mode=1 if self.dist_mode == 1 else 0,
            participation_cap=float(self.participation_cap),
            shortfall_premium=float(self.shortfall_premium),
            slippage=float(self.slippage),
            haul_delay_prob=float(self.haul_delay_prob),
            haul_delay_hours_mean=float(self.haul_delay_hours_mean),
            holding_daily_rate=float(self.holding_daily_rate),
            slots=max(1, int(self.slots)), risk_lambda=float(self.risk_lambda),
            copula=1 if self.copula == 1 else 0,
            t_df=float(self.t_df),
            path_steps=max(1, min(168, int(self.path_steps))),
            garch=1 if self.garch == 1 else 0,
        )


class RankRequest(BaseModel):
    run_ids: list[int] = []
    weights: Optional[dict[str, float]] = None


# IO-23 scenario simulation request models

class CustomScenarioIn(BaseModel):
    """A user-built scenario (the Custom Scenario Builder). Every field is a
    ``ScenarioParams`` modifier with its no-op default, so the client only sends the
    knobs it changed."""
    key: Optional[str] = None
    name: str = "Custom scenario"
    material_price_mult: float = 1.0
    product_price_mult: float = 1.0
    volatility_mult: float = 1.0
    volume_mult: float = 1.0
    spread_mult: float = 1.0
    production_cost_mult: float = 1.0
    tax_mult: float = 1.0
    sales_tax_add: float = 0.0
    broker_fee_add: float = 0.0
    shortfall_premium_add: float = 0.0
    holding_rate_add: float = 0.0
    haul_delay_prob: Optional[float] = None
    haul_delay_hours_mean: Optional[float] = None
    time_mult: float = 1.0
    slots_mult: float = 1.0
    horizon_mult: float = 1.0

    def to_scenario(self, idx: int) -> Scenario:
        sp = ScenarioParams(
            material_price_mult=self.material_price_mult, product_price_mult=self.product_price_mult,
            volatility_mult=self.volatility_mult, volume_mult=self.volume_mult,
            spread_mult=self.spread_mult, production_cost_mult=self.production_cost_mult,
            tax_mult=self.tax_mult, sales_tax_add=self.sales_tax_add,
            broker_fee_add=self.broker_fee_add, shortfall_premium_add=self.shortfall_premium_add,
            holding_rate_add=self.holding_rate_add, haul_delay_prob=self.haul_delay_prob,
            haul_delay_hours_mean=self.haul_delay_hours_mean, time_mult=self.time_mult,
            slots_mult=self.slots_mult, horizon_mult=self.horizon_mult,
        )
        return Scenario(key=self.key or f"custom_{idx}", name=self.name,
                        category="custom", description="Custom scenario", params=sp)


class ScenarioRequestIn(BaseModel):
    """Which scenarios to evaluate. Empty → the full predefined catalog (the
    'Multiple Scenario Stress Test' default)."""
    keys: list[str] = []                       # predefined catalog keys
    composites: list[list[str]] = []           # each inner list → one composite stress test
    custom: list[CustomScenarioIn] = []        # custom-builder scenarios
    params: Optional[SimParamsIn] = None       # MC knobs (iterations, distribution, …)


def resolve_specs(req: ScenarioRequestIn) -> list[Scenario]:
    """Turn the request into concrete ``Scenario`` objects. Unknown keys are
    skipped; an empty request runs the whole catalog."""
    specs: list[Scenario] = []
    for key in req.keys:
        sc = scenarios.SCENARIOS.get(key)
        if sc is not None:
            specs.append(sc)
    for combo in req.composites:
        comp = scenarios.composite_scenario(combo)
        if comp is not None:
            specs.append(comp)
    for i, c in enumerate(req.custom):
        specs.append(c.to_scenario(i))
    return specs or scenarios.catalog()


# orchestration helpers

def summary(metrics: dict) -> dict:
    return {k: metrics.get(k) for k in _SUMMARY_KEYS}


def _share_params(sim_params: SimParams, share_code: Optional[str], share_url: Optional[str]) -> dict:
    """SimParams snapshot + the (optional) self-contained share code/link, for storage
    and for the PDF's QR. Kept in ``params`` so a regenerated PDF still has them."""
    p = asdict(sim_params)
    if share_code:
        p["share_code"] = share_code
    if share_url:
        p["share_url"] = share_url
    return p


def _persist(db: Session, sim_req, *, source: str, user_id: int, project_id: Optional[int],
             product_name: str, product_type_id: int, share_code: Optional[str] = None,
             share_url: Optional[str] = None) -> SimulationRun:
    result, engine = sim_engine.simulate(sim_req)
    metrics = asdict(result.metrics)
    params_dict = _share_params(sim_req.params, share_code, share_url)
    report = {
        "label": sim_req.label, "source": source, "product_name": product_name,
        "target_type_id": product_type_id, "engine": engine,
        "created_at": utcnow().isoformat(timespec="seconds"),
        "params": params_dict, "metrics": metrics,
        "share_code": share_code, "share_url": share_url,
    }
    pdf = sim_report_pdf.render_run_pdf(report)
    run = SimulationRun(
        user_id=user_id, project_id=project_id, source=source,
        target_type_id=product_type_id, label=sim_req.label,
        n_iterations=sim_req.params.n_iterations, engine=engine,
        params=params_dict, metrics=metrics, pdf=pdf,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_chain_simulation(db: Session, *, user_id: int, project_id: Optional[int], plan,
                         production_time_s: int, history: dict, params: SimParams,
                         product_name: str, broker_fee_pct: float = 0.0,
                         sales_tax_pct: float = 0.0, label: Optional[str] = None,
                         share_code: Optional[str] = None, share_url: Optional[str] = None) -> SimulationRun:
    sim_req = core.request_from_chain(plan, history, params, production_time_s,
                                      broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
                                      label=label or product_name)
    return _persist(db, sim_req, source="chain", user_id=user_id, project_id=project_id,
                    product_name=product_name, product_type_id=plan.target_type_id,
                    share_code=share_code, share_url=share_url)


def run_calc_simulation(db: Session, *, user_id: int, project_id: Optional[int], calc,
                        product_type_id: int, history: dict, params: SimParams,
                        product_name: str, label: Optional[str] = None,
                        share_code: Optional[str] = None, share_url: Optional[str] = None) -> SimulationRun:
    sim_req = core.request_from_calc(calc, product_type_id, history, params, label=label or product_name)
    return _persist(db, sim_req, source="production", user_id=user_id, project_id=project_id,
                    product_name=product_name, product_type_id=product_type_id,
                    share_code=share_code, share_url=share_url)


def run_payload(run: SimulationRun) -> dict:
    """Compact JSON for a run (no PDF blob) — used by the inline flag + GET /runs."""
    return {
        "run_id": run.id, "label": run.label, "source": run.source,
        "target_type_id": run.target_type_id, "project_id": run.project_id,
        "n_iterations": run.n_iterations, "engine": run.engine,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "summary": summary(run.metrics or {}),
    }


# endpoints

def _run_or_404(db: Session, run_id: int, user_id: int) -> SimulationRun:
    run = db.query(SimulationRun).filter(
        SimulationRun.id == run_id, SimulationRun.user_id == user_id).first()
    if not run:
        raise HTTPException(404, "Simulation run not found")
    return run


@router.get("/runs")
async def list_runs(project_id: Optional[int] = None, source: Optional[str] = None,
                    current_user: UserDB = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    q = db.query(SimulationRun).filter(SimulationRun.user_id == current_user.id)
    if project_id is not None:
        q = q.filter(SimulationRun.project_id == project_id)
    if source:
        q = q.filter(SimulationRun.source == source)
    runs = q.order_by(SimulationRun.created_at.desc()).limit(200).all()
    return {"runs": [run_payload(r) for r in runs]}


@router.get("/runs/{run_id}", responses={**ERR_404})
async def get_run(run_id: int, current_user: UserDB = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id, current_user.id)
    return {**run_payload(run), "params": run.params, "metrics": run.metrics}


@router.get("/runs/{run_id}/pdf", responses={**ERR_404})
async def get_run_pdf(run_id: int, current_user: UserDB = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id, current_user.id)
    pdf = run.pdf
    if not pdf:  # older run without a stored PDF → regenerate from metrics
        params = run.params or {}
        pdf = sim_report_pdf.render_run_pdf({
            "label": run.label, "source": run.source, "target_type_id": run.target_type_id,
            "engine": run.engine,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "params": params, "metrics": run.metrics or {},
            "share_code": params.get("share_code"), "share_url": params.get("share_url"),
        })
    return Response(content=bytes(pdf), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="simulation_{run_id}.pdf"'})


@router.get("/reports/project/{project_id}/pdf", responses={**ERR_404})
async def project_rollup_pdf(project_id: int, current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    runs = (db.query(SimulationRun)
            .filter(SimulationRun.user_id == current_user.id,
                    SimulationRun.project_id == project_id)
            .order_by(SimulationRun.created_at.asc()).all())
    if not runs:
        raise HTTPException(404, "No simulation runs for this project")
    reports = [{
        "label": r.label, "source": r.source, "target_type_id": r.target_type_id,
        "engine": r.engine, "created_at": r.created_at.isoformat() if r.created_at else "",
        "params": r.params or {}, "metrics": r.metrics or {},
    } for r in runs]
    items = [RankInput.from_metrics_dict(r.label, r.metrics or {}) for r in runs]
    ranked, _ = risk_engine.rank(items)
    pdf = sim_report_pdf.render_rollup_pdf(f"Project {project_id}", reports,
                                           [asdict(rk) for rk in ranked])
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="project_{project_id}_simulations.pdf"'})


@router.post("/rank", responses={**ERR_404})
async def rank_runs(body: RankRequest, current_user: UserDB = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    runs = (db.query(SimulationRun)
            .filter(SimulationRun.user_id == current_user.id,
                    SimulationRun.id.in_(body.run_ids or [-1])).all())
    if not runs:
        raise HTTPException(404, "No matching simulation runs")
    items = [RankInput.from_metrics_dict(r.label, r.metrics or {}) for r in runs]
    ranked, engine = risk_engine.rank(items, body.weights)
    return {"engine": engine, "ranked": [asdict(r) for r in ranked]}


# IO-23 scenario simulation — orchestration

_SCN_SUMMARY_KEYS = ("expected_profit", "std", "var5", "var1", "prob_loss", "sharpe_like")


def run_scenario_analysis(db: Session, *, baseline_req, specs: list[Scenario], source: str,
                          user_id: int, project_id: Optional[int], product_name: str,
                          product_type_id: int, share_code: Optional[str] = None,
                          share_url: Optional[str] = None) -> ScenarioAnalysis:
    """Run the baseline + every scenario through the native scenario engine (Python
    oracle fallback), diff each against baseline, rank, render the PDF, persist."""
    base_metrics, scen_metrics, engine = scenario_engine.simulate(
        baseline_req, [s.params for s in specs])
    base_dict = asdict(base_metrics)
    base_fixed = float(baseline_req.fixed_cost)

    outcomes: list[dict] = []
    rank_items = [RankInput.from_metrics_dict("● Baseline", base_dict)]
    for s, m in zip(specs, scen_metrics):
        m_dict = asdict(m)
        cmp = scenarios.compare(base_dict, m_dict, base_fixed_cost=base_fixed,
                                scen_fixed_cost=base_fixed * s.params.production_cost_mult)
        outcomes.append({
            "key": s.key, "name": s.name, "category": s.category,
            "description": s.description, "params": asdict(s.params),
            "metrics": m_dict, "comparison": asdict(cmp),
        })
        rank_items.append(RankInput.from_metrics_dict(s.name, m_dict))

    ranked, _ = risk_engine.rank(rank_items)
    ranking = [asdict(r) for r in ranked]
    params_dict = _share_params(baseline_req.params, share_code, share_url)
    report = {
        "label": product_name, "source": source, "product_name": product_name,
        "target_type_id": product_type_id, "engine": engine,
        "created_at": utcnow().isoformat(timespec="seconds"),
        "params": params_dict, "baseline": base_dict,
        "outcomes": outcomes, "ranking": ranking,
        "share_code": share_code, "share_url": share_url,
    }
    pdf = scenario_report_pdf.render_scenario_pdf(report)
    row = ScenarioAnalysis(
        user_id=user_id, project_id=project_id, source=source,
        target_type_id=product_type_id, label=product_name, product_name=product_name,
        engine=engine, params=params_dict, baseline=base_dict,
        outcomes=outcomes, ranking=ranking, pdf=pdf)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def run_calc_scenario_analysis(db: Session, *, user_id: int, project_id: Optional[int], calc,
                               product_type_id: int, history: dict, params: SimParams,
                               product_name: str, specs: list[Scenario],
                               share_code: Optional[str] = None,
                               share_url: Optional[str] = None) -> ScenarioAnalysis:
    sim_req = core.request_from_calc(calc, product_type_id, history, params, label=product_name)
    return run_scenario_analysis(db, baseline_req=sim_req, specs=specs, source="production",
                                 user_id=user_id, project_id=project_id, product_name=product_name,
                                 product_type_id=product_type_id, share_code=share_code, share_url=share_url)


def run_chain_scenario_analysis(db: Session, *, user_id: int, project_id: Optional[int], plan,
                                production_time_s: int, history: dict, params: SimParams,
                                product_name: str, specs: list[Scenario], broker_fee_pct: float = 0.0,
                                sales_tax_pct: float = 0.0, share_code: Optional[str] = None,
                                share_url: Optional[str] = None) -> ScenarioAnalysis:
    sim_req = core.request_from_chain(plan, history, params, production_time_s,
                                      broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
                                      label=product_name)
    return run_scenario_analysis(db, baseline_req=sim_req, specs=specs, source="chain",
                                 user_id=user_id, project_id=project_id, product_name=product_name,
                                 product_type_id=plan.target_type_id, share_code=share_code, share_url=share_url)


def scenario_summary(metrics: dict) -> dict:
    return {k: metrics.get(k) for k in _SCN_SUMMARY_KEYS}


def scenario_payload(row: ScenarioAnalysis) -> dict:
    """Compact entry for a scenario analysis (no PDF blob) — used by the inline flag
    + GET /scenario-runs. Includes the full outcomes so the panel renders without a
    second round-trip (the analysis is on-demand, not auto-run)."""
    return {
        "analysis_id": row.id, "label": row.label, "source": row.source,
        "target_type_id": row.target_type_id, "project_id": row.project_id,
        "engine": row.engine, "n_scenarios": len(row.outcomes or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "baseline_summary": scenario_summary(row.baseline or {}),
        "baseline": row.baseline, "outcomes": row.outcomes, "ranking": row.ranking,
    }


def _scenario_list_entry(row: ScenarioAnalysis) -> dict:
    return {
        "analysis_id": row.id, "label": row.label, "source": row.source,
        "target_type_id": row.target_type_id, "project_id": row.project_id,
        "engine": row.engine, "n_scenarios": len(row.outcomes or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "baseline_summary": scenario_summary(row.baseline or {}),
    }


# IO-23 scenario simulation — endpoints

@router.get("/scenarios")
async def list_scenarios(current_user: UserDB = Depends(get_current_user)):
    """The predefined scenario catalog, grouped by category (for the picker)."""
    by_cat: dict[str, list] = {}
    for s in scenarios.catalog():
        by_cat.setdefault(s.category, []).append(asdict(s))
    return {"categories": [{"category": c, "scenarios": v} for c, v in by_cat.items()],
            "scenarios": [asdict(s) for s in scenarios.catalog()]}


def _scenario_or_404(db: Session, analysis_id: int, user_id: int) -> ScenarioAnalysis:
    row = db.query(ScenarioAnalysis).filter(
        ScenarioAnalysis.id == analysis_id, ScenarioAnalysis.user_id == user_id).first()
    if not row:
        raise HTTPException(404, "Scenario analysis not found")
    return row


@router.get("/scenario-runs")
async def list_scenario_runs(project_id: Optional[int] = None, source: Optional[str] = None,
                             target_type_id: Optional[int] = None,
                             current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    q = db.query(ScenarioAnalysis).filter(ScenarioAnalysis.user_id == current_user.id)
    if project_id is not None:
        q = q.filter(ScenarioAnalysis.project_id == project_id)
    if source:
        q = q.filter(ScenarioAnalysis.source == source)
    if target_type_id is not None:
        q = q.filter(ScenarioAnalysis.target_type_id == target_type_id)
    rows = q.order_by(ScenarioAnalysis.created_at.desc()).limit(200).all()
    return {"runs": [_scenario_list_entry(r) for r in rows]}


@router.get("/scenario-runs/{analysis_id}", responses={**ERR_404})
async def get_scenario_run(analysis_id: int, current_user: UserDB = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    row = _scenario_or_404(db, analysis_id, current_user.id)
    return {**scenario_payload(row), "params": row.params}


@router.get("/scenario-runs/{analysis_id}/pdf", responses={**ERR_404})
async def get_scenario_run_pdf(analysis_id: int, current_user: UserDB = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    row = _scenario_or_404(db, analysis_id, current_user.id)
    pdf = row.pdf
    if not pdf:  # older row without a stored PDF → regenerate from stored data
        params = row.params or {}
        pdf = scenario_report_pdf.render_scenario_pdf({
            "label": row.label, "source": row.source, "product_name": row.product_name,
            "target_type_id": row.target_type_id, "engine": row.engine,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "params": params, "baseline": row.baseline or {},
            "outcomes": row.outcomes or [], "ranking": row.ranking or [],
            "share_code": params.get("share_code"), "share_url": params.get("share_url"),
        })
    return Response(content=bytes(pdf), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="scenario_{analysis_id}.pdf"'})


@router.get("/reports/product/{type_id}/pdf", responses={**ERR_404})
async def product_rollup_pdf(type_id: int, analysis_id: Optional[int] = None,
                             run_id: Optional[int] = None, latest: bool = False,
                             current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Combined 'whole product' PDF: the Monte-Carlo run(s) + scenario analysis(es) for
    this product (``target_type_id``). Scoped, NOT a full history dump — the panel passes
    the current ``analysis_id`` (+ its ``run_id``) so you get a report for *this* build.
    ``latest`` returns only the most-recent of each; with no scoping it falls back to all."""
    runs_q = db.query(SimulationRun).filter(
        SimulationRun.user_id == current_user.id, SimulationRun.target_type_id == type_id)
    analyses_q = db.query(ScenarioAnalysis).filter(
        ScenarioAnalysis.user_id == current_user.id, ScenarioAnalysis.target_type_id == type_id)
    if run_id is not None:
        runs_q = runs_q.filter(SimulationRun.id == run_id)
    if analysis_id is not None:
        analyses_q = analyses_q.filter(ScenarioAnalysis.id == analysis_id)
    # If the caller scopes to a specific analysis but no run, don't pull the whole MC
    # history — the analysis already carries its own baseline.
    if analysis_id is not None and run_id is None:
        runs_q = runs_q.filter(SimulationRun.id == -1)

    if latest and analysis_id is None and run_id is None:
        runs = list(reversed(runs_q.order_by(SimulationRun.created_at.desc()).limit(1).all()))
        analyses = list(reversed(analyses_q.order_by(ScenarioAnalysis.created_at.desc()).limit(1).all()))
    else:
        runs = runs_q.order_by(SimulationRun.created_at.asc()).all()
        analyses = analyses_q.order_by(ScenarioAnalysis.created_at.asc()).all()
    if not runs and not analyses:
        raise HTTPException(404, "No simulations or scenario analyses for this product")
    product_name = next((a.product_name for a in analyses if a.product_name), None) \
        or next((r.label for r in runs), str(type_id))
    sim_reports = [{
        "label": r.label, "source": r.source, "product_name": r.label,
        "target_type_id": r.target_type_id, "engine": r.engine,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "params": r.params or {}, "metrics": r.metrics or {},
        "share_code": (r.params or {}).get("share_code"),
        "share_url": (r.params or {}).get("share_url"),
    } for r in runs]
    scn_reports = [{
        "label": a.label, "source": a.source, "product_name": a.product_name,
        "target_type_id": a.target_type_id, "engine": a.engine,
        "created_at": a.created_at.isoformat() if a.created_at else "",
        "params": a.params or {}, "baseline": a.baseline or {},
        "outcomes": a.outcomes or [], "ranking": a.ranking or [],
        "share_code": (a.params or {}).get("share_code"),
        "share_url": (a.params or {}).get("share_url"),
    } for a in analyses]
    # header QR uses the scoped build's code (analysis preferred, else the MC run)
    hp = next((a.params for a in analyses if (a.params or {}).get("share_code")), None) \
        or next((r.params for r in runs if (r.params or {}).get("share_code")), {}) or {}
    pdf = scenario_report_pdf.render_product_pdf(
        product_name, sim_reports, scn_reports,
        share_code=hp.get("share_code"), share_url=hp.get("share_url"))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="product_{type_id}_report.pdf"'})
