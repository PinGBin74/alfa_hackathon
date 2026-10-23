from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import InsightRecord, User
from app.db.session import get_db
from app.schemas.news import FeedEntry, NewsItemOut
from app.security.rbac import ensure_client_access, get_current_user
from app.services import client_profile, feed

router = APIRouter()


@router.get("/{client_id}", response_model=list[FeedEntry])
def personalized_feed(
    client_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Персональная лента: новости за news_max_age_days, отсортированные по скорингу клиент x новость x роль
    (`services/ranking.py`), с причинами ранга (признаки клиента) и ссылкой на готовый инсайт, если он есть."""
    ensure_client_access(user, client_id)
    profile = client_profile.build_profile(db, client_id)
    if profile is None:
        raise HTTPException(404, "Client not found")
    entries = [
        FeedEntry(news=NewsItemOut.from_row(n), relevance_score=min(1.0, s.value), relevance_reasons=s.reasons,
                  relevance_parts={k: v for k, v in s.parts.items() if k != "semantic"})
        for n, s in feed.ranked(db, profile, user.role, limit)
    ]
    ready = dict(
        db.query(InsightRecord.news_id, InsightRecord.insight_id)
        .filter(InsightRecord.client_id == client_id, InsightRecord.user_role == user.role,
                InsightRecord.news_id.in_([e.news.news_id for e in entries]))
        .order_by(InsightRecord.created_at)  # последний инсайт перезаписывает более ранние
        .all()
    )
    for e in entries:
        e.insight_id = ready.get(e.news.news_id)
    return entries
