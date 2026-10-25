"""Роуты, через которые ML-часть доступна пользователю: чат, новость по ссылке, лента, инсайты и ход их генерации,
аналитика банка, вход, метрики качества. Агент и конвейер новостей подменены (их логика - в test_agent /
test_news_ingestion), БД - SQLite в памяти."""
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent.llm_client import LLMError
from app.api.routes import analytics as analytics_route
from app.api.routes import chat as chat_route
from app.api.routes import feed as feed_route
from app.api.routes import news as news_route
from app.config import Settings
from app.db.models import (
    AgentTrace,
    AnalyticsChunk,
    AnalyticsDoc,
    Company,
    Feedback,
    InsightRecord,
    NewsItem,
    Payment,
    Person,
    TokenUsage,
    User,
)
from app.db.session import Base, get_db
from app.ingestion import manual
from app.main import app
from app.ml import bank_positions
from app.ml.news import NewsClassification
from app.schemas.insight import Insight
from app.schemas.news import ChatAnswer
from app.security.rbac import get_current_user
from app.services import insight_jobs
from app.services.token_budget import BudgetExceeded

NOW = datetime.now(UTC)
PAYLOAD = {
    "verification": {"passed": True, "iterations": 1, "issues": []},
    "bank_position": [{"text": "Банк ожидает ставку 14%", "analytics_doc_id": "d1", "quote_ref": "bank:d1:1"}],
    "consequences": {"risks": [{"text": "Долг останется дорогим", "basis": ["news:n1"]}], "opportunities": []},
    "ai_inference": [],
    "why_it_matters": [{"text": "У компании кредиты", "client_features": ["CL_PRODUCT_LOA_MARK"]}],
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[t.__table__ for t in (
        Company, Person, Payment, NewsItem, InsightRecord, AgentTrace, TokenUsage, Feedback, User, AnalyticsDoc,
        AnalyticsChunk)])
    with Session(engine) as s:
        s.add_all([
            Company(synthetic_u="C", mainokved_code="42.99", mainokved_name="Строительство", revenue=20e9,
                    region="Иркутская область", has_loans=True, cl_type="CLIENT"),
            NewsItem(news_id="n1", source="test", url="https://x.test/1", title="ЦБ сохранил ставку 14%",
                     event_type="key_rate", dedup_hash="h1", published_at=NOW - timedelta(hours=2)),
            NewsItem(news_id="n2", source="test", url="https://x.test/2", title="Минфин разместил ОФЗ",
                     event_type="bonds", dedup_hash="h2", published_at=NOW - timedelta(hours=1)),
            InsightRecord(insight_id="i1", client_id="C", user_role="treasurer", news_id="n1", payload=PAYLOAD,
                          trace_id="t1"),
        ])
        s.commit()
        yield s


@pytest.fixture
def client(db):
    user = User(user_id="u1", login="treasurer_demo", role="treasurer", company_ids=["C"])

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------- чат ----------

def test_chat_returns_agent_answer(client, monkeypatch):
    calls = []

    def fake_answer(db, record, question, user_role=None, history=None):
        calls.append((record.insight_id, question, user_role, [(t.role, t.content) for t in history or []]))
        return ChatAnswer(answer="Ставка останется высокой.", source_ids=["bank:d1:1"], trace_id="t2")

    monkeypatch.setattr(chat_route.chat, "answer", fake_answer)
    history = [{"role": "user", "content": "Что со ставкой?"}, {"role": "assistant", "content": "Сохранена на 14%."}]
    r = client.post("/api/chat", json={"insight_id": "i1", "question": "А с долгом?", "history": history})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Ставка останется высокой." and body["source_ids"] == ["bank:d1:1"] and body["trace_id"] == "t2"
    assert calls == [("i1", "А с долгом?", "treasurer", [("user", "Что со ставкой?"), ("assistant", "Сохранена на 14%.")])]


def test_chat_history_block_is_bounded():
    from app.agent.chat import HISTORY_TURNS, _history_block
    from app.schemas.news import ChatTurn
    turns = [ChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"реплика {i}") for i in range(10)]
    block = _history_block(turns)
    assert block.startswith("ИСТОРИЯ РАЗГОВОРА") and "реплика 9" in block and "реплика 3" not in block
    assert block.count("\n") == HISTORY_TURNS and _history_block([]) == ""


