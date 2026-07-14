# RSS-to-Daily-Brief Vertical Slice — Implementation Plan

Spec: `docs/superpowers/specs/2026-07-13-rss-daily-brief-design.md` (accepted).
Branch: `codex/rss-daily-brief-plan`.

This is the implementer's contract: file structure, task decomposition, per-task
Interfaces (Consumes/Produces), build order, and risks. Exact code, prompts, and
shell commands are regenerated per task, not transcribed here.

## Reconciliation notes vs. spec text

- Spec §4.4 says the `article.source_id → source.id` FK is "missing". The existing
  migration (`963e5ab691b1`) already creates it (`ON DELETE RESTRICT`). No action
  needed — Task 2 documents this instead of re-adding it.
- Spec §3.5 flags `GroupingMethod` as mislabeled (`TITLE_COSINE`/`CONTENT_COSINE`
  when the method is token/Jaccard). Task 1 renames the enum member actually used
  by the new batcher; existing members are only referenced by test fixtures today
  (no persisted rows to migrate), so this is a safe rename, not a data migration.

## File structure (new/changed)

```
src/analyst_engine/
  domain/models.py            [CHANGED] SourceFeed, IngestionAttempt, IngestionStatus,
                               ExtractorKind, GroupingMethod rename (Task 1);
                               ArticleBatch.batch_key (Task 2, with its ORM column)
  config.py                   [CHANGED] ingestion/pipeline settings
  persistence/models.py       [CHANGED] source_feed, ingestion_attempt ORM; batch_key +
                               batch_summary unique constraint; GIN index
  persistence/repositories.py [CHANGED] feed/attempt/article/batch/summary lookups
  ingestion/
    __init__.py
    errors.py                 shared classified-error hierarchy (retryable/terminal)
    bounded_http.py           shared size/timeout/redirect/SSRF-safe fetch helper
    canonicalize.py           UrlCanonicalizer
    feed_client.py            FeedClient
    feed_parser.py            FeedParser
    html_clean.py             deterministic HTML cleaner
    extractor.py               ArticleExtractor protocol, PrimaryHttpExtractor, Crawl4AIExtractor
    models.py                  ArticleCandidate, ExtractedArticle, FeedFetchResult, IngestionResult
    service.py                  IngestionService
  batching/
    __init__.py
    batcher.py                  ArticleBatcher, BatcherResult
  summarization/
    __init__.py
    prompts.py                   message construction + BatchSummaryModelResult schema
    summarizer.py                 BatchSummarizer
  pipeline/
    __init__.py
    daily_brief.py                 DailyBriefPipeline, DailyPipelineResult
  runtime.py                   [CHANGED] add httpx client factory + ingestion/pipeline construction
  scheduling.py                [CHANGED] daily job binds to DailyBriefPipeline.run
  api/app.py                   [CHANGED] new routes, replace /briefs placeholder, auth tightening
alembic/versions/
  <rev>_add_source_feed_ingestion_attempt_batch_constraints.py   [NEW]
tests/unit/…, tests/integration/…, tests/api/…                  [NEW/CHANGED per task]
docs/architecture.md, database.md, patterns.md, commands.md,
  index.md, changelog.md, .env.example, compose.yaml             [CHANGED, Task 12]
```

Module boundary carried over from the existing repair: `ingestion/`, `batching/`,
`summarization/` stay free of FastAPI/SQLAlchemy; only `service.py`,
`daily_brief.py`, and the repositories touch persistence; only `bounded_http.py`,
`feed_client.py`, and `extractor.py` touch network/SDKs.

## Task decomposition

Each task lands as its own commit(s) with a TODO sub-item, git note, and a full
`ruff format --check` + `ruff check` + `mypy src tests` + `uv run pytest` gate
before commit (per spec §12: "independent specification/code-quality review").

### Task 1 — Domain models + config

- **Consumes:** nothing new (extends existing `domain/models.py`, `config.py`).
- **Produces:**
  - `SourceFeed`, `IngestionAttempt` frozen Pydantic models (fields per spec §4.2–4.3).
  - `IngestionStatus` StrEnum (`pending, fetched, duplicate, succeeded, failed`), `ExtractorKind` StrEnum (`primary_http, crawl4ai`).
  - `GroupingMethod` renamed member for the real method (`TITLE_TOKEN_JACCARD`); update the two existing test-fixture references in the same commit.
  - `Settings` fields: `feed_request_timeout_seconds`, `feed_response_size_limit_bytes`, `feed_user_agent`, `default_poll_interval_minutes`, `article_min_content_length`, `article_max_response_size_bytes`, `allowed_languages: list[str]`, `title_similarity_threshold: float`, `grouping_algorithm_version: str`, `batch_summary_prompt_version: str`, `max_feeds_per_run: int`, `max_articles_per_run: int`, `allow_unauthenticated_write: bool = False`.
