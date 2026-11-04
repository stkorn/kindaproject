"""Acceptance test ของจำนวนบิลที่คาดหวังต่อวัน

ตัวเลขคาดหวังคำนวณด้วยมือจาก config/business.yaml ก่อนเขียนโค้ด (ไม่ได้ copy ผลจากโค้ด)
ถ้าแก้ตัวคูณหรือ normal_daily_bills ใน config ต้องคำนวณตารางนี้ใหม่
"""

from datetime import date
from decimal import Decimal

import pytest

from generator.config import load_config
from generator.demand import expected_bills

CFG = load_config("config/business.yaml")
BRANCHES = {b.branch_id: b for b in CFG.branches}


@pytest.mark.parametrize(
    ("day", "branch_id", "expected"),
    [
        # จ. สงกรานต์: 1.00 × public_holiday 1.20 × term_break 0.80 × songkran_cnx 1.20 = 1.152
        ("2026-04-13", "CNX01", "322.56"),
        # จ. สงกรานต์ BKK: 1.20 × 0.80 × songkran_bkk 0.40 = 0.384
        ("2026-04-13", "BKK02", "115.2"),
        # ส. ปิดเทอม: sat 1.20 × term_break 0.80
        ("2026-04-18", "BKK01", "230.4"),
        # ส. วาเลนไทน์: sat 1.20 × valentine 1.30
        ("2026-02-14", "BKK01", "374.4"),
        # อ. ตรุษจีน (dated, ไม่ใช่วันหยุดราชการ): 1.10
        ("2026-02-17", "CNX01", "308"),
        # จ. ชดเชยมาฆบูชา (holidays lib คำนวณให้): public_holiday 1.20
        ("2027-02-22", "CNX01", "336"),
        # พ. วันธรรมดา ไม่มีตัวคูณ = normal_daily_bills พอดี
        ("2026-11-04", "CPN01", "160"),
    ],
)
def test_expected_bills(day, branch_id, expected):
    assert expected_bills(CFG, BRANCHES[branch_id], date.fromisoformat(day)) == Decimal(
        expected
    )


@pytest.mark.parametrize(
    ("day", "branch_id"),
    [
        ("2026-04-13", "CNX02"),  # ปิดสงกรานต์ (closed.dates annual)
        ("2026-04-13", "CPN01"),  # ปิดสงกรานต์
        ("2026-04-18", "CNX02"),  # ปิดทุกวันเสาร์ (closed.weekdays)
        ("2026-11-02", "CPN01"),  # ปิดทุกวันจันทร์
    ],
)
def test_closed_day_has_no_bills(day, branch_id):
    # ADR-002: วันปิด = None ไม่ใช่ 0 · ชนะตัวคูณทุกตัว
    assert expected_bills(CFG, BRANCHES[branch_id], date.fromisoformat(day)) is None


def test_city_scope_does_not_leak():
    # songkran_cnx ต้องไม่กระทบ BKK และ songkran_bkk ต้องไม่กระทบ CNX
    day = date(2026, 4, 13)
    cnx = (
        expected_bills(CFG, BRANCHES["CNX01"], day)
        / BRANCHES["CNX01"].normal_daily_bills
    )
    bkk = (
        expected_bills(CFG, BRANCHES["BKK01"], day)
        / BRANCHES["BKK01"].normal_daily_bills
    )
    assert cnx == Decimal("1.152")
    assert bkk == Decimal("0.384")


def test_result_is_decimal():
    # ADR-003: ห้าม float ใน path ของตัวเลข
    result = expected_bills(CFG, BRANCHES["CNX01"], date(2026, 11, 4))
    assert isinstance(result, Decimal)
