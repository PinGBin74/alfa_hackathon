"""Метрики качества AI-компонента по сохранённым инсайтам и трассам (критерий 08).

Считаются по таблицам insights / agent_traces / feedback, без LLM. Подключение (делает backend):
в observability.metrics.quality_snapshot добавить `**insight_quality(db)`.
"""
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import AgentTrace, Feedback, InsightRecord


def _share(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def insight_quality(db: Session, last: int = 500) -> dict:
    rows = db.query(InsightRecord).order_by(InsightRecord.created_at.desc()).limit(last).all()
    n = len(rows)
    passed = first = with_bank = statements = grounded = why = why_feat = removed = 0
    by_role: dict[str, int] = defaultdict(int)
    for r in rows:
        p = r.payload or {}
        v = p.get("verification") or {}
        passed += bool(v.get("passed"))
        first += bool(v.get("passed")) and v.get("iterations") == 1
        removed += sum(str(i).startswith("removed:") for i in v.get("issues") or [])
        with_bank += bool(p.get("bank_position"))
        cons = p.get("consequences") or {}
        items = (cons.get("risks") or []) + (cons.get("opportunities") or []) + (p.get("ai_inference") or [])
        statements += len(items)
        grounded += sum(bool(s.get("basis")) for s in items)
        why += len(p.get("why_it_matters") or [])
        why_feat += sum(bool(w.get("client_features")) for w in p.get("why_it_matters") or [])
        by_role[r.user_role or "-"] += 1

    trace_ids = [r.trace_id for r in rows if r.trace_id]
    cost = latency = 0.0
    if trace_ids:
        for out, ms in db.query(AgentTrace.output, AgentTrace.latency_ms).filter(
                AgentTrace.trace_id.in_(trace_ids), AgentTrace.kind == "llm_call"):
            cost += float((out or {}).get("cost_rub") or 0)
            latency += ms or 0
    ids = [r.insight_id for r in rows]
    neg = db.query(func.count(Feedback.id)).filter(Feedback.insight_id.in_(ids), Feedback.rating < 0).scalar() if ids else 0
    return {
        "insights_evaluated": n,
        "verified_rate": _share(passed, n),
        "verified_first_iteration_rate": _share(first, n),
        "bank_view_rate": _share(with_bank, n),
        "statements_with_sources_rate": _share(grounded, statements),
        "why_with_client_features_rate": _share(why_feat, why),
        "sanitizer_removals_per_insight": round(removed / n, 3) if n else None,
        "avg_llm_cost_rub": round(cost / n, 3) if n else None,
        "avg_llm_latency_ms": round(latency / n) if n else None,
        "negative_feedback_rate": _share(neg, n),
        "insights_by_role": dict(by_role),
    }
