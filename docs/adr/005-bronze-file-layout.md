# ADR-005: ผังไฟล์ของ bronze Parquet

- สถานะ: Accepted
- วันที่: 2026-11-04

## บริบท
Generator เขียนบิลตาม schema ของ ADR-003 ลง `data/bronze/` ให้ dbt (M2) อ่าน และ backfill ใน M6 ต้องรันซ้ำเป็นรายวันได้
ต้องเลือกว่าจะแบ่งไฟล์อย่างไร และการรันซ้ำต้องไม่ทำให้ข้อมูลซ้ำหรือค้าง

## ทางเลือก
1. ไฟล์เดียวทั้งปี: อ่านง่าย แต่แก้วันเดียวต้องเขียนทั้งไฟล์
2. ไฟล์ต่อ (วัน, สาขา): ละเอียดสุด แต่ได้ 3,650 ไฟล์เล็กๆ (small files) ให้ query engine ต้องเปิดทีละไฟล์
3. ไฟล์ต่อวัน แบบ Hive partition: `<table>/order_date=YYYY-MM-DD/part-0.parquet`

## ตัดสินใจ
เลือก **3** สำหรับทั้ง `orders` และ `order_items`

- `order_date` อยู่ใน path ไม่อยู่ในไฟล์ ใช้ตัดไฟล์ที่ไม่เกี่ยวตอน query (partition pruning) · `order_items` จึงกรองตามวันได้โดยไม่ต้องเพิ่มคอลัมน์ใน schema ของ ADR-003
- ทุกวันเขียนไฟล์เสมอ แม้ไม่มีบิล เพื่อให้รันซ้ำแล้วแทนที่ข้อมูลรุ่นเก่า
- เขียนลงไฟล์ชั่วคราวแล้ว `replace` เพื่อไม่ให้เหลือไฟล์ครึ่งเดียวถ้า process ตาย
- ช่วงวันเป็น argument ของ CLI (`--start`, `--end`) ไม่อยู่ใน config เพราะ backfill ต้องสั่งทีละช่วง
- `order_time` เก็บเป็น `timestamp[us, tz=Asia/Bangkok]`: Parquet เก็บ instant เป็น UTC ส่วน tz เป็น metadata

## ผลที่ตามมา
- รันวันเดียวกันซ้ำได้ไฟล์เดิมทุกไบต์ ไม่ว่าสั่งเป็นช่วงไหน (ตรวจแล้วทั้ง 730 ไฟล์ ข้าม process และ `PYTHONHASHSEED` ต่างกัน) ภายใต้ pyarrow เวอร์ชันเดียวกัน
- ผู้อ่านต้องเปิด hive partitioning เช่น `read_parquet(..., hive_partitioning=true)` ใน DuckDB และ `order_date` ที่ได้อาจเป็น string
- วันที่อยู่นอกช่วงที่สั่งจะไม่ถูกลบ ถ้าเคยสร้างเกินช่วงต้องลบ partition นั้นเอง
- generate ใหม่ทั้งหมดใช้เวลาหลักวินาที จึงไม่ต้อง commit หรือสำรอง `data/` (อยู่ใน `.gitignore`)

**ทบทวนเมื่อ**: Spark cold path (M4) เขียนไฟล์หลาย part ต่อวัน, ย้ายไป GCS/BigQuery (M8) ที่ใช้ partition column จริง หรือข้อมูลต่อวันใหญ่จนต้องแบ่งเพิ่ม
