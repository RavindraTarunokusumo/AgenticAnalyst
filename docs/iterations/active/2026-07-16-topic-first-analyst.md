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
- **R7 — Onboarding elicits interests in enough detail** that suggested
  keywords are accurate and relevant. A bare topic name is not sufficient
  input; the flow must draw out the specifics of the user's interest — and
  what they want excluded — before suggesting anything.
- **R7a — Onboarding is domain-general.** A topic is any subject the user wants
  followed: a conflict, a company, a technology, a sport, a scientific field, a
  person, a market. Neither the flow nor the prompts may assume a domain. What
  counts as a useful specific is *subject-dependent* — for a conflict it might
  be parties and regions; for a software release, versions and breaking
  changes; for a drug trial, compounds and phases; for a league, teams and
  transfers. The questions must be derived from the user's own description, not
  drawn from a fixed domain-shaped checklist. **No domain vocabulary may be
  hard-coded into the prompts** (see §3.5).
- **R8 — Keywords are AI-suggested and user-editable**, both during onboarding
  and when the user later revisits a topic's configuration. The user always
  sees and can edit the final keyword list; suggestion never silently decides
  what is tracked.

## 3. Data model

New `Topic` entity; `topic_id` threaded down the chain.

```
Topic (new)
  id, name, description, interest_detail?, keywords[], created_at, updated_at
    # name            - display label ("US-Iran war")
    # description     - user's free-text statement of interest
    # interest_detail - captured Q&A from the guided flow (R7), retained so
    #                   re-suggestion at edit time has the original context
    # keywords[]      - the actual matching terms (R8); user-editable
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

### 3.3 Decision — relevance is deterministic keyword matching only

Topic relevance is decided by matching a candidate's title/content against the
topic's `keywords[]`: case-insensitive, word-boundary, **any** keyword matches.
No model call per candidate.

Rationale: free, deterministic, fast, and testable without mocking a model —
which matters for the demo and for the suite. An LLM-per-candidate judge reads
nuance better but bills every ingested item.

**Embeddings are explicitly NOT used here.** An earlier draft of this spec
claimed pgvector embedding similarity was available as a free fallback. That is
wrong: `gateway.embed` is a billed DashScope `text-embedding-v4` call
(`models/gateway.py:80`, `models/dashscope.py:118`), so embedding each
candidate costs one API call per article — the exact cost profile rejected
above for the LLM judge. Keyword matching is the whole mechanism.

**Upgrade path:** the filter is a single injected predicate at the ingestion
boundary; swapping in an LLM or embedding judge later is a one-implementation
change and does not touch the schema.

### 3.4 Where matching happens — two points, asymmetric roles

Both points are pure string matching: no network, no model, no cost. But they
are **not** symmetric, and an earlier draft of this spec described them wrongly.

1. **Candidate stage (pre-fetch)** — sets the **recall ceiling.**
   Matched against title + feed summary (see §3.4.1). A miss is rejected
   *before* the page is fetched, which is what stops the system from
   downloading everything a source publishes. **Anything rejected here is never
   seen again** — no later stage can recover it.
2. **Post-extraction, pre-persist** — adds **precision only.**
   `cleaned_content` now exists; match again to drop candidates that matched a
   headline but whose body is off-topic. Only survivors are persisted,
   embedded, batched and summarised, satisfying R3.

**Correction to an earlier draft.** It claimed stage 2 "catches on-topic
articles whose title was vague." That is impossible: stage 1 already rejected
them, and stage 1 runs first by construction. Stage 2 can only ever *remove*
articles stage 1 admitted — it cannot add any back. Recall is decided entirely
at stage 1. Any reasoning that treats stage 2 as a recall safety net is wrong.

### 3.4.1 Decision — enrich the candidate with the feed summary

Because stage 1 alone decides recall, matching it against the title alone is
too lossy: "Talks collapse in Geneva" is on-topic for a US-Iran-war reader and
contains no keyword, so it would be dropped and never fetched. The user would
experience this as the product silently missing the story — the exact failure
they would notice.

`parse_feed` (`ingestion/feed_parser.py:58`) currently reads
`link`/`title`/`author`/`published_parsed`/`id` but ignores the entry summary,
which feedparser exposes for both RSS (`description`) and Atom (`summary`) and
which nearly every real feed carries. So:

- `ArticleCandidate` gains `summary: str | None`.
- `parse_feed` populates it from the entry.
- Stage 1 matches keywords against **title + summary**.

A large recall gain for a small parser/model change, at zero per-article cost.

**Alternatives rejected.** *Title-only matching* — cheapest, but concedes the
recall loss above for no saving worth having. *Fetch-then-filter on content
only* (drop stage 1, fetch every feed entry) — best possible recall and not
unbounded, since feed entries are a bounded set, but it pays a fetch and an
extraction for every article a source publishes, which is the cost profile this
whole design exists to avoid.

**Residual limitation, accepted:** an on-topic article whose title *and* feed
summary both avoid every keyword is still missed. This is the honest ceiling of
keyword matching, and the reason §3.3's upgrade path (swap the predicate for an
LLM/embedding judge) exists.

### 3.5 Decision — keywords are AI-suggested per topic, never per article

Keywords cannot be derived from the topic name by tokenising. "US-Iran war" →
`["us", "iran", "war"]` fails both ways: any-match drags in every Ukraine story
via "war"; all-match drops "Tehran nuclear talks collapse". So keywords are
suggested by a model call **at topic creation/edit time — once per topic, not
once per article** — and then edited by the user (R8). Ingestion stays free.

Implementation follows the existing per-task gateway pattern
(`ModelTask`/`get_model_for_task`/`generate`): one new `TOPIC_ASSIST` task
mapped to the cheap batch-summary-tier model, with two prompt builders in a new
`topics/prompts.py` mirroring `summarization/prompts.py`.

Two stateless routes, usable before a topic exists (onboarding) and after
(edit) — this is what makes one implementation serve both halves of R8:

- `POST /topics/clarify` — `{name, description}` → `{questions[]}`
  2-3 targeted clarifying questions generated from the user's description.
  This is the mechanism for R7: it draws out whatever specifics matter *for
  that subject*, rather than relying on the user to volunteer them into a text
  box.
- `POST /topics/suggest-keywords` — `{name, description, answers[]}` →
  `{keywords[]}`
  Suggested terms, returned for the user to accept/edit as chips.

**Decision — adaptive LLM questions over a static structured form.** This is
what makes the flow domain-general (R7a), and is the main reason to prefer it.
A fixed set of fields would be free and deterministic, but any such field set
encodes a domain: actors/regions/angles is a *geopolitics* form, and asking a
user tracking a database release which regions concern them is noise. Questions
generated from the user's own description adapt to conflicts, product launches,
clinical trials or transfer windows alike, and are also the interactive moment
the product wants at first-run. Cost is two calls per topic creation —
negligible, given per-article filtering is free.

**Prompt constraint (R7a).** The `TOPIC_ASSIST` system prompts must instruct the
model to derive its questions from the supplied description and must not
enumerate domain-specific dimensions to ask about. Worked examples inside the
prompt, if any, must span unlike domains (e.g. a software release, a sports
season, a public-health story) so no single domain's shape is learned as the
template. A prompt that reads "ask about the actors, regions and timeframe"
violates this requirement even though it would demo well on a geopolitics
topic.

**Fallback:** if either call fails, the flow degrades to a plain editable
keywords field rather than blocking topic creation. Suggestion is an
accelerator, not a dependency (see §6).

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
- **`list_due_source_feeds(session, now)` gains a `topic_id` filter** — see
  §4.1. This is not optional.

### 4.1 The poll loop must be topic-scoped too, not just selection

`DailyBriefPipeline.run` (`pipeline/daily_brief.py:79-93`) does **two** things
in one method: it polls `list_due_source_feeds(session, now)` — which is
global, with no source or topic filter (`repositories.py:735`) — and *then*
selects eligible articles.

Making the scheduler call `run()` once per topic without also scoping the poll
is a real bug, not an inefficiency: `poll_feed` updates each feed's
`last_polled_at`, so the **first** topic's run would poll every due feed in the
system — including other topics' feeds — and consume their due status. Every
subsequent topic in that cycle would then find its own feeds "not due" and
ingest nothing. Topic ordering would silently determine whose brief has
content.

Fix: `list_due_source_feeds` takes `topic_id` and joins through `source`, so
each topic's run polls only its own feeds.

This is exactly the cross-task breakage that per-task implementers cannot see:
whoever scopes article *selection* and whoever scopes the *scheduler* are each
individually correct while the system is broken. It is called out here so the
plan's task contracts can carry it.

Every existing pipeline/repository test asserting global selection or
one-brief-per-date semantics will need updating. This is expected, not a
regression.

## 5. Workflows

**Onboarding (new topic) — a guided flow, not one static form (R7):**
1. **Interest.** User names the topic and describes what they want to follow in
   free text. Any subject (R7a) — "the US-Iran war, mainly the nuclear talks
   and shipping disruption", "Postgres releases, only breaking changes and perf
   regressions", "GLP-1 drug trials and their outcomes".
2. **Clarify.** System asks 2-3 generated follow-up questions drawn from that
   description (`POST /topics/clarify`), asking about whatever is specific to
   *that* subject, and what to exclude. User answers.
3. **Keywords.** System suggests keywords from name + description + answers
   (`POST /topics/suggest-keywords`) and presents them as editable chips. User
   adds/removes freely; the list they accept is what actually gets matched (R8).
4. **Sources.** User-supplied domains/feeds. (Auto Search suggestion is Slice 2
   and attaches at this same step.)
5. Topic is created with its sources and keywords. **No brief is generated on
   the spot** — the first brief arrives on the next scheduled cadence (R5).

**Steady state:**
- Scheduled cadence runs per topic: poll that topic's sources → filter
  candidates for relevance (R3) → extract/batch/summarise **only** the
  survivors → emit one brief for that topic.
- User may edit the topic's sources at any time (R6). The same clarify /
  suggest-keywords routes back the edit view, so keywords can be re-suggested
  against the retained `interest_detail` rather than re-derived from scratch
  (R8).
- User may paste links / add feeds / upload files to a topic's article pool at
  any time; these wait for the next scheduled run (R5).

## 6. Edge cases and constraints

- **Migration + backfill.** Existing sources/articles/briefs have no topic. A
  "Default"/"Uncategorised" topic adopts existing rows, keeping `topic_id`
  non-null. Pre-existing rows are dev-only data at this stage — verify that
  before relying on it. **The Default topic needs a non-empty `keywords[]`**,
  since empty is rejected (below); it gets an explicit sentinel rather than
  tripping its own validation at migration time.
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
- **Keyword suggestion must never block topic creation.** If `clarify` or
  `suggest-keywords` errors or times out, the flow degrades to a plain editable
  keywords field. A topic with user-typed keywords and no AI assistance is a
  valid topic (§3.5).
- **A topic with an empty keyword list matches nothing**, which would silently
  ingest zero articles forever. Reject empty `keywords[]` at the API boundary
  rather than treating it as "match everything" — the failure mode of an
  accidentally-unfiltered topic is worse than a validation error.
- **Suggested keywords are untrusted model output** used to build a matching
  predicate. They must be treated as data (escaped/quoted when compiled into
  any regex), never interpolated into a pattern unescaped.

## 7. Proposed build order

The whole model is specified above; the work is staged so a demo-able vertical
slice lands first.

- **Slice 1 (this session) — topic-first core.** `Topic` entity + migration,
  `topic_id` on source/article/brief/attempt, keyword filter at both ingestion
  points (R3, §3.4), topic-scoped pipeline + scheduler (§4), topic CRUD +
  editable sources (R6), direct-article inputs bound to a topic (R4/R5),
  `TOPIC_ASSIST` gateway task + clarify/suggest-keywords routes (§3.5), guided
  onboarding UI (R7/R8) with editable keyword chips.
  → Demo: describe interest → answer 2-3 generated questions → accept suggested
  keywords → add Reuters → only US-Iran-war articles ingested → a topic-scoped
  brief renders.
- **Slice 2 (separate) — Auto Search.** Wire SearXNG: config, client, source
  suggestion, accept/reject UI. Isolated because it is the only genuinely new
  external integration and carries unknown connectivity risk.
- **Slice 3 (optional) — analysis style.** A tone/style preference threaded
  into `summarization/prompts.py`. Independent of everything above.

## 8. Success criteria

- A topic can be created with sources, and edited afterwards (R1, R2a, R6).
- Onboarding asks generated follow-up questions and proposes keywords the user
  can edit before anything is tracked; the flow still completes with keyword
  suggestion unavailable (R7, R8, §3.5).
- **Domain-generality is demonstrated, not assumed (R7a):** the flow is
  exercised end-to-end on at least three unlike subjects — e.g. a geopolitical
  conflict, a software release, and a sports season — and produces questions
  and keywords that are sensible for each. A flow that asks a Postgres-release
  topic which regions it concerns fails this criterion. The `TOPIC_ASSIST`
  prompts contain no hard-coded domain vocabulary.
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
