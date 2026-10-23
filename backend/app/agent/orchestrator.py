"""Агентный цикл: план -> инструменты -> черновик -> самопроверка -> адаптация -> (повтор).

Собственная реализация, без готовых агентных фреймворков (требование кейса). Модели разделены по ролям:
план - Gemma 4, черновик - GLM-5.3-Flash, фактчекинг - DeepSeek-V4.1-Flash (другая модель, чем автор).
Каждый шаг, вызов инструмента и вызов LLM пишется в agent_traces (критерий 12).
"""
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent import context, planner, verifier
from app.agent.llm_client import LLMClient, json_instruction
from app.agent.schemas import DraftInsight, Issue
from app.agent.state import AgentState
from app.agent.tools.registry import call_tool
from app.db.models import InsightRecord, NewsItem
from app.ml import taxonomy
from app.ml.grounding import ungrounded
from app.ml.news import NewsClassification, news_meta
from app.observability.tracing import Tracer
from app.schemas.client import ClientProfile, GraphFeatures
from app.schemas.insight import Insight, SourceRef, Verification
from app.services import ranking

PROMPT = (Path(__file__).parent / "prompts" / "interpret.md").read_text(encoding="utf-8")
MAX_ITERATIONS = 2  # черновик + точечная правка; что не исправлено - удаляется (_drop_flagged)
MAX_BANK_ITEMS = 8


def _profile(state: AgentState) -> ClientProfile:
    p = ClientProfile.model_validate(state.profile)
    if state.graph:
        p.graph = GraphFeatures.model_validate(state.graph)
    return p


def _gather(db: Session, tracer: Tracer, state: AgentState) -> None:
    for step in state.plan:
        tool = step["tool"]
        if tool == "get_counterparty_graph":
            state.graph = call_tool(db, tracer, tool, client_id=state.client_id)
        elif tool == "search_bank_analytics":
            query = step.get("query") or state.news["title"]
            state.add_bank(call_tool(db, tracer, tool, query=query, k=4, factors=step.get("factors") or state.focus_factors))
        elif tool == "search_news":
            state.add_related(call_tool(db, tracer, tool, query=step.get("query") or state.news["title"], k=3))


def _bank_for_context(state: AgentState) -> list[dict]:
    """Порядок (сортировки устойчивые): актуальные позиции, затем фрагменты; внутри - свежие и релевантные.
    Устаревшие документы и обновлённые позднее прогнозы - в конце."""
    items = sorted(state.bank_chunks, key=lambda c: c.get("score") or 0, reverse=True)
    items.sort(key=lambda c: str(c.get("published_at") or ""), reverse=True)
    items.sort(key=lambda c: (bool(c.get("stale")), bool(c.get("superseded_by")), c.get("kind") != "position"))
    return items[:MAX_BANK_ITEMS]


def _context(state: AgentState, profile: ClientProfile, score: ranking.Score) -> str:
    meta = NewsClassification.model_validate(state.scratch["meta"])
    factors = list(dict.fromkeys(state.focus_factors + meta.factor_codes))
    hints = taxonomy.product_hints(profile, factors)
    state.scratch["product_codes"] = {h.code for h in hints}
    bank = _bank_for_context(state)
    known = sorted({f"news:{state.news_id}", f"client:{state.client_id}",
                    *(f"news:{n['news_id']}" for n in state.related_news),
                    *(context.bank_source_id(c) for c in bank)})
    brief = context.profile_brief(profile, state.user_role)
    state.scratch["context_text"] = brief
    blocks = [
        brief,
        context.exposures_brief(taxonomy.exposures(profile), factors, state.user_role),
        "ПОЧЕМУ НОВОСТЬ В ЛЕНТЕ КЛИЕНТА: " + ("; ".join(score.reasons) or "общая значимость события"),
        context.news_block(state.news, meta),
        context.related_block(state.related_news),
        context.bank_block(bank),
        context.products_block(hints),
        "ГИПОТЕЗЫ ПЛАНА: " + ("; ".join(state.hypotheses) or "нет"),
        "ДОПУСТИМЫЕ source_id: " + ", ".join(known),
        "ДОПУСТИМЫЕ client_features: " + ", ".join(sorted(state.scratch["allowed_features"])),
    ]
    return "\n\n".join(b for b in blocks if b)


def _draft(llm: LLMClient, state: AgentState, ctx: str) -> dict:
    """Первый черновик - с нуля; следующие - точечная правка: исправить только пункты из замечаний,
    остальное сохранить дословно (иначе каждая пересборка вносит новые ошибки и проверка не сходится)."""
    user = ctx
    if state.feedback and state.draft:
        previous = {k: v for k, v in state.draft.items() if k != "confidence"}
        user += ("\n\nПРЕДЫДУЩИЙ ЧЕРНОВИК (JSON):\n" + json.dumps(previous, ensure_ascii=False)
                 + "\n\nЗАМЕЧАНИЯ ПРОВЕРКИ:\n" + "\n".join(f"- {f}" for f in state.feedback)
                 + "\n\nВерни исправленный черновик: исправь или удали только пункты из замечаний, "
                   "остальные пункты сохрани дословно. Новых утверждений не добавляй.")
    draft, _ = llm.structured(
        [{"role": "system", "content": f"{PROMPT}\n\n{json_instruction(DraftInsight)}"}, {"role": "user", "content": user}],
        DraftInsight, complexity="reasoning", name=f"draft#{state.iterations}",
    )
    return draft.model_dump(mode="json")


