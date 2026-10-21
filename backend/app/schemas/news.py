from datetime import datetime

from pydantic import BaseModel, Field


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


class FeedEntry(BaseModel):
    news: NewsItemOut
    relevance_score: float = Field(ge=0, le=1)
    relevance_reasons: list[str] = Field(default_factory=list, description="Признаки клиента, объясняющие ранг")
    insight_id: str | None = None


class ChatRequest(BaseModel):
    insight_id: str
    question: str


class ChatAnswer(BaseModel):
    answer: str
    source_ids: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class FeedbackIn(BaseModel):
    insight_id: str
    rating: int = Field(ge=-1, le=1)
    comment: str | None = None
