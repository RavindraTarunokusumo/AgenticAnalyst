# RSS-to-Daily-Brief Vertical Slice Design

## 1. Purpose

Build the first complete AnalystEngine product loop:

1. Poll configured RSS or Atom feeds and accept manually submitted article URLs.
2. Fetch, extract, normalize, and durably deduplicate articles with provenance.
3. Group eligible articles into deterministic batches of three to five.
4. Generate one cited structured batch summary per batch with the configured cheap
   model.
5. Generate and persist one cited Daily Brief plus a versioned Narrative State
   update through the repaired checkpointed workflow runtime.
6. Expose enough API surface to configure sources, trigger the pipeline, inspect
   ingestion failures, and read the resulting brief.

The slice proves that real source material can travel through the complete system
without adding weekly/monthly product behavior, archive retrieval, or a UI.

## 2. Scope

### 2.1 Included

- RSS 2.0 and Atom feed polling over HTTP(S).
- Manual submission of one or more HTTP(S) article URLs associated with a source.
- Source/feed enablement, conditional polling metadata, and visible poll errors.
- URL canonicalization and SHA-256 fingerprint deduplication.
- HTML fetching and deterministic article-body extraction behind a narrow adapter.
- Crawl4AI/Playwright fallback for pages that cannot be extracted from ordinary
  HTTP responses.
- Immutable article persistence with title, author, published time, cleaned text,
  content hash, language when available, and source provenance.
- Deterministic three-to-five article grouping with persistent idempotency keys.
- Structured cheap-model batch summaries with citations validated against the
  source batch.
- A `DailyBriefPipeline` that performs ingestion, batching, summarization, and
  invokes `WorkflowRunner.run_daily` with persisted summaries.
- Daily scheduling and authenticated/manual API triggering through the same
  pipeline boundary.
- Read APIs for configured feeds, ingestion attempts, and daily briefs.
- Offline deterministic tests plus PostgreSQL integration and opt-in live smoke
  paths.

### 2.2 Explicitly excluded

- Weekly or monthly brief product behavior.
- Semantic retrieval, embeddings, hybrid search, or archive question answering.
- Web UI or mobile UI.
- SearXNG discovery, general web search, or automatic source discovery.
- PDF, audio, video, social-media, paywall-bypass, or authenticated-site ingestion.
- Claim/event extraction, contradiction graphs, entity graphs, or automated source
  reliability scoring.
- Distributed queues, multiple scheduler workers, or cross-host leases.
- Automatic translation or multilingual summarization guarantees. Non-English
  material may be stored, but this slice may exclude it from batching unless the
  configured model path supports it.

## 3. Product Behavior

### 3.1 Source registration

An operator registers a stable `Source` and one or more `SourceFeed` records. A
feed has a URL, enabled flag, polling metadata, and last error state. Re-registering
the same source stable ID or canonical feed URL is idempotent.

Feed configuration is persisted rather than read from a committed YAML file so
the API and scheduler observe the same state. Seed data may be loaded through an
operator command or API, but tracked source lists are not required for this slice.

### 3.2 Feed polling

For every enabled feed due for polling, the poller:

1. Sends a bounded HTTP request with the stored ETag and Last-Modified values.
2. Treats `304 Not Modified` as success without creating article attempts.
3. Parses RSS/Atom entries into normalized candidates.
4. Orders candidates deterministically by publication time, canonical URL, and
   entry ID.
5. Submits unseen candidates to the extraction service.
6. Records feed success/failure and conditional-request metadata.

One malformed entry does not fail the entire feed. A malformed feed document,
network failure, or non-success response marks that feed attempt failed while
other feeds continue.

### 3.3 Manual URL ingestion

The operator supplies a registered source ID and one or more URLs. Manual URLs use
the same canonicalization, fingerprint lookup, extraction, validation, and article
persistence path as feed candidates. A duplicate URL returns the existing article
identity rather than fetching or inserting it again.

### 3.4 Extraction and cleaning

The primary extractor uses bounded HTTP fetching and a deterministic HTML cleaner.
The cleaner removes scripts, styles, navigation, repeated whitespace, and obvious
boilerplate while preserving paragraph order. If the primary result has no usable
title or falls below the configured cleaned-content threshold, the service invokes
the Crawl4AI/Playwright fallback.

