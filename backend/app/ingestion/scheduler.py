"""Фоновый сбор. Запуск: python -m app.ingestion.scheduler [--once]"""
import argparse
import hashlib
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.agent.llm_client import LLMClient
from app.config import get_settings
from app.db.models import NewsItem
from app.db.session import SessionLocal
from app.ingestion import analytics_loader, classify, dedup
from app.ingestion.sources import SOURCES
from app.security import injection_guard

log = logging.getLogger("ingestion")


def run_once() -> None:
    with SessionLocal() as db:
        analytics_loader.load_dir(db)
        llm = LLMClient(db)
        added = 0
        for src in SOURCES:
            for raw in src.fetch():
                h = dedup.dedup_hash(raw.title, raw.body)
                if db.query(NewsItem).filter_by(dedup_hash=h).first():
                    continue
                if injection_guard.scan(raw.body):
                    log.warning("possible injection in %s", raw.url)
                meta = classify.classify(llm, raw.title, raw.body)
                db.add(NewsItem(
                    news_id=hashlib.sha1(raw.url.encode()).hexdigest()[:16],
                    source=raw.source, url=raw.url, title=raw.title, body=raw.body,
                    published_at=raw.published_at, dedup_hash=h, **meta,
                ))
                added += 1
        db.commit()
        log.info("ingestion done, added=%s", added)


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
