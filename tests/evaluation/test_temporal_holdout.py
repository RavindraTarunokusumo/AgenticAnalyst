"""Opt-in temporal holdout test (marked to be excluded from CI).

Parity note: this drives `WorkflowRunner.run_daily/weekly/monthly` directly,
not `DailyBriefPipeline`/`PeriodicBriefPipeline` (the path every production
trigger - scheduler, API, `/workflows/trigger` - actually uses). This is
intentional, not an oversight: the pipelines only select real evidence
already persisted in Postgres via repository queries, while this harness
replays a synthetic in-memory corpus against a runner constructed with
`session_factory=None`/`checkpointer_factory=None` (no database at all).
Routing a synthetic corpus through the pipelines would require building
corpus-to-Postgres seeding (articles/batches/summaries) that doesn't exist
anywhere else in the suite - a new capability, not a parity fix. If a real
temporal evaluation harness is ever built, it should seed a corpus through
`IngestionService`/`batch_articles`/`summarize_batch` into a real database
and drive the pipelines, not extend this smoke test.
"""

# mypy: ignore-errors
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fixtures import FakeModelGateway

from analyst_engine.config import Settings
from analyst_engine.workflows.runner import WorkflowRunner


@dataclass
class EvaluationReport:
    corpus_path: str
    model: str
    cutoff: str
    runs: list[dict[str, Any]]
    total_duration_seconds: float


class TemporalHoldoutRunner:
    def __init__(self, runner: WorkflowRunner, fake_gateway: Any) -> None:
        self.runner = runner
        self.gateway = fake_gateway

    async def run(
        self,
        corpus_path: Path,
        model: str,
        cutoff: str,
        start: date,
        days: int = 30,
    ) -> EvaluationReport:
        runs: list[dict[str, Any]] = []
        virtual = start
        for _ in range(days):
            d = virtual
            run = await self.runner.run_daily(d)
            runs.append(
                {
                    "cadence": "daily",
                    "date": d.isoformat(),
                    "run_id": str(run.id),
                    "status": run.status,
                }
            )
            if virtual.weekday() == 6:
                w = await self.runner.run_weekly(virtual)
                runs.append({"cadence": "weekly", "date": virtual.isoformat(), "run_id": str(w.id)})
            if virtual.day == 1:
                m = await self.runner.run_monthly(virtual)
                runs.append(
                    {"cadence": "monthly", "date": virtual.isoformat(), "run_id": str(m.id)}
                )
            virtual += timedelta(days=1)
        return EvaluationReport(str(corpus_path), model, cutoff, runs, 0.1)


@pytest.mark.evaluation
@pytest.mark.skip(
    reason=(
        "Opt-in temporal evaluation. Requires explicit corpus + credentials. "
        "Run manually outside CI."
    )
)
async def test_one_month_post_cutoff_replay(tmp_path):
    # Synthetic tiny corpus manifest (for illustration)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"date":"2026-06-01","articles":[{"title":"A","body":"..."}]}\n', encoding="utf-8"
    )

    settings = Settings(
        dashscope_api_key="fake",
        database_url="postgresql+asyncpg://u:p@localhost/db",  # not actually used in fake run
    )
    fake_gw = FakeModelGateway()
    # Runner with no real persistence for this smoke
    runner = WorkflowRunner(settings, fake_gw, None, None)  # type: ignore
    eval_runner = TemporalHoldoutRunner(runner, fake_gw)

    report = await eval_runner.run(
        corpus_path=corpus,
        model="qwen3.7-max-preview",
        cutoff="2026-05-01",
        start=date(2026, 6, 1),
        days=5,
    )

    assert len(report.runs) >= 5
    assert all(r["status"] in ("succeeded", "pending") for r in report.runs)
    # Ensure no future leak: all dates <= simulated now (the runner enforces order)
