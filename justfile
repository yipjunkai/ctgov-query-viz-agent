# Task runner. `just verify` is the single green gate — it must pass before any slice is "done".

set dotenv-load := true

default: verify

# Single green gate: format-check + lint + strict typecheck + tests (no network).
verify: lint typecheck test

# Lint + format-check (non-mutating; safe for CI).
lint:
    uv run ruff format --check .
    uv run ruff check .

# Auto-fix formatting and lint violations.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

typecheck:
    uv run pyright

# Fast tests only — e2e/live-network suites are excluded here.
test:
    uv run pytest

# Live tests against the real ClinicalTrials.gov API (network required).
e2e:
    uv run pytest -m e2e

# Run the service locally with autoreload.
run:
    uv run uvicorn ctgov_agent.api.app:app --reload

# Regenerate the golden example outputs in examples/.
examples:
    uv run python -m ctgov_agent.tools.gen_examples
