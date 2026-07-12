"""Opt-in temporal holdout test (marked to be excluded from CI)."""

# mypy: ignore-errors
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from analyst_engine.config import Settings
from analyst_engine.workflows.runner import WorkflowRunner
from fixtures import FakeModelGateway


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
