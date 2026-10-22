"""Аналитика банка: очистка и чанки PDF, манифест, позиции с проверкой цитат, BM25-поиск."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AnalyticsChunk, AnalyticsDoc, NewsItem
from app.db.session import Base
from app.ingestion import analytics_loader as al
from app.ml import bank_positions as bp
from app.rag import retriever

FOOTER = ("Альфа-Банк, 2026 г. Все права защищены. Генеральная лицензия ЦБ РФ № 1326 от 16.01.2015 г. "
          "Настоящее письмо и содержащаяся в нем информация\nявляются исключительной собственностью Альфа-Банка.")
DISCLAIMER = ("Контакты и дисклеймер\n\n© Альфа-Банк, 2026 г. Все права защищены.\n\n"
              "Данный материал предназначен АО «Альфа-Банк» для распространения в Российской\n"
              "Федерации. Он не предназначен для распространения среди частных инвесторов.")
PAGE1 = f"""Центр макроэкономического анализа

Наталия Орлова,
Norlova@alfabank.ru
11 сентября 2026 г. | Валерия Кобяк,
VKobyak@alfabank.ru
Ключевая ставка ЦБ РФ

Мы ожидаем сохранения паузы на заседании 23 октября: С учетом риторики ЦБ РФ мы меняем наш взгляд
на динамику ключевой ставки на этот год. Если раньше мы ориентировались на ставку на уровне 13,5% на конец
2026 г., то теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года.

{FOOTER}
1"""
PAGE2 = """Центр макроэкономического анализа

Табл.1: Основные макроэкономические показатели
2019 2020 2021 2022 2023 2024 2025 2026П 2027П
Ставка, конец года, % | 6,3% 4,3% 8,5% 7,5% 16,0% 21,0% 16,0% 14,0% 12,0%

