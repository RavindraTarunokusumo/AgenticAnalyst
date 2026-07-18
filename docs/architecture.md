# System Architecture

## Entry Points

The local environment is defined in `compose.yaml` and contains exactly three
services:

- `app`: a single Agentic Analyst image. `APP_PROCESS_MODE=api` is the default;
  `scheduler` selects the scheduler process. The shared entrypoint (and main)
  validates the mode and constructs the runtime dependency bundle for both
  processes. In API mode the process serves a FastAPI application (uvicorn on
  port 8000) exposing liveness, readiness, workflow triggers, and read-only
  endpoints. In scheduler mode the process constructs the same runtime and
  registers APScheduler jobs that drive WorkflowRunner cadence execution.
- `postgres`: PostgreSQL 16 with pgvector, backed by the `postgres_data` named
  volume.
- `searxng`: self-hosted search, backed by the `searxng_config` named volume.
  Its settings template receives its required secret through the environment at
  first initialization; no real secret or fallback is committed. The bootstrap
  initializes the named configuration volume once, then preserves its secret
  and settings across restarts. SearXNG is available to the host at
  `http://localhost:8080` and to `app` at `http://searxng:8080`.

Compose waits for healthy PostgreSQL and SearXNG services before it starts the
application. Application health checks are implemented via the readiness
subsystem rather than temporary file markers: API mode probes the HTTP /readyz
endpoint; scheduler mode executes the readiness module directly. The app image
includes Crawl4AI and Playwright Chromium (installed at build), used as the
extraction fallback by the RSS ingestion pipeline (see Ingestion / Batching /
Summarization / Pipeline below).

## Module Structure

### Core / Infrastructure

- `config.py`: typed Settings (pydantic-settings) for direct application runtime configuration. MODEL_PROVIDER and OpenRouter settings (plus others like DATABASE_URL, APP_PROCESS_MODE, LangSmith flags) are read from process environment or .env; Compose currently forwards only a subset (APP_PROCESS_MODE, DASHSCOPE_*, DATABASE_URL, LANGSMITH_* etc.) and does not declare MODEL_PROVIDER or OPENROUTER_* .
- `runtime.py`: constructs the shared `RuntimeDependencies` bundle (engine, async session factory, ModelGateway, checkpointer factory, `httpx.AsyncClient`) from Settings; owns resource cleanup on close. `build_ingestion_service`/`build_daily_brief_pipeline`/`build_periodic_brief_pipeline` construct those services identically for API and scheduler, mirroring the pattern already used for `WorkflowRunner`. `build_ingestion_service` also constructs the `file_extractors` mapping (`{"application/pdf": PdfFileExtractor(), "text/plain": TextFileExtractor()}`) injected into `IngestionService`. `build_periodic_brief_pipeline` is cadence-parameterized; one instance is constructed per `Cadence.WEEKLY`/`Cadence.MONTHLY`.
- `persistence/engine.py`: async SQLAlchemy engine + session_scope helper.
- `persistence/checkpoints.py`: LangGraph AsyncPostgresSaver integration.

### Domain

- `domain/models.py`: pure Pydantic contracts (Topic, Source, Article, BatchSummary, Brief, NarrativeStateVersion, WorkflowRun, WorkflowStatus, ...). No infrastructure imports. `Topic` is the top-level unit (name, description, optional `interest_detail`, non-empty `keywords[]`); `Source`/`Article`/`Brief`/`IngestionAttempt` carry a `topic_id`, and `Article.source_id`/`IngestionAttempt.source_id` are nullable (pasted-link and uploaded-file adds carry a topic but no source, spec §3.2). `USER_PROVIDED_SOURCE_NAME` ("User-provided") is the display/prompt attribution when `source_id` is null. `ExtractorKind` (a plain `String(32)` column, no DB check constraint) gained `FILE_PDF`/`FILE_TEXT` members for uploaded-file ingestion - additive, no migration.
- `topics/`: topic-relevance and topic-assist support. `matcher.py`'s pure `matches(keywords, *fields)` is the deterministic relevance predicate (case-insensitive, ASCII word-boundary, any-match; `re.escape` on untrusted keywords — no embeddings, so no billed call). `prompts.py` builds the domain-general clarify / keyword-suggestion messages and their output schemas (`ClarifyingQuestions`, `SuggestedKeywords`); the prompts derive questions only from the user's own description and hard-code no domain vocabulary (R7a).

