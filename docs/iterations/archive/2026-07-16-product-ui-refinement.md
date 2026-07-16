# 2026-07-16 — Product UI Refinement (codex/product-ui-refinement)

**Merge:** PR #8 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/8)
**Merge commit:** 3a810c9339d4be4849dc7452a49e85e5ba8b873d
**Feature branch:** codex/product-ui-refinement
**Merged:** 2026-07-16T16:56:28Z

## Completed Work

Backend chain:
- [x] `pypdf` dependency (`pyproject.toml`) (`dfec38d`)
- [x] `ExtractorKind` gains upload member(s) (`domain/models.py`) (`c2d5fda`)
- [x] `FileExtractor` protocol + PDF/text implementations
      (`ingestion/file_extractor.py`) (`6911e89`)
- [x] `IngestionService` shared-tail refactor + `ingest_file`
      (`ingestion/service.py`) (`11796c6`)
- [x] `POST /ingestion/files` route + `runtime.py` wiring (`api/app.py`)
      (`a1b0a51`)
- [x] Backend tests (`tests/unit/test_file_extractor.py`,
      `test_ingestion_service.py`, `tests/api/test_ingestion.py`)
      (`1129771`, `212a2bf`)

Frontend chain:
- [x] `api.ts` additions (types + write wrappers) (`bddd68f`)
- [x] Onboarding + gating (`Onboarding.tsx`, `App.tsx`) (`b7b3dc9`)
- [x] Add-content UI (`AddContentPanel.tsx`, `IngestionResultList.tsx`,
      `RecentActivityList.tsx`) (`5d05e9d`)
- [x] API key settings (`ApiKeySettings.tsx`) (`5a61e2f`)
- [x] `App.tsx` final wiring (`1433b99`, `29a2d51`)

Docs:
- [x] `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md`
      (`21b7d0e`)

Code review fixes (post-PR-open, pre-merge):
- [x] Backend: broad exception handling around file extraction, oversized-
      upload attempt-recording gap, content-type/extension fallback
      (`2a33840`)
- [x] Frontend: success/`succeeded` status-string mismatch, silent no-op on
      a whitespace-only links submission (`d7c6b08`)

## Summary

The UI was read-only with no onboarding, upload, or write-surface
functionality - it didn't look like a usable product. This slice adds
first-run source onboarding (`Onboarding.tsx`, gates the existing 3-panel
brief viewer behind at least one registered source), a 3-mode add-content
panel (paste links / register a feed / upload a PDF or plain-text file -
`AddContentPanel.tsx`, `IngestionResultList.tsx`), a persistent recent-
activity view (`RecentActivityList.tsx`, backed by the existing
`GET /ingestion/attempts`), and client-held API key settings
(`ApiKeySettings.tsx`, `localStorage['ae_api_key']`). Explicitly
functionality-only per product direction - no visual/design changes.

New backend surface: `POST /ingestion/files` (multipart), backed by a new
`FileExtractor` protocol (`PdfFileExtractor` via `pypdf`, `TextFileExtractor`
for plain text) and `IngestionService.ingest_file`, which reuses the
existing dedup/persist path via an extract-method refactor
(`_check_duplicate`/`_finalize_extracted` factored out of `_ingest_candidate`
- verified behavior-preserving against the pre-existing test suite passing
unmodified). Uploads dedup by content-hash via a synthetic
`upload://<sha256>` URL and are stamped with ingestion time as
`published_at` (uploads have no real publish date). Two new
`ExtractorKind` members (`FILE_PDF`/`FILE_TEXT`) were additive against the
existing unconstrained `String(32)` column - no migration.

Both the backend (file-upload chain, 6 tasks) and frontend (onboarding/add-
content chain, 5 tasks) were implemented as two parallel background-agent
worktrees per the plan's build order; both agents were killed mid-task by
the harness before finishing (unrelated to the work itself - see
`docs/insights.md`'s 2026-07-16 entry). Recovering required verifying real
`git status`/`git log` state in each sub-worktree (several tasks were
already committed; others were complete in the working tree but
uncommitted) rather than trusting either agent's last-reported chat text,
then finishing the remaining tasks (Task 5 route, Task 6 tests on the
backend side; Task 10 commit + Task 11 wiring on the frontend side)
directly before merging both chains into the integration branch.

An independent ephemeral code-review agent found 6 issues against the PR;
2 were HIGH severity and real (pypdf can raise non-`PyPdfError` exceptions
on a malformed PDF, which propagated as an unhandled 500 through the route
instead of a graceful `status="failed"`; and a frontend status-string
mismatch - `'success'` vs. the backend's actual `'succeeded'` - silently
miscolored every successful ingestion result gray instead of green). Fixed
5 of 6 findings; pushed back on the 6th (a redundant `sha256` computation)
as genuinely low-value given the fix would widen the `FileExtractor`
protocol's signature for a negligible gain on content already bounded well
under the 10MB size cap.

Root cause: not a bug - a net-new feature closing a named product gap
("doesn't look like a Product yet").

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` / `uv run mypy src
  tests` / `uv run pytest` (unit + api + integration, including a real-
  Postgres testcontainers concurrency test) - all green (231 unit/api
  passed, 1 skipped; 16 integration passed) on the merged integration
  branch, independently re-run after both chains merged (not either
  chain's own scoped self-report) and again after the code-review fixes.
- `npm run lint` (oxlint) / `npm run build` (`tsc -b && vite build`) -
  clean.
- CI (`quality` + `frontend` jobs, both platforms) green on the final
  commit before merge.
- Manual validation: local dev server (standalone Postgres container +
  `uv run python -m analyst_engine.main` + `npm run dev`), tunneled to the
  user via SSH local port-forward, confirmed onboarding gates the 3-panel
  view behind a registered source and the add-content flow renders. A full
  Docker-compose browser walkthrough was not run in the implementing
  environment since port 5432 was already bound by an unrelated project's
  container on the shared host.

## Follow-up scoped during manual review (not yet spec'd)

User feedback after manually exercising onboarding (2026-07-16, same
session): the onboarding form is functionally minimal and has no way to
express *what* to track within a source (e.g. "follow the US-Iran war on
Reuters," not just register `reuters.com` wholesale), and there is no
personalization concept anywhere in the domain model (`Source` has no
topic/keyword field; `topics` only ever exists as an LLM-*output* on
`BatchSummary`, never a user input). Framed as a real gap for a hackathon
demo specifically, not a design nitpick. Logged as a new Future Backlog
item in `TODO.md` - needs its own spec (Workflow Step 3) before
implementation.
