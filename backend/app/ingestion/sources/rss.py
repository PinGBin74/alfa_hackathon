"""RSS-источник: записи из ленты, полный текст - из ленты или со страницы статьи (trafilatura)."""
import logging
import re
from calendar import timegm
from datetime import UTC, datetime
from functools import partial

import feedparser
import trafilatura

from app.ingestion.sources.base import Http, NewsSource, RawNews, html_to_text

log = logging.getLogger("ingestion.sources")

# Служебные строки сайтов, которые trafilatura оставляет в тексте (меню, лицензия, подпись пресс-службы).
BOILERPLATE = [re.compile(p, re.I) for p in (
    r"^и многое другое$",
    r"Creative Commons",
    r"^При использовании материала ссылка на .{0,60}обязательна\.?$",
)]
_http: Http | None = None


def shared_http() -> Http:
    """Один клиент на процесс: общий пул соединений и память о хостах, которые не пускают прокси."""
    global _http
    if _http is None:
        _http = Http()
    return _http


def clean_text(text: str | None) -> str:
    lines = (line.strip() for line in (text or "").split("\n"))
    return "\n".join(line for line in lines if line and not any(rx.search(line) for rx in BOILERPLATE))


def extract_text(http: Http, url: str) -> str | None:
    """Основной текст страницы. Байты отдаём trafilatura целиком: кодировку (windows-1251 у части
    страниц Интерфакса) она определяет сама, httpx по заголовкам угадывает её неверно."""
    page = http.get(url)
    text = trafilatura.extract(page.content, url=page.url, include_comments=False, favor_precision=True)
    return clean_text(text) or None


def published_at(entry) -> datetime:
    """feedparser отдаёт время в UTC (struct_time): timegm, а не mktime, иначе сдвиг на пояс сервера."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(timegm(t), tz=UTC) if t else datetime.now(UTC)


class RssSource(NewsSource):
    """name - издание, как его видит пользователь. categories - рубрики ленты, которые берём (по префиксу:
    «Экономика» подходит под «Экономика / Налоги и сборы»). full_text_field - поле ленты с полным текстом
    (у РБК). extract=False - страницы не загружаем: полный текст уже в анонсе (пресс-релизы ЦБ)."""

    def __init__(self, name: str, feed_url: str, *, max_items: int = 20, categories: tuple[str, ...] = (),
                 full_text_field: str | None = None, extract: bool = True, http: Http | None = None):
        self.name = name
        self.feed_url = feed_url
        self.max_items = max_items
        self.categories = categories
        self.full_text_field = full_text_field
        self.extract = extract
        self._http = http

    @property
    def http(self) -> Http:
        return self._http or shared_http()

    def fetch(self) -> list[RawNews]:
        """Свежие записи ленты (не больше max_items). Недоступная лента - пустой список, не исключение."""
        try:
            page = self.http.get(self.feed_url)
        except Exception as e:
            log.warning("%s: feed unavailable %s: %s", self.name, self.feed_url, e)
            return []
        feed = feedparser.parse(page.content)
        if not feed.entries:
            log.warning("%s: no entries in %s (%s)", self.name, self.feed_url, feed.get("bozo_exception"))
            return []
        items: list[RawNews] = []
        for entry in feed.entries:
            if len(items) >= self.max_items:
                break
            if self._wanted(entry) and (raw := self._to_raw(entry)):
                items.append(raw)
        return items

    def _wanted(self, entry) -> bool:
        if not self.categories:
            return True
        terms = [(t.get("term") or "").strip() for t in entry.get("tags", [])]
        return any(term.startswith(c) for term in terms for c in self.categories)

    def _to_raw(self, entry) -> RawNews | None:
        url = (entry.get("link") or "").strip()
        title = " ".join(html_to_text(entry.get("title")).split())
        if not url.startswith(("http://", "https://")) or not title:
            return None
        full = clean_text(html_to_text(self._full_text_html(entry)))
        summary = clean_text(html_to_text(entry.get("summary")))
        loader = partial(extract_text, self.http, url) if not full and self.extract else None
        return RawNews(self.name, url, title, full or summary, published_at(entry), fetch_body=loader)

    def _full_text_html(self, entry) -> str | None:
        if self.full_text_field:
            return entry.get(self.full_text_field)
        content = entry.get("content") or []  # content:encoded (WordPress и др.)
        return content[0].get("value") if content else None
