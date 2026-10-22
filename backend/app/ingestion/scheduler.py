"""Фоновый сбор. Запуск: python -m app.ingestion.scheduler [--once]"""
import argparse
import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMClient, LLMError
from app.config import get_settings
from app.db.models import NewsItem
from app.db.session import SessionLocal
from app.ingestion import analytics_loader, classify, dedup
from app.ingestion.sources import SOURCES
from app.ingestion.sources.base import NewsSource, RawNews
from app.ml.news import NewsClassification
from app.security import injection_guard
from app.services.token_budget import BudgetExceeded

log = logging.getLogger("ingestion")

# Новости без последствий для бизнеса не сохраняются; чтобы не классифицировать их заново в каждом
# запуске (лента отдаёт их ещё несколько часов), их id помним в процессе воркера.
_rejected: dict[str, None] = {}
REJECTED_MAX = 5000


def news_id_for(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


@dataclass
class Stats:
    fetched: int = 0
    added: int = 0
    duplicates: int = 0
    near_duplicates: int = 0
    irrelevant: int = 0
    stale: int = 0
    failed: int = 0


class NewsPipeline:
    """Дедупликация -> полный текст -> классификация -> запись. Общая для планировщика и ручного добавления."""

    def __init__(self, db: Session, llm: LLMClient, now: datetime | None = None):
        self.db, self.llm = db, llm
        now = now or datetime.now(UTC)
        self.since = now - timedelta(days=get_settings().news_max_age_days)
        self.index = dedup.recent_index(db, now=now)
        self.hashes: dict[str, str] = {}   # dedup_hash -> news_id, добавленные в этом запуске
        self.stats = Stats()

    def duplicate_of(self, raw: RawNews) -> tuple[str, str] | None:
        """(вид дубля, news_id уже сохранённой новости): тот же URL, тот же заголовок за день, перепечатка."""
        news_id = news_id_for(raw.url)
        if self.db.get(NewsItem, news_id) is not None:
            return "url", news_id
        h = dedup.dedup_hash(raw.title, published_at=raw.published_at)
        same = self.hashes.get(h) or self.db.query(NewsItem.news_id).filter_by(dedup_hash=h).scalar()
        if same:
            return "title", same
        near = self.index.find(raw.title, raw.published_at)
        return ("near", near) if near else None

    def process(self, raw: RawNews) -> NewsItem | None:
        """Сохранённая новость или None (дубль, устарела, не про бизнес, ошибка классификации)."""
        self.stats.fetched += 1
        if _as_utc(raw.published_at) < self.since:
            self.stats.stale += 1
            return None
        news_id = news_id_for(raw.url)
        if news_id in _rejected:
            self.stats.irrelevant += 1
            return None
        dup = self.duplicate_of(raw)
        if dup:
            kind, other = dup
            if kind == "near":
                self.stats.near_duplicates += 1
                log.info("near-duplicate of %s: %s (%s)", other, raw.title, raw.source)
            else:
                self.stats.duplicates += 1
            return None
        cls = self.classify_raw(raw, news_id)
        if cls is None:
            self.stats.failed += 1
            return None
        if not cls.is_business_relevant:
            self.stats.irrelevant += 1
            remember_rejected(news_id)
            return None
        return self.store(raw, news_id, cls)

    def classify_raw(self, raw: RawNews, news_id: str) -> NewsClassification | None:
        body = raw.load_body()
        if injection_guard.scan(f"{raw.title}\n{body}"):
            log.warning("possible injection in %s", raw.url)
        try:
            return classify.classify_news(self.llm, raw.title, body, source_id=news_id)
        except LLMError as e:
            log.warning("classification failed for %s: %s", raw.url, e)
            return None

    def store(self, raw: RawNews, news_id: str, cls: NewsClassification) -> NewsItem | None:
        h = dedup.dedup_hash(raw.title, published_at=raw.published_at)
        item = NewsItem(news_id=news_id, source=raw.source, url=raw.url, title=raw.title, body=raw.body,
                        published_at=raw.published_at, dedup_hash=h, **cls.columns())
        if hasattr(NewsItem, "ml_meta"):  # колонку добавит backend; до этого разметка восстанавливается из колонок
            item.ml_meta = cls.meta()
        self.db.add(item)
        try:
            self.db.commit()
        except IntegrityError:  # ту же новость успел записать другой процесс
            self.db.rollback()
            self.stats.duplicates += 1
            return None
        self.hashes[h] = news_id
        self.index.add(news_id, raw.title, raw.published_at)
        self.stats.added += 1
        return item


def remember_rejected(news_id: str) -> None:
    _rejected[news_id] = None
    while len(_rejected) > REJECTED_MAX:
        _rejected.pop(next(iter(_rejected)))


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def ingest_news(db: Session, llm: LLMClient, sources: list[NewsSource] | None = None) -> Stats:
    """Один проход по источникам. Сломанный источник или новость не останавливают сбор, исчерпанный
    бюджет LLM - останавливает (остальное подберёт следующий запуск)."""
    pipe = NewsPipeline(db, llm)
    for src in SOURCES if sources is None else sources:
        try:
            items = src.fetch()
        except Exception:
            log.exception("source %s failed", getattr(src, "name", src))
            continue
        for raw in items:
            try:
                pipe.process(raw)
            except BudgetExceeded:
                log.warning("LLM budget exhausted, ingestion stopped: %s", asdict(pipe.stats))
                return pipe.stats
            except Exception:
                log.exception("failed to ingest %s", raw.url)
                db.rollback()
                pipe.stats.failed += 1
    log.info("news ingestion done: %s", asdict(pipe.stats))
    return pipe.stats


def run_once() -> None:
    with SessionLocal() as db:
        analytics_loader.load_dir(db)
        llm = LLMClient(db)
        ingest_news(db, llm)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    run_once()
    if args.once:
        return
    sched = BlockingScheduler()
    sched.add_job(run_once, "interval", minutes=get_settings().ingest_interval_minutes)
    sched.start()


if __name__ == "__main__":
    main()
