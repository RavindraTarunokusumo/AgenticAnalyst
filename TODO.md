# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Archive Retrieval / Semantic Search (2026-07-15)

Spec: `docs/superpowers/specs/2026-07-15-archive-retrieval-design.md`
Plan: `docs/superpowers/plans/2026-07-15-archive-retrieval.md`

- [x] `ModelGateway.embed()` abstract method (`models/gateway.py`)
- [x] `FakeModelGateway.embed()` (`tests/fixtures.py`) - same commit as above
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
- [x] `DashScopeAdapter.embed()` (`models/dashscope.py`)
- [x] `OpenRouterAdapter.embed()` (`models/openrouter.py`)
- [x] `search_embeddings_by_similarity()` repository function
- [x] Wire best-effort embedding into `synthesize` node (`workflows/graphs.py`)
- [x] **Scope note** (found during this task): the plan's suggested resolution -
      a bare `try/except Exception: pass` around `save_embedding` - is not
      actually transaction-safe. Verified empirically (temporarily reverted the
      fix and re-ran the new DB-level-failure integration test): when
      `save_embedding`'s own flush fails at the DB layer (not a `ModelError`),
      Postgres aborts the whole transaction, and the plain try/except leaves
      the session in that aborted state - `session_scope`'s subsequent
      `session.commit()` then raises `PendingRollbackError`, so the brief is
      *not* actually persisted despite the try/except swallowing the first
      exception. Used `async with session.begin_nested():` (a SAVEPOINT)
      around the embed+save_embedding block instead, which isolates either a
      model-side or DB-side failure from the outer transaction. Covered by a
      new integration test
      (`test_synthesize_node_persists_brief_despite_db_level_embedding_failure`)
      using a fake gateway that returns a wrong-dimension vector to trigger a
      real pgvector constraint failure. Code review follow-up (`86595dd`):
      moved the `gateway.embed()` network call out of `session_scope`
      entirely (not just out of the SAVEPOINT), so no pooled DB connection/
      transaction is held during the network call.
- [x] `GET /archive/search` route + response model (`api/app.py`) - landed
      with route-level tests in the same commit (7 cases: happy path,
      cadence/limit passthrough, blank q, limit out of range, unknown
      cadence, 503 on TerminalModelError, empty results)
- [x] Tests: adapter embed (happy/error) - landed in the DashScopeAdapter.embed()
      and OpenRouterAdapter.embed() commits (`a444a9b`, `f95c6af`)
- [x] Tests: best-effort swallow (brief persists despite embed failure) -
      landed in the same commit as the synthesize-node wiring above (mocked
      unit test + real-DB integration test)
- [x] Tests: pgvector-backed similarity ordering integration test
- [x] Docs: `docs/architecture.md`, `docs/changelog.md`

## Session: UI / Brief Viewer (2026-07-15)

Spec: `docs/superpowers/specs/2026-07-15-ui-brief-viewer-design.md`
Plan: `docs/superpowers/plans/2026-07-15-ui-brief-viewer.md`

- [x] `frontend/` scaffold (Vite + React + TS + Tailwind)
- [x] API client module (`frontend/src/api.ts`)
- [x] Components: `CadenceTabs`, `BriefList`, `BriefDetail`, loading/empty/error states
- [x] App shell / state (`frontend/src/App.tsx`)
- [x] Backend static mount (`api/app.py`) + local-dev fallback placeholder
      (`api/static/index.html` + gitignore `frontend/dist/`) - landed as one
      commit: `StaticFiles(directory=...)` raises at construction time if the
      directory doesn't exist, so the mount and the placeholder file are
      technically coupled and cannot be split into independently-working
      commits (plan listed them as separate line items; consolidated here,
      logged per Workflow Rule 2).
- [x] `Dockerfile` multi-stage build (Node build stage + COPY into runtime stage)
- [x] CI: extend to build/lint frontend, or explicitly document the gap
- [x] Tests: backend mount smoke test, existing `GET /briefs` tests untouched
      (also updated `test_container_image_installs_playwright_chromium_for_
      future_ingestion`'s `dockerfile.startswith(...)` assertion, which the
      new Node frontend-build stage legitimately broke since it is no longer
      the first line of the Dockerfile - not a pre-existing/unrelated
      failure, logged per Workflow Rule 2)
- [x] Docs: `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md`

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
- [ ] **claim_event / contradiction graph.** Explicitly deferred since the
      initial migration (`docs/database.md`); no schema, no design started.
      Likely the largest single slice on this list - needs its own spec
      before scoping, not a quick follow-on.
