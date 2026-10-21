from app.ingestion.sources.base import NewsSource
from app.ingestion.sources.rss import RssSource  # noqa: F401

# TODO: выбрать и перечислить реальные источники (также внести в THIRD_PARTY_NOTICES.md)
SOURCES: list[NewsSource] = [
    # RssSource("example", "https://example.com/rss.xml"),
]
