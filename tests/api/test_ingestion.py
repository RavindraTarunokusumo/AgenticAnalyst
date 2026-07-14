"""API tests for /ingestion routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from conftest import make_client

from analyst_engine.domain.models import ExtractorKind, IngestionAttempt, IngestionStatus
from analyst_engine.ingestion.models import IngestionResult

_SOURCE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ARTICLE_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_ATTEMPT_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def test_post_ingestion_urls_requires_auth_and_maps_results(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ingestion_service = Mock(
        ingest_urls=AsyncMock(
            return_value=[
                IngestionResult(
                    candidate_url="https://example.com/story",
                    status=IngestionStatus.SUCCEEDED,
                    article_id=_ARTICLE_ID,
                    error_code=None,
                    error_summary=None,
                ),
                IngestionResult(
                    candidate_url="https://example.com/broken",
                    status=IngestionStatus.FAILED,
                    article_id=None,
                    error_code="fetch_error",
                    error_summary="timeout",
                ),
            ]
        )
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        ingestion_service=ingestion_service,
    )

    unauthenticated = client.post(
        "/ingestion/urls",
        json={"source_id": str(_SOURCE_ID), "urls": ["https://example.com/story"]},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "API key required"}
    ingestion_service.ingest_urls.assert_not_awaited()

    authenticated = client.post(
        "/ingestion/urls",
        headers={"X-API-Key": "test-secret"},
        json={
            "source_id": str(_SOURCE_ID),
            "urls": ["https://example.com/story", "https://example.com/broken"],
        },
    )

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert len(body) == 2
    assert body[0] == {
        "candidate_url": "https://example.com/story",
        "status": "succeeded",
        "article_id": str(_ARTICLE_ID),
        "error_code": None,
        "error_summary": None,
    }
    assert body[1] == {
        "candidate_url": "https://example.com/broken",
        "status": "failed",
        "article_id": None,
        "error_code": "fetch_error",
        "error_summary": "timeout",
    }
    ingestion_service.ingest_urls.assert_awaited_once_with(
        _SOURCE_ID,
        ["https://example.com/story", "https://example.com/broken"],
    )


def test_get_ingestion_attempts_returns_recent_attempts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    started = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    attempt = IngestionAttempt(
        id=_ATTEMPT_ID,
        source_id=_SOURCE_ID,
        requested_url="https://example.com/story",
        canonical_url="https://example.com/story",
        status=IngestionStatus.SUCCEEDED,
        http_status=200,
        extractor=ExtractorKind.PRIMARY_HTTP,
        article_id=_ARTICLE_ID,
        started_at=started,
        completed_at=started,
    )
    list_attempts = AsyncMock(return_value=[attempt])
    monkeypatch.setattr("analyst_engine.api.app.list_ingestion_attempts", list_attempts)

    client = make_client(monkeypatch)
    response = client.get("/ingestion/attempts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(_ATTEMPT_ID)
    assert body[0]["status"] == "succeeded"
    assert body[0]["extractor"] == "primary_http"
    list_attempts.assert_awaited_once()
    assert list_attempts.await_args is not None
    assert list_attempts.await_args.kwargs == {"status": None, "limit": 50}


def test_get_ingestion_attempts_filters_by_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    list_attempts = AsyncMock(return_value=[])
    monkeypatch.setattr("analyst_engine.api.app.list_ingestion_attempts", list_attempts)

    client = make_client(monkeypatch)
    response = client.get("/ingestion/attempts", params={"status": "succeeded"})

    assert response.status_code == 200
    assert response.json() == []
    list_attempts.assert_awaited_once()
    assert list_attempts.await_args is not None
    assert list_attempts.await_args.kwargs["status"] == IngestionStatus.SUCCEEDED


def test_get_ingestion_attempts_rejects_unknown_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    list_attempts = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.list_ingestion_attempts", list_attempts)

    client = make_client(monkeypatch)
    response = client.get("/ingestion/attempts", params={"status": "not-a-real-status"})

    assert response.status_code == 422
    assert response.json() == {"detail": "unknown status"}
    list_attempts.assert_not_awaited()
