from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMClient, LLMError
from app.db.models import NewsItem, User
from app.db.session import get_db
from app.ingestion import manual
from app.schemas.news import NewsDetail, NewsItemOut, NewsUrlIn
from app.security.rbac import get_current_user
from app.services.token_budget import BudgetExceeded

router = APIRouter()
BODY_PREVIEW_CHARS = 6000


@router.post("", response_model=NewsItemOut)
def add_by_url(body: NewsUrlIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Добавить новость по ссылке: загрузка статьи, дедупликация и разметка тем же конвейером, что у
    планировщика. Уже известная новость (тот же URL, заголовок или перепечатка) возвращается без повторной
    обработки. Инсайт по ней: `POST /api/insights/{client_id}/{news_id}`.

    422 - ссылку обработать нельзя (не http(s), внутренний адрес, нет текста статьи) или новость не про бизнес.
    """
    try:
        item = manual.ingest_url(db, LLMClient(db), body.url)
    except manual.IngestError as e:
        raise HTTPException(422, str(e)) from None
    except BudgetExceeded:
        raise HTTPException(429, "Daily LLM budget exhausted") from None
    except LLMError:
        raise HTTPException(502, "LLM is unavailable, try again later") from None
    return NewsItemOut.from_row(item)


@router.get("/{news_id}", response_model=NewsDetail)
def get_news(news_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Новость с разметкой и началом текста статьи (экран события до и вместе с инсайтом)."""
    n = db.get(NewsItem, news_id)
    if n is None:
        raise HTTPException(404, "News not found")
    return NewsDetail(**NewsItemOut.from_row(n).model_dump(), body=(n.body or "")[:BODY_PREVIEW_CHARS] or None)