def _adapt(db: Session, tracer: Tracer, state: AgentState, issues: list[Issue]) -> None:
    """Корректировка шагов по замечаниям: дополнительный поиск и обратная связь автору."""
    types = {i.type for i in issues if i.blocking}
    actions: list[str] = []
    if types & {"missing_bank_view", "wrong_bank_attribution", "stale_bank_view"} or not state.bank_chunks:
        added = 0
        for f in state.focus_factors[:3]:
            query = f"{taxonomy.FACTORS[f].label} " + " ".join(taxonomy.FACTORS[f].keywords[:2])
            added += state.add_bank(call_tool(db, tracer, "search_bank_analytics", query=query, k=4, factors=[f]))
        actions.append(f"дополнительный поиск в аналитике банка по факторам {state.focus_factors[:3]}: +{added}")
    if types & {"unsupported_fact", "contradiction"} and not state.related_news:
        added = state.add_related(call_tool(db, tracer, "search_news", query=state.news["title"], k=3))
        actions.append(f"поиск связанных новостей для перекрёстной проверки: +{added}")
    state.feedback = [f"[{i.type}] {i.field}: {i.text}" + (f" -> {i.fix}" if i.fix else "") for i in issues]
    actions.append("черновик будет пересобран с замечаниями")
    tracer.log("adapt", "adapt", output={"actions": actions, "feedback": state.feedback})


_ITEM = re.compile(r"^(what_happened\.confirmed_facts|why_it_matters|consequences\.risks|consequences\.opportunities"
                   r"|suggested_actions|bank_position|ai_inference)\[(\d+)\]")


def _drop_flagged(state: AgentState, issues: list[Issue]) -> list[str]:
    """После последней итерации: пункты с блокирующими замечаниями, которые не удалось исправить, удаляются.
    Пункты «почему важно» не удаляются до пустого списка - без них нет персонализации."""
    targets: dict[str, set[int]] = {}
    for i in issues:
        m = _ITEM.match(i.field or "")
        if i.blocking and m:
            targets.setdefault(m.group(1), set()).add(int(m.group(2)))
    removed = []
    for path, idx in targets.items():
        head, _, tail = path.partition(".")
        container = state.draft[head] if tail else state.draft
        items = container[tail or head]
        keep = [x for n, x in enumerate(items) if n not in idx]
        if path == "why_it_matters" and not keep:
            continue
        removed += [f"не прошло проверку ({path}): {str(x.get('text', ''))[:80]}" for n, x in enumerate(items) if n in idx]
        container[tail or head] = keep
    return removed


def _sanitize(state: AgentState) -> list[str]:
    """Последний рубеж: убрать то, что не прошло проверку источников, чтобы не показать пользователю ошибку."""
    d, known, removed = state.draft, state.source_ids(), []
    allowed = state.scratch["allowed_features"]
    wh = d["what_happened"]
    for bp in d["bank_position"]:
        verifier.normalize_bank_ref(bp)
    kept = []
    for f in wh["confirmed_facts"]:
        sid = f["source_id"]
        if sid.startswith("bank:") and sid in known:  # прогноз банка - не факт события: переносим
            doc = sid.split(":")[1]
            if not ungrounded(f["text"], verifier.bank_text(state, doc, sid)):
                d["bank_position"].append({"text": f["text"], "analytics_doc_id": doc, "quote_ref": sid})
                removed.append(f"перенесено из фактов в позицию банка: {f['text'][:80]}")
                continue
        if sid in known and not ungrounded(f["text"], verifier.news_text(state, sid)):
            kept.append(f)
        else:
            removed.append(f"факт без подтверждения: {f['text'][:80]}")
    wh["confirmed_facts"] = kept
    kept = []
    for bp in d["bank_position"]:
        source = verifier.bank_text(state, bp["analytics_doc_id"], bp.get("quote_ref"))
        if source and not ungrounded(bp["text"], source):
            kept.append(bp)
        else:
            removed.append(f"позиция банка без подтверждения: {bp['text'][:80]}")
    d["bank_position"] = kept
    for w in d["why_it_matters"]:
        w["client_features"] = [f for f in w["client_features"] if f in allowed]
    cons = d["consequences"]
    for s in cons["risks"] + cons["opportunities"] + d["ai_inference"]:
        # код признака клиента в basis - это ссылка на данные клиента
        basis = [f"client:{state.client_id}" if b in allowed else b for b in s["basis"]]
        s["basis"] = list(dict.fromkeys(b for b in basis if b in known))
    for a in d["suggested_actions"]:
        if a["kind"] == "product" and a.get("product_code") not in state.scratch["product_codes"]:
            a["kind"], a["product_code"] = "action", None
            removed.append(f"продукт не из списка кандидатов: {a['text'][:60]}")
    return removed


