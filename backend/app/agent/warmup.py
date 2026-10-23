"""Прогрев разборов для демо: агент заранее готовит инсайты по верху ленты каждого тестового пользователя.

Запуск: python -m app.agent.warmup [--top 2] [--dry-run]
Разбор кэшируется по (компания, новость, роль), поэтому жюри открывает готовые карточки сразу, а живую
генерацию (1-1,5 мин) видно на любой другой новости ленты. Цена - около 0,8 ₽ за разбор (бюджет: 500 ₽/день).
"""
import argparse
import logging

from app.agent import orchestrator
from app.agent.llm_client import LLMError
from app.api.routes.insights import cached_insight
from app.db.models import User
from app.db.session import SessionLocal
from app.services import client_profile, feed
from app.services.token_budget import BudgetExceeded

log = logging.getLogger("warmup")


def plan(db, top: int) -> list[tuple[str, str, str, str]]:
    """(компания, новость, роль, заголовок) - верх ленты каждого пользователя, без готовых разборов и повторов."""
    todo, seen = [], set()
    for user in db.query(User).order_by(User.user_id):
        for client_id in user.company_ids or []:
            profile = client_profile.build_profile(db, client_id)
            if profile is None:
                continue
            for news, _ in feed.ranked(db, profile, user.role, top):
                key = (client_id, news.news_id, user.role)
                if key not in seen and cached_insight(db, *key) is None:
                    seen.add(key)
                    todo.append((*key, news.title))
    return todo


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=2, help="сколько верхних новостей ленты разобрать для каждой компании")
    parser.add_argument("--dry-run", action="store_true", help="только показать, что будет разобрано")
    args = parser.parse_args()
    with SessionLocal() as db:
        todo = plan(db, args.top)
        log.info("разборов к подготовке: %d (~%.0f ₽)", len(todo), len(todo) * 0.8)
        for client_id, news_id, role, title in todo:
            if args.dry_run:
                log.info("%s / %s / %s: %s", client_id, role, news_id, title[:80])
                continue
            try:
                ins = orchestrator.run(db, client_id, news_id, user_role=role)
                log.info("готово %s / %s: %s (проверка: %s)", client_id, role, title[:70], ins.verification.passed)
            except BudgetExceeded:
                log.warning("дневной бюджет LLM исчерпан, прогрев остановлен")
                return
            except (LLMError, LookupError) as e:
                log.warning("пропуск %s / %s: %s", client_id, news_id, e)


if __name__ == "__main__":
    main()
