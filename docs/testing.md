# Testing Guide

## Purpose

Testing includes both execution and planning. Run automated tests and use test-plan-writer (when available) when meaningful changes need explicit coverage mapping.

## Prerequisites

- activate the project environment
- run commands from repo root
- mock external services
- avoid real credentials in tests

## Test Layout

Document test groups as the project grows:
- API / delivery tests
- service / domain tests
- persistence tests
- integration tests
- frontend tests (if any)
- fixtures / helpers

## Core Fixtures

Document shared fixtures and helpers once defined.

## Running Tests

(Define actual commands once the test runner and stack are chosen.)

Example placeholders:

Run all tests:
```bash
# pytest
# npm test
# cargo test
# etc.
```

Run one file / one test / by keyword / stop on first failure — adapt to actual tooling.

## Validation Workflow

Default sequence before commit (adapt to stack):
```bash
# lint + format + test commands here
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

## Test Writing Rules

- keep tests deterministic
- isolate state
- mock network and external services
- name tests by behavior
- assert durable outcomes, not implementation trivia
