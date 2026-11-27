PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: install lint format-check format typecheck test check e2e test-pg run docker-up fresh-clone-check

install:
	$(PY) -m pip install -r requirements-dev.txt

lint:
	$(PY) -m ruff check .

format-check:
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest

check: lint format-check typecheck test

e2e:
	$(PY) -m pytest tests/e2e -o addopts="-q"

run:
	$(PY) -m uvicorn app.main:app --reload --port 8000

docker-up:
	docker compose up --build
