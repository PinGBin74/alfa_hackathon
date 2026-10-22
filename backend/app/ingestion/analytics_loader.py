"""Загрузка PDF-материалов Альфа-Банка (Приложение 2) -> analytics_docs + analytics_chunks.

Текст страницы: текстовый слой PDF (pypdf). Материалы кейса - сканы без текстового слоя, поэтому для
таких страниц берётся распознанный текст рядом с PDF (формат `=== page N ===`):
text/<stem>.vlm.txt (Qwen3-VL, `python -m app.ml.bank_positions ocr`) приоритетнее text/<stem>.txt
(OCR macOS Vision). Метаданные (название, дата, тип, факторы, устаревание) - в manifest.json;
для файла вне манифеста дата и факторы определяются по тексту (needs_review).

Очистка: дисклеймер, копирайт-подвал, колонтитулы, контакты аналитиков, номера страниц, деления
осей графиков. Чанки - по абзацам в пределах одной страницы, у каждого чанка есть номер страницы.
Повторная загрузка идемпотентна: документ перезаписывается, только если изменились его чанки
или метаданные (сравнение с БД), иначе пропускается.

CLI: python -m app.ingestion.analytics_loader [--dir data/bank_analytics] [--manifest] [--report] [--dump DIR]
"""
import argparse
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.db.models import AnalyticsChunk, AnalyticsDoc
from app.ml.taxonomy import FACTOR_CODES, FACTORS

log = logging.getLogger("analytics_loader")
logging.getLogger("pypdf").setLevel(logging.ERROR)  # «Ignoring wrong pointing object» в каждом скане

DEFAULT_DIR = "data/bank_analytics"
MANIFEST_NAME = "manifest.json"
TEXT_DIR = "text"
MIN_TEXT_CHARS = 40        # меньше символов в текстовом слое - страница-картинка
CHUNK_CHARS = 1400         # целевой размер чанка
MIN_CHUNK_CHARS = 300      # хвост короче приклеивается к предыдущему чанку страницы
TITLE_PAGE_CHARS = 250     # страница-заставка короче приклеивается к следующей странице
MIN_PAGE_CHARS = 80        # после очистки меньше - страница без содержания
STALE_AFTER_DAYS = 365     # для документов вне манифеста

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
          "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", re.I)
