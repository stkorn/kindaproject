.PHONY: install lint test

install:
	poetry check --lock
	poetry sync
	poetry run pre-commit install

lint:
	poetry run ruff check .

test:
	poetry run pytest -v
