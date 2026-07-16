# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Product UI Refinement (2026-07-16)

Spec: `docs/superpowers/specs/2026-07-16-product-ui-refinement-design.md`
Plan: `docs/superpowers/plans/2026-07-16-product-ui-refinement.md`

Backend chain:
- [ ] `pypdf` dependency (`pyproject.toml`)
- [ ] `ExtractorKind` gains upload member(s) (`domain/models.py`)
- [ ] `FileExtractor` protocol + PDF/text implementations (`ingestion/file_extractor.py`)
- [ ] `IngestionService` shared-tail refactor + `ingest_file` (`ingestion/service.py`)
- [ ] `POST /ingestion/files` route + `runtime.py` wiring (`api/app.py`)
- [ ] Backend tests (`tests/unit/test_file_extractor.py`, `test_ingestion_service.py`, `tests/api/test_ingestion.py`)

Frontend chain:
- [ ] `api.ts` additions (types + write wrappers)
- [ ] Onboarding + gating (`Onboarding.tsx`, `App.tsx`)
- [ ] Add-content UI (`AddContentPanel.tsx`, `IngestionResultList.tsx`, `RecentActivityList.tsx`)
- [ ] API key settings (`ApiKeySettings.tsx`)
- [ ] `App.tsx` final wiring

Docs:
- [ ] `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md`

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
