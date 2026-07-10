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

The API and scheduler entrypoints are introduced in later harness tasks. No development server command is available yet.

## Database

Database initialization, migrations, and Compose services are introduced in later harness tasks.

## Logs

Application logging configuration is introduced with the API and workflow layers.

## Environment Variables

Required and optional settings are documented in `.env.example`. At minimum, runtime startup requires:

```
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
DATABASE_URL=
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
