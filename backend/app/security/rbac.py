"""Авторизация и разграничение доступа.

Сервис создаётся для людей, а не для юрлиц: у одной компании несколько
пользователей с разными ролями (собственник, ГД, ФД, главбух, казначей...).
Роль влияет на то, какие аспекты инсайта выносятся на первый план.
"""
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

bearer = HTTPBearer(auto_error=False)

ROLE_FOCUS = {
    "owner": ["стратегия", "риски группы", "капитал"],
    "ceo": ["рынок", "конкуренты", "регулирование"],
    "cfo": ["ставки", "курсы", "ликвидность", "долговая нагрузка"],
    "chief_accountant": ["налоги", "регулирование", "отчётность"],
    "treasurer": ["курсы", "ставки", "ликвидность", "платёжный календарь"],
    "c_level": ["рынок", "операционные риски"],
    "other": [],
}


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=s.jwt_ttl_minutes)
    return jwt.encode({"sub": user.user_id, "role": user.role, "exp": exp}, s.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None
    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def ensure_client_access(user: User, client_id: str) -> None:
    """Пользователь видит только компании из своего списка."""
    if client_id not in (user.company_ids or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this company")
