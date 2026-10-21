"""Модель данных. Поля компаний повторяют Приложение 1 задания."""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.db.session import Base

EMB_DIM = get_settings().embedding_dim


def hnsw_cosine_index(table: str) -> Index:
    """HNSW-индекс по embedding под поиск cosine_distance (оператор <=>)."""
    return Index(
        f"ix_{table}_embedding_hnsw",
        "embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class Company(Base):
    """df_Uid_data_hack.csv"""

    __tablename__ = "companies"

    synthetic_u: Mapped[str] = mapped_column(String, primary_key=True)
    org_type: Mapped[str | None] = mapped_column(String)
    okfs_name: Mapped[str | None] = mapped_column(String)
    age_gradation: Mapped[str | None] = mapped_column(String)
    eco_mark_label: Mapped[str | None] = mapped_column(String)
    mainokved_code: Mapped[str | None] = mapped_column(String, index=True)
    mainokved_name: Mapped[str | None] = mapped_column(String)
    negativemark: Mapped[bool | None] = mapped_column(Boolean)
    workers_fns: Mapped[str | None] = mapped_column(String)
    workers_spark: Mapped[str | None] = mapped_column(String)
    cl_type: Mapped[str | None] = mapped_column(String)
    has_rko: Mapped[bool | None] = mapped_column(Boolean)
    has_guarantees: Mapped[bool | None] = mapped_column(Boolean)
    has_loans: Mapped[bool | None] = mapped_column(Boolean)
    has_leasing: Mapped[bool | None] = mapped_column(Boolean)
    has_deposits: Mapped[bool | None] = mapped_column(Boolean)
    has_payroll: Mapped[bool | None] = mapped_column(Boolean)
    fts_flag: Mapped[bool | None] = mapped_column(Boolean)
    fts_country_name: Mapped[str | None] = mapped_column(String)
    has_factoring: Mapped[bool | None] = mapped_column(Boolean)
    revenue: Mapped[float | None] = mapped_column(Float)
    group_id: Mapped[str | None] = mapped_column(String, index=True)
    city: Mapped[str | None] = mapped_column(String)
    region: Mapped[str | None] = mapped_column(String, index=True)


class Person(Base):
    """Связанные физлица (обезличены)."""

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    synthetic_f: Mapped[str] = mapped_column(String, index=True)
    synthetic_u: Mapped[str] = mapped_column(ForeignKey("companies.synthetic_u"), index=True)
    city_name: Mapped[str | None] = mapped_column(String)
    rc_name: Mapped[str | None] = mapped_column(String)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payer: Mapped[str] = mapped_column(String, index=True)
    beneficiary: Mapped[str] = mapped_column(String, index=True)
    pay_amt: Mapped[float | None] = mapped_column(Float)
    pay_cnt: Mapped[int | None] = mapped_column(Integer)


class NewsItem(Base):
    __tablename__ = "news"
    __table_args__ = (hnsw_cosine_index("news"),)

    news_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    key_facts: Mapped[list | None] = mapped_column(JSON)
    industries: Mapped[list | None] = mapped_column(JSON)
    regions: Mapped[list | None] = mapped_column(JSON)
    event_type: Mapped[str | None] = mapped_column(String, index=True)
    dedup_hash: Mapped[str] = mapped_column(String, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    embedding = mapped_column(Vector(EMB_DIM), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsDoc(Base):
    """Материалы Центра макроэкономических исследований Альфа-Банка (Приложение 2)."""

    __tablename__ = "analytics_docs"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    topics: Mapped[list | None] = mapped_column(JSON)


class AnalyticsChunk(Base):
    __tablename__ = "analytics_chunks"
    __table_args__ = (hnsw_cosine_index("analytics_chunks"),)

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("analytics_docs.doc_id"), index=True)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMB_DIM), nullable=True)


class User(Base):
    """Пользователь сервиса (человек, не юрлицо). Одна компания - несколько ролей."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    login: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[str] = mapped_column(String)  # owner | ceo | cfo | chief_accountant | treasurer | c_level | other
    company_ids: Mapped[list] = mapped_column(JSON)  # доступные SYNTHETIC_U


class InsightRecord(Base):
    __tablename__ = "insights"

    insight_id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    user_role: Mapped[str | None] = mapped_column(String)
    news_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)  # соответствует contracts/insight.schema.json
    trace_id: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTrace(Base):
    """Журнал шагов агента: источники, признаки компании, промежуточные результаты."""

    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String, index=True)
    step: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)  # plan | tool_call | llm_call | verify | final
    name: Mapped[str | None] = mapped_column(String)
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    model: Mapped[str] = mapped_column(String)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_rub: Mapped[float] = mapped_column(Float, default=0.0)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insight_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String)
    rating: Mapped[int] = mapped_column(Integer)  # -1 | 0 | 1
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
