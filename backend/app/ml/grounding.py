"""Детерминированная проверка обоснованности: каждое число в утверждении должно найтись в источнике.

Главный источник фактологических ошибок LLM - выдуманные или искажённые цифры. Проверка дешёвая
и не зависит от модели: «14%» в выводе должно быть в новости или в аналитике банка; округление
до целого или до одного-двух знаков допускается («62 млрд» при «62,3 млрд» в источнике).
"""
import re

_NUM = re.compile(r"(?<![\w.,])\d+(?:[   ]\d{3}(?!\d))*(?:[.,]\d+)?")


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
