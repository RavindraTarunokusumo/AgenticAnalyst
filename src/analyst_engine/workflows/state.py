"""Typed state for cadence workflows.

All nodes consume and produce validated Pydantic state where possible.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from analyst_engine.domain.models import (
    BatchSummary,
    Brief,
    Cadence,
    NarrativeStateVersion,
    PredictionExpectation,
)


class BriefGenerationInput(BaseModel):
    """Input visible to a frontier synthesis node."""

    cadence: Cadence
    covered_start: date
    covered_end: date
    batch_summaries: list[BatchSummary] = Field(default_factory=list)
    prior_briefs: list[Brief] = Field(default_factory=list)
    current_narrative: NarrativeStateVersion | None = None
    correlation_id: str


class BriefGenerationOutput(BaseModel):
    """Output of a frontier node."""

    brief: Brief
    proposed_narrative_version: NarrativeStateVersion
    proposed_expectations: list[PredictionExpectation] = Field(default_factory=list)


class CadenceWorkflowState(BaseModel):
    """LangGraph state for a cadence run.

    We keep it small and validated at node boundaries.
    """

    run_id: str
    cadence: Cadence
    covered_start: date
    covered_end: date
    idempotency_key: str
    batch_summaries: list[BatchSummary] = Field(default_factory=list)
    brief: Brief | None = None
    proposed_narrative: NarrativeStateVersion | None = None
    error: str | None = None
    checkpoint_id: str | None = None
    correlation_id: str

    model_config = ConfigDict(arbitrary_types_allowed=True)
