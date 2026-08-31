.PHONY: install lint format typecheck test test-integration test-all up down env check

install:            ## Install the package and dev tooling into the active environment
	pip install -e '.[dev]'

lint:               ## Ruff lint + format check — same as CI
	ruff check .
	ruff format --check .

format:             ## Apply Ruff's formatting and safe fixes
	ruff check . --fix
	ruff format .

typecheck:          ## mypy, strict
	mypy

test:               ## Unit tests with the 100% coverage gate (no containers needed)
	pytest -m "not integration" --cov --cov-report=term-missing

test-integration:   ## Real Postgres + Redis; run ./scripts/dev-up.sh first
	pytest -m integration --no-cov

test-all: test test-integration

up:                 ## Start this worktree's isolated stack
	./scripts/dev-up.sh

down:               ## Tear this worktree's stack down, volumes included
	./scripts/dev-down.sh

env:                ## Print env vars pointing at this worktree's stack
	./scripts/dev-env.sh

check: lint typecheck test  ## Everything CI runs without containers
