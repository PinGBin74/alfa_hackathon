"""Синтетические данные для воспроизводимой проверки без исходной выгрузки банка.

Запуск: python -m app.db.synthetic [--profiles ../eval/fixtures/demo_profiles.json] [--out ../data/synthetic]
Результат - три CSV в формате Приложения 1 (разделитель «;») и news.jsonl; загрузка: python -m app.db.seed
--dir data/synthetic --news data/synthetic/news.jsonl.

Демо-клиенты (их id - в data/test_accounts.json) воспроизводят признаки из eval/fixtures/demo_profiles.json:
ОКВЭД, регион, выручку, продукты, ВЭД, группу компаний, место в отрасли и структуру платежей (топ контрагентов,
отраслевые доли, долю неизвестных и внутригрупповых платежей). Остальные компании и платежи сгенерированы
(детерминированно, seed 2026) так, чтобы профиль и граф клиента получились близкими к исходным. Это не выгрузка
банка: id сгенерированных компаний - SYN_U_*, контрагентов вне выборки - SYN_X_*.
"""
import argparse
import json
import math
import random
from pathlib import Path

from app.ml.taxonomy import OKVED2_CLASSES

CSV_SEP = ";"
COMPANY_COLUMNS = [
    "SYNTHETIC_U", "ORG_TYPE", "OKFS_NAME", "COMPANY_AGE_YEARS_GRADATION", "ECO_MARK_LABEL", "MAINOKVED_CODE",
    "MAINOKVED_NAME", "NEGATIVEMARK", "AMOUNT_WORKERS_FNS_GRADATION", "AMOUNT_WORKERS_SPARK_GRADATION", "CL_TYPE",
    "CL_PRODUCT_RKO_MARK", "CL_PRODUCT_GAR_MARK", "CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK", "CL_PRODUCT_DEP_MARK",
    "CL_PRODUCT_ZPP_MARK", "FTS_FLAG", "FTS_COUNTRY_NAME", "FACTORING_MARK", "REVENUE_COMPANY", "GROUP_ID", "CITY",
    "REGION",
]
PRODUCT_COLUMNS = {
    "rko": "CL_PRODUCT_RKO_MARK", "guarantees": "CL_PRODUCT_GAR_MARK", "loans": "CL_PRODUCT_LOA_MARK",
    "leasing": "CL_PRODUCT_LEA_MARK", "deposits": "CL_PRODUCT_DEP_MARK", "payroll": "CL_PRODUCT_ZPP_MARK",
    "factoring": "FACTORING_MARK",
}
# Мелкие отрасли «прочих» контрагентов: в топ-5 отраслей клиента они не попадают
FILLER_CLASSES = ["33", "43", "49", "52", "62", "69", "70", "71", "73", "74", "77", "78", "80", "81", "82", "85",
                  "18", "22", "26", "27", "31", "32", "38", "53", "56", "58", "63", "65", "66", "86"]
MAX_PEERS = 300  # компаний того же класса ОКВЭД; в выборке их бывают тысячи - для профиля важна доля, а не число
CITIES = [("г. Москва", "Москва"), ("г. Санкт-Петербург", "Санкт-Петербург"), ("г. Новосибирск", "Новосибирская область"),
          ("г. Екатеринбург", "Свердловская область"), ("г. Казань", "Республика Татарстан"),
          ("г. Краснодар", "Краснодарский край"), ("г. Самара", "Самарская область")]


def class_name(cls: str, default: str | None = None) -> str:
    return OKVED2_CLASSES.get(cls) or default or "Деятельность прочая"


