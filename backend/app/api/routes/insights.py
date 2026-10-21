from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent import orchestrator
from app.db.models import AgentTrace, InsightRecord, User
from app.db.session import get_db
from app.schemas.insight import Insight
from app.security.rbac import ensure_client_access, get_current_user
from app.services.token_budget import BudgetExceeded

router = APIRouter()


@router.post("/{client_id}/{news_id}", response_model=Insight)
def get_or_create_insight(
    client_id: str, news_id: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Кэш: если инсайт для (клиент, новость, роль) уже есть, отдаём его (экономия токенов)."""
    ensure_client_access(user, client_id)
    cached = (
        db.query(InsightRecord)
        .filter_by(client_id=client_id, news_id=news_id, user_role=user.role)
        .order_by(InsightRecord.created_at.desc())
        .first()
    )
    if cached:
        return Insight.model_validate(cached.payload)
    try:
        return orchestrator.run(db, client_id, news_id, user_role=user.role)
    except BudgetExceeded:
        raise HTTPException(429, "Daily LLM budget exhausted") from None


@router.get("/{insight_id}/trace")
def get_trace(insight_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Трасса агента: какие инструменты и источники использованы (критерий 12)."""
    rec = db.get(InsightRecord, insight_id)
    if rec is None:
        raise HTTPException(404, "Insight not found")
    ensure_client_access(user, rec.client_id)
    steps = db.query(AgentTrace).filter_by(trace_id=rec.trace_id).order_by(AgentTrace.step).all()
    return [
        {"step": s.step, "kind": s.kind, "name": s.name, "input": s.input, "output": s.output,
         "model": s.model, "latency_ms": s.latency_ms}
        for s in steps
    ]
