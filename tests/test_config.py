"""Test ของ generator.config: config จริงต้องโหลดผ่าน และ config ที่ผิดต้อง error พร้อมบอกจุดที่ผิด"""

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from generator.config import load_config

REAL_CONFIG = Path(__file__).parent.parent / "config" / "business.yaml"


@pytest.fixture
def raw() -> dict:
    # config จริงแบบ dict ที่แก้ได้ แต่ละ test ทำให้ผิดทีละจุด
    with open(REAL_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_from(raw: dict, tmp_path: Path):
    # เขียนลงไฟล์จริงแล้วโหลดผ่าน load_config เพื่อทดสอบเส้นทางเดียวกับที่ generator ใช้
    path = tmp_path / "business.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return load_config(path)


def branch(raw: dict, branch_id: str) -> dict:
    return next(b for b in raw["branches"] if b["branch_id"] == branch_id)


# ---------- config จริง ----------


def test_real_config_loads():
    cfg = load_config(REAL_CONFIG)
    assert len(cfg.branches) == 5
    assert len(cfg.cities) == 3
    assert len(cfg.menu) == 10


def test_branch_without_closed_is_none():
    cfg = load_config(REAL_CONFIG)
    by_id = {b.branch_id: b for b in cfg.branches}
    assert by_id["CNX01"].closed is None
    assert by_id["CNX02"].closed is not None


def test_money_is_exact_decimal():
    # ADR-003: เงินต้องเป็น Decimal ที่ตรงทุกสตางค์ ไม่ใช่ float
    cfg = load_config(REAL_CONFIG)
    b001 = next(m for m in cfg.menu if m.menu_id == "B001")
    assert isinstance(b001.price_incl_vat, Decimal)
    assert b001.price_incl_vat == Decimal("27.00")


def test_rates_multiply_with_money():
    # royalty = ยอดขาย (Decimal) × royalty_rate ต้องคูณกันได้โดยไม่ TypeError
    cfg = load_config(REAL_CONFIG)
    f001 = next(f for f in cfg.franchisees if f.franchisee_id == "F001")
    assert Decimal("1000.00") * f001.royalty_rate == Decimal("50.00")


def test_real_normal_daily_bills_in_range():
    # CLAUDE.md: ~150–300 บิล/สาขา/วัน · test ของข้อมูล ไม่ใช่ของโค้ด
    cfg = load_config(REAL_CONFIG)
    assert all(150 <= b.normal_daily_bills <= 300 for b in cfg.branches)


@pytest.mark.parametrize("bad", [0, -10, 200.5])
def test_normal_daily_bills_must_be_positive_int(raw, tmp_path, bad):
    branch(raw, "CNX01")["normal_daily_bills"] = bad
    with pytest.raises(ValidationError) as exc:
        load_from(raw, tmp_path)
    assert error_locs(exc) == [("branches", 0, "normal_daily_bills")]


# ---------- FK: อ้างถึง id ที่ไม่มีอยู่ ----------


def test_unknown_city_id_in_branch(raw, tmp_path):
    branch(raw, "CNX01")["city_id"] = "KKN"
    with pytest.raises(ValidationError, match="branch CNX01: unknown city_id 'KKN'"):
        load_from(raw, tmp_path)


def test_unknown_franchisee_id_in_branch(raw, tmp_path):
    branch(raw, "BKK01")["franchisee_id"] = "F999"
    with pytest.raises(
        ValidationError, match="branch BKK01: unknown franchisee_id 'F999'"
    ):
        load_from(raw, tmp_path)


def test_unknown_channel_in_branch(raw, tmp_path):
    branch(raw, "CPN01")["channels"] = ["walk_in", "foodpanda"]
    with pytest.raises(
        ValidationError, match="branch CPN01: unknown channel_id 'foodpanda'"
    ):
        load_from(raw, tmp_path)


def test_unknown_city_in_date_range(raw, tmp_path):
    songkran = next(
        r for r in raw["seasonality"]["date_range"] if r["range_name"] == "songkran_bkk"
    )
    songkran["cities"] = ["KKN"]
    with pytest.raises(ValidationError, match="songkran_bkk: unknown city_id 'KKN'"):
        load_from(raw, tmp_path)


# ---------- id ซ้ำ ----------


def test_duplicate_branch_id(raw, tmp_path):
    raw["branches"].append(copy.deepcopy(branch(raw, "BKK01")))
    with pytest.raises(ValidationError, match="duplicate branch_id 'BKK01'"):
        load_from(raw, tmp_path)


# ---------- รูปร่างของข้อมูล ----------


def test_typo_key_is_rejected(raw, tmp_path):
    # extra="forbid": พิมพ์ key ผิดต้อง error ไม่ใช่ถูกทิ้งเงียบๆ
    raw["seasonality"]["date_range"][1]["multipler"] = raw["seasonality"]["date_range"][
        1
    ].pop("multiplier")
    with pytest.raises(ValidationError, match="multipler"):
        load_from(raw, tmp_path)


def error_locs(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple]:
    # ตำแหน่งของทุก error เช่น ("channels", 1, "settlement", ...) ใช้ยืนยันว่า error มาจากจุดที่เราทำให้ผิดจริง
    return [e["loc"] for e in exc.value.errors()]


def test_settlement_shape_follows_type(raw, tmp_path):
    # type: weekly ต้องมี weekday ไม่ใช่ days
    raw["channels"][1]["settlement"] = {"type": "weekly", "days": 1}
    with pytest.raises(ValidationError) as exc:
        load_from(raw, tmp_path)
    assert all(loc[:3] == ("channels", 1, "settlement") for loc in error_locs(exc))


def test_unknown_date_range_type(raw, tmp_path):
    raw["seasonality"]["date_range"][1]["type"] = "lunar"
    with pytest.raises(ValidationError) as exc:
        load_from(raw, tmp_path)
    assert all(loc[:3] == ("seasonality", "date_range", 1) for loc in error_locs(exc))


def test_annual_date_must_be_month_day(raw, tmp_path):
    # ADR-002: annual ใช้ "MM-DD" · "4-13" หรือ "02-30" ต้อง error
    raw["seasonality"]["date_range"][1]["start"] = "02-30"
    with pytest.raises(
        ValidationError, match="annual date must be 'MM-DD', got '02-30'"
    ):
        load_from(raw, tmp_path)


def test_day_of_week_must_cover_all_days(raw, tmp_path):
    del raw["seasonality"]["day_of_week"]["sun"]
    with pytest.raises(ValidationError, match="day_of_week missing \\['sun'\\]"):
        load_from(raw, tmp_path)
