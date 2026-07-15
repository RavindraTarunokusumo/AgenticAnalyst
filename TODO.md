# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Archive Retrieval / Semantic Search (2026-07-15)

Spec: `docs/superpowers/specs/2026-07-15-archive-retrieval-design.md`
Plan: `docs/superpowers/plans/2026-07-15-archive-retrieval.md`

- [ ] `ModelGateway.embed()` abstract method (`models/gateway.py`)
- [ ] `FakeModelGateway.embed()` (`tests/fixtures.py`) - same commit as above
- [ ] **Scope extension** (found during Task 1): the new abstract method makes
      *every* `ModelGateway` subclass uninstantiable, not just
      `tests/fixtures.py::FakeModelGateway` as the plan called out - four more
      test-local fakes also extend `ModelGateway` directly:
      `tests/unit/test_daily_brief_pipeline.py::_FakeGateway`,
      `tests/integration/test_periodic_brief_pipeline.py::_CountingGateway`,
      `tests/unit/test_batch_summarizer.py::_ScriptedGateway`,
      `tests/integration/test_daily_pipeline.py::_CountingGateway`, and
      `tests/unit/test_workflow_graphs.py::_Gateway`. Landed `embed()` on all
      of them in the same commit as the abstract method to keep collection
      green throughout.
- [ ] `DashScopeAdapter.embed()` (`models/dashscope.py`)
- [ ] `OpenRouterAdapter.embed()` (`models/openrouter.py`)
- [ ] `search_embeddings_by_similarity()` repository function
- [ ] Wire best-effort embedding into `synthesize` node (`workflows/graphs.py`)
- [ ] `GET /archive/search` route + response model (`api/app.py`)
- [ ] Tests: adapter embed (happy/error)
- [ ] Tests: best-effort swallow (brief persists despite embed failure)
- [ ] Tests: pgvector-backed similarity ordering integration test
- [ ] Docs: `docs/architecture.md`, `docs/changelog.md`

## Future Backlog

Candidate next slices, roughly in suggested priority order. None have a spec
yet; each needs Workflow Step 3 (spec + lightweight plan) before
implementation. See chat/session notes from 2026-07-15 for the full rationale
behind this ordering.

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
- [ ] **Evaluation-harness parity check.** `tests/evaluation/
      test_temporal_holdout.py` (opt-in, excluded from routine CI) drives
      `WorkflowRunner.run_daily/weekly/monthly` directly, bypassing
      `DailyBriefPipeline`/`PeriodicBriefPipeline` entirely - it now exercises
      a different code path than every production trigger (scheduler, API,
      `/workflows/trigger`). Worth a small follow-up to route it through the
      pipelines instead, or explicitly document why it intentionally
      shortcuts them.
