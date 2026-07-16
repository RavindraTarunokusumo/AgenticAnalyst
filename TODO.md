# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

### Session: Topic-First Analyst — Slice 1 (`codex/topic-first-analyst`)

Spec: `docs/superpowers/specs/2026-07-16-topic-first-analyst-design.md` (`8e3c6da`, `cdf60ff`)
Plan: `docs/superpowers/plans/2026-07-16-topic-first-analyst.md` (`73aa05b`)

Topic becomes the top-level unit: sources are scoped to a topic, fetching is
keyword-filtered before any model call, and briefs are per-topic. Auto Search
(SearXNG) is Slice 2; analysis style is Slice 3.

- [x] **T1** Domain models — `Topic`; `topic_id` on Source/Article/Brief/
      IngestionAttempt; `Article.source_id` nullable; reject empty `keywords[]`
- [x] **T1b** Handle source-less articles in `src/` — *added mid-session
      (Rule 2); the plan's breaking-change table listed only
      `daily_brief.py:135` and missed three more call sites, found by the
      post-T1 full gate.* `summarizer._build_article_source_lookup` **raises**
      on a null `source_id`, so a pasted link or upload (source-less by design,
      spec §3.2) would crash the brief pipeline — the R4 feature breaking the
      moment it is used. Also `daily_brief.py:136`, `api/app.py:581,603`.
      Fallback attribution: `USER_PROVIDED_SOURCE_NAME` ("User-provided").
      Source-id sites are mypy-clean; remaining `mypy src` errors are
      missing `topic_id` in later-task call sites (T2–T6 ownership).
- [x] **T2** Persistence + Alembic migration + Default-topic backfill
      (needs keywords sentinel — empty is rejected by T1). ORM `Topic`
      table; `topic_id` FK on source/article/brief/ingestion_attempt;
      `article.source_id` nullable. Revision `00f3ae192a5a` revises
      `6b135f7a55de`: create topic → insert Default with keywords
      `["__default__"]` → backfill → NOT NULL. Executed against real
      Postgres (upgrade/downgrade + seeded backfill).
- [x] **T3** Topic repository (CRUD + `list_sources_for_topic`) (`859ef11`)
      - [x] `create_topic` / `get_topic` / `list_topics` / `update_topic` /
            `delete_topic` / `list_sources_for_topic` in repositories.py
      - [x] Postgres-backed repository tests (round-trip, list order, update
            keywords, delete with sources attached, list_sources_for_topic)
- [ ] **T4** Keyword matcher (`topics/matcher.py`) + `ArticleCandidate.summary`
      populated by `parse_feed` (spec §3.4.1 — sets the recall ceiling)
- [ ] **T5** Ingestion filtering — matcher injected; filter at both asymmetric
      points; rejected candidates still recorded as observable attempts
- [ ] **T6** Pipeline scoping — `list_eligible_unbatched_articles` **and**
      `list_due_source_feeds` gain `topic_id` (spec §4.1); per-topic runs
- [ ] **T7** Scheduler iterates topics (R5: cadence stays the only trigger)
- [ ] **T8** `ModelTask.TOPIC_ASSIST` + `topics/prompts.py`
      (R7a: no hard-coded domain vocabulary)
- [ ] **T9** API — topics CRUD, `/topics/clarify`, `/topics/suggest-keywords`,
      `topic_id` on ingestion routes, brief topic filter
- [ ] **T10** `api.ts` topic types + wrappers
- [ ] **T11** Guided onboarding UI + editable keyword chips
- [ ] **T12** Topic settings — edit sources (R6), re-suggest keywords (R8)
- [ ] **T13** `App.tsx` wiring + topic selection (add dev-proxy prefixes)
- [ ] **T14** Docs — architecture, database, changelog

## Future Backlog

Candidate next slices, roughly in suggested priority order. None have a spec
yet; each needs Workflow Step 3 (spec + lightweight plan) before
implementation. See chat/session notes from 2026-07-15 for the full rationale
behind this ordering.

- [ ] **Onboarding personalization (topics of interest / analysis style).**
      Raised 2026-07-16 while manually reviewing the just-merged Product UI
      Refinement slice (`docs/iterations/archive/2026-07-16-product-ui-refinement.md`).
      The onboarding form has no way to express *what* to track within a
      source (e.g. "follow the US-Iran war on Reuters," not just register
      `reuters.com` wholesale) - there is no topic/keyword field anywhere in
      the domain model (`Source` has none; `topics` only ever exists as an
      LLM-*output* on `BatchSummary`, never a user input), and no
      personalization concept (e.g. an analysis-style/tone preference) at
      all. Framed explicitly as a gap for a hackathon demo, not a design
      nitpick - judges will type their own topic and notice it's
      inexpressible. Confirmed by code inspection (2026-07-16) that no layer
      of the pipeline is topic-aware: `poll_feed` ingests every feed entry
      indiscriminately (no keyword gate before extraction/persist);
      `ingest_urls`/`ingest_file` only process exactly what's handed to
      them (a user can manually curate topic-specific URLs themselves, but
      the system does no targeting); extraction is pure content-parsing
      with no relevance scoring; `batching/batcher.py` clusters
      *already-ingested* articles by title-token similarity, it doesn't
      filter what gets ingested; and SearXNG is provisioned and running in
      `compose.yaml` but is not referenced anywhere in the Python source -
      infrastructure that exists but is completely unwired into ingestion.
      Suggested prioritization (highest impact per effort first):
      (1) a "topics of interest" field on the onboarding form, stored on
      `Source`, used as a keyword/content filter applied at ingestion/poll
      time (reject candidates whose title/content doesn't match before
      persisting) - cheapest, and the most direct fix for "only Reuters
      articles about the US-Iran war," reusing the existing `topics`
      extraction machinery; (2) a short multi-step guided onboarding flow
      (source -> topics -> style) instead of one static form, for the
      "personalization is happening" feel; (3, stretch) wiring SearXNG for
      actual topic-directed *discovery* within a source (turns "register a
      feed" into "periodically search this domain for X") - bigger, since
      it's genuinely new ingestion capability, not just a filter on
      existing feeds; (4, stretch) an analysis-style toggle threaded into
      `summarization/prompts.py`'s brief-generation prompt - touches the
      summarization pipeline, not just ingestion. Needs its own spec before
      scoping.
- [ ] **Prediction expectation resolution.** `PredictionExpectation` rows
      are created by the frontier synthesis graph (`proposed_expectations`)
      with `outcome_status`, but nothing ever revisits and updates that
      status later (no confirm/falsify job or route). The falsifiable-
      predictions concept is half-built: expectations are proposed but never
      checked against what actually happened.
- [ ] **claim_event / contradiction graph.** Explicitly deferred since the
      initial migration (`docs/database.md`); no schema, no design started.
      Likely the largest single slice on this list - needs its own spec
      before scoping, not a quick follow-on.
