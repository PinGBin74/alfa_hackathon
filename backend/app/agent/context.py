"""Сборка контекста для модели: профиль клиента, чувствительность, новость, аналитика банка.

Каждый признак подписан кодом ([CL_PRODUCT_LOA_MARK], [graph.supplier_industries]), каждый источник -
идентификатором (news:..., bank:<doc>:<page>, client:...). Модель может ссылаться только на них, а
верификатор проверяет ссылки по тем же спискам (критерии 04, 12).
"""
from app.ml import bank_positions, taxonomy
from app.ml.grounding import parse_date, ru_date
from app.ml.news import NewsClassification
from app.schemas.client import ClientProfile
from app.security import injection_guard

NEWS_BODY_CHARS = 4000
BANK_TEXT_CHARS = 1300  # меньше - теряется, кому принадлежит утверждение (банку или ЦБ)
PRODUCT_FLAGS = {
    "rko": ("CL_PRODUCT_RKO_MARK", "РКО"), "guarantees": ("CL_PRODUCT_GAR_MARK", "гарантии"),
    "loans": ("CL_PRODUCT_LOA_MARK", "кредиты"), "leasing": ("CL_PRODUCT_LEA_MARK", "лизинг"),
    "deposits": ("CL_PRODUCT_DEP_MARK", "депозиты"), "payroll": ("CL_PRODUCT_ZPP_MARK", "зарплатный проект"),
    "factoring": ("FACTORING_MARK", "факторинг"),
}
BASE_FEATURES = {
    "MAINOKVED_CODE", "REVENUE_COMPANY", "REGION", "GROUP_ID", "FTS_FLAG", "FTS_COUNTRY_NAME", "OKFS_NAME",
    "AMOUNT_WORKERS_FNS_GRADATION", "ECO_MARK_LABEL", "CL_TYPE", "COMPANY_AGE_YEARS_GRADATION",
    "industry_position", "group.top_industries", "group.total_revenue", "user_role",
    *(code for code, _ in PRODUCT_FLAGS.values()),
}
GRAPH_FEATURES = {
    "graph.top_suppliers", "graph.top_buyers", "graph.supplier_industries", "graph.buyer_industries",
    "graph.supplier_concentration", "graph.buyer_concentration", "graph.supplier_unknown_share",
    "graph.buyer_unknown_share", "graph.supplier_intragroup_share", "graph.buyer_intragroup_share",
}
ROLE_NAMES = {"owner": "собственник", "ceo": "генеральный директор", "cfo": "финансовый директор",
              "chief_accountant": "главный бухгалтер", "treasurer": "руководитель казначейства",
              "c_level": "C-level руководитель", "other": "сотрудник компании"}


def _bn(x: float | None) -> str:
    return f"{x / 1e9:.1f} млрд руб." if x else "нет данных"


def _industries(items) -> str:
    return "; ".join(
        f"{i.okved2} {taxonomy.OKVED2_CLASSES.get(i.okved2, '')} {i.share:.0%}"
        + (f" (напр. {i.examples[0]})" if i.examples else "")
        for i in items
    ) or "нет данных"


