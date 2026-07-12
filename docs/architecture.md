# System Architecture

## Entry Points

The local environment is defined in `compose.yaml` and contains exactly three
services:

- `app`: a single AnalystEngine image. `APP_PROCESS_MODE=api` is the default;
  `scheduler` selects the scheduler process. The shared entrypoint (and main)
  validates the mode and constructs the runtime dependency bundle for both
  processes. In API mode the process serves a FastAPI application (uvicorn on
  port 8000) exposing liveness, readiness, workflow triggers, and read-only
  endpoints. In scheduler mode the process constructs the same runtime and
  registers APScheduler jobs that drive WorkflowRunner cadence execution.
- `postgres`: PostgreSQL 16 with pgvector, backed by the `postgres_data` named
  volume.
- `searxng`: self-hosted search, backed by the `searxng_config` named volume.
  Its settings template receives its required secret through the environment at
  first initialization; no real secret or fallback is committed. The bootstrap
  initializes the named configuration volume once, then preserves its secret
  and settings across restarts. SearXNG is available to the host at
  `http://localhost:8080` and to `app` at `http://searxng:8080`.

Compose waits for healthy PostgreSQL and SearXNG services before it starts the
application. Application health checks are implemented via the readiness
subsystem rather than temporary file markers: API mode probes the HTTP /readyz
endpoint; scheduler mode executes the readiness module directly. The app image
includes Crawl4AI and Playwright Chromium (installed at build) so future
ingestion work can use the same image.

## Module Structure

### Core / Infrastructure

- `config.py`: typed Settings (pydantic-settings) for direct application runtime configuration. MODEL_PROVIDER and OpenRouter settings (plus others like DATABASE_URL, APP_PROCESS_MODE, LangSmith flags) are read from process environment or .env; Compose currently forwards only a subset (APP_PROCESS_MODE, DASHSCOPE_*, DATABASE_URL, LANGSMITH_* etc.) and does not declare MODEL_PROVIDER or OPENROUTER_* .
- `runtime.py`: constructs the shared `RuntimeDependencies` bundle (engine, async session factory, ModelGateway, checkpointer factory) from Settings; owns resource cleanup on close.
- `persistence/engine.py`: async SQLAlchemy engine + session_scope helper.
- `persistence/checkpoints.py`: LangGraph AsyncPostgresSaver integration.

### Domain

- `domain/models.py`: pure Pydantic contracts (Source, Article, BatchSummary, Brief, NarrativeStateVersion, WorkflowRun, WorkflowStatus, ...). No infrastructure imports.

### Data / Persistence

- `persistence/models.py`: SQLAlchemy 2 ORM (mirrors migration schema, pgvector)
- `persistence/repositories.py`: session-scoped writes and lookups with explicit create/update for workflow runs, idempotency, citation helpers, and transition validation.
- `alembic/`: sole schema evolution (initial migration creates analytical tables + workflow_run + LangGraph checkpoint tables; no claim_event).

### Runtime Composition

- `main.py`: dispatches on APP_PROCESS_MODE to run_api (uvicorn factory) or run_scheduler (APScheduler + WorkflowRunner).
- `scheduling.py`: registers cadence jobs on the scheduler.

### Services / Workflows

- `workflows/runner.py`: WorkflowRunner coordinates idempotent run lifecycle (ensure/claim), loads context, compiles and invokes the cadence graph with PostgreSQL checkpointer (using stable run ID for thread), and records succeeded/failed only after graph completion (or on error).
- `workflows/graphs.py`: cadence-specific graph builders wired to the ModelGateway.
- `workflows/state.py`: workflow state contracts.

### API / Delivery

- `api/app.py`: FastAPI application factory with lifespan that materializes runtime + runner into app.state. Exposes:
  - `GET /healthz`: process liveness.
  - `GET /readyz`: database connectivity + current vs expected Alembic revision (503 when not ready).
  - `POST /workflows/trigger`: accepts cadence + covered interval; returns durable run (id, status, idempotency_key) using the runner.
  - `GET /briefs`: placeholder.
- `api/readiness.py`: `check_readiness` implementation and a CLI entrypoint (`python -m analyst_engine.api.readiness`) used by scheduler container healthcheck.

### Integrations

ModelGateway supports dashscope (default) or openrouter (selected by MODEL_PROVIDER at application runtime). OpenRouter uses the OpenAI-compatible chat completions endpoint with configurable frontier and batch-summary model aliases (plus fallbacks). LangSmith tracing is opt-in. SearXNG provides search. Provider selection and keys are supplied directly to the process (Compose does not forward MODEL_PROVIDER/OPENROUTER_*).

## Data Flow

Startup and operation:

