"""Таксономия: сопоставление ОКВЭД, чувствительность клиента к факторам, роли, продукты."""
import pytest

from app.ml import taxonomy
from app.schemas.client import ClientProfile, ForeignTrade, GraphFeatures, IndustryShare, Products


@pytest.mark.parametrize(("code", "prefixes", "ok"), [
    ("46.71.2", ("46",), True), ("46.71.2", ("46.7",), True), ("46.71.2", ("46.71",), True),
    ("46.71.2", ("46.2",), False), ("41.20", ("4",), True), ("24.41", ("24.4",), True),
    ("41.2", ("41.20",), False), (None, ("41",), False),
])
def test_okved_matches(code, prefixes, ok):
    assert taxonomy.okved_matches(code, prefixes) is ok


def test_every_factor_has_rule():
    assert set(taxonomy.RULES) == set(taxonomy.FACTORS)


def test_borrower_is_sensitive_to_key_rate():
    p = ClientProfile(client_id="c", okved_code="42.99", products=Products(loans=True, leasing=True))
    e = taxonomy.exposures(p)["key_rate"]
    assert e.weight >= 0.8
    assert {r.feature for r in e.reasons} == {"CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK", "MAINOKVED_CODE"}


def test_no_loans_no_key_rate_exposure_from_products():
    e = taxonomy.exposures(ClientProfile(client_id="c", okved_code="62.01"))["key_rate"]
    assert e.weight == 0 and e.reasons == []


def test_counterparty_industry_drives_metals_exposure():
    p = ClientProfile(client_id="c", okved_code="62.01", graph=GraphFeatures(
        supplier_industries=[IndustryShare(okved2="24", share=0.3), IndustryShare(okved2="46", share=0.5)]))
    e = taxonomy.exposures(p)["metals"]
    assert e.weight == pytest.approx(0.3)
    assert e.reasons[0].feature == "graph.supplier_industries"


def test_narrow_sector_codes_do_not_match_whole_class():
    """«46.71 опт топливом» в секторах нефти не должен засчитывать весь опт у контрагентов."""
    p = ClientProfile(client_id="c", okved_code="62.01", graph=GraphFeatures(
        supplier_industries=[IndustryShare(okved2="46", share=0.9)]))
    assert taxonomy.exposures(p)["oil_gas"].weight == 0


def test_fx_exposure_names_countries():
    p = ClientProfile(client_id="c", foreign_trade=ForeignTrade(fts_flag=True, countries=["КИТАЙ"]))
    e = taxonomy.exposures(p)["fx"]
    assert e.weight == 0.5 and "КИТАЙ" in e.reasons[0].text


def test_role_weights():
    assert taxonomy.role_weight("treasurer", "fx") > 1 > taxonomy.role_weight("treasurer", "labor")
    assert taxonomy.role_weight(None, "fx") == taxonomy.role_weight("unknown", "fx") == 1.0


def test_product_hints():
    p = ClientProfile(client_id="c", foreign_trade=ForeignTrade(fts_flag=True),
                      graph=GraphFeatures(buyer_concentration=0.4))
    codes = {h.code for h in taxonomy.product_hints(p, ["fx", "key_rate"])}
    assert codes == {"fx_hedge", "factoring", "deposit"}


@pytest.mark.parametrize(("code", "expected"), [
    ("46.72", {"46", "24", "07"}), ("46.21", {"46", "01"}), ("46.34", {"46", "11"}), ("42.99", {"42"}), (None, set()),
])
def test_client_industry_classes_maps_trade_to_product(code, expected):
    assert set(taxonomy.client_industry_classes(code)) == expected
