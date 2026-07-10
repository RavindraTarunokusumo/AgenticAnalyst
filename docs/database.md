# Database and Persistence

## Purpose

Document schema, state ownership, migrations, and persistence rules as they are defined.

## Storage Backend

(Describe the database or storage layer once chosen.)

## Core Tables / Collections

(For each table or collection, document once created.)

### `<name>`

Purpose:

Fields:
- `id`
- `created_at`
- `updated_at`

Relationships:

Notes:

## Migration Rules

- Migrations must be deterministic.
- Backward compatibility must be explicit.
- Data deletion must be intentional and documented.
- Tests must cover migration-sensitive behavior.

## State Ownership

Document which module owns each state transition.

## Persistence Invariants

Examples:
- Stable IDs are authoritative.
- Display names are not state keys.
- Writes must be atomic where consistency matters.
- External side effects must be auditable.
