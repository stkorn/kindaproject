.PHONY: install lint test generate

install:
	poetry check --lock
	poetry sync
	poetry run pre-commit install

lint:
	poetry run ruff check .

test:
	poetry run pytest -v

# 12 เดือนตาม CLAUDE.md · เขียนทับ partition เดิมได้เสมอ (idempotent)
generate:
	poetry run python -m generator --start 2025-11-01 --end 2026-10-31
