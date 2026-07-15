# 2026-07-15 — Weekly/Monthly Brief Vertical Slice (codex/weekly-monthly-brief-plan)

**Merge:** PR #4 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/4)
**Merge commit:** 552e272524edfdd0652c8892226ef63d276e7051
**Feature branch:** codex/weekly-monthly-brief-plan
**Merged:** 2026-07-15T15:23:33Z

Spec: `docs/superpowers/specs/2026-07-15-weekly-monthly-brief-design.md`
Plan: `docs/superpowers/plans/2026-07-15-weekly-monthly-brief.md`

## Completed Work

- [x] Task 1: `list_eligible_batch_summaries_for_window` repository function (`67b0832`)
- [x] Task 2: `PeriodicBriefPipeline` + `PeriodicPipelineResult` (`b5d1106`)
- [x] Task 3: Runtime wiring + scheduler rebinding (`f00ce7c`)
  - [x] Extension: `register_schedules` also drops its now fully-unused `runner` parameter (weekly/monthly jobs call their pipeline, not the runner, after this task) rather than leaving a dead parameter (same commit)
- [x] Task 4: API routes (`/pipelines/weekly`, `/pipelines/monthly`) + `/workflows/trigger` fix — all 3 cadences delegate to their pipeline (`4b4edb6`)
- [x] Task 5: Integration/API test sweep + success-criteria verification (`4bc5950`)
- [x] Task 6: Documentation reconciliation (`492221c`)
- [x] Post-PR review reception: Grok bundled review (PR #4, review id 4705394734) — 5 findings, 4 fixed (weekly/monthly scheduler jobs now pass local `date.today()` instead of the pipeline's default UTC clock — a real bug that could pick the wrong week/month near local midnight in non-UTC deployments; N+1 DB sessions in the citation-exclusion loop batched into one; implicit `WorkflowStatus` enum coercion in `/workflows/trigger` made explicit; added a missing daily-cadence 409 regression test), 1 pushed back on with reasoning (repopulating `summaries_selected` on the idempotent-retry fall-through would deviate from `DailyBriefPipeline`'s exact accepted pattern the spec required mirroring — applied a doc-comment clarification instead) (`5803fab`)
- [x] Fix: CI-only failure — `ArticleBatch.article_ids` requires 3-5 items; several window-boundary and periodic-pipeline test fixtures constructed 1-2 article batches, invisible locally because these tests are Docker-gated and skip before the constructor (and its pydantic validation) ever runs (`c2c55fc`)

## Summary

Closed the gap the RSS-to-Daily-Brief slice left open: weekly/monthly workflow runs previously called `WorkflowRunner.run_weekly`/`run_monthly` directly with no evidence (`batch_summaries=None`), producing a degenerate brief from an empty context. Added `PeriodicBriefPipeline`, one cadence-parameterized pipeline that normalizes an anchor date to the canonical Monday-Sunday week or calendar month (matching the runner's own default-case formula exactly), selects already-persisted `BatchSummary` evidence for that window, excludes summaries already cited for that same cadence and window (cadence-independent citation tracking, reused unchanged), then calls the existing, unmodified `WorkflowRunner.run_weekly`/`run_monthly`. Wired into the scheduler (weekly Sunday 03:00, monthly 1st 04:00) and exposed via `POST /pipelines/weekly`/`monthly`. Fixed `/workflows/trigger`'s pre-existing bypass for all three cadences (daily included), so there is now exactly one correct way to trigger a real brief per cadence.

No schema changes, no new Alembic migration, and `workflows/graphs.py`/`workflows/runner.py` were left untouched throughout, per the accepted design's explicit constraint.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` — passed (final state).
- `uv run mypy src tests` — clean (strict mode, 84 source files).
- `uv run pytest --ignore=tests/evaluation` (local, Docker unavailable) — 220 passed, 26 skipped (Docker-only integration tests).
- GitHub Actions `quality` job (CI Postgres service) — failed on the first push (5 tests, `ArticleBatch` constraint violation invisible locally), green after the fix (run `29427132123`).
- Grok bundled code review (`/bundled:review`, `grok-composer-2.5-fast`) — 5 findings (1 bug, 3 suggestions, 1 nit), all verified against the codebase before acting; 4 fixed, 1 pushed back on with technical reasoning (see PR #4 review thread replies).
