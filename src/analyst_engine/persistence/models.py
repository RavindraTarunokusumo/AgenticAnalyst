"""SQLAlchemy 2.0 ORM models.

These map 1:1 to the tables created by the initial migration. Domain
Pydantic models remain the public contracts; repositories translate.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


class Source(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stable_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    articles: Mapped[list[Article]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Article(Base):
    __tablename__ = "article"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_fingerprint: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    language: Mapped[str | None] = mapped_column(String(16))
    raw_content_hash: Mapped[str | None] = mapped_column(String(128))
    cleaned_content: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="articles")


class ArticleBatch(Base):
    __tablename__ = "article_batch"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    grouping_method: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    similarity_threshold: Mapped[float | None] = mapped_column(Float)
    grouping_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )


class BatchSummary(Base):
    __tablename__ = "batch_summary"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_notes: Mapped[str | None] = mapped_column(Text)
    entities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )


class NarrativeStateVersion(Base):
    __tablename__ = "narrative_state_version"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_by_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    change_log: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class PredictionExpectation(Base):
    __tablename__ = "prediction_expectation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    narrative_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confirmation_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    falsification_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class Brief(Base):
    __tablename__ = "brief"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    covered_start: Mapped[date] = mapped_column(Date, nullable=False)
    covered_end: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cited_batch_summary_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    cited_article_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    narrative_state_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "cadence", "covered_start", "covered_end", name="uq_brief_cadence_interval"
        ),
    )


class Embedding(Base):
    __tablename__ = "embedding"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    checkpoint_ref: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
