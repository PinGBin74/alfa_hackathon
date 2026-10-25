"""Сквозной сценарий проверки из README на синтетических данных (data/synthetic, data/test_accounts.json):
вход -> компании -> персональная лента -> разбор события -> трасса -> уточняющий вопрос -> оценка -> метрики.

Настоящие: загрузка данных (app.db.seed), вход и JWT, разграничение доступа, профиль, граф, ранжирование ленты,
кэш разборов. Подменены только вызовы LLM: агент (orchestrator.run) и ответ чата - их логика в unit-тестах.
БД - SQLite в памяти."""
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import chat as chat_route
from app.db import seed
from app.db.models import AgentTrace, InsightRecord
from app.db.session import Base, get_db
from app.main import app
from app.schemas.insight import Insight
from app.schemas.news import ChatAnswer
from app.services import insight_jobs


def _data_dir() -> Path:
    """data/ - в корне репозитория; в контейнере backend смонтирован в /app/data."""
    here = Path(__file__).resolve()
    for base in (here.parents[3], here.parents[2]):
        if (base / "data" / "synthetic").is_dir():
            return base / "data"
    pytest.skip("data/synthetic not found")


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def client(engine):
    data = _data_dir()
    mp = pytest.MonkeyPatch()
    mp.setattr(seed, "engine", engine)
    mp.setattr(seed, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    mp.setattr(sys, "argv", ["seed", "--dir", str(data / "synthetic"), "--users", str(data / "test_accounts.json"),
                             "--news", str(data / "synthetic" / "news.jsonl")])
    seed.main()

    def _db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()
    mp.undo()


def _login(client: TestClient, login: str) -> dict:
    r = client.post("/api/auth/login", json={"login": login})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _fake_agent(db, client_id, news_id, user_role=None, trace_id=None):
    """Вместо агента: тот же контракт - шаги в трассе, инсайт в БД, Insight на выходе."""
    db.add_all([
        AgentTrace(trace_id=trace_id, step=1, kind="plan", name="make_plan",
                   output={"focus_factors": ["key_rate"], "plan": [{"tool": "search_bank_analytics"}], "source": "llm"}),
        AgentTrace(trace_id=trace_id, step=2, kind="verify", name="verifier",
                   output={"passed": True, "issues": [], "iterations": 1}),
    ])
    insight = Insight(
        insight_id=uuid.uuid4().hex, client_id=client_id, user_role=user_role, news_id=news_id,
        what_happened={"summary": "Событие из новости."},
        why_it_matters=[{"text": "У компании кредиты в Альфа-Банке", "client_features": ["CL_PRODUCT_LOA_MARK"]}],
        consequences={"risks": [{"text": "Обслуживание долга не подешевеет", "basis": [f"news:{news_id}"]}]},
        verification={"passed": True, "iterations": 1, "issues": []},
        trace_id=trace_id, generated_at=datetime.now(UTC),
    )
    db.add(InsightRecord(insight_id=insight.insight_id, client_id=client_id, user_role=user_role, news_id=news_id,
                         payload=insight.model_dump(mode="json"), trace_id=trace_id))
    db.commit()
    return insight


def test_jury_scenario(client, monkeypatch):
    # 1. Экран входа: тестовые учётки из data/test_accounts.json с компаниями
    accounts = {a["login"]: a for a in client.get("/api/auth/demo-accounts").json()}
    assert {"cfo_demo", "ceo_demo", "treasurer_demo", "owner_demo", "accountant_demo"} <= set(accounts)
    assert all(c["okved_name"] for c in accounts["cfo_demo"]["companies"])   # компании загружены
    assert client.post("/api/auth/login", json={"login": "nobody"}).status_code == 401

    cfo = _login(client, "cfo_demo")
    assert client.get("/api/auth/me", headers=cfo).json()["role"] == "cfo"
    assert client.get("/api/clients").status_code == 401                       # без токена - нет доступа

    # 2. Компании пользователя и профиль первой
    companies = [c["client_id"] for c in client.get("/api/clients", headers=cfo).json()]
    assert companies == accounts["cfo_demo"]["company_ids"]
    main, other = companies[0], companies[1]
    profile = client.get(f"/api/clients/{main}/profile", headers=cfo).json()
    assert profile["client_id"] == main and profile["okved_code"]

    # 3. Персональная лента: ранжирована, у новостей есть причины; у другой компании - другой порядок
    feed = client.get(f"/api/feed/{main}", headers=cfo).json()
    assert len(feed) >= 5
    scores = [e["relevance_score"] for e in feed]
    assert scores == sorted(scores, reverse=True)
    assert any(e["relevance_reasons"] for e in feed)
    other_feed = client.get(f"/api/feed/{other}", headers=cfo).json()
    assert [e["news"]["news_id"] for e in feed] != [e["news"]["news_id"] for e in other_feed]

    # Чужая компания недоступна
    foreign = next(c for a in accounts.values() for c in a["company_ids"] if c not in companies)
    assert client.get(f"/api/feed/{foreign}", headers=cfo).status_code == 403
    assert client.post(f"/api/insights/{foreign}/{feed[0]['news']['news_id']}", headers=cfo).status_code == 403

    # 4. Событие: новость и разбор (агент запускается один раз, дальше - из кэша)
    news_id = feed[0]["news"]["news_id"]
    assert client.get(f"/api/news/{news_id}", headers=cfo).json()["title"]
    runs = []
    monkeypatch.setattr(insight_jobs.orchestrator, "run",
                        lambda *a, **kw: runs.append(1) or _fake_agent(*a, **kw))
    insight = client.post(f"/api/insights/{main}/{news_id}", headers=cfo).json()
    assert insight["client_id"] == main and insight["user_role"] == "cfo" and insight["why_it_matters"]
    assert client.post(f"/api/insights/{main}/{news_id}", headers=cfo).json()["insight_id"] == insight["insight_id"]
    assert len(runs) == 1
    refreshed = {e["news"]["news_id"]: e for e in client.get(f"/api/feed/{main}", headers=cfo).json()}
    assert refreshed[news_id]["insight_id"] == insight["insight_id"]      # в ленте отмечен готовый разбор

    # 5. «Как получен разбор»: шаги агента
    trace = client.get(f"/api/insights/{insight['insight_id']}/trace", headers=cfo).json()
    assert [s["kind"] for s in trace] == ["plan", "verify"]

    # 6. Уточняющий вопрос
    monkeypatch.setattr(chat_route.chat, "answer", lambda db, record, question, user_role=None, history=None:
                        ChatAnswer(answer=f"Ответ по {record.insight_id}", source_ids=[f"news:{news_id}"]))
    answer = client.post("/api/chat", headers=cfo, json={"insight_id": insight["insight_id"],
                                                         "question": "Покажите влияние в разрезе контрагентов"})
    assert answer.status_code == 200 and insight["insight_id"] in answer.json()["answer"]

    # 7. Пользователь без доступа к компании не открывает её разбор даже по прямому id
    accountant = _login(client, "accountant_demo")
    assert main not in accounts["accountant_demo"]["company_ids"]
    assert client.get(f"/api/insights/{insight['insight_id']}", headers=accountant).status_code == 403
    assert client.get(f"/api/insights/{insight['insight_id']}/trace", headers=accountant).status_code == 403

    # 8. Оценка разбора и метрики качества
    assert client.post("/api/feedback", headers=cfo,
                       json={"insight_id": insight["insight_id"], "rating": 1}).json() == {"ok": True}
    metrics = client.get("/api/feedback/metrics", headers=cfo).json()
    assert metrics["insights_total"] == 1
