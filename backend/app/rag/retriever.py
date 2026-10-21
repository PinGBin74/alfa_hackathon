"""Поиск по новостям и аналитике банка. Каждый результат несёт ссылку на первоисточник."""
from sqlalchemy.orm import Session

from app.db.models import AnalyticsChunk, AnalyticsDoc, NewsItem
from app.rag import embeddings


def _terms(query: str, n: int = 4) -> list[str]:
    return [w for w in query.lower().split() if len(w) > 4][:n]


def search_news(db: Session, query: str, k: int = 5) -> list[dict]:
    vec = embeddings.embed([query])
    if vec:
        rows = db.query(NewsItem).order_by(NewsItem.embedding.cosine_distance(vec[0])).limit(k).all()
    else:
        q = db.query(NewsItem)
        for t in _terms(query):
            q = q.filter(NewsItem.title.ilike(f"%{t}%"))
        rows = q.order_by(NewsItem.published_at.desc()).limit(k).all()
    return [{"news_id": r.news_id, "title": r.title, "url": r.url, "source": r.source} for r in rows]


def search_bank_analytics(db: Session, query: str, k: int = 4) -> list[dict]:
    vec = embeddings.embed([query])
    q = db.query(AnalyticsChunk, AnalyticsDoc).join(AnalyticsDoc, AnalyticsDoc.doc_id == AnalyticsChunk.doc_id)
    if vec:
        q = q.order_by(AnalyticsChunk.embedding.cosine_distance(vec[0]))
    else:
        for t in _terms(query):
            q = q.filter(AnalyticsChunk.text.ilike(f"%{t}%"))
    return [
        {"doc_id": c.doc_id, "title": d.title, "page": c.page, "text": c.text[:1200]}
        for c, d in q.limit(k).all()
    ]
