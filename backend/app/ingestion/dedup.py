"""Дубликаты новостей: точные (хэш заголовка за день) и нечёткие (перепечатки в других изданиях).

Нечёткий дубль - заголовок, похожий по символьным триграммам (Jaccard >= NEAR_DUP_THRESHOLD), без
противоречащих «информативных» слов и опубликованный в пределах NEAR_DUP_WINDOW. Информативные слова -
числа, имена (с заглавной не в начале фразы, латиница, «Х:» - автор заявления), дни недели и месяцы:
«ЦБ понизил курс доллара на 22 октября» и «...на 20 октября» похожи на 0.85, но это разные новости.
Порог подобран 21.10.2026 на 2079 заголовках из 21 RSS-ленты: при 0.6 с проверкой слов ложных склеек
не найдено, перепечатки и перестановки слов (0.6-1.0) ловятся. Пересказы своими словами (<0.6) не
ловятся: лучше показать дубль, чем потерять отдельную новость.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import NewsItem

NEAR_DUP_THRESHOLD = 0.6
NEAR_DUP_WINDOW = timedelta(hours=48)
RECENT_DAYS = 3

_CALENDAR = ("понедельник", "вторник", "четверг", "пятниц", "суббот", "воскресен", "январ", "феврал",
             "март", "апрел", "мая", "май", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
_WEDNESDAY = {"среда", "среду", "среды", "среде"}
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")

Variants = list[tuple[str, frozenset[str]]]


def normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower().replace("ё", "е")).strip()


def dedup_hash(title: str, body: str = "", published_at: datetime | None = None) -> str:
    """Точные дубликаты: одинаковый заголовок. С датой публикации - в пределах суток (UTC): ЦБ и Минфин
    регулярно выпускают сообщения с одним заголовком («Результаты мониторинга ставок...»)."""
    key = normalize(title)
    if published_at is not None:
        key += "|" + _utc(published_at).date().isoformat()
    return hashlib.sha256(key.encode()).hexdigest()


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def shingles(text: str, n: int = 3) -> frozenset[str]:
    s = f" {normalize(text)} "
    return frozenset(s[i:i + n] for i in range(len(s) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def variants(title: str) -> Variants:
    """Заголовок целиком и его части: «Коммерсантъ» пишет «Рубрика // Суть», перепечатывают суть."""
    parts = [p.strip() for p in title.split("//")]
    texts = [title] + ([p for p in parts if len(p.split()) >= 3] if len(parts) > 1 else [])
    return [(t, shingles(t)) for t in texts]


def _stem(word: str) -> str:
    return word if len(word) <= 3 else word[:max(3, min(5, len(word) - 1))]


def informative(title: str) -> set[str]:
    """Числа, имена и даты заголовка (основы слов): по ним различаются однотипные новости."""
    text = title.replace("ё", "е").replace("Ё", "Е")
    out: set[str] = set()
    phrase_start = True
    for m in _WORD.finditer(text):
        word, low = m.group(), m.group().lower()
        nxt = text[m.end():m.end() + 3].strip()[:1]
        if low[0].isdigit():
            out.add(low.replace(",", "."))
        elif (re.fullmatch(r"[a-z]{2,}", low) or (word[0].isupper() and not phrase_start)
              or text[m.end():m.end() + 1] == ":" or low.startswith(_CALENDAR) or low in _WEDNESDAY):
            out.add(_stem(low))
        phrase_start = nxt in (":", ".", "!", "?", "/")
    return out


def _unmatched(a: set[str], b: set[str]) -> set[str]:
    """Слова из a без пары в b: числа - точно, основы - по префиксу («китая»/«китае»)."""
    words_b = [y for y in b if not y[0].isdigit()]
    return {x for x in a if (x not in b if x[0].isdigit()
                             else not any(y.startswith(x) or x.startswith(y) for y in words_b))}


def conflicting(a: str, b: str) -> bool:
    """У каждого заголовка есть свои числа/имена/даты, которых нет в другом: разные события по шаблону."""
    ia, ib = informative(a), informative(b)
    return bool(_unmatched(ia, ib)) and bool(_unmatched(ib, ia))


def _match(va: Variants, vb: Variants, threshold: float) -> bool:
    return any(jaccard(sa, sb) >= threshold and not conflicting(ta, tb) for ta, sa in va for tb, sb in vb)


def title_similarity(a: str, b: str) -> float:
    return max(jaccard(sa, sb) for _, sa in variants(a) for _, sb in variants(b))


def is_near_duplicate(a: str, b: str, threshold: float = NEAR_DUP_THRESHOLD) -> bool:
    return _match(variants(a), variants(b), threshold)


@dataclass
class TitleIndex:
    """Недавние заголовки для поиска перепечаток: из БД за последние дни и добавленные в этом запуске."""
    window: timedelta = NEAR_DUP_WINDOW
    threshold: float = NEAR_DUP_THRESHOLD
    items: list[tuple[str, datetime | None, Variants]] = field(default_factory=list)

    def add(self, news_id: str, title: str, published_at: datetime | None) -> None:
        self.items.append((news_id, _utc(published_at) if published_at else None, variants(title)))

    def find(self, title: str, published_at: datetime | None = None) -> str | None:
        """news_id новости, перепечаткой которой является заголовок, или None."""
        ts = _utc(published_at) if published_at else None
        va = variants(title)
        for news_id, other_ts, vb in self.items:
            if ts and other_ts and abs(ts - other_ts) > self.window:
                continue
            if _match(va, vb, self.threshold):
                return news_id
        return None


def recent_index(db: Session, days: int = RECENT_DAYS, now: datetime | None = None) -> TitleIndex:
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    index = TitleIndex()
    rows = db.query(NewsItem.news_id, NewsItem.title, NewsItem.published_at).filter(NewsItem.published_at >= since)
    for news_id, title, published in rows:
        index.add(news_id, title, published)
    return index
