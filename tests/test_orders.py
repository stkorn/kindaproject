"""Test ของ generator.orders: กฎของ schema (ADR-003), ความ deterministic และสถิติ (ADR-004)"""

import re
from collections import Counter
from datetime import date, timedelta

import pytest

from generator.config import load_config, load_simulation
from generator.demand import expected_bills
from generator.orders import generate_day

CFG = load_config("config/business.yaml")
SIM = load_simulation("config/simulation.yaml", CFG)
BRANCHES = {b.branch_id: b for b in CFG.branches}
STATUSES = {"completed", "cancelled_by_customer", "cancelled_by_branch"}


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


@pytest.fixture(scope="module")
def week():
    # ทุกสาขา 7 วันที่มีทั้งวันปิด (CNX02 เสาร์, CPN01 จันทร์) และเสาร์อาทิตย์
    orders, items = [], []
    for day in days(date(2026, 11, 2), 7):
        for b in CFG.branches:
            o, i = generate_day(CFG, SIM, b, day)
            orders += o
            items += i
    return orders, items


# ---------- deterministic ----------


def test_same_input_same_output():
    day = date(2026, 4, 13)
    assert generate_day(CFG, SIM, BRANCHES["CNX01"], day) == generate_day(
        CFG, SIM, BRANCHES["CNX01"], day
    )


def test_seed_changes_output():
    day = date(2026, 4, 13)
    other = SIM.model_copy(update={"seed": SIM.seed + 1})
    assert generate_day(CFG, SIM, BRANCHES["CNX01"], day) != generate_day(
        CFG, other, BRANCHES["CNX01"], day
    )


def test_closed_day_has_no_orders():
    assert generate_day(CFG, SIM, BRANCHES["CNX02"], date(2026, 11, 7)) == ([], [])


# ---------- กฎของ schema (ADR-003) ----------


def test_order_id_is_unique_and_readable(week):
    orders, _ = week
    ids = [o.order_id for o in orders]
    assert len(ids) == len(set(ids))
    for o in orders:
        assert re.fullmatch(rf"{o.branch_id}-{o.order_time:%Y%m%d}-\d{{4}}", o.order_id)


def test_order_time_is_bangkok_and_within_open_hours(week):
    orders, _ = week
    for o in orders:
        assert o.order_time.utcoffset() == timedelta(hours=7)
        assert o.order_time.hour in CFG.seasonality.hourly_weight


def test_order_id_follows_time_order(week):
    orders, _ = week
    by_branch_day = {}
    for o in orders:
        by_branch_day.setdefault(o.order_id[:-5], []).append(o)
    for group in by_branch_day.values():
        assert group == sorted(group, key=lambda o: o.order_id)
        assert [o.order_time for o in group] == sorted(o.order_time for o in group)


def test_channel_is_one_the_branch_has(week):
    orders, _ = week
    for o in orders:
        assert o.channel_id in BRANCHES[o.branch_id].channels


def test_platform_ref_null_iff_walk_in(week):
    orders, _ = week
    for o in orders:
        prefix = SIM.channels[o.channel_id].ref_prefix
        if o.channel_id == "walk_in":
            assert o.platform_order_ref is None
        else:
            assert o.platform_order_ref.startswith(f"{prefix}-")


def test_platform_ref_unique_per_channel(week):
    orders, _ = week
    refs = [
        (o.channel_id, o.platform_order_ref) for o in orders if o.platform_order_ref
    ]
    assert len(refs) == len(set(refs))


def test_total_equals_sum_of_items(week):
    # รวมบิลที่ยกเลิกด้วย: ยอดเต็มเสมอ และยังมี items
    orders, items = week
    totals = Counter()
    for i in items:
        totals[i.order_id] += i.quantity * i.unit_price_incl_vat_thb
    for o in orders:
        assert o.total_price_incl_vat_thb == totals[o.order_id]
    assert {o.status for o in orders} == STATUSES


def test_lines_are_numbered_and_menu_not_repeated(week):
    _, items = week
    by_order = {}
    for i in items:
        by_order.setdefault(i.order_id, []).append(i)
    for lines in by_order.values():
        assert [i.line_no for i in lines] == list(range(1, len(lines) + 1))
        assert len({i.menu_id for i in lines}) == len(lines)


def test_unit_price_is_menu_price_snapshot(week):
    _, items = week
    price = {m.menu_id: m.price_incl_vat for m in CFG.menu}
    for i in items:
        assert i.unit_price_incl_vat_thb == price[i.menu_id]
        # 2 ตำแหน่งเสมอ ตรงกับ decimal(10,2) ของ bronze
        assert i.unit_price_incl_vat_thb.as_tuple().exponent == -2


# ---------- สถิติ: seed ตายตัว ผลจึงตายตัว ไม่ flaky ----------


@pytest.fixture(scope="module")
def cpn_quarter():
    # CPN01 3 เดือน ≈ 13k บิล: SD ของ Poisson รวม ≈ 1% ของค่าเฉลี่ย
    branch = BRANCHES["CPN01"]
    span = days(date(2025, 11, 1), 90)
    orders = [o for d in span for o in generate_day(CFG, SIM, branch, d)[0]]
    expected = sum(float(expected_bills(CFG, branch, d) or 0) for d in span)
    return orders, expected


def test_bill_count_matches_expected(cpn_quarter):
    orders, expected = cpn_quarter
    assert len(orders) == pytest.approx(expected, rel=0.03)


def test_channel_share_renormalized_to_branch_channels(cpn_quarter):
    # CPN01 มีแค่ walk_in 0.60 + grab 0.20 → walk_in 75%
    orders, _ = cpn_quarter
    share = sum(o.channel_id == "walk_in" for o in orders) / len(orders)
    assert share == pytest.approx(0.75, abs=0.02)


def test_evening_hours_are_busier(cpn_quarter):
    # hourly_weight 18–22 = 1.2 เทียบ 10–17 = 1.0
    orders, _ = cpn_quarter
    per_hour = Counter(o.order_time.hour for o in orders)
    evening = sum(per_hour[h] for h in range(18, 23)) / 5
    daytime = sum(per_hour[h] for h in range(10, 18)) / 8
    assert evening / daytime == pytest.approx(1.2, rel=0.05)
