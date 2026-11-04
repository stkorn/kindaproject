# ADR-003: Schema ของบิลในชั้น bronze

- สถานะ: Accepted
- วันที่: 2026-11-03

## บริบท
Generator สร้างบิลจำลองลง `data/bronze/` เป็น Parquet แล้ว dbt (M2) อ่านไปทำยอดขาย, P&L, royalty และ reconciliation
บิลหนึ่งใบมีหลายรายการ แต่คำถามทางธุรกิจถามได้ทั้งระดับบิล ("ยอดขายวันนี้") และระดับสินค้า ("เฟอเรโร่ขายได้กี่ชิ้น")
bronze ควรมีหน้าตาเหมือนข้อมูลที่ POS และ delivery platform ส่งออกมาจริง และ rebuild ชั้นบนได้โดยไม่ต้อง generate ใหม่

## ทางเลือก
**Grain**
1. ตารางเดียว หนึ่งแถวต่อบิล โดยเก็บรายการเป็น list: ต้อง unnest ทุกครั้งที่ถามระดับสินค้า
2. ตารางเดียว หนึ่งแถวต่อรายการ และข้อมูลระดับบิลซ้ำทุกแถว: `sum` ยอดบิลจะนับซ้ำตามจำนวนรายการ
3. สองตาราง `orders` + `order_items`: แต่ละตารางมี grain เดียว แต่ต้อง join

**เลขออเดอร์ฝั่ง platform**
1. แยกคอลัมน์ตาม platform (`grab_order_id`, `lineman_order_id`, …): เป็น null เกือบทั้งหมด, เพิ่มช่องทางใหม่ต้องแก้ schema และ schema ไม่กันบิล walk-in ที่มีเลข Grab ติดมา
2. คอลัมน์เดียว `platform_order_ref` ที่ความหมายขึ้นกับ `channel_id`

## ตัดสินใจ
เลือก grain แบบ **3** และเลขออเดอร์แบบ **2**

`orders` (หนึ่งแถวต่อบิล, PK `order_id`)

| คอลัมน์ | ชนิด | หมายเหตุ |
|---|---|---|
| `order_id` | string | |
| `branch_id` | string | FK `branches` |
| `order_time` | timestamp (tz-aware, +07:00) | |
| `channel_id` | string | FK `channels` |
| `total_price_incl_vat_thb` | decimal(10,2) | ยอดเต็มเสมอ แม้บิลถูกยกเลิก |
| `platform_order_ref` | string, nullable | null เมื่อเป็น `walk_in` · unique ต่อ `(channel_id, platform_order_ref)` |
| `status` | string | `completed` \| `cancelled_by_customer` \| `cancelled_by_branch` |

`order_items` (หนึ่งแถวต่อบรรทัดในบิล, PK `(order_id, line_no)`)

| คอลัมน์ | ชนิด | หมายเหตุ |
|---|---|---|
| `order_id` | string | FK `orders` |
| `line_no` | int | |
| `menu_id` | string | FK `menu` |
| `quantity` | int | |
| `unit_price_incl_vat_thb` | decimal(10,2) | ราคา ณ ตอนขาย ไม่ join จาก config |

หลักการ:
- คอลัมน์อยู่ที่ grain ที่ค่านั้นขึ้นอยู่กับ key จริง เช่น `branch_id`, `channel_id` และ `order_time` เป็นคุณสมบัติของบิล
- bronze **ไม่กรองและไม่คำนวณ** บิลที่ยกเลิกเก็บไว้พร้อม `status` ส่วน GP, ค่าคอมมิชชั่น และการตัดบิลที่ยกเลิกออกจากรายได้เป็นงานของ dbt
- เงินใช้ decimal ทั้งระบบ (`decimal.Decimal` สร้างจาก string ใน Python และ `decimal128(10, 2)` ใน Parquet)

## ผลที่ตามมา
- ถามระดับบิลได้จาก `orders` และถามระดับสินค้าได้จาก `order_items` โดยไม่นับซ้ำ แต่ถ้าต้องการทั้งสองระดับพร้อมกันต้อง join
- เพิ่มช่องทาง delivery ใหม่ได้โดยแก้แค่ config ไม่ต้องแก้ schema
- ขึ้นราคาใน config ได้โดยไม่กระทบยอดขายย้อนหลัง
- reconciliation (M7) ใช้ `platform_order_ref` จับคู่กับ statement ของ platform และใช้ `status` อธิบายเงินชดเชยหรือค่าปรับจากบิลที่ยกเลิก
- DQ test ที่ได้จาก schema นี้ (M2):
  - `unique` บน `order_id` และบน `(order_id, line_no)`
  - `relationships` ไป `branches` / `channels` / `menu`
  - `accepted_values` บน `status`
  - `platform_order_ref` เป็น null ก็ต่อเมื่อ `channel_id = 'walk_in'`
  - `total_price_incl_vat_thb = sum(quantity × unit_price_incl_vat_thb)` ทุกบิล รวมบิลที่ยกเลิกด้วย
- ยอดใน `total_price_incl_vat_thb` ซ้ำซ้อนกับผลรวมของ items โดยตั้งใจ เพื่อใช้ตรวจความถูกต้องระหว่างกัน
- generator ต้องห้ามใช้ float กับเงิน (การผสม `Decimal` กับ `float` ใน Python จะ raise `TypeError`)

**ทบทวนเมื่อ**: มีส่วนลด, โปรโมชัน หรือค่าส่ง ที่ทำให้ยอดบิลไม่เท่ากับผลรวมของรายการ, มีราคา delivery ต่างจากหน้าร้าน
หรือมีการคืนเงินบางส่วน (partial refund) ซึ่งต้องใช้ตาราง event แยก
