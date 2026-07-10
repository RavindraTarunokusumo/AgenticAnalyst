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
- [x] Task 3 — Implement durable domain and persistence foundations.
  - [x] 3.1 Add runtime/dev dependencies (SQLAlchemy, Alembic, asyncpg, pgvector, langgraph, langgraph-checkpoint-postgres, testcontainers) and update lock
  - [x] 3.2 Create Pydantic domain models (src/analyst_engine/domain/models.py): Source, Article, ArticleBatch, BatchSummary, Brief, NarrativeStateVersion, PredictionExpectation, Embedding, WorkflowRun, Cadence, Citation, etc.
  - [x] 3.3 Bootstrap Alembic (alembic.ini + alembic/env.py + script) wired to our async engine and models
  - [x] 3.4 Author initial Alembic migration establishing tables + indexes + constraints (LangGraph checkpoint tables included; claim_event explicitly absent)
  - [x] 3.5 Persistence engine: async SQLAlchemy engine + scoped session factory from Settings (persistence/engine.py)
  - [x] 3.6 ORM models: SQLAlchemy 2 declarative models with pgvector, unique constraints, relationships (persistence/models.py)
  - [x] 3.7 Repositories: session-accepting CRUD + idempotency lookup for runs + citation helpers (persistence/repositories.py)
  - [x] 3.8 LangGraph checkpoint integration (persistence/checkpoints.py) using Postgres async saver on shared DB
  - [x] 3.9 Persistence integration tests (tests/integration/) using Testcontainers Postgres+pgvector: blank migrate, constraints, repo ops, lineage, checkpoints
  - [x] 3.10 Update docs/database.md and docs/patterns.md; reconcile architecture.md as needed for persistence
- [ ] Task 4 — Add provider and observability adapters.
  - [ ] 4.1 Add runtime deps (openai, langsmith, httpx, fastapi, uvicorn, apscheduler) + dev (freezegun); uv lock/sync
  - [ ] 4.2 Define ModelGateway protocol, ModelTask, structured output contracts, usage metadata (src/analyst_engine/models/gateway.py)
  - [ ] 4.3 Implement DashScopeOpenAIAdapter: routing (flash for batch, max for frontier, embedding-v4), timeout/retry, error classification (retryable vs terminal), structured output enforcement
  - [ ] 4.4 Implement observability: LangSmith init (opt-in), run correlation, redaction of secrets + article excerpts/body, metadata enrichment (run_id, cadence, model, checkpoint)
  - [ ] 4.5 Wire Settings for model names, timeouts, langsmith; update .env.example
  - [ ] 4.6 Unit/contract tests (transport mocks) asserting request shape, model selection, rejection of bad structured output, non-fatal tracing
  - [ ] 4.7 Update architecture.md, testing.md
- [ ] Task 5 — Assemble checkpointed cadence workflows and scheduling.
  - [ ] 5.1 Define workflow state (Pydantic models for daily/weekly/monthly inputs/outputs, graph state)
  - [ ] 5.2 Implement daily graph: load recent batches/summaries + prior briefs/narrative → call gateway (flash summaries if needed) → frontier (max) → produce Brief + proposed NarrativeStateVersion + expectations; citation validation + atomic write via repositories + checkpoint
  - [ ] 5.3 Implement weekly and monthly graphs (rollup over previous briefs + retrieval)
  - [ ] 5.4 Create WorkflowRunner (idempotency via repo lookup, resume from checkpoint, error handling that leaves resumable state)
  - [ ] 5.5 APScheduler setup in scheduling.py: register daily/weekly/monthly jobs (only in scheduler mode), use idempotency keys
  - [ ] 5.6 Workflow integration tests with fake gateway: success paths, bad output rejection, checkpoint resume, duplicate schedule, all cadences
  - [ ] 5.7 Process mode test (scheduler vs api)
- [ ] Task 6 — Deliver the minimal API and operational readiness surface.
  - [ ] 6.1 Create FastAPI app (src/analyst_engine/api/app.py): lifespan for engine + checkpointer + readiness (migrations + db)
  - [ ] 6.2 Health/readiness endpoints; read-only GET /briefs, /narrative-versions (with filters)
  - [ ] 6.3 Authenticated POST /workflows/trigger (cadence + interval) → idempotent run via runner, return run status
  - [ ] 6.4 main.py entrypoint: uvicorn for api mode, or scheduler start
  - [ ] 6.5 Update docker/app-entrypoint.sh and compose for modes
  - [ ] 6.6 API tests (TestClient/ASGI) + update commands/docs
- [ ] Task 7 — Build deterministic fixtures and temporal-holdout evaluation.
  - [ ] 7.1 Add test fixtures/fakes (fake gateway, fake clock, source/article factories, brief factories) in tests/
  - [ ] 7.2 Define evaluation corpus manifest format + small synthetic post-cutoff example
  - [ ] 7.3 Implement TemporalHoldoutRunner: virtual clock, accelerated cadence triggers, strict time visibility (no future leaks), report with traces/citations/config
  - [ ] 7.4 Evaluation test (opt-in, marked, skipped in CI)
  - [ ] 7.5 Update docs/testing.md, commands.md
- [ ] Task 8 — Finalize operational documentation and CI.
  - [ ] 8.1 Reconcile all acceptance criteria; fill/update architecture, commands, testing, agent-harness, changelog
  - [ ] 8.2 Create .github/workflows/ci.yml (fresh env: ruff, mypy, pytest (skipping integration/eval), alembic check on postgres service, compose smoke)
  - [ ] 8.3 Update .env.example, docs/index.md, commands for full harness
  - [ ] 8.4 Final review of diffs for leakage, trailing newlines; full quality gate (once, at end)

## Session: <Session Name> (<YYYY-MM-DD>)

- [ ] <sub-item 1>
- [ ] <sub-item 2>
- [ ] <sub-item 3>

## Future Backlog

- [ ] <future item>
