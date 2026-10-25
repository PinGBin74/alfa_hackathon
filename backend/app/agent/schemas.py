"""Структурированные форматы обмена между шагами агента (JSON по схеме, рекомендация кейса)."""
from typing import Literal

from pydantic import BaseModel, Field

from app.ml.news import FactorCode
from app.schemas.insight import (
    BankPosition,
    Consequences,
    Statement,
    SuggestedAction,
    WhatHappened,
    WhyItMatters,
)

PlannableTool = Literal["get_counterparty_graph", "search_bank_analytics", "search_news"]


class PlanStep(BaseModel):
    tool: PlannableTool
    why: str = Field(description="Зачем этот шаг для вывода о клиенте")
    query: str | None = Field(None, description="Поисковый запрос для search_* (по-русски, 2-6 слов)")
    factors: list[FactorCode] = Field(default_factory=list, description="Факторы для search_bank_analytics")


class Plan(BaseModel):
    focus_factors: list[FactorCode] = Field(default_factory=list, description="Факторы, через которые событие касается клиента")
    hypotheses: list[str] = Field(default_factory=list, description="До 3 гипотез: как событие может повлиять на этого клиента")
    steps: list[PlanStep] = Field(default_factory=list)


class DraftInsight(BaseModel):
    """Черновик интерпретации: ответы на 6 вопросов кейса с разделением факт / банк / AI."""

    what_happened: WhatHappened
    why_it_matters: list[WhyItMatters]
    consequences: Consequences
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    bank_position: list[BankPosition] = Field(default_factory=list)
    ai_inference: list[Statement] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


IssueType = Literal["unsupported_fact", "wrong_number", "wrong_date", "contradiction", "generic", "restates_news",
                    "wrong_bank_attribution", "stale_bank_view", "missing_bank_view", "unknown_source", "other"]


class Issue(BaseModel):
    type: IssueType
    field: str = Field(description="Где проблема, например why_it_matters[1]")
    text: str
    fix: str | None = Field(None, description="Как исправить")
    blocking: bool = True


class Verdict(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    overall: Literal["pass", "revise"] = "pass"


class ChatReply(BaseModel):
    answer: str
    source_ids: list[str] = Field(default_factory=list)
