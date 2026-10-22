"""Поиск по аналитике банка и новостям. Каждый результат несёт ссылку на первоисточник.

Лексический BM25 на чистом Python с русской нормализацией (нижний регистр, ё -> е, стоп-слова,
лёгкий стемминг: снятие окончания + усечение до 6 символов), поэтому «ключевой ставки» находит
«ключевая ставка». Работает одинаково на Postgres и SQLite. Индексы кешируются в процессе и
пересобираются, когда меняется содержимое таблиц (count / max id / суммарная длина текста).

search_bank_analytics смешивает позиции банка (data/bank_analytics/positions.json: тезис + дословная
цитата со страницы) и чанки PDF; позиции с факторами запроса получают сильный буст, свежие документы -
небольшой, устаревшие и заменённые более поздним прогнозом - штраф.
"""
import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AnalyticsChunk, AnalyticsDoc, NewsItem
from app.ingestion import analytics_loader
from app.ml import bank_positions

STOPWORDS = frozenset("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от
меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж
вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один
почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после
над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед
иногда лучше чуть том нельзя такой им более всегда конечно всю между это также который которая которые
которых году года г гг т тыс млн млрд трлн руб the of and in to for on at by with from is are
""".split())
ENDINGS = tuple(sorted("""
ами ями ыми ими ого его ому ему ая яя ое ее ые ие ый ий ой ей ую юю ым им ых их ом ем ам ям ах ях ов ев
ию ия ие ии ья ье ьи ью ость ости ение ения ании ание ания ться тся ешь ишь ете ите ют ут ат ят ет ит ал
ала али ало ил ила или ило а я о е ы и у ю ь
""".split(), key=len, reverse=True))
STEM_LEN = 6
_TOKEN = re.compile(r"[a-zа-я]+|\d+(?:[.,]\d+)?")

NEWS_WINDOW_DAYS = 30
NEWS_CAP = 3000
BM25_FLOOR = 5.0              # нормировка: слабое совпадение не становится «лучшим» = 1.0
POSITION_FACTOR_BOOST = 1.0   # позиция с фактором запроса
CHUNK_FACTOR_BOOST = 0.3      # чанк документа с фактором запроса
POSITION_PRIOR = 0.05         # при равенстве - позиция банка, а не сырой фрагмент
RECENCY_BOOST = 0.2           # самый свежий документ; линейно до 0 за RECENCY_DAYS
RECENCY_DAYS = 120
STALE_PENALTY = 0.6
SUPERSEDED_PENALTY = 0.3     # прогноз той же метрики и горизонта обновлён в более свежем материале
HORIZON_PASSED_PENALTY = 0.3  # горизонт прогноза уже прошёл (например, ожидание по прошедшему заседанию)


# ---------- нормализация ----------

def stem(word: str) -> str:
    if word[0].isdigit():  # «14,0» == «14», «6,32» -> «6.32»
        w = word.replace(",", ".")
        return w.rstrip("0").rstrip(".") if "." in w else w
    for e in ENDINGS:
        if word.endswith(e) and len(word) - len(e) >= 3:
            word = word[: -len(e)]
            break
    if len(word) >= 5 and word[-2] in "ое" and word[-1] in "кн":  # беглая гласная: рынок/рынка, уровень/уровня
        word = word[:-2] + word[-1]
    return word[:STEM_LEN]


def tokenize(text: str | None) -> list[str]:
    text = (text or "").lower().replace("ё", "е")
    return [stem(t) for t in _TOKEN.findall(text) if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


class BM25:
    """Okapi BM25 по инвертированному индексу."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.n = k1, b, len(docs)
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / self.n) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.postings.setdefault(t, []).append((i, f))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in set(query):
            for i, f in self.postings.get(t, ()):
                norm = f + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg or 1))
                out[i] = out.get(i, 0.0) + self.idf[t] * f * (self.k1 + 1) / norm
        return out


def _normalized(raw: dict[int, float]) -> dict[int, float]:
    top = max(raw.values(), default=0.0)
    return {i: s / max(top, BM25_FLOOR) for i, s in raw.items()}


# ---------- кеш индексов ----------

_cache: dict[str, tuple[tuple, object]] = {}


def _cached(name: str, key: tuple, build):
    hit = _cache.get(name)
    if hit and hit[0] == key:
        return hit[1]
    value = build()
    _cache[name] = (key, value)
    return value


