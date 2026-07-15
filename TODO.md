# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Eval Harness Parity Documentation (2026-07-15)

- [x] Document why `tests/evaluation/test_temporal_holdout.py` intentionally
      drives `WorkflowRunner` directly instead of
      `DailyBriefPipeline`/`PeriodicBriefPipeline` (chose the "document the
      shortcut" branch over rerouting - rerouting would require new
      corpus-to-Postgres seeding infra the suite doesn't otherwise have).

## Future Backlog

Candidate next slices, roughly in suggested priority order. None have a spec
yet; each needs Workflow Step 3 (spec + lightweight plan) before
implementation. See chat/session notes from 2026-07-15 for the full rationale
behind this ordering.

- [ ] **Archive retrieval / semantic search over past briefs.** `Embedding`
      (domain model + `save_embedding` repository function) exists but is
      never called from any pipeline or graph node - there is no embedding
      generation step and no read API (e.g. `GET /archive/search`) to query
      by similarity. This is the largest gap between the current product
      (three cadences of briefs, browsable only by cadence+date) and
      "narrative memory you can actually query."
- [ ] **Prediction expectation resolution.** `PredictionExpectation` rows
      are created by the frontier synthesis graph (`proposed_expectations`)
      with `outcome_status`, but nothing ever revisits and updates that
      status later (no confirm/falsify job or route). The falsifiable-
      predictions concept is half-built: expectations are proposed but never
      checked against what actually happened.
- [ ] **UI / frontend.** The product is API-only end to end (RSS-to-Daily and
      Weekly/Monthly slices both explicitly scoped UI out). Even a minimal
      read-only brief viewer would make the existing `GET /briefs` surface
      usable by a human instead of only `curl`/`gh`.
- [ ] **claim_event / contradiction graph.** Explicitly deferred since the
      initial migration (`docs/database.md`); no schema, no design started.
      Likely the largest single slice on this list - needs its own spec
      before scoping, not a quick follow-on.