_PAGE_MARK = re.compile(r"^=== page (\d+) ===[ \t]*$", re.M)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+\s?7\s?\(?\d{3}\)?[\s\d-]{6,}")
_NAME = re.compile(r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+,?$")
_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_BULLET = re.compile(r"^[•●▪■□❑◦➢>]")
_SENTENCE_END = re.compile(r"(?<=[.!?…;])\s+(?=[«(•\-–А-ЯЁA-Z0-9])")

# Юридический подвал и дисклеймер (одинаковы во всех материалах): строка с маркером и всё после неё
# в том же блоке удаляются. Сравнение - по нормализованному тексту (нижний регистр, ё -> е).
FOOTER_MARKERS = (
    "все права защищены", "генеральная лицензия цб рф", "исключительной собственностью альфа",
    "настоящий отчет и содержащаяся", "настоящее письмо и содержащаяся", "несанкционированное копирование",
    "данный материал предназначен ао", "не предназначен для распространения среди частных",
    "не является деятельностью по инвестиционному", "аффилированные лица ведут и намерены",
    "могут иметь конфликт интересов",
)
DISCLAIMER_HEADS = ("дисклеймер", "disclaimer")


@dataclass
class Page:
    page: int
    text: str
    source: str  # pdf | vlm_ocr | ocr_sidecar | none


@dataclass
class Document:
    file: Path
    doc_id: str
    title: str
    published_at: datetime | None
    topics: list[str]
    stale: bool
    pages: list[Page]                       # очищенный текст, нумерация как в PDF
    entry: dict = field(default_factory=dict)
    alt_pages: dict[int, str] = field(default_factory=dict)  # та же страница из другого OCR (второй свидетель)

    def chunks(self) -> list[tuple[int, str]]:
        return [(p.page, ch) for p in self.pages for ch in chunk_page(p.text)]


def nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def doc_id_for(name: str) -> str:
    """bank:{doc_id}:{page} - идентификатор источника во всей системе; doc_id = sha1(имени файла)[:12]."""
    return hashlib.sha1(nfc(name).encode()).hexdigest()[:12]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _key(text: str) -> str:
    """Ключ строки для поиска колонтитулов: только буквы (номера страниц и даты не мешают)."""
    return " ".join(re.findall(r"[a-zа-я]+", text.lower().replace("ё", "е")))


# ---------- текст страниц: PDF -> распознанный текст рядом ----------

def sidecar_path(pdf: Path, vlm: bool = False) -> Path:
    return pdf.parent / TEXT_DIR / f"{pdf.stem}{'.vlm' if vlm else ''}.txt"


def read_sidecar(path: Path) -> dict[int, str]:
    parts = _PAGE_MARK.split(path.read_text(encoding="utf-8"))
    return {int(parts[i]): parts[i + 1].strip("\n") for i in range(1, len(parts), 2)}


def write_sidecar(path: Path, pages: dict[int, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"=== page {n} ===\n{pages[n].strip()}\n\n" for n in sorted(pages)), encoding="utf-8")


def pdf_page_texts(pdf: Path) -> list[str]:
    out = []
    for page in PdfReader(str(pdf)).pages:
        try:
            out.append(page.extract_text() or "")
        except Exception as e:  # битая страница не должна ронять загрузку
            log.warning("%s: extract_text failed: %s", pdf.name, e)
            out.append("")
    return out


def raw_pages(pdf: Path) -> list[Page]:
    """Текстовый слой PDF, где он есть; для страниц-картинок - распознанный текст (VLM, затем OCR)."""
    vlm_file, ocr_file = sidecar_path(pdf, vlm=True), sidecar_path(pdf)
    vlm = read_sidecar(vlm_file) if vlm_file.exists() else {}
    ocr = read_sidecar(ocr_file) if ocr_file.exists() else {}
    pages = []
    for n, text in enumerate(pdf_page_texts(pdf), start=1):
        if len(text.strip()) >= MIN_TEXT_CHARS:
            pages.append(Page(n, text, "pdf"))
        elif vlm.get(n, "").strip():
            pages.append(Page(n, vlm[n], "vlm_ocr"))
        elif ocr.get(n, "").strip():
            pages.append(Page(n, ocr[n], "ocr_sidecar"))
        else:
            pages.append(Page(n, text, "none"))
    return pages


def alt_page_texts(pdf: Path, primary: list[Page]) -> dict[int, str]:
    """Текст страниц из второго источника распознавания: для VLM - OCR Vision и наоборот.
    Нужен для перекрёстной проверки цитат позиций банка."""
    vlm_file, ocr_file = sidecar_path(pdf, vlm=True), sidecar_path(pdf)
    vlm = read_sidecar(vlm_file) if vlm_file.exists() else {}
    ocr = read_sidecar(ocr_file) if ocr_file.exists() else {}
    out = {}
    for p in primary:
        other = ocr if p.source == "vlm_ocr" else vlm if p.source == "ocr_sidecar" else {}
        if other.get(p.page, "").strip():
            out[p.page] = other[p.page]
    return out


# ---------- очистка ----------

def _blocks(text: str) -> list[list[str]]:
    blocks, cur = [], []
    for line in text.splitlines():
        line = " ".join(line.replace("\u00ad", "").split())
        if line:
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split(" | ")]


def _numeric(line: str) -> bool:
    """Строка без слов (4+ букв): деления осей, подписи точек графика, номер страницы.
    Шапка таблицы с годами - не шум."""
    return not _WORD.search(line) and len(_YEAR.findall(line)) < 2


