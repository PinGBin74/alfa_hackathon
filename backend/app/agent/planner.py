"""Планирование: какие данные и источники нужны для вывода о конкретном клиенте.

План строит Gemma (5 с, ~0,02 ₽; Qwen3.6 на этом промпте зацикливался, GLM втрое дороже - замер 21.10), валидатор гарантирует минимальный набор
доказательств: граф контрагентов и поиск позиции банка по каждому фактору фокуса. При сбое модели -
детерминированный план по факторам с наибольшей чувствительностью клиента.
"""
from pathlib import Path

from app.agent import context
from app.agent.llm_client import LLMClient, LLMError, json_instruction
from app.agent.schemas import Plan, PlanStep
from app.agent.state import AgentState
from app.ml import taxonomy
from app.ml.news import NewsClassification
from app.observability.tracing import Tracer
from app.schemas.client import ClientProfile
from app.services.token_budget import BudgetExceeded

PROMPT = (Path(__file__).parent / "prompts" / "planner.md").read_text(encoding="utf-8")
MAX_STEPS = 6


def _fallback(meta: NewsClassification, exps: dict[str, taxonomy.Exposure]) -> Plan:
    ranked = sorted(meta.factor_codes, key=lambda f: exps[f].weight, reverse=True)
    focus = ranked[:2] or ["gdp_growth"]
    return Plan(
        focus_factors=focus,
        steps=[PlanStep(tool="search_bank_analytics", why="позиция банка по фактору",
                        query=" ".join(taxonomy.FACTORS[f].keywords[:3]), factors=[f]) for f in focus],
    )


def _validate(plan: Plan, meta: NewsClassification) -> tuple[Plan, list[str]]:
    """Убирает повторы, ограничивает длину, добавляет обязательные шаги. Возвращает правки для трассы."""
    notes: list[str] = []
    if not plan.focus_factors:
        plan.focus_factors = meta.factor_codes[:2] or ["gdp_growth"]
        notes.append("focus_factors взяты из разметки новости")
    steps, seen = [], set()
    for s in plan.steps:
        key = (s.tool, (s.query or "").lower(), tuple(s.factors))
        if key not in seen:
            seen.add(key)
            steps.append(s)
    if not any(s.tool == "get_counterparty_graph" for s in steps):
        steps.insert(0, PlanStep(tool="get_counterparty_graph", why="зависимость от поставщиков и покупателей"))
        notes.append("добавлен get_counterparty_graph")
    covered = {f for s in steps if s.tool == "search_bank_analytics" for f in s.factors}
    for f in plan.focus_factors:
        if f not in covered:
            steps.append(PlanStep(tool="search_bank_analytics", why=f"позиция банка: {taxonomy.FACTORS[f].label}",
                                  query=" ".join(taxonomy.FACTORS[f].keywords[:3]), factors=[f]))
            notes.append(f"добавлен поиск позиции банка по {f}")
    plan.steps = steps[:MAX_STEPS]
    plan.hypotheses = plan.hypotheses[:3]
    return plan, notes


def make_plan(llm: LLMClient, tracer: Tracer, state: AgentState) -> list[dict]:
    meta = NewsClassification.model_validate(state.scratch["meta"])
    profile = ClientProfile.model_validate(state.profile)
    exps = taxonomy.exposures(profile)
    user = "\n\n".join([
        f"НОВОСТЬ: {state.news.get('title')}\nКратко: {meta.summary}\n"
        f"Факторы: {', '.join(f'{f.factor}:{f.direction}' for f in meta.factors) or 'нет'}; "
        f"отрасли: {', '.join(meta.industries) or 'нет'}; страны: {', '.join(meta.countries) or 'нет'}",
        context.profile_brief(profile, state.user_role),
        context.exposures_brief(exps, list(dict.fromkeys(meta.factor_codes + ["key_rate", "fx"])), state.user_role),
    ])
    source = "llm"
    try:
        plan, _ = llm.structured(
            [{"role": "system", "content": f"{PROMPT}\n\n{json_instruction(Plan)}"}, {"role": "user", "content": user}],
            Plan, complexity="light", name="planner", max_tokens=1500,
        )
    except BudgetExceeded:
        raise
    except LLMError as e:
        plan, source = _fallback(meta, exps), f"fallback: {str(e)[:200]}"
    plan, notes = _validate(plan, meta)
    state.focus_factors = list(plan.focus_factors)
    state.hypotheses = list(plan.hypotheses)
    state.plan = [s.model_dump() for s in plan.steps]
    tracer.log("plan", "make_plan", output={"source": source, "focus_factors": state.focus_factors,
                                             "hypotheses": state.hypotheses, "plan": state.plan, "validator": notes})
    return state.plan
