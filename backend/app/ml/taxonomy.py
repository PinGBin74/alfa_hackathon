"""Таксономия факторов и чувствительность клиента к ним.

Единый словарь, через который новости, аналитика банка и профиль клиента сопоставляются друг с другом:
- классификатор помечает новость факторами (`FACTORS`);
- позиции банка из аналитики помечены теми же факторами;
- `exposures(profile)` объясняет, почему клиент чувствителен к фактору, через конкретные признаки.

Правила детерминированные и объяснимые: каждое срабатывание даёт причину с именем признака,
которую можно показать пользователю и проверить в трассе (критерии 01, 12). Новая отрасль или фактор -
это новая запись здесь, без переобучения (критерий 07).
"""
from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.client import ClientProfile

# Классы ОКВЭД2 (первые две цифры), которые встречаются в выборке и в новостях.
OKVED2_CLASSES: dict[str, str] = {
    "01": "Сельское хозяйство", "02": "Лесоводство и лесозаготовки", "03": "Рыболовство",
    "05": "Добыча угля", "06": "Добыча нефти и газа", "07": "Добыча металлических руд",
    "08": "Добыча прочих полезных ископаемых", "09": "Услуги в области добычи",
    "10": "Пищевая промышленность", "11": "Производство напитков", "13": "Текстиль",
    "16": "Обработка древесины", "17": "Бумага и картон", "19": "Кокс и нефтепродукты",
    "20": "Химическая промышленность", "21": "Фармацевтика", "22": "Резина и пластмассы",
    "23": "Стройматериалы (неметаллическая минеральная продукция)", "24": "Металлургия",
    "25": "Металлические изделия", "26": "Электроника", "27": "Электрооборудование",
    "28": "Машиностроение", "29": "Автомобилестроение", "30": "Прочие транспортные средства",
    "33": "Ремонт и монтаж оборудования", "35": "Электроэнергетика, газ, пар",
    "36": "Водоснабжение", "38": "Отходы", "41": "Строительство зданий",
    "42": "Строительство инженерных сооружений", "43": "Специализированные строительные работы",
    "45": "Торговля и ремонт автотранспорта", "46": "Оптовая торговля", "47": "Розничная торговля",
    "49": "Сухопутный и трубопроводный транспорт", "50": "Водный транспорт", "51": "Воздушный транспорт",
    "52": "Складское хозяйство и транспортные услуги", "53": "Почта и курьеры", "55": "Гостиницы",
    "56": "Общественное питание", "58": "Издательская деятельность", "61": "Связь",
    "62": "Разработка ПО", "63": "Информационные технологии", "64": "Финансовые услуги",
    "65": "Страхование", "66": "Вспомогательные финансовые услуги", "68": "Недвижимость",
    "69": "Право и бухгалтерский учёт", "70": "Управленческий консалтинг",
    "71": "Архитектура и инжиниринг", "72": "НИОКР", "73": "Реклама", "77": "Аренда и лизинг",
    "78": "Подбор персонала", "80": "Безопасность", "81": "Обслуживание зданий",
    "82": "Административные услуги", "85": "Образование", "86": "Здравоохранение",
    "93": "Спорт и развлечения",
}


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    keywords: tuple[str, ...]          # для поиска по аналитике банка и подсказки классификатору
    sectors: tuple[str, ...] = ()      # классы/коды ОКВЭД, на которые фактор влияет напрямую


