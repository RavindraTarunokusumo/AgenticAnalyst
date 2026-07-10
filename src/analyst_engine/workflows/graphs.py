"""Cadence workflow graph builders (LangGraph).

Daily: cited batches → frontier synthesis (Brief + Narrative proposal)
Weekly/Monthly: rollups over prior briefs + retrieval.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from analyst_engine.domain.models import (
    Brief,
    Cadence,
    NarrativeStateVersion,
    PredictionExpectation,
)
from analyst_engine.models.gateway import ModelGateway, ModelTask
from analyst_engine.persistence.repositories import (
    get_brief_by_cadence_interval,
    save_brief,
    save_narrative_version,
)
from analyst_engine.workflows.state import (
    BriefGenerationInput,
    BriefGenerationOutput,
    CadenceWorkflowState,
)


async def _frontier_synthesis(
    gateway: ModelGateway,
    inp: BriefGenerationInput,
) -> BriefGenerationOutput:
    """Call the frontier model for the given cadence."""
    task = {
        Cadence.DAILY: ModelTask.FRONTIER_DAILY,
        Cadence.WEEKLY: ModelTask.FRONTIER_WEEKLY,
        Cadence.MONTHLY: ModelTask.FRONTIER_MONTHLY,
    }[inp.cadence]

    # In a real impl we would build rich prompt from summaries + prior state.
    # Here we send a minimal prompt and expect JSON matching Brief + Narrative.
    messages = [
        {
            "role": "system",
            "content": "You are an analytical synthesis engine. Return strict JSON.",
        },
        {
            "role": "user",
            "content": f"Synthesize a {inp.cadence} brief for {inp.covered_start} to {inp.covered_end}. "
            f"Use these batch summaries: {[s.id for s in inp.batch_summaries]}. "
            f"Prior narrative: {inp.current_narrative.id if inp.current_narrative else 'none'}.",
        },
    ]

    # For harness we use a loose schema; real impl would have dedicated output model
    class _FrontierResult(BaseModel):
        brief_content: str
        narrative_state: dict[str, Any]
        change_log: list[str]
        expectations: list[dict[str, Any]] = []

    result, usage = await gateway.generate(
        task=task,
        messages=messages,
        output_schema=_FrontierResult,
        correlation_id=inp.correlation_id,
    )

    # Build domain objects (simplified for harness)
    brief = Brief(
        cadence=inp.cadence,
        covered_start=inp.covered_start,
        covered_end=inp.covered_end,
        content=result.brief_content,
        cited_batch_summary_ids=[s.id for s in inp.batch_summaries],
        cited_article_ids=[],  # populated upstream in real flow
        created_by_run_id=inp.correlation_id,  # placeholder
    )

    narrative = NarrativeStateVersion(
        created_by_run_id=inp.correlation_id,
        state=result.narrative_state,
        change_log=result.change_log,
    )

    expectations = [
        PredictionExpectation(
            narrative_version_id=narrative.id,
            statement=e.get("statement", ""),
            confidence=float(e.get("confidence", 0.5)),
            confirmation_criteria=e.get("confirmation", ""),
            falsification_criteria=e.get("falsification", ""),
        )
        for e in result.expectations
    ]

    return BriefGenerationOutput(
        brief=brief,
        proposed_narrative_version=narrative,
        proposed_expectations=expectations,
    )


async def daily_frontier_node(state: dict[str, Any], gateway: ModelGateway, session) -> dict[str, Any]:
    """Daily node: produce brief + narrative proposal from batch summaries."""
    inp = BriefGenerationInput(
        cadence=Cadence(state["cadence"]),
        covered_start=date.fromisoformat(state["covered_start"]),
        covered_end=date.fromisoformat(state["covered_end"]),
        batch_summaries=state.get("batch_summaries", []),
        correlation_id=state["correlation_id"],
    )
    out = await _frontier_synthesis(gateway, inp)

    # Persist atomically (in real code use session_scope + repos)
    await save_brief(session, out.brief)
    await save_narrative_version(session, out.proposed_narrative_version)

    return {
        "brief": out.brief.model_dump(),
        "proposed_narrative": out.proposed_narrative_version.model_dump(),
        "error": None,
    }


def build_daily_graph(gateway: ModelGateway, session_factory) -> StateGraph:
    """Build the daily cadence graph."""
    builder = StateGraph(CadenceWorkflowState)

    async def node(state: CadenceWorkflowState) -> dict[str, Any]:
        # In real usage the graph would be compiled with checkpointer
        # and nodes would receive injected deps via context or partial
        async with session_factory() as session:
            return await daily_frontier_node(state.model_dump(), gateway, session)

    builder.add_node("frontier", node)
    builder.set_entry_point("frontier")
    builder.add_edge("frontier", END)
    return builder


# Weekly and monthly are similar rollups (simplified for harness completeness)
def build_weekly_graph(gateway: ModelGateway, session_factory) -> StateGraph:
    builder = StateGraph(CadenceWorkflowState)

    async def node(state: CadenceWorkflowState) -> dict[str, Any]:
        # Placeholder that reuses daily logic shape
        async with session_factory() as session:
            inp = BriefGenerationInput(
                cadence=Cadence.WEEKLY,
                covered_start=date.fromisoformat(state.covered_start.isoformat() if hasattr(state, "covered_start") else str(state["covered_start"])),
                covered_end=date.fromisoformat(state.covered_end.isoformat() if hasattr(state, "covered_end") else str(state["covered_end"])),
                correlation_id=state.correlation_id if hasattr(state, "correlation_id") else state["correlation_id"],
            )
            out = await _frontier_synthesis(gateway, inp)
            await save_brief(session, out.brief)
            return {"brief": out.brief.model_dump(), "proposed_narrative": out.proposed_narrative_version.model_dump()}

    builder.add_node("rollup", node)
    builder.set_entry_point("rollup")
    builder.add_edge("rollup", END)
    return builder


def build_monthly_graph(gateway: ModelGateway, session_factory) -> StateGraph:
    # Same shape as weekly for harness
    return build_weekly_graph(gateway, session_factory)