- **Consumed by:** every later task.
- **Risk:** enum rename is a breaking signature change — grep all call sites before committing.

### Task 2 — Persistence schema + migration

- **Consumes:** Task 1 domain fields.
- **Produces:** `source_feed`, `ingestion_attempt` ORM tables + domain↔ORM mappers; `ArticleBatch.batch_key: str` domain field **and** its `article_batch.batch_key` column + unique constraint, added together in this task (not Task 1) so every commit round-trips cleanly — Task 1 has no ORM column to back a required domain field; unique constraint on `batch_summary(batch_id, model, prompt_version)`; GIN index on `article_batch.article_ids` (needed by the "unbatched articles" exclusion query in Task 3); one new Alembic revision, `down_revision = "963e5ab691b1"`.
- **Consumed by:** Task 3 repositories, Task 13 integration tests (upgrade/base/upgrade roundtrip, reusing the existing `_apply_migrations` integration-test pattern).
- **Risk:** the GIN-index/array-exclusion query shape must be decided together with Task 3's `list_eligible_unbatched_articles` — write the query first, then the index that supports it, not the reverse.

### Task 3 — Repositories

- **Consumes:** Task 1/2 types and tables. Same pattern as existing repositories: `async def fn(session: AsyncSession, ...) -> ...`, no owned session.
- **Produces:**
  - `upsert_source_feed`, `get_source_feed_by_fingerprint`, `list_due_source_feeds(session, now) -> list[SourceFeed]`
  - `list_sources`, `get_source_by_stable_id`
  - `record_ingestion_attempt`, `update_ingestion_attempt`
  - `get_article_by_fingerprint`, `list_eligible_unbatched_articles(session, before_date, languages) -> list[Article]`
  - `get_article_batch_by_key`, `get_batch_summary_by_identity(session, batch_id, model, prompt_version) -> BatchSummary | None`
  - `get_brief_by_id` (for `GET /briefs/{brief_id}`)
- **Consumed by:** Task 9 (IngestionService), Task 10 (DailyBriefPipeline), Task 12 (API routes).
- **Risk:** `list_eligible_unbatched_articles` is the correctness-critical query (spec §3.5: never assign an article to more than one batch) — needs an integration test with a PostgreSQL-backed batch already covering some articles, asserting exclusion.

### Task 4 — UrlCanonicalizer + shared bounded-fetch/SSRF helper

- **Consumes:** raw URL string, `Settings` (size/timeout limits).
- **Produces:** `canonicalize(url) -> (canonical_url, fingerprint)`, raising typed errors for unsupported scheme, embedded credentials, invalid host, and private/loopback/link-local/multicast/reserved destinations (resolved via DNS before any request). `bounded_http.py` exposes a `fetch(url, *, timeout, size_limit, headers) -> BoundedFetchResult` used identically by Task 5's `FeedClient` and Task 6's `PrimaryHttpExtractor`, revalidating every redirect hop through the same SSRF check.
- **Consumed by:** Tasks 5, 6, 9.
- **Risk:** this is the security-critical module (spec §8). Unit tests must cover DNS-rebinding-style redirect-to-private-IP, not just the initial host check.

### Task 5 — FeedClient + FeedParser

- **Consumes:** Task 4's `bounded_http`, feed URL, conditional headers (ETag/Last-Modified).
- **Produces:** `FeedClient.fetch(...) -> FeedFetchResult` (304 short-circuit, classified retryable/terminal errors); `FeedParser.parse(raw_bytes, feed_url, source_id) -> list[ArticleCandidate]`, deterministically ordered (published time, canonical URL, entry ID), one malformed entry skipped rather than failing the whole feed. Add `feedparser` (or equivalent) to `pyproject.toml` if not already present — verify first.
- **Consumed by:** Task 9.
- **Risk:** `feedparser`'s lenient parsing must not silently swallow a fully-malformed document — only-zero-entries-and-bozo should raise, not return `[]` silently (spec §3.2: "a malformed feed document ... marks that feed attempt failed").