FACTORS: dict[str, Factor] = {f.code: f for f in [
    Factor("key_rate", "Ключевая ставка и стоимость кредита",
           ("ключевая ставка", "ставка ЦБ", "денежно-кредитная политика", "кредит", "процентные ставки")),
    Factor("inflation", "Инфляция и цены",
           ("инфляция", "цены", "ИПЦ", "инфляционные ожидания")),
    Factor("fx", "Курс рубля и валют",
           ("курс рубля", "доллар", "евро", "юань", "валюта", "девальвация", "укрепление рубля")),
    Factor("bonds", "Долговой рынок и доходности",
           ("облигации", "ОФЗ", "доходность", "размещение", "долговой рынок", "купон")),
    Factor("oil_gas", "Нефть, газ и топливо",
           ("нефть", "Brent", "Urals", "газ", "топливо", "бензин", "дизель"), ("06", "09", "19", "46.71")),
    Factor("metals", "Металлы и сталь",
           ("сталь", "металлы", "металлургия", "прокат", "медь", "алюминий", "никель"),
           ("07", "24", "25", "46.72")),
    Factor("gold", "Золото и драгметаллы",
           ("золото", "драгметаллы", "серебро", "платина"), ("24.41", "32.12", "46.48", "47.77")),
    Factor("agri", "Зерно и агросырьё",
           ("зерно", "пшеница", "урожай", "агро", "экспортная пошлина на зерно", "сахар", "масло"),
           ("01", "10", "46.2")),
    Factor("consumption", "Потребительский спрос",
           ("потребление", "розничные продажи", "спрос", "потребительский кредит", "доходы населения"),
           ("47", "56", "55", "46.3", "45")),
    Factor("labor", "Рынок труда и зарплаты",
           ("рынок труда", "безработица", "зарплаты", "дефицит кадров", "занятость")),
    Factor("gdp_growth", "Экономический рост и деловая активность",
           ("ВВП", "экономический рост", "деловая активность", "промышленное производство", "рецессия")),
    Factor("taxes", "Налоги и сборы",
           ("налог", "НДС", "НДФЛ", "налог на прибыль", "НДПИ", "сборы", "Минфин")),
    Factor("regulation", "Регулирование отрасли",
           ("закон", "регулирование", "постановление", "требования", "лицензия", "запрет")),
    Factor("sanctions_trade", "Санкции, пошлины и внешняя торговля",
           ("санкции", "пошлина", "импорт", "экспорт", "ограничения", "параллельный импорт", "ВЭД")),
    Factor("logistics", "Логистика и транспортные тарифы",
           ("логистика", "перевозки", "РЖД", "тарифы", "фрахт", "порт", "транспорт"), ("49", "50", "51", "52")),
    Factor("real_estate", "Недвижимость, ипотека и стройка",
           ("ипотека", "недвижимость", "жильё", "застройщик", "строительство", "ввод жилья"),
           ("41", "42", "43", "68", "71")),
    Factor("energy", "Электроэнергия и тарифы ЖКХ",
           ("электроэнергия", "тарифы ЖКХ", "энергетика", "тепло"), ("35",)),
    Factor("company_event", "Событие компании или контрагента",
           ("сделка", "банкротство", "отчётность", "слияние", "дефолт", "суд")),
]}

FACTOR_CODES: tuple[str, ...] = tuple(FACTORS)


@dataclass
class Reason:
    feature: str   # признак клиента, например CL_PRODUCT_LOA_MARK или graph.supplier_industries[24]
    text: str      # человекочитаемое объяснение


@dataclass
class Exposure:
    factor: str
    weight: float = 0.0
    reasons: list[Reason] = field(default_factory=list)

    def add(self, weight: float, feature: str, text: str) -> None:
        self.weight = min(1.0, self.weight + weight)
        self.reasons.append(Reason(feature, text))


def okved_matches(code: str | None, prefixes: tuple[str, ...]) -> bool:
    """По сегментам ОКВЭД: '46.71.2' подходит под '46', '46.7' и '46.71', но не под '46.2'."""
    if not code:
        return False
    parts = code.split(".")
    for p in prefixes:
        pp = p.split(".")
        if len(parts) >= len(pp) and parts[: len(pp) - 1] == pp[:-1] and parts[len(pp) - 1].startswith(pp[-1]):
            return True
    return False


def _industry_share(industries, prefixes: tuple[str, ...]) -> float:
    """Отрасли контрагентов известны с точностью до класса (2 цифры): более узкие коды не учитываем,
    иначе «46.71 опт топливом» засчитал бы весь опт."""
    classes = {p for p in prefixes if "." not in p}
    return sum(i.share for i in industries if i.okved2 in classes)


