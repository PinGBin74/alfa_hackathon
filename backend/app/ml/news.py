"""Контракт размеченной новости: выход классификатора и вход ранжирования/агента.

Хранение: колонки news (summary, key_facts, industries, regions, event_type) заполняются из `columns()`,
полная разметка (`meta()`: факторы с направлением, страны, участники, важность) - в JSON-колонку
news.ml_meta. Для новостей, записанных до её появления, `news_meta()` восстанавливает разметку из колонок
(основной фактор - event_type).
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.ml.taxonomy import FACTOR_CODES, OKVED2_CLASSES

FactorCode = Literal[FACTOR_CODES]  # type: ignore[valid-type]
Direction = Literal["up", "down", "unchanged", "mixed", "unknown"]


def _cut(n: int):
    def validator(v):
        return list(v)[:n] if isinstance(v, list | tuple) else v
    return validator


class FactorTag(BaseModel):
    factor: FactorCode
    direction: Direction = Field("unknown", description="Как изменился фактор: ставка выросла = up")
    evidence: str | None = Field(None, description="Фраза из текста новости, на которой основан тег")


class NewsClassification(BaseModel):
    is_business_relevant: bool = Field(True, description="Есть ли последствия для бизнеса (не спорт, не происшествия)")
    summary: str = Field(description="1-2 предложения: только то, что написано в тексте, без оценок")
    key_facts: list[str] = Field(default_factory=list, description="До 6 фактов с цифрами и датами как в тексте")
    factors: list[FactorTag] = Field(default_factory=list, description="До 4 факторов, главный первым")
    industries: list[str] = Field(default_factory=list, description="Классы ОКВЭД2 (2 цифры), которых касается событие")
    regions: list[str] = Field(default_factory=list, description="Регионы РФ из текста")
    countries: list[str] = Field(default_factory=list, description="Страны из текста, кроме России")
    companies: list[str] = Field(default_factory=list, description="Названные в тексте компании и ведомства")
    importance: int = Field(3, ge=1, le=5, description="5 - меняет условия для многих компаний")

    _cut_facts = field_validator("key_facts", mode="before")(_cut(6))
    _cut_factors = field_validator("factors", mode="before")(_cut(4))

    @field_validator("industries", mode="before")
    @classmethod
    def _okved2(cls, v):
        out: list[str] = []
        for code in v or []:
            c = str(code).strip().split(".")[0].zfill(2)
            if c in OKVED2_CLASSES and c not in out:
                out.append(c)
        return out[:6]

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v):
        return (v or "").strip()[:600]

    @property
    def factor_codes(self) -> list[str]:
        return [f.factor for f in self.factors]

    def columns(self) -> dict:
        """Поля для существующих колонок таблицы news."""
        return {
            "summary": self.summary,
            "key_facts": self.key_facts,
            "industries": self.industries,
            "regions": self.regions,
            "event_type": self.factors[0].factor if self.factors else None,
        }

    def meta(self) -> dict:
        return self.model_dump(mode="json")


def news_meta(news) -> NewsClassification:
    """Разметка из ORM-объекта news: ml_meta, если заполнена, иначе - из колонок."""
    raw = getattr(news, "ml_meta", None)
    if raw:
        return NewsClassification.model_validate(raw)
    factors = [{"factor": news.event_type}] if getattr(news, "event_type", None) in FACTOR_CODES else []
    return NewsClassification(
        summary=getattr(news, "summary", None) or "",
        key_facts=getattr(news, "key_facts", None) or [],
        factors=factors,
        industries=getattr(news, "industries", None) or [],
        regions=getattr(news, "regions", None) or [],
    )
