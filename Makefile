.PHONY: setup dev test lint fmt

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	cp -n .env.example .env 2>/dev/null || true
	@echo "\n✓ Setup complete. Edit .env with your API keys, then run: make dev"

dev:
	INNGEST_DEV=1 .venv/bin/uvicorn src.main:app --reload --port 8000

test:
	OMDB_API_KEY=test .venv/bin/pytest -v

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	.venv/bin/ruff check --fix . && .venv/bin/ruff format .
