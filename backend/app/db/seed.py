"""Загрузка данных в БД. Запуск: python -m app.db.seed [--dir data/raw] [--news data/synthetic/news.jsonl]

- CSV выгрузки (Приложение 1, разделитель «;») из --dir: data/raw - исходные данные кейса (не в git),
  data/synthetic - синтетические (python -m app.db.synthetic) для проверки без исходных данных;
- тестовые учётные записи из --users (data/test_accounts.json): вход в сервис, роли, доступные компании;
- --news: демо-новости с готовой разметкой (jsonl) - лента работает без сбора RSS и без LLM.

Загрузка полностью заменяет companies / persons / payments и users; новости добавляются, если их ещё нет.
Очистка CSV (счётчики печатаются в лог):
- SYNTHETIC_U, который стоит у нескольких разных компаний (артефакт обезличивания), неоднозначен:
  убираем его и из компаний, и из платежей;
- связи физлиц с компаниями вне df_Uid_data_hack.csv отбрасываются (FK на companies);
- платежи компании самой себе отбрасываются, повторы пары плательщик-получатель суммируются.
"""
import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import delete

from app.db import models
from app.db.session import Base, SessionLocal, engine

CSV_SEP = ";"

COMPANY_MAP = {
    "SYNTHETIC_U": "synthetic_u",
    "ORG_TYPE": "org_type",
    "OKFS_NAME": "okfs_name",
    "COMPANY_AGE_YEARS_GRADATION": "age_gradation",
    "ECO_MARK_LABEL": "eco_mark_label",
    "MAINOKVED_CODE": "mainokved_code",
    "MAINOKVED_NAME": "mainokved_name",
    "NEGATIVEMARK": "negativemark",
    "AMOUNT_WORKERS_FNS_GRADATION": "workers_fns",
    "AMOUNT_WORKERS_SPARK_GRADATION": "workers_spark",
    "CL_TYPE": "cl_type",
    "CL_PRODUCT_RKO_MARK": "has_rko",
    "CL_PRODUCT_GAR_MARK": "has_guarantees",
    "CL_PRODUCT_LOA_MARK": "has_loans",
    "CL_PRODUCT_LEA_MARK": "has_leasing",
    "CL_PRODUCT_DEP_MARK": "has_deposits",
    "CL_PRODUCT_ZPP_MARK": "has_payroll",
    "FTS_FLAG": "fts_flag",
    "FTS_COUNTRY_NAME": "fts_country_name",
    "FACTORING_MARK": "has_factoring",
    "REVENUE_COMPANY": "revenue",
    "GROUP_ID": "group_id",
    "CITY": "city",
    "REGION": "region",
}
BOOL_COLS = [
    "negativemark", "has_rko", "has_guarantees", "has_loans", "has_leasing",
    "has_deposits", "has_payroll", "fts_flag", "has_factoring",
]


PERSON_MAP = {"SYNTHETIC_F": "synthetic_f", "SYNTHETIC_U": "synthetic_u", "CITY_NAME": "city_name", "RC_NAME": "rc_name"}
PAYMENT_MAP = {"PAYER": "payer", "BENEFICIARY": "beneficiary", "PAY_AMT": "pay_amt", "PAY_CNT": "pay_cnt"}


# Коды и идентификаторы - строки: иначе pandas читает ОКВЭД «02.10» как число 2.1 и теряет ведущий ноль
TEXT_COLUMNS = ("SYNTHETIC_U", "SYNTHETIC_F", "MAINOKVED_CODE", "GROUP_ID", "PAYER", "BENEFICIARY")


