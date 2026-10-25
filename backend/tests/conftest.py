"""Общие настройки тестов (SQLite в памяти вместо Postgres)."""
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):
    """В SQLite автоинкремент есть только у INTEGER PRIMARY KEY (agent_traces.id - BigInteger)."""
    return "INTEGER"
