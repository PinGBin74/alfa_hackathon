from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.insight import SourceRef


class FactorOut(BaseModel):
    factor: str
    label: str
    direction: str = "unknown"


class NewsItemOut(BaseModel):
    news_id: str
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str | None = None
    key_facts: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    event_type: str | None = None
    factors: list[FactorOut] = Field(default_factory=list, description="Факторы события из разметки, главный первым")
    countries: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    importance: int | None = Field(None, ge=1, le=5)

    @classmethod
    def from_row(cls, n) -> "NewsItemOut":
        """Из строки таблицы news (списки в БД могут быть NULL); факторы и важность - из полной разметки."""
        from app.ml.news import news_meta
        from app.ml.taxonomy import FACTORS

        meta = news_meta(n)
        return cls(news_id=n.news_id, title=n.title, url=n.url, source=n.source, published_at=n.published_at,
                   summary=n.summary, key_facts=n.key_facts or [], industries=n.industries or [],
                   regions=n.regions or [], event_type=n.event_type,
                   factors=[FactorOut(factor=f.factor, label=FACTORS[f.factor].label, direction=f.direction)
                            for f in meta.factors if f.factor in FACTORS],
                   countries=meta.countries, companies=meta.companies, importance=meta.importance)


class NewsDetail(NewsItemOut):
    body: str | None = Field(None, description="Текст статьи (начало) - для экрана события")


class NewsUrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000, description="Ссылка на статью (http/https)")


class FeedEntry(BaseModel):
    news: NewsItemOut
    relevance_score: float = Field(ge=0, le=1)
    relevance_reasons: list[str] = Field(default_factory=list, description="Признаки клиента, объясняющие ранг")
    relevance_parts: dict[str, float] = Field(default_factory=dict,
                                              description="Компоненты скоринга 0..1: factor, industry, geo, importance, freshness")
    insight_id: str | None = Field(None, description="Готовый инсайт для этой роли, если уже сформирован")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    insight_id: str
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12,
                                    description="Предыдущие вопросы и ответы этого разговора (для уточнений вида «а в рублях?»)")


class ChatAnswer(BaseModel):
    answer: str
    source_ids: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list, description="Описание источников из source_ids")
    trace_id: str | None = None


class FeedbackIn(BaseModel):
    insight_id: str
    rating: int = Field(ge=-1, le=1)
    comment: str | None = None
