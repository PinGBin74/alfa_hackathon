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


class GraphFeatures(BaseModel):
    top_suppliers: list[dict] = Field(default_factory=list)
    top_buyers: list[dict] = Field(default_factory=list)
    supplier_concentration: float | None = None
    buyer_concentration: float | None = None
    group_size: int | None = None
    regions_of_counterparties: list[str] = Field(default_factory=list)


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
    city: str | None = None
    region: str | None = None
    client_type: Literal["existing", "potential"] | None = None
    products: Products = Field(default_factory=Products)
    foreign_trade: ForeignTrade = Field(default_factory=ForeignTrade)
    graph: GraphFeatures = Field(default_factory=GraphFeatures)


class ClientSummary(BaseModel):
    client_id: str
    okved_name: str | None = None
    region: str | None = None
    revenue: float | None = None
