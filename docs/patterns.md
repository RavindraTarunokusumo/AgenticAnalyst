# Key Patterns

## Identifier Pattern

Document the difference between internal IDs, display names, symbols, slugs, or external IDs.

Rules:
- Use stable IDs for internal state.
- Use display names only for UI.
- Store external IDs separately.

## State Pattern

Document how runtime state is shaped, stored, cached, and invalidated.

## Snapshot Pattern

If mutable configuration affects long-running operations, snapshot the config at operation start.

Purpose:
- preserve reproducibility
- avoid mid-operation config drift
- improve auditability

## Persistence Pattern

Document transaction/session rules.

Examples:
- use context-managed sessions
- rollback on failure
- keep writes atomic
- avoid direct writes outside persistence helpers

## External Side-Effect Pattern

External operations should be isolated behind service or broker layers.

Rules:
- no raw external calls from random modules
- queue or wrap dangerous side effects
- log outcomes
- test with mocks

## Code Style

- Comments should be sparse and useful.
- Prefer clear names.
- Avoid clever abstractions.
- Delete dead code.
- Do not add compatibility shims unless required.
- Keep helpers only when they reduce real duplication or complexity.

## Anti-Patterns

- hidden global state
- broad exception swallowing
- untested external calls
- unexplained background jobs
- docs that duplicate code instead of explaining behavior