# Торговля (45-47) - широкие классы: важно не «опт вообще», а продукцией какой отрасли торгует компания.
TRADE_PRODUCT_CLASSES: dict[str, tuple[str, ...]] = {
    "45.3": ("29",), "46.2": ("01",), "46.3": ("10", "11"), "46.34": ("11",), "46.38": ("10", "03"),
    "46.4": ("13", "21", "27"), "46.46": ("21",), "46.5": ("26",), "46.6": ("28", "27"), "46.71": ("19", "06"),
    "46.72": ("24", "07"), "46.73": ("16", "23"), "46.75": ("20",), "47.3": ("19",),
}
BROAD_CLASSES = ("45", "46", "47")


def client_industry_classes(okved_code: str | None) -> dict[str, str]:
    """Классы ОКВЭД, к которым компания относится по существу: свой класс + отрасль товара для торговли."""
    if not okved_code:
        return {}
    own = okved_code.split(".")[0]
    out = {own: f"основной вид деятельности {okved_code}"}
    for prefix, classes in sorted(TRADE_PRODUCT_CLASSES.items(), key=lambda kv: -len(kv[0])):
        if okved_matches(okved_code, (prefix,)):
            for c in classes:
                out.setdefault(c, f"торгует продукцией отрасли {c} {OKVED2_CLASSES.get(c, '')} (ОКВЭД {okved_code})")
            break
    return out


CAPEX_HEAVY =("35", "41", "42", "43", "49", "50", "51", "52", "64", "68", "71", "77")
LABOR_HEAVY = ("41", "43", "47", "49", "56", "81")
CYCLICAL = ("07", "16", "20", "23", "24", "25", "28", "29", "41", "42", "43", "46", "49", "52")
WORKERS_WEIGHT = {"Более 251": 0.35, "101-250": 0.2}


def _rule_key_rate(p: ClientProfile, e: Exposure) -> None:
    if p.products.loans:
        e.add(0.45, "CL_PRODUCT_LOA_MARK", "есть кредитные продукты в Альфа-Банке: ставка определяет стоимость обслуживания и рефинансирования")
    if p.products.leasing:
        e.add(0.25, "CL_PRODUCT_LEA_MARK", "есть лизинг: стоимость новых договоров следует за ставкой")
    if p.products.deposits:
        e.add(0.2, "CL_PRODUCT_DEP_MARK", "есть депозиты: доходность размещения свободных средств зависит от ставки")
    if okved_matches(p.okved_code, CAPEX_HEAVY):
        e.add(0.2, "MAINOKVED_CODE", "капиталоёмкая отрасль: инвестпроекты обычно финансируются заёмными средствами")


def _rule_inflation(p: ClientProfile, e: Exposure) -> None:
    if okved_matches(p.okved_code, ("10", "11", "46", "47", "56")):
        e.add(0.3, "MAINOKVED_CODE", "торговля и пищевая отрасль: цены закупки и продажи меняются вместе с инфляцией")
    w = WORKERS_WEIGHT.get(p.workers_fns or "")
    if w:
        e.add(w / 2, "AMOUNT_WORKERS_FNS_GRADATION", f"штат {p.workers_fns}: инфляция давит на индексацию зарплат")


def _rule_fx(p: ClientProfile, e: Exposure) -> None:
    if p.foreign_trade.fts_flag:
        countries = ", ".join(p.foreign_trade.countries) or "страны не указаны"
        e.add(0.5, "FTS_FLAG", f"ведёт внешнеторговую деятельность (ФТС: {countries}): курс меняет рублёвую стоимость контрактов")
    if p.ownership and "ИНОСТРАН" in p.ownership.upper():
        e.add(0.2, "OKFS_NAME", "иностранное участие в капитале: расчёты с акционерами и группой в валюте")


def _rule_bonds(p: ClientProfile, e: Exposure) -> None:
    if okved_matches(p.okved_code, ("64", "66", "77")):
        e.add(0.4, "MAINOKVED_CODE", "финансовая/лизинговая деятельность: фондирование на долговом рынке")
    if p.large_business and (p.products.loans or p.products.leasing):
        e.add(0.25, "REVENUE_COMPANY", "крупный заёмщик: облигации - альтернатива банковскому кредиту, их доходности задают цену долга")
    if p.products.deposits:
        e.add(0.1, "CL_PRODUCT_DEP_MARK", "свободные средства: доходности облигаций - ориентир для размещения")


