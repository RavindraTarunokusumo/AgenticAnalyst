# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Product UI Refinement (2026-07-16)

Spec: `docs/superpowers/specs/2026-07-16-product-ui-refinement-design.md`
Plan: `docs/superpowers/plans/2026-07-16-product-ui-refinement.md`

Backend chain:
- [x] `pypdf` dependency (`pyproject.toml`) - `dfec38d`
- [x] `ExtractorKind` gains upload member(s) (`domain/models.py`) - `c2d5fda`
- [x] `FileExtractor` protocol + PDF/text implementations (`ingestion/file_extractor.py`) - `6911e89`
- [x] `IngestionService` shared-tail refactor + `ingest_file` (`ingestion/service.py`) - `11796c6`
- [x] `POST /ingestion/files` route + `runtime.py` wiring (`api/app.py`) - `a1b0a51`
- [x] Backend tests (`tests/unit/test_file_extractor.py`, `test_ingestion_service.py`, `tests/api/test_ingestion.py`) - `1129771`, `212a2bf`

Frontend chain:
- [x] `api.ts` additions (types + write wrappers) - `bddd68f`
- [x] Onboarding + gating (`Onboarding.tsx`, `App.tsx`) - `b7b3dc9`
- [x] Add-content UI (`AddContentPanel.tsx`, `IngestionResultList.tsx`, `RecentActivityList.tsx`) - `5d05e9d`
- [x] API key settings (`ApiKeySettings.tsx`) - `5a61e2f`
- [x] `App.tsx` final wiring - `1433b99`, `29a2d51`

Docs:
- [x] `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md` - `21b7d0e`

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
