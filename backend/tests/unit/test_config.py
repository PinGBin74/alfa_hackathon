"""Настройки: адрес БД собирается из POSTGRES_*, если DATABASE_URL не задан (так в Docker)."""
from sqlalchemy.engine import make_url

from app.config import Settings

RESERVED_URL_CHARS = "@/:?#%"  # без экранирования ломают строку подключения


def test_database_url_built_from_postgres_parts():
    s = Settings(_env_file=None, postgres_user="alfa", postgres_password=RESERVED_URL_CHARS, postgres_db="news",
                 postgres_host="db", postgres_port=5433)
    url = make_url(s.database_url)
    assert url.drivername == "postgresql+psycopg" and url.host == "db" and url.port == 5433
    assert url.username == "alfa" and url.password == RESERVED_URL_CHARS and url.database == "news"


def test_explicit_database_url_wins():
    s = Settings(_env_file=None, database_url="postgresql+psycopg://u@h:1/d", postgres_host="db")
    assert s.database_url == "postgresql+psycopg://u@h:1/d"


def test_database_url_without_password():
    assert make_url(Settings(_env_file=None, postgres_password="").database_url).password is None
