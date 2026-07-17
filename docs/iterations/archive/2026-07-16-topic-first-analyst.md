# 2026-07-16 — Topic-First Analyst, Slice 1 (codex/topic-first-analyst)

**Merge:** PR #9 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/9)
**Merge commit:** 6348d9097b5ecce7af6204350deb14f52e5e3142
**Feature branch:** codex/topic-first-analyst
**Merged:** 2026-07-17T17:33:54Z

Spec: `docs/superpowers/specs/2026-07-16-topic-first-analyst-design.md` (`8e3c6da`, `cdf60ff`)
Plan: `docs/superpowers/plans/2026-07-16-topic-first-analyst.md` (`73aa05b`)

The topic becomes the top-level unit: sources are scoped to a topic, fetching is
keyword-filtered before any model call, and briefs are per-topic. Auto Search
(SearXNG) is Slice 2; analysis style is Slice 3.

## Completed Work

- [x] **T1** Domain models — `Topic`; `topic_id` on Source/Article/Brief/
      IngestionAttempt; `Article.source_id` nullable; reject empty `keywords[]`
- [x] **T1b** Source-less articles in `src/` (Rule 2) — `summarizer.
      _build_article_source_lookup` raised on null `source_id` (would crash the
      brief pipeline for pasted links/uploads, spec §3.2); fallback attribution
      `USER_PROVIDED_SOURCE_NAME`. Also `daily_brief.py:136`, `api/app.py:581,603`.
- [x] **T2** Persistence + Alembic migration + Default-topic backfill. Revision
      `00f3ae192a5a` on `6b135f7a55de`: create topic → seed Default (keywords
      sentinel `["__default__"]`) → backfill → NOT NULL. Executed against real
      Postgres (upgrade/downgrade + seeded backfill).
- [x] **T3** Topic repository CRUD + `list_sources_for_topic` (`859ef11`);
      Postgres-backed repository tests.
- [x] **T4** Keyword matcher (`topics/matcher.py`) + `ArticleCandidate.summary`
      from `parse_feed` (spec §3.4.1 — recall ceiling) (`8b3e10d`, `2d5fca9`).
- [x] **T5** Ingestion filtering — matcher injected; filter at both asymmetric
      points; rejects recorded as `not_relevant` attempts; `ingest_urls`/
      `ingest_file` take `topic_id`, `source_id=None`, unfiltered
      (`cfc7114`, `ec266aa`, `9b4482c`).
- [x] **T5b** Make `ingestion_attempt.source_id` nullable (`2f319b2`, Rule 2) —
      proven against real Postgres (not-null violation on source-less insert);
      folded into revision `00f3ae192a5a`.
- [x] **T6** Pipeline scoping (load-bearing, spec §4.1) —
      `list_eligible_unbatched_articles` **and** `list_due_source_feeds` gain
      `topic_id`; per-topic runs; brief unique index made topic-scoped
      (`d29d35b`, `ecf3e17`, `b69076a`, `709dfb9`). §4.1 poll-starvation
      regression test included.
- [x] **T7** Scheduler iterates topics with per-topic error isolation (R5)
      (`7758fac`).
- [x] **T8** `ModelTask.TOPIC_ASSIST` + domain-general `topics/prompts.py`
      (R7a); mapped in both provider task maps (`a240aa4`). R7a verified by
      static read + structural 3-domain check + a domain-blocklist tripwire;
      behavioral live-model check deferred (billed call).
- [x] **T9** API — topics CRUD, stateless `/topics/clarify` + `/topics/
      suggest-keywords` (503-degrade), `topic_id` on ingestion routes (fixed a
      latent T5 mismatch), brief topic filter (`97be67d`).
- [x] **T10** `api.ts` topic types + wrappers; fixed already-broken
      `RegisterSourceRequest` (missing `topic_id`); ingest bodies use
      `topic_id`; `/topics` dev proxy (`b315088`).
- [x] **T11** Guided onboarding (`TopicOnboarding.tsx`) + editable
      `KeywordChips.tsx` (spec §5); graceful assist degradation; `interest_detail`
      from Q&A (R8) (`2588694`).
- [x] **T12** `TopicSettings.tsx` — edit sources (R6), re-suggest keywords
      against retained `interest_detail` (R8) (`d1adc7f`).
- [x] **T13** `App.tsx` topic-first wiring + topic selector; `AddContentPanel`
      refactored to topic article pool; old `Onboarding.tsx` deleted. Build green
      end-to-end and driven against a live Postgres (contract verified)
      (`ca7532c`).
- [x] **T14** Docs — architecture, database, changelog (`f36e539`).

### Code review fixes (PR #9, Grok bundled review — Rule 2)

- [x] **R1** (`e4122f3`) `IngestionAttemptResponse.source_id` / TS type made
      nullable — a source-less direct add otherwise 500s the whole
      `GET /ingestion/attempts` listing. Route-level regression test added.
- [x] **R2** (`0a88822`) Narrative load topic-scoping — `get_narrative_version_
      as_of` was global while prior briefs were topic-scoped (T6); scoped by
      `ORMBrief.topic_id` (no migration — reachable per-topic through the brief).
- [x] CI fix (`820c4c7`) — `ruff format` on T7/T8/T9 files (local gate ran
      `ruff check` but not `ruff format --check`).

### Deferred to a follow-up slice

- **Composite-uniqueness so two topics can share a source/URL** (confirmed a
  real requirement by the user — same source across topics is wanted).
  `(topic_id, stable_id)` on source, `(topic_id, url_fingerprint)` on article,
  `(topic_id, feed_url_fingerprint)` on source_feed. Needs a migration. Today:
  re-registering a shared source silently reassigns it, and the same URL under a
  second topic is dup-suppressed against the first topic's article. Carried into
  the Future Backlog. (Also deferred: topic delete blocked by `not_relevant`
  attempts — a deliberate `ON DELETE RESTRICT` UX nit.)
