"""Cadence-specific LangGraph builders and durable frontier synthesis."""

from __future__ import annotations

from contextlib import suppress
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
    Embedding,
    NarrativeStateVersion,
    PredictionExpectation,
)
from analyst_engine.models.gateway import ModelGateway, ModelTask
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    save_brief,
    save_embedding,
    save_narrative_version,
    save_prediction_expectation,
)
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
    summary_context = [
        {
            "id": str(summary.id),
            "summary": summary.summary,
            "source_notes": summary.source_notes,
            "entities": summary.entities,
            "topics": summary.topics,
            "citations": [citation.model_dump(mode="json") for citation in summary.citations],
        }
        for summary in inp.batch_summaries
    ]
    current_state = inp.current_narrative.state if inp.current_narrative else None
    messages = [
        {
            "role": "system",
            "content": "You are an analytical synthesis engine. Return strict JSON.",
        },
        {
            "role": "user",
            "content": (
                f"Synthesize a {inp.cadence.value} brief for {inp.covered_start} "
                f"to {inp.covered_end}. Batch summaries: {summary_context}. "
                f"Prior briefs: {[b.content for b in inp.prior_briefs]}. "
                f"Current narrative: {current_state}."
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
        parent_id=inp.current_narrative.id if inp.current_narrative else None,
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
        prior_briefs = [Brief.model_validate(item) for item in state.get("prior_briefs", [])]
        current_narrative = (
            NarrativeStateVersion.model_validate(state["current_narrative"])
            if state.get("current_narrative") is not None
            else None
        )
        inp = BriefGenerationInput(
            cadence=cadence,
            covered_start=date.fromisoformat(str(state["covered_start"])),
            covered_end=date.fromisoformat(str(state["covered_end"])),
            batch_summaries=summaries,
            prior_briefs=prior_briefs,
            current_narrative=current_narrative,
            correlation_id=str(state["correlation_id"]),
        )
        output = await _frontier_synthesis(gateway, inp)

        # Best-effort: run the embed() network call before opening the DB
        # transaction below, so a slow/failing provider call never holds a
        # pooled connection + open transaction. A model-side failure here is
        # swallowed the same way a DB-side save_embedding failure is below.
        embedding_vector: list[float] | None = None
        with suppress(Exception):
            embedding_vector, _usage = await gateway.embed(
                text=output.brief.content, correlation_id=inp.correlation_id
            )

        async with session_scope(session_factory) as session:
            await save_narrative_version(session, output.proposed_narrative_version)
            for expectation in output.proposed_expectations:
                await save_prediction_expectation(session, expectation)
            await save_brief(session, output.brief)
            if embedding_vector is not None:
                # A DB-side save_embedding flush failure must not roll back the
                # already-flushed brief/narrative/expectations above. A plain
                # try/except is not enough: Postgres aborts the whole
                # transaction on a failed statement, so the outer
                # session.commit() in session_scope would then fail too. A
                # SAVEPOINT (begin_nested) isolates the failure to this block.
                try:
                    async with session.begin_nested():
                        await save_embedding(
                            session,
                            Embedding(
                                brief_id=output.brief.id,
                                model=gateway.get_model_for_task(ModelTask.EMBED),
                                vector=embedding_vector,
                            ),
                        )
                except Exception:
                    pass
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
