# Spec — Topic-First Analyst

**Status:** DRAFT — awaiting acceptance (Workflow Step 3)
**Session:** `codex/topic-first-analyst`
**Raised:** 2026-07-16

## 1. Problem

The product is an **analyst agent that follows, analyses and briefs users about
the topics they are interested in** (e.g. "the US-Iran war"). The current
implementation has no concept of a topic at all.

Confirmed by code inspection (2026-07-16):

- `Source` (`domain/models.py:77`) has `id`/`stable_id`/`name`/
  `normalized_domain`/`created_at`. No topic.
- `Article`, `Brief` (`domain/models.py:213`) have no topic field. `topics`
  exists only as an LLM-*output* on `BatchSummary`, never a user input.
- `list_eligible_unbatched_articles(session, before_date, languages)`
  (`persistence/repositories.py:860`) selects articles **globally** by
  publish-date and language. Not scoped by source, let alone topic.
- `DailyBriefPipeline.run(target_date)` (`pipeline/daily_brief.py:79`) polls
  *all* due feeds, batches *all* eligible articles, and emits **one brief per
  cadence per date** across everything ingested.
- `POST /sources` and `GET /sources` exist; there is **no** update or delete
  route. Sources are add-only.
- SearXNG is provisioned in `compose.yaml`, and `SEARXNG_BASE_URL` is passed
  into the app container, but there are **zero** Python references to it
  (`config.py` does not even read the variable; only
  `tests/test_compose_structure.py` mentions it). It is dead infrastructure.

Consequence: a user can register `reuters.com`, but cannot say *what* to follow
there. Every article Reuters publishes is ingested, and every brief mixes all
sources and all subjects together. The core product promise is not implemented.

## 2. Requirements

Derived from the product direction as stated by the user (2026-07-16). Each is
load-bearing; R3, R5 and R6 are the ones easiest to violate accidentally.

- **R1 — Topic is the top-level unit.** A user's entry point is creating a
  topic ("US-Iran war"), not registering a source. Topics are the organising
  entity that sources, articles and briefs hang off.
- **R2 — Sources are scoped to a topic**, and are populated two ways:
  (a) user-provided (Reuters, CNN, ...), or (b) **Auto Search** — the system
  searches the web to *suggest* sources for the topic.
- **R3 — Fetching is topic-filtered at the source.** The fetcher pulls from a
  topic's configured sources only what is relevant to that topic, and **every
  subsequent model call processes only those articles.** This is not a
  post-hoc filter on output; irrelevant articles must not reach extraction,
  batching, summarisation or briefing.
- **R4 — Direct article inputs.** Pasted links, RSS feeds and file uploads add
  **articles, not sources**, to a topic's article pool.
- **R5 — Direct article inputs do NOT trigger a briefing run.** They are added
  to the pool and picked up by the *next scheduled* daily/weekly/monthly run.
  The cadence is unchanged. No "ingest now → brief now" path may be added.
- **R6 — Sources are editable.** A user can add, remove and modify a topic's
  configured sources after onboarding. This is net-new API surface.

## 3. Data model

New `Topic` entity; `topic_id` threaded down the chain.

```
Topic (new)
  id, name, description?, keywords[], created_at, updated_at
Source
  + topic_id (FK)          # a source belongs to a topic
Article
  + topic_id (FK)          # denormalised for query scoping (see 3.1)
Brief
  + topic_id (FK)          # one brief per topic per cadence per date
IngestionAttempt
  + topic_id (FK)          # observability parity
```

