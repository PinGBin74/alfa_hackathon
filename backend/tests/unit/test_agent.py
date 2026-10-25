"""Агентный цикл на фейковой LLM: план, инструменты, самопроверка, адаптация, очистка, трасса, чат."""
import copy
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent import chat, orchestrator
from app.agent.llm_client import LLMError
from app.agent.schemas import ChatReply, DraftInsight, Plan, Verdict
from app.agent.tools import registry
from app.db.models import (
    AgentTrace,
    Company,
    Feedback,
    InsightRecord,
    NewsItem,
    Payment,
    TokenUsage,
)
from app.db.session import Base

NEWS_BODY = ("Совет директоров Банка России 11 сентября 2026 года сохранил ключевую ставку на уровне 14% годовых. "
             "Регулятор отметил устойчивость инфляции.")
BANK_ITEM = {"doc_id": "d1", "title": "Ключевая ставка ЦБ РФ", "page": 1, "kind": "position", "factors": ["key_rate"],
             "text": "Мы ожидаем паузу 23.10; ставка на конец 2026 года - 14,0%.", "published_at": "2026-09-11",
             "stale": False, "score": 5.0, "position_id": "d1-p1-1"}
GOOD = {
    "what_happened": {"summary": "Банк России сохранил ключевую ставку 14%.",
                      "confirmed_facts": [{"text": "Ставка сохранена на уровне 14% годовых", "source_id": "news:n1"}],
                      "assumptions": []},
    "why_it_matters": [{"text": "У компании кредиты в Альфа-Банке: обслуживание долга останется дорогим",
                        "client_features": ["CL_PRODUCT_LOA_MARK", "NOT_A_FEATURE"]}],
    "consequences": {"risks": [{"text": "Процентная нагрузка не снизится", "basis": ["news:n1", "client:C", "bogus"]}],
                     "opportunities": [], "factors_to_watch": ["заседание 23.10"]},
    "suggested_actions": [{"text": "Оценить долю кредитов с плавающей ставкой", "kind": "question"},
                          {"text": "Открыть вклад", "kind": "product", "product_code": "not_offered"}],
    "bank_position": [{"text": "Банк ожидает ставку 14,0% на конец 2026 года", "analytics_doc_id": "d1", "quote_ref": "bank:d1:1"}],
    "ai_inference": [{"text": "Рефинансирование разумно отложить до снижения ставки", "basis": ["bank:d1:1"]}],
    "confidence": "high",
}


def _bad_number(draft):
    d = copy.deepcopy(draft)
    d["what_happened"]["confirmed_facts"][0]["text"] = "Ставка сохранена на уровне 15% годовых"
    return d


class FakeLLM:
    def __init__(self, drafts, plan=None, plan_error=False):
        self.drafts, self.plan, self.plan_error = list(drafts), plan, plan_error
        self.calls: list[tuple[str, list[dict]]] = []

    def structured(self, messages, schema, complexity="light", *, name="llm", **kw):
        self.calls.append((name, messages))
        if schema is Plan:
            if self.plan_error:
                raise LLMError("planner down")
            return self.plan or Plan(focus_factors=["key_rate"], hypotheses=["дорогой долг"], steps=[
                {"tool": "search_bank_analytics", "why": "позиция банка", "query": "ключевая ставка", "factors": ["key_rate"]}]), {}
        if schema is DraftInsight:
            return DraftInsight.model_validate(self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]), {}
        if schema is Verdict:
            return Verdict(), {}
        if schema is ChatReply:
            return ChatReply(answer="Ставка останется высокой (позиция банка).", source_ids=["bank:d1:1", "bogus"]), {}
        raise AssertionError(schema)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[t.__table__ for t in (
        Company, Payment, NewsItem, InsightRecord, AgentTrace, TokenUsage, Feedback)])
    calls = {"bank": 0, "news": 0}

    def fake_bank(db, query, k=4, factors=None):
        calls["bank"] += 1
        return [dict(BANK_ITEM)]

    def fake_news(db, query, k=5):
        calls["news"] += 1
        return []

    monkeypatch.setattr(registry.retriever, "search_bank_analytics", fake_bank)
    monkeypatch.setattr(registry.retriever, "search_news", fake_news)
    with Session(engine) as s:
        s.add_all([
            Company(synthetic_u="C", mainokved_code="42.99", mainokved_name="Строительство", group_id="g1",
                    revenue=20e9, region="Иркутская область", has_loans=True, cl_type="CLIENT"),
            Company(synthetic_u="S1", mainokved_code="24.10", mainokved_name="Сталь", group_id="g2", revenue=1e9),
            Payment(payer="C", beneficiary="S1", pay_amt=600.0, pay_cnt=3),
            NewsItem(news_id="n1", source="test", url="http://x/1", title="ЦБ сохранил ставку 14%", body=NEWS_BODY,
                     event_type="key_rate", dedup_hash="h1", published_at=datetime.now(UTC)),
        ])
        s.commit()
        s.info["calls"] = calls
        yield s