def _rule_sector(p: ClientProfile, e: Exposure) -> None:
    """Общее правило для сырьевых и отраслевых факторов: своя отрасль, отрасли контрагентов."""
    f = FACTORS[e.factor]
    if not f.sectors:
        return
    if okved_matches(p.okved_code, f.sectors):
        e.add(0.6, "MAINOKVED_CODE", f"основной вид деятельности ({p.okved_code} {p.okved_name or ''}) напрямую связан с фактором «{f.label}»")
    if p.group:
        gs = _industry_share(p.group.top_industries, f.sectors)
        if gs >= 0.2 and not okved_matches(p.okved_code, f.sectors):
            e.add(0.3 * gs, "GROUP_ID", f"в группе компаний {gs:.0%} выручки приходится на связанные с фактором отрасли")
    for side, label in (("supplier", "закупок"), ("buyer", "выручки от покупателей")):
        share = _industry_share(getattr(p.graph, f"{side}_industries"), f.sectors)
        if share >= 0.05:
            e.add(min(0.5, share), f"graph.{side}_industries",
                  f"{share:.0%} {label} по платежам приходится на отрасли, связанные с фактором «{f.label}»")


def _rule_labor(p: ClientProfile, e: Exposure) -> None:
    w = WORKERS_WEIGHT.get(p.workers_fns or "")
    if w:
        e.add(w, "AMOUNT_WORKERS_FNS_GRADATION", f"штат {p.workers_fns}: зарплаты - существенная статья затрат")
    if p.products.payroll:
        e.add(0.15, "CL_PRODUCT_ZPP_MARK", "зарплатный проект в Альфа-Банке")
    if okved_matches(p.okved_code, LABOR_HEAVY):
        e.add(0.15, "MAINOKVED_CODE", "трудоёмкая отрасль: дефицит кадров и рост зарплат бьют по марже")


def _rule_gdp(p: ClientProfile, e: Exposure) -> None:
    e.add(0.1, "base", "общая деловая активность влияет на спрос любой компании")
    if okved_matches(p.okved_code, CYCLICAL):
        e.add(0.25, "MAINOKVED_CODE", "циклическая отрасль: спрос сильно зависит от темпов роста экономики")
    if p.large_business:
        e.add(0.1, "REVENUE_COMPANY", "крупный бизнес с выручкой более 15 млрд руб.")


def _rule_taxes(p: ClientProfile, e: Exposure) -> None:
    e.add(0.2, "base", "налоговые изменения затрагивают любую компанию")
    if p.large_business:
        e.add(0.15, "REVENUE_COMPANY", "крупный налогоплательщик")


def _rule_sanctions(p: ClientProfile, e: Exposure) -> None:
    if p.foreign_trade.fts_flag:
        countries = ", ".join(p.foreign_trade.countries) or "страны не указаны"
        e.add(0.5, "FTS_COUNTRY_NAME", f"внешнеторговые контракты (ФТС: {countries}): пошлины и ограничения меняют логистику и расчёты")
    if p.ownership and "ИНОСТРАН" in p.ownership.upper():
        e.add(0.2, "OKFS_NAME", "иностранное участие в капитале")


def _rule_logistics(p: ClientProfile, e: Exposure) -> None:
    _rule_sector(p, e)
    if p.foreign_trade.fts_flag:
        e.add(0.2, "FTS_FLAG", "внешнеторговые поставки зависят от транспортных тарифов и маршрутов")
    if okved_matches(p.okved_code, ("46",)):
        e.add(0.15, "MAINOKVED_CODE", "оптовая торговля: доставка - заметная часть себестоимости")


def _rule_energy(p: ClientProfile, e: Exposure) -> None:
    _rule_sector(p, e)
    if okved_matches(p.okved_code, ("17", "20", "23", "24")):
        e.add(0.3, "MAINOKVED_CODE", "энергоёмкое производство")


