"""Загрузка CSV в БД. Запуск: python -m app.db.seed [--dir data/synthetic]

Имена колонок - из Приложения 1. Перед первым запуском сверьте фактические
заголовки файлов (в задании у физлиц и платежей указано одно имя файла).
"""
import argparse
from pathlib import Path

import pandas as pd

from app.db import models
from app.db.session import Base, SessionLocal, engine

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


def load_companies(path: Path) -> None:
    df = pd.read_csv(path).rename(columns=COMPANY_MAP)
    df = df[[c for c in COMPANY_MAP.values() if c in df.columns]]
    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(bool)
    df.to_sql("companies", engine, if_exists="append", index=False, chunksize=5000)


def load_persons(path: Path) -> None:
    df = pd.read_csv(path).rename(columns={
        "SYNTHETIC_F": "synthetic_f", "SYNTHETIC_U": "synthetic_u",
        "CITY_NAME": "city_name", "RC_NAME": "rc_name",
    })
    df.to_sql("persons", engine, if_exists="append", index=False, chunksize=5000)


def load_payments(path: Path) -> None:
    df = pd.read_csv(path).rename(columns={
        "PAYER": "payer", "BENEFICIARY": "beneficiary",
        "PAY_AMT": "pay_amt", "PAY_CNT": "pay_cnt",
    })
    df.to_sql("payments", engine, if_exists="append", index=False, chunksize=5000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/synthetic")
    parser.add_argument("--companies", default="df_Uid_data_hack.csv")
    parser.add_argument("--persons", default="df_Fid_Uid_link_hack.csv")
    parser.add_argument("--payments", default="df_payments_hack.csv")  # TODO: уточнить имя файла платежей
    args = parser.parse_args()

    base = Path(args.dir)
    Base.metadata.create_all(engine)  # на старте; далее - alembic

    for name, loader in (
        (args.companies, load_companies),
        (args.persons, load_persons),
        (args.payments, load_payments),
    ):
        p = base / name
        if p.exists():
            print(f"loading {p}")
            loader(p)
        else:
            print(f"skip (not found): {p}")

    with SessionLocal() as db:
        print("companies:", db.query(models.Company).count())


if __name__ == "__main__":
    main()
