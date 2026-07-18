# Agentic Analyst Technical Harness Implementation Plan

> **For agentic workers:** Follow the repository workflow and execute one checked task at a time. Delegated implementation requires explicit user authorization; otherwise implement inline. This is a lightweight contract: regenerate commands and code locally rather than copying code from this document.

**Goal:** Build a reproducible local-first Python harness for durable, observable, Qwen-powered briefing workflows before feature-specific ingestion logic begins.

**Architecture:** A Python modular monolith exposes a small FastAPI delivery surface and runs LangGraph workflows using PostgreSQL/pgvector as the system of record. Docker Compose supplies the application, PostgreSQL, and SearXNG. Provider calls and LangSmith tracing remain behind narrow adapters; daily, weekly, and monthly workflows consume persisted batch summaries and produce a brief plus a proposed Narrative State update.

**Tech Stack:** Python 3.12; uv; FastAPI/Uvicorn; LangGraph; DashScope OpenAI-compatible API; Pydantic v2; SQLAlchemy 2/Alembic/asyncpg/pgvector; APScheduler; PostgreSQL 16 + pgvector; SearXNG; feedparser/Crawl4AI/Playwright; LangSmith; pytest/testcontainers; Ruff/mypy/pre-commit; Docker Compose.

---

## Scope and firm boundaries

- Use DashScope's configured OpenAI-compatible endpoint and route task kinds to `qwen3.5-flash`, `qwen3.7-max`, and `text-embedding-v4` exactly as defined in the approved design.
- Implement Daily, Weekly, and Monthly Brief outputs and a proposed Narrative State update at each cadence.
- Persist article metadata, article batches, batch summaries, briefs, Narrative State versions, workflow runs, and embeddings. Do not add `claim_event`, claim candidates, an event index, a contradiction graph, Redis, Celery, or a separate vector database.
- Keep all live provider, web, SearXNG, and LangSmith calls disabled in routine tests. The temporal-holdout evaluation is explicit, credentialed, and outside pull-request CI.
- Each task lands in a separate commit after the full configured quality suite passes. Update `TODO.md` before each implementation task and attach a git note to every commit.