def _iso(d: datetime | date | None) -> str | None:
    return d.date().isoformat() if isinstance(d, datetime) else (d.isoformat() if d else None)


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


# ---------- аналитика банка ----------

def _doc_flags(positions_path: str | Path | None = None) -> dict[str, dict]:
    """Метаданные документов, которых нет в БД (stale): manifest.json, затем раздел documents из positions.json."""
    flags = {d["doc_id"]: d for d in bank_positions.load_positions_data(positions_path).get("documents", [])}
    manifest = analytics_loader.manifest_entries(Path(get_settings().data_dir) / "bank_analytics")
    return flags | {e["doc_id"]: e for e in manifest.values() if e.get("doc_id")}


def _chunk_index(db: Session, positions_path: str | Path | None = None) -> dict:
    """Чанки с метаданными документов + BM25 по тексту и названию документа."""
    count, max_id, total = db.query(func.count(AnalyticsChunk.chunk_id), func.max(AnalyticsChunk.chunk_id),
                                    func.sum(func.length(AnalyticsChunk.text))).one()
    flags = _doc_flags(positions_path)
    key = (str(db.get_bind().url), count, max_id, total,
           tuple(sorted((k, bool(v.get("stale"))) for k, v in flags.items())))

    def build() -> dict:
        docs = {d.doc_id: d for d in db.query(AnalyticsDoc).all()}
        rows = db.query(AnalyticsChunk.chunk_id, AnalyticsChunk.doc_id, AnalyticsChunk.page,
                        AnalyticsChunk.text).order_by(AnalyticsChunk.chunk_id).all()
        manifest = flags
        items = []
        for chunk_id, doc_id, page, text in rows:
            d = docs.get(doc_id)
            m = manifest.get(doc_id, {})
            items.append({
                "doc_id": doc_id, "title": d.title if d else doc_id, "page": page, "text": text,
                "kind": "chunk", "factors": list((d.topics if d else None) or []),
                "published_at": _iso(d.published_at) if d else None, "stale": bool(m.get("stale")),
                "superseded_by": None, "horizon_passed": False, "position_id": None, "forecast": None,
                "chunk_id": chunk_id,
            })
        newest = max((_day(i["published_at"]) for i in items if i["published_at"]), default=None)
        for i in items:  # документ вне манифеста: устаревший, если на год старше самого свежего
            d = _day(i["published_at"])
            if i["doc_id"] not in manifest and newest and d:
                i["stale"] = (newest - d).days > analytics_loader.STALE_AFTER_DAYS
        index = BM25([tokenize(f"{i['title']}\n{i['text']}") for i in items])
        return {"items": items, "bm25": index}

    return _cached("chunks", key, build)


def _position_index(path: str | Path | None = None) -> dict:
    data = bank_positions.load_positions_data(path)

    def build() -> dict:
        docs = {d["doc_id"]: d for d in data.get("documents", [])}
        items = []
        for p in data.get("positions", []):
            d = docs.get(p["doc_id"], {})
            items.append({
                "doc_id": p["doc_id"], "title": d.get("title") or p["doc_id"], "page": p["page"],
                "text": bank_positions.position_text(p), "kind": "position", "factors": list(p.get("factors") or []),
                "published_at": p.get("date") or d.get("date"), "stale": bool(d.get("stale")),
                "superseded_by": p.get("superseded_by"), "horizon_passed": bool(p.get("horizon_passed")),
                "position_id": p["position_id"],
                "forecast": p.get("forecast"), "thesis": p["thesis"], "quote": p["quote"],
            })
        index = BM25([tokenize(f"{i['thesis']}\n{i['quote']}\n{i['title']}") for i in items])
        return {"items": items, "bm25": index}

    return _cached("positions", (id(data),), build)


def _recency(published: str | None, newest: date | None) -> float:
    d = _day(published)
    if not d or not newest:
        return 0.0
    return RECENCY_BOOST * max(0.0, 1 - (newest - d).days / RECENCY_DAYS)


