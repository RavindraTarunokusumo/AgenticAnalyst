# AnalystEngine Technical Harness Design

**Status:** Approved design; pending user review of this document  
**Date:** 2026-07-10  
**Scope:** Local-first development and test harness only. Application features are out of scope.

## 1. Purpose and Constraints

This harness provides a repeatable foundation for a durable analytical-agent system before feature work begins. It must support asynchronous ingestion, durable LangGraph workflows, a versioned analytical memory, hybrid retrieval, scheduled jobs, and a reviewable local development experience.

The first deployment target is local Docker Compose. The design deliberately keeps a modular-monolith topology: API and scheduled worker execution share one deployable application initially. Redis, Celery, a separate vector database, and production infrastructure are explicitly deferred.

The only model provider is DashScope through its OpenAI-compatible endpoint:

`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`

Model assignments are fixed by responsibility:

| Responsibility | Model |
| --- | --- |
| Structured extraction, deduplication, relevance and low-cost classification | `qwen3.5-flash` |
| Daily/weekly synthesis and proposed Narrative State updates | `qwen3.7-max` |
| Archive embeddings | `text-embedding-v4` |

All credentials are supplied through environment variables. Secrets are neither committed, logged, nor baked into containers.

## 2. Chosen Architecture

### 2.1 Runtime and package management

- **Language/runtime:** Python 3.12.
- **Package manager:** `uv`, with a committed `uv.lock` once dependencies are introduced.
- **Application shape:** `src/analyst_engine/` modular monolith.
- **Configuration:** `pydantic-settings`, with typed, fail-fast settings loaded from environment variables.
- **Schemas:** Pydantic v2 models at every external and workflow boundary.

The initial package boundaries are `api`, `domain`, `ingestion`, `memory`, `retrieval`, `workflows`, `models`, `persistence`, and `observability`. A module may depend inward on `domain` contracts; domain code must not import FastAPI, SQLAlchemy, LangGraph, or provider SDKs.

### 2.2 Durable execution and delivery

- **HTTP delivery:** FastAPI, initially exposing health/readiness endpoints plus manual, authenticated workflow triggers and read-only briefing/narrative retrieval.
- **Workflow orchestration:** LangGraph, using PostgreSQL-backed checkpoints so a failed or interrupted graph can resume from its persisted state.
- **Scheduling:** APScheduler running in the application worker mode for daily, weekly, and monthly workflows. Only one scheduler instance is permitted in Compose.
- **Database access:** SQLAlchemy 2 async engine and Alembic migrations.

LangGraph nodes are narrow services rather than route handlers. Each node accepts and returns validated state, records a run correlation ID, and has idempotency keys for scheduled work.

### 2.3 Persistence and retrieval

PostgreSQL 16 plus pgvector is the single system of record. It persists LangGraph checkpoints, source/article records, structured claims/events, briefs, Narrative State versions, workflow runs, and embeddings. The archive embeds daily and weekly briefs—not raw articles—using `text-embedding-v4`; PostgreSQL metadata filters narrow candidates before vector ranking.

Initial persistence contracts:

| Record | Stable identity / required relationships |
| --- | --- |
| `source` | Stable source ID and normalized domain |
| `article` | Normalized URL fingerprint; source ID; immutable raw/cleaned provenance |
| `claim_event` | Article ID; time, entities, topics, reliability/source notes |
| `brief` | UUID; cadence (`daily`/`weekly`); covered interval; content; source references |
| `narrative_state_version` | UUID; parent version; created-by workflow run; structured state and change log |
| `prediction_expectation` | Narrative version; confidence; confirmation/falsification criteria; outcome status |
| `embedding` | Brief ID; model ID; vector; metadata filter columns |
| `workflow_run` | Run ID; graph/cadence; idempotency key; checkpoint reference; status and error summary |

Alembic is the sole schema-change mechanism. Migrations must be reversible where feasible and are exercised against a blank PostgreSQL container in CI.

### 2.4 Provider boundary and observability

An internal `ModelGateway` protocol hides OpenAI-compatible SDK calls. It consumes a typed task request (task kind, messages, output schema, correlation ID) and produces a validated result plus model-usage metadata. The DashScope adapter owns `DASHSCOPE_API_KEY`, base URL configuration, timeouts, retry classification, and model names. No LangGraph node calls a provider SDK directly.

LangSmith provides tracing for development and deployed runs. When enabled, it records LangGraph graph/node execution, model calls, retrieval/tool operations, latency, token/model usage, and errors. Every trace carries the workflow run ID, checkpoint/thread ID, cadence, and selected model. The harness must redact article body excerpts and all secrets from trace metadata. Tests disable remote tracing by default.

