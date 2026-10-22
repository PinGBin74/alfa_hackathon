"""Базовый интерфейс источника новостей. Новый источник = новый файл с подклассом (критерий 07)."""
import html
import logging
import re
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlsplit

import httpx

log = logging.getLogger("ingestion.sources")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
# Ответы, после которых пробуем без прокси: часть российских сайтов (cbr.ru, minfin.gov.ru,
# страницы rbc.ru) отвечает зарубежному прокси 401/403, сам прокси - 403 на CONNECT.
BLOCKED_STATUS = {401, 403, 407, 451}


class FetchError(RuntimeError):
    pass


@dataclass
class Page:
    url: str
    status: int
    content: bytes
    location: str | None = None   # адрес редиректа (редиректы обходим сами, чтобы проверять каждый)


@dataclass
class RawNews:
    source: str
    url: str
    title: str
    body: str                  # полный текст или, до load_body(), анонс из RSS
    published_at: datetime
    fetch_body: Callable[[], str | None] | None = field(default=None, repr=False, compare=False)

    def load_body(self) -> str:
        """Полный текст статьи: загружается один раз и только для новых новостей.
        Если загрузить не удалось или текст короче анонса, остаётся анонс из RSS."""
        if self.fetch_body is not None:
            loader, self.fetch_body = self.fetch_body, None
            try:
                text = loader()
            except Exception as e:  # сломанная страница не должна останавливать сбор
                log.warning("body extraction failed for %s: %s", self.url, e)
                text = None
            if text and len(text) > len(self.body):
                self.body = text
        return self.body


class NewsSource(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[RawNews]:
        ...


class Http:
    """GET с браузерными заголовками, таймаутами и лимитом размера ответа.

    Запрос идёт по настройкам окружения (HTTP(S)_PROXY); если прокси отказал - повтор напрямую,
    и хост дальше запрашивается напрямую. `guard(url)` проверяет каждый адрес, включая редиректы
    (ручное добавление ссылки: защита от SSRF)."""

    def __init__(self, timeout: httpx.Timeout = TIMEOUT, max_bytes: int = MAX_BYTES):
        self.max_bytes = max_bytes
        self._env = httpx.Client(headers=HEADERS, timeout=timeout, trust_env=True)
        self._direct = httpx.Client(headers=HEADERS, timeout=timeout, trust_env=False)
        self._has_proxy = bool(urllib.request.getproxies())
        self._direct_hosts: set[str] = set()

    def get(self, url: str, guard: Callable[[str], None] | None = None) -> Page:
        for _ in range(MAX_REDIRECTS + 1):
            if guard:
                guard(url)
            page = self._get_once(url)
            if page.location:
                url = urljoin(url, page.location)
                continue
            if page.status >= 400:
                raise FetchError(f"HTTP {page.status}: {url}")
            return page
        raise FetchError(f"too many redirects: {url}")

    def _get_once(self, url: str) -> Page:
        host = urlsplit(url).hostname or ""
        if host in self._direct_hosts:
            clients = [self._direct]
        else:
            clients = [self._env, self._direct] if self._has_proxy else [self._env]
        error: Exception | None = None
        for i, client in enumerate(clients):
            last = i == len(clients) - 1
            try:
                page = self._read(client, url)
            except httpx.HTTPError as e:
                error = e
                continue
            if page.status in BLOCKED_STATUS and not last:
                error = FetchError(f"HTTP {page.status}")
                continue
            if i > 0:
                self._direct_hosts.add(host)
                log.info("%s: proxy refused, fetching directly", host)
            return page
        raise FetchError(f"{url}: {error}")

    def _read(self, client: httpx.Client, url: str) -> Page:
        with client.stream("GET", url) as r:
            if r.is_redirect:
                return Page(url, r.status_code, b"", location=r.headers["location"])
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise FetchError(f"response larger than {self.max_bytes} bytes: {url}")
                chunks.append(chunk)
            return Page(str(r.url), r.status_code, b"".join(chunks))


_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_BLOCKS = re.compile(r"</?(p|div|br|li|h\d|tr|blockquote)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None) -> str:
    """Текст из HTML-фрагмента RSS (анонс, полный текст): абзацы сохраняются, теги и сущности - нет."""
    if not raw:
        return ""
    s = _BLOCKS.sub("\n", _COMMENTS.sub("", raw))
    s = html.unescape(_TAGS.sub("", s)).replace("\u00a0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in s.split("\n"))
    return "\n".join(line for line in lines if line)
