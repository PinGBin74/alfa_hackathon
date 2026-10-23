"""Самопроверка: полнота, непротиворечивость, обоснованность.

Два слоя:
1. `verify` - детерминированные проверки без LLM: ссылки только на найденные источники, числа в фактах
   и позиции банка есть в цитируемом тексте, каждый пункт «почему важно» опирается на признаки клиента,
   позиция банка не пропущена, если она найдена.
2. `review` - LLM-фактчекер на другой модели (DeepSeek), чем автор черновика (GLM): ловит пересказ,
   неверную атрибуцию банку, противоречия, устаревшие прогнозы. Без reasoning: 8 с и ~0,18 ₽ против 35-60 с
   и ~0,5 ₽ с ним при той же строгости на контрольном черновике (замер 21.10).
"""
import json
import re
from pathlib import Path

from app.agent.llm_client import LLMClient, LLMError, json_instruction
from app.agent.schemas import Issue, Verdict
from app.agent.state import AgentState
from app.ml.grounding import ungrounded

PROMPT = (Path(__file__).parent / "prompts" / "verifier.md").read_text(encoding="utf-8")
RESTATE_JACCARD = 0.5
# Позиции банка по этим факторам - о конкретных компаниях и решениях («кредитное качество эмитента»), а не о
# рынке: найденная позиция с таким фактором не значит, что инсайт обязан её использовать.
NON_MARKET_FACTORS = {"company_event", "regulation"}
_DIGITS = re.compile(r"\d")


def _words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 3}


def date_forms(value) -> str:
    """Дата источника в форматах, которыми модель её цитирует: «11.09.2026», «11.09», «2026»."""
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text.split("-")
        return f" {d}.{m}.{y} {d}.{m} {y}"
    return ""


def news_text(state: AgentState, source_id: str) -> str:
    if state.news and source_id == f"news:{state.news.get('news_id')}":
        n = state.news
        return f"{n.get('title', '')}\n{n.get('body') or ''}\n{n.get('summary') or ''}{date_forms(n.get('published_at'))}"
    for n in state.related_news:
        if source_id == f"news:{n['news_id']}":
            return f"{n.get('title', '')}\n{n.get('summary') or ''}{date_forms(n.get('published_at'))}"
    return ""


def normalize_bank_ref(bp: dict) -> None:
    """Модель видит в контексте идентификаторы bank:<doc>:<page> и часто пишет их в analytics_doc_id.
    Приводим к контракту: analytics_doc_id = <doc>, quote_ref = bank:<doc>:<page> (quote_ref приоритетнее)."""
    doc = page = None
    for value in (bp.get("quote_ref"), bp.get("analytics_doc_id")):
        parts = str(value or "").strip().split(":")
        if parts[0] == "bank" and len(parts) >= 2:
            doc = doc or parts[1]
            page = page or (parts[2] if len(parts) >= 3 else None)
    raw = str(bp.get("analytics_doc_id") or "").strip()
    doc = doc or (raw if raw and not raw.startswith("bank:") else None)
    quote = str(bp.get("quote_ref") or "").strip()
    if page is None and quote.isdigit():
        page = quote
    if doc:
        bp["analytics_doc_id"] = doc
        if page:
            bp["quote_ref"] = f"bank:{doc}:{page}"


def bank_text(state: AgentState, doc_id: str | None, quote_ref: str | None = None) -> str:
    items = [c for c in state.bank_chunks if c["doc_id"] == doc_id]
    if quote_ref:
        exact = [c for c in items if f"bank:{c['doc_id']}:{c.get('page')}" == quote_ref]
        items = exact or items
    return "\n".join((c.get("text") or "") + date_forms(c.get("published_at")) for c in items)


def _stale_ref(state: AgentState, quote_ref: str | None) -> str | None:
    """Все найденные материалы этой страницы помечены как обновлённые позже - описание пометки, иначе None."""
    items = [c for c in state.bank_chunks if f"bank:{c['doc_id']}:{c.get('page')}" == quote_ref]
    if items and all(c.get("superseded_by") for c in items):
        return "прогноз на этой странице банк обновил в более позднем материале"
    return None


def _statements(d: dict):
    for i, w in enumerate(d.get("why_it_matters") or []):
        yield f"why_it_matters[{i}]", w.get("text", ""), []
    cons = d.get("consequences") or {}
    for key in ("risks", "opportunities"):
        for i, s in enumerate(cons.get(key) or []):
            yield f"consequences.{key}[{i}]", s.get("text", ""), s.get("basis") or []
    for i, s in enumerate(d.get("ai_inference") or []):
        yield f"ai_inference[{i}]", s.get("text", ""), s.get("basis") or []
    for i, a in enumerate(d.get("suggested_actions") or []):
        yield f"suggested_actions[{i}]", a.get("text", ""), []


