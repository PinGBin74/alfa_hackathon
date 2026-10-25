"""Детерминированная проверка обоснованности: каждое число в утверждении должно найтись в источнике.

Главный источник фактологических ошибок LLM - выдуманные или искажённые цифры. Проверка дешёвая
и не зависит от модели: «14%» в выводе должно быть в новости или в аналитике банка; округление
до целого или до одного-двух знаков допускается («62 млрд» при «62,3 млрд» в источнике).
"""
import re
from datetime import date, datetime

MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря")
# Месяц в любой форме: «сентябрь», «сентября», «в сентябре», «сентябрьский». «Май» - отдельно, иначе «маржа».
_MONTH = re.compile(r"\b(?:(январ|феврал|март|апрел|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*|(ма[йяе]))\b",
                    re.IGNORECASE)
_MONTH_NO = {stem: i for i, stem in enumerate(
    ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"), 1)}

_NUM =re.compile(r"(?<![\w.,])\d+(?:[   ]\d{3}(?!\d))*(?:[.,]\d+)?")


def numbers(text: str | None) -> list[tuple[str, float]]:
    """(как в тексте, значение). Знак не учитываем: «−0,01%» и «0,01%» - одно и то же число."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0)
        try:
            out.append((raw, float(re.sub(r"[   ]", "", raw).replace(",", "."))))
        except ValueError:
            continue
    return out


def _same(claim: float, source: float) -> bool:
    return any(abs(claim - v) < 1e-9 for v in (source, round(source), round(source, 1), round(source, 2)))


def ungrounded(claim: str, source: str, skip_small_ints: bool = False) -> list[str]:
    """Числа из claim, которых нет в source. skip_small_ints - не проверять целые < 10 («2 фактора»)."""
    src = [v for _, v in numbers(source)]
    missing = []
    for raw, value in numbers(claim):
        if skip_small_ints and value.is_integer() and value < 10:
            continue
        if not any(_same(value, s) for s in src):
            missing.append(raw)
    return missing


def parse_date(value) -> date | None:
    """Дата из ISO-строки («2026-09-11», «2026-09-11T08:00:00+00:00») или date/datetime."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def ru_date(value) -> str:
    """«11 сентября 2026» - так модель читает и цитирует даты; пустая строка, если даты нет."""
    d = parse_date(value)
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}" if d else ""


def months(text: str | None) -> dict[int, str]:
    """Упомянутые месяцы: {номер: как в тексте}."""
    out: dict[int, str] = {}
    for m in _MONTH.finditer(text or ""):
        stem = (m.group(1) or "ма").lower()
        out.setdefault(_MONTH_NO[stem], m.group(0))
    return out


def ungrounded_months(claim: str, source: str) -> list[str]:
    """Месяцы из claim, которых нет в source (в тексте или в дате публикации, добавленной к тексту)."""
    known = months(source)
    return [raw for no, raw in months(claim).items() if no not in known]
