# Learning progress

> Claude อัปเดตไฟล์นี้ตอนจบทุก session · ผู้ใช้แก้/เติมได้เสมอ

## สถานะปัจจุบัน
- **Milestone**: M1 — Business config + data generator (ยังไม่เริ่ม) · M0 ✅ merged (PR #1, `44ad4c5`)
- **Branch**: `main` → สร้าง `m1-generator` ตอนเริ่ม
- **ก้าวถัดไป**: คุยโครง business config (YAML) ก่อนเขียน generator

## Log
### 2026-11-01 — เริ่มใหม่จากศูนย์
- ย้ายงานเดิมไปเป็น reference worktree (`../kinda-data-platform-reference`, branch `reference`)
- `main` เริ่มด้วย CLAUDE.md, README, .gitignore, ไฟล์นี้

### 2026-11-01/02 — M0 Repo foundation
- ADR-001: root `pyproject.toml` เดียว (ทางเลือก B), producer อยู่ใน `generator/`, Spark tests ใน `streaming/tests/` รันใน container
- Poetry: `poetry.toml` (in-project venv), `requires-python = ">=3.14,<3.15"`, `package-mode = false`, dev group = pytest, ruff, pre-commit
- เช็ค wheel cp314 macOS arm64: duckdb (abi3), dbt-core/dbt-duckdb (pure), msgpack, protobuf ผ่านหมด → อยู่ 3.14 ได้
- `.gitignore` จัดหมวด: secrets (`.env.*`, `*key*/*credential*/*service-account*.json`), caches, DuckDB, dbt, Spark local
- Makefile: `install` (check --lock → sync → pre-commit install), `lint`, `test`
- pre-commit: pre-commit-hooks v6.0.0 (detect-private-key, large files, yaml/toml, EOF, whitespace, merge conflict) + ruff แบบ `repo: local`
- ruff: config ใน `pyproject.toml`, `extend-select = ["DTZ", "I"]`
- DoD: clone สะอาด → `make install` exit 0, `pip freeze` เหมือน env เดิมทุกตัว (Claude รันตรวจให้ ผู้ใช้เลือกข้ามการรันเอง)

## สิ่งที่เข้าใจแล้ว
- แยกโฟลเดอร์ตาม data flow / deployable unit (ก่อน Kafka = generator, หลัง Kafka = streaming)
- `poetry.toml` (commit ได้) vs `poetry config` global (อยู่แค่เครื่องเดียว)
- ทำไม commit `poetry.lock`: pin เวอร์ชันจริง + transitive deps + hash, `content-hash` ผูกกับ pyproject (ขอเฉลย — ควรทบทวน)
- `[project]` คือ metadata มาตรฐาน, config เครื่องมือทุกตัวอยู่ใต้ `[tool.*]`
- pytest collection error หยุดทั้งรอบ (exit 2), ไม่มี test = exit 5
- gitignore แบบ fail-safe vs fail-open, defense in depth (ชื่อไฟล์ / เนื้อหา / ไม่มี key เลยด้วย ADC)

## สิ่งที่ยังสับสน / อยากทบทวน
- `poetry install` vs `poetry sync` (ตอนแรกเข้าใจว่า install ลบของเกิน)
- `.PHONY` และ target ที่เป็นไฟล์จริง (`test: install` trade-off — ขอเฉลย)
- pre-commit hook id มาจาก `.pre-commit-hooks.yaml` ของแต่ละ repo
- `select` vs `extend-select` / `exclude` vs `extend-exclude`

## ค้างไว้ทำทีหลัง
- **M1**: ตัดสินใจ `package-mode = false` + `pythonpath = ["."]` หรือ `packages = [{ include = "generator" }]` เพื่อให้ `tests/` import `generator` ได้
- **M1**: `make test` จะ exit 5 จนกว่ามี test แรก (ตั้งใจไว้ ทางเลือก b)
- **M4**: Spark checkpoint ให้อยู่ใต้ `data/` (ถูก ignore อยู่แล้ว)
- **M8**: ใช้ `gcloud auth application-default login` แทนไฟล์ service-account key
- **M9**: `make lint` ควรมี `ruff format --check` ด้วย (ตอนนี้ format ตรวจแค่ใน pre-commit); CI รัน pre-commit ซ้ำเพราะ `--no-verify` ข้ามได้