def _tabular(line: str) -> bool:
    letters = len(_LETTER.findall(line))
    return " | " in line or line.startswith("|") or (len(_NUMBER.findall(line)) >= 3 and letters < len(line) * 0.5)


def _strip_footer(block: list[str]) -> list[str]:
    for i, line in enumerate(block):
        n = _norm(line)
        if any(m in n for m in FOOTER_MARKERS):
            return block[:i]
    return block


def _contact_names(blocks: list[list[str]]) -> set[str]:
    """Имена аналитиков: ячейка-имя в строке с e-mail или строкой выше."""
    names = set()
    for block in blocks:
        for i, line in enumerate(block):
            if not _EMAIL.search(line):
                continue
            around = _cells(line) + (_cells(block[i - 1]) if i else [])
            names |= {c.rstrip(",") for c in around if _NAME.match(c)}
    return names


def _drop_contacts(block: list[str], names: set[str]) -> list[str]:
    if any(_PHONE.search(x) for x in block) and all(len(x) < 50 for x in block):
        return []  # блок контактов без e-mail: имя, должность, телефон
    out = []
    for line in block:
        cells = [c for c in _cells(line) if c and not _EMAIL.search(c) and not _PHONE.search(c)
                 and c.rstrip(",") not in names and len(c) > 1]
        if cells:
            out.append(" | ".join(cells))
    return out


def _drop_chart_noise(block: list[str]) -> list[str]:
    numeric = [_numeric(x) for x in block]
    if len(block) >= 3 and sum(numeric) >= 0.4 * len(block):
        return [x for x, num in zip(block, numeric, strict=True) if not num]
    return block


def _join(block: list[str]) -> list[str]:
    """Строки абзаца - в одну строку; строки таблиц и пункты списка остаются отдельными.
    «пресс-» + «релиза» склеиваются без пробела."""
    out: list[str] = []
    for line in block:
        if out and not _tabular(line) and not _tabular(out[-1]) and not _BULLET.match(line):
            sep = "" if re.search(r"[^\W\d_]-$", out[-1]) else " "
            out[-1] = out[-1] + sep + line
        else:
            out.append(line)
    return out


def _is_disclaimer(blocks: list[list[str]]) -> bool:
    head = " ".join(" ".join(b) for b in blocks[:2])[:200]
    return any(h in _norm(head) for h in DISCLAIMER_HEADS)


def _boilerplate_keys(pages: list[list[list[str]]], zone: int = 3) -> set[str]:
    """Колонтитулы: ячейки, которые стоят в первых/последних строках на многих страницах документа."""
    content = [p for p in pages if p]
    seen: Counter[str] = Counter()
    for blocks in content:
        lines = [x for b in blocks for x in b]
        keys = {_key(c) for x in lines[:zone] + lines[-zone:] for c in _cells(x)}
        seen.update(k for k in keys if len(k) >= 5)
    need = max(2, round(0.5 * len(content)))
    return {k for k, n in seen.items() if n >= need}


def _drop_boilerplate(blocks: list[list[str]], keys: set[str], zone: int = 3) -> list[list[str]]:
    lines = [(bi, li) for bi, b in enumerate(blocks) for li in range(len(b))]
    edge = set(lines[:zone] + lines[-zone:])
    out = []
    for bi, b in enumerate(blocks):
        kept = []
        for li, line in enumerate(b):
            if (bi, li) in edge:
                cells = [c for c in _cells(line) if _key(c) not in keys]
                line = " | ".join(cells)
            if line and not ((bi, li) in edge and _numeric(line) and len(line) <= 3):  # номер страницы
                kept.append(line)
        if kept:
            out.append(kept)
    return out


