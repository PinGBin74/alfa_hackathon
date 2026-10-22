"""Слой данных: очистка CSV при загрузке, профиль компании, граф контрагентов."""
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import seed
from app.db.models import Company, Payment, Person
from app.db.session import Base
from app.services import client_profile, counterparty_graph


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Company.__table__, Person.__table__, Payment.__table__])
    with Session(engine) as s:
        yield s


def _co(uid: str, okved: str = "46.71", group: str = "g1", revenue: float = 1e9, **kw) -> Company:
    return Company(synthetic_u=uid, mainokved_code=okved, mainokved_name=f"name {okved}",
                   group_id=group, revenue=revenue, region="Москва", **kw)


def _pay(payer: str, beneficiary: str, amt: float, cnt: int = 1) -> Payment:
    return Payment(payer=payer, beneficiary=beneficiary, pay_amt=amt, pay_cnt=cnt)


# ---------- seed: очистка ----------

def test_read_csv_uses_semicolon(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("SYNTHETIC_U;REVENUE_COMPANY\nU_1;10.0\n", encoding="utf-8")
    assert list(seed.read_csv(p).columns) == ["SYNTHETIC_U", "REVENUE_COMPANY"]


def test_clean_companies_drops_ambiguous_ids():
    df = pd.DataFrame({"synthetic_u": ["U_1", "U_2", "U_2"], "has_loans": [1.0, None, 0.0]})
    clean, ambiguous = seed.clean_companies(df)
    assert clean.synthetic_u.tolist() == ["U_1"]
    assert ambiguous == {"U_2"}
    assert clean.has_loans.tolist() == [True]


def test_clean_persons_keeps_only_known_companies():
    df = pd.DataFrame({"synthetic_f": ["F_1", "F_2"], "synthetic_u": ["U_1", "U_404"]})
    assert seed.clean_persons(df, known={"U_1"}).synthetic_u.tolist() == ["U_1"]


def test_clean_payments_drops_self_and_ambiguous_and_merges_pairs():
    df = pd.DataFrame({
        "payer":       ["U_1", "U_1", "U_1", "U_1", "U_2"],
        "beneficiary": ["U_1", "U_2", "U_2", "U_3", "U_1"],
        "pay_amt":     [100.0, 10.0, 5.0, 7.0, 3.0],
        "pay_cnt":     [1, 2, 1, 1, 1],
    })
    clean = seed.clean_payments(df, ambiguous={"U_3"}).sort_values(["payer", "beneficiary"])
    assert clean[["payer", "beneficiary"]].values.tolist() == [["U_1", "U_2"], ["U_2", "U_1"]]
    assert clean.pay_amt.tolist() == [15.0, 3.0]
    assert clean.pay_cnt.tolist() == [3, 1]


# ---------- граф контрагентов ----------

@pytest.fixture
def graph_db(db):
    db.add_all([
        _co("C", okved="41.20", group="g1"),
        _co("S1", okved="24.10", group="g2"),   # внешний поставщик, металлургия
        _co("S2", okved="46.73", group="g1"),   # поставщик из своей группы
        _co("B1", okved="68.20", group="g3"),   # покупатель
        # платежи: клиент платит -> получатель = поставщик
        _pay("C", "S1", 600, 3), _pay("C", "S2", 300), _pay("C", "X_OUT", 400),
        _pay("B1", "C", 500),
        _pay("C", "C", 1000),                    # сам себе: не контрагент
    ])
    db.commit()
    return db


def test_graph_direction_suppliers_are_payment_receivers(graph_db):
    g = counterparty_graph.features(graph_db, "C")
    assert [c.client_id for c in g.top_suppliers] == ["S1", "X_OUT"]
    assert [c.client_id for c in g.top_buyers] == ["B1"]


def test_graph_separates_intragroup_and_unknown(graph_db):
    g = counterparty_graph.features(graph_db, "C")
    assert g.supplier_turnover == 1000                       # только внешние: 600 + 400
    assert g.supplier_intragroup_share == pytest.approx(300 / 1300, abs=1e-4)
    assert g.supplier_unknown_share == pytest.approx(0.4)
    s1 = g.top_suppliers[0]
    assert (s1.okved_code, s1.share, s1.payments) == ("24.10", 0.6, 3)
    assert g.top_suppliers[1].okved_code is None
    assert g.supplier_concentration == pytest.approx(0.6 ** 2 + 0.4 ** 2)
    assert g.group_size == 2


def test_graph_industry_breakdown(graph_db):
    g = counterparty_graph.features(graph_db, "C")
    assert [(i.okved2, i.share, i.examples) for i in g.supplier_industries] == [("24", 0.6, ["name 24.10"])]
    assert [(i.okved2, i.share) for i in g.buyer_industries] == [("68", 1.0)]


def test_graph_without_payments(db):
    db.add(_co("LONELY"))
    db.commit()
    g = counterparty_graph.features(db, "LONELY")
    assert g.top_suppliers == [] and g.supplier_turnover == 0
    assert g.supplier_concentration is None and g.supplier_unknown_share is None


# ---------- профиль компании ----------

@pytest.mark.parametrize(("raw", "expected"), [
    ("CLIENT", "existing"), ("PROSPECT", "potential"), ("CLOSE_CLIENT", "closed"), (None, None),
])
def test_profile_client_type(db, raw, expected):
    db.add(_co("C", cl_type=raw))
    db.commit()
    p = client_profile.build_profile(db, "C", with_graph=False)
    assert p.client_type == expected and p.cl_type == raw


def test_profile_splits_fts_countries(db):
    db.add(_co("C", fts_flag=True, fts_country_name="КИТАЙ, ТУРЦИЯ"))
    db.commit()
    assert client_profile.build_profile(db, "C", with_graph=False).foreign_trade.countries == ["КИТАЙ", "ТУРЦИЯ"]


def test_profile_group_and_industry_position(db):
    db.add_all([
        _co("C", okved="41.20", group="g1", revenue=20e9),
        _co("M", okved="46.71", group="g1", revenue=1e9),
        _co("P1", okved="41.10", group="g2", revenue=5e9),
        _co("P2", okved="41.20", group="g3", revenue=30e9),
        _co("O", okved="46.71", group="g4", revenue=90e9),
    ])
    db.commit()
    p = client_profile.build_profile(db, "C", with_graph=False)
    assert p.large_business is True
    assert (p.group.size, p.group.total_revenue, p.group.large_business) == (2, 21e9, True)
    assert [i.okved2 for i in p.group.top_industries] == ["41", "46"]
    pos = p.industry_position
    assert (pos.okved2, pos.peers, pos.revenue_rank) == ("41", 3, 2)
    assert pos.revenue_share == pytest.approx(20 / 55, abs=1e-4)


def test_profile_missing_company(db):
    assert client_profile.build_profile(db, "NOPE") is None