### Task 6 — HTML cleaner + ArticleExtractor (primary + Crawl4AI fallback)

- **Consumes:** Task 4's `bounded_http` for primary fetch; bundled Crawl4AI/Playwright (already in the app image per `docs/architecture.md`) for fallback.
- **Produces:** `clean_html(html) -> CleanedContent(title, text, language)`; `ArticleExtractor` protocol with `PrimaryHttpExtractor` and `Crawl4AIExtractor`; fallback trigger policy (no usable title or cleaned content below `article_min_content_length`).
- **Consumed by:** Task 9.
- **Risk:** Crawl4AI/Playwright must not be exercised in routine unit tests (spec §10) — adapter-test the fallback trigger and call shape with a fake, reserve real browser launches for an opt-in smoke test.

### Task 7 — ArticleBatcher

- **Consumes:** ordered `list[Article]`, grouping config (threshold, algorithm version) from `Settings`.
- **Produces:** pure `batch(articles, config) -> BatcherResult(batches: list[ArticleBatch], carried_forward_ids: list[UUID])` — language partition, deterministic ordering, title-token Jaccard groups of 3–5, stable `batch_key` derivation (ordered fingerprints + method/version + threshold), never double-assigns an article.
- **Consumed by:** Task 10.
- **Risk:** tie-breaking determinism — needs a property-style unit test asserting identical input order always yields identical batch_key/grouping across repeated runs.

### Task 8 — BatchSummarizer

- **Consumes:** persisted `ArticleBatch` + its `Article`/`Source` rows, `ModelGateway`, model name, prompt version.
- **Produces:** `summarize(batch, articles, sources, gateway, model, prompt_version) -> (BatchSummary, ModelUsage)`, calling `gateway.generate(task=ModelTask.BATCH_SUMMARY, ...)` with a `BatchSummaryModelResult` `output_schema` (mirrors the existing `FrontierResult` pattern in `workflows/graphs.py`); validates every citation's `article_id` is in the batch and every excerpt matches cleaned content after whitespace normalization; raises rather than returning a summary with zero/invalid citations.
- **Consumed by:** Task 10.
- **Risk:** prompt must explicitly delimit article content and instruct the model not to follow embedded instructions (spec §8) — this is a security requirement, not just a quality one; test it with an adversarial fixture article containing an injected instruction.

### Task 9 — IngestionService

- **Consumes:** source/feed repositories (Task 3), `UrlCanonicalizer` (Task 4), `FeedClient`/`FeedParser` (Task 5), extractors (Task 6), clock, settings, `session_factory`.
- **Produces:** `poll_feed(feed) -> IngestionResult`, `ingest_urls(source_id, urls) -> list[IngestionResult]`. Persists `IngestionAttempt` + `Article` transactionally; on a unique-fingerprint race, reloads the winning article and marks the new attempt `duplicate` rather than erroring (spec §9).
- **Consumed by:** Task 10, Task 12 (`POST /ingestion/urls`).
- **Risk:** the largest integration surface in the slice — build against fakes for unit tests, then a dedicated PostgreSQL integration test for the concurrent-duplicate-URL race (spec §10 Integration, §9).

### Task 10 — DailyBriefPipeline

- **Consumes:** `IngestionService` (9), `ArticleBatcher` (7), `BatchSummarizer` (8), repositories (3), the **existing, unmodified** `WorkflowRunner.run_daily` (`workflows/runner.py:186`), `session_factory`, clock, settings.
- **Produces:** `DailyBriefPipeline.run(target_date) -> DailyPipelineResult` implementing spec §3.7's 7 steps exactly, including the no-content short-circuit (no `WorkflowRun`/`Brief` created, distinct from failure) and idempotent rerun (reuses existing batches/summaries/terminal workflow runs, per spec §9).
- **Consumed by:** Task 11 (scheduler), Task 12 (`POST /pipelines/daily`).
- **Risk:** must not duplicate `WorkflowRunner`'s claiming/checkpointing responsibilities (spec §3.7 explicit boundary) — the pipeline only selects summaries and calls `run_daily`; do not touch `workflows/runner.py` or `graphs.py` in this task.

### Task 11 — Runtime wiring + scheduler

