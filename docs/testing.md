# Testing Guide

## Purpose

Testing includes both execution and planning. Run automated tests and use test-plan-writer (when available) when meaningful changes need explicit coverage mapping.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- Dependencies installed: `uv sync`
- Run commands from the repository root
- Mock external services; do not contact DashScope, OpenRouter, LangSmith, or live data sources in routine tests
- Avoid real credentials in tests; supply fixture values directly to `Settings` or via test-local environment overrides

## Test Layout

```
tests/
  test_config.py              # Settings validation (baseline)
  test_compose_structure.py   # Static Compose contract and health check topology
```

Core layers:

- `tests/unit/` — domain, adapter (OpenRouter routing, process modes), repository lifecycle, workflow runner, graph, and runtime tests. Use fakes and mocks.
- `tests/integration/` — persistence (workflow run create/update/idempotency), migration round-trips, checkpoint behavior, and concurrency (require Docker/Testcontainers or CI Postgres service; capability-aware skipping).
- `tests/api/` — FastAPI liveness, readiness (200/503 + component shape), and trigger contract tests.
- `tests/evaluation/` — opt-in temporal holdout evaluation (outside routine
  CI). Drives `WorkflowRunner.run_daily/weekly/monthly` directly with no
  corpus or evidence data, not `DailyBriefPipeline`/`PeriodicBriefPipeline`
  (the path every production trigger uses, which does live ingestion,
  batching, and summarization against Postgres) - intentional, see the
  module docstring in `test_temporal_holdout.py` for why routing a real
  corpus through the pipelines isn't a small change, and note that the test
  is presently skip-only (not actually runnable if unskipped).

## Core Fixtures

Baseline tests construct `Settings` instances inline with deterministic fixture values. Integration and workflow tests share common fixtures for engine, session, and runner construction when Docker is available.

Postgres-backed test modules (any file with its own `migrated` fixture) each read `DATABASE_URL` when set - in CI this is one shared Postgres service, not a per-module container, so every such module's tests run against the same physical database with no isolation beyond what the module provides itself. A module's `migrated` fixture must call `truncate_domain_tables()` (`tests/fixtures.py`) after applying migrations, or its tests can collide with leftover rows from an earlier-run module (unique-constraint violations, or unscoped `COUNT`/`ORDER BY` assertions picking up rows they didn't insert). This only surfaces where a real `DATABASE_URL` is present (i.e. CI, not local runs without Docker) - see `docs/insights.md` for how this was diagnosed.

## Running Tests

Run all tests with coverage:

```bash
uv run pytest
```

Run one file:

```bash
uv run pytest tests/test_config.py
```

Run one test by keyword:

```bash
uv run pytest -k "loads_with_required"
```

Stop on first failure:

```bash
uv run pytest -x
```

Show verbose output:

```bash
uv run pytest -v
```

## Validation Workflow

Default sequence before commit:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Install and run pre-commit hooks for formatting, linting, whitespace checks, and secret detection:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## When To Invoke Test Planning Tools

Invoke after implementation and before PR-ready when:

- behavior changed
- API changed
- state transitions changed
- persistence changed
- external integrations changed
- acceptance criteria need coverage mapping

Do not invoke for trivial copy, docs-only, or tiny localized edits.

## Coverage Expectations

Meaningful changes should cover:

- happy path
- failure path
- boundary conditions
- state before and after
- persistence effects
- external service mocks
- regression case, if bug fix

Baseline settings tests demonstrate the expected pattern: deterministic fixture values, behavior-oriented test names, and field-specific validation error assertions.

## Test Writing Rules

- keep tests deterministic
- isolate state
- mock network and external services
- name tests by behavior
- assert durable outcomes, not implementation trivia