### Data / Persistence

- `persistence/models.py`: SQLAlchemy 2 ORM (mirrors migration schema, pgvector)
- `persistence/repositories.py`: session-scoped writes and lookups with explicit create/update for workflow runs, idempotency, citation helpers, and transition validation.
- `alembic/`: sole schema evolution (initial migration creates analytical tables + workflow_run + LangGraph checkpoint tables; no claim_event).

### Runtime Composition

- `main.py`: dispatches on APP_PROCESS_MODE to run_api (uvicorn factory) or run_scheduler (APScheduler + WorkflowRunner).
- `scheduling.py`: registers cadence jobs on the scheduler. Each cadence job lists topics and runs its pipeline **once per topic** (`run(date.today(), topic_id=...)`); each per-topic run is wrapped so one topic's failure cannot starve the rest of the cadence (spec §4.1). The scheduled cadence remains the only trigger (R5) — no route runs a pipeline as a side-effect of adding content.

### Services / Workflows

- `workflows/runner.py`: WorkflowRunner coordinates idempotent run lifecycle (ensure/claim), loads context, compiles and invokes the cadence graph with PostgreSQL checkpointer (using stable run ID for thread), and records succeeded/failed only after graph completion (or on error). Unchanged by the RSS ingestion or Weekly/Monthly Brief slices; the pipelines below only call `run_daily`/`run_weekly`/`run_monthly`, never claiming/checkpointing/persistence directly. `run_weekly`/`run_monthly` only normalize their window when `target_date` is omitted - callers that pass an explicit anchor must pre-normalize it (see `pipeline/periodic_brief.py`), since an unaligned date would silently create a misaligned/overlapping idempotency key.
- `workflows/graphs.py`: cadence-specific graph builders wired to the ModelGateway. After `save_brief`, the `synthesize` node best-effort embeds the brief content (`gateway.embed()`) and persists it (`save_embedding`) inside a `session.begin_nested()` SAVEPOINT - any failure there (model-side `ModelError` or a DB-side flush failure, e.g. a vector-dimension mismatch) is isolated to that SAVEPOINT and swallowed, so it cannot roll back the already-flushed brief/narrative/expectations in the same `session_scope` transaction. A bare `try/except` around `save_embedding` alone is not sufficient for the DB-side case: Postgres aborts the whole transaction on a failed statement, so the outer `session.commit()` would then raise `PendingRollbackError` too.
- `workflows/state.py`: workflow state contracts.

### Ingestion / Batching / Summarization / Pipeline