Requires a **real Alembic migration** (unlike the last slice's additive enum),
plus a backfill decision for existing rows — see §6.

### 3.1 Decision — Article.topic_id is denormalised, not derived

`Article.topic_id` duplicates what `Source.topic_id` already implies. It is
carried explicitly because (a) directly-added articles (R4) may have no
meaningful source, and (b) the hot selection query (§4) would otherwise need a
join on every brief run. Rationale recorded so the redundancy is deliberate.

### 3.2 Decision — directly-added articles use a nullable `source_id`

Pasted links / uploads set `article.topic_id` and leave `source_id` NULL,
rather than inventing a synthetic per-topic "manual source". A synthetic source
would pollute `GET /sources` (R6's editable list) with rows the user never
added and cannot meaningfully edit. Cost: `source_id` becomes nullable, and the
brief pipeline's `get_sources_by_ids` lookup (`daily_brief.py:135`) must
tolerate articles with no source.

**Alternative rejected:** synthetic source keeps `source_id` non-null but
requires filtering it out of every source-facing view.

### 3.3 Decision — relevance is a deterministic keyword/embedding filter

Topic relevance is decided by matching a candidate's title/content against the
topic's `keywords[]` (with the existing pgvector embedding available as a
similarity fallback), **not** by an LLM relevance call per candidate.

Rationale: deterministic, free, fast, and testable without mocking a model —
which matters for a demo and for the test suite. An LLM-per-candidate judge is
better at nuance ("Tehran talks" is about the US-Iran war without naming it)
but adds cost and latency to every ingested item.

**Upgrade path:** the filter is a single injected predicate at the ingestion
boundary; swapping in an LLM judge later is a one-implementation change and
does not touch the schema.

## 4. The load-bearing change — pipeline scoping

This is the requirement most likely to break the currently-green suite, and it
is *not* the onboarding form.

Today: `run(target_date)` → global article selection → one brief.
Required: `run(target_date, topic_id)` → topic-scoped selection → one brief
**per topic**.

Concretely:
- `list_eligible_unbatched_articles(session, before_date, languages)` gains a
  `topic_id` parameter and a `WHERE article.topic_id = :topic_id` clause.
- `DailyBriefPipeline.run` / `PeriodicBriefPipeline.run` take a topic and
  return a per-topic result.
- The scheduler (`scheduling.py`) iterates topics and runs the pipeline once
  per topic per cadence, rather than once globally.
- `Brief` gains `topic_id`; `GET /briefs` gains a topic filter.
- Feed polling (`list_due_source_feeds`) already returns feeds globally; each
  feed's `source.topic_id` determines which topic its candidates are filtered
  against.

Every existing pipeline/repository test asserting global selection or
one-brief-per-date semantics will need updating. This is expected, not a
regression.

## 5. Workflows

**Onboarding (new topic):**
1. User names a topic and describes what they want to follow.
2. Sources: either user-supplied domains/feeds, or **Auto Search** suggests
   candidates the user accepts/rejects.
3. Topic is created with its sources. No brief is generated on the spot — the
   first brief arrives on the next scheduled cadence (R5).

**Steady state:**
- Scheduled cadence runs per topic: poll that topic's sources → filter
  candidates for relevance (R3) → extract/batch/summarise **only** the
  survivors → emit one brief for that topic.
- User may edit the topic's sources at any time (R6).
- User may paste links / add feeds / upload files to a topic's article pool at
  any time; these wait for the next scheduled run (R5).

## 6. Edge cases and constraints

- **Migration + backfill.** Existing sources/articles/briefs have no topic.
  Backfill strategy must be decided at plan time: a "Default"/"Uncategorised"
  topic that adopts existing rows is the cheapest option and keeps `topic_id`
  non-null. Pre-existing rows are dev-only data at this stage.
- **A topic with zero relevant articles** in a window must not error — the
  existing "no summaries selected" path (`daily_brief.py:177`) already handles
  an empty brief run and should be reused per-topic.
- **Relevance filter false-negatives** silently drop content. Every rejected
  candidate must still be recorded as an `IngestionAttempt` with a distinct
  status/error code so the drop is observable, not invisible.
- **Auto Search connectivity.** SearXNG is unwired and unvalidated from Python;
  its reachability, response shape and failure modes are unknown. Treated as a
  risk, and isolated in its own slice (§7).
- **R5 is a negative requirement.** No route may run a pipeline as a
  side-effect of adding content. Worth an explicit test.

## 7. Proposed build order

The whole model is specified above; the work is staged so a demo-able vertical
slice lands first.

- **Slice 1 (this session) — topic-first core.** `Topic` entity + migration,
  `topic_id` on source/article/brief/attempt, relevance filter at ingestion
  (R3), topic-scoped pipeline + scheduler (§4), topic CRUD + editable sources
  (R6), direct-article inputs bound to a topic (R4/R5), onboarding UI creating
  a topic with user-supplied sources.
  → Demo: create topic → add Reuters → only US-Iran-war articles ingested →
  a topic-scoped brief renders.
- **Slice 2 (separate) — Auto Search.** Wire SearXNG: config, client, source
  suggestion, accept/reject UI. Isolated because it is the only genuinely new
  external integration and carries unknown connectivity risk.
- **Slice 3 (optional) — analysis style.** A tone/style preference threaded
  into `summarization/prompts.py`. Independent of everything above.

## 8. Success criteria

- A topic can be created with sources, and edited afterwards (R1, R2a, R6).
- An article from a topic's source that does not match the topic is **not**
  extracted, batched, summarised or briefed — and its rejection is recorded as
  an observable attempt (R3).
- Pasted links / feeds / uploads attach to a topic's article pool and trigger
  **no** pipeline run; they appear in the next scheduled brief (R4, R5).
- Briefs are per-topic; two topics produce two independent briefs for the same
  date (§4).
- Full gate green: `ruff format --check` / `ruff check` / `mypy src tests` /
  `pytest` (incl. Docker-backed integration), `npm run lint` / `npm run build`.

## 9. Out of scope

- Auto Search / SearXNG (Slice 2).
- Analysis-style personalisation (Slice 3).
- Multi-user / auth model — the client-held API key pattern is unchanged.
- Prediction-expectation resolution, claim/contradiction graph (pre-existing
  backlog, unrelated).
