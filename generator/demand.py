"""จำนวนบิลที่คาดหวังต่อสาขาต่อวัน (ADR-002)

deterministic ล้วน ไม่มีการสุ่ม: ขั้นสุ่มจำนวนบิลจริงใช้ค่านี้เป็นค่าเฉลี่ย
ชื่อไฟล์ไม่ใช้ calendar.py เพื่อไม่ชนกับ stdlib calendar
"""

from datetime import date
from decimal import Decimal

import holidays

from generator.config import (
    WEEKDAYS,
    Annual,
    Branch,
    BusinessConfig,
    Dated,
    PublicHoliday,
)

# holidays คำนวณปีที่ถูกถามแบบ lazy จึงสร้างครั้งเดียวใช้ได้ทุกปี
TH_HOLIDAYS = holidays.Thailand()


def matches(spec: PublicHoliday | Annual | Dated, day: date) -> bool:
    match spec:
        case PublicHoliday():
            return day in TH_HOLIDAYS
        case Annual(start=start, end=end):
            # "MM-DD" เทียบแบบ string ได้เพราะเติม 0 นำหน้าเสมอ · ไม่รองรับช่วงข้ามปี (เช่น 12-30 → 01-02)
            return start <= day.strftime("%m-%d") <= end
        case Dated(start=start, end=end):
            return start <= day <= end


def is_closed(branch: Branch, day: date) -> bool:
    if branch.closed is None:
        return False
    if WEEKDAYS[day.weekday()] in branch.closed.weekdays:
        return True
    return any(matches(spec, day) for spec in branch.closed.dates)


def expected_bills(cfg: BusinessConfig, branch: Branch, day: date) -> Decimal | None:
    """None = ร้านปิด (ชนะตัวคูณทุกตัว) · ไม่งั้น = normal_daily_bills × day_of_week × ทุก date_range ที่ตรง"""
    if is_closed(branch, day):
        return None

    result = (
        branch.normal_daily_bills * cfg.seasonality.day_of_week[WEEKDAYS[day.weekday()]]
    )
    for r in cfg.seasonality.date_range:
        in_scope = r.cities is None or branch.city_id in r.cities
        if in_scope and matches(r, day):
            result *= r.multiplier
    return result
