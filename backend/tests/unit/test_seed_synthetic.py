"""Синтетические данные (app/db/synthetic.py) и загрузка в БД (app/db/seed.py): профиль демо-клиента,
построенный по синтетике, повторяет признаки исходного профиля; тестовые учётки и демо-новости загружаются."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import seed, synthetic
from app.db.models import Company, NewsItem, Payment, Person, User
from app.db.session import Base
from app.services.client_profile import build_profile

ROOT = Path(__file__).resolve().parents[3]
PROFILES_PATH = ROOT / "eval" / "fixtures" / "demo_profiles.json"
if not PROFILES_PATH.exists():  # в образе backend нет eval/ (make test в Docker)
    pytest.skip("нет eval/fixtures/demo_profiles.json", allow_module_level=True)
PROFILES = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[t.__table__ for t in (Company, Person, Payment, NewsItem, User)])
    return eng


def _load_synthetic(engine, tmp_path: Path, profiles: list[dict]) -> None:
    gen = synthetic.Generator()
    for p in profiles:
        gen.client(p)
    gen.peers(profiles)
    synthetic.write_csv(tmp_path / "c.csv", synthetic.COMPANY_COLUMNS, list(gen.companies.values()))
    synthetic.write_csv(tmp_path / "p.csv", ["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"], gen.payments)
    companies, ambiguous = seed.clean_companies(seed.read_csv(tmp_path / "c.csv", seed.COMPANY_MAP))
    payments = seed.clean_payments(seed.read_csv(tmp_path / "p.csv", seed.PAYMENT_MAP), ambiguous)
    companies.to_sql("companies", engine, if_exists="append", index=False)
    payments.to_sql("payments", engine, if_exists="append", index=False)


@pytest.mark.parametrize("client_id", ["U_9250", "U_177581"])
def test_synthetic_profile_matches_source_profile(engine, tmp_path, client_id):
    ref = PROFILES[client_id]
    _load_synthetic(engine, tmp_path, [ref])
    with Session(engine) as db:
        p = build_profile(db, client_id)
    assert (p.okved_code, p.region, p.revenue, p.products, p.foreign_trade) == (
        ref["okved_code"], ref["region"], ref["revenue"], type(p.products)(**ref["products"]),
        type(p.foreign_trade)(**ref["foreign_trade"]))
    assert p.group.size == ref["group"]["size"]
    assert [i.okved2 for i in p.group.top_industries] == [i["okved2"] for i in ref["group"]["top_industries"]]
    assert p.industry_position.revenue_rank == ref["industry_position"]["revenue_rank"]
    g, rg = p.graph, ref["graph"]
    for side in ("supplier", "buyer"):
        assert [t.client_id for t in getattr(g, f"top_{side}s")] == [t["client_id"] for t in rg[f"top_{side}s"]]
        assert [i.okved2 for i in getattr(g, f"{side}_industries")] == [i["okved2"] for i in rg[f"{side}_industries"]]
        assert getattr(g, f"{side}_unknown_share") == pytest.approx(rg[f"{side}_unknown_share"], abs=0.01)
        assert getattr(g, f"{side}_intragroup_share") == pytest.approx(rg[f"{side}_intragroup_share"], abs=0.01)
        assert getattr(g, f"{side}s_count") == rg[f"{side}s_count"]


def test_peers_keep_rank_for_clients_of_one_class(engine, tmp_path):
    refs = [PROFILES[c] for c in ("U_200890", "U_1465", "U_34911")]   # все трое - оптовая торговля (46)
    _load_synthetic(engine, tmp_path, refs)
    with Session(engine) as db:
        ranks = {r["client_id"]: build_profile(db, r["client_id"], with_graph=False).industry_position.revenue_rank
                 for r in refs}
    assert ranks == {r["client_id"]: r["industry_position"]["revenue_rank"] for r in refs}


def test_generator_is_deterministic():
    def run():
        gen = synthetic.Generator()
        gen.client(PROFILES["U_34911"])
        return gen.companies, gen.payments
    assert run() == run()


def test_seed_loads_users_and_demo_news(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=engine))
    with Session(engine) as db:
        db.add_all([Company(synthetic_u="U_1"), User(user_id="old", login="old", role="cfo", company_ids=[])])
        db.commit()
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps([{"user_id": "u1", "login": "cfo_demo", "role": "cfo", "company_ids": ["U_1", "U_x"]}]))
    seed.load_users(accounts)
    news = tmp_path / "news.jsonl"
    news.write_text(json.dumps({"news_id": "syn-1", "source": "demo", "title": "ЦБ сохранил ставку", "body": "Текст",
                                "ml_meta": {"summary": "ЦБ сохранил ставку.", "factors": [{"factor": "key_rate"}],
                                            "importance": 5}}, ensure_ascii=False) + "\n")
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    seed.load_news(news, now=now)
    seed.load_news(news, now=now)   # повторная загрузка не дублирует
    with Session(engine) as db:
        assert [(u.login, u.company_ids) for u in db.query(User)] == [("cfo_demo", ["U_1", "U_x"])]
        items = db.query(NewsItem).all()
        assert len(items) == 1 and items[0].event_type == "key_rate" and items[0].ml_meta["importance"] == 5
