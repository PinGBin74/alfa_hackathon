"""Журналирование шагов агента в agent_traces (критерий 12: трассируемость)."""
import time
import uuid
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.db.models import AgentTrace


def new_trace_id() -> str:
    return uuid.uuid4().hex


class Tracer:
    def __init__(self, db: Session, trace_id: str | None = None):
        self.db = db
        self.trace_id = trace_id or new_trace_id()
        self._step = 0

    def log(
        self,
        kind: str,
        name: str | None = None,
        input: dict | None = None,
        output: dict | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self._step += 1
        self.db.add(
            AgentTrace(
                trace_id=self.trace_id, step=self._step, kind=kind, name=name,
                input=input, output=output, model=model,
                tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
            )
        )
        self.db.commit()

    @contextmanager
    def span(self, kind: str, name: str, input: dict | None = None):
        start = time.perf_counter()
        holder: dict = {}
        try:
            yield holder
        finally:
            self.log(kind, name, input=input, output=holder.get("output"),
                     latency_ms=int((time.perf_counter() - start) * 1000))