def profile_brief(p: ClientProfile, role: str | None) -> str:
    has = [name for attr, (_, name) in PRODUCT_FLAGS.items() if getattr(p.products, attr)]
    has_not = [name for attr, (_, name) in PRODUCT_FLAGS.items() if not getattr(p.products, attr)]
    lines = [
        f"КЛИЕНТ (source_id client:{p.client_id}). Данные обезличенной выгрузки банка.",
        f"- [MAINOKVED_CODE] основной вид деятельности: {p.okved_code} {p.okved_name or ''}",
        f"- [REVENUE_COMPANY] выручка: {_bn(p.revenue)}" + (" - крупный бизнес (> 15 млрд)" if p.large_business else ""),
        f"- [AMOUNT_WORKERS_FNS_GRADATION] штат по ФНС: {p.workers_fns or 'нет данных'}; "
        f"[COMPANY_AGE_YEARS_GRADATION] возраст: {p.age_gradation or 'нет данных'} лет; [ECO_MARK_LABEL] стадия: {p.stage or 'нет данных'}",
        f"- [REGION] регион: {p.region or 'нет данных'}; [OKFS_NAME] собственность: {p.ownership or 'нет данных'}",
        f"- [CL_TYPE] статус в банке: {p.cl_type or 'нет данных'}",
        f"- продукты в Альфа-Банке (это не весь долг компании): есть - {', '.join(has) or 'нет'}; нет - {', '.join(has_not)}",
        f"- [FTS_FLAG] внешнеторговая деятельность: {'да' if p.foreign_trade.fts_flag else 'нет'}"
        + (f"; [FTS_COUNTRY_NAME] страны: {', '.join(p.foreign_trade.countries)}" if p.foreign_trade.countries else ""),
    ]
    if p.industry_position:
        ip = p.industry_position
        share = f", доля выручки класса {ip.revenue_share:.1%}" if ip.revenue_share is not None else ""
        lines.append(f"- [industry_position] место по выручке в классе ОКВЭД {ip.okved2} внутри выборки банка: "
                     f"{ip.revenue_rank} из {ip.peers}{share} (это не доля всего рынка)")
    if p.group:
        g = p.group
        lines.append(f"- [GROUP_ID] группа компаний: {g.size} юрлиц, [group.total_revenue] суммарная выручка {_bn(g.total_revenue)}; "
                     f"[group.top_industries] отрасли группы: {_industries(g.top_industries)}")
    gr = p.graph
    if gr.suppliers_count or gr.buyers_count:
        lines += [
            "- платежи через банк (только часть оборота компании):",
            f"  поставщики: {gr.suppliers_count} внешних, [graph.supplier_industries] {_industries(gr.supplier_industries)}; "
            f"[graph.supplier_unknown_share] вне выборки {gr.supplier_unknown_share or 0:.0%}; "
            f"[graph.supplier_intragroup_share] внутри группы {gr.supplier_intragroup_share or 0:.0%}; "
            f"[graph.supplier_concentration] HHI {gr.supplier_concentration if gr.supplier_concentration is not None else '-'}",
            f"  покупатели: {gr.buyers_count} внешних, [graph.buyer_industries] {_industries(gr.buyer_industries)}; "
            f"[graph.buyer_unknown_share] вне выборки {gr.buyer_unknown_share or 0:.0%}; "
            f"[graph.buyer_intragroup_share] внутри группы {gr.buyer_intragroup_share or 0:.0%}; "
            f"[graph.buyer_concentration] HHI {gr.buyer_concentration if gr.buyer_concentration is not None else '-'}",
        ]
    else:
        lines.append("- платежей с контрагентами в выгрузке нет")
    if role:
        lines.append(f"- [user_role] пользователь: {ROLE_NAMES.get(role, role)}")
    return "\n".join(lines)


def exposures_brief(exps: dict[str, taxonomy.Exposure], factors: list[str], role: str | None) -> str:
    lines = ["ЧУВСТВИТЕЛЬНОСТЬ КЛИЕНТА К ФАКТОРАМ СОБЫТИЯ (детерминированные правила по признакам):"]
    for code in factors:
        e = exps.get(code)
        if e is None:
            continue
        rw = taxonomy.role_weight(role, code)
        head = f"- {code} «{taxonomy.FACTORS[code].label}»: вес {e.weight:.2f}" + (f", приоритет роли x{rw}" if rw != 1 else "")
        lines.append(head)
        lines += [f"    [{r.feature}] {r.text}" for r in e.reasons] or ["    прямых признаков чувствительности нет"]
    return "\n".join(lines)


def dates_block(today, news_published) -> str:
    """Опорные даты: без них модель путает ожидания из прошлых материалов с уже случившимся."""
    return "\n".join([
        f"ДАТЫ: сегодня {ru_date(today)}; новость опубликована {ru_date(news_published) or 'дата неизвестна'}.",
        "- Произошедшим считай только то, о чём прямо написано в новости. Событие, которое в источниках только "
        "ожидается или запланировано (заседание, решение, публикация данных), не подавай как случившееся.",
        "- Материал банка, опубликованный до новости, не оценивает это событие: это ожидания банка на дату "
        "материала («банк ожидал», «банк прогнозировал»), а не его реакция.",
        "- Даты и месяцы бери только из текста источников и их дат публикации, ничего не сдвигай и не достраивай.",
    ])


