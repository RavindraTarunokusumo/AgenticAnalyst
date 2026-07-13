# 2026-07-11 — Runtime and Persistence Repair (codex/runtime-persistence-repair)

**Merge:** PR #2 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/2)
**Merge commit:** 2cd8ad0260a3ee50727727bf1addf45247e1f82a
**Feature branch:** codex/runtime-persistence-repair
**Merged:** 2026-07-12T19:14:20Z

## Completed Work

- [x] Separate workflow-run creation from lifecycle updates and enforce valid transitions. (`c717d74`)
- [x] Add OpenRouter configuration and provider routing with offline contract tests. (`1f88183`)
- [x] Introduce shared runtime dependency wiring for API and scheduler modes. (`3600a6a`)
- [x] Execute cadence graphs with stable run/checkpoint identity and truthful failure handling. (`f3d585d`)
- [x] Replace hard-coded readiness and file health markers with database/migration-aware HTTP readiness. (`90a39fe`, `0bb9204`)
- [x] Enable and repair persistence, workflow, API, migration, and Compose verification for this milestone. (`86e41df`, `49ccabc`)
- [x] Reconcile operational documentation and complete the full project quality gates. (docs: `739a764`, `0268b42`, `facb92e`, `fa19810`, `330ffde`; harness/gates: `b0b00fa`, `f7ab25d`, `7bb40b4`)
  - [x] Task 7: valid persistence lineage fixture (`b0b00fa`)
  - [x] Task 7: portable Docker/async integration harness (`f7ab25d`)
  - [x] Task 7: rerun Docker migration/checkpoint/concurrency gates (gates passed) (`dc8f040`)
  - [x] PR review: isolate testcontainers URL normalization from DATABASE_URL (`2bd292e`)
  - [x] CI review: make Windows selector policy type-safe on Linux (`06143db`)
  - [x] Task 7: CI review: isolate missing DATABASE_URL settings test from CI environment (`2f64a32`)

## Summary

Repaired workflow-run persistence with explicit create/update operations, valid lifecycle transitions, stable idempotency, and concurrency-safe claims. Added OpenRouter provider configuration and routing behind the existing provider-neutral gateway. Introduced shared API/scheduler runtime dependencies and checkpointed cadence execution with truthful durable outcomes. Replaced placeholder readiness with live database and Alembic-head checks, including Compose HTTP readiness. Reconciled operational documentation and hardened Docker-backed integration verification on Windows and other supported hosts.

Root cause: the initial harness mixed insert and update semantics, allowed runtime dependencies to remain incomplete, could report workflow success without verified graph execution, and exposed placeholder readiness. Integration tests also skipped real Docker failures because endpoint detection, async loop scope, and fixture data did not match the production contracts.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` — passed.
- `uv run mypy src tests` — clean.
- `uv run pytest` with Docker Desktop — 102 passed, 2 intentional opt-in skips.
- `uv run pytest tests/integration -rs` without explicit `DOCKER_HOST` — 6 passed (Docker Desktop detection, migration round-trip, checkpoints, concurrency).
- `docker compose config --quiet` with test-only required environment values — passed.
- `uv run pytest tests/test_compose_structure.py` — 10 passed.
- GitHub Actions run `29195662415` — Ruff, lint, mypy, PostgreSQL-backed tests, Alembic check, and Compose structure all passed.
