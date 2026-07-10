# System Architecture

## Entry Points

The local environment is defined in `compose.yaml` and contains exactly three
services:

- `app`: a single AnalystEngine image. `APP_PROCESS_MODE=api` is the default;
  `scheduler` selects the future scheduler process. At this harness stage the
  entrypoint only validates the mode and holds a healthy process: it does not
  load runtime settings, expose FastAPI routes, or register scheduled jobs.
- `postgres`: PostgreSQL 16 with pgvector, backed by the `postgres_data` named
  volume.
- `searxng`: self-hosted search, backed by the `searxng_config` named volume.
  Its settings template receives its required secret through the environment at
  first initialization; no real secret or fallback is committed. The bootstrap
  initializes the named configuration volume once, then preserves its secret
  and settings across restarts. SearXNG is available to the host at
  `http://localhost:8080` and to `app` at `http://searxng:8080`.

Compose waits for healthy PostgreSQL and SearXNG services before it starts the
application. The app's temporary file-based health check is replaced by API
readiness once migrations and the FastAPI surface exist.

The app image includes the direct Crawl4AI and Playwright dependencies and
installs Playwright Chromium at build time. This makes browser automation ready
for the later ingestion layer without turning it into a routine test dependency.

## Module Structure

### Core / Infrastructure

- `config.py`: typed Settings (pydantic-settings)
- `persistence/engine.py`: async SQLAlchemy engine + session_scope
- `persistence/checkpoints.py`: LangGraph AsyncPostgresSaver integration

### Domain

- `domain/models.py`: pure Pydantic contracts (Source, Article, BatchSummary, Brief, NarrativeStateVersion, ...). No infrastructure imports.

### Data / Persistence

- `persistence/models.py`: SQLAlchemy 2 ORM (mirrors migration schema, pgvector)
- `persistence/repositories.py`: session-scoped writes and lookups (idempotency, citation helpers)
- `alembic/`: sole schema evolution (initial migration covers app tables + LangGraph checkpoints; no claim_event)

### Services / Workflows

(Added in later tasks)

### API / Delivery

(Added in later tasks)

### Integrations

DashScope (via ModelGateway), LangSmith (opt-in tracing), SearXNG (search only).

## Data Flow

The initial local startup flow is:

1. Compose creates or reuses the PostgreSQL and SearXNG named volumes.
2. PostgreSQL and SearXNG report their own health checks.
3. Compose starts `app` only after both dependencies are healthy.
4. The app entrypoint validates `APP_PROCESS_MODE`, records its temporary
   readiness marker, and waits for the API/scheduler layers introduced later.

## Background Jobs

The scheduler mode is reserved for the future APScheduler process. It shares the
application image with API mode and registers no jobs in this Compose task.

## External Integrations

### Local external services

| Dependency | Configuration | Failure behavior | Test strategy |
| --- | --- | --- | --- |
| PostgreSQL 16 + pgvector | Non-empty `POSTGRES_PASSWORD`, `POSTGRES_*`, and `DATABASE_URL` environment variables | Compose refuses configuration without the password; app startup is then gated on health | Compose topology is structurally tested; live database tests arrive with persistence. |
| SearXNG | Non-empty `SEARXNG_SECRET_KEY` and `SEARXNG_PUBLIC_BASE_URL` environment variables | Compose refuses configuration without the secret; app startup is then gated on health | Compose topology is structurally tested; no live search runs in routine tests. |

DashScope and LangSmith remain configured by environment only, but their adapters
are introduced in later tasks.

## Invariants

- Local Compose declares exactly `app`, `postgres`, and `searxng` services.
- PostgreSQL and SearXNG state lives in named volumes and survives `docker
  compose down` without `--volumes`.
- The application never starts before PostgreSQL and SearXNG are healthy.
- Secrets are supplied through environment variables and are not committed to
  Compose settings or application source; the Compose secrets have no fallback
  values.
- `SEARXNG_SECRET_KEY` is written only when an empty `searxng_config` volume is
  initialized. Changing it later does not replace the persisted SearXNG secret.

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
