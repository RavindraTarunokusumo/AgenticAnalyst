# Lightweight Plan — Topic-First Analyst, Slice 1

**Spec:** `2026-07-16-topic-first-analyst.md` (§7 Slice 1 scope)
**Session:** `codex/topic-first-analyst`
**Delegation:** Grok, `-m grok-4.5 --effort medium` (implementer),
`-m grok-4.5 --effort high` (reviewer). Per-invocation flags, not repo config.

This is a contract, not a transcript. Implementers regenerate code from the
Interfaces below. The value here is the cross-task contract — who calls what,
in what order — because that is the class of breakage a per-task implementer
structurally cannot see (Workflow Rule 10).

## Cross-task breaking changes — read first

These signature changes each break callers **outside** the task that makes
them. Every one is a known trap; the owning task must update all listed
callers, and the main agent validates with the full suite (not the
implementer's scoped tests) before committing.

| Change | Owner | Breaks |
|---|---|---|
| `list_eligible_unbatched_articles(session, before_date, languages)` gains `topic_id` | T6 | `pipeline/daily_brief.py:96`; repository tests |
| `list_due_source_feeds(session, now)` gains `topic_id` (spec §4.1) | T6 | `pipeline/daily_brief.py:82`; repository tests |
| `ArticleCandidate` gains `summary` (spec §3.4.1) | T4 | `ingestion/feed_parser.py:68`; feed-parser tests; candidate fixtures |
| `DailyBriefPipeline.run(target_date)` gains a topic | T6 | `api/app.py` `/pipelines/daily`; `scheduling.py`; pipeline tests |
| `PeriodicBriefPipeline.run(...)` gains a topic | T6 | `api/app.py` `/pipelines/{weekly,monthly}`; `scheduling.py`; tests |
| `Brief` gains non-null `topic_id` | T1 | brief construction in `workflows/graphs.py`, both pipelines; every `Brief(...)` fixture |
| `Article` gains non-null `topic_id`; `source_id` becomes nullable | T1 | `_finalize_extracted`; `get_sources_by_ids` call at `daily_brief.py:135`; every `Article(...)` fixture |
| `IngestionService.__init__` gains a relevance matcher | T5 | `runtime.py:build_ingestion_service`; `tests/unit/test_ingestion_service.py` `build_service`; `tests/integration/test_ingestion_concurrency.py` |
| `ModelTask` gains `TOPIC_ASSIST` | T8 | `models/dashscope.py` + `models/openrouter.py` task maps (openrouter raises for unmapped tasks — mirror the EMBED precedent) |

**Fixture blast radius:** `Article`/`Brief` gaining a required `topic_id` will
break many existing fixtures. Prefer a test helper that supplies a default
topic over editing each call site.

**Docker-gated test trap** (`docs/insights.md`, 2026-07-15): Postgres-backed
tests skip *before* their body runs on this machine, so pydantic validation
inside them never executes locally. Any new domain-model constraint must have a
non-Docker unit test, or CI will find it first.

## Files

```
src/analyst_engine/
  domain/models.py                 T1  Topic; topic_id on Source/Article/Brief/IngestionAttempt
  persistence/models.py            T2  ORM columns + FKs
  persistence/migrations/          T2  Alembic revision + Default-topic backfill
  persistence/repositories.py      T3  topic CRUD; T6 topic-scoped selection
  topics/__init__.py               T4  new package
  topics/matcher.py                T4  pure keyword predicate
  topics/prompts.py                T8  clarify + suggest-keywords prompt builders
  models/gateway.py                T8  ModelTask.TOPIC_ASSIST
  models/dashscope.py              T8  task->model mapping
  models/openrouter.py             T8  unmapped-task raise (mirror EMBED)
  config.py                        T8  topic_assist_model, topic_assist_prompt_version
  ingestion/service.py             T5  thread topic; filter at both points
  runtime.py                       T5  inject matcher
  pipeline/daily_brief.py          T6  topic-scoped run
  pipeline/periodic_brief.py       T6  topic-scoped run
  scheduling.py                    T7  iterate topics per cadence
  api/app.py                       T9  topics CRUD, clarify, suggest, topic_id on ingestion, brief filter
frontend/src/
  api.ts                           T10 topic types + wrappers
  components/TopicOnboarding.tsx   T11 guided flow (replaces Onboarding.tsx)
  components/KeywordChips.tsx      T11 editable chips
  components/TopicSettings.tsx     T12 edit sources + re-suggest keywords
  App.tsx                          T13 wiring + topic selection
docs/                              T14 architecture, database, changelog
```

## Tasks

### T1 — Domain models
- **Consumes:** spec §3.
- **Produces:** `Topic(id, name, description, interest_detail?, keywords[], created_at, updated_at)`;
  `topic_id: UUID` on `Source`/`Article`/`Brief`/`IngestionAttempt`;
  `Article.source_id: UUID | None`.
- **Constraint:** reject empty `keywords[]` at the model boundary (spec §6) —
  empty must not mean "match everything".
- **Note:** pure pydantic, no infra imports (file's existing rule).

### T2 — Persistence + migration
- **Consumes:** T1.
- **Produces:** ORM columns/FKs; one Alembic revision creating `topic`,
  adding `topic_id`, making `article.source_id` nullable; backfill inserting a
  `Default` topic and adopting existing rows so `topic_id` lands non-null.
- **Trap:** the Default topic needs a non-empty `keywords[]` sentinel — T1
  rejects empty lists, so a naive backfill fails its own validation.
- **Risk:** first real migration for this feature class (last slice's enum
  needed none). Backfill must run inside the revision, not as a manual step.

### T3 — Topic repository
- **Consumes:** T1, T2.
- **Produces:** `create_topic`, `get_topic`, `list_topics`, `update_topic`,
  `delete_topic`, `list_sources_for_topic` following existing repository
  conventions in `repositories.py`.

### T4 — Keyword matcher + candidate summary (independent; parallelisable)
- **Consumes:** spec §3.3, §3.4, §3.4.1.
- **Produces:**
  - `matches(keywords: list[str], *fields: str | None) -> bool` —
    case-insensitive, word-boundary, any-match, in `topics/matcher.py`.
  - `ArticleCandidate.summary: str | None` (`ingestion/models.py`), populated by
    `parse_feed` from the feed entry (spec §3.4.1). feedparser exposes this as
    `summary` (Atom) / `description` (RSS); `parse_feed` currently ignores it.
- **Why the summary matters:** stage 1 sets the recall ceiling (spec §3.4) —
  anything it rejects is never fetched and never recoverable. Title-only
  matching drops "Talks collapse in Geneva". This is the single highest-leverage
  line in the slice for output quality.
- **Constraint:** keywords are untrusted model output (spec §6) — escape
  before compiling into any regex. Pure function: no I/O, no model, no network.
- **Tests:** word-boundary correctness ("war" must not match "Warsaw"),
  regex-metacharacter keywords, empty/None fields, feeds with no summary.

### T5 — Ingestion filtering
- **Consumes:** T1, T4.
- **Produces:** `IngestionService` takes a matcher; `poll_feed` resolves the
  feed's `source.topic_id` and its keywords, then filters at **two asymmetric
  points** (spec §3.4): title **+ summary** at candidate stage *before* fetch
  (recall ceiling — rejects here are unrecoverable), then `cleaned_content`
  post-extraction *before* persist (precision only — can only remove, never
  restore). `ingest_urls`/`ingest_file` take `topic_id` and set it on the
  article with `source_id=None` (spec §3.2).
- **Constraint:** a rejected candidate must still record an `IngestionAttempt`
  with a distinct error code (spec §6) — drops must be observable, not silent.
- **Interface note:** the matcher is one injected predicate (spec §3.3's
  upgrade path). Do not inline matching logic into the service.

### T6 — Pipeline scoping (load-bearing; spec §4)
- **Consumes:** T1, T2, T3.
- **Produces:**
  - `list_eligible_unbatched_articles` gains `topic_id` + WHERE clause.
  - **`list_due_source_feeds` gains `topic_id`, joining through `source`**
    (spec §4.1) — mandatory, not an optimisation. `run()` polls *and* selects;
    if only selection is scoped, the first topic's run polls every due feed in
    the system and consumes their `last_polled_at`, so every later topic in the
    cycle ingests nothing. Topic ordering would decide whose brief has content.
  - Both pipelines run per-topic and stamp `Brief.topic_id`.
- **Constraint:** `get_sources_by_ids` at `daily_brief.py:135` must tolerate
  articles with `source_id=None` (spec §3.2).
- **Reuse:** the existing empty-run path (`daily_brief.py:177`) already handles
  "no summaries selected" — a topic with zero matches must take it, not error.

### T7 — Scheduler
- **Consumes:** T3, T6.
- **Produces:** `register_schedules` iterates topics, running each cadence once
  per topic.
- **Constraint (R5):** scheduled cadence remains the *only* trigger. No route
  may run a pipeline as a side-effect of adding content.

### T8 — TOPIC_ASSIST gateway + prompts (independent; parallelisable)
- **Consumes:** spec §3.5, R7a.
- **Produces:** `ModelTask.TOPIC_ASSIST` mapped to the batch-summary-tier model;
  `build_clarify_messages(name, description)` and
  `build_keyword_suggestion_messages(name, description, answers)` in
  `topics/prompts.py`, mirroring `summarization/prompts.py` conventions.
- **Hard constraint (R7a):** prompts must derive questions from the user's
  description and must **not** enumerate domain-specific dimensions. No
  hard-coded domain vocabulary. In-prompt examples, if any, must span unlike
  domains. "Ask about the actors, regions and timeframe" violates this.

### T9 — API
- **Consumes:** T3, T5, T8.
- **Produces:** topics CRUD (incl. update/delete — net-new per R6);
  `POST /topics/clarify`, `POST /topics/suggest-keywords` (stateless, work
  pre-creation); `topic_id` on ingestion routes; topic filter on `GET /briefs`.
- **Constraint:** suggestion routes must degrade, not block — model failure
  returns a clear error the UI can fall back from (spec §6). All writes stay
  behind the existing `_require_key` dependency.

### T10-T13 — Frontend
- **Consumes:** T9's contract.
- **T10** `api.ts`: `Topic` type + wrappers for CRUD/clarify/suggest.
- **T11** guided onboarding (spec §5): interest → generated questions →
  editable keyword chips → sources. Must complete with suggestion unavailable.
- **T12** topic settings: edit sources (R6), re-suggest keywords against
  retained `interest_detail` (R8).
- **T13** `App.tsx`: topic selection; briefs scoped to selected topic.
- **Trap** (`docs/insights.md`, 2026-07-15): add new route prefixes to
  `vite.config.ts`'s dev proxy or they 404 under `npm run dev`.

### T14 — Docs
`docs/architecture.md`, `docs/database.md` (new table + migration),
`docs/changelog.md`.

## Build order

```
T1 -> T2 -> T3 ------> T6 -> T7 --.
                                   >-- T9 -> T10 -> T11,T12 -> T13 -> T14
T4 (parallel) -> T5 --------------'
T8 (parallel) --------------------'
```

- T4 and T8 are disjoint-file and depend on nothing in the T1→T3 chain — the
  only genuine parallel candidates (CLAUDE.md Step 4).
- T5 needs T4's predicate; T6 needs the T1→T3 foundation.
- Everything downstream of T9 is sequential on its contract.

## Risks

1. **T6 is the slice.** Topic-scoping article selection is where the green
   suite breaks. Budget for it; do not let T11's UI polish crowd it out.
2. **Migration + backfill** is the only irreversible-shaped step. Existing rows
   are dev-only, which is what makes the Default-topic adoption cheap — verify
   that assumption before relying on it.
3. **R5 is a negative requirement** — nothing proves it by passing. Needs an
   explicit test that adding content triggers no run.
4. **R7a is invisible to a passing test suite.** A geopolitics-shaped prompt
   demos perfectly on "US-Iran war" and fails silently on a software release.
   Verify against three unlike subjects (spec §8).
5. **Filter false-negatives are silent.** T5's attempt-recording is what makes
   them debuggable; treat it as load-bearing, not bookkeeping.