## Target file structure

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock` | Python version, runtime/dev dependencies, tool configuration, locked resolution |
| `.env.example`, `.gitignore`, `.pre-commit-config.yaml` | Safe local configuration contract and developer hooks |
| `Dockerfile`, `compose.yaml`, `searxng/settings.yml` | Repeatable local application image and three-service topology |
| `src/analyst_engine/config.py` | Typed environment settings and model/scheduling/observability configuration |
| `src/analyst_engine/domain/models.py` | Pydantic contracts shared across workflows, persistence, and delivery |
| `src/analyst_engine/persistence/{engine,models,repositories,checkpoints}.py` | SQLAlchemy engine/session factory, ORM schema, repositories, LangGraph checkpoint adapter |
| `alembic/`, `alembic.ini` | Deterministic schema migration environment and initial migration |
| `src/analyst_engine/models/{gateway,dashscope}.py` | Provider-neutral model protocol and DashScope implementation |
| `src/analyst_engine/observability/langsmith.py` | Trace configuration, correlation metadata, redaction policy |
| `src/analyst_engine/workflows/{state,graphs}.py` | Cadence state, daily/weekly/monthly graph assembly, validated graph outputs |
| `src/analyst_engine/scheduling.py` | Single-process APScheduler registration and idempotent interval triggers |
| `src/analyst_engine/api/{app,routes}.py`, `src/analyst_engine/main.py` | ASGI application, health/readiness and manual workflow-trigger interfaces |
| `tests/{unit,integration,workflow,api,evaluation}/` | Deterministic test layers and opt-in temporal-holdout evaluation harness |
| `docs/{architecture,database,patterns,testing,commands,agent-harness}.md` | Final operational and technical source of truth |
| `.github/workflows/ci.yml` | Fresh-environment formatting, lint, typing, tests, migration, and Compose-smoke validation |

## Shared interface contract

| Contract | Consumes | Produces |
| --- | --- | --- |
| `Settings` | Environment variables | Validated `Settings`; startup fails with a field-specific configuration error |
| `ArticleMetadata` | Source capture fields | Immutable canonical URL, publisher, author (nullable), published/ingested times, source ID, hash, language |
| `ArticleBatch` | 3–5 ordered `ArticleMetadata` IDs and grouping configuration | Persistable batch identity, selected title/content embedding method, model, threshold, run ID |
| `BatchSummary` | `ArticleBatch`, cleaned article content, citations, Flash result | Validated cohesive summary, source notes, entities/topics, article/excerpt citations |
| `ModelGateway.generate` | `ModelTask`, messages, expected Pydantic schema, correlation ID | Validated structured result and usage metadata; classified provider error |
| `BriefGenerationInput` | Cadence, cited batch summaries, prior briefs, Narrative State, run ID | Input visible to one frontier workflow invocation |
| `BriefGenerationOutput` | Frontier structured response | `Brief` plus proposed `NarrativeStateVersion`, each with batch-summary/article citations |
| `WorkflowRunner.run` | Cadence, covered interval, idempotency key | Existing or newly persisted `WorkflowRun` and checkpointed graph result |
| `TemporalReplay.run` | Frozen corpus, virtual schedule, evaluation profile | Auditable report and trace/run identifiers; no real-time wait |

## Build order and task contract

### Task 1: Establish the Python project and local quality baseline

**Files:** Create the package root, `pyproject.toml`, `.python-version`, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, and baseline test directories. Modify `docs/commands.md` and `docs/testing.md`.

**Consumes:** Approved stack and secret-handling constraints.

**Produces:** A `uv`-managed Python 3.12 project; Ruff formatting/linting, strict mypy for `src/analyst_engine`, pytest/asyncio/coverage configuration, pre-commit hooks, and documented commands. `.env.example` names DashScope, database, LangSmith, scheduling, and evaluation settings without values.

**Verification:** Configuration/import smoke tests pass; malformed required settings produce deterministic errors; formatter, linter, type checker, and test runner operate from a fresh environment. Confirm no real key can be tracked by git.

**Commit boundary:** Tooling baseline and its tests/docs only.

### Task 2: Provide the local Compose environment

**Files:** Create `Dockerfile`, `compose.yaml`, `searxng/settings.yml`, application container entrypoint, and Compose-focused tests or smoke script. Modify `.env.example`, `docs/commands.md`, and `docs/architecture.md`.

**Consumes:** Settings contract from Task 1.

**Produces:** `app`, `postgres`, and `searxng` Compose services; PostgreSQL 16 + pgvector and SearXNG named volumes; health checks and startup ordering; application image with Crawl4AI/Playwright browser prerequisites. The app has distinct API and scheduler modes from one image; only the scheduler mode registers jobs.

**Verification:** A clean Compose start reaches health checks; database and SearXNG configuration persist across restart; no application process starts a scheduler in API mode.

**Commit boundary:** Container and Compose topology only.

### Task 3: Implement durable domain and persistence foundations

**Files:** Create domain models; SQLAlchemy engine/session, ORM models, repositories, checkpoint integration; Alembic environment and initial migration; unit/integration persistence tests. Modify `docs/database.md` and `docs/patterns.md`.

**Consumes:** `Settings`; shared interface contracts; PostgreSQL/pgvector from Task 2.

**Produces:** Repository operations for sources, immutable article metadata/content, article batches, batch summaries, briefs, Narrative State versions, expectations, embeddings, and workflow runs. All write methods accept a transaction/session; `WorkflowRunner.run` can locate an existing run from its cadence/interval idempotency key. LangGraph checkpoints use the same PostgreSQL database. There is no claim-event schema.

**Verification:** Testcontainers PostgreSQL with pgvector applies migrations from blank state; unique URL and idempotency constraints work; a citation path from a Brief/Narrative proposal to a BatchSummary to source ArticleMetadata is valid; migration downgrade/upgrade policy is tested where supported.

**Commit boundary:** Schema, migrations, repositories, and persistence tests only.

### Task 4: Add provider and observability adapters

**Files:** Create `models/gateway.py`, `models/dashscope.py`, `observability/langsmith.py`, provider/trace tests. Modify configuration, `.env.example`, `docs/architecture.md`, and `docs/testing.md`.

**Consumes:** `Settings`, Pydantic output contracts, correlation/run IDs.

**Produces:** A provider-neutral gateway selecting Flash for batch summaries, Max for frontier synthesis, and text-embedding-v4 for retrieval. The DashScope adapter owns base URL, auth, timeout, retry/error categorization, and usage collection. LangSmith initialization is opt-in, redacts secrets/article body excerpts, and enriches traces with run ID, checkpoint ID, cadence, model, and operation.

**Verification:** HTTP-transport contract tests assert endpoint/model/request shape without a real key; malformed structured responses are rejected before persistence; trace-enabled and trace-disabled configurations work; LangSmith failures are non-fatal and are recorded as degraded observability.

**Commit boundary:** Model and tracing adapters plus isolated tests/docs only.

### Task 5: Assemble checkpointed cadence workflows and scheduling

**Files:** Create workflow state/graphs and scheduler module; create workflow tests. Modify persistence integration, configuration, and architecture/pattern documentation.

**Consumes:** Repositories, checkpoint adapter, `ModelGateway`, `BatchSummary`, existing Briefs, and prior Narrative State.

**Produces:** Daily graph: cited batch summaries → `Daily Brief` + proposed `NarrativeStateVersion`; weekly graph: recent Daily Briefs/retrieval → `Weekly Brief` + proposal; monthly graph: broad archive retrieval → `Monthly Brief` + proposal. Each graph validates output citations, writes atomically, saves a checkpoint, and leaves a failed run resumable. APScheduler invokes exactly one idempotent run per cadence/covered interval.

**Verification:** Fake-gateway workflow tests cover success, invalid output, classified retry, checkpoint resume, duplicate schedule call, citation rejection, and all three cadence output contracts. A process-mode test confirms only the scheduler process registers jobs.

**Commit boundary:** Graphs, scheduling, and workflow tests only.

### Task 6: Deliver the minimal API and operational readiness surface

**Files:** Create FastAPI app/routes/main entrypoint and API tests. Modify Compose entrypoint, commands, architecture, and agent-harness documentation.

**Consumes:** Settings, database readiness, `WorkflowRunner`, and workflow run/brief repositories.

**Produces:** Liveness/readiness endpoints; read-only retrieval of persisted briefs and Narrative State versions; authenticated manual trigger endpoint accepting cadence and covered interval, returning the existing/new workflow run. Readiness is false until migrations and database connectivity succeed. Routes do not embed LangGraph or provider logic.

**Verification:** ASGI tests cover health/readiness transitions, invalid trigger input, idempotent trigger response, and read-only serialization. Compose smoke test exercises readiness against migrated PostgreSQL with tracing disabled.

**Commit boundary:** API/delivery layer and operational docs only.

### Task 7: Build deterministic test fixtures and the opt-in temporal-holdout evaluation

**Files:** Create fixture factories, model fakes, frozen-corpus manifest format, virtual-clock replay runner, evaluation report schema, and evaluation tests. Modify `docs/testing.md`, `docs/commands.md`, and LangSmith configuration documentation.

**Consumes:** Cadence workflows, repository schema, virtual time, frozen article corpus, and the `qwen3.7-max-preview` evaluation profile with documented cut-off date.

**Produces:** Routine test fixtures with no external calls and an explicit evaluation entrypoint that runs a one-month post-cut-off corpus in accelerated succession. The replay advances virtual time between publication intervals, invokes Daily/Weekly/Monthly workflows at virtual boundaries, preserves prompt/config/model/cut-off/trace metadata, and targets completion in under one hour.

**Verification:** Offline tests prove future-dated articles cannot become visible before their virtual publication time and no scheduler wait is used. Credentialed manual evaluation validates run/report generation, citation visibility, checkpoint/version chains, and completion timing. It is excluded from pre-commit and pull-request CI.

**Commit boundary:** Evaluation harness, fixtures, and testing docs only.

### Task 8: Finalize operational documentation and CI

**Files:** Modify all core technical docs, `docs/index.md`, `docs/changelog.md`, and `.github/workflows/ci.yml`; add focused CI/config tests if required.

**Consumes:** Implemented commands, migration behavior, Compose topology, package/tool settings, and all test layers.

**Produces:** A consistent operator/developer guide for setup, environment variables, API/scheduler modes, migrations, routine quality gates, Compose smoke tests, and manual temporal replay. CI runs format, lint, type check, routine tests, migration validation, and Compose smoke tests on a fresh environment; it never runs the credentialed temporal evaluation.

**Verification:** Reconcile every acceptance criterion in the approved design to an implemented component and documented command. Run the complete quality suite and review the diff for configuration leakage, stale commands, and missing trailing newlines.

**Commit boundary:** Documentation and CI only.

## Test coverage map

| Requirement | Tasks that prove it |
| --- | --- |
| Reproducible Python/tooling and secret safety | 1 |
| Three-service local stack and persistence across restart | 2, 6 |
| PostgreSQL/pgvector, migrations, checkpoint persistence, citation lineage | 3, 5 |
| DashScope routing, structured output, error handling | 4, 5 |
| LangSmith correlation/redaction/non-fatal failure | 4 |
| Daily/weekly/monthly briefs and Narrative proposals | 5 |
| Single scheduler and idempotent runs | 2, 5 |
| API/readiness/manual runs | 6 |
| Under-one-hour accelerated, post-cut-off temporal evaluation | 7 |
| Fresh-environment automation and operator documentation | 8 |

## Risks and implementation controls

| Risk | Control |
| --- | --- |
| DashScope compatibility differs from OpenAI SDK behavior | Keep provider logic in one adapter and lock it behind HTTP contract tests before workflow work. |
| A LangGraph PostgreSQL checkpointer changes API/version | Pin and lock versions, test checkpoint resume against real PostgreSQL, and keep checkpoint access behind the persistence module. |
| Playwright/Crawl4AI makes the image slow or brittle | Build and validate the browser image in Task 2; do not make live crawling a test dependency. |
| Multiple processes register duplicate schedules | Separate API/scheduler modes and test scheduler registration directly. |
| Brief provenance is lost during synthesis | Require batch-summary/article citation IDs in every frontier output and reject invalid writes transactionally. |
| Temporal replay is slow, costly, or leaks future corpus data | Use an accelerated virtual clock, explicit evaluation profile, corpus visibility guard, dedicated credentials/project, and keep it out of CI. |

## Plan self-review

- **Spec coverage:** Tasks 1–8 cover the local Compose stack, package/toolchain, persistence, Qwen routing, LangSmith, LangGraph/checkpoints, scheduling, API readiness, test layers, and accelerated temporal evaluation. Deferred claim-event persistence is excluded throughout.
- **Contract consistency:** `BatchSummary` is the only Flash analytical artifact; all frontier outputs cite it and its source metadata. Daily, weekly, and monthly workflows all return a Brief plus a proposed Narrative State version.
- **Scope check:** This is one harness milestone with independent, sequentially integrable commits. Source-specific ingestion rules, UI, authentication policy, and claim-event extraction remain outside it.
