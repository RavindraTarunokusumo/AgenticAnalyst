# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

No active session. Most recent: Multi-Topic Source Sharing (composite
uniqueness), merged as PR #10
(`docs/iterations/archive/2026-07-17-multi-topic-source-sharing.md`).

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