class Generator:
    def __init__(self, seed: int = 2026):
        self.rnd = random.Random(seed)
        self.companies: dict[str, dict] = {}
        self.payments: list[dict] = []
        self.persons: list[dict] = []
        self._n = {"U": 0, "X": 0, "F": 0}

    def new_id(self, kind: str) -> str:
        self._n[kind] += 1
        return f"SYN_{kind}_{self._n[kind]:05d}"

    def company(self, cid: str, okved_code: str | None, okved_name: str | None, revenue: float | None,
                region: str | None = None, city: str | None = None, group_id: str | None = None,
                persons: bool = True, **extra) -> str:
        if cid in self.companies:
            return cid
        if region is None:
            city, region = self.rnd.choice(CITIES)
        row = {c: "" for c in COMPANY_COLUMNS} | {
            "SYNTHETIC_U": cid, "ORG_TYPE": "КОММ_ОРГ", "OKFS_NAME": "ЧАСТНАЯ СОБСТВЕННОСТЬ",
            "COMPANY_AGE_YEARS_GRADATION": self.rnd.choice(["3-5", "6-10", "11-15", "16-25"]),
            "ECO_MARK_LABEL": "Бизнес в новой реальности", "MAINOKVED_CODE": okved_code or "",
            "MAINOKVED_NAME": okved_name or "", "NEGATIVEMARK": 0,
            "AMOUNT_WORKERS_FNS_GRADATION": self.rnd.choice(["16-50", "51-100", "101-250", "Более 251"]),
            "CL_TYPE": self.rnd.choice(["CLIENT", "PROSPECT"]), "CL_PRODUCT_RKO_MARK": 1,
            "REVENUE_COMPANY": round(revenue) if revenue else "", "GROUP_ID": group_id or "",
            "CITY": city or "", "REGION": region or "",
        }
        row.update(extra)
        self.companies[cid] = row
        for _ in range(self.rnd.randint(1, 2) if persons else 0):
            self.persons.append({"SYNTHETIC_F": self.new_id("F"), "CITY_NAME": row["CITY"],
                                 "RC_NAME": row["REGION"], "SYNTHETIC_U": cid})
        return cid

    def pay(self, payer: str, beneficiary: str, amount: float, count: int | None = None) -> None:
        if amount > 0:
            self.payments.append({"BENEFICIARY": beneficiary, "PAYER": payer, "PAY_AMT": round(amount),
                                  "PAY_CNT": count or self.rnd.randint(1, 40)})

    def split(self, total: float, cap: float, min_parts: int = 1) -> list[float]:
        """Сумма total частями не больше cap (чтобы не вытеснить заданный топ контрагентов)."""
        if total <= 0:
            return []
        n = max(min_parts, math.ceil(total / max(cap, 1.0)))
        weights = [self.rnd.uniform(0.5, 1.5) for _ in range(n)]
        parts = [total * w / sum(weights) for w in weights]
        while max(parts) > cap and n < 10_000:  # перекос весов: делим мельче
            n *= 2
            parts = [total / n] * n
        return parts

    # ---------- демо-клиент ----------

    def client(self, p: dict) -> None:
        cid, group = p["client_id"], p.get("group")
        products = {col: int(bool(p["products"].get(k))) for k, col in PRODUCT_COLUMNS.items()}
        self.company(
            cid, p.get("okved_code"), p.get("okved_name"), p.get("revenue"), region=p.get("region"),
            city=p.get("city"), group_id=p.get("group_id"), ORG_TYPE=p.get("org_type") or "КОММ_ОРГ",
            OKFS_NAME=p.get("ownership") or "", COMPANY_AGE_YEARS_GRADATION=p.get("age_gradation") or "",
            ECO_MARK_LABEL=p.get("stage") or "", NEGATIVEMARK=int(bool(p.get("negative_mark"))),
            AMOUNT_WORKERS_FNS_GRADATION=p.get("workers_fns") or "", AMOUNT_WORKERS_SPARK_GRADATION=p.get("workers_spark") or "",
            CL_TYPE=p.get("cl_type") or "", FTS_FLAG=int(bool(p["foreign_trade"]["fts_flag"])),
            FTS_COUNTRY_NAME=", ".join(p["foreign_trade"]["countries"]), **products,
        )
        siblings = self.group(cid, p, group) if group else []
        g = p.get("graph") or {}
        for side in ("supplier", "buyer"):
            self.side(cid, p, g, side, siblings)

    def group(self, cid: str, p: dict, group: dict) -> list[str]:
        """Участники группы: выручка группы (без самого клиента) по её отраслевым долям; доля вне топ-3 отраслей -
        у участников из мелких отраслей, каждая меньше последней из топа."""
        others = max(0, group["size"] - 1)
        if not others:
            return []
        total, own = group.get("total_revenue") or 0.0, p.get("revenue") or 0.0
        own_cls = (p.get("okved_code") or "").split(".")[0]
        buckets = [[i["okved2"], i["share"] * total - (own if i["okved2"] == own_cls else 0.0), i.get("examples") or []]
                   for i in group["top_industries"]]
        rest = total * max(0.0, 1 - sum(i["share"] for i in group["top_industries"]))
        per_class = 0.7 * min((b[1] for b in buckets if b[1] > 0), default=rest)
        listed = {b[0] for b in buckets}
        for cls in (c for c in FILLER_CLASSES if c not in listed):
            if rest <= 0 or len(buckets) >= others:
                break
            buckets.append([cls, min(rest, per_class), []])
            rest -= min(rest, per_class)
        if rest > 0 and buckets:  # не уместилось - добавляем к крупнейшей отрасли
            max(buckets, key=lambda b: b[1])[1] += rest
        # участников - пропорционально выручке отрасли, хотя бы по одному
        weights = [max(b[1], 0.0) for b in buckets]
        counts = [1] * len(buckets)
        for _ in range(others - len(buckets)):
            k = max(range(len(buckets)), key=lambda j: weights[j] / counts[j])
            counts[k] += 1
        ids = []
        for (cls, amount, examples), n in zip(buckets, counts, strict=True):
            names = examples or [class_name(cls)]
            for k in range(n):
                ids.append(self.company(self.new_id("U"), f"{cls}.{k % 9 + 1}", names[k % len(names)],
                                        max(amount, 0.0) / n or None, region=p.get("region"), city=p.get("city"),
                                        group_id=p.get("group_id")))
        return ids

    def peers(self, clients: list[dict]) -> None:
        """Компании того же класса ОКВЭД (не больше MAX_PEERS на класс): место клиента по выручке - как в выборке.
        Клиенты одного класса обрабатываются вместе, от крупного к мелкому; доля в классе - приблизительно."""
        by_class: dict[str, list[dict]] = {}
        for p in clients:
            if p.get("industry_position") and p.get("revenue"):
                by_class.setdefault(p["industry_position"]["okved2"], []).append(p)
        for cls, group in by_class.items():
            group.sort(key=lambda p: p["revenue"], reverse=True)
            budget = max(0, min(max(p["industry_position"]["peers"] for p in group), MAX_PEERS)
                         - sum(1 for c in self.companies.values() if c["MAINOKVED_CODE"].split(".")[0] == cls))
            code, name = group[0].get("okved_code") or f"{cls}.1", group[0].get("okved_name") or class_name(cls)
            for i, p in enumerate(group):  # выше клиента должно быть rank-1 компаний
                ceiling = group[i - 1]["revenue"] if i else p["revenue"] * 3
                above = sum(1 for c in self.companies.values() if c["MAINOKVED_CODE"].split(".")[0] == cls
                            and float(c["REVENUE_COMPANY"] or 0) > p["revenue"])
                for _ in range(min(budget, max(0, (p["industry_position"].get("revenue_rank") or 1) - 1 - above))):
                    self.company(self.new_id("U"), code, name, self.rnd.uniform(p["revenue"] * 1.02, ceiling * 0.98),
                                 persons=False)
                    budget -= 1
            # остальные - ниже самого мелкого клиента класса: доля клиентов в классе по выручке примерно как в выборке
            smallest = group[-1]
            ip = smallest["industry_position"]
            class_total = smallest["revenue"] / ip["revenue_share"] if ip.get("revenue_share") else smallest["revenue"] * 20
            have = sum(float(c["REVENUE_COMPANY"] or 0) for c in self.companies.values()
                       if c["MAINOKVED_CODE"].split(".")[0] == cls)
            weights = [self.rnd.lognormvariate(0, 1.6) for _ in range(budget)]
            left = max(class_total - have, 0.0)
            for w in weights:
                self.company(self.new_id("U"), code, name, min(smallest["revenue"] * 0.95, left * w / sum(weights)),
                             persons=False)

    def side(self, cid: str, p: dict, g: dict, side: str, siblings: list[str]) -> None:
        """Платежи одного направления: топ контрагентов из профиля, отраслевые доли, неизвестные и внутригрупповые."""
        turnover = g.get(f"{side}_turnover") or 0.0
        if turnover <= 0:
            return
        top = g.get(f"top_{side}s") or []
        out = side == "supplier"  # поставщикам платит клиент

        def flow(other: str, amount: float, count: int | None = None) -> None:
            self.pay(cid, other, amount, count) if out else self.pay(other, cid, amount, count)

        cap = 0.9 * min((t["amount"] for t in top), default=turnover)
        done_cls: dict[str, float] = {}
        unknown_top = 0.0
        for t in top:
            if t.get("okved_code"):
                self.company(t["client_id"], t["okved_code"], t.get("okved_name"), t["amount"] * self.rnd.uniform(3, 20),
                             region=t.get("region"))
                done_cls[t["okved_code"].split(".")[0]] = done_cls.get(t["okved_code"].split(".")[0], 0.0) + t["amount"]
            else:
                unknown_top += t["amount"]
            flow(t["client_id"], t["amount"], t.get("payments"))
        industries = g.get(f"{side}_industries") or []
        listed = {i["okved2"] for i in industries}
        made = len(top)
        for ind in industries:
            left = ind["share"] * turnover - done_cls.get(ind["okved2"], 0.0)
            names = ind.get("examples") or [class_name(ind["okved2"], "Деятельность прочая")]
            for k, amount in enumerate(self.split(left, cap)):
                other = self.company(self.new_id("U"), f"{ind['okved2']}.{k % 9 + 1}", names[k % len(names)],
                                     amount * self.rnd.uniform(3, 20))
                flow(other, amount)
                made += 1
        # остальные отрасли: каждая мельче последней в списке, чтобы не войти в топ-5 отраслей клиента
        unknown_share = g.get(f"{side}_unknown_share") or 0.0
        rest = turnover * max(0.0, 1 - unknown_share - sum(i["share"] for i in industries))
        per_class = 0.7 * min((i["share"] * turnover for i in industries), default=cap)
        for cls in (c for c in FILLER_CLASSES if c not in listed):
            if rest <= 0:
                break
            amount_cls = min(rest, per_class)
            for amount in self.split(amount_cls, cap):
                other = self.company(self.new_id("U"), f"{cls}.1", class_name(cls), amount * self.rnd.uniform(3, 20))
                flow(other, amount)
                made += 1
            rest -= amount_cls
        # контрагенты вне выборки (и то, что не уместилось в мелкие отрасли): общее число - как в профиле
        count = g.get(f"{side}s_count") or made
        left = unknown_share * turnover - unknown_top + max(rest, 0.0)
        for amount in self.split(left, cap, min_parts=max(1, count - made)):
            flow(self.new_id("X"), amount)
        intra = g.get(f"{side}_intragroup_share") or 0.0
        if intra and siblings and intra < 1:
            for k, amount in enumerate(self.split(intra / (1 - intra) * turnover, turnover, min_parts=min(3, len(siblings)))):
                flow(siblings[k % len(siblings)], amount)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    lines = [CSV_SEP.join(columns)]
    lines += [CSV_SEP.join(str(r.get(c, "")).replace(CSV_SEP, ",") for c in columns) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def synthetic_news(fixture: Path, out: Path) -> int:
    """Демо-новости с готовой разметкой (eval/fixtures/news_synthetic.jsonl): лента работает без RSS и LLM."""
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    keep = ("news_id", "source", "title", "body", "ml_meta")
    out.write_text("".join(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    return len(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, default=root / "eval" / "fixtures" / "demo_profiles.json")
    parser.add_argument("--news", type=Path, default=root / "eval" / "fixtures" / "news_synthetic.jsonl")
    parser.add_argument("--out", type=Path, default=root / "data" / "synthetic")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    gen = Generator(args.seed)
    profiles = list(json.loads(args.profiles.read_text(encoding="utf-8")).values())
    for profile in profiles:
        gen.client(profile)
    gen.peers(profiles)  # последними: в классе уже есть участники групп и контрагенты
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "df_Uid_data_hack.csv", COMPANY_COLUMNS, list(gen.companies.values()))
    write_csv(args.out / "df_Fid_Uid_link_hack.csv", ["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"], gen.persons)
    write_csv(args.out / "df_Uid_payment_hack.csv", ["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"], gen.payments)
    news = synthetic_news(args.news, args.out / "news.jsonl")
    print(f"companies {len(gen.companies)}, persons {len(gen.persons)}, payments {len(gen.payments)}, news {news} -> {args.out}")


if __name__ == "__main__":
    main()
