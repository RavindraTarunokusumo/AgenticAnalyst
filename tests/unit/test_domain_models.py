"""Offline unit tests for pure pydantic domain models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from analyst_engine.domain.models import Topic


def test_topic_constructs_with_required_fields() -> None:
    topic = Topic(
        name="US-Iran war",
        description="Follow the conflict and related diplomacy.",
        keywords=["iran", "nuclear", "tehran"],
    )

    assert isinstance(topic.id, UUID)
    assert topic.name == "US-Iran war"
    assert topic.description == "Follow the conflict and related diplomacy."
    assert topic.interest_detail is None
    assert topic.keywords == ["iran", "nuclear", "tehran"]
    assert isinstance(topic.created_at, datetime)
    assert isinstance(topic.updated_at, datetime)


def test_topic_accepts_interest_detail() -> None:
    topic = Topic(
        name="Postgres 18",
        description="Release notes and breaking changes.",
        interest_detail="Focus on SQL features; exclude cloud managed offerings.",
        keywords=["postgres", "postgresql", "breaking change"],
    )

    assert topic.interest_detail == "Focus on SQL features; exclude cloud managed offerings."


def test_topic_rejects_empty_keywords() -> None:
    with pytest.raises(ValidationError, match="keywords must not be empty"):
        Topic(
            name="Empty keywords",
            description="Should fail validation.",
            keywords=[],
        )


def test_topic_rejects_whitespace_only_keyword_entries() -> None:
    with pytest.raises(ValidationError, match="empty or whitespace-only"):
        Topic(
            name="Whitespace keywords",
            description="Should fail validation.",
            keywords=["  ", "\t"],
        )


def test_topic_rejects_list_containing_blank_among_valid() -> None:
    with pytest.raises(ValidationError, match="empty or whitespace-only"):
        Topic(
            name="Mixed keywords",
            description="One blank entry is enough to reject.",
            keywords=["iran", "", "tehran"],
        )
