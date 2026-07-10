"""Opt-in temporal holdout test (marked to be excluded from CI)."""

import pytest
from datetime import date

from analyst_engine.config import Settings
from tests.evaluation.temporal_runner import TemporalHoldoutRunner
from tests.fixtures import FakeModelGateway
from analyst_engine.workflows.runner import WorkflowRunner


@pytest.mark.evaluation
@pytest.mark.skip(reason="Opt-in temporal evaluation. Requires explicit corpus + credentials. Run manually outside CI.")
async def test_one_month_post_cutoff_replay(tmp_path):
    # Synthetic tiny corpus manifest (for illustration)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"date":"2026-06-01","articles":[{"title":"A","body":"..."}]}\n', encoding="utf-8")

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