def clean_pages(pages: list[Page], title_pages: tuple[int, ...] = ()) -> list[Page]:
    """Очищенный текст страниц: абзацы через пустую строку, строки таблиц - через перевод строки."""
    parsed = [_blocks(p.text) for p in pages]
    names = _contact_names([b for blocks in parsed for b in blocks])
    staged: list[list[list[str]]] = []
    for blocks in parsed:
        if not blocks or _is_disclaimer(blocks):
            staged.append([])
            continue
        blocks = [_strip_footer(b) for b in blocks]
        blocks = [_drop_chart_noise(_drop_contacts(b, names)) for b in blocks]
        staged.append([b for b in blocks if b])
    keys = _boilerplate_keys(staged)
    texts = []
    for blocks in staged:
        blocks = _drop_boilerplate(blocks, keys)
        text = "\n\n".join("\n".join(_join(b)) for b in blocks)
        texts.append(text)
    # страницы-заставки (короткий текст) приклеиваются к следующей содержательной странице
    for i, text in enumerate(texts):
        short = 0 < len(text) < TITLE_PAGE_CHARS or pages[i].page in title_pages
        nxt = next((j for j in range(i + 1, len(texts)) if texts[j]), None)
        if text and short and nxt is not None:
            texts[nxt] = f"{text}\n\n{texts[nxt]}"
            texts[i] = ""
    return [Page(p.page, t if len(t) >= MIN_PAGE_CHARS else "", p.source) for p, t in zip(pages, texts, strict=True)]


# ---------- чанки ----------

def _split_long(paragraph: str, size: int) -> list[str]:
    out, cur = [], ""
    for sent in _SENTENCE_END.split(paragraph):
        if cur and len(cur) + 1 + len(sent) > size:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur:
        out.append(cur)
    return out


def chunk_page(text: str, size: int = CHUNK_CHARS, min_size: int = MIN_CHUNK_CHARS) -> list[str]:
    """Чанки ~size символов из абзацев одной страницы; страница не пересекается."""
    units: list[str] = []
    for para in (p.strip() for p in text.split("\n")):
        if para:
            units += _split_long(para, size) if len(para) > size else [para]
    chunks, cur = [], ""
    for u in units:
        if cur and len(cur) + 1 + len(u) > size:
            chunks.append(cur)
            cur = u
        else:
            cur = f"{cur}\n{u}" if cur else u
    if cur:
        if chunks and len(cur) < min_size and len(chunks[-1]) + len(cur) < size * 1.3:
            chunks[-1] = f"{chunks[-1]}\n{cur}"
        else:
            chunks.append(cur)
    return chunks


# ---------- метаданные ----------

def detect_date(text: str, today: date | None = None) -> date | None:
    """Дата выпуска: самая частая из дат текста не позже сегодняшней (при равенстве - первая).
    Будущие даты - это сроки погашения и заседаний."""
    today = today or date.today()
    found = []
    for m in _DATE.finditer(text):
        try:
            d = date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            continue
        if d <= today:
            found.append(d)
    if not found:
        return None
    counts = Counter(found)
    return max(found, key=lambda d: (counts[d], -found.index(d)))


def detect_factors(text: str, min_hits: int = 3, top: int = 6) -> list[str]:
    """Факторы таксономии по ключевым словам (для документов вне манифеста).
    Импорт отложенный: retriever сам импортирует этот модуль."""
    from app.rag.retriever import tokenize

    tokens = tokenize(text)
    joined = " " + " ".join(tokens) + " "
    hits = {}
    for code, f in FACTORS.items():
        n = sum(joined.count(" " + " ".join(tokenize(kw)) + " ") for kw in f.keywords if tokenize(kw))
        if n >= min_hits:
            hits[code] = n
    return sorted(hits, key=hits.get, reverse=True)[:top]


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    d = date.fromisoformat(str(value)[:10])
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def manifest_path(directory: str | Path) -> Path:
    return Path(directory) / MANIFEST_NAME


_manifest_cache: dict[str, tuple[float, dict]] = {}


