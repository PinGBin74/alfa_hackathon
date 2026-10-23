"""Уточняющий вопрос к готовому инсайту (критерий 10): другой разрез, детали, первоисточник.

Короткий агентный цикл: инструменты поиска по вопросу -> ответ Qwen3.6 со ссылками -> проверка ссылок и чисел
(числа ответа должны быть в переданных источниках; если нет - одна точечная правка с замечанием).
Роут: POST /api/chat (app/api/routes/chat.py).
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent import context
from app.agent.llm_client import LLMClient, LLMError, json_instruction
from app.agent.schemas import ChatReply
from app.agent.tools.registry import call_tool
from app.db.models import InsightRecord
from app.ml.grounding import ungrounded
from app.observability.tracing import Tracer
from app.schemas.client import ClientProfile, GraphFeatures
from app.schemas.insight import SourceRef
from app.schemas.news import ChatAnswer, ChatTurn

PROMPT = (Path(__file__).parent / "prompts" / "chat.md").read_text(encoding="utf-8")
HISTORY_TURNS = 6
HISTORY_CHARS = 1500


def _history_block(history: list[ChatTurn]) -> str:
    """Последние реплики разговора: только для понимания вопроса, источником фактов не являются."""
    turns = history[-HISTORY_TURNS:]
    if not turns:
        return ""
    names = {"user": "Пользователь", "assistant": "Ответ"}
    return "ИСТОРИЯ РАЗГОВОРА (не источник фактов):\n" + "\n".join(
        f"{names[t.role]}: {' '.join(t.content.split())[:HISTORY_CHARS]}" for t in turns)


def _sources(insight: dict, client_id: str, bank: list[dict], news: list[dict], ids: list[str]) -> list[SourceRef]:
    """Описание источников ответа для интерфейса: название, ссылка, дата."""
    known = {s["source_id"]: SourceRef.model_validate(s) for s in insight.get("sources", [])}
    known.setdefault(f"client:{client_id}", SourceRef(source_id=f"client:{client_id}", type="client_data",
                                                       title="Данные о компании из выгрузки банка"))
    for b in bank:
        known.setdefault(context.bank_source_id(b), SourceRef(
            source_id=context.bank_source_id(b), type="bank_analytics", title=f"{b.get('title')}, стр. {b.get('page')}",
            published_at=b.get("published_at")))
    for n in news:
        known.setdefault(f"news:{n['news_id']}", SourceRef(source_id=f"news:{n['news_id']}", type="news", title=n.get("title"),
                                                           url=n.get("url"), published_at=n.get("published_at")))
    return [known[i] for i in ids if i in known]


def answer(db: Session, record: InsightRecord, question: str, user_role: str | None = None,
           history: list[ChatTurn] | None = None) -> ChatAnswer:
    tracer = Tracer(db)
    llm = LLMClient(db, tracer=tracer)
    insight = record.payload
    tracer.log("plan", "chat", input={"insight_id": record.insight_id, "question": question[:500],
                                      "history_turns": len(history or [])},
               output={"plan": ["get_client_profile", "get_counterparty_graph", "search_bank_analytics", "search_news"]})

    profile = ClientProfile.model_validate(call_tool(db, tracer, "get_client_profile", client_id=record.client_id))
    profile.graph = GraphFeatures.model_validate(call_tool(db, tracer, "get_counterparty_graph", client_id=record.client_id))
    bank = call_tool(db, tracer, "search_bank_analytics", query=question, k=4)
    news = call_tool(db, tracer, "search_news", query=question, k=3)

    known = {s["source_id"] for s in insight.get("sources", [])} | {f"client:{record.client_id}"}
    known |= {context.bank_source_id(b) for b in bank} | {f"news:{n['news_id']}" for n in news}
    blocks = [
        "ИНСАЙТ (JSON):\n" + json.dumps({k: insight.get(k) for k in (
            "what_happened", "why_it_matters", "consequences", "suggested_actions", "bank_position", "ai_inference",
            "sources")}, ensure_ascii=False),
        context.profile_brief(profile, user_role),
        context.bank_block(bank),
        context.related_block(news),
        "ДОПУСТИМЫЕ source_id: " + ", ".join(sorted(known)),
    ]
    sources_text = "\n\n".join(b for b in blocks if b)  # история - не источник: числа сверяются без неё
    prompt = "\n\n".join(b for b in (sources_text, _history_block(history or []), f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}") if b)
    messages = [{"role": "system", "content": f"{PROMPT}\n\n{json_instruction(ChatReply)}"},
                {"role": "user", "content": prompt}]
    reply, _ = llm.structured(messages, ChatReply, complexity="general", name="chat")
    missing = ungrounded(reply.answer, sources_text, skip_small_ints=True)
    if missing:  # цифры не из источников: одна правка, остаётся вариант с меньшим числом таких цифр
        tracer.log("verify", "chat_grounding", output={"passed": False, "iterations": 1,
                                                       "issues": [f"wrong_number answer: чисел {missing} нет в источниках"]})
        try:
            fixed, _ = llm.structured(messages + [
                {"role": "assistant", "content": reply.model_dump_json()},
                {"role": "user", "content": f"В ответе есть числа, которых нет в источниках: {', '.join(missing)}. "
                                            "Убери их или замени цифрами из источников, остальное сохрани."}],
                ChatReply, complexity="general", name="chat#2")
        except LLMError:  # правка не удалась - отдаём первый ответ, непроверенные числа - в трассе
            fixed = None
        still = ungrounded(fixed.answer, sources_text, skip_small_ints=True) if fixed else missing
        if fixed and len(still) < len(missing):
            reply, missing = fixed, still
    source_ids = [s for s in reply.source_ids if s in known]
    tracer.log("final", "chat_answer", output={"source_ids": source_ids, "ungrounded_numbers": missing,
                                               "dropped_source_ids": [s for s in reply.source_ids if s not in known]})
    return ChatAnswer(answer=reply.answer, source_ids=source_ids,
                      sources=_sources(insight, record.client_id, bank, news, source_ids), trace_id=tracer.trace_id)