def search_bank_analytics(db: Session, query: str, k: int = 4, factors: list[str] | None = None,
                          positions_path: str | Path | None = None) -> list[dict]:
    """Позиции банка и фрагменты материалов, лучшие первыми.

    Ключи: doc_id, title, page, text, kind (position|chunk), factors, published_at (YYYY-MM-DD|None),
    stale, superseded_by, horizon_passed, position_id, forecast, score; у позиций ещё thesis и quote,
    у чанков chunk_id (position_id, forecast, superseded_by у чанков - None)."""
    q = tokenize(query)
    wanted = set(factors or [])
    pos, chunks = _position_index(positions_path), _chunk_index(db, positions_path)
    newest = max((_day(i["published_at"]) for i in pos["items"] + chunks["items"] if i["published_at"]), default=None)

    candidates: list[dict] = []
    lexical = _normalized(pos["bm25"].scores(q))
    for i, it in enumerate(pos["items"]):
        hit = bool(wanted & set(it["factors"]))
        if i not in lexical and not hit:
            continue
        s = lexical.get(i, 0.0) + POSITION_FACTOR_BOOST * hit + POSITION_PRIOR + _recency(it["published_at"], newest)
        s -= (STALE_PENALTY * it["stale"] + SUPERSEDED_PENALTY * bool(it["superseded_by"])
              + HORIZON_PASSED_PENALTY * it["horizon_passed"])
        candidates.append(it | {"score": round(s, 4)})
    lexical = _normalized(chunks["bm25"].scores(q))
    for i, s in lexical.items():
        it = chunks["items"][i]
        s += CHUNK_FACTOR_BOOST * bool(wanted & set(it["factors"])) + _recency(it["published_at"], newest)
        s -= STALE_PENALTY * it["stale"]
        candidates.append(it | {"score": round(s, 4)})
    candidates.sort(key=lambda c: (c["score"], c["published_at"] or ""), reverse=True)

    # одна страница - один чанк; если на странице есть позиция, вместо чанка берётся она
    best_position = {}
    for c in candidates:
        if c["kind"] == "position":
            best_position.setdefault((c["doc_id"], c["page"]), c)
    out, used_positions, used_pages = [], set(), set()
    for c in candidates:
        if len(out) >= k:
            break
        page = (c["doc_id"], c["page"])
        if c["kind"] == "chunk":
            alt = best_position.get(page)
            if alt is None and page in used_pages:
                continue
            if alt is not None:
                if alt["position_id"] in used_positions:
                    continue
                c = alt | {"score": max(alt["score"], c["score"])}
        if c["kind"] == "position":
            if c["position_id"] in used_positions:
                continue
            used_positions.add(c["position_id"])
        used_pages.add(page)
        out.append(c)
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


# ---------- новости ----------

def _news_index(db: Session) -> dict:
    since = datetime.combine(date.today() - timedelta(days=NEWS_WINDOW_DAYS), datetime.min.time(), tzinfo=UTC)
    flt = NewsItem.published_at >= since
    count, last, total = db.query(func.count(NewsItem.news_id), func.max(NewsItem.published_at),
                                  func.sum(func.length(NewsItem.title) + func.coalesce(func.length(NewsItem.summary), 0))
                                  ).filter(flt).one()
    key = (str(db.get_bind().url), since.date().isoformat(), count, str(last), total)

    def build() -> dict:
        rows = (db.query(NewsItem.news_id, NewsItem.title, NewsItem.url, NewsItem.source, NewsItem.published_at,
                         NewsItem.summary).filter(flt).order_by(NewsItem.published_at.desc()).limit(NEWS_CAP).all())
        items = [{"news_id": r.news_id, "title": r.title, "url": r.url, "source": r.source,
                  "published_at": r.published_at.isoformat() if r.published_at else None, "summary": r.summary}
                 for r in rows]
        # заголовок дважды: он точнее описывает событие, чем пересказ
        return {"items": items, "bm25": BM25([tokenize(f"{i['title']}\n{i['title']}\n{i['summary'] or ''}") for i in items])}

    return _cached("news", key, build)


def search_news(db: Session, query: str, k: int = 5) -> list[dict]:
    """Новости за последние NEWS_WINDOW_DAYS дней. Ключи: news_id, title, url, source, published_at, summary, score."""
    idx = _news_index(db)
    raw = idx["bm25"].scores(tokenize(query))
    ranked = sorted(raw.items(), key=lambda x: (x[1], idx["items"][x[0]]["published_at"] or ""), reverse=True)
    return [idx["items"][i] | {"score": round(s, 4)} for i, s in ranked[:k]]