def read_manifest(directory: str | Path = DEFAULT_DIR) -> dict:
    """manifest.json целиком (кешируется до изменения файла); нет файла - пустой манифест."""
    path = manifest_path(directory)
    if not path.exists():
        return {"documents": []}
    key, mtime = str(path.resolve()), path.stat().st_mtime
    cached = _manifest_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _manifest_cache[key] = (mtime, data)
    return data


def manifest_entries(directory: str | Path = DEFAULT_DIR) -> dict[str, dict]:
    return {nfc(d["file"]): d for d in read_manifest(directory).get("documents", [])}


def auto_entry(pdf: Path, pages: list[Page] | None = None) -> dict:
    """Метаданные документа вне манифеста: дата и факторы по тексту, название - первая строка."""
    pages = pages if pages is not None else clean_pages(raw_pages(pdf))
    published = detect_date("\n".join(p.text for p in raw_pages(pdf)))
    head = next((p.text for p in pages if p.text), "")
    title = next((x for x in head.split("\n") if len(x.split()) >= 3 and not _DATE.search(x)), pdf.stem)[:200]
    stale = bool(published and (date.today() - published).days > STALE_AFTER_DAYS)
    return {
        "file": nfc(pdf.name), "doc_id": doc_id_for(pdf.name), "title": title,
        "date": published.isoformat() if published else None, "date_estimated": False,
        "type": "unknown", "stale": stale, "stale_reason": "старше года" if stale else None,
        "factors": detect_factors("\n".join(p.text for p in pages)), "in_case_list": False, "needs_review": True,
    }


def prepare(pdf: Path, entry: dict | None = None) -> Document:
    entry = entry or {}
    raw = raw_pages(pdf)
    pages = clean_pages(raw, tuple(entry.get("title_pages") or ()))
    if not entry:
        entry = auto_entry(pdf, pages)
    topics = [f for f in entry.get("factors") or [] if f in FACTOR_CODES]
    return Document(file=pdf, doc_id=doc_id_for(pdf.name), title=entry.get("title") or pdf.stem,
                    published_at=_parse_date(entry.get("date")), topics=topics,
                    stale=bool(entry.get("stale")), pages=pages, entry=entry, alt_pages=alt_page_texts(pdf, raw))


def documents(directory: str | Path = DEFAULT_DIR) -> list[Document]:
    d = Path(directory)
    entries = manifest_entries(d)
    return [prepare(pdf, entries.get(nfc(pdf.name))) for pdf in sorted(d.glob("*.pdf"))]


def quality(pdf: Path, title_pages: tuple[int, ...] = ()) -> dict:
    """Качество извлечения: текстовый слой PDF, страницы-картинки, источник и объём текста после очистки."""
    raw = raw_pages(pdf)
    pdf_chars = [len(t.strip()) for t in pdf_page_texts(pdf)]
    clean = clean_pages(raw, title_pages)
    sources = Counter(p.source for p in raw)
    return {
        "pages": len(raw),
        "pdf_text_chars": sum(pdf_chars),
        "image_only_pages": sum(1 for c in pdf_chars if c < MIN_TEXT_CHARS),
        "page_sources": dict(sources),
        "raw_chars": sum(len(p.text) for p in raw),
        "clean_chars": sum(len(p.text) for p in clean),
        "clean_chars_per_page": [len(p.text) for p in clean],
        "empty_pages_after_clean": [p.page for p in clean if not p.text],
        "chunks": sum(len(chunk_page(p.text)) for p in clean),
    }