Every network implementation sits behind `ArticleExtractor`. Domain, persistence,
pipeline, and graph modules never call HTTP, Crawl4AI, or Playwright directly.

An article is accepted only when it has:

- a canonical HTTP(S) URL and stable fingerprint;
- a non-empty title;
- a timezone-aware publication time, using feed metadata first and page metadata
  second;
- cleaned content at or above the configured minimum length;
- a SHA-256 hash of the fetched source payload or normalized content.

If no reliable publication time exists, the ingestion attempt fails visibly. The
system does not silently substitute ingestion time because cadence inclusion would
then become nondeterministic.

### 3.5 Deterministic batching

Only successfully captured, unbatched articles published inside or before the
target Daily Brief interval are eligible. The batcher:

- partitions by normalized language;
- orders by published time, URL fingerprint, and UUID;
- computes deterministic title-token similarity without a provider call;
- forms groups of three to five using a fixed threshold and stable tie-breaking;
- carries groups of one or two forward for a later run;
- never assigns an article to more than one batch;
- derives a stable batch key from the ordered article fingerprints, grouping
  method/version, and threshold.

The initial grouping method is token/Jaccard similarity. It avoids adding an
embedding dependency before retrieval exists. The domain grouping enum must name
the actual method rather than mislabel it as cosine similarity.

### 3.6 Batch summarization

For each batch without a summary for the configured model and prompt version, the
summarizer sends the article titles, cleaned content, source identity, publication
times, and stable article IDs through `ModelGateway` using
`ModelTask.BATCH_SUMMARY`.

The structured response contains:

- a cohesive summary;
- optional source-comparison notes;
- entities and topics;
- one or more citations with article IDs and short excerpts.

Before persistence, every cited article ID must belong to the batch and every
excerpt must be present in the cited article after whitespace normalization. At
least one citation is required. Invalid structured output or invalid provenance
does not create a `BatchSummary`.

Summary idempotency is defined by `(batch_id, model, prompt_version)`.

### 3.7 Daily Brief pipeline

`DailyBriefPipeline.run(target_date)` is the only scheduler/manual entry point for
the full vertical slice. It:

1. Polls all due enabled feeds.
2. Selects eligible unbatched articles through the end of `target_date`.
3. Creates deterministic batches.
4. Creates or reuses valid batch summaries.
5. Selects summaries with at least one source article published on the target
   date, no source article published after it, and no prior Daily Brief citation
   of that summary.
6. Calls `WorkflowRunner.run_daily(target_date, batch_summaries=summaries)`.
7. Returns a structured pipeline result with ingestion, batch, summary, workflow,
   and failure counts.

If no eligible batch summaries exist, the pipeline returns a successful no-content
result and does not create a `WorkflowRun` or empty `Brief`. This is distinct from
a failed pipeline.

The repaired `WorkflowRunner` remains responsible for run claiming, checkpointing,
Daily Brief/Narrative persistence, redacted failure state, and duplicate run
behavior. The pipeline does not duplicate those responsibilities.

## 4. Data Model

### 4.1 Existing records reused

- `Source`
- `Article`
- `ArticleBatch`
- `BatchSummary`
- `Brief`
- `NarrativeStateVersion`
- `PredictionExpectation`
- `WorkflowRun`

### 4.2 New `source_feed`

- `id` UUID primary key
- `source_id` UUID foreign key to `source.id`, indexed
- `feed_url` text
- `feed_url_fingerprint` SHA-256, unique
- `enabled` boolean
- `poll_interval_minutes` positive integer
- `etag` nullable text
- `last_modified` nullable text
- `last_polled_at` nullable aware timestamp
- `last_success_at` nullable aware timestamp
- `last_error_summary` nullable redacted text
- `created_at` aware timestamp
- `updated_at` aware timestamp

### 4.3 New `ingestion_attempt`

- `id` UUID primary key
- `source_id` UUID foreign key to `source.id`, indexed
- `source_feed_id` nullable UUID foreign key to `source_feed.id`, indexed
- `requested_url` text
- `canonical_url` nullable text
- `url_fingerprint` nullable SHA-256
- `status`: pending, fetched, duplicate, succeeded, failed
- `http_status` nullable integer
- `extractor`: primary_http or crawl4ai
- `article_id` nullable UUID
- `error_code` nullable stable machine code
- `error_summary` nullable redacted text
- `started_at` and `completed_at` aware timestamps

