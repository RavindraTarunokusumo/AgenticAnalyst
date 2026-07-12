# Runtime and Persistence Repair Implementation Plan

> **For agentic workers:** Implement one checked task at a time. Independent tasks
> may use isolated worktrees only where their files and dependencies do not overlap.

**Goal:** Make AnalystEngine workflow execution, persistence state, provider
wiring, and operational readiness truthful and executable before ingestion work
begins.

**Architecture:** A shared runtime factory constructs database, provider, and
checkpoint dependencies for both process modes. `WorkflowRunner` owns durable
lifecycle transitions and invokes checkpointed cadence graphs; the API reports
readiness from live database and migration checks. OpenRouter remains behind the
existing provider-neutral gateway.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/pgvector,
LangGraph PostgreSQL checkpoints, APScheduler, OpenAI-compatible OpenRouter API,
Pydantic v2, pytest, Testcontainers, Ruff, and mypy.

**Specification:**
`docs/superpowers/specs/2026-07-11-runtime-persistence-repair-design.md`

---

## Scope Boundaries

This plan repairs the runtime foundation only. It does not add source ingestion,
article batching, production brief prompts, retrieval, or UI behavior. The graph
invocation must be real and truthfully reflected in workflow state, but the later
ingestion milestone owns substantive article-to-brief behavior.

OpenRouter tests read `OPENROUTER_API_KEY` only for an explicitly selected live
smoke profile. Routine tests use mocked transport. The initial configured model
preferences are:

- Frontier: `tencent/hy3:free`, with
  `nvidia/nemotron-3-ultra-550b-a55b:free` as the configured alternative.
- Cheap: `cohere/north-mini-code:free`, with
  `google/gemma-4-31b-it:free` as the configured alternative.

Model identifiers remain environment-configurable because free-model availability
can change independently of the application.

## Target File Structure

| Path | Responsibility |
| --- | --- |
| `src/analyst_engine/config.py` | Provider selection and validated OpenRouter settings |
| `src/analyst_engine/models/openrouter.py` | OpenRouter-specific OpenAI-compatible gateway behavior |
| `src/analyst_engine/models/factory.py` | Select configured `ModelGateway` without leaking provider logic |
| `src/analyst_engine/runtime.py` | Construct and close shared engine, sessions, gateway, and checkpointer dependencies |
| `src/analyst_engine/persistence/repositories.py` | Explicit workflow-run creation, lookup, and lifecycle updates |
| `src/analyst_engine/workflows/runner.py` | Idempotent state machine and checkpointed graph invocation |
| `src/analyst_engine/workflows/graphs.py` | Stable run identity and cadence-correct graph selection |
| `src/analyst_engine/api/app.py` | Runtime lifespan, truthful readiness, and durable trigger results |
| `src/analyst_engine/main.py` | Shared runtime wiring for API and scheduler modes |
| `docker/app-entrypoint.sh`, `compose.yaml` | Published API and HTTP readiness health check |
| `tests/unit/` | Provider routing, lifecycle, and redaction tests |
| `tests/integration/` | Database, migration, workflow, and checkpoint verification |
| `tests/api/` | Liveness, readiness, and trigger contract tests |
| `tests/test_compose_structure.py` | Static process, port, and health-check contract |
| `.env.example` | Secret-free OpenRouter configuration contract |
| `docs/{architecture,database,patterns,testing,commands}.md` | Updated runtime and operator truth |

## Shared Interface Contract

### Provider configuration

**Consumes:** Provider name, `OPENROUTER_API_KEY`, OpenRouter base URL, frontier
model, cheap model, timeout, and retry count.

**Produces:** Validated settings with secret fields represented by `SecretStr` and
a provider choice that the gateway factory can exhaustively resolve.

### Gateway factory

**Consumes:** Validated `Settings`.

**Produces:** One concrete `ModelGateway`. OpenRouter maps frontier task kinds to
the configured frontier model and batch-summary/cheap structured tasks to the
configured cheap model. Embedding remains unsupported in this milestone and must
fail explicitly rather than being routed to chat completions.

