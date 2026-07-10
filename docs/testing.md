# Testing Guide

## Purpose

Testing includes both execution and planning. Run automated tests and use test-plan-writer (when available) when meaningful changes need explicit coverage mapping.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- Dependencies installed: `uv sync`
- Run commands from the repository root
- Mock external services; do not contact DashScope, LangSmith, or live data sources in routine tests
- Avoid real credentials in tests; supply fixture values directly to `Settings` or via test-local environment overrides

## Test Layout

```
tests/
  test_config.py    # Settings validation (baseline)
```

Additional layers are added as the harness grows:

- `tests/unit/` — domain and adapter unit tests
- `tests/integration/` — persistence and migration tests
- `tests/workflow/` — LangGraph workflow tests
- `tests/api/` — FastAPI delivery tests
- `tests/evaluation/` — opt-in temporal holdout evaluation (outside routine CI)

## Core Fixtures

Baseline tests construct `Settings` instances inline with deterministic fixture values. Shared fixtures and factories are introduced in later harness tasks.

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
