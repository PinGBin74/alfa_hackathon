from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import NewsItem, User
from app.db.session import get_db
from app.schemas.news import FeedEntry, NewsItemOut
from app.security.rbac import ensure_client_access, get_current_user
from app.services import client_profile, ranking

router = APIRouter()


@router.get("/{client_id}", response_model=list[FeedEntry])
def personalized_feed(
    client_id: str,
    limit: int = Query(20, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_client_access(user, client_id)
    profile = client_profile.build_profile(db, client_id)
    if profile is None:
        raise HTTPException(404, "Client not found")

    since = datetime.now(UTC) - timedelta(days=get_settings().news_max_age_days)
    candidates = db.query(NewsItem).filter(NewsItem.published_at >= since).limit(500).all()

    entries = []
    for n in candidates:
        s = ranking.score_news(profile, n)  # TODO: передать semantic_sim из векторного поиска
        entries.append(FeedEntry(
            news=NewsItemOut(
                news_id=n.news_id, title=n.title, url=n.url, source=n.source,
                published_at=n.published_at, summary=n.summary, key_facts=n.key_facts or [],
                industries=n.industries or [], regions=n.regions or [], event_type=n.event_type,
            ),
            relevance_score=min(1.0, s.value),
            relevance_reasons=s.reasons,
        ))
    entries.sort(key=lambda e: e.relevance_score, reverse=True)
    return entries[:limit]
