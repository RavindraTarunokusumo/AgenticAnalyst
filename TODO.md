# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

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
      inexpressible. Suggested prioritization (highest impact per effort
      first): (1) a "topics of interest" field on the onboarding form,
      stored on `Source`, used to filter/tag ingested articles against the
      existing `topics` extraction; (2) a short multi-step guided onboarding
      flow (source -> topics -> style) instead of one static form, for the
      "personalization is happening" feel; (3, stretch) an analysis-style
      toggle threaded into `summarization/prompts.py`'s brief-generation
      prompt - larger/riskier since it touches the summarization pipeline,
      not just ingestion. Needs its own spec before scoping.
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
