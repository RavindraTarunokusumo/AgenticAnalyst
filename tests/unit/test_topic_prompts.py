"""Offline unit tests for topic-assist prompt construction and schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from analyst_engine.topics.prompts import (
    ClarifyingQuestions,
    SuggestedKeywords,
    build_clarify_messages,
    build_keyword_suggestion_messages,
)

_PROMPT_VERSION = "v1"
_NAME = "Widget Reliability"
_DESCRIPTION = "Track reliability of the Foo widget after the 2.0 release."
_ANSWERS = [
    "Focus on post-release regressions and known workarounds.",
    "Exclude pure marketing announcements.",
]

# R7a tripwire: short domain-leakage blocklist, not an exhaustive filter.
_R7A_DOMAIN_BLOCKLIST = (
    "geopolit",
    "country",
    "countries",
    "conflict",
    "market",
    "election",
)


def test_build_clarify_messages_shape_and_interpolation() -> None:
    messages = build_clarify_messages(
        _NAME,
        _DESCRIPTION,
        prompt_version=_PROMPT_VERSION,
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[0]["content"]
    user_content = messages[1]["content"]
    assert _NAME in user_content
    assert _DESCRIPTION in user_content
    assert f"prompt_version: {_PROMPT_VERSION}" in user_content
    assert "ClarifyingQuestions" in user_content
    assert "UNTRUSTED DATA" in messages[0]["content"]


def test_build_keyword_suggestion_messages_shape_and_interpolation() -> None:
    messages = build_keyword_suggestion_messages(
        _NAME,
        _DESCRIPTION,
        _ANSWERS,
        prompt_version=_PROMPT_VERSION,
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert _NAME in user_content
    assert _DESCRIPTION in user_content
    for answer in _ANSWERS:
        assert answer in user_content
    assert f"prompt_version: {_PROMPT_VERSION}" in user_content
    assert "SuggestedKeywords" in user_content
    assert "UNTRUSTED DATA" in messages[0]["content"]


def test_clarifying_questions_schema_accepts_and_rejects() -> None:
    ok = ClarifyingQuestions.model_validate(
        {"questions": ["What depth of detail?", "Any exclusions?"]}
    )
    assert ok.questions == ["What depth of detail?", "Any exclusions?"]
    with pytest.raises(ValidationError):
        ClarifyingQuestions.model_validate({"questions": "not a list"})
    with pytest.raises(ValidationError):
        ClarifyingQuestions.model_validate({})


def test_suggested_keywords_schema_accepts_and_rejects() -> None:
    ok = SuggestedKeywords.model_validate({"keywords": ["foo widget", "2.0 regression"]})
    assert ok.keywords == ["foo widget", "2.0 regression"]
    with pytest.raises(ValidationError):
        SuggestedKeywords.model_validate({"keywords": 123})
    with pytest.raises(ValidationError):
        SuggestedKeywords.model_validate({"not_keywords": []})


def test_r7a_prompts_avoid_domain_blocklist() -> None:
    """Encode R7a: system prompts must not hard-code domain-specific vocabulary."""
    clarify = build_clarify_messages("n", "d", prompt_version="v1")
    keywords = build_keyword_suggestion_messages("n", "d", [], prompt_version="v1")
    prompt_corpus = "\n".join(
        m["content"] for m in (*clarify, *keywords) if m["role"] == "system"
    ).lower()
    for term in _R7A_DOMAIN_BLOCKLIST:
        assert term not in prompt_corpus, f"R7a tripwire hit: {term!r} in system prompts"
