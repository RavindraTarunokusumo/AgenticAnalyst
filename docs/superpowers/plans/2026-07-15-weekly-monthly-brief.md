# Weekly/Monthly Brief Vertical Slice — Implementation Plan

Spec: `docs/superpowers/specs/2026-07-15-weekly-monthly-brief-design.md` (accepted).
Branch: `codex/weekly-monthly-brief-plan` (create under `.worktree/` per workflow
step 1).

This is the implementer's contract: file structure, task decomposition, per-task
Interfaces (Consumes/Produces), build order, and risks. Exact code, prompts, and
shell commands are regenerated per task, not transcribed here.

## Why this plan is small

Unlike the RSS-to-Daily-Brief slice, almost all required architecture already
exists and is correct (spec §2): the graph, the runner, the citation-exclusion
primitive, and the read API are all reused unmodified. This slice is a thin
orchestration layer plus wiring — one new repository query, one new pipeline
class, and routing fixes. Resist the temptation to add scope beyond spec §12's
explicit constraints.

## File structure (new/changed)

```
src/analyst_engine/
  persistence/repositories.py  [CHANGED] + list_eligible_batch_summaries_for_window
  pipeline/
    periodic_brief.py          [NEW] PeriodicBriefPipeline, PeriodicPipelineResult
  runtime.py                   [CHANGED] + build_periodic_brief_pipeline
  main.py                      [CHANGED] construct weekly_pipeline/monthly_pipeline,
                                pass into register_schedules
  scheduling.py                [CHANGED] weekly/monthly jobs rebind to pipeline.run;
                                register_schedules gains 2 new parameters
  api/app.py                   [CHANGED] POST /pipelines/weekly, POST /pipelines/monthly;
                                /workflows/trigger's 3 branches delegate to pipelines
tests/unit/…, tests/integration/…, tests/api/…                  [NEW/CHANGED per task]
docs/architecture.md, database.md, changelog.md, index.md        [CHANGED, Task 6]
```

No `alembic/versions/`, no `domain/models.py`, no `config.py` changes (spec §4, §7:
no schema, no new settings).

Module boundary carried over from the existing repair and RSS slice: `pipeline/`
touches persistence via repositories and the runner only, never SQLAlchemy ORM
types or FastAPI directly.

## Task decomposition

Each task lands as its own commit(s) with a TODO sub-item, git note, and a full
`ruff format --check` + `ruff check` + `mypy src tests` + `uv run pytest` gate
before commit (per spec §12).

### Task 1 — Repository: `list_eligible_batch_summaries_for_window`

- **Consumes:** existing `ORMBatchSummary`, `ORMArticleBatch`, `ORMArticle` models;
  existing `_summary_to_domain` mapper; existing `any_()`/`exists()` query pattern
  already used by `list_eligible_unbatched_articles` (`repositories.py:822-852`).
- **Produces:** `list_eligible_batch_summaries_for_window(session, window_start,
  window_end) -> list[BatchSummary]` per spec §5.1 — join `batch_summary` to
  `article_batch` on `batch_id`, `exists()` filter for at least one article in
  `[window_start, window_end]` (half-open UTC range, matching the existing
  `published_before` construction style), ordered by `created_at asc, id asc`.
  No `cadence` parameter (spec §5.1 — citation exclusion stays in the pipeline).
- **Consumed by:** Task 2.
- **Risk:** boundary correctness (an article published exactly on `window_end`
  must be included; one published the day after must not) — needs a dedicated
  unit/integration test at the exact boundary, not just "somewhere in the middle."

### Task 2 — `PeriodicBriefPipeline`

- **Consumes:** Task 1's repository function; existing `is_batch_summary_cited`
  (`repositories.py:912+`, unmodified); existing `get_workflow_run_by_idempotency`,
  `get_brief_by_cadence_interval` (unmodified); the **existing, unmodified**
  `WorkflowRunner.run_weekly`/`run_monthly` (`workflows/runner.py:195-224`);
  `session_factory`, clock.