def _sources(state: AgentState) -> list[SourceRef]:
    n = state.news
    refs = [SourceRef(source_id=f"news:{n['news_id']}", type="news", title=n["title"], url=n.get("url"),
                      published_at=n.get("published_at")),
            SourceRef(source_id=f"client:{state.client_id}", type="client_data", title="Данные о компании из выгрузки банка")]
    refs += [SourceRef(source_id=f"news:{r['news_id']}", type="news", title=r.get("title"), url=r.get("url"),
                       published_at=r.get("published_at")) for r in state.related_news]
    seen = set()
    for c in state.bank_chunks:
        sid = context.bank_source_id(c)
        if sid not in seen:
            seen.add(sid)
            refs.append(SourceRef(source_id=sid, type="bank_analytics", title=f"{c.get('title')}, стр. {c.get('page')}",
                                  published_at=c.get("published_at")))
    return refs


def run(db: Session, client_id: str, news_id: str, user_role: str | None = None, trace_id: str | None = None) -> Insight:
    """trace_id задаётся заранее, когда за ходом генерации следят по трассе (GET .../progress)."""
    tracer = Tracer(db, trace_id)
    llm = LLMClient(db, tracer=tracer)
    state = AgentState(client_id=client_id, news_id=news_id, user_role=user_role)

    state.news = call_tool(db, tracer, "get_news_item", news_id=news_id)
    state.profile = call_tool(db, tracer, "get_client_profile", client_id=client_id)
    if not state.news or not state.profile:
        raise LookupError(f"news {news_id} or client {client_id} not found")
    news_orm = db.get(NewsItem, news_id)
    state.scratch["meta"] = news_meta(news_orm).meta()

    planner.make_plan(llm, tracer, state)
    _gather(db, tracer, state)
    profile = _profile(state)
    state.scratch["allowed_features"] = context.allowed_features(profile)
    score = ranking.score_news(profile, news_orm, role=user_role)
    tracer.log("context", "client_context", output={
        "relevance": score.value, "parts": score.parts, "reasons": score.reasons,
        "exposures": {f: {"weight": e.weight, "features": [r.feature for r in e.reasons]}
                      for f, e in taxonomy.exposures(profile).items() if e.weight > 0},
        "bank_items": [context.bank_source_id(c) for c in state.bank_chunks],
        "related_news": [n["news_id"] for n in state.related_news],
    })

    issues: list[Issue] = []
    while True:
        state.iterations += 1
        ctx = _context(state, profile, score)
        state.draft = _draft(llm, state, ctx)
        issues = verifier.check(state)
        if not any(i.blocking for i in issues):  # LLM-фактчекер - только для черновика без явных ошибок
            issues += verifier.review(llm, state, ctx)
        state.verification = verifier.summarize(issues, state.iterations)
        tracer.log("verify", "verifier", output=state.verification)
        if state.verification["passed"] or state.iterations >= MAX_ITERATIONS:
            break
        _adapt(db, tracer, state, issues)

    removed: list[str] = []
    confidence = state.draft.pop("confidence", None)
    if not state.verification["passed"]:
        removed = _drop_flagged(state, issues)
        remaining = [i for i in verifier.check(state) if i.blocking]
        state.verification = verifier.summarize(remaining + [i for i in issues if not i.blocking], state.iterations)
        confidence = "low" if remaining else "medium" if confidence == "high" else confidence
    removed += _sanitize(state)
    if removed:
        tracer.log("verify", "sanitize", output={"removed": removed, "passed": state.verification["passed"]})
    insight = Insight(
        insight_id=uuid.uuid4().hex,
        client_id=client_id,
        user_role=user_role,
        news_id=news_id,
        relevance_score=score.value,
        sources=_sources(state),
        confidence=confidence,
        verification=Verification(passed=state.verification["passed"],
                                  issues=state.verification["issues"] + [f"removed: {r}" for r in removed],
                                  iterations=state.iterations),
        trace_id=tracer.trace_id,
        generated_at=datetime.now(UTC),
        **state.draft,
    )
    db.add(InsightRecord(
        insight_id=insight.insight_id, client_id=client_id, user_role=user_role, news_id=news_id,
        payload=insight.model_dump(mode="json"), trace_id=tracer.trace_id,
    ))
    db.commit()
    tracer.log("final", "insight", output={"insight_id": insight.insight_id, "confidence": confidence,
                                            "iterations": state.iterations})
    return insight
