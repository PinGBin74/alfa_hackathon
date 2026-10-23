"""Ранжирование: персонализация по признакам клиента, контрагентам, роли и географии."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.schemas.client import ClientProfile, ForeignTrade, GraphFeatures, IndustryShare, Products
from app.services import ranking


def _news(factors=(), industries=(), countries=(), regions=(), importance=3, relevant=True, age_days=0):
    return SimpleNamespace(
        ml_meta={"summary": "s", "factors": [{"factor": f} for f in factors], "industries": list(industries),
                 "countries": list(countries), "regions": list(regions), "importance": importance,
                 "is_business_relevant": relevant},
        published_at=datetime.now(UTC) - timedelta(days=age_days),
    )


BORROWER = ClientProfile(client_id="b", okved_code="42.99", products=Products(loans=True, leasing=True))
IT_FIRM = ClientProfile(client_id="it", okved_code="62.01")
METAL_BUYER = ClientProfile(client_id="m", okved_code="41.20", graph=GraphFeatures(
    supplier_industries=[IndustryShare(okved2="24", share=0.35)]))
IMPORTER = ClientProfile(client_id="imp", okved_code="46.90", foreign_trade=ForeignTrade(fts_flag=True, countries=["КИТАЙ"]))


def test_key_rate_news_matters_more_to_borrower():
    n = _news(["key_rate"], importance=5)
    assert ranking.score_news(BORROWER, n).value > ranking.score_news(IT_FIRM, n).value + 0.2


def test_counterparty_industry_lifts_news():
    n = _news(["metals"], industries=["24"])
    s = ranking.score_news(METAL_BUYER, n)
    assert s.parts["industry"] > 0 and s.parts["factor"] > 0
    assert any("graph.supplier_industries" in r for r in s.reasons)
    assert s.value > ranking.score_news(IT_FIRM, n).value


def test_fts_country_match():
    s = ranking.score_news(IMPORTER, _news(["sanctions_trade"], countries=["Китай"]))
    assert s.parts["geo"] == 1.0 and any("КИТАЙ" in r for r in s.reasons)


def test_role_changes_priority():
    n = _news(["fx"])
    assert ranking.score_news(IMPORTER, n, role="treasurer").value > ranking.score_news(IMPORTER, n, role="ceo").value


def test_irrelevant_and_old_news_sink():
    fresh = ranking.score_news(BORROWER, _news(["key_rate"]))
    assert ranking.score_news(BORROWER, _news(["key_rate"], relevant=False)).value < fresh.value * 0.5
    assert ranking.score_news(BORROWER, _news(["key_rate"], age_days=30)).value < fresh.value


def test_same_feed_differs_between_clients():
    feed = {"rate": _news(["key_rate"], importance=4), "steel": _news(["metals"], industries=["24"], importance=4),
            "china": _news(["sanctions_trade", "fx"], countries=["Китай"], importance=4)}
    def top(p):
        return max(feed, key=lambda k: ranking.score_news(p, feed[k]).value)
    assert {top(BORROWER), top(METAL_BUYER), top(IMPORTER)} == {"rate", "steel", "china"}


@pytest.mark.parametrize("p", [BORROWER, IT_FIRM, METAL_BUYER, IMPORTER])
def test_score_bounds(p):
    s = ranking.score_news(p, _news(["key_rate", "fx", "inflation", "metals"], industries=["24", "42"], importance=5))
    assert 0 <= s.value <= 1 and len(s.reasons) <= 6


METAL_TRADER = ClientProfile(client_id="mt", okved_code="46.72", foreign_trade=ForeignTrade(fts_flag=True, countries=["ГРУЗИЯ"]))
GRAIN_TRADER = ClientProfile(client_id="gt", okved_code="46.21", foreign_trade=ForeignTrade(fts_flag=True, countries=["АЛЖИР"]))


def test_trade_product_beats_broad_wholesale_class():
    grain_duty = _news(["agri", "sanctions_trade"], industries=["01", "46"], countries=["Алжир"])
    grain = ranking.score_news(GRAIN_TRADER, grain_duty)
    metal = ranking.score_news(METAL_TRADER, grain_duty)
    assert grain.parts["industry"] == 1.0 and metal.parts["industry"] == 0.0
    assert grain.value > metal.value + 0.3


def test_targeted_trade_measure_needs_country_or_industry_match():
    china_duty = _news(["sanctions_trade"], industries=["29"], countries=["Китай"])
    assert ranking.score_news(METAL_TRADER, china_duty).parts["factor"] < ranking.score_news(IMPORTER, china_duty).parts["factor"]


# ---------- поправки против ложных совпадений ----------

STEEL_TRADER = ClientProfile(client_id="st", okved_code="24.10")


def test_news_about_many_industries_is_a_weak_industry_match():
    focused = ranking.score_news(STEEL_TRADER, _news(["metals"], industries=["24"]))
    broad = ranking.score_news(STEEL_TRADER, _news(["metals"], industries=["06", "19", "20", "24", "28", "35"]))
    assert focused.parts["industry"] == 1.0
    assert broad.parts["industry"] == pytest.approx(ranking.INDUSTRY_FOCUS / 6, abs=1e-3)
    assert broad.value < focused.value


def test_macro_news_industry_tags_are_background():
    s = ranking.score_news(STEEL_TRADER, _news(["key_rate", "metals"], industries=["24"]))
    assert s.parts["industry"] == pytest.approx(ranking.MACRO_INDUSTRY_SCALE, abs=1e-3)


def test_fts_country_in_a_long_list_counts_less():
    passing = ranking.score_news(IMPORTER, _news(["logistics"], countries=["Китай", "ОАЭ", "Турция", "Грузия", "Египет", "Армения"]))
    assert passing.parts["geo"] == pytest.approx(ranking.COUNTRY_FOCUS / 6, abs=1e-3)
    assert any("КИТАЙ" in r for r in passing.reasons)   # причина остаётся, вклад меньше


def test_minor_event_does_not_outrank_rate_decision_for_borrower():
    minor = _news(["key_rate", "consumption"], importance=1)
    decision = _news(["key_rate"], importance=5)
    assert ranking.score_news(BORROWER, decision).value > ranking.score_news(BORROWER, minor).value * 1.5
