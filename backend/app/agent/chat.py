"""Уточняющий вопрос к готовому инсайту (критерий 10): другой разрез, детали, первоисточник.

Короткий агентный цикл: инструменты поиска по вопросу -> ответ Qwen3.6 со ссылками -> проверка ссылок.
Подключение к роуту (делает backend): в app/api/routes/chat.py
`return chat.answer(db, rec, body.question, user.role)`.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent import context
from app.agent.llm_client import LLMClient, json_instruction
from app.agent.schemas import ChatReply
from app.agent.tools.registry import call_tool
from app.db.models import InsightRecord
from app.observability.tracing import Tracer
from app.schemas.client import ClientProfile, GraphFeatures
from app.schemas.news import ChatAnswer

PROMPT = (Path(__file__).parent / "prompts" / "chat.md").read_text(encoding="utf-8")


def answer(db: Session, record: InsightRecord, question: str, user_role: str | None = None) -> ChatAnswer:
    tracer = Tracer(db)
    llm = LLMClient(db, tracer=tracer)
    insight = record.payload
    tracer.log("plan", "chat", input={"insight_id": record.insight_id, "question": question[:500]},
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
        f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}",
    ]
    reply, _ = llm.structured(
        [{"role": "system", "content": f"{PROMPT}\n\n{json_instruction(ChatReply)}"},
         {"role": "user", "content": "\n\n".join(b for b in blocks if b)}],
        ChatReply, complexity="general", name="chat",
    )
    source_ids = [s for s in reply.source_ids if s in known]
    tracer.log("final", "chat_answer", output={"source_ids": source_ids,
                                               "dropped_source_ids": [s for s in reply.source_ids if s not in known]})
    return ChatAnswer(answer=reply.answer, source_ids=source_ids, trace_id=tracer.trace_id)
