"""Cadence-specific LangGraph builders and durable frontier synthesis."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.domain.models import (
    BatchSummary,
    Brief,
    Cadence,
    NarrativeStateVersion,
    PredictionExpectation,
)
from analyst_engine.models.gateway import ModelGateway, ModelTask
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import save_brief, save_narrative_version
from analyst_engine.workflows.state import BriefGenerationInput, BriefGenerationOutput


class FrontierResult(BaseModel):
    brief_content: str
    narrative_state: dict[str, Any]
    change_log: list[str]
    expectations: list[dict[str, Any]] = Field(default_factory=list)


async def _frontier_synthesis(
    gateway: ModelGateway,
    inp: BriefGenerationInput,
) -> BriefGenerationOutput:
    task = {
        Cadence.DAILY: ModelTask.FRONTIER_DAILY,
        Cadence.WEEKLY: ModelTask.FRONTIER_WEEKLY,
        Cadence.MONTHLY: ModelTask.FRONTIER_MONTHLY,
    }[inp.cadence]
    messages = [
        {
            "role": "system",
            "content": "You are an analytical synthesis engine. Return strict JSON.",
        },
        {
            "role": "user",
            "content": (
                f"Synthesize a {inp.cadence.value} brief for {inp.covered_start} "
                f"to {inp.covered_end}. Use batch summaries "
                f"{[str(s.id) for s in inp.batch_summaries]}."
            ),
        },
    ]
    result, _usage = await gateway.generate(
        task=task,
        messages=messages,
        output_schema=FrontierResult,
        correlation_id=inp.correlation_id,
    )
    frontier = FrontierResult.model_validate(result)
    run_id = UUID(inp.correlation_id)
    cited_articles = list(
        dict.fromkeys(
            citation.article_id for summary in inp.batch_summaries for citation in summary.citations
        )
    )
    narrative = NarrativeStateVersion(
        created_by_run_id=run_id,
        state=frontier.narrative_state,
        change_log=frontier.change_log,
        created_at=datetime.now(UTC),
    )
    brief = Brief(
        cadence=inp.cadence,
        covered_start=inp.covered_start,
        covered_end=inp.covered_end,
        content=frontier.brief_content,
        cited_batch_summary_ids=[summary.id for summary in inp.batch_summaries],
        cited_article_ids=cited_articles,
        narrative_state_version_id=narrative.id,
        created_by_run_id=run_id,
        created_at=datetime.now(UTC),
    )
    expectations = [
        PredictionExpectation(
            narrative_version_id=narrative.id,
            statement=str(item.get("statement", "")),
            confidence=float(item.get("confidence", 0.5)),
            confirmation_criteria=str(item.get("confirmation", "")),
            falsification_criteria=str(item.get("falsification", "")),
            created_at=datetime.now(UTC),
        )
        for item in frontier.expectations
    ]
    return BriefGenerationOutput(
        brief=brief,
        proposed_narrative_version=narrative,
        proposed_expectations=expectations,
    )


def _build_graph(
    cadence: Cadence,
    gateway: ModelGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> StateGraph[Any]:
    builder = StateGraph(dict[str, Any])  # type: ignore[type-var]

    async def synthesize(state: dict[str, Any]) -> dict[str, Any]:
        summaries = [BatchSummary.model_validate(item) for item in state.get("batch_summaries", [])]
        inp = BriefGenerationInput(
            cadence=cadence,
            covered_start=date.fromisoformat(str(state["covered_start"])),
            covered_end=date.fromisoformat(str(state["covered_end"])),
            batch_summaries=summaries,
            correlation_id=str(state["correlation_id"]),
        )
        output = await _frontier_synthesis(gateway, inp)
        async with session_scope(session_factory) as session:
            await save_narrative_version(session, output.proposed_narrative_version)
            await save_brief(session, output.brief)
        return {
            "brief": output.brief.model_dump(mode="python"),
            "proposed_narrative": output.proposed_narrative_version.model_dump(mode="python"),
            "error": None,
        }

    builder.add_node("frontier", synthesize)  # type: ignore[type-var]
    builder.set_entry_point("frontier")
    builder.add_edge("frontier", END)
    return builder


def build_daily_graph(
    gateway: ModelGateway, session_factory: async_sessionmaker[AsyncSession]
) -> StateGraph[Any]:
    return _build_graph(Cadence.DAILY, gateway, session_factory)


def build_weekly_graph(
    gateway: ModelGateway, session_factory: async_sessionmaker[AsyncSession]
) -> StateGraph[Any]:
    return _build_graph(Cadence.WEEKLY, gateway, session_factory)


def build_monthly_graph(
    gateway: ModelGateway, session_factory: async_sessionmaker[AsyncSession]
) -> StateGraph[Any]:
    return _build_graph(Cadence.MONTHLY, gateway, session_factory)