### Runtime dependency bundle

**Consumes:** Validated `Settings`.

**Produces:** Async engine, async session factory, `ModelGateway`, and a
checkpointer context factory. Cleanup disposes owned database resources exactly
once.

### Workflow-run persistence

**Consumes:** A new run for creation, or an existing run ID plus target status and
status metadata for update.

**Produces:** A refreshed domain `WorkflowRun`. Create never overwrites; update
never inserts and must affect exactly one row.

### Workflow runner

**Consumes:** Cadence, covered interval, runtime dependencies, and optional
existing idempotent run.

**Produces:** A durable run whose terminal status reflects graph completion. Graph
configuration uses the workflow run ID for correlation and checkpoint threading.

### Readiness service

**Consumes:** Active engine and expected Alembic head.

**Produces:** Component readiness details suitable for API serialization. Failure
contains no database URL, credentials, or raw exception content.

## Build Order and Task Contract

### Task 1: Repair workflow-run persistence semantics

**Files:** `persistence/repositories.py`, relevant domain/ORM models, and focused
unit/integration tests.

**Consumes:** Existing `WorkflowRun`, `WorkflowStatus`, ORM schema, and async
transaction pattern.

**Produces:** Separate create and update repository operations, refreshed domain
mapping, transition validation, and deterministic missing/duplicate-row errors.

**Verification:** Prove stable IDs, pending→running→succeeded and
pending/running→failed paths, duplicate idempotency behavior, and rollback on
illegal transitions against PostgreSQL.

**Commit boundary:** Repository lifecycle behavior and its tests only.

### Task 2: Add OpenRouter configuration and adapter

**Files:** `config.py`, `.env.example`, `models/openrouter.py`,
`models/factory.py`, model exports, and provider unit tests.

**Consumes:** Existing `ModelGateway` contract and OpenAI-compatible request
shape.

**Produces:** Validated provider settings, configurable frontier/cheap model
routing, structured-output validation, classified provider errors, and a clear
unsupported-embedding error.

**Verification:** Mock transport tests assert endpoint, authorization handling,
model selection, correlation header, structured validation, retryable errors, and
secret redaction. The optional live smoke profile reads `OPENROUTER_API_KEY` and
skips when it is unavailable.

**Commit boundary:** Provider configuration/adapter and isolated tests/docs only.

### Task 3: Introduce the shared runtime dependency bundle

**Files:** New `runtime.py`, `api/app.py`, `main.py`, and runtime tests.

**Consumes:** `Settings`, gateway factory, SQLAlchemy engine/session helpers, and
checkpointer factory.

**Produces:** One construction path shared by API and scheduler modes, explicit
resource ownership, and cleanup behavior. No production path supplies `None`
dependencies.

**Verification:** Tests prove both modes receive complete dependencies, API mode
does not register schedules, scheduler mode registers once, and engine disposal
occurs at shutdown.

**Commit boundary:** Runtime composition and process-mode tests only.

### Task 4: Execute checkpointed graphs with truthful lifecycle state

**Files:** `workflows/runner.py`, `workflows/graphs.py`, workflow state/contracts,
and workflow tests.

**Consumes:** Runtime bundle, lifecycle repository, cadence graph builders, stable
run ID, and PostgreSQL checkpointer.

**Produces:** Cadence-correct graph compilation/invocation, stable correlation and
checkpoint identity, durable success/failure transitions, and idempotent duplicate
behavior. Monthly graph selection must not silently execute weekly cadence.

**Verification:** Fake-gateway tests cover success, malformed output, provider
failure, database failure, checkpoint resume, duplicate terminal runs, and
cadence-correct selection. A run cannot succeed when graph invocation is skipped
or fails.

**Commit boundary:** Runner/graph orchestration and its tests only.

### Task 5: Implement truthful readiness and container health

**Files:** `api/app.py`, a focused readiness module if needed,
`docker/app-entrypoint.sh`, `compose.yaml`, API tests, and Compose structure tests.