def _run(db, monkeypatch, llm, role="cfo"):
    monkeypatch.setattr(orchestrator, "LLMClient", lambda db, tracer=None: llm)
    return orchestrator.run(db, "C", "n1", user_role=role)


def test_happy_path_passes_and_is_traced(db, monkeypatch):
    llm = FakeLLM([GOOD])
    ins = _run(db, monkeypatch, llm)
    assert ins.verification.passed and ins.verification.iterations == 1 and ins.confidence == "high"
    assert ins.bank_position[0].analytics_doc_id == "d1"
    assert {s.source_id for s in ins.sources} >= {"news:n1", "client:C", "bank:d1:1"}
    assert 0 < ins.relevance_score <= 1
    kinds = [t.kind for t in db.query(AgentTrace).filter_by(trace_id=ins.trace_id).order_by(AgentTrace.step)]
    assert kinds[0] == "tool_call" and {"plan", "context", "verify", "final"} <= set(kinds)
    assert [n for n, _ in llm.calls] == ["planner", "draft#1", "verifier"]
    assert db.get(InsightRecord, ins.insight_id).payload["insight_id"] == ins.insight_id


def test_sanitize_filters_features_sources_and_products(db, monkeypatch):
    ins = _run(db, monkeypatch, FakeLLM([GOOD]))
    assert ins.why_it_matters[0].client_features == ["CL_PRODUCT_LOA_MARK"]
    assert ins.consequences.risks[0].basis == ["news:n1", "client:C"]
    assert ins.suggested_actions[1].kind == "action" and ins.suggested_actions[1].product_code is None


def test_wrong_number_triggers_revision(db, monkeypatch):
    llm = FakeLLM([_bad_number(GOOD), GOOD])
    ins = _run(db, monkeypatch, llm)
    assert ins.verification.passed and ins.verification.iterations == 2
    second_draft_prompt = [m for n, m in llm.calls if n == "draft#2"][0][-1]["content"]
    assert "ЗАМЕЧАНИЯ ПРОВЕРКИ" in second_draft_prompt and "15" in second_draft_prompt
    kinds = [t.kind for t in db.query(AgentTrace).filter_by(trace_id=ins.trace_id)]
    assert "adapt" in kinds


def test_missing_bank_view_triggers_extra_search(db, monkeypatch):
    no_bank = copy.deepcopy(GOOD)
    no_bank["bank_position"] = []
    before = db.info["calls"]["bank"]
    ins = _run(db, monkeypatch, FakeLLM([no_bank, GOOD]))
    assert ins.verification.iterations == 2 and ins.bank_position
    assert db.info["calls"]["bank"] - before >= 2  # план + адаптация


