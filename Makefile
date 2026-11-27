PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: install lint format-check format typecheck test check e2e test-pg run docker-up fresh-clone-check test-pg acceptance loc e2e-pg

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
	$(PY) -m uvicorn --factory app.main:create_app --reload --port 8000

docker-up:
	docker compose up --build

# Run the unit tests against PostgreSQL (needs a reachable server).
TEST_DATABASE_URL ?= postgresql://rb:rb@localhost:5432/rb_test
test-pg:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PY) -m pytest

# Acceptance: browser flows (SPEC "Done when"), PostgreSQL run, fresh-clone Docker check.
acceptance: e2e test-pg

fresh-clone-check:
	scripts/check_fresh_clone.sh

loc:
	$(PY) scripts/count_loc.py | tail -1

E2E_DATABASE_URL ?= postgresql://rb:rb@localhost:5432/rb_e2e
e2e-pg:
	E2E_DATABASE_URL=$(E2E_DATABASE_URL) $(PY) -m pytest tests/e2e -o addopts="-q"
