# Kinda Data Platform

Data platform ด้านการเงินสำหรับร้านขนมปังไส้ครีมแฟรนไชส์ Kinda (5 สาขา) — สร้างตั้งแต่ศูนย์เพื่อเรียนงาน Data Engineer
ด้วย Kafka · Spark · Airflow · dbt · BigQuery

> 🚧 กำลังสร้าง — ความคืบหน้าดูที่ [docs/progress.md](docs/progress.md)

## เริ่มต้นใช้งาน

ต้องมี: Python 3.14, [Poetry](https://python-poetry.org/) 2.x, git, make

```bash
git clone <repo-url> && cd kinda-data-platform
make install
```

`make install` จะตรวจว่า `poetry.lock` ตรงกับ `pyproject.toml`, สร้าง `.venv/` ในโปรเจคให้ตรงกับ lock
(แพ็กเกจที่ไม่อยู่ใน lock จะถูกลบออก) และติดตั้ง pre-commit hook

## คำสั่ง

| คำสั่ง | ทำอะไร |
|---|---|
| `make install` | ติดตั้ง/sync env ตาม `poetry.lock` + ติดตั้ง pre-commit hook |
| `make lint` | ตรวจโค้ดด้วย ruff |
| `make test` | รัน pytest (เฉพาะ `tests/`; test ของ Spark รันใน container) |

## โครงสร้าง

ดูเหตุผลของโครงโฟลเดอร์และการจัด Python env ที่ [ADR-001](docs/adr/001-repo-layout-and-python-env.md)