**Consumes:** Runtime engine, database connectivity, Alembic migration head, and
FastAPI lifespan state.

**Produces:** Process-only `/healthz`, dependency-aware `/readyz`, HTTP 503 on
database or migration failure, published API port, and container health based on
the readiness endpoint.

**Verification:** ASGI tests cover ready/not-ready transitions and redacted errors;
Compose tests assert port publication, HTTP health check, and removal of the early
file readiness marker.

**Commit boundary:** Readiness and container health behavior only.

### Task 6: Enable the milestone integration and API suite

**Files:** `tests/integration/test_persistence.py`, new workflow/API test modules,
shared fixtures, pytest configuration, and CI workflow where required.

**Consumes:** Completed repository, runtime, workflow, readiness, migration, and
Compose interfaces.

**Produces:** Executable PostgreSQL/pgvector integration tests with valid source
lineage, migration round-trip coverage, checkpoint verification, and API trigger
coverage. Docker-dependent tests use capability-based skipping instead of a
module-wide unconditional skip.

**Verification:** Focused suites pass with Docker; routine offline suites pass
without live provider calls; CI selection actually exercises the database service
it provisions.

**Commit boundary:** Test harness and CI selection changes only.

### Task 7: Reconcile documentation and run final gates

**Files:** Core technical docs, changelog, active TODO/archive records, and any
operator examples affected by the final implementation.

**Consumes:** Implemented commands, environment contract, process behavior,
readiness semantics, and verified test results.

**Produces:** Documentation matching actual behavior, completed TODO references
tagged with their commits, and a review-ready change set.

**Verification:** Run formatting, lint, strict type checking, full routine tests,
Docker integration tests, migration upgrade/downgrade/upgrade, Compose structure,
and an optional credentialed OpenRouter smoke test. Review the full diff and use
GitNexus change detection if an index becomes available.

**Commit boundary:** Documentation and work-tracking reconciliation only.

## Cross-Task Build Dependencies

1. Task 1 lands first because the runner contract depends on update semantics.
2. Task 2 can be implemented independently of Task 1 in an isolated worktree.
3. Task 3 consumes Task 2's gateway factory and therefore lands after Task 2.
4. Task 4 consumes Tasks 1 and 3.
5. Task 5 consumes Task 3 but may otherwise proceed independently of Task 4.
6. Task 6 follows Tasks 1–5 so it can validate the integrated system.
7. Task 7 is last and records only verified behavior.

## Risks and Controls

| Risk | Control |
| --- | --- |
| Free OpenRouter model identifiers disappear or change behavior | Keep identifiers configurable, mock routine tests, and treat live smoke as opt-in evidence rather than CI truth. |
| Existing workflow schema cannot express transition metadata cleanly | Prefer a focused migration over encoding lifecycle state in error/checkpoint strings. |
| Checkpointer and application transactions imply false atomicity | Document and test the ordering explicitly; never mark success until graph and analytical writes complete. |
| Duplicate scheduler/manual triggers race | Enforce database uniqueness and handle the insert race by reloading the winning idempotent run. |
| Readiness reveals infrastructure details | Return component-level status only and keep raw exceptions in redacted internal logs. |
| Integration tests remain silently skipped | Use explicit Docker capability detection and make CI invoke the integration marker against its PostgreSQL service. |
| Runtime factory becomes a service locator | Keep a small typed bundle with explicit fields and construction/cleanup only. |

## Plan Self-Review

- **Specification coverage:** Tasks 1–7 cover every included requirement and keep
  ingestion, retrieval, and UI outside the milestone.
- **Interface consistency:** The stable workflow run ID flows from repository
  creation through runner correlation, checkpoint configuration, graph output,
  and terminal update.
- **Secret safety:** Only the `OPENROUTER_API_KEY` variable name appears in tracked
  files. Mock transport is the routine test path.
- **Scope check:** Each task has one commit boundary and a testable output. Provider
  work can proceed independently; integrated workflow work waits for persistence
  and runtime composition.
