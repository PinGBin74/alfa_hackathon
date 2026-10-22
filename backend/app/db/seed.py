"""Загрузка CSV в БД. Запуск: python -m app.db.seed [--dir data/raw]

Имена колонок - из Приложения 1, разделитель в выгрузке - «;». Загрузка полностью заменяет
companies / persons / payments. Очистка (счётчики печатаются в лог):
- SYNTHETIC_U, который стоит у нескольких разных компаний (артефакт обезличивания), неоднозначен:
  убираем его и из компаний, и из платежей;
- связи физлиц с компаниями вне df_Uid_data_hack.csv отбрасываются (FK на companies);
- платежи компании самой себе отбрасываются, повторы пары плательщик-получатель суммируются.
"""
import argparse
import sys
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


def read_csv(path: Path, columns: dict[str, str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, sep=CSV_SEP, low_memory=False)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/raw")
    parser.add_argument("--companies", default="df_Uid_data_hack.csv")
    parser.add_argument("--persons", default="df_Fid_Uid_link_hack.csv")
    parser.add_argument("--payments", default="df_Uid_payment_hack.csv")
    args = parser.parse_args()

    base = Path(args.dir)
    companies_path, persons_path, payments_path = (base / args.companies, base / args.persons, base / args.payments)
    if not companies_path.exists():
        sys.exit(f"not found: {companies_path}")

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


if __name__ == "__main__":
    main()
