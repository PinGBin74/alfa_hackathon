"""Шаги агента человеческим языком: для живого прогресса генерации и для экрана трассы (критерии 11, 12).

`describe` превращает строку agent_traces в {title, detail}: что сделал агент, какой моделью, что нашёл.
Сырые input/output остаются в трассе - их можно раскрыть.
"""
from app.config import get_settings
from app.ml import taxonomy

TOOL_TITLES = {
    "get_news_item": "Загрузка новости",
    "get_client_profile": "Профиль компании из данных банка",
    "get_counterparty_graph": "Граф контрагентов по платежам",
    "search_bank_analytics": "Поиск в аналитике Альфа-Банка",
    "search_news": "Поиск связанных новостей",
}


def model_label(model_id: str | None) -> str | None:
    """ID модели прокси -> название из списка кейса."""
    if not model_id:
        return None
    s = get_settings()
    names = {s.llm_model_light: "Gemma 4 26B A4B", s.llm_model_reasoning: "GLM-5.3-Flash",
             s.llm_model_general: "Qwen3.6 35B A3B", s.llm_model_research: "DeepSeek-V4.1-Flash",
             s.llm_model_text: "Kimi-K2.6", s.llm_model_vision: "Qwen3-VL-30B-A3B-Instruct"}
    return names.get(model_id, model_id)


def _factors(codes) -> str:
    return ", ".join(taxonomy.FACTORS[c].label if c in taxonomy.FACTORS else str(c) for c in codes or []) or "нет"


def describe(kind: str, name: str | None, input: dict | None, output: dict | None, model: str | None) -> dict:
    inp, out = input or {}, output or {}
    title, detail = name or kind, None
    if kind == "tool_call":
        title = TOOL_TITLES.get(name or "", name or "инструмент")
        if name in ("search_bank_analytics", "search_news") and inp.get("query"):
            detail = f"запрос «{inp['query']}»" + (f", факторы: {_factors(inp.get('factors'))}" if inp.get("factors") else "")
        elif inp.get("client_id"):
            detail = f"клиент {inp['client_id']}"
    elif kind == "llm_call":
        label = model_label(model)
        if name == "planner":
            title = "Планирование шагов"
        elif name and name.startswith("draft#"):
            title = "Черновик инсайта" if name == "draft#1" else "Точечная правка черновика по замечаниям проверки"
        elif name == "verifier":
            title = "Фактчекинг черновика другой моделью"
        elif name == "chat":
            title = "Ответ на вопрос"
        elif name == "chat#2":
            title = "Правка ответа: числа без источника"
        elif name == "classify":
            title = "Разметка новости"
        detail = label + (f", {out['cost_rub']:.2f} ₽" if isinstance(out.get("cost_rub"), int | float) else "")
    elif kind == "plan":
        title = "План анализа"
        if name == "chat":
            detail = "профиль и граф клиента, поиск по аналитике банка и новостям"
        else:
            steps = [s.get("tool") for s in out.get("plan") or []]
            detail = (f"фокус: {_factors(out.get('focus_factors'))}; шагов: {len(steps)}"
                      + ("; запасной план (модель не ответила по схеме)" if str(out.get("source", "")).startswith("fallback") else ""))
    elif kind == "context":
        title = "Единый контекст: признаки клиента, причины ранга, найденные материалы"
        detail = (f"релевантность {out.get('relevance')}; материалов банка: {len(out.get('bank_items') or [])}; "
                  f"связанных новостей: {len(out.get('related_news') or [])}")
    elif kind == "verify" and name == "verifier":
        issues = out.get("issues") or []
        blocking = [i for i in issues if not str(i).startswith("(warning)")]
        title = "Самопроверка: пройдена" if out.get("passed") else "Самопроверка: есть замечания"
        detail = f"итерация {out.get('iterations')}; замечаний: {len(blocking)}" + (
            f", предупреждений: {len(issues) - len(blocking)}" if len(issues) > len(blocking) else "")
    elif kind == "verify" and name == "chat_grounding":
        title = "Проверка чисел ответа по источникам"
        detail = "; ".join(out.get("issues") or []) or None
    elif kind == "verify" and name == "sanitize":
        title = "Очистка перед показом"
        detail = f"удалено или перенесено пунктов: {len(out.get('removed') or [])}"
    elif kind == "adapt":
        title = "Адаптация: повторный поиск и правка"
        detail = "; ".join(out.get("actions") or []) or None
    elif kind == "final":
        title = "Инсайт готов" if name == "insight" else "Ответ готов"
        if out.get("confidence"):
            detail = f"уверенность: {out['confidence']}, итераций: {out.get('iterations')}"
    return {"title": title, "detail": detail}


def step_view(s) -> dict:
    """Строка agent_traces для API: описание + сырые данные."""
    return {"step": s.step, "kind": s.kind, "name": s.name, **describe(s.kind, s.name, s.input, s.output, s.model),
            "model": model_label(s.model), "model_id": s.model, "latency_ms": s.latency_ms, "tokens_in": s.tokens_in,
            "tokens_out": s.tokens_out, "input": s.input, "output": s.output}
