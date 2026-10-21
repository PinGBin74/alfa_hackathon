"""Планирование: какие данные нужны для интерпретации конкретного события."""
from app.agent.llm_client import LLMClient
from app.agent.state import AgentState
from app.observability.tracing import Tracer

PROMPT_PATH = "app/agent/prompts/planner.md"

DEFAULT_PLAN = [
    {"tool": "get_client_profile", "why": "контекст компании"},
    {"tool": "get_counterparty_graph", "why": "зависимость от контрагентов"},
    {"tool": "get_news_item", "why": "детали события"},
    {"tool": "search_bank_analytics", "why": "позиция банка"},
    {"tool": "search_news", "why": "связанные события, перекрёстная проверка"},
]


def make_plan(llm: LLMClient, tracer: Tracer, state: AgentState) -> list[dict]:
    """TODO (ML): запросить у LLM план под тип события и профиль клиента.
    Пока возвращаем детерминированный план, чтобы каркас работал без LLM."""
    state.plan = list(DEFAULT_PLAN)
    tracer.log("plan", "make_plan", output={"plan": state.plan})
    return state.plan
