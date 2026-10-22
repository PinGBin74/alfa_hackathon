from typing import Literal

from pydantic import BaseModel, Field


class Products(BaseModel):
    rko: bool = False
    guarantees: bool = False
    loans: bool = False
    leasing: bool = False
    deposits: bool = False
    payroll: bool = False
    factoring: bool = False


class ForeignTrade(BaseModel):
    fts_flag: bool = False
    countries: list[str] = Field(default_factory=list)


class Counterparty(BaseModel):
    client_id: str
    amount: float
    share: float = Field(description="Доля во внешнем обороте этого направления")
    payments: int | None = None
    okved_code: str | None = Field(None, description="None: контрагента нет в выборке")
    okved_name: str | None = None
    region: str | None = None


class IndustryShare(BaseModel):
    okved2: str = Field(description="Класс ОКВЭД (первые две цифры)")
    share: float
    examples: list[str] = Field(default_factory=list, description="ОКВЭД крупнейших компаний класса")


class GraphFeatures(BaseModel):
    """Поставщики = получатели платежей клиента, покупатели = плательщики клиенту.
    Платежи внутри своей группы компаний в топы, доли и концентрацию не входят."""

    top_suppliers: list[Counterparty] = Field(default_factory=list)
    top_buyers: list[Counterparty] = Field(default_factory=list)
    supplier_concentration: float | None = Field(None, description="HHI по внешним поставщикам")
    buyer_concentration: float | None = Field(None, description="HHI по внешним покупателям")
    supplier_turnover: float = 0.0
    buyer_turnover: float = 0.0
    suppliers_count: int = 0
    buyers_count: int = 0
    supplier_industries: list[IndustryShare] = Field(default_factory=list)
    buyer_industries: list[IndustryShare] = Field(default_factory=list)
    supplier_unknown_share: float | None = Field(None, description="Доля оборота с контрагентами вне выборки")
    buyer_unknown_share: float | None = None
    supplier_intragroup_share: float | None = Field(None, description="Доля платежей внутри своей группы")
    buyer_intragroup_share: float | None = None
    group_size: int | None = None
    regions_of_counterparties: list[str] = Field(default_factory=list)


class GroupInfo(BaseModel):
    group_id: str
    size: int
    total_revenue: float | None = None
    large_business: bool = Field(False, description="Суммарная выручка группы > 15 млрд руб.")
    top_industries: list[IndustryShare] = Field(default_factory=list, description="По выручке участников")


class IndustryPosition(BaseModel):
    """Положение в своём классе ОКВЭД внутри выборки банка (не доля всего рынка)."""

    okved2: str
    peers: int
    revenue_rank: int | None = None
    revenue_share: float | None = None


class ClientProfile(BaseModel):
    client_id: str
    group_id: str | None = None
    okved_code: str | None = None
    okved_name: str | None = None
    org_type: str | None = None
    ownership: str | None = None
    age_gradation: str | None = None
    stage: str | None = None
    workers_fns: str | None = None
    workers_spark: str | None = None
    revenue: float | None = None
    large_business: bool = Field(False, description="Выручка компании > 15 млрд руб. (порог кейса)")
    negative_mark: bool | None = Field(None, description="NEGATIVEMARK: признак ключевого собственника")
    city: str | None = None
    region: str | None = None
    client_type: Literal["existing", "potential", "closed"] | None = None
    cl_type: str | None = Field(None, description="Исходное значение CL_TYPE")
    products: Products = Field(default_factory=Products, description="Продукты в Альфа-Банке, не весь долг компании")
    foreign_trade: ForeignTrade = Field(default_factory=ForeignTrade)
    group: GroupInfo | None = None
    industry_position: IndustryPosition | None = None
    graph: GraphFeatures = Field(default_factory=GraphFeatures)


class ClientSummary(BaseModel):
    client_id: str
    okved_name: str | None = None
    region: str | None = None
    revenue: float | None = None