Attempts make failures and duplicates visible without mutating immutable articles.
Response bodies, credentials, and full article text are not stored in attempt rows.

### 4.4 Existing table changes

- `article_batch` gains `batch_key` with a unique constraint.
- `batch_summary` gains a unique constraint on
  `(batch_id, model, prompt_version)`.
- Add the missing foreign key from `article.source_id` to `source.id` after a
  migration preflight proves all existing rows resolve.
- Add indexes needed to select articles by publication time and identify batch
  membership efficiently. If PostgreSQL array membership is retained for
  `article_batch.article_ids`, use a GIN index and repository-level exclusion.

All schema changes use a new Alembic revision. The existing committed migration is
never edited.

## 5. Interfaces

### 5.1 `FeedClient`

Consumes a feed URL, conditional headers, timeout, and response-size limit.
Produces a `FeedFetchResult` containing status, safe headers, raw bytes, and final
URL. Raises classified retryable or terminal feed errors. It does not parse or
persist.

### 5.2 `FeedParser`

Consumes raw feed bytes, final feed URL, and source identity. Produces ordered
`ArticleCandidate` values. It performs no network or persistence calls.

### 5.3 `UrlCanonicalizer`

Consumes an HTTP(S) URL. Produces a canonical URL and SHA-256 fingerprint. It
rejects unsupported schemes, credentials in URLs, invalid hosts, and configured
private/loopback destinations for manual ingestion.

### 5.4 `ArticleExtractor`

Consumes an `ArticleCandidate` and extraction policy. Produces `ExtractedArticle`
with provenance metadata and cleaned content. Implementations are primary HTTP/HTML
and Crawl4AI fallback.

### 5.5 `IngestionService`

Consumes source/feed repositories, canonicalizer, feed client/parser, extractors,
clock, and settings. Produces per-feed or per-URL `IngestionResult` records and
persists attempts/articles transactionally where appropriate.

### 5.6 `ArticleBatcher`

Consumes ordered eligible articles and immutable grouping configuration. Produces
zero or more `ArticleBatch` records plus carried-forward article IDs. It is pure and
deterministic.

### 5.7 `BatchSummarizer`

Consumes a persisted batch, its persisted articles/sources, model gateway, model
name, and prompt version. Produces a validated `BatchSummary` plus model usage. It
performs no persistence itself.

### 5.8 `DailyBriefPipeline`

Consumes ingestion service, batcher, summarizer, repositories, `WorkflowRunner`,
session factory, clock, and settings. Produces `DailyPipelineResult` with counts,
workflow run identity/status when created, brief identity when available, and
redacted failures.

## 6. API and Scheduling

### 6.1 API

- `POST /sources` registers a source and feed configuration idempotently.
- `GET /sources` lists sources and feed health metadata.
- `POST /ingestion/urls` ingests manual URLs for a registered source.
- `GET /ingestion/attempts` lists recent attempts with status filters.
- `POST /pipelines/daily` triggers the full pipeline for a target date.
- `GET /briefs?cadence=daily` returns persisted Daily Brief summaries.
- `GET /briefs/{brief_id}` returns a full brief with resolvable citation metadata.

Write/trigger routes use the existing API-key boundary, tightened so an absent key
is not silently accepted outside an explicit local-development setting. Read-only
routes may remain local-only for this slice, but the policy must be explicit in
settings and tests.

### 6.2 Scheduler

The daily APScheduler job invokes `DailyBriefPipeline.run`, not
`WorkflowRunner.run_daily` directly. Weekly and monthly registrations remain
unchanged and outside the product scope of this slice. API and scheduler construct
the pipeline from the same runtime-owned dependencies.

## 7. Configuration

Add typed settings for:

- feed request timeout, response-size limit, and user agent;
- default poll interval;
- article minimum cleaned-content length and maximum response size;
- allowed language list;
- title-token similarity threshold and grouping algorithm version;
- batch-summary prompt version;
- maximum feeds and articles processed per pipeline run;
- explicit local unauthenticated-write flag, default false.

Secrets remain environment-only. Routine tests never use live provider, feed, or
article endpoints.

