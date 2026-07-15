# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Weekly/Monthly Brief Vertical Slice (2026-07-15)

Spec: `docs/superpowers/specs/2026-07-15-weekly-monthly-brief-design.md`
Plan: `docs/superpowers/plans/2026-07-15-weekly-monthly-brief.md`

Spec and lightweight plan written; not yet implemented. A future session should
start at Workflow step 1 (dedicated worktree/branch, e.g.
`codex/weekly-monthly-brief-plan`) and follow the plan's Task 1-6 build order.

- [x] Write and validate the weekly/monthly brief design specification.
- [x] Produce the lightweight implementation plan (6 tasks: repository query,
      `PeriodicBriefPipeline`, runtime/scheduler wiring, API routes +
      `/workflows/trigger` fix, test sweep, docs reconciliation).
- [x] Task 1: `list_eligible_batch_summaries_for_window` repository function.
- [x] Task 2: `PeriodicBriefPipeline` + `PeriodicPipelineResult`.
- [ ] Task 3: Runtime wiring + scheduler rebinding.
- [ ] Task 4: API routes (`/pipelines/weekly`, `/pipelines/monthly`) +
      `/workflows/trigger` fix (all 3 cadences delegate to their pipeline).
- [ ] Task 5: Integration/API test sweep + success-criteria verification.
- [ ] Task 6: Documentation reconciliation.

## Session: <Session Name> (<YYYY-MM-DD>)

- [ ] <sub-item 1>
- [ ] <sub-item 2>
- [ ] <sub-item 3>

## Future Backlog

- [ ] <future item>
