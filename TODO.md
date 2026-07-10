# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Harness Design (2026-07-10)

- [x] Write and validate the approved local-first technical harness specification.
- [x] Clarify batch-summary provenance and the temporal-holdout demo test.
- [x] Defer claim-event persistence and define cadence-specific frontier outputs.
- [x] Accelerate the temporal-holdout replay without relaxing visibility controls.
- [x] Produce the lightweight implementation contract for the approved technical harness.

## Session: Technical Harness Implementation (2026-07-10)

- [x] Task 1 — Establish the Python project and local quality baseline.
- [x] Task 2 — Provide the local Compose environment.
- [ ] Task 3 — Implement durable domain and persistence foundations.
  - [x] 3.1 Add runtime/dev dependencies (SQLAlchemy, Alembic, asyncpg, pgvector, langgraph, langgraph-checkpoint-postgres, testcontainers) and update lock
  - [x] 3.2 Create Pydantic domain models (src/analyst_engine/domain/models.py): Source, Article, ArticleBatch, BatchSummary, Brief, NarrativeStateVersion, PredictionExpectation, Embedding, WorkflowRun, Cadence, Citation, etc.
  - [x] 3.3 Bootstrap Alembic (alembic.ini + alembic/env.py + script) wired to our async engine and models
  - [x] 3.4 Author initial Alembic migration establishing tables + indexes + constraints (LangGraph checkpoint tables included; claim_event explicitly absent)
  - [x] 3.5 Persistence engine: async SQLAlchemy engine + scoped session factory from Settings (persistence/engine.py)
  - [x] 3.6 ORM models: SQLAlchemy 2 declarative models with pgvector, unique constraints, relationships (persistence/models.py)
  - [x] 3.7 Repositories: session-accepting CRUD + idempotency lookup for runs + citation helpers (persistence/repositories.py)
  - [x] 3.8 LangGraph checkpoint integration (persistence/checkpoints.py) using Postgres async saver on shared DB
  - [ ] 3.9 Persistence integration tests (tests/integration/) using Testcontainers Postgres+pgvector: blank migrate, constraints, repo ops, lineage, checkpoints
  - [ ] 3.10 Update docs/database.md and docs/patterns.md; reconcile architecture.md as needed for persistence
- [ ] Task 4 — Add provider and observability adapters.
- [ ] Task 5 — Assemble checkpointed cadence workflows and scheduling.
- [ ] Task 6 — Deliver the minimal API and operational readiness surface.
- [ ] Task 7 — Build deterministic fixtures and temporal-holdout evaluation.
- [ ] Task 8 — Finalize operational documentation and CI.

## Session: <Session Name> (<YYYY-MM-DD>)

- [ ] <sub-item 1>
- [ ] <sub-item 2>
- [ ] <sub-item 3>

## Future Backlog

- [ ] <future item>