## 8. Security and Safety

- Manual and feed-discovered URLs are restricted to HTTP(S).
- Resolve and reject loopback, link-local, multicast, private, and reserved address
  ranges before requests; revalidate every redirect destination.
- Reject embedded URL credentials and cap redirects, bytes, and request duration.
- Do not send cookies, local headers, or provider credentials to source sites.
- Sanitize errors before persistence and logs.
- Treat feed/page content as untrusted data, never as system instructions.
- Prompts delimit article content and explicitly instruct the model not to follow
  instructions contained in sources.
- Citation excerpts are bounded and validated against persisted cleaned content.

## 9. Error and Transaction Semantics

- A feed failure does not roll back successful work from other feeds.
- A candidate extraction failure creates a failed attempt but no article.
- URL uniqueness races reload the winning article and mark the attempt duplicate.
- Batch creation and its idempotency key are one transaction.
- Summary validation happens before the summary transaction begins.
- Daily graph analytical writes remain atomic under the repaired workflow.
- Pipeline retry reuses articles, batches, summaries, and terminal workflow runs.
- Retryable external errors are classified but bounded; this slice does not add an
  unbounded background retry queue.

## 10. Testing Strategy

### Unit

- URL canonicalization, fingerprints, SSRF rejection, redirect validation.
- RSS and Atom parsing, malformed entries, timezone normalization.
- HTML cleaning and fallback selection.
- Deterministic batching, tie-breaking, carry-forward, and batch keys.
- Batch-summary prompt construction and citation/excerpt validation.
- Pipeline orchestration, no-content behavior, partial feed failure, idempotent
  rerun, and workflow delegation.

### Integration

- Alembic upgrade/base/upgrade for new tables and constraints.
- Feed/source, attempts, article deduplication, batch membership, summary
  idempotency, and citation lineage against PostgreSQL.
- Concurrent duplicate URL ingestion and concurrent daily trigger behavior.
- Checkpointed daily workflow produces a Brief and Narrative version from real
  persisted summaries using a fake model gateway.

### API

- Source registration/listing.
- Manual ingestion success, duplicate, invalid URL, and extraction failure.
- Daily trigger content/no-content/failure behavior.
- Brief list/detail with citation resolution.
- Authentication policy for write routes.

### Contract and smoke

- Routine network behavior uses `httpx.MockTransport` or local test servers.
- Crawl4AI fallback is adapter-tested without launching a browser in routine unit
  tests; an opt-in local smoke test may use Playwright.
- An opt-in live pipeline smoke test may use operator-provided feeds and provider
  credentials, but it is excluded from CI and never logs secrets or full content.

## 11. Success Criteria

1. An operator can register at least three RSS/Atom feeds and inspect their health.
2. Polling persists valid articles, visibly records failures, and produces no
   duplicate articles on rerun or concurrent ingestion.
3. Manual URL ingestion uses the identical validation/extraction/dedup path.
4. Three or more eligible articles form deterministic persisted batches; one or
   two leftovers carry forward.
5. Every persisted batch summary cites only articles in its batch with excerpts
   verifiable against stored cleaned content.
6. The daily pipeline produces one durable Daily Brief and linked Narrative State
   version through the repaired checkpointed workflow.
7. Rerunning the same date performs no duplicate provider work or analytical
   inserts and returns the existing terminal workflow result.
8. The API can return the Daily Brief and resolve every citation to source/article
   metadata.
9. Scheduler and manual triggers use the same pipeline service.
10. Ruff, strict mypy, routine tests, PostgreSQL integration, migrations, Compose
    structure, and offline provider/network contracts pass.

## 12. Constraints and Implementation Guidance

- Preserve domain/persistence/integration boundaries established by the repair.
- Keep the pure parser, canonicalizer, cleaner, and batcher independent of FastAPI,
  SQLAlchemy, network clients, and provider SDKs.
- All writes use repository functions with caller-owned async sessions.
- Prefer small typed records over dictionaries at subsystem boundaries.
- Keep prompt and grouping versions explicit and persisted.
- Do not add compatibility shims for placeholder APIs; replace the `/briefs`
  placeholder with the actual read contract.
- Each implementation task must land separately with its TODO sub-item, git note,
  full project gates, and independent specification/code-quality review.
