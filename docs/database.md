# Database and Persistence

## Purpose

PostgreSQL 16 + pgvector is the single system of record for AnalystEngine. It stores LangGraph checkpoints, source and article records, deterministic article batches, batch summaries, briefs, versioned Narrative State, expectations, embeddings of briefs, and workflow run metadata for durable cadence execution.

No claim_event, event fingerprinting, or contradiction graph exists (explicitly deferred).

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

### source_feed
Polled RSS/Atom feed belonging to a source.
- `id`, `source_id` (FK), `feed_url`, `feed_url_fingerprint` (unique), `enabled`, `poll_interval_minutes`, `etag`, `last_modified`, `last_polled_at`, `last_success_at`, `last_error_summary`, created/updated_at

### ingestion_attempt
Observable record of one feed or manual ingestion attempt (attempts, not the immutable article, absorb failures/duplicates).
- `id`, `source_id` (FK), `source_feed_id` (nullable FK), `requested_url`, `canonical_url`, `url_fingerprint`, `status` (pending/fetched/duplicate/succeeded/failed), `http_status`, `extractor`, `article_id`, `error_code`, `error_summary`, started/completed_at

### article
Immutable captured content with provenance.
- `id` (UUID PK), `source_id` (FK), `url`, `url_fingerprint` (unique), title, author, published/ingested, language, hashes, `cleaned_content`
- Indexes on source and published_at.

### article_batch
Deterministic 3–5 article grouping.
- `id`, `article_ids` (array, GIN-indexed), `batch_key` (unique - derived from ordered article fingerprints + grouping method/version/threshold, makes batch creation idempotent on retry), grouping_method, embedding_model, threshold, grouping_run_id, created_at

### batch_summary
Flash model output over one batch (with citations).
- `id`, `batch_id` (FK), model/prompt_version, summary, source_notes, entities/topics (arrays), `citations` (JSONB), created_at
- Unique constraint on `(batch_id, model, prompt_version)` - a batch's summary for a given model+prompt version is created at most once.

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
- Initial migration (`963e5ab691b1`) is manual and includes both app tables and checkpoint tables. `6b135f7a55de` adds `source_feed`/`ingestion_attempt` and the `article_batch`/`batch_summary` constraints above.
- Migrations are exercised from blank PostgreSQL+pgvector container in integration tests (upgrade/base/upgrade roundtrip).
- Downgrades are provided where feasible.
- Never edit a committed migration; add a new revision.

## State Ownership

- Repositories (in `persistence/repositories.py`) own all writes.
- Workflows (via WorkflowRunner) own high-level orchestration and call repositories inside session_scope.
- The LangGraph checkpointer owns its own tables' low-level writes.

## Persistence Invariants

- Stable IDs (UUIDs + fingerprints) are authoritative.
- Articles and their derived records are immutable after capture.
- Idempotency keys on workflow_run prevent duplicate scheduled executions (daily/weekly/monthly).
- Workflow runs record lifecycle (pending → running → succeeded/failed) with stable ID used for checkpoint correlation.
- Every Brief and Narrative proposal carries citation arrays that resolve through batch_summary → article_batch → article.
- All writes go through an AsyncSession provided by engine.session_scope; the context manager commits on success, rolls back on error, and closes the session around the caller's operations.
- Secrets and article bodies are never stored in LangSmith metadata (redaction is adapter concern).
