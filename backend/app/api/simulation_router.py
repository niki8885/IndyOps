from __future__ import annotations
import datetime
from dataclasses import asdict
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import profit_sim as sim_engine
from app.adapters import risk_engine
from app.core.database import SimulationRun, UserDB, get_db
from app.core.security import get_current_user
from app.services import profit_sim as core
from app.services import sim_report_pdf
from app.services.profit_sim import RankInput, SimParams

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


# orchestration helpers

def summary(metrics: dict) -> dict:
    return {k: metrics.get(k) for k in _SUMMARY_KEYS}


def _persist(db: Session, sim_req, *, source: str, user_id: int, project_id: Optional[int],
             product_name: str, product_type_id: int) -> SimulationRun:
    result, engine = sim_engine.simulate(sim_req)
    metrics = asdict(result.metrics)
    report = {
        "label": sim_req.label, "source": source, "product_name": product_name,
        "target_type_id": product_type_id, "engine": engine,
        "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "params": asdict(sim_req.params), "metrics": metrics,
    }
    pdf = sim_report_pdf.render_run_pdf(report)
    run = SimulationRun(
        user_id=user_id, project_id=project_id, source=source,
        target_type_id=product_type_id, label=sim_req.label,
        n_iterations=sim_req.params.n_iterations, engine=engine,
        params=asdict(sim_req.params), metrics=metrics, pdf=pdf,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_chain_simulation(db: Session, *, user_id: int, project_id: Optional[int], plan,
                         production_time_s: int, history: dict, params: SimParams,
                         product_name: str, broker_fee_pct: float = 0.0,
                         sales_tax_pct: float = 0.0, label: Optional[str] = None) -> SimulationRun:
    sim_req = core.request_from_chain(plan, history, params, production_time_s,
                                      broker_fee_pct=broker_fee_pct, sales_tax_pct=sales_tax_pct,
                                      label=label or product_name)
    return _persist(db, sim_req, source="chain", user_id=user_id, project_id=project_id,
                    product_name=product_name, product_type_id=plan.target_type_id)


def run_calc_simulation(db: Session, *, user_id: int, project_id: Optional[int], calc,
                        product_type_id: int, history: dict, params: SimParams,
                        product_name: str, label: Optional[str] = None) -> SimulationRun:
    sim_req = core.request_from_calc(calc, product_type_id, history, params, label=label or product_name)
    return _persist(db, sim_req, source="production", user_id=user_id, project_id=project_id,
                    product_name=product_name, product_type_id=product_type_id)


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


@router.get("/runs/{run_id}")
async def get_run(run_id: int, current_user: UserDB = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id, current_user.id)
    return {**run_payload(run), "params": run.params, "metrics": run.metrics}


@router.get("/runs/{run_id}/pdf")
async def get_run_pdf(run_id: int, current_user: UserDB = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id, current_user.id)
    pdf = run.pdf
    if not pdf:  # older run without a stored PDF → regenerate from metrics
        pdf = sim_report_pdf.render_run_pdf({
            "label": run.label, "source": run.source, "target_type_id": run.target_type_id,
            "engine": run.engine,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "params": run.params or {}, "metrics": run.metrics or {},
        })
    return Response(content=bytes(pdf), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="simulation_{run_id}.pdf"'})


@router.get("/reports/project/{project_id}/pdf")
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


@router.post("/rank")
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
