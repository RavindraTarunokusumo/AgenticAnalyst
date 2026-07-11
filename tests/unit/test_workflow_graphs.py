from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from analyst_engine.domain.models import BatchSummary, Cadence, Citation
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.workflows.graphs import (
    _frontier_synthesis,
    build_daily_graph,
    build_monthly_graph,
    build_weekly_graph,
)
from analyst_engine.workflows.state import BriefGenerationInput


class _Gateway(ModelGateway):
    def __init__(self, *, malformed: bool = False) -> None:
        self.malformed = malformed
        self.tasks: list[ModelTask] = []

    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel],
        correlation_id: str,
    ) -> tuple[BaseModel, ModelUsage]:
        self.tasks.append(task)
        if self.malformed:

            class EmptyResult(BaseModel):
                pass

            return EmptyResult(), ModelUsage(model="fake")
        return (
            output_schema(
                brief_content=f"{task.value} brief",
                narrative_state={"cadence": task.value},
                change_log=["updated"],
            ),
            ModelUsage(model="fake"),
        )

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake"


def _input(cadence: Cadence) -> BriefGenerationInput:
    run_id = UUID("00000000-0000-0000-0000-000000000001")
    article_id = UUID("00000000-0000-0000-0000-000000000011")
    summary = BatchSummary(
        id=UUID("00000000-0000-0000-0000-000000000012"),
        batch_id=UUID("00000000-0000-0000-0000-000000000010"),
        model="fake",
        prompt_version="v1",
        summary="summary",
        citations=[Citation(article_id=article_id)],
        created_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    return BriefGenerationInput(
        cadence=cadence,
        covered_start=date(2026, 7, 1),
        covered_end=date(2026, 7, 31),
        batch_summaries=[summary],
        correlation_id=str(run_id),
    )


@pytest.mark.parametrize(
    ("cadence", "task"),
    [
        (Cadence.DAILY, ModelTask.FRONTIER_DAILY),
        (Cadence.WEEKLY, ModelTask.FRONTIER_WEEKLY),
        (Cadence.MONTHLY, ModelTask.FRONTIER_MONTHLY),
    ],
)
async def test_frontier_outputs_keep_run_and_citation_lineage(
    cadence: Cadence, task: ModelTask
) -> None:
    gateway = _Gateway()
    inp = _input(cadence)

    output = await _frontier_synthesis(gateway, inp)

    run_id = UUID(inp.correlation_id)
    assert gateway.tasks == [task]
    assert output.brief.cadence is cadence
    assert output.brief.created_by_run_id == run_id
    assert output.proposed_narrative_version.created_by_run_id == run_id
    assert output.brief.narrative_state_version_id == output.proposed_narrative_version.id
    assert output.brief.cited_batch_summary_ids == [inp.batch_summaries[0].id]
    assert output.brief.cited_article_ids == [inp.batch_summaries[0].citations[0].article_id]


async def test_malformed_provider_output_does_not_create_domain_records() -> None:
    with pytest.raises(ValidationError):
        await _frontier_synthesis(_Gateway(malformed=True), _input(Cadence.DAILY))


@pytest.mark.parametrize(
    ("cadence", "build"),
    [
        (Cadence.DAILY, build_daily_graph),
        (Cadence.WEEKLY, build_weekly_graph),
        (Cadence.MONTHLY, build_monthly_graph),
    ],
)
async def test_each_cadence_graph_commits_brief_and_narrative(
    monkeypatch: pytest.MonkeyPatch, cadence: Cadence, build: Callable[..., object]
) -> None:
    session = object()

    @asynccontextmanager
    async def fake_scope(_factory: object) -> AsyncIterator[object]:
        yield session

    save_brief = AsyncMock()
    save_narrative = AsyncMock()
    monkeypatch.setattr("analyst_engine.workflows.graphs.session_scope", fake_scope)
    monkeypatch.setattr("analyst_engine.workflows.graphs.save_brief", save_brief)
    monkeypatch.setattr("analyst_engine.workflows.graphs.save_narrative_version", save_narrative)
    inp = _input(cadence)
    state = {
        "run_id": inp.correlation_id,
        "cadence": cadence.value,
        "covered_start": inp.covered_start.isoformat(),
        "covered_end": inp.covered_end.isoformat(),
        "idempotency_key": "key",
        "batch_summaries": [item.model_dump(mode="python") for item in inp.batch_summaries],
        "correlation_id": inp.correlation_id,
    }

    graph = build(_Gateway(), Mock()).compile()  # type: ignore[attr-defined]
    await graph.ainvoke(state)

    assert save_narrative.await_args_list[0].args[0] is session
    assert save_brief.await_args_list[0].args[0] is session
    assert save_brief.await_args_list[0].args[1].cadence is cadence
