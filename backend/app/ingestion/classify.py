"""Классификация новости и извлечение ключевых фактов (LLM: лёгкая модель)."""
from app.agent.llm_client import LLMClient


def classify(llm: LLMClient, title: str, body: str) -> dict:
    """TODO (ML): вернуть {"industries": [...], "regions": [...], "event_type": "...",
    "summary": "...", "key_facts": [...]} через llm.chat_json(..., complexity="light").
    Весь текст новости оборачивать через security.injection_guard.wrap_untrusted."""
    return {"industries": [], "regions": [], "event_type": None, "summary": None, "key_facts": []}
