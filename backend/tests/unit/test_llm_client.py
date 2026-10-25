"""LLM-клиент: профили вызова, разбор JSON, повторы, бюджет, кеш. HTTP подменён MockTransport."""
import json

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent import llm_client
from app.agent.llm_client import LLMClient, LLMError, parse_json
from app.config import get_settings
from app.db.models import TokenUsage
from app.db.session import Base
from app.services.token_budget import BudgetExceeded


class Tags(BaseModel):
    sentiment: str
    factors: list[str]


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TokenUsage.__table__])
    with Session(engine) as s:
        yield s
    get_settings.cache_clear()


def _reply(content, cost="0.5", status=200, finish="stop"):
    body = {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    return httpx.Response(status, json=body, headers={"x-litellm-response-cost": cost} if cost else {})


def _client(db, handler, **kw) -> tuple[LLMClient, list[dict]]:
    sent: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return handler(request, len(sent))

    c = LLMClient(db, http=httpx.Client(transport=httpx.MockTransport(wrapped)), **kw)
    c._sleep = lambda s: None
    return c, sent


@pytest.mark.parametrize(("content", "expected"), [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Вот ответ: {"a": {"b": 2}} спасибо', {"a": {"b": 2}}),
])
def test_parse_json(content, expected):
    assert parse_json(content) == expected


@pytest.mark.parametrize("content", [None, "", "нет json", "[1, 2]"])
def test_parse_json_rejects(content):
    with pytest.raises(ValueError):
        parse_json(content)


def test_profile_disables_reasoning_and_sets_max_tokens(db):
    c, sent = _client(db, lambda r, n: _reply("ok"))
    c.chat([{"role": "user", "content": "hi"}], complexity="general")
    c.chat([{"role": "user", "content": "hi"}], complexity="light")
    assert sent[0]["reasoning"] == {"enabled": False} and sent[0]["max_tokens"] == llm_client.PROFILES["general"]["max_tokens"]
    assert "reasoning" not in sent[1]


def test_records_real_cost_from_header(db):
    c, _ = _client(db, lambda r, n: _reply("ok", cost="1.25"))
    meta = c.chat([{"role": "user", "content": "hi"}])
    assert meta["cost_rub"] == 1.25
    assert db.query(TokenUsage).one().cost_rub == 1.25


def test_structured_retries_with_validation_error(db):
    replies = ['{"sentiment": "neutral"}', '```json\n{"sentiment": "neutral", "factors": ["key_rate"]}\n```']
    c, sent = _client(db, lambda r, n: _reply(replies[n - 1]))
    obj, _ = c.structured([{"role": "user", "content": "x"}], Tags)
    assert obj.factors == ["key_rate"]
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert "не прошёл проверку схемы" in sent[1]["messages"][-1]["content"]


def test_structured_gives_up(db):
    c, _ = _client(db, lambda r, n: _reply("не json"))
    with pytest.raises(LLMError):
        c.structured([{"role": "user", "content": "x"}], Tags, retries=1)


def test_retries_transient_errors(db):
    c, sent = _client(db, lambda r, n: _reply("ok") if n == 2 else httpx.Response(503, text="busy"))
    assert c.chat([{"role": "user", "content": "x"}])["content"] == "ok"
    assert len(sent) == 2


def test_budget_exceeded_from_proxy(db):
    c, _ = _client(db, lambda r, n: httpx.Response(400, text='{"error": "Budget has been exceeded! Current cost: 500"}'))
    with pytest.raises(BudgetExceeded):
        c.chat([{"role": "user", "content": "x"}])


def test_falls_back_to_json_object_when_schema_rejected(db):
    c, sent = _client(db, lambda r, n: httpx.Response(400, text="bad schema") if n == 1
                      else _reply('{"sentiment": "neutral", "factors": []}'))
    obj, _ = c.structured([{"role": "user", "content": "x"}], Tags)
    assert obj.sentiment == "neutral" and sent[1]["response_format"] == {"type": "json_object"}


def test_cache_skips_second_call(db, tmp_path):
    c, sent = _client(db, lambda r, n: _reply("ok"), cache_dir=tmp_path)
    msgs = [{"role": "user", "content": "x"}]
    c.chat(msgs)
    again = c.chat(msgs)
    assert len(sent) == 1 and again["cached"] is True and again["content"] == "ok"


def test_own_timeout_fails_fast_without_retries(db):
    def slow(request, n):
        assert request.extensions["timeout"]["read"] == 2.0   # свой лимит дошёл до запроса
        raise httpx.ReadTimeout("slow", request=request)

    c, sent = _client(db, slow)
    with pytest.raises(LLMError, match="in 2 s"):
        c.chat([{"role": "user", "content": "x"}], timeout=2.0)
    assert len(sent) == 1


def test_timeout_without_own_limit_is_retried(db):
    def flaky(request, n):
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return _reply("ok")

    c, sent = _client(db, flaky)
    assert c.chat([{"role": "user", "content": "x"}])["content"] == "ok" and len(sent) == 2


# ---------- ошибки настройки и ответа прокси: LLMError (502), а не 500 ----------

@pytest.mark.parametrize(("env", "value"), [
    ("LLM_API_KEY", "changeme"),
    ("LLM_API_KEY", ""),
    ("LLM_BASE_URL", "https://<endpoint-из-кейса>/v1"),
    ("LLM_BASE_URL", ""),
])
def test_misconfigured_llm_fails_before_request(db, monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    get_settings.cache_clear()
    c, sent = _client(db, lambda r, n: pytest.fail("request must not be sent"))
    with pytest.raises(LLMError, match=env):
        c.chat([{"role": "user", "content": "hi"}])
    assert sent == []


def test_invalid_base_url_is_llm_error(db):
    def broken(request, n):
        raise httpx.InvalidURL("Invalid IDNA hostname")

    c, sent = _client(db, broken)
    with pytest.raises(LLMError, match="invalid LLM_BASE_URL"):
        c.chat([{"role": "user", "content": "hi"}])
    assert len(sent) == 1   # без бессмысленных повторов


def test_non_json_response_is_llm_error(db):
    c, _ = _client(db, lambda r, n: httpx.Response(200, text="<html>Bad gateway</html>"))
    with pytest.raises(LLMError, match="non-JSON"):
        c.chat([{"role": "user", "content": "hi"}])