- **Produces:** `PeriodicBriefPipeline` + `PeriodicPipelineResult` per spec §5.2 —
  one cadence-parameterized class (constructed with `cadence=Cadence.WEEKLY` or
  `Cadence.MONTHLY`), implementing spec §3.2 (window normalization — must
  independently compute the Monday-aligned/month-aligned start using the exact
  same formula `run_weekly`/`run_monthly` use internally, never passing a raw
  anchor date to the runner), §3.3 (selection algorithm), and §3.4 (no-content
  short-circuit, generalized from `DailyBriefPipeline`'s existing pattern).
- **Consumed by:** Task 3 (runtime/scheduler), Task 4 (API routes).
- **Risk:** the window-normalization formula must exactly match
  `run_weekly`/`run_monthly`'s own default-case formula (spec §3.2) — a
  off-by-one or non-Monday-aligned start here silently creates a second,
  overlapping `WorkflowRun` idempotency key for what should be "the same week."
  Unit test this by asserting the pipeline's computed `covered_start`/`covered_end`
  match what `run_weekly()`/`run_monthly()` compute with no `target_date` argument,
  for at least one case where `date.today()` is mid-week/mid-month.

### Task 3 — Runtime wiring + scheduler

- **Consumes:** Task 2's `PeriodicBriefPipeline` constructor.
- **Produces:** `runtime.py::build_periodic_brief_pipeline(runtime, *, runner,
  cadence) -> PeriodicBriefPipeline`; `main.py` constructs
  `weekly_pipeline`/`monthly_pipeline` alongside the existing `pipeline` (daily)
  and passes both into `register_schedules`; `scheduling.py::register_schedules`
  gains `weekly_pipeline`/`monthly_pipeline` parameters, and the weekly/monthly
  `scheduler.add_job(...)` calls rebind from `runner.run_weekly`/`run_monthly` to
  `weekly_pipeline.run`/`monthly_pipeline.run` (spec §6.2) — same rebinding
  pattern PR #3's `_run_daily_pipeline` closure already established for daily.
  Cron schedules (`Sunday 03:00`, `1st 04:00`) are unchanged.
- **Consumed by:** Task 4 (API lifespan needs the same two pipeline instances on
  `app.state`).
- **Risk:** `register_schedules`'s signature changes — grep every call site
  (production `main.py` and any test that constructs/calls it directly) before
  committing, same class of risk PR #3's plan flagged for `RuntimeDependencies`.

### Task 4 — API routes + `/workflows/trigger` fix

- **Consumes:** Task 2 (`PeriodicBriefPipeline`), Task 3 (runtime wiring),
  existing `_require_key` boundary (unmodified).
- **Produces:** `POST /pipelines/weekly`, `POST /pipelines/monthly` (spec §6.1,
  request/response shapes mirroring `POST /pipelines/daily`'s existing pattern
  but scoped to `PeriodicPipelineResult`'s actual fields — no
  `feeds_polled`/`batches_*`); `app.state.weekly_pipeline`/`monthly_pipeline` set
  in the lifespan; `/workflows/trigger`'s three cadence branches
  (`api/app.py:264-271`) redelegate to `app.state.pipeline` /
  `app.state.weekly_pipeline` / `app.state.monthly_pipeline` respectively instead
  of calling `runner.run_daily`/`run_weekly`/`run_monthly` directly — fixes the
  pre-existing daily bypass in the same change (spec §2, confirmed in scope).
  `TriggerResponse`'s shape is unchanged.
- **Consumed by:** nothing further in-repo; this is the external contract.
- **Risk:** `/workflows/trigger`'s existing daily-cadence tests currently assert
  against `runner.run_daily` being called directly (or a mock standing in for it)
  — those tests must be updated to assert against the pipeline call instead, not
  left red or silently skipped (mirrors the exact risk PR #3's plan flagged for
  its own auth-tightening change to this same route).

### Task 5 — Integration/API test sweep + success-criteria verification

- **Consumes:** everything above.
- **Produces:** the cross-cutting tests spec §10 lists that don't naturally belong
  to one task alone — PostgreSQL-backed window-boundary test for Task 1's query
  against real seeded rows; end-to-end weekly (and monthly) checkpointed workflow
  producing a real `Brief` + `NarrativeStateVersion` from persisted batch
  summaries with a fake gateway (mirrors `test_daily_pipeline.py`'s existing
  structure); explicit test that a batch summary already cited by a Daily brief
  is still independently eligible for its Weekly brief (spec §11 criterion 4) —
  plus a pass through spec §11's success-criteria checklist.
- **Risk:** none new; this is verification, not new production code.

### Task 6 — Documentation reconciliation

- **Consumes:** the merged behavior of Tasks 1-5.
- **Produces:** updates to `docs/architecture.md` (scheduler section: weekly/
  monthly jobs now call their pipelines, not the runner directly; new module
  note for `pipeline/periodic_brief.py`), `docs/database.md` (if the new query
  shape is worth documenting alongside the existing "unbatched articles"
  exclusion query), `docs/changelog.md`, `docs/index.md` if a new module doc
  section is warranted.
- **Risk:** none new.

## Build order

Task 1 → 2 (strict; Task 2 needs Task 1's repository function).
Task 3 needs Task 2. Task 4 needs Task 2 and Task 3 (needs both pipeline
instances constructed and reachable from the API lifespan). Task 5 needs Task 4.
Task 6 needs Task 5.

Practically: implement sequentially (1→2→3→4→5→6) in this worktree. The slice is
small enough, and each task depends on the prior closely enough (window formula →
pipeline → wiring → routes), that parallelizing across sub-worktrees would add
merge-coordination overhead disproportionate to the work saved.

## Cross-task risks

- **Window-normalization drift** (Task 2) is the single highest-risk item in this
  slice — an incorrect Monday/month-start formula silently produces a second,
  overlapping idempotency key rather than a loud failure (spec §3.2). Get this
  right and tested before Task 3 wires it into anything schedule-driven.
- **`/workflows/trigger` regression** (Task 4) touches an existing, already-tested
  route for daily; update its existing tests in the same commit, not after.
- **Do not touch `workflows/graphs.py` or `workflows/runner.py`** (spec §12) — if
  an implementer finds themselves wanting to change either file to make this
  slice work, that is a signal the design has drifted from the spec, not a
  reason to expand this plan's scope. Stop and reconcile against the spec first.