Рис. 1: Динамика инфляции
0,40
0,35
- 0,30
1,10 | 0,20
2"""


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[AnalyticsDoc.__table__, AnalyticsChunk.__table__, NewsItem.__table__])
    retriever._cache.clear()
    with Session(engine) as s:
        yield s
    retriever._cache.clear()


def _pages(*texts: str) -> list[al.Page]:
    return [al.Page(i, t, "ocr_sidecar") for i, t in enumerate(texts, start=1)]


def _blank_pdf(path: Path, pages: int) -> Path:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    with path.open("wb") as f:
        w.write(f)
    return path


# ---------- очистка и чанки ----------

def test_clean_pages_removes_boilerplate_and_keeps_content():
    clean = al.clean_pages(_pages(PAGE1, PAGE2, DISCLAIMER))
    text = "\n".join(p.text for p in clean)
    for junk in ("Центр макроэкономического анализа", "alfabank.ru", "Орлова", "Кобяк", "Все права защищены",
                 "исключительной собственностью", "частных инвесторов", "0,35"):
        assert junk not in text, junk
    assert "11 сентября 2026 г." in clean[0].text
    assert "мы ожидаем ее сохранения на текущем значении 14,0% до конца года" in clean[0].text  # строки склеены
    assert "2019 2020 2021 2022 2023 2024 2025 2026П 2027П" in clean[1].text  # шапка таблицы - не шум
    assert "Ставка, конец года, % | 6,3%" in clean[1].text
    assert clean[2].text == ""  # страница дисклеймера
    assert not clean[0].text.rstrip().endswith("1")  # номер страницы


def test_title_page_is_merged_into_next_page():
    body = "Банки - основные инвесторы на рынке ОФЗ. " * 10
    clean = al.clean_pages(_pages("ОФЗ - неиссякаемый источник", body))
    assert clean[0].text == ""
    assert clean[1].text.startswith("ОФЗ - неиссякаемый источник")


def test_chunks_keep_page_and_size():
    para = "Мы полагаем, что динамика потребления сейчас находится на пике. " * 12
    doc = al.Document(file=Path("x.pdf"), doc_id="d", title="T", published_at=None, topics=[], stale=False,
                      pages=_pages(f"{para}\n\n{para}\n\n{para}", "Короткий вывод банка: ставка останется 14,0%. " * 3))
    chunks = doc.chunks()
    assert {p for p, _ in chunks} == {1, 2}
    assert all(len(t) <= al.CHUNK_CHARS * 1.3 for _, t in chunks)
    page1 = "".join(t for p, t in chunks if p == 1).replace("\n", " ")
    assert page1.count("находится на пике") == 36  # ничего не потеряно и не задвоено


def test_doc_id_is_sha1_of_file_name():
    assert al.doc_id_for("ALFA-7M26.pdf") == hashlib.sha1(b"ALFA-7M26.pdf").hexdigest()[:12]


def test_detect_date_skips_future_maturities():
    text = "погашение 17 сентября 2031 г.\n14 сентября 2026\nитоги\n14 сентября 2026"
    assert al.detect_date(text, today=datetime(2026, 10, 21).date()).isoformat() == "2026-09-14"


# ---------- загрузка: манифест, источник текста, идемпотентность ----------

def _bank_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bank"
    d.mkdir()
    _blank_pdf(d / "rate.pdf", 2)
    al.write_sidecar(al.sidecar_path(d / "rate.pdf"), {1: PAGE1, 2: PAGE2})
    manifest = {"documents": [{"file": "rate.pdf", "title": "Ключевая ставка ЦБ РФ: пауза", "date": "2026-09-11",
                               "type": "key_rate_decision", "stale": False, "factors": ["key_rate", "inflation", "bogus"]}]}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return d


def test_load_dir_uses_manifest_and_is_idempotent(db, tmp_path):
    d = _bank_dir(tmp_path)
    assert al.load_dir(db, str(d)) == 1
    doc = db.get(AnalyticsDoc, al.doc_id_for("rate.pdf"))
    assert doc.title == "Ключевая ставка ЦБ РФ: пауза"
    assert doc.published_at.date().isoformat() == "2026-09-11"
    assert doc.topics == ["key_rate", "inflation"]  # неизвестный фактор отброшен
    pages = {c.page for c in db.query(AnalyticsChunk).all()}
    assert pages == {1, 2}

    assert al.load_dir(db, str(d)) == 0  # ничего не изменилось
    al.write_sidecar(al.sidecar_path(d / "rate.pdf"), {1: PAGE1.replace("14,0%", "14,5%"), 2: PAGE2})
    assert al.load_dir(db, str(d)) == 1  # изменился текст - документ перезагружен
    texts = " ".join(c.text for c in db.query(AnalyticsChunk).all())
    assert "14,5%" in texts and "текущем значении 14,0%" not in texts
    assert db.query(AnalyticsDoc).count() == 1


def test_raw_pages_prefer_vlm_then_ocr(tmp_path):
    pdf = _blank_pdf(tmp_path / "a.pdf", 3)
    al.write_sidecar(al.sidecar_path(pdf), {1: "OCR one " * 10, 2: "OCR two " * 10})
    al.write_sidecar(al.sidecar_path(pdf, vlm=True), {2: "VLM two " * 10})
    assert [p.source for p in al.raw_pages(pdf)] == ["ocr_sidecar", "vlm_ocr", "none"]


def test_document_without_manifest_gets_auto_metadata(tmp_path):
    pdf = _blank_pdf(tmp_path / "new.pdf", 2)
    al.write_sidecar(al.sidecar_path(pdf), {1: PAGE1, 2: PAGE2})
    doc = al.prepare(pdf)
    assert doc.published_at.date().isoformat() == "2026-09-11"
    assert "key_rate" in doc.topics
    assert doc.entry["needs_review"] is True


# ---------- позиции: проверка цитат и чисел ----------

PAGE_TEXT = ("Мы ожидаем сохранения паузы на заседании 23 октября: С учетом риторики ЦБ РФ мы меняем наш взгляд на "
             "динамику ключевой ставки на этот год. Если раньше мы ориентировались на ставку на уровне 13,5% на "
             "конец 2026 г., то теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года. При этом "
             "наш прогноз по ставке на конец 2027 г. остается на уровне 12,0%. Ослабление курса рубля, на наш "
             "взгляд, продолжит воздействовать на динамику цен в непродовольственном сегменте.")


@pytest.mark.parametrize("quote", [
    "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года",
    "теперь  мы ожидаем ее\nсохранения на текущем значении 14,0 % до конца года.",   # пробелы, перенос строки
    "«теперь мы ожидаем её сохранения на текущем значении 14,0% до конца года»",     # кавычки, ё
])
def test_locate_quote_exact_after_normalization(quote):
    span, kind = bp.locate_quote(quote, PAGE_TEXT)
    assert kind == "exact"
    assert span in PAGE_TEXT


def test_locate_quote_fuzzy_returns_page_text_and_rejects_paraphrase():
    span, kind = bp.locate_quote("теперь мы ожидаем ее сохранения на текушем значении 14,0% до конца года", PAGE_TEXT)
    assert kind == "fuzzy" and "текущем значении" in span  # цитатой становится текст страницы
    assert bp.locate_quote("банк думает, что ставка будет 14% весь год", PAGE_TEXT) is None


def test_check_position_numbers_must_be_on_page():
    pages = {1: PAGE_TEXT, 2: "Другая страница без нужных чисел, но с достаточным количеством текста."}
    good = {"page": 2, "factors": ["key_rate"], "thesis": "Банк ожидает ставку 14,0% до конца 2026 года.",
            "quote": "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года",
            "forecast": {"metric": "key_rate_eoy", "value": "14,0%", "horizon": "2026"}}
    pos, reasons = bp.check_position(good, pages)
    assert reasons == [] and pos["page"] == 1 and pos["checks"]["page_corrected"]  # номер страницы исправлен
    assert pos["forecast"]["label"] == bp.METRICS["key_rate_eoy"]
    bad = good | {"page": 1, "thesis": "Банк ожидает ставку 13,0% на конец 2026 года."}
    pos, reasons = bp.check_position(bad, pages)
    assert pos is None and reasons[0].startswith("numbers_not_on_page") and "13,0" in reasons[0]
    pos, reasons = bp.check_position(good | {"factors": ["unknown"]}, pages)
    assert reasons == ["no_valid_factors"]


def test_check_position_cross_checks_second_ocr():
    raw = {"page": 1, "factors": ["key_rate"], "thesis": "Банк ожидает ставку 14,0% до конца года.",
           "quote": "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года"}
    shuffled = " | ".join(reversed(PAGE_TEXT.split(". ")))  # колонки перемешаны, слова те же
    pos, reasons = bp.check_position(raw, {1: PAGE_TEXT}, {1: shuffled})
    assert reasons == [] and pos["checks"]["second_ocr"] == 1.0
    pos, reasons = bp.check_position(raw, {1: PAGE_TEXT}, {1: "Совсем другой текст: прогноз 14,0% по ставке ЦБ."})
    assert pos is None and reasons[0].startswith("quote_not_confirmed_by_second_ocr")


class FakeLLM:
    def __init__(self, payload: dict):
        self.payload, self.calls = payload, []

    def structured(self, messages, schema, complexity="light", **kwargs):
        self.calls.append({"messages": messages, "complexity": complexity, **kwargs})
        return schema.model_validate(self.payload), {"model": "fake", "tokens_in": 10, "tokens_out": 5,
                                                     "cost_rub": 0.01, "cached": False}


def _doc(text: str = PAGE_TEXT, date: str = "2026-09-11", doc_id: str = "d1") -> al.Document:
    return al.Document(file=Path(f"{doc_id}.pdf"), doc_id=doc_id, title="Ключевая ставка", published_at=None,
                       topics=["key_rate"], stale=False, pages=[al.Page(1, text, "ocr_sidecar")],
                       entry={"date": date, "type": "key_rate_decision"})


def test_extract_document_grounds_and_rejects():
    llm = FakeLLM({"positions": [
        {"page": 1, "factors": ["key_rate"], "thesis": "Банк ожидает сохранения ставки 14,0% до конца 2026 года.",
         "quote": "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года",
         "forecast": {"metric": "key_rate_eoy", "value": "14,0%", "horizon": "2026"}},
        {"page": 1, "factors": ["fx"], "thesis": "Банк ждёт ослабления рубля.",
         "quote": "рубль ослабнет до 100 за доллар к концу года", "forecast": None},
        {"page": 1, "factors": ["key_rate"], "thesis": "Банк ждёт ставку 11% на конец 2027 года.",
         "quote": "наш прогноз по ставке на конец 2027 г. остается на уровне 12,0%", "forecast": None},
    ]})
    accepted, rejected, info = bp.extract_document(llm, _doc(), complexity="research")
    assert [p["thesis"] for p in accepted] == ["Банк ожидает сохранения ставки 14,0% до конца 2026 года."]
    p = accepted[0]
    assert p["position_id"].startswith("d1-p1-") and p["date"] == "2026-09-11" and p["superseded_by"] is None
    assert sorted(r["reasons"][0].split(":")[0] for r in rejected) == ["numbers_not_on_page", "quote_not_found"]
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "UNTRUSTED_SOURCE" in prompt and "=== Страница 1 ===" in prompt
    assert llm.calls[0]["complexity"] == "research" and info["model"] == "fake"


def test_link_forecasts_marks_superseded_and_passed_horizons():
    def pos(pid, date, metric, horizon):
        return {"position_id": pid, "date": date, "forecast": {"metric": metric, "value": "x", "horizon": horizon}}
    ps = [pos("old", "2026-07-31", "key_rate_eoy", "2026"), pos("new", "2026-09-11", "key_rate_eoy", "2026"),
          pos("mid", "2026-08-05", "key_rate_eoy", "2026"), pos("other", "2026-07-31", "key_rate_eoy", "2027"),
          pos("july", "2026-07-22", "key_rate_decision", "2026-07-24")]
    bp.link_forecasts(ps)
    by = {p["position_id"]: p for p in ps}
    assert by["old"]["superseded_by"] == "new" and by["mid"]["superseded_by"] == "new"
    assert by["new"]["superseded_by"] is None and by["other"]["superseded_by"] is None
    assert by["july"]["horizon_passed"] and not by["new"]["horizon_passed"]


def test_build_writes_positions_file_and_load_positions(tmp_path, monkeypatch):
    d = _bank_dir(tmp_path)
    out = d / "positions.json"
    llm = FakeLLM({"positions": [{"page": 1, "factors": ["key_rate"], "thesis": "Банк ожидает ставку 14,0% до конца года.",
                                  "quote": "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года"}]})
    data = bp.build(llm, d, out)
    assert data["grounding"] == {"extracted": 1, "accepted": 1, "pass_rate": 1.0}
    assert data["documents"][0]["title"] == "Ключевая ставка ЦБ РФ: пауза"
    loaded = bp.load_positions(out)
    assert loaded[0]["doc_id"] == al.doc_id_for("rate.pdf")
    assert bp.load_positions(out) is loaded  # кеш в процессе


def test_clean_vlm_text_drops_empty_rows_and_loops():
    raw = "Заголовок\n| | a | b |\n|---|---|---|\n| | | |\n| | | |\n" + "| x | | |\n" * 5
    assert bp.clean_vlm_text(raw) == "Заголовок\n| | a | b |\n| x | | |\n| x | | |"


# ---------- поиск ----------

def test_tokenize_handles_russian_morphology():
    assert retriever.tokenize("ключевой ставки") == retriever.tokenize("Ключевая ставка")
    assert retriever.tokenize("рынка труда") == retriever.tokenize("рынок труда")
    assert retriever.tokenize("курс рубля") == retriever.tokenize("курса рубль")
    assert retriever.tokenize("ставка 14,0%") == ["ставк", "14"]
    assert retriever.tokenize("и в на по") == []


def _chunks(db, *items: tuple[str, int, str, str]) -> None:
    for doc_id, page, text, date in items:
        if not db.get(AnalyticsDoc, doc_id):
            db.add(AnalyticsDoc(doc_id=doc_id, title=f"Doc {doc_id}", published_at=datetime.fromisoformat(date).replace(tzinfo=UTC),
                                topics=["key_rate"] if "ставк" in text else ["consumption"]))
            db.flush()
        db.add(AnalyticsChunk(doc_id=doc_id, page=page, text=text))
    db.commit()


REQUIRED = {"doc_id", "title", "page", "text", "kind", "factors", "published_at", "stale", "score"}


def test_search_bank_analytics_finds_morphological_forms(db, tmp_path):
    _chunks(db, ("a", 1, "ЦБ сохранил ключевую ставку на уровне 14,0%, мы ожидаем паузы", "2026-09-11"),
            ("b", 1, "Потребление на пике: рост розничных продаж замедлится", "2026-08-05"),
            ("b", 2, "Рынок труда остаётся жёстким, безработица 2,2%", "2026-08-05"))
    res = retriever.search_bank_analytics(db, "ключевой ставки", 3, positions_path=tmp_path / "none.json")
    assert res[0]["doc_id"] == "a" and res[0]["kind"] == "chunk"
    assert REQUIRED <= set(res[0]) and res[0]["published_at"] == "2026-09-11" and res[0]["stale"] is False
    assert retriever.search_bank_analytics(db, "рынка труда", positions_path=tmp_path / "none.json")[0]["page"] == 2
    assert retriever.search_bank_analytics(db, "криптовалюта", positions_path=tmp_path / "none.json") == []
    assert retriever.search_bank_analytics(db, "ключевая ставка", 4)  # старая сигнатура (db, query, k)


def _positions_file(tmp_path: Path, positions: list[dict], docs: list[dict]) -> Path:
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"documents": docs, "positions": positions}, ensure_ascii=False), encoding="utf-8")
    return path


def _position(pid, doc_id, page, factors, thesis, quote, date, **kw):
    return {"position_id": pid, "doc_id": doc_id, "page": page, "factors": factors, "thesis": thesis, "quote": quote,
            "forecast": None, "date": date, "superseded_by": None} | kw


def test_factor_boost_and_dedup_prefer_positions(db, tmp_path):
    _chunks(db, ("a", 1, "Мы ожидаем сохранения ставки 14,0%: ключевая ставка, ставка ЦБ, ставка", "2026-09-11"),
            ("b", 3, "Потребительский спрос и розничные продажи замедлятся во втором полугодии", "2026-08-05"))
    path = _positions_file(tmp_path, [
        _position("pa", "a", 1, ["key_rate"], "Банк ожидает сохранения ставки 14,0% до конца года.",
                  "мы ожидаем сохранения ставки 14,0%", "2026-09-11"),
        _position("pb", "b", 3, ["consumption"], "Банк ждёт замедления потребления: ставка высокая.",
                  "потребление замедлится", "2026-08-05"),
    ], [{"doc_id": "a", "title": "Ставка", "stale": False}, {"doc_id": "b", "title": "Потребление", "stale": False}])
    res = retriever.search_bank_analytics(db, "ставка", 4, factors=["consumption"], positions_path=path)
    assert res[0]["position_id"] == "pb"  # факторный буст сильнее лексики
    assert [r["kind"] for r in res] == ["position", "position"]  # чанки тех же страниц заменены позициями
    assert {"position_id", "forecast", "superseded_by"} <= set(res[0]) and REQUIRED <= set(res[0])
    assert "Цитата (стр. 3)" in res[0]["text"]
    res = retriever.search_bank_analytics(db, "ставка", 4, positions_path=path)
    assert res[0]["position_id"] == "pa"


def test_stale_and_superseded_positions_rank_lower(db, tmp_path):
    path = _positions_file(tmp_path, [
        _position("old", "o", 1, ["key_rate"], "Банк ожидает ставку 13,5% на конец года.", "ставка 13,5% на конец года",
                  "2026-07-31", superseded_by="new"),
        _position("new", "n", 1, ["key_rate"], "Банк ожидает ставку 14,0% на конец года.", "ставка 14,0% на конец года",
                  "2026-09-11"),
        _position("st", "s", 1, ["key_rate"], "Банк ожидает ставку 4,5% на конец года.", "ставка 4,5% на конец года",
                  "2021-04-15"),
    ], [{"doc_id": "o", "title": "1П26", "stale": False}, {"doc_id": "n", "title": "Ставка", "stale": False},
        {"doc_id": "s", "title": "2021", "stale": True}])
    res = retriever.search_bank_analytics(db, "ставка на конец года", 3, factors=["key_rate"], positions_path=path)
    assert [r["position_id"] for r in res] == ["new", "old", "st"]
    assert res[1]["superseded_by"] == "new" and res[2]["stale"] is True


def test_search_news_bm25_recent_window(db):
    now = datetime.now(UTC)
    for nid, title, summary, age in [
        ("n1", "ЦБ сохранил ключевую ставку", "Банк России оставил ставку 14%", 1),
        ("n2", "Цены на сталь растут", "Металлурги повышают цены", 2),
        ("n3", "Ключевая ставка: архив", "Старая новость про ставку", 90),
    ]:
        db.add(NewsItem(news_id=nid, source="rss", url=f"https://x/{nid}", title=title, summary=summary,
                        dedup_hash=nid, published_at=now - timedelta(days=age)))
    db.commit()
    res = retriever.search_news(db, "ключевая ставка", k=5)
    assert [r["news_id"] for r in res] == ["n1"]  # n3 вне окна
    assert set(res[0]) == {"news_id", "title", "url", "source", "published_at", "summary", "score"}
    assert retriever.search_news(db, "цен на стали")[0]["news_id"] == "n2"
    assert retriever.search_news(db, "") == []