- **Consumes:** Task 9/10 constructors.
- **Produces:** `RuntimeDependencies` (or a sibling factory used alongside it) grows an `httpx.AsyncClient` factory and constructs `IngestionService`/`DailyBriefPipeline` identically for API (`api/app.py` lifespan) and scheduler (`main.py::run_scheduler`) — same pattern already used for `WorkflowRunner`. `scheduling.py`'s daily job rebinds from `runner.run_daily` to `pipeline.run`; weekly/monthly jobs are untouched.
- **Consumed by:** Task 12.
- **Risk:** the `RuntimeDependencies.close()` must also dispose the new `httpx.AsyncClient`; check both call sites (API lifespan `finally`, scheduler shutdown) get the new dependency, not just one.

### Task 12 — API routes

- **Consumes:** Task 9 (`IngestionService`), Task 10 (`DailyBriefPipeline`), Task 3 (repositories), Task 11 (runtime wiring), existing `_require_key` boundary.
- **Produces:** `POST /sources`, `GET /sources`, `POST /ingestion/urls`, `GET /ingestion/attempts`, `POST /pipelines/daily`, `GET /briefs?cadence=daily` (real implementation replacing the placeholder), `GET /briefs/{brief_id}` with resolved citation metadata. Auth: write/trigger routes require a key unless `settings.allow_unauthenticated_write` is explicitly `True`; read routes may stay open but the policy is asserted in tests either way (spec §6.1).
- **Consumed by:** nothing further in-repo; this is the external contract.
- **Risk:** `_require_key`'s current behavior (`None`/blank key silently becomes `"local"`) is a live gap the spec calls out — tightening it must not break the existing `/workflows/trigger` route's tests; update those tests in the same commit rather than leaving them red.

### Task 13 — Integration/API test sweep + success-criteria verification

- **Consumes:** everything above.
- **Produces:** the cross-cutting tests spec §10 lists that don't naturally belong to one task alone — full migration upgrade/base/upgrade with the new tables, concurrent daily-trigger behavior, end-to-end checkpointed daily workflow producing a `Brief`+`NarrativeStateVersion` from real persisted summaries with a fake gateway — plus a pass through spec §11's 10 success criteria as an explicit checklist.
- **Risk:** none new; this is verification, not new production code.

### Task 14 — Documentation reconciliation

- **Consumes:** the merged behavior of Tasks 1–13.
- **Produces:** updates to `docs/architecture.md`, `docs/database.md`, `docs/patterns.md`, `docs/commands.md`, `docs/index.md`, `docs/changelog.md`, `.env.example`, and `compose.yaml` env forwarding for the new settings (mirrors the existing gap noted for `MODEL_PROVIDER`/`OPENROUTER_*`).
- **Risk:** none new.

## Build order

Task 1 → 2 → 3 (strict; each needs the prior committed).
Tasks 4, 5, 6, 7 can proceed in any order once Task 1 lands (disjoint files, only
share `bounded_http.py` between 5 and 6 — land 4 first since both depend on it).
Task 8 only needs Task 1 (domain) + existing `ModelGateway` — can run in parallel
with 4–7.
Task 9 needs 3, 4, 5, 6. Task 10 needs 7, 8, 9. Task 11 needs 10. Task 12 needs
3, 9, 10, 11. Task 13 needs 12. Task 14 needs 13.

Practically: implement sequentially in this worktree (1→2→3→4→5→6→7→8→9→10→11→12→13→14).
Parallelizing 4/5/6/7/8 across sub-worktrees is possible per CLAUDE.md workflow
rule 4, but the shared `bounded_http.py` dependency and the small size of each
task make sequential implementation with full gates between tasks simpler and
safer than merge coordination overhead for this slice.

## Cross-task risks

- **SSRF correctness** (Task 4) is reused by everything that fetches a URL
  (Tasks 5, 6, 9) — a mistake here compromises the whole slice's security
  posture. Land and gate it first among the pure/adapter tasks.
- **`GroupingMethod` rename** (Task 1) is the one change with blast radius into
  existing code/tests — must be swept in the same commit, not deferred.
- **Auth tightening** (Task 12) touches an existing route (`/workflows/trigger`)
  — regressions here would silently reopen or break write access; its existing
  test must be updated, not skipped.
- **Idempotency chain** (batch_key → summary identity → pipeline no-duplicate
  rerun) spans Tasks 2, 7, 8, 10 — the batch_key derivation formula must be
  fixed once (Task 7) and never redefined downstream.
