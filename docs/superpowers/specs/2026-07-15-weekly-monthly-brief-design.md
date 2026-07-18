# Weekly/Monthly Brief Vertical Slice Design

## 1. Purpose

Give Agentic Analyst real weekly and monthly product behavior. The RSS-to-Daily-Brief
slice (PR #3) proved the full ingestion-to-brief loop for `Cadence.DAILY` only;
`Cadence.WEEKLY`/`Cadence.MONTHLY` are wired into the scheduler and
`/workflows/trigger` today, but both call `WorkflowRunner.run_weekly`/`run_monthly`
directly with `batch_summaries=None` — the frontier-synthesis graph runs with an
empty evidence set, producing a degenerate brief rather than real product output.
This slice closes that gap the same way `DailyBriefPipeline` closed it for daily:
add a pipeline layer that selects real, already-persisted evidence for the covered
window before invoking the existing, unmodified graph/runner.

## 2. What Already Exists (verified against the current codebase, not assumed)

No new architecture is required. Confirmed present and correct, untouched since
PR #2 and PR #3:

- `build_weekly_graph` / `build_monthly_graph` (`workflows/graphs.py:170-179`) — the
  single generic `_frontier_synthesis` node, parameterized by `Cadence`, already
  handles weekly/monthly exactly like daily (model task routing, narrative
  versioning, `Brief` persistence).
- `WorkflowRunner.run_weekly` / `run_monthly` (`workflows/runner.py:195-224`) —
  correct Monday-Sunday and calendar-month window computation, idempotency-key
  claiming, terminal-status short-circuiting — identical machinery to `run_daily`.
- `WorkflowRunner._load_context`'s `prior_cadence` mapping — already routes a
  weekly run's continuity context to the most recent prior **daily** briefs, and a
  monthly run's to the most recent prior **weekly** briefs (`runner.py:98-102`).
  This is intentional, pre-existing design: each cadence tier's "prior_briefs"
  input is the next-finer tier's recent output, for narrative color, not the
  content being synthesized this run.
- `is_batch_summary_cited(session, id, cadence, *, exclude_covered_start,
  exclude_covered_end)` (`repositories.py:912+`) — already `Cadence`-parameterized.
  A batch summary's citation status is tracked **independently per cadence**: the
  same batch summary can legitimately be cited by a Daily brief and, separately,
  by that week's Weekly brief. This slice reuses this function as-is.
- `GET /briefs?cadence=` and `GET /briefs/{brief_id}` (`api/app.py:412-501`) —
  already fully `Cadence`-generic (parses `cadence` via `Cadence(cadence)`). Zero
  changes needed.
- `list_prior_briefs` / `get_brief_by_cadence_interval` (`repositories.py:546,
  595`) — already `Cadence`-generic. Zero changes needed.

Not present, and the actual gap this slice fills:

- No pipeline selects real `BatchSummary` rows for a weekly/monthly window before
  calling the runner. The scheduler (`scheduling.py`) and `/workflows/trigger`
  (`api/app.py:266-269`) both call `runner.run_weekly`/`run_monthly` with no
  `batch_summaries` argument.
- No repository query finds batch summaries by article-publish-date window (the
  closest existing function, `list_eligible_unbatched_articles`, is article-level
  and "not yet batched"-scoped — it answers a different question).
- No `POST /pipelines/weekly` / `POST /pipelines/monthly` API routes.
- `/workflows/trigger`'s `cadence="daily"` branch has the identical bug today
  (calls `runner.run_daily` directly, bypassing `DailyBriefPipeline`) — a
  pre-existing inconsistency from PR #3, not introduced by this spec. Since this
  slice already touches this route to add weekly/monthly, it fixes daily's branch
  in the same change (confirmed in scope with the user) so there is exactly one
  correct way to trigger a real brief per cadence.

## 3. Product Behavior

### 3.1 Key design decision: weekly/monthly synthesize from batch summaries, not from Daily/Weekly Brief text

A Weekly Brief re-synthesizes directly over the week's underlying `BatchSummary`
records (the same article-batch-level evidence Daily consumes), not over the text
of that week's Daily Briefs. A Monthly Brief re-synthesizes over the month's
`BatchSummary` records, not over that month's Weekly Brief text. Reasons:

- `_frontier_synthesis`'s `batch_summaries` input is typed `list[BatchSummary]`
  end-to-end (`graphs.py`, `state.py`) — consuming `Brief` text instead would
  require changing that shared, already-implemented graph, which this slice must
  not touch (see §12).
- Citation provenance stays traceable to the original article-level batch summary
  in every cadence, never through an intermediate "summary of a summary" hop that
  would compound drift and break the existing citation-validation contract
  (`cited_batch_summary_ids` on `Brief` must reference real `BatchSummary` rows).
- Narrative continuity across cadences is already carried by two other existing
  mechanisms — `prior_briefs` context (§2) and the single continuously-versioned
  `NarrativeStateVersion` chain — so re-synthesizing from batch summaries does not
  lose continuity; it only changes what raw evidence is re-examined at each grain.

### 3.2 Window computation (must mirror the runner's own defaulting exactly)

`WorkflowRunner.run_weekly`/`run_monthly` only normalize the window when
`target_date` is omitted (defaults to "this week"/"this month" from
`date.today()`); if a caller passes `target_date` explicitly, it is used **as the
literal window start with no alignment** (`runner.py:201-202`, `213`). A caller
that passes an unaligned date silently creates a misaligned/overlapping window
with its own idempotency key. This slice must not change `WorkflowRunner` (§12),
so the new pipeline layer is fully responsible for normalizing any anchor date
into a canonical window start **before** calling the runner:

- Weekly: `week_start = anchor - timedelta(days=anchor.weekday())` (Monday),
  `week_end = week_start + timedelta(days=6)` (Sunday) — the exact formula
  `run_weekly` itself uses for its default case.
- Monthly: `month_start = anchor.replace(day=1)`, `month_end` = the day before the
  first of the next month — the exact formula `run_monthly` itself uses for its
  default case.
- The pipeline always calls `run_weekly(week_start, ...)` / `run_monthly(month_start,
  ...)` with the **computed, canonical** start — never the raw anchor — so the
  idempotency key the pipeline expects always matches the one `_execute` derives.

### 3.3 Selection algorithm (per pipeline run)

1. Determine `window_start`/`window_end` from an optional anchor date (§3.2;
   default anchor is `self._clock().date()`, matching `DailyBriefPipeline`'s
   injectable-clock pattern).
2. Query candidate batch summaries: all `BatchSummary` rows whose batch contains
   at least one article with `published_at` inside `[window_start, window_end]`
   (new repository function, §5).
3. For each candidate, check `is_batch_summary_cited(session, id, <this cadence>,
   exclude_covered_start=window_start, exclude_covered_end=window_end)` — skip if
   already cited for this exact cadence+window (supports safe reruns, mirrors
   `DailyBriefPipeline`'s existing exclusion pattern exactly).
4. If zero summaries survive selection, apply the same no-content/idempotent-retry
   short-circuit `DailyBriefPipeline` already uses (§3.4 below) — do not invoke the
   runner, do not create a `WorkflowRun`, unless retrying a non-terminal prior run.
5. Otherwise call `run_weekly`/`run_monthly` with the computed window start and the
   selected summaries.
6. On `WorkflowStatus.SUCCEEDED`, resolve the created `Brief` via
   `get_brief_by_cadence_interval(session, cadence, window_start, window_end)`
   (already generic, reused as-is) for the result's `brief_id`.

This is a deliberate, intentional difference from Daily: because weekly/monthly
selection has no "resolved this run" set to scope against (Daily's batches are
freshly created/reused in the same call; weekly/monthly never batch anything), the
window-based candidate query is unconditional over the whole covered window, not
limited to "batches touched this run." A batch summary whose articles were
ingested late (after its nominal publish date, so it never appeared in that
particular Daily Brief) is still correctly picked up by the enclosing week's
selection — this is a natural, welcome side effect of the independent-per-cadence
citation tracking already built in, not a new mechanism.

### 3.4 No-content / idempotent-rerun short-circuit

Reuse `DailyBriefPipeline.run`'s exact pattern (`pipeline/daily_brief.py:177-209`),
generalized to arbitrary cadence + window:

```
idempotency_key = f"{cadence.value}:{window_start.isoformat()}:{window_end.isoformat()}"
existing_run = await get_workflow_run_by_idempotency(session, idempotency_key)
if existing_run is None or existing_run.status not in (SUCCEEDED, FAILED):
    return <no-content result>  # no WorkflowRun/Brief created
# else: existing_run is terminal -> fall through to run_weekly/run_monthly,
# whose own _ensure_run + _execute terminal-status check returns it directly
# without re-invoking the graph (runner.py:123-124).
```

## 4. Data Model

No schema changes. No new Alembic migration. This slice is read-and-orchestrate
only against existing tables (`article`, `article_batch`, `batch_summary`, `brief`,
`workflow_run`, `narrative_state_version`) via existing domain models
(`BatchSummary`, `Brief`, `WorkflowRun`) and one new read-only repository query.

## 5. Interfaces

### 5.1 New repository function

`src/analyst_engine/persistence/repositories.py`:

```python
async def list_eligible_batch_summaries_for_window(
    session: AsyncSession, window_start: date, window_end: date
) -> list[BatchSummary]:
    """Batch summaries whose batch has >=1 article published within [window_start, window_end]."""
```

Query shape (mirrors `list_eligible_unbatched_articles`'s existing `exists(...
any_(...))` pattern): join `batch_summary` to `article_batch` on `batch_id`,
filter with `exists(select(1) from article where article.id = any(article_batch
.article_ids) and article.published_at` in the half-open UTC range for
`[window_start, window_end]`), order by `created_at asc, id asc` for determinism.
This function does **not** take a `cadence` argument — citation exclusion by
cadence stays the separate, already-existing `is_batch_summary_cited` call in the
pipeline's selection loop (§3.3 step 3), keeping this function single-purpose.

### 5.2 New pipeline

`src/analyst_engine/pipeline/periodic_brief.py` — **one** class parameterized by
cadence, not two near-duplicate classes, because the algorithm (§3.3) is identical
for weekly and monthly and only the window formula and which `WorkflowRunner`
method to call differ:

```python
@dataclass(frozen=True)
class PeriodicPipelineResult:
    cadence: Cadence
    covered_start: date
    covered_end: date
    summaries_selected: int
    is_no_content: bool
    workflow_run_id: UUID | None
    workflow_status: WorkflowStatus | None
    brief_id: UUID | None

class PeriodicBriefPipeline:
    def __init__(
        self,
        *,
        cadence: Cadence,  # Cadence.WEEKLY or Cadence.MONTHLY only
        session_factory: async_sessionmaker[AsyncSession],
        runner: WorkflowRunner,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None: ...

    async def run(self, anchor_date: date | None = None) -> PeriodicPipelineResult: ...
```

Two runtime instances are constructed (one per cadence), analogous to how the
existing `WorkflowRunner` is one instance shared across all three cadences today.

### 5.3 Consumers

- `runtime.py`: add `build_periodic_brief_pipeline(runtime, *, runner, cadence) ->
  PeriodicBriefPipeline` alongside the existing `build_daily_brief_pipeline`.
- `main.py`: construct both `weekly_pipeline`/`monthly_pipeline` instances the same
  place `pipeline` (daily) is built today; pass them into `register_schedules`.
- `scheduling.py`: `register_schedules` gains `weekly_pipeline`/`monthly_pipeline`
  parameters; the weekly/monthly `scheduler.add_job(...)` calls rebind from
  `runner.run_weekly`/`run_monthly` to `weekly_pipeline.run`/`monthly_pipeline.run`
  — the exact rebinding pattern `_run_daily_pipeline` already established for
  daily in PR #3.
- `api/app.py`: `app.state.weekly_pipeline`/`app.state.monthly_pipeline` set in the
  lifespan alongside the existing `app.state.pipeline` (daily). New routes (§6.1).
  `/workflows/trigger`'s three cadence branches all delegate to their pipeline's
  `.run(req.covered_start)` instead of calling the runner directly (fixes daily's
  pre-existing bypass in the same change, per §2).

## 6. API and Scheduling

### 6.1 API

- `POST /pipelines/weekly` — body `{"target_date": date}` (an anchor date within
  the target week; the pipeline normalizes it to Monday per §3.2). Response
  mirrors `DailyPipelineResultResponse`'s shape but only the fields
  `PeriodicPipelineResult` actually has (§5.2) — no `feeds_polled`/`batches_*`
  fields, since this pipeline does not ingest or batch.
- `POST /pipelines/monthly` — identical shape, anchor date normalized to the 1st
  of its month.
- `GET /briefs?cadence=weekly|monthly` and `GET /briefs/{brief_id}` — **no
  changes**; already generic (§2).
- `/workflows/trigger` — all three cadence branches now delegate to
  `app.state.pipeline` / `app.state.weekly_pipeline` / `app.state.monthly_pipeline`
  respectively (§5.3), each `.run(req.covered_start)`. Response shape (`TriggerResponse`:
  `run_id`, `status`, `idempotency_key`) is unchanged — it already only reports on
  the `WorkflowRun`, which every pipeline still returns/creates identically.

Auth: identical `_require_key` boundary already applied to `/pipelines/daily` and
`/workflows/trigger`. No changes to the auth policy itself.

### 6.2 Scheduler

Weekly job (Sunday 03:00) and monthly job (1st at 04:00) keep their existing
`CronTrigger` schedules; only their callable changes, from `runner.run_weekly`/
`run_monthly` to `weekly_pipeline.run`/`monthly_pipeline.run` (§5.3). No schedule
retiming — Sunday 03:00 already runs after that day's 02:00 daily job, so a normal
week's Sunday batch summaries are expected to already exist by the time the weekly
job runs (soft ordering assumption inherited from the existing cron schedule, not
newly introduced by this slice).

## 7. Configuration

No new settings. This slice introduces no new tunables (no new timeouts, size
limits, or thresholds) — it only selects and re-synthesizes over data the existing
Daily pipeline already produces under existing settings.

## 8. Security and Safety

No new attack surface. This slice adds no network calls, no new user-controlled
URLs, and no new untrusted content paths — it only reads already-validated,
already-persisted `BatchSummary` rows (validated at creation time by the existing
`BatchSummarizer`, §8 of the RSS-to-Daily-Brief spec) and passes them through the
existing, unmodified frontier-synthesis graph. The same `_require_key` boundary
already governs the new write/trigger routes.

## 9. Error and Transaction Semantics

- Selection (read-only) failures propagate; no partial state is written before the
  runner is invoked (mirrors Daily: batching/summarization writes happen before
  selection, but this slice's selection step performs no writes of its own).
- The runner's own claim/execute/checkpoint transaction semantics are unchanged
  and untouched (§12) — this pipeline is a caller, not a participant, in that
  transaction boundary.
- Rerunning the same window performs no duplicate analytical inserts: a terminal
  prior run is returned directly by `_execute`'s existing terminal-status check
  (§3.4); a non-terminal/missing prior run with zero eligible summaries returns
  the no-content result without creating a `WorkflowRun`.

## 10. Testing Strategy

### Unit

- `list_eligible_batch_summaries_for_window`: articles inside/outside/on the exact
  boundary of `[window_start, window_end]`; a batch with mixed in-window and
  out-of-window article dates (must be included, matching Daily's "at least one
  in-window article" precedent, §3.3); an empty window.
- `PeriodicBriefPipeline.run` (fakes for `WorkflowRunner`, in-memory repository
  stand-ins matching the existing `_ServiceHarness`/fake-repository test pattern
  used by `test_daily_brief_pipeline.py`): weekly window normalization from a
  mid-week anchor; monthly window normalization from a mid-month anchor and from
  December (year rollover); no-content short-circuit on first run vs. on a
  terminal-run retry; already-cited-for-this-cadence exclusion; already-cited-for-
  a-different-cadence is **not** excluded (the same batch summary is eligible for
  both a Daily and a Weekly brief independently, per §2).
- `/workflows/trigger`'s three redelegated branches: each calls its pipeline's
  `.run`, not the runner directly (regression test for the fix in §5.3).

### Integration

- `list_eligible_batch_summaries_for_window` against PostgreSQL with real
  `article`/`article_batch`/`batch_summary` rows spanning a window boundary.
- End-to-end: seed a week's worth of persisted batch summaries (as
  `DailyBriefPipeline`/`BatchSummarizer` would produce them), run
  `PeriodicBriefPipeline(cadence=WEEKLY).run(...)`, assert a real `Brief` +
  `NarrativeStateVersion` are created via the checkpointed workflow with a fake
  model gateway (mirrors the existing `test_daily_pipeline.py` integration test
  structure).

### API

- `POST /pipelines/weekly`/`monthly` content/no-content/failure behavior.
- `/workflows/trigger` for all three cadences now produces a real (non-empty)
  `WorkflowRun` outcome when eligible summaries exist, not an empty-context one.

## 11. Success Criteria

1. A week with three or more days of persisted batch summaries produces one
   durable Weekly Brief citing summaries from across that week, not just one day.
2. A month with weekly activity across at least two weeks produces one durable
   Monthly Brief.
3. Rerunning the same week/month performs no duplicate analytical inserts and
   returns the existing terminal workflow result.
4. A batch summary already cited by a Daily brief is still independently eligible
   for that week's Weekly brief (and a Weekly-cited summary for its Monthly
   brief) — cadence-independent citation tracking, verified explicitly by test.
5. The scheduler's weekly/monthly cron jobs and `/pipelines/weekly`/`monthly` and
   `/workflows/trigger` all produce identical outcomes for the same window,
   because all three now call the same `PeriodicBriefPipeline` instance.
6. `GET /briefs?cadence=weekly` and `?cadence=monthly` return the new briefs with
   fully resolved citations, using the existing, unmodified route.
7. Ruff, strict mypy, routine tests, and PostgreSQL integration tests pass; no
   existing daily-cadence test regresses from the `/workflows/trigger` fix.

## 12. Constraints and Implementation Guidance

- Do not modify `workflows/graphs.py` or `workflows/runner.py`. Every behavior
  this slice needs from them (window computation, idempotency, checkpointing,
  prior-briefs context) already exists and is correct (§2) — this is strictly an
  orchestration-layer addition above them, mirroring the boundary
  `DailyBriefPipeline` already respects for `run_daily`.
- `PeriodicBriefPipeline` must be one cadence-parameterized class, not two
  near-duplicate `WeeklyBriefPipeline`/`MonthlyBriefPipeline` classes (§5.2) — the
  selection algorithm is identical; only the window formula and which runner
  method to call differ, and that's a small, explicit branch, not a reason to
  fork the class.
- Do not introduce a generic "which BatchSummary rows count as evidence for cadence
  X" abstraction beyond what §3.3 specifies — resist expanding this into a
  configurable/pluggable selection strategy; the daily/weekly/monthly split is the
  only one requested.
- Preserve `list_eligible_batch_summaries_for_window`'s single responsibility
  (window-based candidate discovery only); keep cadence-based citation exclusion
  in the pipeline's selection loop via the existing `is_batch_summary_cited`, not
  folded into the new query.
- Each implementation task lands separately with its own TODO sub-item, git note,
  and full `ruff format --check` + `ruff check` + `mypy src tests` +
  `uv run pytest` gate before commit, per the standing CLAUDE.md workflow.
