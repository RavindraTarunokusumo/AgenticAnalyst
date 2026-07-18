# Changelog

Record notable behavior, architecture, API, persistence, or workflow changes.

## 2026-07-17 — Multi-Topic Source Sharing (composite uniqueness)

Summary:
- What changed: Three previously-global uniqueness constraints became composite so the same source and the same URL can be used across multiple topics (migration `b8e4c1a09f3d`): `source.stable_id` → `(topic_id, stable_id)`, `article.url_fingerprint` → `(topic_id, url_fingerprint)`, `source_feed.feed_url_fingerprint` → `(source_id, feed_url_fingerprint)`. Correspondingly, the repository lookups that keyed on these identifiers were scoped: `get_source_by_stable_id`/`upsert_source` take `topic_id`, `get_article_by_fingerprint` takes `topic_id`, `get_source_feed_by_fingerprint`/`upsert_source_feed` key on `source_id`. Both `get_article_by_fingerprint` call sites in ingestion (pre-insert dedup and the IntegrityError winner re-fetch) pass `topic_id`.
- Why: Slice 1 (PR #9) scoped sources/articles/briefs to a topic but left these three uniqueness scopes global. That made a shared source/URL unusable across topics — re-registering silently reassigned the source, and the same URL under a second topic was dup-suppressed against the first topic's article. Once two topics legitimately share an identifier, an unscoped `scalar_one_or_none()` lookup also returns two rows and 500s. The user confirmed cross-topic sharing as a real requirement.
- User-visible impact: the same source can now be registered under several topics, and the same URL ingested under several topics lands as a distinct article in each topic's pool.
- Migration notes: `b8e4c1a09f3d` (`down_revision = 00f3ae192a5a`). Downgrade re-adds the global uniques and can fail if cross-topic duplicates already exist (inherent to widening a uniqueness scope).
- Related PR/commit: `docs/superpowers/specs/2026-07-17-multi-topic-source-sharing-design.md`, `docs/superpowers/plans/2026-07-17-multi-topic-source-sharing.md`; see `TODO.md` for commit hashes.

## 2026-07-16 — Product UI Refinement (onboarding, uploads, add-content)

Summary:
- What changed: Backend gained `POST /ingestion/files` (multipart, `source_id` + `file`) for manual PDF/plain-text article uploads, backed by a new `FileExtractor` protocol (`PdfFileExtractor`/`TextFileExtractor`, `ingestion/file_extractor.py`) and two new `ExtractorKind` members (`FILE_PDF`/`FILE_TEXT`, additive - no migration). `IngestionService`'s duplicate-check/finalize-persist tail was factored out of `_ingest_candidate` into `_check_duplicate`/`_finalize_extracted` (a pure extract-method refactor, behavior unchanged) so the new `ingest_file` can reuse the same race-safe persistence path; uploads dedup by content-hash via a synthetic `upload://<sha256>` URL and are stamped with ingestion time as `published_at` (no real publish date exists for an upload). Oversized uploads (over `settings.article_max_response_size_bytes`) are rejected before extraction with `status="failed"`/`error_code="file_too_large"` rather than a raw `413`. Frontend gained first-run onboarding (`Onboarding.tsx`, gates the existing 3-panel view behind at least one registered source), a 3-mode add-content panel (paste links / register a feed / upload a file - `AddContentPanel.tsx`, `IngestionResultList.tsx`), a persistent recent-activity view (`RecentActivityList.tsx`, backed by the existing `GET /ingestion/attempts`), and client-held API key settings (`ApiKeySettings.tsx`, `localStorage['ae_api_key']`). The dev-server proxy (`vite.config.ts`) was extended to cover `/sources` and `/ingestion`, not just `/briefs`.
- Why: The UI was read-only with no onboarding, upload, or write-surface functionality - it didn't look like a usable product. This slice is explicitly functionality-only; visual/design changes were out of scope per product direction.
- User-visible impact: A fresh install now walks a user through registering a first source before showing the brief viewer; once a source exists, links/feeds/files can be submitted through the UI with per-item result feedback and a running activity log, with no change to the existing read-only brief browsing behavior.
- Migration notes: None. `ExtractorKind`'s new members are additive against the existing unconstrained `String(32)` column.
- Related PR/commit: tracked in `docs/superpowers/specs/2026-07-16-product-ui-refinement-design.md` and `docs/superpowers/plans/2026-07-16-product-ui-refinement.md`; see `TODO.md` for commit hashes.

## 2026-07-15 — Archive Retrieval / Semantic Search

Summary:
- What changed: Added `ModelGateway.embed()` (new abstract method; `DashScopeAdapter.embed` calls `client.embeddings.create`, `OpenRouterAdapter.embed` unconditionally raises `TerminalModelError` since OpenRouter has no embeddings endpoint). The `synthesize` node now best-effort embeds every new brief's content and persists it via `save_embedding`, wrapped in a SAVEPOINT (`session.begin_nested()`) rather than a bare `try/except`, so neither a model-side nor a DB-side embedding failure can roll back the brief/narrative/expectations already flushed in the same transaction (verified empirically against a real DB-level failure - see `docs/architecture.md`). New `search_embeddings_by_similarity` repository function (embedding joined to brief, ordered by pgvector cosine distance, optional cadence filter). New `GET /archive/search?q=...&cadence=...&limit=...` route ranks briefs by similarity to a free-text query, returning a bounded content snippet and similarity score per result.
- Why: `Embedding` (domain model + `save_embedding`) existed since an earlier slice but was never called from any pipeline or graph node - there was no embedding generation step and no read API to query by similarity, the largest gap between the current product (three cadences of briefs, browsable only by cadence+date) and "narrative memory you can actually query," per `TODO.md`'s Future Backlog.
- User-visible impact: every new brief (any cadence) now gets an `Embedding` row on the happy path; `GET /archive/search` lets a caller find past briefs by meaning, not just cadence/date. No change to brief creation's existing behavior on the OpenRouter provider or on any DB-layer embedding failure - both degrade silently, brief creation itself always succeeds.
- Migration notes: None. No schema changes - reuses the existing `embedding` table and `Vector(1536)` column from a prior slice.
- Related PR/commit: tracked in `docs/superpowers/specs/2026-07-15-archive-retrieval-design.md` and `docs/superpowers/plans/2026-07-15-archive-retrieval.md`; see `TODO.md` for commit hashes.

## 2026-07-15 — UI / Brief Viewer

Summary:
- What changed: Added a React + TypeScript + Vite + Tailwind CSS SPA (`frontend/`, the repo's first Node/npm toolchain) served read-only at `GET /ui/*` via `StaticFiles(directory=..., html=True)` mounted last in `create_app()`. The viewer has cadence tabs (daily/weekly/monthly), a brief list panel, and a detail panel (content, resolved citations, entity/topic chips), all backed by the existing unmodified `GET /briefs` / `GET /briefs/{brief_id}` routes via a typed client (`frontend/src/api.ts`) that mirrors `BriefListItemResponse`/`BriefDetailResponse` field-for-field. The Dockerfile gained a first `frontend-build` Node stage whose `dist/` output is copied into the existing Python runtime stage, keeping one deployable image. A committed placeholder `index.html` under `src/analyst_engine/api/static/` (gitignored `frontend/dist/` overwrites it locally on build; Docker always produces the real one) keeps `/ui/` from 404ing on a fresh checkout with no frontend build run yet. CI gained a parallel `frontend` job (`npm ci`, `oxlint`, `npm run build` including `tsc -b`).
- Why: The product was API-only end to end (`GET /briefs` usable only via curl/gh); this closes that gap with a minimal read-only viewer, per the accepted spec's revision to a full React app (not a static HTML file) per explicit product direction.
- User-visible impact: `GET /ui/` now serves a working brief browser after `npm run build` (local) or in the built Docker image; no change to any existing API route's behavior or auth.
- Migration notes: None. No schema or API contract changes - the SPA only reads existing routes.
- Related PR/commit: tracked in `docs/superpowers/specs/2026-07-15-ui-brief-viewer-design.md` and `docs/superpowers/plans/2026-07-15-ui-brief-viewer.md`; see `TODO.md` for commit hashes.

## 2026-07-15 — Weekly/Monthly Brief Vertical Slice

Summary:
- What changed: Added `PeriodicBriefPipeline` (`pipeline/periodic_brief.py`), one cadence-parameterized pipeline (`Cadence.WEEKLY`/`Cadence.MONTHLY`) that closes the gap the RSS-to-Daily-Brief slice left open: weekly/monthly workflow runs previously called `WorkflowRunner.run_weekly`/`run_monthly` directly with no evidence (`batch_summaries=None`), producing a degenerate brief from an empty context. The pipeline normalizes an anchor date to the canonical Monday-Sunday week or calendar month (matching the runner's own default-case formula exactly, since the runner does not normalize an explicitly-passed date), selects already-persisted `BatchSummary` rows whose batch has an article published in that window via the new `list_eligible_batch_summaries_for_window` repository query, excludes summaries already cited for *this same cadence and window* (a summary cited by a Daily brief remains independently eligible for its Weekly brief — citation tracking is per-cadence, unchanged and reused as-is), then calls the existing, unmodified `WorkflowRunner.run_weekly`/`run_monthly`. The scheduler's weekly (Sunday 03:00) and monthly (1st 04:00) cron jobs now call `weekly_pipeline.run()`/`monthly_pipeline.run()` instead of the runner directly. New API surface: `POST /pipelines/weekly`, `POST /pipelines/monthly`. `/workflows/trigger`'s three cadence branches (daily, weekly, monthly) now all delegate to their respective pipeline's `.run()` — this also fixes daily's identical pre-existing bypass (`/workflows/trigger` calling `runner.run_daily` directly instead of `DailyBriefPipeline`) in the same change, so there is exactly one correct way to trigger a real brief per cadence. `/workflows/trigger`'s returned `idempotency_key` is now derived from each pipeline's own normalized window, not the raw request; a genuinely no-content pipeline result now returns 409 from that route (its response fields stay non-nullable by contract).
- Why: This slice proves the full weekly/monthly product loop the same way the RSS-to-Daily-Brief slice proved it for daily — real, already-persisted evidence in, a durable checkpointed Brief out — using only existing, unmodified architecture (the graph, the runner, the citation-exclusion primitive, the read API) plus one new orchestration layer, per the accepted design's explicit constraint not to touch `workflows/graphs.py` or `workflows/runner.py`.
- User-visible impact: `POST /pipelines/weekly`/`monthly`, a scheduled Sunday/1st-of-month run, or `POST /workflows/trigger` for any of the three cadences now all produce a real Brief citing real evidence for the same window, through the same pipeline instance. `GET /briefs?cadence=weekly|monthly` (already cadence-generic, unchanged) now returns real content instead of degenerate empty-context briefs.
- Migration notes: None. No schema changes, no new Alembic revision — this slice is read-and-orchestrate only against existing tables.
- Related PR/commit: PR #4 (merged `552e272`), Tasks 1-6, tracked in `docs/iterations/archive/2026-07-15-weekly-monthly-brief.md`. See accepted spec `docs/superpowers/specs/2026-07-15-weekly-monthly-brief-design.md` and plan `docs/superpowers/plans/2026-07-15-weekly-monthly-brief.md`.

## 2026-07-14 — RSS-to-Daily-Brief Vertical Slice

Summary:
- What changed: Added the full ingestion-to-brief pipeline. RSS/Atom feed polling (conditional requests, 304 short-circuit) and manual URL submission both route through one `IngestionService._ingest_candidate` path: SSRF-safe URL canonicalization (rejects private/loopback/reserved hosts, re-validated on every redirect hop, never delegated to httpx's own follower), bounded HTTP fetch with a deterministic stdlib HTML cleaner as primary extractor and Crawl4AI as fallback, article-shape validation (title, publish time from feed-then-page metadata, minimum content length), and race-safe persistence (a fingerprint-uniqueness race reloads the winning article and marks the loser's attempt duplicate rather than erroring). `ArticleBatcher` deterministically groups eligible unbatched articles into batches of 3-5 by title-token Jaccard similarity (`GroupingMethod.TITLE_TOKEN_JACCARD`, correcting the prior mislabeled `TITLE_COSINE`), carrying groups under 3 forward. `BatchSummarizer` calls `ModelGateway` with an explicit anti-prompt-injection system message and validates every citation's article-ID membership and excerpt provenance before persisting. `DailyBriefPipeline.run(target_date)` is now the sole entry point for both the scheduler's daily job and `POST /pipelines/daily`, orchestrating polling, batching, summarization, and the existing unmodified `WorkflowRunner.run_daily`. New API surface: `POST`/`GET /sources`, `POST /ingestion/urls`, `GET /ingestion/attempts`, `POST /pipelines/daily`, and a real `GET /briefs` / `GET /briefs/{brief_id}` (replacing the `/briefs` placeholder) that resolves every citation to article title/URL/source name. Write/trigger routes now reject requests with no API key (401) unless `ALLOW_UNAUTHENTICATED_WRITE=true` is explicitly set; read routes stay open. Post-review hardening (Task 15): a rejected `UrlValidationError` from the primary extractor is now terminal rather than triggering the weaker-validated Crawl4AI fallback, and `bounded_fetch` pins its connection to the exact IP validated by `canonicalize_url` (preserving the original hostname via `Host` header + TLS SNI) to close a DNS-rebinding TOCTOU window between validation and connection.
- Why: This is Agentic Analyst's first complete product loop — proving real source material can travel from a feed or a submitted URL through extraction, deduplication, batching, summarization, and a durable checkpointed Daily Brief without any weekly/monthly behavior, archive retrieval, or UI. It also closes a live security gap (`/workflows/trigger` silently accepting an absent API key with no opt-out) called out explicitly in the accepted design. The Task 15 hardening closes two SSRF gaps found by a self-conducted post-implementation security review (native Agent tooling, since Grok's own delegation had already failed 3x on this session's simpler Task 14).
- User-visible impact: operators can register sources/feeds and manually submit URLs via the API; a daily `docker compose` scheduler run (or `POST /pipelines/daily`) now performs real ingestion instead of relying on pre-seeded batch summaries; `GET /briefs/{id}` returns resolvable citations instead of bare UUIDs. Write routes require `X-API-Key` unless the new `allow_unauthenticated_write` setting is explicitly enabled for local development.
- Migration notes: New revision `6b135f7a55de` (on top of `963e5ab691b1`) adds `source_feed` and `ingestion_attempt` tables, `article_batch.batch_key` (unique) and its GIN-indexed `article_ids` column, and a `(batch_id, model, prompt_version)` unique constraint on `batch_summary`. `article.source_id`'s FK to `source.id` already existed from the initial migration (the design doc's text calling it "missing" was a stale assumption, verified and reconciled, not an actual gap).
- Related PR/commit: PR #3 (merged `9848a9c`), Tasks 1-15, tracked in `docs/iterations/archive/2026-07-13-rss-daily-brief.md`. See accepted spec `docs/superpowers/specs/2026-07-13-rss-daily-brief-design.md` and plan `docs/superpowers/plans/2026-07-13-rss-daily-brief.md`.

## 2026-07-12 — Runtime and Persistence Repair

Summary:
- What changed: Implemented truthful workflow-run lifecycle (explicit create + update with strict transitions: pending→running→succeeded/failed), shared RuntimeDependencies bundle (engine, session factory, ModelGateway, Postgres checkpointer factory) used by both API and scheduler modes, WorkflowRunner for cadence graphs with stable run ID as checkpoint thread/correlation, database+migration-aware readiness (/readyz returns component status and 503 when not ready; scheduler uses python -m ...readiness), OpenRouter provider support (MODEL_PROVIDER=openrouter, configurable frontier/batch models, mocked in routine tests), container health gated on HTTP readiness or readiness module, removal of file-based health markers. Initial Alembic migration covers workflow_run + LangGraph checkpoints (no claim_event). Updated operator docs and .env.example contract.
- Why: Prior harness-era implementation used temporary markers, insert-only runs, incomplete wiring, and inaccurate readiness; this repair makes execution, persistence, and operational probes match the durable design so that success is only reported after real graph completion and readiness reflects live DB state.
- User-visible impact: after Alembic reaches head, Compose starts FastAPI; a fresh volume requires the documented migration step. `docker compose up` now starts a real FastAPI on 8000 with /healthz (liveness) and /readyz (db/migrations); APP_PROCESS_MODE=scheduler runs registered cadence jobs; POST /workflows/trigger returns durable run records; readiness fails closed until migrations match head. OpenRouter selectable by supplying MODEL_PROVIDER and OPENROUTER_* directly to the application runtime environment (for direct non-Compose process execution) or via a user-supplied Compose override that explicitly adds `environment:` or `env_file:` (current compose.yaml does not forward these).
- Migration notes: One initial migration (963e5ab691b1) creates all core tables + checkpoint tables. Use Alembic for future revisions; downgrades supported where provided.
- Related PR/commit: Tasks 1-6 (c717d74, 1f88183, 3600a6a, f3d585d, 90a39fe+0bb9204, 86e41df+49ccabc); Task 7 documentation reconciliation is tracked in TODO.md. See accepted spec docs/superpowers/specs/2026-07-11-runtime-persistence-repair-design.md and plan.

## 2026-07-17 — Topic-First Analyst (Slice 1)

Summary:
- What changed: The topic became the top-level organising unit. New `Topic`
  entity (name, description, retained `interest_detail`, non-empty `keywords[]`)
  with `topic_id` on source/article/brief/ingestion_attempt; `article.source_id`
  and `ingestion_attempt.source_id` are now nullable (direct pasted-link/upload
  adds carry a topic but no source). Ingestion is keyword-filtered for topic
  relevance at two asymmetric points (title+summary before fetch — the recall
  ceiling; `cleaned_content` before persist — precision), via a pure
  deterministic matcher (`topics/matcher.py`, no embeddings); rejected
  candidates still record an observable `not_relevant` attempt. Pipelines,
  the scheduler, article/feed selection, and narrative-memory loading are all
  per-topic (`list_due_source_feeds`, `list_eligible_unbatched_articles`, and
  `get_narrative_version_as_of` gained `topic_id`; the brief unique
  index is now `(topic_id, cadence, covered_start, covered_end)`). New
  `TOPIC_ASSIST` gateway task + domain-general clarify/keyword-suggestion prompts
  (`topics/prompts.py`, R7a — no hard-coded domain vocabulary). API gained topics
  CRUD, stateless `POST /topics/clarify` + `POST /topics/suggest-keywords`
  (degrade to 503, never crash), `topic_id` on ingestion routes, and a `topic_id`
  brief filter. Frontend is now topic-first: a guided `TopicOnboarding`
  (interest → clarify → editable keyword chips → sources → create),
  `TopicSettings` (edit sources R6, re-suggest keywords R8), a topic selector,
  and a topic-scoped `AddContentPanel`; the old source-first `Onboarding` was
  removed.
- Why: The product is an analyst that follows and briefs a user about topics
  they choose. Article selection was previously global — every model call
  processed every ingested article regardless of what the user cared about — so
  "only Reuters articles about the US-Iran war" was inexpressible. Topic-scoping
  the whole pipeline (not just an onboarding form) is the load-bearing change.
- User-visible impact: Users start by naming a topic and describing their
  interest; the system asks AI-generated clarifying questions and suggests
  editable keywords, then filters every source to what's relevant to that topic.
  Users provide sources, paste links, add feeds, or upload files per topic;
  pasted/uploaded content joins the topic's article pool and waits for the next
  scheduled cadence (adding content never triggers a run, R5). Briefs are
  per-topic. Auto Search (SearXNG-backed source suggestion) and analysis-style
  are explicitly deferred to Slices 2 and 3.
- Migration notes: Revision `00f3ae192a5a` (on `6b135f7a55de`) adds the `topic`
  table and `topic_id` FKs, makes the two `source_id` columns nullable, and
  swaps the brief unique index. Upgrade seeds a `Default` topic (keywords
  sentinel `["__default__"]`) and backfills existing rows so `topic_id` lands
  non-null; adopted sources go dormant against the sentinel (accepted, spec §6).
  Run against a real Postgres (upgrade/downgrade + backfill).
- Related PR/commit: Tasks T1–T14, tracked in `TODO.md` (to be archived to
  `docs/iterations/archive/` on merge). Accepted spec
  `docs/superpowers/specs/2026-07-16-topic-first-analyst-design.md` and plan
  `docs/superpowers/plans/2026-07-16-topic-first-analyst.md`.
- Known gap: the R7a behavioral check (a live model call on 3 unlike subjects)
  was deferred as a billed call; the prompt was verified by static read + a
  structural 3-domain check + a domain-blocklist unit tripwire instead.

## <YYYY-MM-DD> — <Change Title>

Summary:
- What changed:
- Why:
- User-visible impact:
- Migration notes:
- Related PR/commit:
