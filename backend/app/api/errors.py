"""Ошибки LLM -> HTTP: одна точка для всех маршрутов, которые вызывают модели."""
from fastapi import HTTPException

from app.agent.llm_client import LLMError, LLMNotConfigured


def llm_unavailable(error: LLMError) -> HTTPException:
    """503 - модели не настроены (нет ключа или адреса в .env), повтор не поможет;
    502 - модели временно недоступны, можно повторить."""
    if isinstance(error, LLMNotConfigured):
        return HTTPException(503, f"LLM is not configured: {error}")
    return HTTPException(502, "LLM is unavailable, try again later")
