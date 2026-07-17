# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

No active session. Most recent: Topic-First Analyst — Slice 1, merged as PR #9
(`docs/iterations/archive/2026-07-16-topic-first-analyst.md`).

## Future Backlog

Candidate next slices, roughly in suggested priority order. None have a spec
yet; each needs Workflow Step 3 (spec + lightweight plan) before
implementation. See chat/session notes from 2026-07-15 for the full rationale
behind this ordering.

- [ ] **Multi-topic source/URL sharing (composite uniqueness).** Deferred from
      Slice 1's PR #9 review; **confirmed a real requirement** by the user (the
      same source should be usable across topics). Today the global-unique
      constraints prevent it: re-registering a shared source silently reassigns
      it (global `source.stable_id` / `source_feed.feed_url_fingerprint`), and
      the same URL ingested under a second topic is dup-suppressed against the
      first topic's article so it never enters the second pool (global
      `article.url_fingerprint`). Fix: make these uniqueness scopes composite —
      `(topic_id, stable_id)`, `(topic_id, feed_url_fingerprint)`,
      `(topic_id, url_fingerprint)` — plus adjust the upsert/dedup paths that
      assume global uniqueness. Needs an Alembic migration. Also fold in the
      minor Slice-1 review nit: topic delete is blocked by `not_relevant`
      ingestion attempts (a deliberate `ON DELETE RESTRICT`) — decide whether a
      topic that only ever rejected articles should be deletable.
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
