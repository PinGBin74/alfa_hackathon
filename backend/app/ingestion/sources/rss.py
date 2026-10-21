from datetime import UTC, datetime
from time import mktime

import feedparser
import httpx
import trafilatura

from app.ingestion.sources.base import NewsSource, RawNews


class RssSource(NewsSource):
    def __init__(self, name: str, feed_url: str, max_items: int = 30):
        self.name = name
        self.feed_url = feed_url
        self.max_items = max_items

    def fetch(self) -> list[RawNews]:
        feed = feedparser.parse(self.feed_url)
        items: list[RawNews] = []
        for e in feed.entries[: self.max_items]:
            published = (
                datetime.fromtimestamp(mktime(e.published_parsed), tz=UTC)
                if getattr(e, "published_parsed", None) else datetime.now(UTC)
            )
            body = self._extract(e.link) or getattr(e, "summary", "")
            items.append(RawNews(self.name, e.link, e.title, body, published))
        return items

    @staticmethod
    def _extract(url: str) -> str | None:
        try:
            html = httpx.get(url, timeout=20, follow_redirects=True).text
            return trafilatura.extract(html)
        except Exception:
            return None