def read_csv(path: Path, columns: dict[str, str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, sep=CSV_SEP, low_memory=False, dtype=dict.fromkeys(TEXT_COLUMNS, str))
    if columns:
        df = df.rename(columns=columns)
        df = df[[c for c in columns.values() if c in df.columns]]
    return df


def clean_companies(df: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    """Возвращает (компании, неоднозначные id)."""
    dup = df.synthetic_u.duplicated(keep=False)
    ambiguous = set(df.loc[dup, "synthetic_u"])
    df = df[~dup].copy()
    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(bool)
    return df, ambiguous


def clean_persons(df: pd.DataFrame, known: set[str]) -> pd.DataFrame:
    return df[df.synthetic_u.isin(known)]


def clean_payments(df: pd.DataFrame, ambiguous: set[str]) -> pd.DataFrame:
    keep = (df.payer != df.beneficiary) & ~df.payer.isin(ambiguous) & ~df.beneficiary.isin(ambiguous)
    return df[keep].groupby(["payer", "beneficiary"], as_index=False)[["pay_amt", "pay_cnt"]].sum()


def _to_sql(df: pd.DataFrame, table: str, raw_rows: int) -> None:
    df.to_sql(table, engine, if_exists="append", index=False, chunksize=10_000)
    print(f"{table}: loaded {len(df)} of {raw_rows} rows")


def load_users(path: Path) -> None:
    """Полная замена пользователей. Компании, которых нет в загруженной выгрузке, - предупреждение в лог."""
    accounts = json.loads(path.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        known = {cid for (cid,) in db.query(models.Company.synthetic_u)
                 .filter(models.Company.synthetic_u.in_({c for a in accounts for c in a["company_ids"]}))}
        db.execute(delete(models.User))
        for a in accounts:
            db.add(models.User(user_id=a["user_id"], login=a["login"], role=a["role"], company_ids=a["company_ids"]))
            if missing := [c for c in a["company_ids"] if c not in known]:
                print(f"users: {a['login']} - компаний нет в БД: {missing}")
        db.commit()
    print(f"users: loaded {len(accounts)} from {path}")


def load_news(path: Path, now: datetime | None = None) -> None:
    """Демо-новости (news_id, source, title, body, ml_meta): дата публикации - последние часы, чтобы новости
    попали в ленту (окно news_max_age_days); уже загруженные не трогаются."""
    from app.ml.news import NewsClassification

    now = now or datetime.now(UTC)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    added = 0
    with SessionLocal() as db:
        for i, r in enumerate(rows):
            if db.get(models.NewsItem, r["news_id"]) is not None:
                continue
            meta = NewsClassification.model_validate(r["ml_meta"])
            db.add(models.NewsItem(
                news_id=r["news_id"], source=r["source"], url=r.get("url") or f"demo://{r['news_id']}", title=r["title"],
                body=r.get("body"), published_at=now - timedelta(hours=2 * i + 1), dedup_hash=f"demo-{r['news_id']}",
                ml_meta=meta.meta(), **meta.columns()))
            added += 1
        db.commit()
    print(f"news: added {added} of {len(rows)} from {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/raw")
    parser.add_argument("--companies", default="df_Uid_data_hack.csv")
    parser.add_argument("--persons", default="df_Fid_Uid_link_hack.csv")
    parser.add_argument("--payments", default="df_Uid_payment_hack.csv")
    parser.add_argument("--users", default="data/test_accounts.json", help="тестовые учётные записи; '' - не загружать")
    parser.add_argument("--news", help="демо-новости с разметкой (jsonl), например data/synthetic/news.jsonl")
    args = parser.parse_args()

    base = Path(args.dir)
    companies_path, persons_path, payments_path = (base / args.companies, base / args.persons, base / args.payments)
    if not companies_path.exists():
        sys.exit(f"not found: {companies_path} (исходные CSV кейса - в data/raw, синтетика: --dir data/synthetic)")

    Base.metadata.create_all(engine)  # на старте; далее - alembic
    with SessionLocal() as db:  # полная замена: сначала таблицы, которые ссылаются на companies
        for model in (models.Payment, models.Person, models.Company):
            db.execute(delete(model))
        db.commit()

    raw = read_csv(companies_path, COMPANY_MAP)
    companies, ambiguous = clean_companies(raw)
    _to_sql(companies, "companies", len(raw))
    if ambiguous:
        print(f"companies: dropped ambiguous ids {sorted(ambiguous)}")

    for path, columns, table, clean in (
        (persons_path, PERSON_MAP, "persons", lambda df: clean_persons(df, set(companies.synthetic_u))),
        (payments_path, PAYMENT_MAP, "payments", lambda df: clean_payments(df, ambiguous)),
    ):
        if not path.exists():
            print(f"skip (not found): {path}")
            continue
        raw = read_csv(path, columns)
        _to_sql(clean(raw), table, len(raw))
    if args.users:
        load_users(Path(args.users))
    if args.news:
        load_news(Path(args.news))


if __name__ == "__main__":
    main()
