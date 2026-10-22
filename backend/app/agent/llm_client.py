"""Обёртка над LLM (OpenAI-совместимый прокси организаторов) + роутинг моделей + учёт бюджета.

Используются только модели из Приложения 3 задания. Особенности прокси (проверено 21.10.2026):
- Qwen3.6 и Kimi по умолчанию «рассуждают» и могут потратить весь max_tokens на reasoning, вернув
  пустой content; отключается полем {"reasoning": {"enabled": false}}.
- Kimi с включённым reasoning игнорирует json_schema, поэтому любой JSON валидируется pydantic-схемой
  и при ошибке запрос повторяется с текстом ошибки.
- Фактическая цена вызова в рублях приходит в заголовке x-litellm-response-cost.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.observability.tracing import Tracer
from app.services import token_budget

Complexity = Literal["light", "reasoning", "general", "research", "text"]
T = TypeVar("T", bound=BaseModel)

# reasoning: None - поведение модели по умолчанию, True/False - явно включить/выключить.
PROFILES: dict[str, dict] = {
    "light": {"max_tokens": 2000, "reasoning": None},       # Gemma: классификация, извлечение
    # GLM: интерпретация. Со своим reasoning тратит 8-16 тыс. токенов и 80-140 с на черновик (замер 21.10),
    # без него - ~2 тыс. токенов и ~20 с при сопоставимом качестве; глубину даёт цикл план -> проверка.
    "reasoning": {"max_tokens": 6000, "reasoning": False},
    "general": {"max_tokens": 2500, "reasoning": False},    # Qwen3.6: чат, планирование
    "research": {"max_tokens": 5000, "reasoning": None},    # DeepSeek: самопроверка, короткий reasoning
    "text": {"max_tokens": 2500, "reasoning": False},       # Kimi: дорогой и медленный reasoning
}
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
BUDGET_MARKER = "budget has been exceeded"


class LLMError(RuntimeError):
    pass


def pick_model(complexity: Complexity) -> str:
    s = get_settings()
    return {
        "light": s.llm_model_light,
        "reasoning": s.llm_model_reasoning,
        "general": s.llm_model_general,
        "research": s.llm_model_research,
        "text": s.llm_model_text,
    }[complexity]


def parse_json(content: str | None) -> dict:
    """JSON-объект из ответа модели: снимает ```json-обёртку, при мусоре вокруг берёт внешние скобки."""
    if not content or not content.strip():
        raise ValueError("empty content")
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON root is not an object")
    return obj


def json_instruction(schema: type[BaseModel]) -> str:
    """Схема ответа для промпта: модели, игнорирующие response_format, видят её в тексте."""
    return ("Ответь одним JSON-объектом строго по схеме, без пояснений и markdown:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False))


class LLMClient:
    def __init__(self, db: Session, tracer: Tracer | None = None, http: httpx.Client | None = None,
                 cache_dir: str | Path | None = None, timeout: float = 180.0):
        self.db = db
        self.tracer = tracer
        self.settings = get_settings()
        self.http = http or httpx.Client(timeout=timeout)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._sleep = time.sleep

    def _post(self, payload: dict) -> httpx.Response:
        url = f"{self.settings.llm_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.http.post(url, headers=headers, json=payload)
            except httpx.TransportError as e:
                last = e
            else:
                if BUDGET_MARKER in resp.text.lower():
                    raise token_budget.BudgetExceeded("LLM proxy: budget has been exceeded")
                if resp.status_code not in RETRY_STATUS:
                    return resp
                last = LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            self._sleep(2 ** attempt)
        raise LLMError(f"LLM request failed after retries: {last}")

    def chat(
        self,
        messages: list[dict],
        complexity: Complexity = "light",
        json_mode: bool = False,
        temperature: float = 0.2,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        reasoning: bool | None = None,
        name: str = "llm",
    ) -> dict:
        """Возвращает {"content", "model", "tokens_in", "tokens_out", "reasoning_tokens", "cost_rub",
        "latency_ms", "finish_reason", "cached"}."""
        profile = PROFILES[complexity]
        model = pick_model(complexity)
        payload: dict = {"model": model, "messages": messages, "temperature": temperature,
                         "max_tokens": max_tokens or profile["max_tokens"]}
        think = profile["reasoning"] if reasoning is None else reasoning
        if think is not None:
            payload["reasoning"] = {"enabled": think}
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "schema": schema.model_json_schema()}}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}

        cache_file = self._cache_file(payload)
        if cache_file and cache_file.exists():
            meta = json.loads(cache_file.read_text(encoding="utf-8")) | {"cached": True, "latency_ms": 0}
            self._trace(name, messages, meta)
            return meta

        token_budget.check_budget(self.db)
        start = time.perf_counter()
        resp = self._post(payload)
        if resp.status_code == 400 and schema is not None:  # провайдер не принял json_schema
            payload["response_format"] = {"type": "json_object"}
            resp = self._post(payload)
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code} from {model}: {resp.text[:500]}")
        data = resp.json()
        usage = data.get("usage") or {}
        choice = (data.get("choices") or [{}])[0]
        cost = resp.headers.get("x-litellm-response-cost")
        meta = {
            "content": (choice.get("message") or {}).get("content"),
            "model": model,
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "cost_rub": float(cost) if cost else None,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "finish_reason": choice.get("finish_reason"),
            "cached": False,
        }
        meta["cost_rub"] = token_budget.record(self.db, model, meta["tokens_in"], meta["tokens_out"], cost_rub=meta["cost_rub"])
        if cache_file and meta["content"]:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        self._trace(name, messages, meta)
        return meta

    def chat_json(self, messages: list[dict], complexity: Complexity = "light") -> tuple[dict, dict]:
        """Возвращает (распарсенный JSON, мета-информация вызова)."""
        meta = self.chat(messages, complexity=complexity, json_mode=True)
        return parse_json(meta["content"]), meta

    def structured(self, messages: list[dict], schema: type[T], complexity: Complexity = "light", *,
                   name: str = "llm", retries: int = 1, **kwargs) -> tuple[T, dict]:
        """Ответ, провалидированный pydantic-схемой. При ошибке - повтор с текстом ошибки валидации."""
        msgs = list(messages)
        max_tokens = kwargs.pop("max_tokens", None)
        error: Exception | None = None
        for _ in range(retries + 1):
            meta = self.chat(msgs, complexity, schema=schema, name=name, max_tokens=max_tokens, **kwargs)
            try:
                return schema.model_validate(parse_json(meta["content"])), meta
            except (ValueError, ValidationError) as e:
                error = e
            if not meta["content"] and meta.get("finish_reason") == "length":
                max_tokens = 2 * (max_tokens or PROFILES[complexity]["max_tokens"])
                continue
            msgs = [*messages, {"role": "assistant", "content": meta["content"] or ""}, {"role": "user", "content": (
                f"Ответ не прошёл проверку схемы: {str(error)[:800]}\n"
                "Верни только исправленный JSON-объект по схеме, без пояснений.")}]
        raise LLMError(f"{name}: invalid JSON after {retries + 1} attempts: {error}")

    def _cache_file(self, payload: dict) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _trace(self, name: str, messages: list[dict], meta: dict) -> None:
        if self.tracer is None:
            return
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        self.tracer.log(
            "llm_call", name,
            input={"model": meta["model"], "prompt_chars": sum(len(str(m.get("content", ""))) for m in messages),
                   "last_user_preview": str(last_user)[:500]},
            output={"content_preview": (meta["content"] or "")[:1500], "finish_reason": meta.get("finish_reason"),
                    "reasoning_tokens": meta.get("reasoning_tokens"), "cost_rub": meta.get("cost_rub"),
                    "cached": meta.get("cached")},
            model=meta["model"], tokens_in=meta["tokens_in"], tokens_out=meta["tokens_out"],
            latency_ms=meta["latency_ms"],
        )
