"""โหลดและตรวจ config/business.yaml

ทุกความผิดพลาดของ config ต้อง error ที่นี่ที่เดียว (boundary)
โค้ดส่วนอื่นรับ BusinessConfig ที่ผ่านการตรวจแล้ว ไม่ต้องเช็คซ้ำ
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# อัตรา (royalty, GP) เป็น Decimal เพราะต้องคูณกับเงิน และอยู่ในช่วง 0–1
Rate = Annotated[Decimal, Field(ge=0, le=1)]
Money = Annotated[Decimal, Field(ge=0, decimal_places=2)]
Multiplier = Annotated[Decimal, Field(gt=0)]
Hour = Annotated[int, Field(ge=0, le=23)]


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
