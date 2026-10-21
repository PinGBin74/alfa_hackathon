"""Обёртка над LLM (OpenAI-совместимый API) + роутинг моделей по сложности + учёт бюджета.

Используются только модели из Приложения 3 задания.
"""
import json
import time
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import token_budget

Complexity = Literal["light", "reasoning", "general", "research", "text"]


def pick_model(complexity: Complexity) -> str:
    s = get_settings()
    return {
        "light": s.llm_model_light,          # классификация, извлечение
        "reasoning": s.llm_model_reasoning,  # интерпретация, самопроверка
        "general": s.llm_model_general,
        "research": s.llm_model_research,
        "text": s.llm_model_text,
    }[complexity]


class LLMClient:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def chat(
        self,
        messages: list[dict],
        complexity: Complexity = "light",
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> dict:
        """Возвращает {"content", "model", "tokens_in", "tokens_out", "latency_ms"}."""
        token_budget.check_budget(self.db)
        model = pick_model(complexity)
        payload: dict = {"model": model, "messages": messages, "temperature": temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        start = time.perf_counter()
        resp = httpx.post(
            f"{self.settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        latency = int((time.perf_counter() - start) * 1000)

        usage = data.get("usage", {})
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        token_budget.record(self.db, model, tin, tout)

        return {
            "content": data["choices"][0]["message"]["content"],
            "model": model,
            "tokens_in": tin,
            "tokens_out": tout,
            "latency_ms": latency,
        }

    def chat_json(self, messages: list[dict], complexity: Complexity = "light") -> tuple[dict, dict]:
        """Возвращает (распарсенный JSON, мета-информация вызова)."""
        meta = self.chat(messages, complexity=complexity, json_mode=True)
        return json.loads(meta["content"]), meta
