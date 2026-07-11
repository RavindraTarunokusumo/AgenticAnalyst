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

Start the local stack (PostgreSQL/pgvector + SearXNG + app):

```bash
docker compose up --build --wait
```

The app now supports two modes from the same image:

- API (default): `uvicorn` FastAPI server exposing health, readiness, manual triggers and read-only briefing endpoints.
- Scheduler: APScheduler that registers daily/weekly/monthly jobs (idempotent).

```bash
APP_PROCESS_MODE=scheduler docker compose up --build --wait
```

On Windows PowerShell:

```powershell
$env:APP_PROCESS_MODE = "scheduler"
docker compose up --build --wait
Remove-Item Env:APP_PROCESS_MODE
```

The application image installs Playwright Chromium during its build so future
Crawl4AI ingestion can use the same image without a browser-install step.

## Database

The Compose stack starts PostgreSQL 16 with pgvector. Database migrations are
introduced in a later harness task.

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

Required and optional settings are documented in `.env.example`. At minimum, runtime startup requires:

```
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
POSTGRES_DB=analyst_engine
POSTGRES_USER=analyst_engine
POSTGRES_PASSWORD=<local-password>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@postgres:5432/analyst_engine
SEARXNG_SECRET_KEY=<local-secret>
SEARXNG_PUBLIC_BASE_URL=http://localhost:8080/
```

LangSmith, scheduler mode, and temporal evaluation settings are also named in `.env.example`. Never commit real secrets.

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
