# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

### Active: Multi-Topic Source Sharing (composite uniqueness)

Spec: `docs/superpowers/specs/2026-07-17-multi-topic-source-sharing-design.md`
Plan: `docs/superpowers/plans/2026-07-17-multi-topic-source-sharing.md`
Branch: `codex/multi-topic-sources`

- [ ] **M1** ORM composite uniqueness — drop inline `unique=True` on
      `source.stable_id` / `article.url_fingerprint` /
      `source_feed.feed_url_fingerprint`; add composite `UniqueConstraint`s.
- [ ] **M2** Alembic migration (`down_revision = 00f3ae192a5a`) — drop the three
      global unique constraints, create the composites; reversible.
- [ ] **M3** Repository scoping — `get_source_by_stable_id` / `upsert_source`
      by `topic_id`; `get_article_by_fingerprint` by `topic_id`;
      `get_source_feed_by_fingerprint` / `upsert_source_feed` by `source_id`.
- [ ] **M4** Caller ripple — `api/app.py` register_source, `ingestion/service.py`
      dedup (×2), `tests/integration/test_topic_scoped_pipeline.py` call sites.
- [ ] **M5** Discriminating acceptance test — same `stable_id` + same
      `url_fingerprint` under two topics → two rows each, no raise (fails on `main`).
- [ ] **M5b** (extension, Rule 2) Test ripple caught by the full gate that Grok's
      scoped run missed: `test_ingestion_service.py` fakes for
      `get_article_by_fingerprint` needed the new `*, topic_id` kwarg; and
      `test_readiness_checks.py`'s hard-coded migration-head constant bumped to
      the new head `b8e4c1a09f3d`.
- [ ] **M6** Docs — `docs/database.md` uniqueness scopes, `docs/changelog.md`.

Prior: Topic-First Analyst — Slice 1, merged as PR #9
(`docs/iterations/archive/2026-07-16-topic-first-analyst.md`).

## Future Backlog

Candidate next slices, roughly in suggested priority order. None have a spec
yet; each needs Workflow Step 3 (spec + lightweight plan) before
implementation. See chat/session notes from 2026-07-15 for the full rationale
behind this ordering.

- [ ] **Topic delete blocked by `not_relevant` attempts.** Split out of the
      composite-uniqueness slice (now active, see Backlog). Topic delete is
      blocked by `not_relevant` ingestion attempts (a deliberate `ON DELETE
      RESTRICT`) — decide whether a topic that only ever rejected articles
      should be deletable.
- [ ] **Auto Search (Slice 2).** Wire the provisioned-but-unused SearXNG into
      ingestion so a topic can be given source *suggestions* discovered from the
      web (spec R2's "Auto Search"), and/or turn "register a feed" into
      "periodically search this domain for the topic." Genuinely new ingestion
      capability, not just a filter on existing feeds. Needs its own spec.
- [ ] **Analysis style (Slice 3).** A per-topic analysis-style/tone preference
      threaded into `summarization/prompts.py`'s brief-generation prompt. Touches
      the summarization pipeline, not just ingestion. Needs its own spec.
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
