"""
Encyclopedia article quizzes. The articles + questions live in the frontend; this only
persists attempt scores per learning **section** (finance, …) per article, so the account
can show progress by section. (What to do with the scores beyond display is TBD.)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import QuizResult, UserDB, get_db
from app.core.security import get_current_user

router = APIRouter()


class QuizSubmit(BaseModel):
    section: str
    article_key: str
    score: int = Field(ge=0)
    total: int = Field(gt=0)


@router.post("/quiz")
async def submit_quiz(body: QuizSubmit, current_user: UserDB = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Record one quiz attempt; return the new best + attempt count for this article."""
    total = int(body.total)
    score = max(0, min(int(body.score), total))
    row = QuizResult(user_id=current_user.id, section=body.section[:40],
                     article_key=body.article_key[:60], score=score, total=total)
    db.add(row)
    db.commit()
    q = db.query(QuizResult).filter(QuizResult.user_id == current_user.id,
                                    QuizResult.article_key == body.article_key)
    best = db.query(func.max(QuizResult.score)).filter(
        QuizResult.user_id == current_user.id,
        QuizResult.article_key == body.article_key).scalar() or 0
    return {"ok": True, "score": score, "total": total, "best": int(best),
            "attempts": int(q.count())}


@router.get("/scores")
async def scores(current_user: UserDB = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """The user's quiz progress: best/last per article + a per-section roll-up."""
    rows = (db.query(QuizResult)
            .filter(QuizResult.user_id == current_user.id)
            .order_by(QuizResult.created_at.desc()).all())
    by_article: dict[str, dict] = {}
    for r in rows:
        a = by_article.setdefault(r.article_key, {
            "section": r.section, "article_key": r.article_key, "best_score": 0,
            "total": r.total, "attempts": 0, "last_score": None, "last_at": None})
        a["attempts"] += 1
        a["best_score"] = max(a["best_score"], r.score)
        a["total"] = r.total
        if a["last_at"] is None:   # rows are newest-first
            a["last_score"] = r.score
            a["last_at"] = r.created_at.isoformat() if r.created_at else None

    by_section: dict[str, dict] = {}
    for a in by_article.values():
        s = by_section.setdefault(a["section"], {"section": a["section"], "attempts": 0,
                                                 "articles": 0, "_pct": 0.0})
        s["attempts"] += a["attempts"]
        s["articles"] += 1
        s["_pct"] += (a["best_score"] / a["total"]) if a["total"] else 0.0
    sections = [{"section": s["section"], "attempts": s["attempts"], "articles": s["articles"],
                 "avg_best_pct": round(s["_pct"] / s["articles"], 4) if s["articles"] else 0.0}
                for s in by_section.values()]
    return {"by_article": list(by_article.values()), "by_section": sections}
