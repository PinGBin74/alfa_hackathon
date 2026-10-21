from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import InsightRecord, User
from app.db.session import get_db
from app.schemas.news import ChatAnswer, ChatRequest
from app.security.rbac import ensure_client_access, get_current_user

router = APIRouter()


@router.post("", response_model=ChatAnswer)
def ask(body: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Уточняющий вопрос к готовому инсайту (критерий 10).

    TODO: запустить короткий агентный цикл с контекстом инсайта и инструментами поиска;
    ответ должен ссылаться на источники и сохранять трассу.
    """
    rec = db.get(InsightRecord, body.insight_id)
    if rec is None:
        raise HTTPException(404, "Insight not found")
    ensure_client_access(user, rec.client_id)
    return ChatAnswer(answer="TODO: ответ агента на уточняющий вопрос", source_ids=[], trace_id=rec.trace_id)