Required observability settings:

```text
LANGSMITH_TRACING=true|false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=analyst-engine-local
LANGSMITH_ENDPOINT=             # optional; LangSmith default when absent
```

## 3. Local Compose Topology

Compose contains exactly these initial services:

| Service | Responsibility | Persistent data |
| --- | --- | --- |
| `app` | FastAPI process or scheduler/worker process from the same image | No local application state |
| `postgres` | PostgreSQL 16 with pgvector | Named database volume |
| `searxng` | Self-hosted web-search backend | Named configuration volume |

The application image includes browser dependencies required by Crawl4AI and Playwright. Ingestion uses the ordered strategy RSS (`feedparser`), Crawl4AI, then Playwright; SearXNG is used only for the optional web-search mode. Compose health checks gate application start on PostgreSQL and SearXNG readiness. The local app reads a `.env` file that is gitignored; `.env.example` documents variable names only.

## 4. Packages and Developer Tooling

The planned production dependencies are LangGraph, LangChain OpenAI compatibility support (or the official OpenAI Python SDK at the adapter boundary), FastAPI, Uvicorn, Pydantic/Pydantic Settings, SQLAlchemy, Alembic, asyncpg, pgvector, APScheduler, httpx, feedparser, Crawl4AI, Playwright, and LangSmith. Dependency versions are resolved and frozen by `uv lock`; the design avoids hand-maintained requirements files.

Development dependencies are pytest, pytest-asyncio, pytest-cov, testcontainers, Ruff, mypy, pre-commit, and appropriate typed stubs. Docker Compose is the only local service prerequisite.

Quality gates are:

1. `ruff format --check .` and `ruff check .`
2. `mypy src tests` with strict typing for `src/analyst_engine`
3. `pytest` with coverage collection
4. Compose smoke test: health endpoints, migration on blank database, and disabled-tracing execution

Pre-commit runs formatting, linting, whitespace checks, and secret detection. CI runs the four gates on a fresh environment; external network, DashScope, and LangSmith are mocked or disabled in tests.

## 5. Test Strategy

Tests are organized as unit, persistence integration, workflow integration, and delivery/API tests. Unit tests use deterministic fake clocks, source fixtures, model gateway fakes, and HTTP transport mocks. Integration tests use Testcontainers PostgreSQL with pgvector and execute real Alembic migrations. Workflow tests validate resumption from a checkpoint, idempotent scheduled runs, structured-output rejection/retry, and versioned Narrative State transitions. API tests use FastAPI's ASGI transport.

No test contacts DashScope, LangSmith, source websites, or a public SearXNG instance. Contract tests verify the DashScope adapter sends the configured base URL and intended model identifier without exposing a real key.

## 6. Error Handling and Operational Rules

- Provider errors are classified into retryable and terminal categories; retries are bounded and recorded against the workflow run.
- A malformed model result never mutates Narrative State; the graph records a failed/proposed step and remains resumable.
- Scheduling is idempotent by cadence and covered time interval. A duplicate job returns the existing run rather than creating another brief.
- Source content remains immutable after capture; cleaning/extraction produces derived records with provenance links.
- Database migrations run before worker scheduling begins.
- LangSmith trace failures never fail a workflow; they are logged as observability degradation without secret values.

## 7. Acceptance Criteria for Harness Implementation

The harness is complete when:

1. A new developer can copy `.env.example`, supply a DashScope key, and start the local stack with one documented command.
2. PostgreSQL/pgvector, SearXNG, and the app pass Compose health checks; persisted data survives a restart.
3. A typed model gateway selects each specified Qwen model by task and rejects invalid structured output without persisting state changes.
4. LangGraph checkpoint persistence and a single APScheduler instance are demonstrably configured.
5. LangSmith tracing can be enabled with environment variables, includes correlation metadata, redacts configured sensitive content, and is off by default in tests.
6. Formatting, linting, strict type checking, unit/integration tests, and the Compose smoke test are documented and pass in a clean environment.
7. Architecture, persistence, patterns, commands, testing, and agent-harness documentation contain the final toolchain and commands.

## 8. Explicitly Deferred

Production hosting, a Redis/Celery queue, multi-worker distributed scheduling, graph/entity storage beyond relational links, user authentication/authorization policy, dashboards/metrics backends beyond LangSmith, and automated source-reliability scoring are future feature decisions. Their absence must not be hidden behind compatibility shims.
