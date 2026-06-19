"""Encyclopedia quiz results: submit + per-section/per-article roll-up."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import encyclopedia_router as er
from app.api.encyclopedia_router import QuizSubmit
from app.core.database import Base

USER = SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _submit(db, **kw):
    return asyncio.run(er.submit_quiz(QuizSubmit(**kw), current_user=USER, db=db))


def test_submit_tracks_best_and_attempts(db):
    assert _submit(db, section="finance", article_key="monte-carlo", score=6, total=10)["best"] == 6
    r2 = _submit(db, section="finance", article_key="monte-carlo", score=9, total=10)
    assert r2["best"] == 9 and r2["attempts"] == 2


def test_scores_roll_up_by_section(db):
    _submit(db, section="finance", article_key="monte-carlo", score=6, total=10)
    _submit(db, section="finance", article_key="monte-carlo", score=9, total=10)
    _submit(db, section="finance", article_key="scenarios", score=7, total=10)
    out = asyncio.run(er.scores(current_user=USER, db=db))
    arts = {a["article_key"]: a for a in out["by_article"]}
    assert arts["monte-carlo"]["best_score"] == 9 and arts["monte-carlo"]["attempts"] == 2
    assert arts["monte-carlo"]["last_score"] == 9
    sec = {s["section"]: s for s in out["by_section"]}
    assert sec["finance"]["articles"] == 2 and sec["finance"]["attempts"] == 3
    assert 0.0 <= sec["finance"]["avg_best_pct"] <= 1.0


def test_score_clamped_to_total(db):
    assert _submit(db, section="finance", article_key="x", score=99, total=10)["score"] == 10
