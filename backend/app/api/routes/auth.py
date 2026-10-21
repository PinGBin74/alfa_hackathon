from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.security.rbac import create_token, get_current_user

router = APIRouter()


class LoginIn(BaseModel):
    login: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    """Прототип: вход по логину тестовой учётки (data/test_accounts.json). В проде - SSO интернет-банка."""
    user = db.query(User).filter_by(login=body.login).first()
    if not user:
        raise HTTPException(401, "Unknown login")
    return {"access_token": create_token(user), "role": user.role, "company_ids": user.company_ids}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": user.user_id, "login": user.login, "role": user.role, "company_ids": user.company_ids}
