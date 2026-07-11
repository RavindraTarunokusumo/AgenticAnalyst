# Database and Persistence

## Purpose

PostgreSQL 16 + pgvector is the single system of record for the local harness. It stores LangGraph checkpoints, source and article records, deterministic article batches, batch summaries (Flash), briefs, versioned Narrative State, expectations, embeddings of briefs, and workflow run metadata.

No claim_event, event fingerprinting, or contradiction graph exists in the initial harness (explicitly deferred).

## Storage Backend

- Engine: SQLAlchemy 2 async (asyncpg driver) for application paths.
- Migrations: Alembic (synchronous psycopg driver via env.py normalization of DATABASE_URL).
- Vector: pgvector extension; embeddings stored only for briefs (not raw articles).

Connection is supplied exclusively via `DATABASE_URL` (postgresql+asyncpg scheme). Startup and tests fail fast on misconfiguration.

## Core Tables

### source
Stable registered source.
- `id` (UUID PK)
- `stable_id` (unique)
- `name`, `normalized_domain`
- `created_at`

### article
Immutable captured content with provenance.
- `id` (UUID PK), `source_id` (FK), `url`, `url_fingerprint` (unique), title, author, published/ingested, language, hashes, `cleaned_content`
- Indexes on source and published_at.

### article_batch
Deterministic 3–5 article grouping.
- `id`, `article_ids` (array), grouping_method, embedding_model, threshold, grouping_run_id, created_at

### batch_summary
Flash model output over one batch (with citations).
- `id`, `batch_id` (FK), model/prompt_version, summary, source_notes, entities/topics (arrays), `citations` (JSONB), created_at

### brief
Cadence synthesis (daily/weekly/monthly).
- `id`, `cadence`, covered interval (unique per cadence+start+end), content, cited batch/article arrays, narrative_state_version_id, created_by_run_id, created_at

### narrative_state_version
Versioned analytical memory.
- `id`, `parent_id`, created_by_run_id, `state` (JSONB), `change_log` (array), created_at

### prediction_expectation
Falsifiable statements attached to a narrative version.
- `id`, narrative_version_id (FK), statement, confidence, confirmation/falsification criteria, outcome_status, created_at

### embedding
Archive vector for a brief (text-embedding-v4).
- `id`, `brief_id` (FK), model, `vector` (pgvector), metadata (JSONB filters), created_at

### workflow_run
Idempotent scheduled execution record.
- `id`, cadence, `idempotency_key` (unique), status, checkpoint_ref, error_summary, started/completed

### LangGraph checkpoint tables
`checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` (with task_path column). Managed via our initial migration; the async saver calls setup() which is a no-op after migration.

## Migration Rules

- Alembic is the sole mechanism.
- Initial migration is manual and includes both app tables and checkpoint tables.
- Migrations are exercised from blank PostgreSQL+pgvector container in integration tests.
- Downgrades are provided where feasible.
- Never edit a committed migration; add a new revision.

## State Ownership

- Repositories (in `persistence/repositories.py`) own all writes.
- Workflows (later) own high-level orchestration and call repositories inside session_scope.
- The LangGraph checkpointer owns its own tables' low-level writes.

## Persistence Invariants

- Stable IDs (UUIDs + fingerprints) are authoritative.
- Articles and their derived records are immutable after capture.
- Idempotency keys prevent duplicate scheduled briefs.
- Every Brief and Narrative proposal carries citation arrays that resolve through batch_summary → article_batch → article.
- All writes go through an AsyncSession provided by engine.session_scope (caller controls transaction).
- Secrets and article bodies are never stored in LangSmith metadata (redaction is adapter concern).
