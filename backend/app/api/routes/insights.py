from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMError
from app.api.errors import llm_unavailable
from app.db.models import AgentTrace, InsightRecord, User
from app.db.session import get_db
from app.observability.progress import step_view
from app.schemas.insight import Insight
from app.security.rbac import ensure_client_access, get_current_user
from app.services import insight_jobs
from app.services.token_budget import BudgetExceeded

router = APIRouter()


def cached_insight(db: Session, client_id: str, news_id: str, role: str | None) -> InsightRecord | None:
    return (
        db.query(InsightRecord)
        .filter_by(client_id=client_id, news_id=news_id, user_role=role)
        .order_by(InsightRecord.created_at.desc())
        .first()
    )


@router.post("/{client_id}/{news_id}", response_model=Insight)
def get_or_create_insight(
    client_id: str, news_id: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Инсайт по новости для клиента и роли пользователя. Кэш: готовый инсайт для (клиент, новость, роль)
    отдаётся сразу (экономия токенов); иначе запускается агент (1-1,5 мин), ход - в `.../progress`.

    404 - нет клиента или новости, 429 - исчерпан дневной бюджет LLM, 502 - модели недоступны,
    503 - модели не настроены (нет LLM_API_KEY)."""
    ensure_client_access(user, client_id)
    cached = cached_insight(db, client_id, news_id, user.role)
    if cached:
        return Insight.model_validate(cached.payload)
    try:
        return insight_jobs.generate(db, client_id, news_id, user.role)
    except BudgetExceeded:
        raise HTTPException(429, "Daily LLM budget exhausted") from None
    except LookupError:
        raise HTTPException(404, "Client or news not found") from None
    except LLMError as e:
        raise llm_unavailable(e) from None
    except TimeoutError:
        raise HTTPException(504, "Insight generation is taking too long, try again later") from None


@router.get("/{client_id}/{news_id}/progress")
def progress(client_id: str, news_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ход генерации: шаги агента, записанные в трассу к этому моменту (план, инструменты, модели, проверка).
    status: running - агент работает; ready - инсайт уже есть (insight_id); idle - не запускался."""
    ensure_client_access(user, client_id)
    job = insight_jobs.running(client_id, news_id, user.role)
    if job is None:
        cached = cached_insight(db, client_id, news_id, user.role)
        return {"status": "ready" if cached else "idle", "insight_id": cached.insight_id if cached else None,
                "trace_id": cached.trace_id if cached else None, "steps": []}
    steps = db.query(AgentTrace).filter_by(trace_id=job.trace_id).order_by(AgentTrace.step).all()
    return {"status": "running", "insight_id": None, "trace_id": job.trace_id,
            "steps": [{k: v for k, v in step_view(s).items() if k not in ("input", "output")} for s in steps]}


@router.get("/{insight_id}", response_model=Insight)
def get_insight(insight_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.get(InsightRecord, insight_id)
    if rec is None:
        raise HTTPException(404, "Insight not found")
    ensure_client_access(user, rec.client_id)
    return Insight.model_validate(rec.payload)


@router.get("/{insight_id}/trace")
def get_trace(insight_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Трасса агента (критерий 12): каждый шаг - что сделано (title/detail), модель, время, токены и сырые
    вход/выход: какие инструменты и источники использованы, какие признаки клиента повлияли на вывод."""
    rec = db.get(InsightRecord, insight_id)
    if rec is None:
        raise HTTPException(404, "Insight not found")
    ensure_client_access(user, rec.client_id)
    steps = db.query(AgentTrace).filter_by(trace_id=rec.trace_id).order_by(AgentTrace.step).all()
    return [step_view(s) for s in steps]