def test_unfixed_item_is_dropped_after_last_iteration(db, monkeypatch):
    ins = _run(db, monkeypatch, FakeLLM([_bad_number(GOOD)]))
    assert ins.verification.iterations == orchestrator.MAX_ITERATIONS
    assert ins.verification.passed and ins.confidence == "medium"
    assert ins.what_happened.confirmed_facts == []
    assert any(i.startswith("removed: не прошло проверку (what_happened.confirmed_facts)") for i in ins.verification.issues)


def test_generic_insight_stays_low_confidence(db, monkeypatch):
    generic = copy.deepcopy(GOOD)
    generic["why_it_matters"] = [{"text": "Ставка важна для всех компаний", "client_features": []}]
    ins = _run(db, monkeypatch, FakeLLM([generic]))
    assert not ins.verification.passed and ins.confidence == "low"
    assert ins.why_it_matters  # не удаляется до пустого списка


def test_planner_fallback_still_gathers_evidence(db, monkeypatch):
    ins = _run(db, monkeypatch, FakeLLM([GOOD], plan_error=True))
    plan_step = db.query(AgentTrace).filter_by(trace_id=ins.trace_id, kind="plan").one()
    assert plan_step.output["source"].startswith("fallback")
    tools = [s["tool"] for s in plan_step.output["plan"]]
    assert tools[0] == "get_counterparty_graph" and "search_bank_analytics" in tools


def test_chat_answer_keeps_only_known_sources(db, monkeypatch):
    llm = FakeLLM([GOOD])
    ins = _run(db, monkeypatch, llm)
    monkeypatch.setattr(chat, "LLMClient", lambda db, tracer=None: llm)
    ans = chat.answer(db, db.get(InsightRecord, ins.insight_id), "Что это значит для долга?", "cfo")
    assert ans.source_ids == ["bank:d1:1"] and ans.trace_id and "Ставка" in ans.answer


def test_quality_metrics_over_saved_insights(db, monkeypatch):
    from app.ml.quality import insight_quality
    _run(db, monkeypatch, FakeLLM([GOOD]))
    _run(db, monkeypatch, FakeLLM([_bad_number(GOOD), GOOD]))
    q = insight_quality(db)
    assert q["insights_evaluated"] == 2 and q["verified_rate"] == 1.0
    assert q["verified_first_iteration_rate"] == 0.5 and q["bank_view_rate"] == 1.0
    assert q["why_with_client_features_rate"] == 1.0


def test_bank_refs_with_prefix_are_normalized(db, monkeypatch):
    prefixed = copy.deepcopy(GOOD)
    prefixed["bank_position"][0].update(analytics_doc_id="bank:d1", quote_ref="bank:d1:1")
    ins = _run(db, monkeypatch, FakeLLM([prefixed]))
    assert ins.verification.passed and ins.verification.iterations == 1
    assert (ins.bank_position[0].analytics_doc_id, ins.bank_position[0].quote_ref) == ("d1", "bank:d1:1")


def test_bank_forecast_in_facts_is_moved_to_bank_position(db, monkeypatch):
    draft = copy.deepcopy(GOOD)
    draft["what_happened"]["confirmed_facts"].append({"text": "Ставка на конец 2026 года - 14,0%", "source_id": "bank:d1:1"})
    ins = _run(db, monkeypatch, FakeLLM([draft]))
    assert ins.verification.passed and ins.verification.iterations == 1
    assert [f.source_id for f in ins.what_happened.confirmed_facts] == ["news:n1"]
    assert any(b.text == "Ставка на конец 2026 года - 14,0%" for b in ins.bank_position)


def test_planner_falls_back_to_second_model_before_rules(db, monkeypatch):
    class FlakyPlanner(FakeLLM):
        def structured(self, messages, schema, complexity="light", *, name="llm", **kw):
            if schema is Plan and complexity == "light":
                self.calls.append((name, messages))
                raise LLMError("gemma looped")
            return super().structured(messages, schema, complexity, name=name, **kw)

    ins = _run(db, monkeypatch, FlakyPlanner([GOOD]))
    plan_step = db.query(AgentTrace).filter_by(trace_id=ins.trace_id, kind="plan").one()
    assert plan_step.output["source"].startswith("llm (reasoning")
    assert plan_step.output["focus_factors"] == ["key_rate"]


