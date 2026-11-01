# ADR-001: Repo layout และ Python environment

- สถานะ: Accepted
- วันที่: 2026-11-01

## บริบท
Repo นี้จะมีโค้ดหลายชั้น: business config, data generator + Kafka producer, Spark Structured Streaming,
Airflow DAGs, dbt project และ (ภายหลัง) script สำหรับ GCP ทุกชั้นยกเว้น dbt เป็น Python

ข้อจำกัดที่บังคับการเลือก:
- เครื่อง dev เป็น Mac ที่ใช้ Python 3.14 แต่ PySpark 3.5 ยังไม่รองรับ 3.14 ถ้าใส่ Spark ไว้ใน env เดียวกับ generator จะ lock ไม่ผ่าน
- Spark (M4–M5) และ Airflow (M6) รันใน Docker image ของตัวเองซึ่งมี Python และ dependency แยกอยู่แล้ว
- โปรเจคเป็นงานคนเดียว ทุก env หรือ lock ที่เพิ่มเข้ามาคือภาระดูแลที่เพิ่มขึ้นโดยตรง

## ทางเลือก
**A: แยก `pyproject.toml` ต่อโฟลเดอร์ + `shared/` package**
แต่ละส่วนแยกกันชัดเจนและ deploy แยกกันได้ แต่จะได้ 4 pyproject, 4 lock และ 4 venv ต้องคอยให้เวอร์ชันตรงกันเอง
`make install` ต้องวนลูปทีละโฟลเดอร์ เจอปัญหา `poetry -P` จาก subfolder และ `shared/` ยังไม่มีโค้ดที่ใช้ร่วมกันจริง

**B: `pyproject.toml` เดียวที่ root, แยกเฉพาะที่จำเป็น**
มี venv และ lock ชุดเดียวสำหรับเครื่องมือ dev (generator, producer, tests, dbt, ruff) runtime ที่รันใน container
(Spark, Airflow) จัดการ dependency ใน image ของตัวเอง ข้อเสียคือถ้าส่วนใดโตจนต้องการ dependency ที่ขัดกัน ต้องแยกทีหลัง

## ตัดสินใจ
เลือก **B** โครงโฟลเดอร์:

```
kinda-data-platform/
├── config/      # business config (YAML) ที่ generator, dbt และส่วนอื่นใช้ร่วมกัน
├── generator/   # สร้างข้อมูลจำลอง + producer ยิง event เข้า Kafka (ทุกอย่างก่อนถึง Kafka)
├── streaming/   # Spark jobs ที่อ่านจาก Kafka (ทุกอย่างหลัง Kafka) รันใน Docker
├── streaming/
│   └── tests/   # unit test ของ Spark รันใน container
├── dags/        # Airflow DAGs, mount เข้า container ของ Airflow
├── dbt/         # dbt project (deployable unit แยกของตัวเอง)
├── docker/      # Dockerfile และ config ของ service (Kafka, Spark, Airflow)
├── tests/       # unit tests ของโค้ด Python ที่รันบน venv ของ root (ไม่รวม Spark)
└── docs/        # เอกสารและ ADR
```

`pyproject.toml` และ `poetry.lock` อยู่ที่ root ส่วน venv อยู่ใน `.venv/` ของโปรเจค

## ผลที่ตามมา
- `make install` ครั้งเดียวได้ env ครบ ส่วน ruff/pytest config อยู่ที่เดียว
- producer `import generator` ได้ตรงๆ ไม่ต้องมี `shared/` (จะสร้างก็ต่อเมื่อมีโค้ดซ้ำจริง)
- Spark และ Airflow **ไม่ได้** ใช้ dependency จาก root `pyproject.toml` แต่ประกาศไว้ใน Dockerfile/requirements ของ image แต่ละตัว
  ต้องระวังเวอร์ชันของ library ที่ใช้ร่วมกัน (เช่น pyarrow) ไม่ให้ห่างกันมาก
- pytest ที่ root ตั้ง testpaths = ["tests"] → ไม่เห็น streaming/tests/
- Spark test รันใน container: docker compose run --rm spark pytest streaming/tests (รายละเอียดอยู่ใน M4)

**ทบทวน ADR นี้เมื่อ**: dependency ของสองส่วนขัดกันจน lock ไม่ผ่าน, ส่วนใดต้อง deploy เป็น package แยก
หรือ `make install` ช้าจนรบกวนการทำงาน