def check(state: AgentState) -> list[Issue]:
    """Детерминированные проверки черновика."""
    d = state.draft or {}
    known = state.source_ids()
    allowed = state.scratch.get("allowed_features", set())
    context_text = state.scratch.get("context_text", "")
    issues: list[Issue] = []

    wh = d.get("what_happened") or {}
    for i, f in enumerate(wh.get("confirmed_facts") or []):
        sid, field = f.get("source_id"), f"what_happened.confirmed_facts[{i}]"
        if str(sid).startswith("bank:"):  # переносится в bank_position при очистке
            issues.append(Issue(type="wrong_bank_attribution", field=field, blocking=False,
                                text="позиция банка указана как факт события", fix="перенести в bank_position"))
            continue
        if sid not in known:
            issues.append(Issue(type="unknown_source", field=field, text=f"источник {sid} не найден", fix="сослаться на id новости"))
        elif miss := ungrounded(f.get("text", ""), news_text(state, sid)):
            issues.append(Issue(type="wrong_number", field=field, text=f"чисел {miss} нет в новости {sid}", fix="взять цифры из текста новости"))

    for i, bp in enumerate(d.get("bank_position") or []):
        normalize_bank_ref(bp)
        field, doc = f"bank_position[{i}]", bp.get("analytics_doc_id")
        source = bank_text(state, doc, bp.get("quote_ref"))
        if not source:
            issues.append(Issue(type="wrong_bank_attribution", field=field, text=f"материал банка {doc} не был найден",
                                fix="использовать только найденные фрагменты аналитики банка"))
        elif miss := ungrounded(bp.get("text", ""), source):
            issues.append(Issue(type="wrong_number", field=field, text=f"чисел {miss} нет в материале банка {bp.get('quote_ref') or doc}",
                                fix="цифры позиции банка - только из цитируемого фрагмента"))
        elif stale := _stale_ref(state, bp.get("quote_ref")):
            # прогноз с цифрами из материала, который банк позже обновил, - ошибка; без цифр - предупреждение
            issues.append(Issue(type="stale_bank_view", field=field, blocking=bool(_DIGITS.search(bp.get("text", ""))),
                                text=f"материал {bp.get('quote_ref')}: {stale}",
                                fix="взять актуальный прогноз из более свежего материала или убрать пункт"))

    whys = d.get("why_it_matters") or []
    if not whys:
        issues.append(Issue(type="generic", field="why_it_matters", text="нет связи события с компанией",
                            fix="объяснить влияние через признаки клиента"))
    for i, w in enumerate(whys):
        if not [f for f in w.get("client_features") or [] if f in allowed]:
            issues.append(Issue(type="generic", field=f"why_it_matters[{i}]", text="нет ни одного признака клиента",
                                fix="указать признаки из блока КЛИЕНТ в client_features"))

    summary_words = _words(wh.get("summary", "") + " " + (state.news or {}).get("title", ""))
    full_context = "\n".join([context_text, news_text(state, f"news:{state.news_id}"),
                              *(news_text(state, f"news:{n['news_id']}") for n in state.related_news),
                              *(c.get("text") or "" for c in state.bank_chunks)])
    for field, text, basis in _statements(d):
        if unknown := [b for b in basis if b not in known and b not in allowed]:
            issues.append(Issue(type="unknown_source", field=field, text=f"неизвестные источники {unknown}", blocking=False))
        if miss := ungrounded(text, full_context, skip_small_ints=True):
            issues.append(Issue(type="wrong_number", field=field, text=f"чисел {miss} нет в источниках",
                                fix="не приводить цифры, которых нет в данных"))
        w = _words(text)
        if field.startswith("why_it_matters") and w and len(w & summary_words) / len(w | summary_words) > RESTATE_JACCARD:
            issues.append(Issue(type="restates_news", field=field, text="пункт пересказывает новость", blocking=False))

    focus = set(state.focus_factors) - NON_MARKET_FACTORS
    if not d.get("bank_position") and any(c.get("kind") == "position" and focus & set(c.get("factors") or [])
                                          and not c.get("superseded_by") and not c.get("stale")
                                          and not c.get("horizon_passed")
                                          for c in state.bank_chunks):
        issues.append(Issue(type="missing_bank_view", field="bank_position",
                            text="найдена позиция банка по фактору события, но она не использована",
                            fix="добавить позицию банка со ссылкой на материал"))
    return issues


def review(llm: LLMClient, state: AgentState, context_blocks: str) -> list[Issue]:
    """LLM-фактчекер. Ошибка модели не роняет пайплайн: возвращаем пустой список и пишем в трассу."""
    draft = json.dumps(state.draft, ensure_ascii=False)
    try:
        verdict, _ = llm.structured(
            [{"role": "system", "content": f"{PROMPT}\n\n{json_instruction(Verdict)}"},
             {"role": "user", "content": f"ИСТОЧНИКИ:\n{context_blocks}\n\nЧЕРНОВИК ИНСАЙТА (JSON):\n{draft}"}],
            Verdict, complexity="research", name="verifier", reasoning=False, max_tokens=3000,
        )
    except LLMError:
        return []
    return verdict.issues


def summarize(issues: list[Issue], iterations: int) -> dict:
    blocking = [i for i in issues if i.blocking]
    return {
        "passed": not blocking,
        "issues": [f"{'' if i.blocking else '(warning) '}{i.type} {i.field}: {i.text}" for i in issues],
        "iterations": iterations,
    }


def verify(state: AgentState) -> dict:
    """Совместимость: только детерминированный слой, результат пишется в state.verification."""
    result = summarize(check(state), state.iterations)
    state.verification = result
    return result
