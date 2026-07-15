# Commands Reference

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- Python 3.12 (managed by uv via `.python-version`)

## Setup

Install dependencies and create the local virtual environment:

```bash
uv sync
```

Copy the environment template and supply local values (never commit `.env`):

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Before starting Compose, set non-empty `POSTGRES_PASSWORD` and
`SEARXNG_SECRET_KEY` values in `.env`. Compose deliberately refuses to start
without them. Set `DATABASE_URL` to the corresponding `postgres` hostname URL
before using later application tasks.

Activate the project environment (optional; `uv run` works without activation):

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## Routine Verification

Run the full local quality gate sequence from the repository root:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## Testing

Run all tests with coverage:

```bash
uv run pytest
```

Run a single test file:

```bash
uv run pytest tests/test_config.py
```

Run a single test by name:

```bash
uv run pytest -k "rejects_missing_dashscope_api_key"
```

Stop on the first failure:

```bash
uv run pytest -x
```

## Lint and Format

Check formatting:

```bash
uv run ruff format --check .
```

Apply formatting:

```bash
uv run ruff format .
```

Lint:

```bash
uv run ruff check .
```

Lint with auto-fix:

```bash
uv run ruff check . --fix
```

Type check:

```bash
uv run mypy src tests
```

## Pre-commit Hooks

Install hooks once per clone:

```bash
uv run pre-commit install
```

Run all hooks against the working tree:

```bash
uv run pre-commit run --all-files
```

## Development Server

Migrations must be applied before app readiness.

Fresh start (new volume):

```bash
docker compose build app
docker compose up -d --wait postgres searxng
docker compose run --rm --no-deps --entrypoint uv app run alembic upgrade head
docker compose up -d --wait app
```

For an existing database, run `uv run alembic upgrade head` for direct local execution or the same Compose entrypoint-override migration command before starting/restarting app.

The app now supports two modes from the same image:

- API (default): `uvicorn` FastAPI server exposing health, readiness, manual triggers and read-only briefing endpoints.
- Scheduler: APScheduler that registers daily/weekly/monthly jobs (idempotent).

```bash
APP_PROCESS_MODE=scheduler docker compose up -d --wait app
```

On Windows PowerShell:

```powershell
$env:APP_PROCESS_MODE = "scheduler"
docker compose up -d --wait app
Remove-Item Env:APP_PROCESS_MODE
```

The application image installs Playwright Chromium during its build so future
Crawl4AI ingestion can use the same image without a browser-install step.

## Frontend (Brief Viewer)

Prerequisites: Node version pinned in `frontend/.nvmrc`.

Install dependencies:

```bash
cd frontend && npm ci
```

Local dev server (proxies API calls to a separately-running backend):

```bash
cd frontend && npm run dev
```

Build the production bundle (outputs to `frontend/dist/`, gitignored):

```bash
cd frontend && npm run build
```

Lint:

```bash
cd frontend && npm run lint
```

`npm run build` also runs `tsc -b` as a type-check gate. A fresh checkout with
no frontend build yet run still serves a placeholder at `/ui/`
(`src/analyst_engine/api/static/index.html`, committed) rather than 404ing;
run `npm run build` to replace it with the real SPA. Docker images always
build the real frontend via the `frontend-build` stage - the placeholder only
matters for direct (non-Docker) local backend runs.

## Database

The Compose stack starts PostgreSQL 16 with pgvector. Migrations are managed by
Alembic. The initial migration creates the core analytical tables, `workflow_run`,
and the LangGraph checkpoint tables. Routine tests and Compose health use the
current head revision. Migration tests cover upgrade and (where provided)
downgrade paths. Use `alembic` commands (via the project's env) for local
revision management.

## Logs

Follow all local-service logs:

```bash
docker compose logs --follow app postgres searxng
```

Stop the stack while retaining its named volumes:

```bash
docker compose down
```

Reset all local PostgreSQL and SearXNG state (destructive):

```bash
docker compose down --volumes --remove-orphans
```

Rotate only the persisted SearXNG secret while retaining PostgreSQL data:

```bash
docker compose down
docker volume rm analyst-engine_searxng_config
# Set a replacement SEARXNG_SECRET_KEY in .env before restarting.
docker compose up --build --wait
```

The SearXNG bootstrap writes `SEARXNG_SECRET_KEY` only when the configuration
volume is empty. Editing the variable then restarting leaves the existing
secret unchanged. With a custom Compose project name, use `docker compose
volume ls` to identify the corresponding SearXNG configuration volume.

Inspect service health and startup ordering:

```bash
docker compose ps
```

## Environment Variables

Required and optional settings are documented in `.env.example`. Application runtime configuration (MODEL_PROVIDER, provider keys, etc.) is read directly by the process via Settings (pydantic-settings). For direct non-Compose execution, provide the variables in the runtime environment of the process. Current compose.yaml forwards only APP_PROCESS_MODE, DASHSCOPE_*, DATABASE_URL, LANGSMITH_*, SEARXNG_BASE_URL (and requires POSTGRES_* / SEARXNG_SECRET_KEY for other services). MODEL_PROVIDER and OPENROUTER_* are not forwarded by Compose; to use OpenRouter with Compose provide them via a user-supplied override that explicitly adds `environment:` or `env_file:` for the app service. The RSS ingestion/batching/pipeline settings (feed timeouts, size limits, similarity threshold, etc. - see `.env.example`) all have working defaults and follow the same non-forwarded, override-if-needed pattern.

At minimum, runtime startup requires a database URL and provider credentials (depending on MODEL_PROVIDER):

```
MODEL_PROVIDER=dashscope   # or openrouter
DASHSCOPE_API_KEY=...      # when using dashscope (default)
DASHSCOPE_BASE_URL=...
# or for OpenRouter:
# OPENROUTER_API_KEY=...
# OPENROUTER_FRONTIER_MODEL=...
# OPENROUTER_BATCH_SUMMARY_MODEL=...
POSTGRES_DB=analyst_engine
POSTGRES_USER=analyst_engine
POSTGRES_PASSWORD=<local-password>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@postgres:5432/analyst_engine
SEARXNG_SECRET_KEY=<local-secret>
SEARXNG_PUBLIC_BASE_URL=http://localhost:8080/
APP_PROCESS_MODE=api       # or scheduler
```

LangSmith (opt-in), scheduler mode, OpenRouter model aliases, and temporal evaluation settings are documented in `.env.example`. The /readyz endpoint and container health checks require the database to be reachable with migrations at the expected head. Never commit real secrets.

## Git Notes

Add a structured note for the latest commit:

```bash
git log -1 --format="%H"
git notes add -m "Task: <task name>
Summary: <brief what changed and why>
Docs: <docs paths updated, comma-separated, or N/A>
TODO: <TODO.md section/item reference>
Validation: <checks run>" <commit_hash>
```
