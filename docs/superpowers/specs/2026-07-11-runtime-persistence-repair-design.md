# Runtime and Persistence Repair Design

## Purpose

Make the existing AnalystEngine harness truthful and executable before ingestion
or briefing features are added. A workflow trigger must use real dependencies,
persist valid lifecycle transitions, expose accurate readiness, and fail visibly
when work cannot run.

This milestone also introduces an OpenAI-compatible OpenRouter configuration for
development and integration testing. The existing DashScope adapter boundary is
retained; provider selection belongs in application wiring rather than workflow
nodes.

## Scope

### Included

- Replace insert-only workflow-run persistence with explicit create and update
  operations that preserve a stable run ID.
- Define and enforce valid workflow lifecycle transitions: pending, running,
  succeeded, and failed.
- Wire the API and scheduler with a real session factory, model gateway, and
  PostgreSQL LangGraph checkpointer.
- Compile and invoke the cadence graph from `WorkflowRunner`; this milestone may
  use a minimal deterministic graph input, but may not report success without a
  completed graph invocation and durable output.
- Make liveness process-only and readiness dependent on database connectivity and
  the expected Alembic revision.
- Make container health use the HTTP readiness endpoint and expose the API port
  for local operation.
- Add OpenRouter settings using `OPENROUTER_API_KEY` from the untracked `.env`.
  No credential value is copied into source, fixtures, traces, logs, or records.
- Support configurable development model aliases with these defaults:
  - Frontier preference: `tencent/hy3:free`; allowed fallback
    `nvidia/nemotron-3-ultra-550b-a55b:free`.
  - Cheap-model preference: `cohere/north-mini-code:free`; allowed fallback
    `google/gemma-4-31b-it:free`.
- Exercise provider routing with mocked HTTP transport in routine tests. A live
  OpenRouter smoke test is opt-in and reads the key only from the environment.
- Enable and repair persistence, workflow, API, migration, and Compose readiness
  tests needed to prove this milestone.

### Excluded

- Source ingestion, crawling, feed parsing, article cleaning, and batching.
- Production batch summaries or production-quality daily/weekly/monthly prompts.
- Archive embedding generation, semantic retrieval, and UI work.
- Provider failover across multiple live services, billing controls, or model
  quality evaluation.
- Production authentication and multi-user authorization.

## Architecture

Application startup constructs a single runtime dependency bundle from validated
settings. The bundle owns the SQLAlchemy engine/session factory and constructs the
configured model gateway. API lifespan stores the bundle and runner in application
state. Scheduler mode constructs the same bundle before registering jobs.

`WorkflowRunner` owns orchestration and transaction boundaries. It first finds or
creates the interval run, transitions it to running, invokes the cadence graph with
the stable run ID and checkpointer thread configuration, and then records succeeded
or failed. A duplicate request returns a terminal run or resumes/reports the
existing non-terminal run according to its durable state; it never inserts a
second row for the same idempotency key.

Provider-specific HTTP behavior remains behind `ModelGateway`. OpenRouter uses the
OpenAI-compatible chat-completions API and validates structured responses through
the caller-provided Pydantic schema. Workflow code selects task kinds, not provider
model strings.

## Interfaces

### Settings

Consumes environment variables and produces validated provider, database, and
process configuration. OpenRouter configuration consists of base URL, secret API
key, frontier model, cheap model, timeout, and retry limit. Settings validation
must never reveal a secret value.

### Runtime dependency factory

Consumes `Settings` and produces the database engine, async session factory,
configured `ModelGateway`, and checkpointer context factory. It owns cleanup of
resources it creates.

### Workflow-run repository

- Create consumes a new pending `WorkflowRun` and produces the persisted record.
- Update consumes an existing run ID plus lifecycle fields and produces the
  updated record.
- Lookup consumes an idempotency key and produces zero or one durable run.

Updates must affect exactly one existing row. Missing rows and illegal transitions
are errors rather than implicit inserts.

### Readiness probe

Consumes the active engine and expected migration head. It produces a structured
ready/not-ready result. Database connection failure, missing schema, or migration
drift yields HTTP 503 without exposing connection details.

## Data Flow

1. Startup validates settings and creates runtime dependencies.
2. The API or scheduler asks `WorkflowRunner` to run a cadence interval.
3. The runner derives the idempotency key and loads or creates its durable run.
4. The run transitions to running in a committed transaction.
5. The runner compiles the appropriate graph with the PostgreSQL checkpointer and
   invokes it using the stable run ID as correlation/checkpoint identity.
6. Successful graph completion durably records outputs and then marks the run
   succeeded. Any exception records a redacted error summary and marks it failed.
7. The caller receives the durable final state; it never receives a fabricated
   success response.

## Error Handling

- Startup fails fast on missing required runtime configuration.
- Provider timeout and rate-limit failures retain their retryable classification.
- Invalid structured output is terminal for the invocation and cannot mutate
  analytical state.
- Database or checkpoint failures mark the run failed when a run record can still
  be updated; the original exception is chained for logs without secrets.
- Readiness failure returns a generic component status and HTTP 503.
- Opt-in live-provider tests skip when `OPENROUTER_API_KEY` is absent and never
  print request authorization headers or response bodies containing secrets.

## Testing

- Unit tests cover model routing, redaction, lifecycle validation, and provider
  response/error classification with mocked transport.
- Repository integration tests run against PostgreSQL/pgvector and prove create,
  update, idempotency, foreign-key lineage, and migration round trips.
- Workflow tests use a fake gateway and real test database/checkpointer to prove
  graph invocation, stable run identity, success, failure, and duplicate behavior.
- API tests prove liveness, readiness 200/503 transitions, trigger validation, and
  durable trigger responses.
- Compose verification proves the published port and HTTP readiness health check.
- One opt-in live OpenRouter smoke test may validate a minimal structured response
  using a configured free model. Routine CI remains deterministic and offline.

## Success Criteria

1. API and scheduler modes start with complete, non-`None` dependencies.
2. A workflow cannot become succeeded unless its graph invocation completes.
3. Workflow-run status changes update one row and preserve its ID and idempotency
   key.
4. Duplicate triggers do not create duplicate workflow runs.
5. `/readyz` returns 503 until PostgreSQL is reachable and migrations are current.
6. Compose exposes the API and gates application health on HTTP readiness.
7. Mocked tests prove OpenRouter routing for both frontier and cheap task classes.
8. An optional live smoke test can use `OPENROUTER_API_KEY` without persisting or
   displaying it.
9. Formatting, lint, strict type checking, routine tests, migrations, and Compose
   structure validation pass.

## Constraints

- Preserve the modular-monolith boundaries and repository-owned writes.
- Do not place provider SDK calls in domain, persistence, API routes, or workflow
  nodes.
- Do not commit `.env`, credentials, live provider output, or compatibility shims.
- Keep this milestone independently testable and avoid implementing ingestion,
  retrieval, or UI behavior early.
