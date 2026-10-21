"""Граф контрагентов по платежам, групповые связи.

Даёт признаки: топ поставщиков/покупателей, концентрация (HHI), размер группы,
регионы контрагентов. Это основа для объяснений вида «зависимость от одного поставщика».
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Company, Payment
from app.schemas.client import GraphFeatures


def _hhi(amounts: list[float]) -> float | None:
    total = sum(amounts)
    if total <= 0:
        return None
    return round(sum((a / total) ** 2 for a in amounts), 4)


def features(db: Session, client_id: str, top_n: int = 5) -> GraphFeatures:
    suppliers = (
        db.query(Payment.payer.label("id"), func.sum(Payment.pay_amt).label("amt"))
        .filter(Payment.beneficiary == client_id)  # TODO: сверить направление платежа с семантикой данных
        .group_by(Payment.payer)
        .order_by(func.sum(Payment.pay_amt).desc())
        .all()
    )
    buyers = (
        db.query(Payment.beneficiary.label("id"), func.sum(Payment.pay_amt).label("amt"))
        .filter(Payment.payer == client_id)
        .group_by(Payment.beneficiary)
        .order_by(func.sum(Payment.pay_amt).desc())
        .all()
    )

    company = db.get(Company, client_id)
    group_size = None
    if company and company.group_id:
        group_size = db.query(func.count(Company.synthetic_u)).filter(Company.group_id == company.group_id).scalar()

    cp_ids = [r.id for r in suppliers[:top_n]] + [r.id for r in buyers[:top_n]]
    regions: list[str] = []
    if cp_ids:
        rows = db.query(Company.region).filter(Company.synthetic_u.in_(cp_ids)).distinct().all()
        regions = [r[0] for r in rows if r[0]]

    return GraphFeatures(
        top_suppliers=[{"client_id": r.id, "amount": float(r.amt or 0)} for r in suppliers[:top_n]],
        top_buyers=[{"client_id": r.id, "amount": float(r.amt or 0)} for r in buyers[:top_n]],
        supplier_concentration=_hhi([float(r.amt or 0) for r in suppliers]),
        buyer_concentration=_hhi([float(r.amt or 0) for r in buyers]),
        group_size=group_size,
        regions_of_counterparties=regions,
    )