- `ingestion/canonicalize.py`: `canonicalize_url` - scheme/credential/host validation, SHA-256 fingerprint, deterministic query-param sorting; rejects private/loopback/link-local/multicast/reserved hosts (checked against every DNS answer, not just the first).
- `ingestion/bounded_http.py`: `bounded_fetch` - manual redirect walking (never delegates to httpx's follower) so every hop is re-validated through `canonicalize_url`, streamed size-limit enforcement, classified timeout/network errors.
- `ingestion/feed_client.py` / `feed_parser.py`: conditional-GET feed fetching (ETag/Last-Modified, 304 short-circuit) and pure RSS/Atom parsing into deterministically ordered candidates; tolerates malformed entries.
- `ingestion/html_clean.py`: stdlib-only (`html.parser`) deterministic title/language/body/publish-time/author extraction; no third-party HTML libraries.
- `ingestion/extractor.py`: `ArticleExtractor` protocol with `PrimaryHttpExtractor` (bounded HTTP + `html_clean`) and `Crawl4AIExtractor` fallback (real browser, used only when the primary result lacks a title or enough content); `should_use_fallback` is the pure trigger policy.
- `ingestion/file_extractor.py`: `FileExtractor` protocol (synchronous, no I/O) with `PdfFileExtractor` (`pypdf`-backed) and `TextFileExtractor` (UTF-8 decode, `errors="replace"`); both raise `FileExtractionError` when no usable text results. Title falls back to the filename stem when no PDF metadata title exists; `published_at` is always `None` from the extractor itself - `IngestionService.ingest_file` is what decides to stamp ingestion time, since the extractor has no clock.
- `ingestion/service.py`: `IngestionService` takes an injected relevance predicate (`matches`, wired in `runtime.build_ingestion_service`). `poll_feed` resolves the feed's `source.topic_id` and keywords, then filters at **two asymmetric points** (spec §3.4): title+summary at the candidate stage *before* fetch (this sets the recall ceiling — rejects here are never fetched and unrecoverable, which is why `ArticleCandidate` now carries the feed `summary`), then `cleaned_content` post-extraction *before* persist (precision only). `ingest_urls(topic_id, urls)` / `ingest_file(topic_id, ...)` are direct topic adds: they set `source_id=None` and are **not** relevance-filtered (a deliberate user choice, R4). `poll_feed`/`ingest_urls` share one `_ingest_candidate` path (canonicalize, dedup check before extraction, extraction with fallback, article-shape validation, race-safe persist with fingerprint-uniqueness reload-and-mark-duplicate). That shared dedup-check/finalize-persist tail is factored into `_check_duplicate`/`_finalize_extracted`, reused by `ingest_file(source_id, filename, content, content_type)` for uploaded files: computes `content_hash = sha256(content)`, builds a synthetic `url = f"upload://{content_hash}"`/fingerprint (no migration - dedup for uploads is content-hash-based, reusing the existing `Article.url`/`url_fingerprint` columns), looks up the matching `FileExtractor` from the `file_extractors: dict[str, FileExtractor]` mapping keyed by content-type (`unsupported_file_type` failure if no match), and on a `FileExtractionError` records an `extraction_failed` failure.
- `batching/batcher.py`: `batch_articles` - pure, deterministic: language partition, ordering, greedy seed-based title-token Jaccard grouping (3-5), carry-forward under 3, SHA-256 `batch_key`.
- `summarization/prompts.py` / `summarizer.py`: batch-summary prompt construction (delimited article blocks, explicit anti-prompt-injection system message) and `summarize_batch` (calls `ModelGateway` with `ModelTask.BATCH_SUMMARY`, validates citation article-ID membership and excerpt provenance before persistence).
- `pipeline/daily_brief.py`: `DailyBriefPipeline.run(target_date, *, topic_id)` - the sole entry point for the scheduler's daily job, `POST /pipelines/daily`, and `POST /workflows/trigger`'s daily branch. Runs are **per topic**: both `list_due_source_feeds` and `list_eligible_unbatched_articles` are topic-scoped (spec §4.1 — scoping selection alone is insufficient; the poll must be scoped too, or the first topic's run consumes every due feed's `last_polled_at` and starves the rest). Polls that topic's due feeds, selects its eligible unbatched articles, forms/reuses batches, creates/reuses summaries, selects summaries eligible for the target date that no *other* date's daily brief for that topic has already cited, then calls `WorkflowRunner.run_daily` and stamps `Brief.topic_id`.
- `pipeline/periodic_brief.py`: `PeriodicBriefPipeline` - the sole entry point for the scheduler's weekly/monthly jobs, `POST /pipelines/weekly`/`monthly`, and `POST /workflows/trigger`'s weekly/monthly branches. One cadence-parameterized class (`Cadence.WEEKLY` or `Cadence.MONTHLY`, two runtime instances). Normalizes an optional anchor date to the canonical Monday-Sunday week or calendar month using the exact formula `WorkflowRunner.run_weekly`/`run_monthly` use for their own default case, selects already-persisted `BatchSummary` rows whose batch has an article published in that window (`list_eligible_batch_summaries_for_window`) excluding any already cited for *this same cadence* and window (a summary already cited by a Daily brief remains independently eligible for its Weekly brief - citation tracking is per-cadence), then calls the unmodified `WorkflowRunner.run_weekly`/`run_monthly` with the computed window. Unlike Daily, it never ingests, batches, or summarizes - it only selects from evidence Daily has already produced.

### API / Delivery

- `api/app.py`: FastAPI application factory with lifespan that materializes runtime + runner + `IngestionService` + `DailyBriefPipeline` + `PeriodicBriefPipeline` (weekly, monthly) (via `runtime.build_ingestion_service`/`build_daily_brief_pipeline`/`build_periodic_brief_pipeline`, used identically by the scheduler) into app.state. Exposes:
  - `GET /healthz`: process liveness.
  - `GET /readyz`: database connectivity + current vs expected Alembic revision (503 when not ready).
  - `POST /workflows/trigger`: request schema accepts cadence, covered_start, covered_end. All three cadence branches delegate to their pipeline (`app.state.pipeline`/`weekly_pipeline`/`monthly_pipeline`, each `.run(req.covered_start)`) rather than calling `WorkflowRunner` directly, so a manual trigger always selects real persisted evidence instead of running the graph with an empty context. The returned `idempotency_key` reflects the pipeline's own normalized `covered_start`/`covered_end` (Monday-aligned for weekly, month-aligned for monthly), not the raw request value. Returns 409 if the pipeline reports no eligible content for the window (no `WorkflowRun` was created).
  - Topics: `POST /topics` (create), `GET /topics`, `GET /topics/{id}`, `PUT /topics/{id}` (edit, R6), `DELETE /topics/{id}` (204; 409 `TopicInUseError` when dependents exist, 404 when missing), `GET /topics/{id}/sources`. Writes behind `_require_key`; empty keywords → 422.
  - `POST /topics/clarify` / `POST /topics/suggest-keywords`: stateless topic-assist routes (no key — usable before a topic exists, during onboarding, and again from the edit view). Call the `TOPIC_ASSIST` gateway task; **degrade** to 503 on model failure (`Terminal`/`RetryableModelError`) rather than crashing, so the UI can fall back to manual keyword entry.
  - `POST /sources` / `GET /sources`: idempotent source + feed registration (canonicalizes every feed URL via `canonicalize_url`); `POST /sources` requires `topic_id`. Feed health listing.
  - `POST /ingestion/urls`: manual URL ingestion into a topic's article pool through `IngestionService.ingest_urls` (body `{topic_id, urls}`).
  - `POST /ingestion/files`: multipart (`topic_id`, `file`) manual upload of a PDF or plain-text file through `IngestionService.ingest_file`; reads the full body then rejects with `status="failed"`/`error_code="file_too_large"` (not a raw `413`, so the frontend's result renderer handles every failure mode uniformly) if it exceeds `settings.article_max_response_size_bytes` before extraction ever runs. Returns a single `IngestionResultResponse`, not a list. Same `_require_key` gate as `/sources` and `/ingestion/urls`.
  - `GET /ingestion/attempts`: recent attempts, optional status filter.
  - `POST /pipelines/daily`: triggers `DailyBriefPipeline.run` for a target date.
  - `POST /pipelines/weekly` / `POST /pipelines/monthly`: triggers `PeriodicBriefPipeline.run` for an anchor date (normalized to that week's Monday / that month's 1st); response mirrors the daily route's shape but scoped to `PeriodicPipelineResult`'s fields (no ingestion/batching counts, since this pipeline only selects and re-synthesizes).
  - `GET /briefs`: lists recent briefs by cadence (daily/weekly/monthly), with an optional `topic_id` query filter (briefs are per topic). `GET /briefs/{brief_id}`: full brief with every citation resolved to article title/URL/source name.
  - `GET /archive/search?q=<str>&cadence=<str|omit>&limit=<int=10>`: embeds `q` via `runtime.gateway.embed()`, then ranks briefs by cosine similarity via `search_embeddings_by_similarity` (`embedding` joined to `brief` on `brief_id`, ordered by `ORMEmbedding.vector.cosine_distance(query_vector)`; `brief.cadence` is the source of truth for the optional cadence filter, not `embedding.metadata`). Returns each result's `similarity_score` (`1 - cosine_distance`, computed in Python from the two vectors since the repository call returns domain objects, not raw SQL distances) and a bounded 280-char `content` snippet, not the full brief. `422` on a blank `q`, `limit` outside `1-50`, or an unknown `cadence` (same `Cadence(...)` pattern as `GET /briefs`); `503` if `embed()` raises `TerminalModelError` (e.g. OpenRouter, which has no embeddings endpoint) or `RetryableModelError` (a transient provider failure - distinct sanitized messages for each case); `200` with `[]` if no embeddings exist yet - never an error. Open read route, no `X-API-Key`.
  - Write/trigger routes (`/workflows/trigger`, `POST /sources`, `POST /ingestion/urls`, `POST /pipelines/daily`, `POST /pipelines/weekly`, `POST /pipelines/monthly`) require an `X-API-Key` header unless `settings.allow_unauthenticated_write` is explicitly true (local development only); read routes stay open.
  - `GET /ui/*`: `StaticFiles(directory=STATIC_DIR, html=True)` mounted last (after every `@app.get`/`@app.post` declaration), serving the built React brief-viewer SPA (see Frontend / UI below). Read-only, no auth - it only calls the existing open `GET /briefs`/`GET /briefs/{brief_id}` routes client-side.
- `api/readiness.py`: `check_readiness` implementation and a CLI entrypoint (`python -m analyst_engine.api.readiness`) used by scheduler container healthcheck.

### Frontend / UI

- `frontend/`: Vite + React + TypeScript + Tailwind CSS v4 (via `@tailwindcss/vite`, no `tailwind.config.js`) SPA, the repo's first Node/npm toolchain. `npm run build` outputs to `frontend/dist/` (gitignored); Vite's `base` is `/ui/` to match the backend mount path. `npm run dev`'s dev-server proxy (`vite.config.ts`) forwards `/briefs`, `/sources`, `/ingestion`, and `/topics` to `http://localhost:8000` - every path prefix `src/api.ts` fetches. `src/api.ts` holds typed fetch wrappers mirroring the backend's Pydantic response models field-for-field (`fetchBriefList` (optional topic filter)/`fetchBriefDetail`, topic CRUD `fetchTopics`/`fetchTopic`/`createTopic`/`updateTopic`/`deleteTopic`/`fetchTopicSources`, assist `clarifyTopic`/`suggestKeywords`, `registerSource` (topic-scoped), `ingestUrls`/`ingestFile` (topic-scoped)/`fetchIngestionAttempts`); all throw on any non-2xx response rather than swallowing errors, and every write wrapper sets `X-API-Key`. `src/components/` holds presentational components with no fetch calls of their own (`CadenceTabs`, `BriefList`, `BriefDetail`, `LoadingState`, `EmptyState`, `ErrorState`, plus the topic/ingestion set below); `src/App.tsx` owns all state via plain `useState` - no client-side routing library, no global store (YAGNI for this app's size). `BriefDetail` renders `content` only via JSX text interpolation (a `<pre>` text node), never `innerHTML`/`dangerouslySetInnerHTML`, since brief content is untrusted LLM-generated text.
- Topic-first UI: `App.tsx` gates on **topics** (`GET /topics`) — an empty list (or the "New topic" affordance) renders `<TopicOnboarding>` in place of the normal view; otherwise a header topic `<select>` drives `selectedTopicId`, briefs are scoped via `fetchBriefList(cadence, topicId)`, and a "Settings" toggle swaps in `<TopicSettings>`. `TopicOnboarding.tsx` is a guided flow (spec §5): interest → clarify (`clarifyTopic`, keyless) → editable keyword chips (`KeywordChips.tsx`) → optional first source → create (`createTopic` then `registerSource` with the new `topic_id`, keyed). It captures `interest_detail` from the clarify Q&A (for later re-suggestion, R8) and degrades gracefully — a clarify/suggest 503 drops the user onto the keyword step to enter keywords manually rather than dead-ending; create stays disabled until at least one keyword exists. It states plainly that no brief runs on creation (the first arrives on the next scheduled cadence, R5). `TopicSettings.tsx` lists/adds the topic's sources (R6) and re-suggests keywords against the retained `interest_detail` (`suggestKeywords`, R8) before saving via `updateTopic`. `AddContentPanel.tsx` adds to the selected topic's article pool (paste links / upload file → `ingestUrls`/`ingestFile` by `topic_id`); `IngestionResultList` falls back to a locally-known filename when displaying an uploaded file's synthetic `upload://<hash>` `candidate_url`. A **thrown** wrapper error (network failure, or a 401/403 from `_require_key`) is shown as a single inline "check your API key" panel error, distinct from a **successful** response whose items include per-URL/file `status: "failed"` entries. `RecentActivityList.tsx` (refetched via `GET /ingestion/attempts` after every submission) shows ingestion history. `ApiKeySettings.tsx` lets the key be viewed/replaced, writing to `localStorage['ae_api_key']`. The API key is client-held in `localStorage` by deliberate design (no login/session system exists in this slice) - not a gap to harden later.
- `src/analyst_engine/api/static/`: build output directory, tracked in git only as a minimal placeholder `index.html` ("run `npm run build`") so a fresh checkout's `uv run`/pytest never 404s at `/ui/` before a frontend build has run. `frontend/dist/`'s real build output overwrites this placeholder locally when `npm run build` is run, and the Dockerfile's `frontend-build` stage always produces the real one in the shipped image.
- `Dockerfile`'s first stage (`FROM node:22-slim AS frontend-build`) runs `npm ci && npm run build` against `frontend/`; the existing Python `runtime` stage then `COPY --from=frontend-build /app/frontend/dist ./src/analyst_engine/api/static` after its existing `COPY src ./src` line, so the shipped image remains one deployable artifact (no separate frontend service/container in Compose).
- `.github/workflows/ci.yml` runs a parallel `frontend` job (Node pinned via `frontend/.nvmrc`, `npm ci`, `npm run lint` (oxlint), `npm run build`, which also runs `tsc -b` as a type-check gate) alongside the existing Python `quality` job.

### Integrations

ModelGateway supports dashscope (default) or openrouter (selected by MODEL_PROVIDER at application runtime). OpenRouter uses the OpenAI-compatible chat completions endpoint with configurable frontier and batch-summary model aliases (plus fallbacks). LangSmith tracing is opt-in. SearXNG provides search. Provider selection and keys are supplied directly to the process (Compose does not forward MODEL_PROVIDER/OPENROUTER_*).

`ModelGateway` also declares an abstract `embed(*, text, correlation_id) -> tuple[list[float], ModelUsage]` for archive retrieval (`ModelTask.EMBED`, `text-embedding-v4`). `DashScopeAdapter.embed` calls `client.embeddings.create` (same error-mapping helper as `generate()`: timeout/rate-limit -> `RetryableModelError`, other API/unexpected -> `TerminalModelError`). `OpenRouterAdapter.embed` unconditionally raises `TerminalModelError` (no embeddings endpoint) - a one-line delegation to the same rejection `generate(task=EMBED)` already used.

## Data Flow

Startup and operation:

1. Compose creates or reuses the PostgreSQL and SearXNG named volumes.
2. PostgreSQL and SearXNG report their own health checks.
3. Compose starts `app` only after both dependencies are healthy.
4. `main` selects mode from `APP_PROCESS_MODE` (default api) and creates the
   shared runtime bundle via `create_runtime`.
5. API mode: lifespan creates a `WorkflowRunner` and stores it with the runtime
   in app state. `/readyz` runs a live DB connectivity check + compares
   `alembic_version` against the expected head from Alembic scripts; returns 503
   with component status when not ready. Trigger requests delegate to the runner
   which ensures a `WorkflowRun`, claims it, invokes the compiled checkpointed
   graph (thread_id = run ID), then updates the run to succeeded or failed.
6. Scheduler mode: creates the same runtime + runner, registers cadence jobs,
   and runs them; each job follows the same runner path producing durable runs.
7. On shutdown the runtime bundle disposes the engine exactly once.

## Background Jobs

Scheduler mode (APP_PROCESS_MODE=scheduler) runs APScheduler (AsyncIOScheduler)
and registers daily, weekly, and monthly cadence jobs. Each job lists topics and
invokes its pipeline **once per topic** (`run(date.today(), topic_id=...)`),
wrapping each per-topic run so one topic's failure cannot starve the rest of the
cadence (spec §4.1). All three jobs call
their pipeline's `.run()` rather than `WorkflowRunner.run_daily`/`run_weekly`/
`run_monthly` directly: the daily job invokes `DailyBriefPipeline.run(date.
today(), topic_id=...)` (polls that topic's feeds, batches, summarizes, then calls the runner); the
weekly job (Sunday 03:00) invokes `weekly_pipeline.run()` and the monthly job
(1st at 04:00) invokes `monthly_pipeline.run()` (each selects already-
persisted `BatchSummary` evidence for the current week/month, then calls the
runner) - the same rebinding pattern established for daily. Cron schedules are
unchanged; Sunday 03:00 already runs after that day's 02:00 daily job, so a
normal week's Sunday batch summaries are expected to exist by the time the
weekly job runs. Jobs are idempotent via the WorkflowRunner: duplicate
triggers for the same interval return the existing terminal or running run
without creating a second row. The runner drives checkpointed graph execution
using the workflow run ID as the stable correlation and checkpoint thread
identifier. Success is recorded only after graph invocation completes.

## External Integrations

### Local external services

| Dependency | Configuration | Failure behavior | Test strategy |
| --- | --- | --- | --- |
| PostgreSQL 16 + pgvector | Non-empty `POSTGRES_PASSWORD`, `POSTGRES_*`, and `DATABASE_URL` environment variables | Compose refuses configuration without the password; app startup is then gated on health (readiness 503) | Compose topology is structurally tested; integration tests use Testcontainers or the CI Postgres service. |
| SearXNG | Non-empty `SEARXNG_SECRET_KEY` and `SEARXNG_PUBLIC_BASE_URL` environment variables | Compose refuses configuration without the secret; app startup is then gated on health | Compose topology is structurally tested; no live search runs in routine tests. |

### Model providers

Application runtime configuration (via environment variables or .env loaded by Settings; Compose does not currently forward MODEL_PROVIDER or OPENROUTER_* variables — only APP_PROCESS_MODE, DASHSCOPE_*, DATABASE_URL, LANGSMITH_*, and SEARXNG_BASE_URL are declared in compose.yaml environment for the app service).

| Provider | Selection | Notes |
| --- | --- | --- |
| DashScope | `MODEL_PROVIDER=dashscope` (default) or unset | OpenAI-compatible; key and base URL required for live calls. |
| OpenRouter | `MODEL_PROVIDER=openrouter` + `OPENROUTER_API_KEY` etc. | OpenAI-compatible; configurable `OPENROUTER_FRONTIER_MODEL` and `OPENROUTER_BATCH_SUMMARY_MODEL` (with documented alternatives). Routine tests use mocked transport; live smoke is opt-in via env and never persists secrets. |

LangSmith is configured by environment (disabled by default). Adapters sit behind
the ModelGateway; provider selection lives in config and the factory.

## Invariants

- Local Compose declares exactly `app`, `postgres`, and `searxng` services.
- PostgreSQL and SearXNG state lives in named volumes and survives `docker
  compose down` without `--volumes`.
- The application never starts before PostgreSQL and SearXNG are healthy.
- Both API and scheduler modes receive a complete, non-None runtime dependency
  bundle (engine, sessions, gateway, checkpointer factory).
- A workflow run cannot transition to succeeded unless its graph invocation
  completed; duplicate triggers for the same idempotency key never create
  additional rows.
- Secrets are supplied through environment variables and are not committed to
  Compose settings or application source; the Compose secrets have no fallback
  values.
- `SEARXNG_SECRET_KEY` is written only when an empty `searxng_config` volume is
  initialized. Changing it later does not replace the persisted SearXNG secret.
- Readiness returns only sanitized component status (no credentials or full
  exception bodies); 503 is used for not-ready.

## SearXNG Secret Lifecycle

The initial `SEARXNG_SECRET_KEY` is deliberately immutable for an existing
`searxng_config` volume. This prevents an ordinary restart or `.env` edit from
silently invalidating the SearXNG configuration. To rotate a secret, stop the
stack, remove **only** the SearXNG configuration volume, set the replacement
`SEARXNG_SECRET_KEY`, then start the stack again. PostgreSQL data is unaffected:

```bash
docker compose down
docker volume rm analyst-engine_searxng_config
docker compose up --build --wait
```

Use `docker compose volume ls` to confirm the actual Compose project prefix if
the stack is started with a custom project name. This procedure resets SearXNG
configuration to the tracked template; reapply any local SearXNG settings after
the restart.
