# 2026-07-15 — Eval Harness Parity Documentation (codex/eval-harness-parity)

**Merge:** PR #5 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/5)
**Merge commit:** 2a825dc7e2c2f7ab27b67864914e221f58fbb223
**Feature branch:** codex/eval-harness-parity
**Merged:** 2026-07-15T17:24:30Z

## Completed Work

- [x] Document why `tests/evaluation/test_temporal_holdout.py` intentionally
      drives `WorkflowRunner` directly instead of
      `DailyBriefPipeline`/`PeriodicBriefPipeline` (`a2269c9`)
- [x] Correct two accuracy issues in that docstring per code review, and add
      a note that the test is presently skip-only/not runnable if unskipped
      (`6315259`)

## Summary

`tests/evaluation/test_temporal_holdout.py` (opt-in, excluded from routine
CI) drives `WorkflowRunner.run_daily/weekly/monthly` directly, bypassing
`DailyBriefPipeline`/`PeriodicBriefPipeline` - the path every production
trigger (scheduler, API, `/workflows/trigger`) actually uses. `TODO.md`
flagged this and offered two branches: reroute the test through the
pipelines, or document why it intentionally shortcuts them. Rerouting was
rejected: the pipelines only operate against a live Postgres database (live
ingestion, batching, and summarization before selecting evidence), while
this harness replays a synthetic corpus with `session_factory=None` and no
database at all - building corpus-to-Postgres seeding infra for a skip-only,
opt-in smoke test was judged new scope, not a parity fix. Chose to document
the gap instead: the module docstring and `docs/testing.md`'s test-layout
section now state plainly what the harness does and does not exercise, and
note that removing the `@pytest.mark.skip` today would not currently
produce a working run (`WorkflowRunner(session_factory=None)` raises
`TypeError` on its first `session_scope()` call).

A bundled code review (self-reviewed via `gh api` PENDING review, not an
external agent for this small a change) caught two overstated claims in the
first draft of the docstring - that the harness "replays" a corpus (it
doesn't; the corpus file is written but never parsed back), and that the
pipelines "only select" evidence (they also do live ingestion/batching/
summarization). Both were corrected before merge.

Root cause: not a bug. Pre-existing intentional design gap named in
`TODO.md`'s Future Backlog; this session closed the "undocumented" half.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` / `uv run mypy src
  tests` / `uv run pytest` - all green (245 passed, 2 skipped, same skip
  count as before) on both commits.
- CI (`quality` job) green on the final commit.
- No behavior change; docs/docstring only.
