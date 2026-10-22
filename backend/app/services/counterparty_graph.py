"""Граф контрагентов по платежам, групповые связи.

Направление (Приложение 1): PAYER - отправитель, BENEFICIARY - получатель. Для клиента поставщики -
те, кому он платит, покупатели - те, кто платит ему. Платежи внутри своей группы (GROUP_ID) идут
отдельной долей: это перераспределение денег, а не зависимость от внешнего рынка. У большей части
контрагентов нет карточки в выборке, их оборот виден, а отрасль нет (unknown_share).

Даёт признаки: топ поставщиков/покупателей с отраслью, отраслевую структуру оборота, концентрацию
(HHI). Это основа для объяснений вида «30% закупок - у металлургов» или «зависимость от одного покупателя».
"""
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.db.models import Company, Payment
from app.schemas.client import Counterparty, GraphFeatures, IndustryShare


def okved2(code: str | None) -> str | None:
    return code.split(".")[0] if code else None


def _hhi(amounts: list[float]) -> float | None:
    total = sum(amounts)
    if total <= 0:
        return None
    return round(sum((a / total) ** 2 for a in amounts), 4)


def industry_shares(items: Iterable[tuple[str | None, str | None, float]], total: float,
                    top_n: int = 5) -> list[IndustryShare]:
    """items: (okved_code, okved_name, amount). Доли - от total, чтобы вместе с долей
    неизвестных контрагентов давать 1."""
    if total <= 0:
        return []
    by_class: dict[str, float] = defaultdict(float)
    names: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for code, name, amount in items:
        cls = okved2(code)
        if cls is None:
            continue
        by_class[cls] += amount
        if name:
            names[cls][name] += amount
    top = sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        IndustryShare(
            okved2=cls,
            share=round(amount / total, 4),
            examples=[n for n, _ in sorted(names[cls].items(), key=lambda kv: kv[1], reverse=True)[:2]],
        )
        for cls, amount in top
    ]


@dataclass
class _Flow:
    cp_id: str
    amount: float
    payments: int
    okved_code: str | None
    okved_name: str | None
    region: str | None
    group_id: str | None


@dataclass
class _Side:
    top: list[Counterparty] = field(default_factory=list)
    concentration: float | None = None
    turnover: float = 0.0
    count: int = 0
    industries: list[IndustryShare] = field(default_factory=list)
    unknown_share: float | None = None
    intragroup_share: float | None = None


def _flows(db: Session, client_id: str, direction: Literal["out", "in"]) -> list[_Flow]:
    own, other = (Payment.payer, Payment.beneficiary) if direction == "out" else (Payment.beneficiary, Payment.payer)
    cp = aliased(Company)
    rows = (
        db.query(
            other.label("cp_id"),
            func.sum(Payment.pay_amt).label("amt"),
            func.sum(Payment.pay_cnt).label("cnt"),
            cp.mainokved_code, cp.mainokved_name, cp.region, cp.group_id,
        )
        .outerjoin(cp, cp.synthetic_u == other)
        .filter(own == client_id, other != client_id)
        .group_by(other, cp.mainokved_code, cp.mainokved_name, cp.region, cp.group_id)
        .all()
    )
    return [
        _Flow(r.cp_id, float(r.amt or 0), int(r.cnt or 0), r.mainokved_code, r.mainokved_name, r.region, r.group_id)
        for r in rows
    ]


def _side(flows: list[_Flow], group_id: str | None, top_n: int) -> _Side:
    intra = [f for f in flows if group_id and f.group_id == group_id]
    ext = sorted((f for f in flows if not (group_id and f.group_id == group_id)), key=lambda f: f.amount, reverse=True)
    total_all = sum(f.amount for f in flows)
    turnover = sum(f.amount for f in ext)
    side = _Side(
        turnover=turnover,
        count=len(ext),
        intragroup_share=round(sum(f.amount for f in intra) / total_all, 4) if total_all > 0 else None,
    )
    if turnover <= 0:
        return side
    side.top = [
        Counterparty(
            client_id=f.cp_id, amount=f.amount, share=round(f.amount / turnover, 4), payments=f.payments,
            okved_code=f.okved_code, okved_name=f.okved_name, region=f.region,
        )
        for f in ext[:top_n]
    ]
    side.concentration = _hhi([f.amount for f in ext])
    side.industries = industry_shares(((f.okved_code, f.okved_name, f.amount) for f in ext), turnover)
    side.unknown_share = round(sum(f.amount for f in ext if f.okved_code is None) / turnover, 4)
    return side


def features(db: Session, client_id: str, top_n: int = 5) -> GraphFeatures:
    company = db.get(Company, client_id)
    group_id = company.group_id if company else None
    out = _side(_flows(db, client_id, "out"), group_id, top_n)
    inc = _side(_flows(db, client_id, "in"), group_id, top_n)

    group_size = None
    if group_id:
        group_size = db.query(func.count(Company.synthetic_u)).filter(Company.group_id == group_id).scalar()

    return GraphFeatures(
        top_suppliers=out.top,
        top_buyers=inc.top,
        supplier_concentration=out.concentration,
        buyer_concentration=inc.concentration,
        supplier_turnover=out.turnover,
        buyer_turnover=inc.turnover,
        suppliers_count=out.count,
        buyers_count=inc.count,
        supplier_industries=out.industries,
        buyer_industries=inc.industries,
        supplier_unknown_share=out.unknown_share,
        buyer_unknown_share=inc.unknown_share,
        supplier_intragroup_share=out.intragroup_share,
        buyer_intragroup_share=inc.intragroup_share,
        group_size=group_size,
        regions_of_counterparties=sorted({c.region for c in out.top + inc.top if c.region}),
    )
