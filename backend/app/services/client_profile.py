from sqlalchemy.orm import Session

from app.db.models import Company
from app.schemas.client import ClientProfile, ForeignTrade, Products
from app.services import counterparty_graph


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
        city=c.city,
        region=c.region,
        client_type="existing" if (c.cl_type or "").lower().startswith("д") else "potential",
        products=Products(
            rko=bool(c.has_rko), guarantees=bool(c.has_guarantees), loans=bool(c.has_loans),
            leasing=bool(c.has_leasing), deposits=bool(c.has_deposits),
            payroll=bool(c.has_payroll), factoring=bool(c.has_factoring),
        ),
        foreign_trade=ForeignTrade(
            fts_flag=bool(c.fts_flag),
            countries=[c.fts_country_name] if c.fts_country_name else [],
        ),
    )
    if with_graph:
        profile.graph = counterparty_graph.features(db, client_id)
    return profile
