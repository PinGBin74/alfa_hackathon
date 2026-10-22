"""Инструменты агента. Каждый вызов проходит через allowlist и пишется в трассу."""
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.models import NewsItem
from app.observability.tracing import Tracer
from app.rag import retriever
from app.security import tool_allowlist
from app.services import client_profile, counterparty_graph


def get_client_profile(db: Session, client_id: str, **_) -> dict:
    p = client_profile.build_profile(db, client_id, with_graph=False)
    return p.model_dump() if p else {}


def get_counterparty_graph(db: Session, client_id: str, **_) -> dict:
    return counterparty_graph.features(db, client_id).model_dump()


def get_news_item(db: Session, news_id: str, **_) -> dict:
    n = db.get(NewsItem, news_id)
    if not n:
        return {}
    return {
        "news_id": n.news_id, "title": n.title, "url": n.url, "source": n.source,
        "published_at": n.published_at.isoformat(), "body": n.body, "summary": n.summary,
        "key_facts": n.key_facts or [], "industries": n.industries or [],
        "regions": n.regions or [], "event_type": n.event_type,
    }


def search_news(db: Session, query: str, k: int = 5, **_) -> list[dict]:
    return retriever.search_news(db, query, k)


def search_bank_analytics(db: Session, query: str, k: int = 4, factors: list[str] | None = None, **_) -> list[dict]:
    return retriever.search_bank_analytics(db, query, k, factors=factors)


TOOLS: dict[str, Callable] = {
    "get_client_profile": get_client_profile,
    "get_counterparty_graph": get_counterparty_graph,
    "get_news_item": get_news_item,
    "search_news": search_news,
    "search_bank_analytics": search_bank_analytics,
}


def call_tool(db: Session, tracer: Tracer, name: str, **kwargs):
    tool_allowlist.check(name)
    with tracer.span("tool_call", name, input=kwargs) as span:
        result = TOOLS[name](db, **kwargs)
        span["output"] = {"result_preview": str(result)[:1000]}
    return result