1. Compose creates or reuses the PostgreSQL and SearXNG named volumes.
2. PostgreSQL and SearXNG report their own health checks.
3. Compose starts `app` only after both dependencies are healthy.
4. `main` selects mode from `APP_PROCESS_MODE` (default api) and creates the
   shared runtime bundle via `create_runtime`.
5. API mode: lifespan creates a `WorkflowRunner` and stores it with the runtime
   in app state. `/readyz` runs a live DB connectivity check + compares
   `alembic_version` against the expected head from Alembic scripts; returns 503
   with component status when not ready. Trigger requests delegate to the runner
   which ensures a `WorkflowRun`, claims it, invokes the compiled checkpointed
   graph (thread_id = run ID), then updates the run to succeeded or failed.
6. Scheduler mode: creates the same runtime + runner, registers cadence jobs,
   and runs them; each job follows the same runner path producing durable runs.
7. On shutdown the runtime bundle disposes the engine exactly once.

## Background Jobs

Scheduler mode (APP_PROCESS_MODE=scheduler) runs APScheduler (AsyncIOScheduler)
and registers daily, weekly, and monthly cadence jobs. Jobs are idempotent via
the WorkflowRunner: duplicate triggers for the same interval return the existing
terminal or running run without creating a second row. The runner drives
checkpointed graph execution using the workflow run ID as the stable correlation
and checkpoint thread identifier. Success is recorded only after graph
invocation completes.

## External Integrations

### Local external services

| Dependency | Configuration | Failure behavior | Test strategy |
| --- | --- | --- | --- |
| PostgreSQL 16 + pgvector | Non-empty `POSTGRES_PASSWORD`, `POSTGRES_*`, and `DATABASE_URL` environment variables | Compose refuses configuration without the password; app startup is then gated on health (readiness 503) | Compose topology is structurally tested; integration tests use Testcontainers or the CI Postgres service. |
| SearXNG | Non-empty `SEARXNG_SECRET_KEY` and `SEARXNG_PUBLIC_BASE_URL` environment variables | Compose refuses configuration without the secret; app startup is then gated on health | Compose topology is structurally tested; no live search runs in routine tests. |

### Model providers

Application runtime configuration (via environment variables or .env loaded by Settings; Compose does not currently forward MODEL_PROVIDER or OPENROUTER_* variables — only APP_PROCESS_MODE, DASHSCOPE_*, DATABASE_URL, LANGSMITH_*, and SEARXNG_BASE_URL are declared in compose.yaml environment for the app service).

| Provider | Selection | Notes |
| --- | --- | --- |
| DashScope | `MODEL_PROVIDER=dashscope` (default) or unset | OpenAI-compatible; key and base URL required for live calls. |
| OpenRouter | `MODEL_PROVIDER=openrouter` + `OPENROUTER_API_KEY` etc. | OpenAI-compatible; configurable `OPENROUTER_FRONTIER_MODEL` and `OPENROUTER_BATCH_SUMMARY_MODEL` (with documented alternatives). Routine tests use mocked transport; live smoke is opt-in via env and never persists secrets. |

LangSmith is configured by environment (disabled by default). Adapters sit behind
the ModelGateway; provider selection lives in config and the factory.

## Invariants

- Local Compose declares exactly `app`, `postgres`, and `searxng` services.
- PostgreSQL and SearXNG state lives in named volumes and survives `docker
  compose down` without `--volumes`.
- The application never starts before PostgreSQL and SearXNG are healthy.
- Both API and scheduler modes receive a complete, non-None runtime dependency
  bundle (engine, sessions, gateway, checkpointer factory).
- A workflow run cannot transition to succeeded unless its graph invocation
  completed; duplicate triggers for the same idempotency key never create
  additional rows.
- Secrets are supplied through environment variables and are not committed to
  Compose settings or application source; the Compose secrets have no fallback
  values.
- `SEARXNG_SECRET_KEY` is written only when an empty `searxng_config` volume is
  initialized. Changing it later does not replace the persisted SearXNG secret.
- Readiness returns only sanitized component status (no credentials or full
  exception bodies); 503 is used for not-ready.

## SearXNG Secret Lifecycle

The initial `SEARXNG_SECRET_KEY` is deliberately immutable for an existing
`searxng_config` volume. This prevents an ordinary restart or `.env` edit from
silently invalidating the SearXNG configuration. To rotate a secret, stop the
stack, remove **only** the SearXNG configuration volume, set the replacement
`SEARXNG_SECRET_KEY`, then start the stack again. PostgreSQL data is unaffected:

```bash
docker compose down
docker volume rm analyst-engine_searxng_config
docker compose up --build --wait
```

Use `docker compose volume ls` to confirm the actual Compose project prefix if
the stack is started with a custom project name. This procedure resets SearXNG
configuration to the tracked template; reapply any local SearXNG settings after
the restart.
