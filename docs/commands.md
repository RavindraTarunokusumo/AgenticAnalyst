# Commands Reference

## Setup

(Define environment activation and dependency installation once the stack is chosen.)

Generic examples:

```bash
# Python example
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Windows PowerShell:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

## Development Server

(Replace with the actual project command once defined.)

```bash
# python main.py
# npm run dev
# cargo run
# etc.
```

## Testing

```bash
# pytest
# npm test
# cargo test
```

## Lint and Format

(Adapt to actual tools.)

```bash
# ruff check . --fix && ruff format .
# eslint . && prettier --write .
```

## Database (once applicable)

Initialize:

```bash
# python scripts/init_db.py
```

Seed local data:

```bash
# python scripts/seed_mock_db.py
```

Reset local data:

```bash
# python scripts/reset_db.py
```

## Logs

```bash
# tail -f logs/*.log
```

## Environment Variables

List required variables here as they are introduced:

```
APP_ENV=development
DATABASE_URL=
API_KEY=
```

Never commit real secrets.

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
