"""API tests for GET /archive/search."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import UUID

from conftest import make_client, make_runtime, make_settings
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.domain.models import Brief, Cadence, Embedding
from analyst_engine.models.gateway import ModelUsage, RetryableModelError, TerminalModelError

_BRIEF_ID = UUID("11111111-1111-1111-1111-111111111111")
_RUN_ID = UUID("22222222-2222-2222-2222-222222222222")
_CREATED_AT = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
_QUERY_VECTOR = [1.0] + [0.0] * 1535


def _brief() -> Brief:
    return Brief(
        topic_id=DEFAULT_TOPIC_ID,
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 13),
        content="x" * 400,
        cited_batch_summary_ids=[UUID("33333333-3333-3333-3333-333333333333")],
        cited_article_ids=[],
        created_by_run_id=_RUN_ID,
        created_at=_CREATED_AT,
    )


def _embedding(brief_id: UUID, vector: list[float]) -> Embedding:
    return Embedding(brief_id=brief_id, model="text-embedding-v4", vector=vector)


def test_search_returns_ranked_results_with_bounded_snippet(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock(return_value=(_QUERY_VECTOR, ModelUsage(model="fake")))
    brief = _brief()
    search = AsyncMock(return_value=[(_embedding(brief.id, _QUERY_VECTOR), brief)])
    monkeypatch.setattr("analyst_engine.api.app.search_embeddings_by_similarity", search)

    client = make_client(monkeypatch, runtime=runtime)
    response = client.get("/archive/search", params={"q": "central bank policy"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["brief_id"] == str(brief.id)
    assert body[0]["cadence"] == "daily"
    assert len(body[0]["content"]) == 280
    assert body[0]["similarity_score"] == 1.0
    runtime.gateway.embed.assert_awaited_once()
    assert runtime.gateway.embed.await_args is not None
    assert runtime.gateway.embed.await_args.kwargs["text"] == "central bank policy"
    search.assert_awaited_once()
    assert search.await_args is not None
    assert search.await_args.kwargs["cadence"] is None
    assert search.await_args.kwargs["limit"] == 10


def test_search_passes_cadence_and_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock(return_value=(_QUERY_VECTOR, ModelUsage(model="fake")))
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("analyst_engine.api.app.search_embeddings_by_similarity", search)

    client = make_client(monkeypatch, runtime=runtime)
    response = client.get(
        "/archive/search", params={"q": "inflation", "cadence": "weekly", "limit": 5}
    )

    assert response.status_code == 200
    assert response.json() == []
    assert search.await_args is not None
    assert search.await_args.kwargs["cadence"] == Cadence.WEEKLY
    assert search.await_args.kwargs["limit"] == 5


def test_search_rejects_blank_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock()
    client = make_client(monkeypatch, runtime=runtime)

    response = client.get("/archive/search", params={"q": "   "})

    assert response.status_code == 422
    runtime.gateway.embed.assert_not_awaited()


def test_search_rejects_limit_out_of_range(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock()
    client = make_client(monkeypatch, runtime=runtime)

    response = client.get("/archive/search", params={"q": "policy", "limit": 51})

    assert response.status_code == 422
    runtime.gateway.embed.assert_not_awaited()


def test_search_rejects_unknown_cadence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock()
    client = make_client(monkeypatch, runtime=runtime)

    response = client.get("/archive/search", params={"q": "policy", "cadence": "not-real"})

    assert response.status_code == 422
    runtime.gateway.embed.assert_not_awaited()


def test_search_returns_503_when_provider_does_not_support_embeddings(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock(side_effect=TerminalModelError("no embeddings"))
    client = make_client(monkeypatch, runtime=runtime)

    response = client.get("/archive/search", params={"q": "policy"})

    assert response.status_code == 503
    assert "embeddings not supported" in response.json()["detail"]


def test_search_returns_503_on_transient_embed_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock(side_effect=RetryableModelError("timeout"))
    client = make_client(monkeypatch, runtime=runtime)

    response = client.get("/archive/search", params={"q": "policy"})

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_search_returns_empty_list_when_no_embeddings_exist(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(make_settings())
    runtime.gateway.embed = AsyncMock(return_value=(_QUERY_VECTOR, ModelUsage(model="fake")))
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("analyst_engine.api.app.search_embeddings_by_similarity", search)

    client = make_client(monkeypatch, runtime=runtime)
    response = client.get("/archive/search", params={"q": "policy"})

    assert response.status_code == 200
    assert response.json() == []
