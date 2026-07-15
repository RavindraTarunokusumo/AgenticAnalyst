# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: UI / Brief Viewer (2026-07-15)

Spec: `docs/superpowers/specs/2026-07-15-ui-brief-viewer-design.md`
Plan: `docs/superpowers/plans/2026-07-15-ui-brief-viewer.md`

- [x] `frontend/` scaffold (Vite + React + TS + Tailwind)
- [ ] API client module (`frontend/src/api.ts`)
- [x] Components: `CadenceTabs`, `BriefList`, `BriefDetail`, loading/empty/error states
- [ ] App shell / state (`frontend/src/App.tsx`)
- [ ] Backend static mount (`api/app.py`)
- [ ] `Dockerfile` multi-stage build (Node build stage + COPY into runtime stage)
- [ ] Local-dev fallback placeholder (`api/static/index.html` + gitignore `frontend/dist/`)
- [ ] CI: extend to build/lint frontend, or explicitly document the gap
- [ ] Tests: backend mount smoke test, existing `GET /briefs` tests untouched
- [ ] Docs: `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md`

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
- [ ] **claim_event / contradiction graph.** Explicitly deferred since the
      initial migration (`docs/database.md`); no schema, no design started.
      Likely the largest single slice on this list - needs its own spec
      before scoping, not a quick follow-on.
- [ ] **Evaluation-harness parity check.** `tests/evaluation/
      test_temporal_holdout.py` (opt-in, excluded from routine CI) drives
      `WorkflowRunner.run_daily/weekly/monthly` directly, bypassing
      `DailyBriefPipeline`/`PeriodicBriefPipeline` entirely - it now exercises
      a different code path than every production trigger (scheduler, API,
      `/workflows/trigger`). Worth a small follow-up to route it through the
      pipelines instead, or explicitly document why it intentionally
      shortcuts them.
