"""Общий контекст агента: результаты шагов хранятся здесь и переиспользуются."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    client_id: str
    news_id: str
    user_role: str | None = None
    plan: list[dict] = field(default_factory=list)
    focus_factors: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    profile: dict | None = None
    graph: dict | None = None
    news: dict | None = None
    related_news: list[dict] = field(default_factory=list)
    bank_chunks: list[dict] = field(default_factory=list)
    draft: dict | None = None
    verification: dict | None = None
    iterations: int = 0
    feedback: list[str] = field(default_factory=list)
    scratch: dict[str, Any] = field(default_factory=dict)

    def source_ids(self) -> set[str]:
        ids = {f"client:{self.client_id}"}
        if self.news:
            ids.add(f"news:{self.news.get('news_id')}")
        ids |= {f"news:{n['news_id']}" for n in self.related_news}
        ids |= {f"bank:{c['doc_id']}:{c.get('page')}" for c in self.bank_chunks}
        return ids

    def add_bank(self, items: list[dict]) -> int:
        """Добавляет найденные материалы банка без дублей (документ + страница + позиция)."""
        seen = {(c["doc_id"], c.get("page"), c.get("position_id")) for c in self.bank_chunks}
        added = 0
        for it in items or []:
            key = (it["doc_id"], it.get("page"), it.get("position_id"))
            if key not in seen:
                self.bank_chunks.append(it)
                seen.add(key)
                added += 1
        return added

    def add_related(self, items: list[dict]) -> int:
        seen = {n["news_id"] for n in self.related_news} | {self.news_id}
        added = 0
        for it in items or []:
            if it["news_id"] not in seen:
                self.related_news.append(it)
                seen.add(it["news_id"])
                added += 1
        return added
