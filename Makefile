.PHONY: install lint test

install:
	poetry check --lock
	poetry sync

lint:
	poetry run ruff check .

test:
	poetry run pytest -v

