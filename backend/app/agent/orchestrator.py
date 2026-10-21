"""Агентный цикл: план -> инструменты -> черновик -> самопроверка -> (повтор).

Собственная реализация, без готовых агентных фреймворков (требование кейса).
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agent import planner, verifier
from app.agent.llm_client import LLMClient
from app.agent.state import AgentState
from app.agent.tools.registry import call_tool
from app.db.models import InsightRecord
from app.observability.tracing import Tracer
from app.schemas.insight import Insight
from app.security import injection_guard

MAX_ITERATIONS = 2


def _gather(db: Session, tracer: Tracer, state: AgentState) -> None:
    for step in state.plan:
        tool = step["tool"]
        if tool == "get_client_profile":
            state.profile = call_tool(db, tracer, tool, client_id=state.client_id)
        elif tool == "get_counterparty_graph":
            state.graph = call_tool(db, tracer, tool, client_id=state.client_id)
        elif tool == "get_news_item":
            state.news = call_tool(db, tracer, tool, news_id=state.news_id)
            hits = injection_guard.scan((state.news or {}).get("body") or "")
            if hits:
                tracer.log("verify", "injection_scan", output={"patterns": hits})
        elif tool == "search_bank_analytics" and state.news:
            state.bank_chunks = call_tool(db, tracer, tool, query=state.news["title"])
        elif tool == "search_news" and state.news:
            state.related_news = call_tool(db, tracer, tool, query=state.news["title"])


def _draft(llm: LLMClient, tracer: Tracer, state: AgentState) -> dict:
    """TODO (ML): собрать промпт из prompts/interpret.md, передать профиль, граф, новость
    (через injection_guard.wrap_untrusted) и фрагменты аналитики банка; получить JSON по
    contracts/insight.schema.json. Модель: complexity='reasoning'.

    Заглушка возвращает валидный, но пустой по смыслу черновик, чтобы сквозной сценарий работал."""
    news = state.news or {}
    return {
        "what_happened": {
            "summary": news.get("summary") or news.get("title", ""),
            "confirmed_facts": [{"text": f, "source_id": f"news:{news.get('news_id')}"} for f in news.get("key_facts", [])],
            "assumptions": [],
        },
        "why_it_matters": [{"text": "TODO: связь события с признаками компании", "client_features": []}],
        "consequences": {"risks": [], "opportunities": [], "factors_to_watch": []},
        "suggested_actions": [],
        "bank_position": [],
        "ai_inference": [{"text": "TODO: вывод модели", "basis": [f"news:{news.get('news_id')}"]}],
    }


def run(db: Session, client_id: str, news_id: str, user_role: str | None = None) -> Insight:
    tracer = Tracer(db)
    llm = LLMClient(db)
    state = AgentState(client_id=client_id, news_id=news_id, user_role=user_role)

    planner.make_plan(llm, tracer, state)
    _gather(db, tracer, state)

    while True:
        state.iterations += 1
        state.draft = _draft(llm, tracer, state)
        result = verifier.verify(state)
        tracer.log("verify", "verifier", output=result)
        if result["passed"] or state.iterations >= MAX_ITERATIONS:
            break
        # Адаптация: при замечаниях повторить поиск/уточнить данные.
        # TODO: на основе result["issues"] дополнить state (доп. search_*, смена запроса) и пересобрать черновик.

    sources = [
        {"source_id": f"news:{state.news['news_id']}", "type": "news", "title": state.news["title"], "url": state.news["url"]}
    ] if state.news else []
    sources.append({"source_id": f"client:{client_id}", "type": "client_data"})
    sources += [
        {"source_id": f"bank:{c['doc_id']}:{c.get('page')}", "type": "bank_analytics", "title": c.get("title")}
        for c in state.bank_chunks
    ]

    insight = Insight(
        insight_id=uuid.uuid4().hex,
        client_id=client_id,
        user_role=user_role,
        news_id=news_id,
        sources=sources,
        verification=state.verification,
        trace_id=tracer.trace_id,
        generated_at=datetime.now(UTC),
        **state.draft,
    )
    db.add(InsightRecord(
        insight_id=insight.insight_id, client_id=client_id, user_role=user_role, news_id=news_id,
        payload=insight.model_dump(mode="json"), trace_id=tracer.trace_id,
    ))
    db.commit()
    tracer.log("final", "insight", output={"insight_id": insight.insight_id})
    return insight
