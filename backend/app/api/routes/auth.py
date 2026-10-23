from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.context import ROLE_NAMES
from app.config import get_settings
from app.db.models import Company, User
from app.db.session import get_db
from app.security.rbac import create_token, get_current_user

router = APIRouter()


class LoginIn(BaseModel):
    login: str


def _user_out(user: User) -> dict:
    return {"user_id": user.user_id, "login": user.login, "role": user.role,
            "role_name": ROLE_NAMES.get(user.role, user.role), "company_ids": user.company_ids}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    """Прототип: вход по логину тестовой учётки (data/test_accounts.json). В проде - SSO интернет-банка."""
    user = db.query(User).filter_by(login=body.login).first()
    if not user:
        raise HTTPException(401, "Unknown login")
    return {"access_token": create_token(user), **_user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _user_out(user)


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)) -> list[dict]:
    """Тестовые учётки для экрана входа прототипа (кроме APP_ENV=prod): логин, роль, компании."""
    if get_settings().app_env == "prod":
        raise HTTPException(404, "Not found")
    users = db.query(User).order_by(User.user_id).all()
    ids = {c for u in users for c in u.company_ids or []}
    companies = {c.synthetic_u: c for c in db.query(Company).filter(Company.synthetic_u.in_(ids))}
    return [_user_out(u) | {"companies": [
        {"client_id": cid, "okved_name": companies[cid].mainokved_name if cid in companies else None,
         "region": companies[cid].region if cid in companies else None} for cid in u.company_ids or []]}
        for u in users]
