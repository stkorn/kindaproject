"""สร้างบิลจำลองของหนึ่งสาขาในหนึ่งวัน (schema ตาม ADR-003, การสุ่มตาม ADR-004)

หนึ่ง (branch_id, date) = หนึ่ง RNG ใช้สุ่มทุกอย่างของวันนั้นตามลำดับ:
เวลาของทุกบิลก่อน แล้วไล่ทีละบิล: ช่องทาง → รายการ → เลข platform → สถานะ
เปลี่ยนลำดับการเรียก RNG = ข้อมูลของวันนั้นเปลี่ยนทั้งวัน (วันอื่นและสาขาอื่นไม่กระทบ)
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from generator.config import (
    Branch,
    BusinessConfig,
    ChannelBehavior,
    MenuItem,
    SimulationConfig,
)
from generator.demand import expected_bills

BANGKOK = ZoneInfo("Asia/Bangkok")


@dataclass(frozen=True)
class Order:
    order_id: str
    branch_id: str
    order_time: datetime
    channel_id: str
    total_price_incl_vat_thb: Decimal
    platform_order_ref: str | None
    status: str


@dataclass(frozen=True)
class OrderItem:
    order_id: str
    line_no: int
    menu_id: str
    quantity: int
    unit_price_incl_vat_thb: Decimal


def day_rng(sim: SimulationConfig, branch_id: str, day: date) -> random.Random:
    # seed เป็น string: Random แปลงด้วย SHA-512 จึงได้ค่าเดิมทุก process
    # ห้ามใช้ hash() เพราะ PYTHONHASHSEED สุ่มใหม่ทุกครั้งที่รัน
    return random.Random(f"{sim.seed}|{branch_id}|{day.isoformat()}")


def arrival_times(
    rng: random.Random, expected: float, hourly_weight: dict[int, Decimal], day: date
) -> list[datetime]:
    """Poisson process ที่อัตราคงที่ภายในแต่ละชั่วโมง

    ระยะห่างระหว่างบิลสุ่มจาก exponential → จำนวนบิลทั้งวัน ~ Poisson(expected)
    และกระจายตาม hourly_weight ในขั้นเดียว · ผลลัพธ์เรียงตามเวลาเสมอ
    """
    total_weight = sum(hourly_weight.values())
    times: list[datetime] = []
    for hour, weight in sorted(hourly_weight.items()):
        rate = expected * float(weight / total_weight)  # บิลต่อชั่วโมง
        start = datetime.combine(day, time(hour), tzinfo=BANGKOK)
        # exponential ไม่มีความจำ: เริ่มนับใหม่ทุกชั่วโมงได้โดยไม่ผิดการแจกแจง
        t = rng.expovariate(rate)  # หน่วยเป็นชั่วโมง
        while t < 1:
            times.append(start + timedelta(seconds=int(t * 3600)))
            t += rng.expovariate(rate)
    return times


def draw_items(
    rng: random.Random, sim: SimulationConfig, menu: list[MenuItem], order_id: str
) -> list[OrderItem]:
    lines = sim.basket.lines
    n_lines = rng.choices(list(lines), weights=list(lines.values()))[0]
    remaining = list(menu)
    weights = [sim.menu_weight[m.menu_id] for m in remaining]
    quantity = sim.basket.quantity
    items = []
    for line_no in range(1, n_lines + 1):
        # สุ่มแบบไม่ซ้ำ: เมนูเดียวกันอยู่บรรทัดเดียว เพิ่มที่ quantity แทน
        # pop ตาม index ไม่ใช้ list.remove เพราะ __eq__ ของ pydantic เทียบทุก field (ช้า)
        idx = rng.choices(range(len(remaining)), weights=weights)[0]
        item = remaining.pop(idx)
        weights.pop(idx)
        items.append(
            OrderItem(
                order_id=order_id,
                line_no=line_no,
                menu_id=item.menu_id,
                quantity=rng.choices(list(quantity), weights=list(quantity.values()))[
                    0
                ],
                unit_price_incl_vat_thb=item.price_incl_vat,  # snapshot ราคา ณ วันขาย
            )
        )
    return items


def draw_platform_ref(rng: random.Random, behavior: ChannelBehavior) -> str | None:
    if behavior.ref_prefix is None:
        return None
    # 64 บิต: ทั้งปี ~10^5 บิลต่อช่องทาง โอกาสชนกัน ≈ n²/2^65 ≈ 10^-9 (birthday paradox)
    return f"{behavior.ref_prefix}-{rng.getrandbits(64):016X}"


def draw_status(rng: random.Random, behavior: ChannelBehavior) -> str:
    r = rng.random()
    if r < behavior.cancel_by_customer:
        return "cancelled_by_customer"
    if r < behavior.cancel_by_customer + behavior.cancel_by_branch:
        return "cancelled_by_branch"
    return "completed"


def generate_day(
    cfg: BusinessConfig, sim: SimulationConfig, branch: Branch, day: date
) -> tuple[list[Order], list[OrderItem]]:
    expected = expected_bills(cfg, branch, day)
    if expected is None:  # ร้านปิด
        return [], []

    rng = day_rng(sim, branch.branch_id, day)
    times = arrival_times(rng, float(expected), cfg.seasonality.hourly_weight, day)
    # สาขาที่ไม่มีบางช่องทาง: choices เฉลี่ยสัดส่วนใหม่จากช่องทางที่มีให้เอง
    channel_weights = [sim.channels[c].weight for c in branch.channels]

    orders: list[Order] = []
    items: list[OrderItem] = []
    for seq, order_time in enumerate(times, start=1):
        # deterministic และไม่ชนกันเพราะได้จากการนับ ไม่ใช่การสุ่ม
        order_id = f"{branch.branch_id}-{day:%Y%m%d}-{seq:04d}"
        channel_id = rng.choices(branch.channels, weights=channel_weights)[0]
        behavior = sim.channels[channel_id]
        lines = draw_items(rng, sim, cfg.menu, order_id)
        orders.append(
            Order(
                order_id=order_id,
                branch_id=branch.branch_id,
                order_time=order_time,
                channel_id=channel_id,
                # ยอดเต็มเสมอ แม้บิลถูกยกเลิก (ADR-003)
                total_price_incl_vat_thb=sum(
                    (i.quantity * i.unit_price_incl_vat_thb for i in lines),
                    Decimal("0.00"),
                ),
                platform_order_ref=draw_platform_ref(rng, behavior),
                status=draw_status(rng, behavior),
            )
        )
        items.extend(lines)
    return orders, items
