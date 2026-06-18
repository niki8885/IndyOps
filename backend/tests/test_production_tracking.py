"""PAK production-job status history (append-only timeline)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.manufacturing_router import _log_job_status, _status_val
from app.core.database import Base, ProductionJob, ProductionStatusEvent
from app.core.schemas import ProductionStatus


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        ProductionJob.__table__, ProductionStatusEvent.__table__,
    ])
    return sessionmaker(bind=engine)()


def test_status_val_handles_enum_and_string():
    assert _status_val(ProductionStatus.IN_PROGRESS) == "In Progress"
    assert _status_val("Completed") == "Completed"
    assert _status_val(None) is None


def test_log_job_status_records_transition():
    s = _session()
    j = ProductionJob(user_id=1, product_type_id=1, product_name="Nitrogen Fuel Block",
                      status=ProductionStatus.PREPARING)
    s.add(j); s.flush()

    _log_job_status(s, j, ProductionStatus.IN_PROGRESS, note="materials issued")
    s.commit()

    ev = s.query(ProductionStatusEvent).filter(ProductionStatusEvent.job_id == j.id).all()
    assert len(ev) == 1
    assert ev[0].from_status == "Preparing"     # captured before the caller flips job.status
    assert ev[0].status == "In Progress"
    assert ev[0].note == "materials issued"
    s.close()
