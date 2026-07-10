# Documentation Index

Use this file as the second layer after `AGENTS.md`. It points to deeper docs without repeating them.

## Core Docs

- [agent-harness.md](agent-harness.md): agent-facing documentation structure and harness rules
- [architecture.md](architecture.md): system design, module boundaries, entry points, request/data flow
- [database.md](database.md): schema, persistence model, migration rules
- [patterns.md](patterns.md): durable coding and state-management rules
- [testing.md](testing.md): test execution, fixtures, validation workflow
- [commands.md](commands.md): common local commands
- [changelog.md](changelog.md): notable behavior and architecture changes
- [insights.md](insights.md): session lessons and reusable workflow observations

## Module Docs

Add module-specific docs here as the codebase grows:

- [utils/](utils/)

## Repo Areas

Document key repo areas here:

- `src/` or equivalent: application source
- `tests/`: test suite
- `scripts/`: local automation scripts
- `TODO.md`: active work only
- `docs/iterations/archive/`: completed TODO archive

## Fast Path By Task

- Changing app behavior: read `architecture.md`, then relevant module docs
- Changing persistence: read `database.md` and `patterns.md`
- Changing tests: read `testing.md`
- Preparing for review: read `AGENTS.md`, `testing.md`, and PR template
- Adding agent workflow: read `agent-harness.md`

## Core Invariants

List project-specific invariants here.

Examples:
- State must be keyed by stable IDs, not display names.
- External services must be mocked in tests.
- Runtime secrets must not be logged.
- User-facing behavior changes require docs and tests.
