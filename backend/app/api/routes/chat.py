from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent import chat
from app.agent.llm_client import LLMError
from app.db.models import InsightRecord, User
from app.db.session import get_db
from app.schemas.news import ChatAnswer, ChatRequest
from app.security.rbac import ensure_client_access, get_current_user
from app.services.token_budget import BudgetExceeded

router = APIRouter()


@router.post("", response_model=ChatAnswer)
def ask(body: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Уточняющий вопрос к готовому инсайту (критерий 10): другой разрез, детали, первоисточник.

    Короткий агентный цикл (`agent/chat.py`): профиль и граф клиента, поиск по аналитике банка и новостям,
    ответ со ссылками только на найденные источники. Шаги - в трассе `trace_id` ответа.
    """
    rec = db.get(InsightRecord, body.insight_id)
    if rec is None:
        raise HTTPException(404, "Insight not found")
    ensure_client_access(user, rec.client_id)
    try:
        return chat.answer(db, rec, body.question, user.role, body.history)
    except BudgetExceeded:
        raise HTTPException(429, "Daily LLM budget exhausted") from None
    except LLMError:
        raise HTTPException(502, "LLM is unavailable, try again later") from None
