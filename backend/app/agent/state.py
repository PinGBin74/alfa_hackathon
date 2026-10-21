"""Общий контекст агента: результаты шагов хранятся здесь и переиспользуются."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    client_id: str
    news_id: str
    user_role: str | None = None
    plan: list[dict] = field(default_factory=list)
    profile: dict | None = None
    graph: dict | None = None
    news: dict | None = None
    related_news: list[dict] = field(default_factory=list)
    bank_chunks: list[dict] = field(default_factory=list)
    draft: dict | None = None
    verification: dict | None = None
    iterations: int = 0
    scratch: dict[str, Any] = field(default_factory=dict)

    def source_ids(self) -> set[str]:
        ids = {f"client:{self.client_id}"}
        if self.news:
            ids.add(f"news:{self.news.get('news_id')}")
        ids |= {f"news:{n['news_id']}" for n in self.related_news}
        ids |= {f"bank:{c['doc_id']}:{c.get('page')}" for c in self.bank_chunks}
        return ids