@pytest.mark.parametrize(("error", "status"), [(BudgetExceeded("limit"), 429), (LLMError("down"), 502)])
def test_chat_maps_llm_failures(client, monkeypatch, error, status):
    def failing(*a, **kw):
        raise error

    monkeypatch.setattr(chat_route.chat, "answer", failing)
    assert client.post("/api/chat", json={"insight_id": "i1", "question": "Что с долгом?"}).status_code == status


def test_chat_checks_insight_access_and_question(client, db, monkeypatch):
    monkeypatch.setattr(chat_route.chat, "answer", lambda *a, **kw: pytest.fail("agent must not run"))
    db.add(InsightRecord(insight_id="foreign", client_id="OTHER", news_id="n1", payload=PAYLOAD))
    db.commit()
    assert client.post("/api/chat", json={"insight_id": "nope", "question": "?"}).status_code == 404
    assert client.post("/api/chat", json={"insight_id": "foreign", "question": "?"}).status_code == 403
    assert client.post("/api/chat", json={"insight_id": "i1", "question": ""}).status_code == 422
    assert client.post("/api/chat", json={"insight_id": "i1", "question": "x" * 2001}).status_code == 422


# ---------- новость по ссылке ----------

def test_news_by_url_returns_stored_item(client, db, monkeypatch):
    calls = []

    def fake_ingest(db_, llm, url):
        calls.append(url)
        return db_.get(NewsItem, "n1")

    monkeypatch.setattr(news_route.manual, "ingest_url", fake_ingest)
    r = client.post("/api/news", json={"url": "https://x.test/1?utm_source=tg"})
    assert r.status_code == 200
    body = r.json()
    assert body["news_id"] == "n1" and body["event_type"] == "key_rate" and body["key_facts"] == []
    assert calls == ["https://x.test/1?utm_source=tg"]


@pytest.mark.parametrize(("error", "status"), [
    (manual.IngestError("ссылка ведёт во внутреннюю сеть"), 422),
    (manual.NotBusinessNews(NewsClassification(is_business_relevant=False, summary="Матч")), 422),
    (BudgetExceeded("limit"), 429),
    (LLMError("down"), 502),
])
def test_news_by_url_maps_errors(client, monkeypatch, error, status):
    def failing(*a, **kw):
        raise error

    monkeypatch.setattr(news_route.manual, "ingest_url", failing)
    r = client.post("/api/news", json={"url": "http://127.0.0.1/admin"})
    assert r.status_code == status
    if isinstance(error, manual.IngestError):
        assert r.json()["detail"] == str(error)


# ---------- лента и метрики ----------

def test_news_detail_has_factor_labels_and_body(client, db):
    db.get(NewsItem, "n1").body = "Совет директоров Банка России сохранил ключевую ставку на уровне 14%."
    db.commit()
    r = client.get("/api/news/n1")
    assert r.status_code == 200
    body = r.json()
    assert body["factors"][0]["factor"] == "key_rate" and body["factors"][0]["label"]
    assert body["body"].startswith("Совет директоров") and body["importance"] == 3
    assert client.get("/api/news/missing").status_code == 404


def test_feed_ranks_with_user_role_newest_first(client, monkeypatch):
    roles = []
    original = feed_route.feed.ranking.score_news

    def spy(profile, news, semantic_sim=0.0, role=None):
        roles.append(role)
        return original(profile, news, semantic_sim=semantic_sim, role=role)

    monkeypatch.setattr(feed_route.feed.ranking, "score_news", spy)
    r = client.get("/api/feed/C")
    assert r.status_code == 200
    assert {e["news"]["news_id"] for e in r.json()} == {"n1", "n2"}
    assert roles == ["treasurer", "treasurer"]


def test_feed_links_ready_insight_for_user_role(client, db):
    db.add(InsightRecord(insight_id="i-cfo", client_id="C", user_role="cfo", news_id="n2", payload=PAYLOAD))
    db.commit()
    entries = {e["news"]["news_id"]: e for e in client.get("/api/feed/C").json()}
    assert entries["n1"]["insight_id"] == "i1"            # инсайт для роли пользователя (treasurer)
    assert entries["n2"]["insight_id"] is None            # инсайт для другой роли не подходит
    assert set(entries["n1"]["relevance_parts"]) == {"factor", "industry", "geo", "importance", "freshness"}
    assert entries["n1"]["news"]["factors"][0]["factor"] == "key_rate"


