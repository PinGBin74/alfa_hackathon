"""Скоринг «новость <-> клиент (+ роль пользователя)».

Компоненты (веса - в одном месте, подбираются по eval/):
- factor: чувствительность клиента к факторам новости (`taxonomy.exposures`) с учётом роли пользователя;
- industry: новость про отрасль клиента, его группы или его контрагентов по платежам;
- geo: регион клиента или страны его ВЭД упомянуты в новости;
- importance: важность события по разметке (1..5);
- freshness: свежесть;
- semantic: близость текста (пока 0: разрешённой эмбеддинг-модели нет).
Каждая сработавшая компонента даёт причину с признаком клиента - её видит пользователь и агент.

Поправки против ложных совпадений (подобраны на eval-наборе real, проверены на отложенном holdout -
docs/ml.md, раздел 6): совпадение отрасли слабее, если новость перечисляет много отраслей или её главный
фактор - макроэкономический (решение ЦБ «про банки» - не новость отрасли 64 для клиента); страна ВЭД,
названная в длинном списке стран, - слабее; итог умножается на множитель важности события (0,5..1), чтобы
мелкое событие по признакам клиента не обгоняло решение, меняющее условия для всех.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ml import taxonomy
from app.ml.news import news_meta
from app.schemas.client import ClientProfile
from app.services.counterparty_graph import okved2

WEIGHTS = {
    "factor": 0.40,
    "industry": 0.25,
    "geo": 0.10,
    "importance": 0.15,
    "freshness": 0.10,
    "semantic": 0.0,
}
FACTOR_POSITION = (1.0, 0.6, 0.45, 0.35)   # главный фактор новости важнее второстепенных
IRRELEVANT_PENALTY = 0.3                  # новость без последствий для бизнеса
MAX_AGE_DAYS = 14
BROAD_CLASS_MATCH = 0.35                  # «новость про опт» для оптовика другим товаром - слабый сигнал
# Меры, которые бьют по конкретным товарам, странам и отраслям: без совпадения страны или отрасли
# общая чувствительность (например, «есть ВЭД») учитывается частично.
TARGETED_FACTORS = {"sanctions_trade", "regulation", "company_event"}
UNTARGETED_SCALE = 0.4
INDUSTRY_FOCUS = 2        # новость о большем числе отраслей - совпадение ослабляется пропорционально
MACRO_FACTORS = {"key_rate", "inflation", "fx", "bonds", "labor", "gdp_growth", "taxes", "gold"}
MACRO_INDUSTRY_SCALE = 0.4  # главный фактор макро: отрасли в разметке - фон, а не предмет новости
COUNTRY_FOCUS = 3         # страна ВЭД в списке из большего числа стран - упоминание, а не событие в стране
IMPORTANCE_FLOOR = 0.5    # множитель важности: 0,5 при важности 1, 1,0 при важности 5


@dataclass
class Detail:
    component: str
    feature: str
    text: str
    contribution: float


@dataclass
class Score:
    value: float
    reasons: list[str] = field(default_factory=list)
    details: list[Detail] = field(default_factory=list)
    parts: dict[str, float] = field(default_factory=dict)


def _factor_part(profile: ClientProfile, factors: list[str], role: str | None, details: list[Detail],
                 targeted_hit: bool) -> float:
    exp = taxonomy.exposures(profile)
    contrib: list[float] = []
    for i, code in enumerate(factors[: len(FACTOR_POSITION)]):
        e = exp[code]
        c = e.weight * taxonomy.role_weight(role, code) * FACTOR_POSITION[i]
        if code in TARGETED_FACTORS and not targeted_hit:
            c *= UNTARGETED_SCALE
        contrib.append(c)
        label = taxonomy.FACTORS[code].label
        for r in e.reasons:
            details.append(Detail("factor", r.feature, f"{label}: {r.text}", round(c, 3)))
    if not contrib:
        return 0.0
    best = max(contrib)
    return min(1.0, best + 0.3 * (sum(contrib) - best))


def _industry_part(profile: ClientProfile, industries: list[str], details: list[Detail]) -> float:
    if not industries:
        return 0.0
    names = ", ".join(f"{c} {taxonomy.OKVED2_CLASSES.get(c, '')}".strip() for c in industries)
    own = okved2(profile.okved_code)
    classes = taxonomy.client_industry_classes(profile.okved_code)
    for cls, why in classes.items():
        if cls in industries and not (cls == own and own in taxonomy.BROAD_CLASSES):
            details.append(Detail("industry", "MAINOKVED_CODE", f"новость касается отрасли клиента: {why} ({names})", 1.0))
            return 1.0
    best = 0.0
    specific = [c for c in industries if c not in taxonomy.BROAD_CLASSES]
    if own in industries and not specific:  # новость о торговле в целом, без конкретного товара
        best = BROAD_CLASS_MATCH
        details.append(Detail("industry", "MAINOKVED_CODE", f"новость о классе {own} {taxonomy.OKVED2_CLASSES.get(own, '')} в целом", best))
    # Группа и контрагенты: только конкретные отрасли - доля оборота «в опте вообще» не говорит о товаре.
    if profile.group and specific:
        share = sum(i.share for i in profile.group.top_industries if i.okved2 in specific)
        if share >= 0.1:
            best = max(best, 0.6 * min(1.0, share * 2))
            details.append(Detail("industry", "GROUP_ID", f"{share:.0%} выручки группы компаний - в отраслях новости ({names})", best))
    g = profile.graph
    for side, label in (("supplier", "закупок у поставщиков"), ("buyer", "поступлений от покупателей")):
        share = sum(i.share for i in getattr(g, f"{side}_industries") if i.okved2 in specific)
        if share >= 0.03:
            part = 0.8 * min(1.0, share * 2)
            best = max(best, part)
            details.append(Detail("industry", f"graph.{side}_industries", f"{share:.0%} {label} приходится на отрасли новости ({names})", part))
    return best


def _geo_part(profile: ClientProfile, regions: list[str], countries: list[str], details: list[Detail]) -> float:
    part = 0.0
    if profile.region and any(profile.region.lower() in r.lower() or r.lower() in profile.region.lower() for r in regions):
        part = 0.6
        details.append(Detail("geo", "REGION", f"событие в регионе регистрации клиента ({profile.region})", part))
    hits = sorted({c for c in profile.foreign_trade.countries for n in countries if c.lower() == n.lower()})
    if hits:
        part = 1.0
        details.append(Detail("geo", "FTS_COUNTRY_NAME", f"страна внешнеторговых контрактов клиента: {', '.join(hits)}", part))
    return part


def _scaled(details: list[Detail], start: int, value: float, scale: float) -> float:
    """Ослабляет компоненту и вклад её причин (порядок причин следует за вкладом)."""
    if scale < 1:
        for d in details[start:]:
            d.contribution = round(d.contribution * scale, 3)
    return value * scale


def score_news(profile: ClientProfile, news, semantic_sim: float = 0.0, role: str | None = None) -> Score:
    meta = news_meta(news)
    details: list[Detail] = []
    start = len(details)
    industry = _industry_part(profile, meta.industries, details)
    scale = min(1.0, INDUSTRY_FOCUS / len(meta.industries)) if meta.industries else 1.0
    if meta.factor_codes and meta.factor_codes[0] in MACRO_FACTORS:
        scale *= MACRO_INDUSTRY_SCALE
    industry = _scaled(details, start, industry, scale)
    start = len(details)
    geo = _geo_part(profile, meta.regions, meta.countries, details)
    if geo >= 1.0 and len(meta.countries) > COUNTRY_FOCUS:  # совпала страна ВЭД, но в длинном списке
        geo = _scaled(details, start, geo, COUNTRY_FOCUS / len(meta.countries))
    targeted_hit = industry >= 0.5 or geo >= 1.0 or not (meta.industries or meta.countries)
    parts = {
        "factor": _factor_part(profile, meta.factor_codes, role, details, targeted_hit),
        "industry": industry,
        "geo": geo,
        "importance": (meta.importance - 1) / 4,
        "semantic": max(0.0, min(1.0, semantic_sim)),
    }
    published = getattr(news, "published_at", None)
    if published is not None and published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - published).total_seconds() / 86400 if published else MAX_AGE_DAYS
    parts["freshness"] = max(0.0, 1.0 - age_days / MAX_AGE_DAYS)

    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    total *= IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR) * parts["importance"]
    if not meta.is_business_relevant:
        total *= IRRELEVANT_PENALTY
    details.sort(key=lambda d: d.contribution, reverse=True)
    reasons = list(dict.fromkeys(f"{d.text} [{d.feature}]" for d in details))
    return Score(value=round(min(1.0, total), 4), reasons=reasons[:6], details=details,
                 parts={k: round(v, 3) for k, v in parts.items()})
