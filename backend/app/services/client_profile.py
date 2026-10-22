"""Профиль компании: признаки из df_Uid_data_hack.csv, группа компаний, положение в отрасли."""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import Company
from app.schemas.client import ClientProfile, ForeignTrade, GroupInfo, IndustryPosition, Products
from app.services import counterparty_graph

LARGE_BUSINESS_REVENUE = 15e9  # порог кейса: крупный бизнес - выручка свыше 15 млрд руб.

# CL_TYPE в выгрузке: CLIENT, PROSPECT, CLOSE_CLIENT. CLOSE_CLIENT трактуем как бывшего клиента
# (закрыл обслуживание); исходное значение остаётся в cl_type.
CLIENT_TYPES = {"CLIENT": "existing", "PROSPECT": "potential", "CLOSE_CLIENT": "closed"}


def _countries(raw: str | None) -> list[str]:
    """FTS_COUNTRY_NAME бывает списком: «КИТАЙ, ТУРЦИЯ»."""
    return [c.strip() for c in raw.split(",") if c.strip()] if raw else []


def _group(db: Session, group_id: str | None) -> GroupInfo | None:
    if not group_id:
        return None
    rows = (
        db.query(Company.mainokved_code, Company.mainokved_name, Company.revenue)
        .filter(Company.group_id == group_id)
        .all()
    )
    total = sum(r.revenue or 0 for r in rows)
    return GroupInfo(
        group_id=group_id,
        size=len(rows),
        total_revenue=total,
        large_business=total > LARGE_BUSINESS_REVENUE,
        top_industries=counterparty_graph.industry_shares(
            ((r.mainokved_code, r.mainokved_name, r.revenue or 0) for r in rows), total, top_n=3
        ),
    )


def _industry_position(db: Session, c: Company) -> IndustryPosition | None:
    cls = counterparty_graph.okved2(c.mainokved_code)
    if cls is None:
        return None
    in_class = or_(Company.mainokved_code == cls, Company.mainokved_code.like(f"{cls}.%"))
    peers, class_revenue = db.query(func.count(Company.synthetic_u), func.sum(Company.revenue)).filter(in_class).one()
    rank = share = None
    if c.revenue is not None:
        rank = db.query(func.count(Company.synthetic_u)).filter(in_class, Company.revenue > c.revenue).scalar() + 1
        share = round(c.revenue / class_revenue, 4) if class_revenue else None
    return IndustryPosition(okved2=cls, peers=peers, revenue_rank=rank, revenue_share=share)


def build_profile(db: Session, client_id: str, with_graph: bool = True) -> ClientProfile | None:
    c = db.get(Company, client_id)
    if c is None:
        return None
    profile = ClientProfile(
        client_id=c.synthetic_u,
        group_id=c.group_id,
        okved_code=c.mainokved_code,
        okved_name=c.mainokved_name,
        org_type=c.org_type,
        ownership=c.okfs_name,
        age_gradation=c.age_gradation,
        stage=c.eco_mark_label,
        workers_fns=c.workers_fns,
        workers_spark=c.workers_spark,
        revenue=c.revenue,
        large_business=(c.revenue or 0) > LARGE_BUSINESS_REVENUE,
        negative_mark=c.negativemark,
        city=c.city,
        region=c.region,
        client_type=CLIENT_TYPES.get(c.cl_type or ""),
        cl_type=c.cl_type,
        products=Products(
            rko=bool(c.has_rko), guarantees=bool(c.has_guarantees), loans=bool(c.has_loans),
            leasing=bool(c.has_leasing), deposits=bool(c.has_deposits),
            payroll=bool(c.has_payroll), factoring=bool(c.has_factoring),
        ),
        foreign_trade=ForeignTrade(fts_flag=bool(c.fts_flag), countries=_countries(c.fts_country_name)),
        group=_group(db, c.group_id),
        industry_position=_industry_position(db, c),
    )
    if with_graph:
        profile.graph = counterparty_graph.features(db, client_id)
    return profile