def build_manifest(directory: str | Path = DEFAULT_DIR) -> dict:
    """Обновляет вычисляемые поля манифеста (doc_id, sha256, страницы, источник текста, качество),
    сохраняя проверенные вручную (title, date, type, stale, factors). Новые файлы - needs_review."""
    d = Path(directory)
    old = read_manifest(d)
    entries = manifest_entries(d)
    docs = []
    for pdf in sorted(d.glob("*.pdf")):
        entry = dict(entries.get(nfc(pdf.name)) or auto_entry(pdf))
        q = quality(pdf, tuple(entry.get("title_pages") or ()))
        sources = q["page_sources"]
        raw = raw_pages(pdf)
        entry.update({
            "file": nfc(pdf.name), "doc_id": doc_id_for(pdf.name), "sha256": file_sha256(pdf),
            "pages": q["pages"],
            "text_source": next(iter(sources)) if len(sources) == 1 else "mixed",
            "page_sources": {src: [p.page for p in raw if p.source == src] for src in sources},
            "quality": {k: q[k] for k in ("pdf_text_chars", "image_only_pages", "raw_chars", "clean_chars",
                                          "empty_pages_after_clean", "chunks")},
        })
        docs.append(entry)
    out = {k: v for k, v in old.items() if k != "documents"} | {"documents": docs}
    manifest_path(d).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _manifest_cache.pop(str(manifest_path(d).resolve()), None)
    return out


# ---------- загрузка в БД ----------

def _same_date(a: datetime | None, b: datetime | None) -> bool:
    return (a.date() if a else None) == (b.date() if b else None)


def _unchanged(db: Session, row: AnalyticsDoc, doc: Document, chunks: list[tuple[int, str]]) -> bool:
    if (row.title, row.file_path, list(row.topics or [])) != (doc.title, str(doc.file), doc.topics):
        return False
    if not _same_date(row.published_at, doc.published_at):
        return False
    stored = db.query(AnalyticsChunk.page, AnalyticsChunk.text).filter_by(doc_id=row.doc_id).order_by(AnalyticsChunk.chunk_id).all()
    return [(p, t) for p, t in stored] == chunks


def load_dir(db: Session, directory: str = DEFAULT_DIR) -> int:
    """Загружает/обновляет документы папки. Возвращает число (пере)загруженных документов."""
    d = Path(directory)
    entries = manifest_entries(d)
    changed = 0
    for pdf in sorted(d.glob("*.pdf")):
        entry = entries.get(nfc(pdf.name))
        if entry and entry.get("sha256") and entry["sha256"] != file_sha256(pdf):
            log.warning("%s изменился после составления манифеста: проверьте метаданные и OCR", pdf.name)
        doc = prepare(pdf, entry)
        chunks = doc.chunks()
        row = db.get(AnalyticsDoc, doc.doc_id)
        if row is not None and _unchanged(db, row, doc, chunks):
            continue
        if row is None:
            row = AnalyticsDoc(doc_id=doc.doc_id)
            db.add(row)
        else:
            db.query(AnalyticsChunk).filter_by(doc_id=doc.doc_id).delete(synchronize_session=False)
        row.title, row.file_path, row.published_at, row.topics = doc.title, str(doc.file), doc.published_at, doc.topics
        db.flush()
        db.add_all(AnalyticsChunk(doc_id=doc.doc_id, page=page, text=text) for page, text in chunks)
        changed += 1
        log.info("%s: %s чанков, %s", pdf.name, len(chunks), Counter(p.source for p in doc.pages))
    db.commit()
    return changed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--manifest", action="store_true", help="обновить вычисляемые поля manifest.json")
    parser.add_argument("--report", action="store_true", help="качество извлечения по документам")
    parser.add_argument("--dump", help="записать очищенный текст страниц в эту папку (для проверки)")
    args = parser.parse_args()
    if args.manifest:
        build_manifest(args.dir)
    if args.report:
        for pdf in sorted(Path(args.dir).glob("*.pdf")):
            print(pdf.name, json.dumps(quality(pdf), ensure_ascii=False))
    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        for doc in documents(args.dir):
            (out / f"{doc.file.stem}.txt").write_text(
                "".join(f"=== page {p.page} [{p.source}] ===\n{p.text}\n\n" for p in doc.pages), encoding="utf-8")
    if not (args.manifest or args.report or args.dump):
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            print("loaded:", load_dir(db, args.dir))


if __name__ == "__main__":
    main()