def test_superseded_bank_forecast_is_flagged_for_revision(db, monkeypatch):
    stale = dict(BANK_ITEM, superseded_by="d2-p1-1")
    monkeypatch.setattr(registry.retriever, "search_bank_analytics", lambda db, query, k=4, factors=None: [dict(stale)])
    monkeypatch.setattr(orchestrator.context.bank_positions, "newer_forecast", lambda pid: None)
    llm = FakeLLM([GOOD])
    ins = _run(db, monkeypatch, llm)
    assert ins.verification.iterations == 2       # устаревший прогноз с цифрами - блокирующее замечание
    first = db.query(AgentTrace).filter_by(trace_id=ins.trace_id, kind="verify", name="verifier").order_by(AgentTrace.step).first()
    assert any("stale_bank_view" in i for i in first.output["issues"])
    assert not ins.bank_position                   # не исправлен - не показывается
    assert any(i.startswith("removed:") and "bank_position" in i for i in ins.verification.issues)
    draft_ctx = next(m for n, m in llm.calls if n == "draft#1")[1]["content"]
    assert "ОБНОВЛЁН" in draft_ctx


def test_company_event_position_is_not_required_in_insight(db, monkeypatch):
    other = dict(BANK_ITEM, factors=["company_event"], text="Банк не ожидает ухудшения кредитного качества эмитента.")
    monkeypatch.setattr(registry.retriever, "search_bank_analytics", lambda db, query, k=4, factors=None: [dict(other)])
    plan = Plan(focus_factors=["company_event"], steps=[])
    no_bank = copy.deepcopy(GOOD) | {"bank_position": [], "ai_inference": []}
    ins = _run(db, monkeypatch, FakeLLM([no_bank], plan=plan))
    assert ins.verification.passed and ins.verification.iterations == 1


def test_chat_answer_with_invented_number_is_revised(db, monkeypatch):
    class NumberChat(FakeLLM):
        def structured(self, messages, schema, complexity="light", *, name="llm", **kw):
            if schema is ChatReply:
                self.calls.append((name, messages))
                text = ("Спрос может упасть на 37%." if name == "chat" else "Ставка 14% сохранится, спрос под давлением.")
                return ChatReply(answer=text, source_ids=["news:n1"]), {}
            return super().structured(messages, schema, complexity, name=name, **kw)

    llm = NumberChat([GOOD])
    ins = _run(db, monkeypatch, llm)
    monkeypatch.setattr(chat, "LLMClient", lambda db, tracer=None: llm)
    ans = chat.answer(db, db.get(InsightRecord, ins.insight_id), "Что со спросом?", "cfo")
    assert "37" not in ans.answer and [n for n, _ in llm.calls][-2:] == ["chat", "chat#2"]
    assert "37" in llm.calls[-1][1][-1]["content"]          # замечание называет число без источника
    steps = db.query(AgentTrace).filter_by(trace_id=ans.trace_id).all()
    assert any(s.name == "chat_grounding" for s in steps)
    assert ans.sources and ans.sources[0].source_id == "news:n1"


# ---------- даты: контекст и проверка ----------

def _absent_month() -> tuple[int, str]:
    """Месяц, которого нет в источниках теста (новость и банк - сентябрь) и который не совпадает с сегодняшним:
    сегодняшняя дата тоже допустимый источник месяца."""
    from datetime import date
    return next((m, f) for m, f in ((3, "марте"), (4, "апреле")) if m != date.today().month)


def test_months_are_extracted_in_any_form():
    from app.ml.grounding import months, ru_date, ungrounded_months
    assert set(months("в сентябре банк, сентябрьский прогноз, 23 октября, в мае")) == {9, 10, 5}
    assert months("маржа и масштаб бизнеса") == {}
    assert ru_date("2026-09-11T08:00:00+00:00") == "11 сентября 2026" and ru_date(None) == ""
    assert ungrounded_months("решение 23 октября", "заседание 11 сентября 2026") == ["октября"]


