"""Pydantic-модели, зеркалят contracts/insight.schema.json."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Fact(BaseModel):
    text: str
    source_id: str


class Statement(BaseModel):
    text: str
    basis: list[str] = Field(default_factory=list)


class WhatHappened(BaseModel):
    summary: str
    confirmed_facts: list[Fact] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class WhyItMatters(BaseModel):
    text: str
    client_features: list[str] = Field(default_factory=list)


class Consequences(BaseModel):
    risks: list[Statement] = Field(default_factory=list)
    opportunities: list[Statement] = Field(default_factory=list)
    factors_to_watch: list[str] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    text: str
    kind: Literal["action", "question", "scenario", "product"] = "action"
    product_code: str | None = None


class BankPosition(BaseModel):
    text: str
    analytics_doc_id: str
    quote_ref: str | None = None


class SourceRef(BaseModel):
    source_id: str
    type: Literal["news", "bank_analytics", "client_data"]
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None


class Verification(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    iterations: int = 1


class Insight(BaseModel):
    insight_id: str
    client_id: str
    user_role: str | None = None
    news_id: str
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    what_happened: WhatHappened
    why_it_matters: list[WhyItMatters]
    consequences: Consequences
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    bank_position: list[BankPosition] = Field(default_factory=list)
    ai_inference: list[Statement] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] | None = None
    verification: Verification | None = None
    trace_id: str | None = None
    generated_at: datetime