def news_block(news: dict, meta: NewsClassification) -> str:
    sid = f"news:{news['news_id']}"
    body = (news.get("body") or news.get("summary") or "")[:NEWS_BODY_CHARS]
    tags = ", ".join(f"{f.factor}:{f.direction}" for f in meta.factors) or "нет"
    published = ru_date(news.get("published_at")) or "дата неизвестна"
    return "\n".join([
        f"НОВОСТЬ (source_id {sid}), источник {news.get('source')}, опубликовано {published}, {news.get('url')}",
        injection_guard.wrap_untrusted(f"{news.get('title', '')}\n\n{body}", sid),
        f"Разметка новости: факторы {tags}; отрасли {', '.join(meta.industries) or 'нет'}; "
        f"страны {', '.join(meta.countries) or 'нет'}; важность {meta.importance}/5",
    ])


def bank_source_id(item: dict) -> str:
    return f"bank:{item['doc_id']}:{item.get('page')}"


def bank_flags(it: dict) -> list[str]:
    """Пометки актуальности материала банка: их видят модель-автор, фактчекер и проверка правилами."""
    flags = []
    if it.get("stale"):
        flags.append("УСТАРЕВШИЙ ДОКУМЕНТ")
    if it.get("superseded_by"):
        newer = bank_positions.newer_forecast(it["superseded_by"])
        where = f"«{newer['doc_title']}», {newer['doc_date']} [bank:{newer['doc_id']}:{newer['page']}]" if newer else "более поздний материал"
        what = "прогноз" if it.get("kind") == "position" else "прогнозы на этой странице"
        flags.append(f"{what} ОБНОВЛЁН: актуальная версия - {where}; старые цифры не приводи как текущий прогноз банка")
    if it.get("horizon_passed"):
        flags.append("срок прогноза уже наступил: сравнивай с фактом, не подавай как действующий прогноз")
    return flags


def timing_flag(published, event_date) -> str | None:
    """Материал вышел раньше новости - он не может оценивать это событие."""
    doc, event = parse_date(published), parse_date(event_date)
    if doc and event and (event - doc).days >= 1:
        return (f"вышел за {(event - doc).days} дн. до новости: это ожидания банка на ту дату, не оценка этого "
                "события; в bank_position приводи тезис без даты, сравнение с событием - в ai_inference")
    return None


def bank_block(items: list[dict], event_date=None) -> str:
    if not items:
        return "АНАЛИТИКА АЛЬФА-БАНКА: по теме события материалов не найдено."
    lines = ["АНАЛИТИКА АЛЬФА-БАНКА (Центр макроэкономического анализа; только это - позиция банка):"]
    for it in items:
        flags = bank_flags(it)
        if timing := timing_flag(it.get("published_at"), event_date):
            flags.append(timing)
        kind = "позиция" if it.get("kind") == "position" else "фрагмент"
        lines.append(f"- [{bank_source_id(it)}] «{it.get('title')}», {ru_date(it.get('published_at')) or 'дата неизвестна'}, "
                     f"стр. {it.get('page')}, {kind}" + (f" ({'; '.join(flags)})" if flags else ""))
        lines.append("  " + " ".join((it.get("text") or "").split())[:BANK_TEXT_CHARS])
    return "\n".join(lines)


def related_block(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["СВЯЗАННЫЕ НОВОСТИ (для контекста и перекрёстной проверки):"]
    lines += [f"- [news:{n['news_id']}] {ru_date(n.get('published_at')) or 'дата неизвестна'}: {n.get('title')}"
              + (f" - {n['summary']}" if n.get("summary") else "") for n in items]
    return "\n".join(lines)


def products_block(hints: list[taxonomy.ProductHint]) -> str:
    if not hints:
        return "ПРОДУКТЫ БАНКА: уместных предложений по правилам нет - не предлагай продукты."
    lines = ["ПРОДУКТЫ БАНКА, которые можно предложить, только если это следует из вывода (kind=product, product_code):"]
    lines += [f"- {h.code}: {h.title} - {h.rationale}" for h in hints]
    return "\n".join(lines)


def allowed_features(profile: ClientProfile) -> set[str]:
    feats = set(BASE_FEATURES)
    if profile.graph.suppliers_count or profile.graph.buyers_count:
        feats |= GRAPH_FEATURES
    return feats
