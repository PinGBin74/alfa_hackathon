from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Company, User
from app.db.session import get_db
from app.schemas.client import ClientProfile, ClientSummary
from app.security.rbac import ensure_client_access, get_current_user
from app.services import client_profile

router = APIRouter()


@router.get("", response_model=list[ClientSummary])
def list_clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Компании пользователя в порядке его списка (первая - компания по умолчанию)."""
    order = {cid: i for i, cid in enumerate(user.company_ids or [])}
    rows = sorted(db.query(Company).filter(Company.synthetic_u.in_(order)).all(), key=lambda r: order[r.synthetic_u])
    return [
        ClientSummary(client_id=r.synthetic_u, okved_code=r.mainokved_code, okved_name=r.mainokved_name, city=r.city,
                      region=r.region, revenue=r.revenue,
                      large_business=(r.revenue or 0) > client_profile.LARGE_BUSINESS_REVENUE,
                      client_type=client_profile.CLIENT_TYPES.get(r.cl_type or ""), group_id=r.group_id)
        for r in rows
    ]


@router.get("/{client_id}/profile", response_model=ClientProfile)
def get_profile(client_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_client_access(user, client_id)
    profile = client_profile.build_profile(db, client_id)
    if profile is None:
        raise HTTPException(404, "Client not found")
    return profile
