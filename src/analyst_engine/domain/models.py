"""Pydantic domain models for durable records and workflow contracts.

These are pure data contracts. No infrastructure imports (FastAPI, SQLAlchemy,
LangGraph, or provider SDKs) are allowed here.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Cadence(StrEnum):
    """Supported briefing cadences."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class WorkflowStatus(StrEnum):
    """Lifecycle status for a workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RESUMABLE = "resumable"


class GroupingMethod(StrEnum):
    """How an article batch was formed."""

    TITLE_COSINE = "title_cosine"
    CONTENT_COSINE = "content_cosine"


class Citation(BaseModel):
    """Provenance pointer from a summary or brief back to a source article."""

    model_config = {"frozen": True}

    article_id: UUID
    excerpt: str | None = Field(
        default=None,
        description="Short verbatim excerpt from the article used in the summary.",
    )


class Source(BaseModel):
    """Registered information source."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    stable_id: str = Field(description="Stable external identifier for the source.")
    name: str
    normalized_domain: str = Field(
        description="Lower-cased registered domain used for dedup and grouping."
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Article(BaseModel):
    """Immutable captured article with provenance."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    url: str
    url_fingerprint: str = Field(description="Stable hash of normalized URL for deduplication.")
    title: str
    author: str | None = None
    published_at: datetime
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    language: str | None = None
    raw_content_hash: str | None = Field(
        default=None, description="Hash of original fetched payload for audit."
    )
    cleaned_content: str | None = Field(
        default=None, description="Normalized body used for embedding and summarization."
    )

    @field_validator("url_fingerprint")
    @classmethod
    def _nonempty_fingerprint(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("url_fingerprint must not be empty")
        return v


class ArticleBatch(BaseModel):
    """Deterministic grouping of 3-5 related articles for batch summarization."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    article_ids: list[UUID] = Field(min_length=3, max_length=5)
    grouping_method: GroupingMethod
    embedding_model: str
    similarity_threshold: float | None = None
    grouping_run_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("article_ids")
    @classmethod
    def _ordered_unique(cls, v: list[UUID]) -> list[UUID]:
        if len(v) != len(set(v)):
            raise ValueError("article_ids must be unique within a batch")
        # caller ensures order; we accept the provided order
        return v


class BatchSummary(BaseModel):
    """Validated output of the Flash model over one article batch."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    model: str = Field(description="e.g. qwen3.5-flash@<version>")
    prompt_version: str
    summary: str
    source_notes: str | None = None
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    citations: list[Citation]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def _has_citations(self) -> BatchSummary:
        if not self.citations:
            raise ValueError("batch_summary must include at least one citation")
        return self


class NarrativeStateVersion(BaseModel):
    """Versioned snapshot of the evolving analytical narrative state."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    parent_id: UUID | None = None
    created_by_run_id: UUID
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured narrative facts, themes, and open questions.",
    )
    change_log: list[str] = Field(
        default_factory=list,
        description="Human-readable deltas applied in this version.",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PredictionExpectation(BaseModel):
    """A falsifiable expectation attached to a narrative version."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    narrative_version_id: UUID
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    confirmation_criteria: str
    falsification_criteria: str
    outcome_status: str = Field(
        default="pending",
        description="pending | confirmed | falsified | superseded",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Brief(BaseModel):
    """Synthesized output for a cadence (Daily/Weekly/Monthly)."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    cadence: Cadence
    covered_start: date
    covered_end: date
    content: str
    cited_batch_summary_ids: list[UUID]
    cited_article_ids: list[UUID]
    narrative_state_version_id: UUID | None = None
    created_by_run_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def _has_citations(self) -> Brief:
        if not self.cited_batch_summary_ids:
            raise ValueError("brief must cite at least one batch_summary")
        return self


class Embedding(BaseModel):
    """Vector embedding of a brief for archive retrieval."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    brief_id: UUID
    model: str = Field(description="text-embedding-v4 or equivalent")
    vector: list[float]
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Filterable columns (cadence, date bounds, source scope).",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("vector")
    @classmethod
    def _nonempty_vector(cls, v: list[float]) -> list[float]:
        if len(v) < 2:
            raise ValueError("embedding vector must have dimension >= 2")
        return v


class WorkflowRun(BaseModel):
    """Record of a cadence workflow execution (supports idempotency + resumption)."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    cadence: Cadence
    idempotency_key: str = Field(
        description="Stable key e.g. 'daily:2026-07-09' or 'weekly:2026-W28'"
    )
    status: WorkflowStatus = WorkflowStatus.PENDING
    checkpoint_ref: str | None = Field(
        default=None, description="LangGraph thread_id or checkpoint identifier"
    )
    error_summary: str | None = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @field_validator("idempotency_key")
    @classmethod
    def _nonempty_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("idempotency_key must not be empty")
        return v
