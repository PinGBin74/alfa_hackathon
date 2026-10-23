"""Персональная лента: новости за news_max_age_days, отсортированные по скорингу клиент x новость x роль.

Общая для API (`GET /api/feed/{client_id}`) и прогрева разборов (`app.agent.warmup`)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import NewsItem
from app.schemas.client import ClientProfile
from app.services import ranking

CANDIDATES = 500


def ranked(db: Session, profile: ClientProfile, role: str | None, limit: int) -> list[tuple[NewsItem, ranking.Score]]:
    since = datetime.now(UTC) - timedelta(days=get_settings().news_max_age_days)
    candidates = (db.query(NewsItem).filter(NewsItem.published_at >= since)
                  .order_by(NewsItem.published_at.desc()).limit(CANDIDATES).all())
    # роль меняет приоритеты факторов (taxonomy.ROLE_WEIGHTS) - так же, как в инсайте;
    # semantic_sim не передаётся: разрешённой эмбеддинг-модели нет (docs/ml.md, раздел 3)
    scored = [(n, ranking.score_news(profile, n, role=role)) for n in candidates]
    scored.sort(key=lambda x: x[1].value, reverse=True)
    return scored[:limit]
