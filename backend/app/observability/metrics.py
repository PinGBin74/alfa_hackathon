"""Метрики качества (критерий 08). Расчёт по таблицам insights/feedback/agent_traces."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AgentTrace, Feedback, InsightRecord
from app.ml.quality import insight_quality
from app.services.token_budget import spent_today


def quality_snapshot(db: Session) -> dict:
    total_insights = db.query(func.count(InsightRecord.insight_id)).scalar() or 0
    fb = db.query(func.avg(Feedback.rating), func.count(Feedback.id)).one()
    llm = db.query(
        func.coalesce(func.sum(AgentTrace.tokens_in), 0),
        func.coalesce(func.sum(AgentTrace.tokens_out), 0),
        func.avg(AgentTrace.latency_ms),
    ).filter(AgentTrace.kind == "llm_call").one()
    return {
        "insights_total": total_insights,
        "feedback_avg": float(fb[0]) if fb[0] is not None else None,
        "feedback_count": fb[1],
        "llm_tokens_in": int(llm[0]),
        "llm_tokens_out": int(llm[1]),
        "llm_avg_latency_ms": float(llm[2]) if llm[2] is not None else None,
        "llm_spent_today_rub": round(spent_today(db), 2),
        "llm_daily_budget_rub": get_settings().daily_budget_rub,
        # качество AI-компонента по последним инсайтам: проверка, ссылки на источники, позиция банка, цена
        **insight_quality(db),
    }
