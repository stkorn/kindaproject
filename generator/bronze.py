"""เขียนบิลลง bronze Parquet (schema ตาม ADR-003, ผังไฟล์ตาม ADR-005)

หนึ่งวัน = หนึ่งไฟล์ต่อตาราง: <root>/<table>/order_date=YYYY-MM-DD/part-0.parquet
เขียนทับได้เสมอ: รันวันเดิมซ้ำได้ไฟล์เดิม (idempotent) จึง backfill ทีละวันได้
"""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from generator.orders import Order, OrderItem

MONEY = pa.decimal128(10, 2)

ORDERS_SCHEMA = pa.schema(
    [
        pa.field("order_id", pa.string(), nullable=False),
        pa.field("branch_id", pa.string(), nullable=False),
        # Parquet เก็บเป็น UTC เสมอ ส่วน tz เป็น metadata ของ Arrow ใช้แสดงผล
        pa.field("order_time", pa.timestamp("us", tz="Asia/Bangkok"), nullable=False),
        pa.field("channel_id", pa.string(), nullable=False),
        pa.field("total_price_incl_vat_thb", MONEY, nullable=False),
        pa.field("platform_order_ref", pa.string()),  # null เมื่อเป็น walk_in
        pa.field("status", pa.string(), nullable=False),
    ]
)

ORDER_ITEMS_SCHEMA = pa.schema(
    [
        pa.field("order_id", pa.string(), nullable=False),
        pa.field("line_no", pa.int32(), nullable=False),
        pa.field("menu_id", pa.string(), nullable=False),
        pa.field("quantity", pa.int32(), nullable=False),
        pa.field("unit_price_incl_vat_thb", MONEY, nullable=False),
    ]
)


def partition_path(root: Path, table: str, day: date) -> Path:
    return root / table / f"order_date={day.isoformat()}" / "part-0.parquet"


def write_table(rows: list[Order | OrderItem], schema: pa.Schema, path: Path) -> None:
    # vars(): แถวเป็น dict ที่ชื่อ field ตรงกับคอลัมน์ · ไม่มีบิลก็ยังเขียนไฟล์ว่าง
    # เพื่อให้ partition เดิมถูกแทนที่ ไม่ค้างข้อมูลรุ่นเก่า
    table = pa.Table.from_pylist([vars(r) for r in rows], schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    # เขียนไฟล์ชั่วคราวก่อนแล้ว replace: ถ้าตายกลางทาง ไฟล์เดิมยังครบ ไม่มีไฟล์ครึ่งเดียว
    tmp = path.with_suffix(".tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)


def write_day(
    orders: list[Order], items: list[OrderItem], day: date, root: Path
) -> None:
    write_table(orders, ORDERS_SCHEMA, partition_path(root, "orders", day))
    write_table(items, ORDER_ITEMS_SCHEMA, partition_path(root, "order_items", day))
