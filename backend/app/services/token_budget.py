"""Учёт токенов и дневной бюджет (лимит общего ключа: 500 руб/день)."""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import TokenUsage


class BudgetExceeded(Exception):
    pass


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    s = get_settings()
    return tokens_in / 1000 * s.price_per_1k_input_rub + tokens_out / 1000 * s.price_per_1k_output_rub


def spent_today(db: Session) -> float:
    today = date.today().isoformat()
    return float(db.query(func.coalesce(func.sum(TokenUsage.cost_rub), 0.0)).filter(TokenUsage.day == today).scalar())


def check_budget(db: Session) -> None:
    if spent_today(db) >= get_settings().daily_budget_rub:
        raise BudgetExceeded("Daily LLM budget exhausted")


def record(db: Session, model: str, tokens_in: int, tokens_out: int) -> float:
    cost = estimate_cost(tokens_in, tokens_out)
    db.add(TokenUsage(day=date.today().isoformat(), model=model,
                      tokens_in=tokens_in, tokens_out=tokens_out, cost_rub=cost))
    db.commit()
    return cost