def _rule_regulation(p: ClientProfile, e: Exposure) -> None:
    e.add(0.1, "base", "изменения регулирования оцениваются по отрасли новости")


RULES: dict[str, Callable[[ClientProfile, Exposure], None]] = {
    "key_rate": _rule_key_rate, "inflation": _rule_inflation, "fx": _rule_fx, "bonds": _rule_bonds,
    "oil_gas": _rule_sector, "metals": _rule_sector, "gold": _rule_sector, "agri": _rule_sector,
    "consumption": _rule_sector, "labor": _rule_labor, "gdp_growth": _rule_gdp, "taxes": _rule_taxes,
    "regulation": _rule_regulation, "sanctions_trade": _rule_sanctions, "logistics": _rule_logistics,
    "real_estate": _rule_sector, "energy": _rule_energy, "company_event": lambda p, e: None,
}


def exposures(profile: ClientProfile) -> dict[str, Exposure]:
    """Чувствительность клиента ко всем факторам. Вес 0..1, причины - конкретные признаки."""
    out = {}
    for code in FACTOR_CODES:
        e = Exposure(code)
        RULES[code](profile, e)
        e.weight = round(e.weight, 3)
        out[code] = e
    return out


# Роль пользователя меняет приоритеты: казначею важнее ставка и валюта, главбуху - налоги.
ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "treasurer": {"key_rate": 1.4, "fx": 1.5, "bonds": 1.5, "inflation": 1.1, "gold": 1.1, "consumption": 0.8, "labor": 0.7},
    "cfo": {"key_rate": 1.3, "fx": 1.2, "bonds": 1.2, "taxes": 1.3, "inflation": 1.2},
    "chief_accountant": {"taxes": 1.6, "regulation": 1.4, "labor": 1.1, "key_rate": 0.9},
    "ceo": {"gdp_growth": 1.3, "consumption": 1.2, "regulation": 1.2, "sanctions_trade": 1.2, "company_event": 1.3},
    "owner": {"gdp_growth": 1.3, "consumption": 1.2, "regulation": 1.2, "sanctions_trade": 1.2, "company_event": 1.3},
}


def role_weight(role: str | None, factor: str) -> float:
    return ROLE_WEIGHTS.get(role or "", {}).get(factor, 1.0)


@dataclass(frozen=True)
class ProductHint:
    code: str
    title: str
    rationale: str


def product_hints(profile: ClientProfile, factors: list[str]) -> list[ProductHint]:
    """Кандидаты для нативного предложения продукта банка (модель решает, уместно ли его упоминать)."""
    hints: list[ProductHint] = []
    p, fs = profile, set(factors)
    if fs & {"fx", "sanctions_trade"} and p.foreign_trade.fts_flag:
        hints.append(ProductHint("fx_hedge", "Валютный контроль и хеджирование курса",
                                 "у клиента внешнеторговые контракты, курс и ограничения меняют рублёвую стоимость сделок"))
    if not p.products.factoring and (p.graph.buyer_concentration or 0) >= 0.15:
        hints.append(ProductHint("factoring", "Факторинг",
                                 f"выручка сконцентрирована на крупных покупателях (HHI {p.graph.buyer_concentration:.2f}), факторинга в банке нет"))
    if "key_rate" in fs and not p.products.deposits:
        hints.append(ProductHint("deposit", "Депозит / размещение ликвидности",
                                 "при высокой ставке размещение свободных средств даёт доход, депозитов в банке нет"))
    if "key_rate" in fs and p.products.loans:
        hints.append(ProductHint("refinance", "Пересмотр структуры кредитного портфеля",
                                 "есть кредиты: при изменении ставки стоит оценить фиксированную/плавающую ставку и сроки"))
    if fs & {"real_estate", "regulation"} and okved_matches(p.okved_code, ("41", "42", "43", "71")) and not p.products.guarantees:
        hints.append(ProductHint("guarantee", "Банковские гарантии", "строительная отрасль: гарантии под госконтракты и подряды"))
    return hints
