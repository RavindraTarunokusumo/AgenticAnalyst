# Changelog

Record notable behavior, architecture, API, persistence, or workflow changes.

## 2026-07-12 — Runtime and Persistence Repair

Summary:
- What changed: Implemented truthful workflow-run lifecycle (explicit create + update with strict transitions: pending→running→succeeded/failed), shared RuntimeDependencies bundle (engine, session factory, ModelGateway, Postgres checkpointer factory) used by both API and scheduler modes, WorkflowRunner for cadence graphs with stable run ID as checkpoint thread/correlation, database+migration-aware readiness (/readyz returns component status and 503 when not ready; scheduler uses python -m ...readiness), OpenRouter provider support (MODEL_PROVIDER=openrouter, configurable frontier/batch models, mocked in routine tests), container health gated on HTTP readiness or readiness module, removal of file-based health markers. Initial Alembic migration covers workflow_run + LangGraph checkpoints (no claim_event). Updated operator docs and .env.example contract.
- Why: Prior harness-era implementation used temporary markers, insert-only runs, incomplete wiring, and inaccurate readiness; this repair makes execution, persistence, and operational probes match the durable design so that success is only reported after real graph completion and readiness reflects live DB state.
- User-visible impact: `docker compose up` now starts a real FastAPI on 8000 with /healthz (liveness) and /readyz (db/migrations); APP_PROCESS_MODE=scheduler runs registered cadence jobs; POST /workflows/trigger returns durable run records; readiness fails closed until migrations match head. OpenRouter selectable by supplying MODEL_PROVIDER and OPENROUTER_* directly to the application runtime environment (for direct non-Compose process execution) or via a user-supplied Compose override that explicitly adds `environment:` or `env_file:` (current compose.yaml does not forward these).
- Migration notes: One initial migration (963e5ab691b1) creates all core tables + checkpoint tables. Use Alembic for future revisions; downgrades supported where provided.
- Related PR/commit: Tasks 1-6 (c717d74, 1f88183, 3600a6a, f3d585d, 90a39fe+0bb9204, 86e41df+49ccabc); Task 7 doc reconciliation (this commit). See accepted spec docs/superpowers/specs/2026-07-11-runtime-persistence-repair-design.md and plan.

## <YYYY-MM-DD> — <Change Title>

Summary:
- What changed:
- Why:
- User-visible impact:
- Migration notes:
- Related PR/commit:
