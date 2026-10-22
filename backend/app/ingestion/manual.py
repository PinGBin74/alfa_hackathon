"""Ручное добавление новости по ссылке («вставьте ссылку на любую новость») тем же конвейером, что у
планировщика: дедупликация -> классификация -> запись. Маршрут API подключает backend:
`ingest_url(db, llm, url)`; IngestError - ссылку обработать нельзя (422), NotBusinessNews - не про бизнес."""
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMClient
from app.db.models import NewsItem
from app.ingestion.scheduler import NewsPipeline, news_id_for
from app.ingestion.sources import SOURCES
from app.ingestion.sources.base import FetchError, RawNews
from app.ingestion.sources.rss import clean_text, shared_http
from app.ml.news import NewsClassification

log = logging.getLogger("ingestion.manual")

MIN_TEXT_CHARS = 200   # меньше - скорее всего не статья (главная страница, заглушка, капча)


class IngestError(ValueError):
    """Ссылку нельзя обработать: не http(s), внутренний адрес, страница недоступна или без текста."""


class NotBusinessNews(IngestError):
    def __init__(self, classification: NewsClassification):
        super().__init__("новость не связана с бизнесом и экономикой")
        self.classification = classification


def normalize_url(url: str) -> str:
    """Без #якоря и utm-меток: та же статья из ленты и из браузера должна давать один news_id."""
    parts = urlsplit(url.strip())
    query = parts.query
    if "utm_" in query:
        query = urlencode([(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not k.startswith("utm_")])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def check_public_url(url: str) -> None:
    """Защита от SSRF: только http(s) и только публичные адреса (не localhost, не внутренние сети)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise IngestError("нужна ссылка http(s)")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except (OSError, UnicodeError, ValueError) as e:
        raise IngestError(f"сайт {parts.hostname} не найден") from e
    if any(not ipaddress.ip_address(info[4][0]).is_global for info in infos):
        raise IngestError("ссылка ведёт во внутреннюю сеть")


def source_name(url: str, sitename: str | None = None) -> str:
    """Издание: как в реестре источников (по домену ленты), иначе название сайта или домен."""
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    for src in SOURCES:
        feed_host = (urlsplit(getattr(src, "feed_url", "")).hostname or "").removeprefix("www.")
        if feed_host and (host == feed_host or feed_host.endswith("." + host) or host.endswith("." + feed_host)):
            return src.name
    return sitename or host


def _published(date: str | None) -> datetime:
    try:
        day = datetime.strptime(date or "", "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)
    now = datetime.now(UTC)
    return now if day.date() == now.date() else day


def fetch_article(url: str) -> RawNews:
    try:
        page = shared_http().get(url, guard=check_public_url)
    except FetchError as e:
        raise IngestError(f"страница недоступна: {e}") from e
    doc = trafilatura.bare_extraction(page.content, url=page.url, with_metadata=True,
                                      include_comments=False, favor_precision=True)
    text = clean_text(doc.text) if doc else ""
    title = " ".join((doc.title or "").split()) if doc else ""
    if not title or len(text) < MIN_TEXT_CHARS:
        raise IngestError("не удалось извлечь текст статьи")
    final_url = normalize_url(page.url)
    return RawNews(source_name(final_url, doc.sitename), final_url, title, text, _published(doc.date))


def ingest_url(db: Session, llm: LLMClient, url: str) -> NewsItem:
    """Новость по ссылке. Уже сохранённая (тот же URL, заголовок или перепечатка) возвращается как есть,
    без повторной загрузки и классификации."""
    url = normalize_url(url)
    check_public_url(url)
    existing = db.get(NewsItem, news_id_for(url))
    if existing is not None:
        return existing
    raw = fetch_article(url)
    pipe = NewsPipeline(db, llm)
    if dup := pipe.duplicate_of(raw):
        log.info("manual ingest %s: %s duplicate of %s", url, dup[0], dup[1])
        return db.get(NewsItem, dup[1])
    news_id = news_id_for(raw.url)
    cls = pipe.classify_raw(raw, news_id)
    if cls is None:
        raise IngestError("не удалось разметить новость, повторите позже")
    if not cls.is_business_relevant:
        raise NotBusinessNews(cls)
    item = pipe.store(raw, news_id, cls)
    if item is None and (dup := pipe.duplicate_of(raw)):  # параллельный запрос успел записать её раньше
        item = db.get(NewsItem, dup[1])
    if item is None:
        raise IngestError("не удалось сохранить новость")
    return item
