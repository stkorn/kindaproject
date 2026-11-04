"""โหลดและตรวจ config/business.yaml และ config/simulation.yaml

ทุกความผิดพลาดของ config ต้อง error ที่นี่ที่เดียว (boundary)
โค้ดส่วนอื่นรับ BusinessConfig ที่ผ่านการตรวจแล้ว ไม่ต้องเช็คซ้ำ
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# อัตรา (royalty, GP) เป็น Decimal เพราะต้องคูณกับเงิน และอยู่ในช่วง 0–1
Rate = Annotated[Decimal, Field(ge=0, le=1)]
# YAML อ่าน 27.00 เป็น float 27.0 → quantize ให้มี 2 ตำแหน่งเสมอ (str = "27.00")
Money = Annotated[
    Decimal,
    Field(ge=0, decimal_places=2),
    AfterValidator(lambda v: v.quantize(Decimal("0.01"))),
]
Multiplier = Annotated[Decimal, Field(gt=0)]
Hour = Annotated[int, Field(ge=0, le=23)]
# weight และความน่าจะเป็นของการจำลองเป็น float ได้ เพราะไม่ใช่เงิน และ random.choices รับ float
Weight = Annotated[float, Field(gt=0)]
Probability = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    # forbid: key ที่ไม่รู้จัก (พิมพ์ผิด) = error แทนที่จะถูกทิ้งเงียบๆ
    # frozen: config อ่านอย่างเดียว ห้ามโค้ดส่วนอื่นแก้ค่าระหว่างรัน
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- วันที่ (ADR-002) ใช้ร่วมกันระหว่าง closed.dates และ date_range ----------


class PublicHoliday(StrictModel):
    type: Literal["public_holiday"]


class Annual(StrictModel):
    type: Literal["annual"]
    start: str  # "MM-DD"
    end: str

    @field_validator("start", "end")
    @classmethod
    def check_month_day(cls, v: str) -> str:
        # ใช้ปีอธิกสุรทิน (2024) เพื่อให้ "02-29" ผ่าน · fromisoformat ตรวจทั้งรูปแบบและวันที่มีจริง
        try:
            date.fromisoformat(f"2024-{v}")
        except ValueError:
            raise ValueError(f"annual date must be 'MM-DD', got {v!r}") from None
        return v


class Dated(StrictModel):
    type: Literal["dated"]
    start: date  # "YYYY-MM-DD"
    end: date

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.start > self.end:
            raise ValueError(f"dated range start {self.start} is after end {self.end}")
        return self


DateSpec = Annotated[PublicHoliday | Annual | Dated, Field(discriminator="type")]


# ---------- entity ----------


class Franchisee(StrictModel):
    franchisee_id: str
    franchisee_name: str
    royalty_rate: Rate


class City(StrictModel):
    city_id: str
    city_name: str
    region: Literal["north", "northeast", "central", "south"]


class Closed(StrictModel):
    weekdays: list[Weekday] = []
    dates: list[DateSpec] = []


class Branch(StrictModel):
    branch_id: str
    branch_name: str
    city_id: str
    franchisee_id: str
    channels: list[str]
    normal_daily_bills: Annotated[int, Field(gt=0)]  # วันปกติ ก่อนคูณตัวคูณใดๆ
    closed: Closed | None = None  # ไม่ใส่ = เปิดทุกวัน


class DaysAfter(StrictModel):
    type: Literal["days_after"]
    days: Annotated[int, Field(ge=0)]


class Weekly(StrictModel):
    type: Literal["weekly"]
    weekday: Weekday


class Channel(StrictModel):
    channel_id: str
    channel_name: str
    gp_rate: Rate
    settlement: Annotated[DaysAfter | Weekly, Field(discriminator="type")]


class MenuItem(StrictModel):
    menu_id: str
    menu_name: str
    price_incl_vat: Money
    cost: Money


# date_range = DateSpec + ชื่อ ตัวคูณ และขอบเขตเมือง


class DateRangeFields(StrictModel):
    range_name: str
    multiplier: Multiplier
    cities: list[str] | None = None  # ไม่ใส่ = ทุกสาขา


class PublicHolidayRange(PublicHoliday, DateRangeFields):
    pass


class AnnualRange(Annual, DateRangeFields):
    pass


class DatedRange(Dated, DateRangeFields):
    pass


DateRange = Annotated[
    PublicHolidayRange | AnnualRange | DatedRange, Field(discriminator="type")
]


class Seasonality(StrictModel):
    day_of_week: dict[Weekday, Multiplier]
    date_range: list[DateRange]
    hourly_weight: dict[Hour, Multiplier]  # ชั่วโมงที่ไม่มีใน dict = ร้านปิด

    @field_validator("day_of_week")
    @classmethod
    def check_all_weekdays(cls, v: dict[Weekday, Decimal]) -> dict[Weekday, Decimal]:
        missing = [d for d in WEEKDAYS if d not in v]
        if missing:
            raise ValueError(f"day_of_week missing {missing}")
        return v


# ---------- ราก: ตรวจ id ซ้ำ และ FK ข้าม entity ----------


def check_unique(id_name: str, ids: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {id_name} {i!r}")
        seen.add(i)
    return seen


class BusinessConfig(StrictModel):
    franchisees: list[Franchisee]
    cities: list[City]
    branches: list[Branch]
    channels: list[Channel]
    menu: list[MenuItem]
    seasonality: Seasonality

    @model_validator(mode="after")
    def check_references(self) -> Self:
        franchisee_ids = check_unique(
            "franchisee_id", (f.franchisee_id for f in self.franchisees)
        )
        city_ids = check_unique("city_id", (c.city_id for c in self.cities))
        channel_ids = check_unique("channel_id", (c.channel_id for c in self.channels))
        check_unique("branch_id", (b.branch_id for b in self.branches))
        check_unique("menu_id", (m.menu_id for m in self.menu))
        check_unique("range_name", (r.range_name for r in self.seasonality.date_range))

        for b in self.branches:
            if b.city_id not in city_ids:
                raise ValueError(
                    f"branch {b.branch_id}: unknown city_id {b.city_id!r} "
                    f"(known: {sorted(city_ids)})"
                )
            if b.franchisee_id not in franchisee_ids:
                raise ValueError(
                    f"branch {b.branch_id}: unknown franchisee_id {b.franchisee_id!r} "
                    f"(known: {sorted(franchisee_ids)})"
                )
            for ch in b.channels:
                if ch not in channel_ids:
                    raise ValueError(
                        f"branch {b.branch_id}: unknown channel_id {ch!r} "
                        f"(known: {sorted(channel_ids)})"
                    )

        for r in self.seasonality.date_range:
            for c in r.cities or []:
                if c not in city_ids:
                    raise ValueError(
                        f"date_range {r.range_name}: unknown city_id {c!r} "
                        f"(known: {sorted(city_ids)})"
                    )
        return self


def load_config(path: Path | str) -> BusinessConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)  # safe_load: ห้ามรันโค้ดจาก YAML
    return BusinessConfig.model_validate(raw)


# ---------- simulation.yaml (ADR-004): พฤติกรรมจำลอง ใช้เฉพาะ generator ----------


class ChannelBehavior(StrictModel):
    weight: Weight
    ref_prefix: str | None  # None = ไม่มีเลข platform (walk_in)
    cancel_by_customer: Probability
    cancel_by_branch: Probability

    @model_validator(mode="after")
    def check_cancel_total(self) -> Self:
        if self.cancel_by_customer + self.cancel_by_branch > 1:
            raise ValueError("cancel_by_customer + cancel_by_branch must be <= 1")
        return self


class Basket(StrictModel):
    lines: dict[PositiveInt, Weight]
    quantity: dict[PositiveInt, Weight]


def check_same_ids(name: str, got: Iterable[str], expected: Iterable[str]) -> None:
    got, expected = set(got), set(expected)
    if missing := sorted(expected - got):
        raise ValueError(f"{name} missing {missing}")
    if unknown := sorted(got - expected):
        raise ValueError(f"{name} has unknown ids {unknown}")


class SimulationConfig(StrictModel):
    seed: int
    channels: dict[str, ChannelBehavior]
    basket: Basket
    menu_weight: dict[str, Weight]

    @model_validator(mode="after")
    def check_against_business(self, info: ValidationInfo) -> Self:
        # FK ข้ามไฟล์: business ส่งมาทาง context ของ model_validate
        business: BusinessConfig = info.context["business"]
        check_same_ids(
            "channels", self.channels, (c.channel_id for c in business.channels)
        )
        check_same_ids(
            "menu_weight", self.menu_weight, (m.menu_id for m in business.menu)
        )
        if max(self.basket.lines) > len(business.menu):
            raise ValueError(
                f"basket.lines up to {max(self.basket.lines)} "
                f"but menu has only {len(business.menu)} items"
            )
        return self


def load_simulation(path: Path | str, business: BusinessConfig) -> SimulationConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SimulationConfig.model_validate(raw, context={"business": business})
