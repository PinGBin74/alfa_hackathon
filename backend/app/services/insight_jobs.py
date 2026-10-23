"""Генерация инсайта по запросу пользователя: один прогон на (клиент, новость, роль) и ход генерации по трассе.

Инсайт готовится 1-1,5 минуты. trace_id задаётся до старта, поэтому фронтенд видит шаги агента, пока POST
ещё выполняется (`GET /api/insights/{client_id}/{news_id}/progress`). Повторный запрос того же инсайта,
пока он готовится, ждёт первый прогон, а не запускает второй (двойная цена). Реестр - в памяти процесса:
API запускается одним процессом uvicorn; при нескольких процессах нужна общая очередь (docs/scaling.md).
"""
import threading
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent import orchestrator
from app.observability.tracing import new_trace_id
from app.schemas.insight import Insight

WAIT_SECONDS = 600


@dataclass
class Job:
    trace_id: str
    done: threading.Event = field(default_factory=threading.Event)
    insight: Insight | None = None
    error: BaseException | None = None


_lock = threading.Lock()
_jobs: dict[tuple[str, str, str | None], Job] = {}


def running(client_id: str, news_id: str, role: str | None) -> Job | None:
    with _lock:
        return _jobs.get((client_id, news_id, role))


def generate(db: Session, client_id: str, news_id: str, role: str | None) -> Insight:
    """Запускает агента или присоединяется к уже идущему прогону; ошибки прогона пробрасываются обоим."""
    key = (client_id, news_id, role)
    with _lock:
        job = _jobs.get(key)
        owner = job is None
        if owner:
            job = _jobs[key] = Job(trace_id=new_trace_id())
    if not owner:
        if not job.done.wait(WAIT_SECONDS):
            raise TimeoutError("insight generation is still running")
        if job.error is not None:
            raise job.error
        return job.insight
    try:
        job.insight = orchestrator.run(db, client_id, news_id, user_role=role, trace_id=job.trace_id)
        return job.insight
    except BaseException as e:
        job.error = e
        raise
    finally:
        job.done.set()
        with _lock:
            _jobs.pop(key, None)