def test_context_marks_bank_material_published_before_news():
    from app.agent import context
    block = context.bank_block([dict(BANK_ITEM)], event_date="2026-10-23T10:00:00+00:00")
    assert "11 сентября 2026" in block and "вышел за 42 дн. до новости" in block
    same_day = context.bank_block([dict(BANK_ITEM)], event_date="2026-09-11T18:00:00+00:00")
    assert "до новости" not in same_day
    dates = context.dates_block("2026-10-25", "2026-10-23")
    assert "сегодня 25 октября 2026" in dates and "новость опубликована 23 октября 2026" in dates


def test_draft_prompt_has_dates_block(db, monkeypatch):
    llm = FakeLLM([GOOD])
    _run(db, monkeypatch, llm)
    prompt = [m for n, m in llm.calls if n == "draft#1"][0][-1]["content"]
    assert prompt.startswith("ДАТЫ: сегодня ") and "ожидания банка на ту дату" in prompt


def test_month_absent_from_sources_triggers_revision(db, monkeypatch):
    _, form = _absent_month()
    bad = copy.deepcopy(GOOD)
    bad["consequences"]["risks"][0]["text"] = f"Решение ЦБ в {form} подтвердило дорогой долг"
    llm = FakeLLM([bad, GOOD])
    ins = _run(db, monkeypatch, llm)
    assert ins.verification.iterations == 2 and ins.verification.passed
    second = [m for n, m in llm.calls if n == "draft#2"][0][-1]["content"]
    assert "[wrong_date] consequences.risks[0]" in second


def test_month_from_other_source_is_only_a_warning(db, monkeypatch):
    shifted = copy.deepcopy(GOOD)
    # сентябрь есть в новости, но пункт ссылается только на данные клиента
    shifted["consequences"]["risks"][0] = {"text": "С сентября процентная нагрузка не снизится", "basis": ["client:C"]}
    ins = _run(db, monkeypatch, FakeLLM([shifted]))
    assert ins.verification.passed and ins.verification.iterations == 1
    assert any(i.startswith("(warning) wrong_date consequences.risks[0]") for i in ins.verification.issues)


def test_inference_on_bank_material_requires_bank_thesis(db, monkeypatch):
    orphan = copy.deepcopy(GOOD)
    orphan["bank_position"] = []   # ai_inference опирается на bank:d1:1, а тезиса банка нет
    llm = FakeLLM([orphan, GOOD])
    ins = _run(db, monkeypatch, llm)
    assert ins.verification.iterations == 2 and ins.bank_position
    second = [m for n, m in llm.calls if n == "draft#2"][0][-1]["content"]
    assert "выводы опираются на материалы банка ['bank:d1:1']" in second


def test_bank_thesis_with_date_prefix_is_kept_and_cleaned(db, monkeypatch):
    dated = copy.deepcopy(GOOD)
    dated["bank_position"][0]["text"] = ("По материалу от 11 сентября 2026 года (до решения 23 октября): "
                                         "банк ожидает ставку 14,0% на конец 2026 года")
    ins = _run(db, monkeypatch, FakeLLM([dated]))
    assert ins.verification.passed and ins.verification.iterations == 1        # дата - не повод удалять тезис
    assert ins.bank_position[0].text == "Банк ожидает ставку 14,0% на конец 2026 года"
    assert any(i.startswith("(warning) wrong_date bank_position[0]") for i in ins.verification.issues)


def test_strip_bank_date_prefix_leaves_plain_text():
    assert orchestrator.strip_bank_date_prefix("Банк прогнозирует ставку 13,5%") == "Банк прогнозирует ставку 13,5%"
    assert orchestrator.strip_bank_date_prefix("Согласно материалу банка от 2 сентября: инфляция замедлится") == \
        "Инфляция замедлится"
