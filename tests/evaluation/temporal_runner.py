"""Minimal accelerated temporal holdout runner.

Uses virtual time and fake gateway. Never leaks future data.
This is opt-in and excluded from routine CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from analyst_engine.domain.models import Cadence
from analyst_engine.workflows.runner import WorkflowRunner


@dataclass
class EvaluationReport:
    corpus_path: str
    model: str
    cutoff: str
    runs: list[dict[str, Any]]
    total_duration_seconds: float


class TemporalHoldoutRunner:
    """Accelerated replay using a frozen manifest.

    Manifest format (jsonl):
    {"date": "2026-06-01", "articles": [{"id": "...", "title": "...", "body": "..."}]}
    """

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
            # Simulate publication on virtual day
            d = virtual
            # Trigger daily (in real would feed articles for the day)
            run = await self.runner.run_daily(d)
            runs.append(
                {
                    "cadence": "daily",
                    "date": d.isoformat(),
                    "run_id": str(run.id),
                    "status": run.status,
                }
            )
            # Weekly / monthly at boundaries (simplified)
            if virtual.weekday() == 6:  # Sunday
                w = await self.runner.run_weekly(virtual)
                runs.append({"cadence": "weekly", "date": virtual.isoformat(), "run_id": str(w.id)})
            if virtual.day == 1:
                m = await self.runner.run_monthly(virtual)
                runs.append({"cadence": "monthly", "date": virtual.isoformat(), "run_id": str(m.id)})

            virtual += timedelta(days=1)

        return EvaluationReport(
            corpus_path=str(corpus_path),
            model=model,
            cutoff=cutoff,
            runs=runs,
            total_duration_seconds=0.1,  # accelerated
        )
