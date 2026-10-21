"""Скоринг «новость <-> профиль клиента».

Гибрид: правила по признакам (отрасль, регион, продукты, ВЭД) + семантическая
близость (векторный поиск) + свежесть. Веса - в одном месте, чтобы их можно
было подбирать вместе с ML-инженером и проверять в eval/.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.db.models import NewsItem
from app.schemas.client import ClientProfile

WEIGHTS = {
    "industry": 0.30,
    "region": 0.10,
    "product_link": 0.20,   # напр. новость о ставке и у клиента есть кредиты
    "foreign_trade": 0.10,
    "semantic": 0.20,
    "freshness": 0.10,
}

# Тип события -> признак продукта клиента, к которому оно «цепляется»
EVENT_PRODUCT_LINK = {
    "key_rate": ["loans", "leasing", "deposits"],
    "fx_rate": ["foreign_trade"],
    "sanctions": ["foreign_trade"],
    "commodities": [],
}


@dataclass
class Score:
    value: float
    reasons: list[str] = field(default_factory=list)


def score_news(profile: ClientProfile, news: NewsItem, semantic_sim: float = 0.0) -> Score:
    reasons: list[str] = []
    parts: dict[str, float] = {}

    # Отрасль: пересечение по префиксу ОКВЭД. TODO: словарь отраслей и зависимостей между ними
    industries = news.industries or []
    okved = profile.okved_code or ""
    ind_hit = any(okved.startswith(str(i)) for i in industries if i) if okved else False
    parts["industry"] = 1.0 if ind_hit else 0.0
    if ind_hit:
        reasons.append(f"MAINOKVED_CODE={okved}")

    regions = news.regions or []
    reg_hit = bool(profile.region and profile.region in regions)
    parts["region"] = 1.0 if reg_hit else 0.0
    if reg_hit:
        reasons.append(f"REGION={profile.region}")

    link_hit = False
    for feat in EVENT_PRODUCT_LINK.get(news.event_type or "", []):
        if feat == "foreign_trade":
            if profile.foreign_trade.fts_flag:
                link_hit = True
                reasons.append("FTS_FLAG=1")
        elif getattr(profile.products, feat, False):
            link_hit = True
            reasons.append(f"product:{feat}")
    parts["product_link"] = 1.0 if link_hit else 0.0
    parts["foreign_trade"] = 1.0 if (profile.foreign_trade.fts_flag and news.event_type in {"fx_rate", "sanctions"}) else 0.0

    parts["semantic"] = max(0.0, min(1.0, semantic_sim))

    age_days = (datetime.now(UTC) - news.published_at).total_seconds() / 86400
    parts["freshness"] = max(0.0, 1.0 - age_days / 14)

    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return Score(value=round(total, 4), reasons=reasons)
