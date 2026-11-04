"""Test ของการเขียน bronze: อ่านกลับจากไฟล์จริงแล้วต้องได้ค่าเดิมตาม schema ของ ADR-003"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from generator.__main__ import main
from generator.bronze import (
    ORDER_ITEMS_SCHEMA,
    ORDERS_SCHEMA,
    partition_path,
    write_day,
)
from generator.config import load_config, load_simulation
from generator.orders import generate_day

CFG = load_config("config/business.yaml")
SIM = load_simulation("config/simulation.yaml", CFG)
BRANCHES = {b.branch_id: b for b in CFG.branches}
DAY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def day_data():
    return generate_day(CFG, SIM, BRANCHES["CNX01"], DAY)


def test_orders_round_trip(day_data, tmp_path):
    orders, items = day_data
    write_day(orders, items, DAY, tmp_path)
    table = pq.read_table(partition_path(tmp_path, "orders", DAY))

    assert table.schema.equals(ORDERS_SCHEMA)
    rows = table.to_pylist()
    assert len(rows) == len(orders)
    for row, order in zip(rows, orders, strict=True):
        assert row == vars(order)
        assert row["order_time"].utcoffset() == timedelta(hours=7)


def test_order_items_round_trip(day_data, tmp_path):
    orders, items = day_data
    write_day(orders, items, DAY, tmp_path)
    table = pq.read_table(partition_path(tmp_path, "order_items", DAY))

    assert table.schema.equals(ORDER_ITEMS_SCHEMA)
    assert table.to_pylist() == [vars(i) for i in items]


def test_money_stays_exact_decimal(day_data, tmp_path):
    orders, items = day_data
    write_day(orders, items, DAY, tmp_path)
    table = pq.read_table(partition_path(tmp_path, "orders", DAY))
    assert table.schema.field("total_price_incl_vat_thb").type == pa.decimal128(10, 2)
    total = table["total_price_incl_vat_thb"][0].as_py()
    assert isinstance(total, Decimal)
    assert total.as_tuple().exponent == -2


def test_rewrite_gives_identical_bytes(day_data, tmp_path):
    # backfill (M6): รันวันเดิมซ้ำต้องได้ไฟล์เดิม
    orders, items = day_data
    path = partition_path(tmp_path, "orders", DAY)
    write_day(orders, items, DAY, tmp_path)
    first = path.read_bytes()
    write_day(orders, items, DAY, tmp_path)
    assert path.read_bytes() == first


def test_rewrite_replaces_old_rows_and_leaves_no_temp_file(day_data, tmp_path):
    orders, items = day_data
    write_day(orders, items, DAY, tmp_path)
    write_day(orders[:3], [], DAY, tmp_path)

    path = partition_path(tmp_path, "orders", DAY)
    assert pq.read_table(path).num_rows == 3
    assert [p.name for p in path.parent.iterdir()] == ["part-0.parquet"]


def test_empty_day_writes_empty_file_with_schema(tmp_path):
    write_day([], [], DAY, tmp_path)
    table = pq.read_table(partition_path(tmp_path, "orders", DAY))
    assert table.num_rows == 0
    assert table.schema.equals(ORDERS_SCHEMA)


def test_hive_partition_is_readable_as_dataset(day_data, tmp_path):
    # dbt/DuckDB/Spark อ่านผ่าน order_date=... ได้โดยไม่ต้องมีคอลัมน์นี้ในไฟล์
    orders, items = day_data
    write_day(orders, items, DAY, tmp_path)
    table = pq.read_table(tmp_path / "orders")
    assert set(table["order_date"].to_pylist()) == {DAY.isoformat()}


def test_cli_writes_every_day_and_every_branch(tmp_path):
    main(["--start", "2026-11-02", "--end", "2026-11-03", "--out", str(tmp_path)])

    for day in (date(2026, 11, 2), date(2026, 11, 3)):
        branch_ids = set(
            pq.read_table(partition_path(tmp_path, "orders", day))[
                "branch_id"
            ].to_pylist()
        )
        # จันทร์ 11-02 CPN01 ปิด
        expected = {b.branch_id for b in CFG.branches} - (
            {"CPN01"} if day.weekday() == 0 else set()
        )
        assert branch_ids == expected


def test_cli_output_does_not_depend_on_range(tmp_path: Path):
    # วันเดียวกันต้องได้ไฟล์เดียวกัน ไม่ว่าสั่งเป็นช่วงไหน: เงื่อนไขของ backfill
    wide, narrow = tmp_path / "wide", tmp_path / "narrow"
    main(["--start", "2026-11-02", "--end", "2026-11-03", "--out", str(wide)])
    main(["--start", "2026-11-03", "--end", "2026-11-03", "--out", str(narrow)])

    day = date(2026, 11, 3)
    assert (
        partition_path(wide, "orders", day).read_bytes()
        == partition_path(narrow, "orders", day).read_bytes()
    )


def test_cli_rejects_reversed_range(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--start", "2026-11-03", "--end", "2026-11-02", "--out", str(tmp_path)])
    assert "--start 2026-11-03 is after --end 2026-11-02" in capsys.readouterr().err
