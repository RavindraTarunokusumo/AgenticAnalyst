"""API tests for stateless topic assist routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from conftest import make_client, make_runtime, make_settings

from analyst_engine.models.gateway import ModelTask, RetryableModelError, TerminalModelError
from analyst_engine.topics.prompts import ClarifyingQuestions, SuggestedKeywords


def test_clarify_returns_questions(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(
        return_value=(
            ClarifyingQuestions(questions=["What regions matter?", "What actors?"]),
            Mock(),
        )
    )

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/clarify",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 200
    assert response.json() == {
        "questions": ["What regions matter?", "What actors?"],
    }
    runtime.gateway.generate.assert_awaited_once()
    assert runtime.gateway.generate.await_args is not None
    kwargs = runtime.gateway.generate.await_args.kwargs
    assert kwargs["task"] == ModelTask.TOPIC_ASSIST
    assert kwargs["output_schema"] is ClarifyingQuestions
    assert kwargs["messages"][0]["role"] == "system"
    assert "US-Iran" in kwargs["messages"][1]["content"]
    assert (
        f"prompt_version: {runtime.settings.topic_assist_prompt_version}"
        in kwargs["messages"][1]["content"]
    )


def test_clarify_returns_503_on_terminal_model_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(side_effect=TerminalModelError("provider down"))

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/clarify",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_clarify_returns_503_on_retryable_model_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(side_effect=RetryableModelError("timeout"))

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/clarify",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_suggest_keywords_returns_keywords(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(
        return_value=(
            SuggestedKeywords(keywords=["Iran", "Strait of Hormuz", "IRGC"]),
            Mock(),
        )
    )

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/suggest-keywords",
        json={
            "name": "US-Iran",
            "description": "Track the conflict.",
            "answers": ["Focus on naval incidents."],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "keywords": ["Iran", "Strait of Hormuz", "IRGC"],
    }
    runtime.gateway.generate.assert_awaited_once()
    assert runtime.gateway.generate.await_args is not None
    kwargs = runtime.gateway.generate.await_args.kwargs
    assert kwargs["task"] == ModelTask.TOPIC_ASSIST
    assert kwargs["output_schema"] is SuggestedKeywords
    assert "naval incidents" in kwargs["messages"][1]["content"]


def test_suggest_keywords_defaults_answers_to_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(
        return_value=(SuggestedKeywords(keywords=["Iran"]), Mock())
    )

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/suggest-keywords",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 200
    assert response.json()["keywords"] == ["Iran"]
    assert runtime.gateway.generate.await_args is not None
    kwargs = runtime.gateway.generate.await_args.kwargs
    assert "(none provided)" in kwargs["messages"][1]["content"]


def test_suggest_keywords_returns_503_on_terminal_model_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(side_effect=TerminalModelError("provider down"))

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/suggest-keywords",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_suggest_keywords_returns_503_on_retryable_model_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(side_effect=RetryableModelError("timeout"))

    client = make_client(monkeypatch, runtime=runtime)
    response = client.post(
        "/topics/suggest-keywords",
        json={"name": "US-Iran", "description": "Track the conflict."},
    )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_assist_routes_do_not_require_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.generate = AsyncMock(
        side_effect=[
            (ClarifyingQuestions(questions=["Q1?"]), Mock()),
            (SuggestedKeywords(keywords=["k1"]), Mock()),
        ]
    )
    client = make_client(monkeypatch, allow_unauthenticated_write=False, runtime=runtime)

    clarify = client.post(
        "/topics/clarify",
        json={"name": "Topic", "description": "Desc"},
    )
    suggest = client.post(
        "/topics/suggest-keywords",
        json={"name": "Topic", "description": "Desc"},
    )

    assert clarify.status_code == 200
    assert suggest.status_code == 200