def test_metrics_include_insight_quality(client):
    m = client.get("/api/feedback/metrics").json()
    assert m["insights_total"] == 1 and m["insights_evaluated"] == 1
    assert m["verified_rate"] == 1.0 and m["verified_first_iteration_rate"] == 1.0
    assert m["bank_view_rate"] == 1.0 and m["statements_with_sources_rate"] == 1.0
    assert m["insights_by_role"] == {"treasurer": 1}


# ---------- конфигурация моделей ----------

def test_default_models_are_proxy_ids(monkeypatch):
    names = ("light", "reasoning", "general", "research", "text", "vision")
    for name in names:
        monkeypatch.delenv(f"LLM_MODEL_{name.upper()}", raising=False)
    s = Settings(_env_file=None)
    ids = [getattr(s, f"llm_model_{name}") for name in names]
    assert all("/" in m and " " not in m for m in ids), ids   # ID прокси, не отображаемые названия
    assert len(set(ids)) == len(ids)


def test_vision_model_comes_from_settings(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("LLM_MODEL_VISION", "qwen/vl-test")
    get_settings.cache_clear()
    try:
        assert bank_positions.vlm_model() == "qwen/vl-test"
    finally:
        get_settings.cache_clear()


# ---------- инсайты: кэш, ход генерации, трасса ----------

def full_payload(insight_id: str = "i9", news_id: str = "n2", role: str = "treasurer") -> dict:
    return Insight(insight_id=insight_id, client_id="C", user_role=role, news_id=news_id,
                   what_happened={"summary": "Минфин разместил ОФЗ."}, why_it_matters=[], consequences={},
                   trace_id="t9", generated_at=NOW).model_dump(mode="json")


def test_insight_cached_and_by_id(client, db, monkeypatch):
    db.add(InsightRecord(insight_id="i9", client_id="C", user_role="treasurer", news_id="n2", payload=full_payload(),
                         trace_id="t9"))
    db.commit()
    monkeypatch.setattr(insight_jobs.orchestrator, "run", lambda *a, **kw: pytest.fail("cache must be used"))
    assert client.post("/api/insights/C/n2").json()["insight_id"] == "i9"
    assert client.get("/api/insights/i9").json()["what_happened"]["summary"] == "Минфин разместил ОФЗ."
    assert client.get("/api/insights/nope").status_code == 404
    assert client.get("/api/insights/C/n2/progress").json() == {"status": "ready", "insight_id": "i9",
                                                                "trace_id": "t9", "steps": []}
    assert client.get("/api/insights/C/n1x/progress").json()["status"] == "idle"


@pytest.mark.parametrize(("error", "status"), [(LookupError("no news"), 404), (LLMError("down"), 502),
                                               (BudgetExceeded("limit"), 429)])
def test_insight_maps_agent_failures(client, monkeypatch, error, status):
    def failing(*a, **kw):
        raise error

    monkeypatch.setattr(insight_jobs.orchestrator, "run", failing)
    assert client.post("/api/insights/C/n2").status_code == status
    assert insight_jobs.running("C", "n2", "treasurer") is None   # реестр очищается и после ошибки


def test_insight_progress_shows_steps_while_running_and_runs_once(client, db, monkeypatch):
    started, release, runs = threading.Event(), threading.Event(), []

    def slow_run(db_, client_id, news_id, user_role=None, trace_id=None):
        runs.append(trace_id)
        db_.add(AgentTrace(trace_id=trace_id, step=1, kind="tool_call", name="search_bank_analytics",
                           input={"query": "ключевая ставка", "k": 4}))
        db_.commit()
        started.set()
        release.wait(5)
        return Insight.model_validate(full_payload())

    monkeypatch.setattr(insight_jobs.orchestrator, "run", slow_run)
    results = []
    first = threading.Thread(target=lambda: results.append(client.post("/api/insights/C/n2").json()))
    first.start()
    assert started.wait(5)
    progress = client.get("/api/insights/C/n2/progress").json()
    assert progress["status"] == "running" and progress["trace_id"] == runs[0]
    assert progress["steps"][0]["title"] == "Поиск в аналитике Альфа-Банка"
    assert "ключевая ставка" in progress["steps"][0]["detail"] and "input" not in progress["steps"][0]
    second = threading.Thread(target=lambda: results.append(client.post("/api/insights/C/n2").json()))
    second.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    second.join(5)
    assert len(runs) == 1 and [r["insight_id"] for r in results] == ["i9", "i9"]


def test_trace_steps_are_described(client, db):
    db.add_all([AgentTrace(trace_id="t1", step=1, kind="plan", name="make_plan",
                           output={"focus_factors": ["key_rate"], "plan": [{"tool": "search_bank_analytics"}],
                                   "source": "llm"}),
                AgentTrace(trace_id="t1", step=2, kind="verify", name="verifier",
                           output={"passed": False, "issues": ["wrong_number x: y", "(warning) generic z: w"], "iterations": 1})])
    db.commit()
    steps = client.get("/api/insights/i1/trace").json()
    assert steps[0]["title"] == "План анализа" and "Ключевая ставка" in steps[0]["detail"]
    assert steps[1]["title"] == "Самопроверка: есть замечания" and "замечаний: 1" in steps[1]["detail"]
    assert steps[1]["output"]["iterations"] == 1   # сырые данные шага остаются


# ---------- аналитика банка, вход, справочники ----------

POSITIONS = {"documents": [{"doc_id": "d1", "title": "Ключевая ставка ЦБ РФ", "date": "2026-09-11", "stale": False}],
             "positions": [
                 {"position_id": "d1-p1-a", "doc_id": "d1", "page": 1, "thesis": "Банк ждёт ставку 14%.",
                  "quote": "ставка 14%", "factors": ["key_rate"], "superseded_by": "d1-p2-b"},
                 {"position_id": "d1-p2-b", "doc_id": "d1", "page": 2, "thesis": "Банк ждёт ставку 13%.",
                  "quote": "ставка 13%", "factors": ["key_rate"], "date": "2026-09-11"}]}


def test_analytics_page_shows_positions_and_newer_forecast(client, db, monkeypatch):
    monkeypatch.setattr(analytics_route.bank_positions, "load_positions_data", lambda path=None: POSITIONS)
    monkeypatch.setattr(analytics_route.bank_positions, "load_positions", lambda path=None: POSITIONS["positions"])
    db.add_all([AnalyticsDoc(doc_id="d1", title="Ключевая ставка ЦБ РФ", file_path="../../etc/passwd"),
                AnalyticsChunk(doc_id="d1", page=1, text="Текст страницы 1")])
    db.commit()
    page = client.get("/api/analytics/d1/pages/1").json()
    assert page["source_id"] == "bank:d1:1" and page["text"] == "Текст страницы 1"
    assert page["positions"][0]["superseded_by"]["thesis"] == "Банк ждёт ставку 13%."
    assert client.get("/api/analytics/d1/pages/9").status_code == 404
    assert client.get("/api/analytics/zz/pages/1").status_code == 404
    assert client.get("/api/analytics/d1/file").status_code == 404   # путь вне папки аналитики не отдаётся
    assert client.get("/api/analytics").json()[0]["positions"] == 2


def test_demo_accounts_and_meta(client, db):
    db.add(User(user_id="u7", login="cfo_demo", role="cfo", company_ids=["C"]))
    db.commit()
    accounts = client.get("/api/auth/demo-accounts").json()
    assert accounts[0]["login"] == "cfo_demo" and accounts[0]["role_name"] == "финансовый директор"
    assert accounts[0]["companies"][0]["okved_name"] == "Строительство"
    login = client.post("/api/auth/login", json={"login": "cfo_demo"}).json()
    assert login["access_token"] and login["company_ids"] == ["C"]
    assert client.post("/api/auth/login", json={"login": "nobody"}).status_code == 401
    meta = client.get("/api/meta").json()
    assert meta["factors"]["key_rate"] and meta["roles"]["cfo"] == "финансовый директор" and meta["okved2"]["42"]


@pytest.mark.parametrize(("env", "secret", "ok"), [
    ("dev", "change-me-to-random-64-hex-chars-openssl-rand-hex-32", True),   # локально - можно
    ("prod", "change-me-to-random-64-hex-chars-openssl-rand-hex-32", False),  # общеизвестный ключ
    ("prod", "short-secret", False),
    ("prod", "a" * 64, True),
])
def test_prod_requires_strong_jwt_secret(env, secret, ok):
    s = Settings(_env_file=None, app_env=env, jwt_secret=secret)
    if ok:
        s.check_prod_secrets()
    else:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            s.check_prod_secrets()
