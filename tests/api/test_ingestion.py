"""API tests for /ingestion routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from conftest import make_client
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

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
        json={"topic_id": str(DEFAULT_TOPIC_ID), "urls": ["https://example.com/story"]},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "API key required"}
    ingestion_service.ingest_urls.assert_not_awaited()

    authenticated = client.post(
        "/ingestion/urls",
        headers={"X-API-Key": "test-secret"},
        json={
            "topic_id": str(DEFAULT_TOPIC_ID),
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
        DEFAULT_TOPIC_ID,
        ["https://example.com/story", "https://example.com/broken"],
    )


def test_post_ingestion_files_requires_auth_and_maps_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ingestion_service = Mock(
        ingest_file=AsyncMock(
            return_value=IngestionResult(
                candidate_url="upload://deadbeef",
                status=IngestionStatus.SUCCEEDED,
                article_id=_ARTICLE_ID,
                error_code=None,
                error_summary=None,
            )
        )
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        ingestion_service=ingestion_service,
    )

    unauthenticated = client.post(
        "/ingestion/files",
        data={"topic_id": str(DEFAULT_TOPIC_ID)},
        files={"file": ("report.pdf", b"pdf bytes", "application/pdf")},
    )
    assert unauthenticated.status_code == 401
    ingestion_service.ingest_file.assert_not_awaited()

    authenticated = client.post(
        "/ingestion/files",
        headers={"X-API-Key": "test-secret"},
        data={"topic_id": str(DEFAULT_TOPIC_ID)},
        files={"file": ("report.pdf", b"pdf bytes", "application/pdf")},
    )

    assert authenticated.status_code == 200
    assert authenticated.json() == {
        "candidate_url": "upload://deadbeef",
        "status": "succeeded",
        "article_id": str(_ARTICLE_ID),
        "error_code": None,
        "error_summary": None,
    }
    ingestion_service.ingest_file.assert_awaited_once_with(
        DEFAULT_TOPIC_ID, "report.pdf", b"pdf bytes", "application/pdf"
    )


def test_post_ingestion_files_maps_oversized_upload_failure_from_service(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The size check lives in IngestionService.ingest_file (so it's recorded as
    # an IngestionAttempt like every other failure mode, tested at the service
    # level) - this test only proves the route passes the result through as-is.
    ingestion_service = Mock(
        ingest_file=AsyncMock(
            return_value=IngestionResult(
                candidate_url="report.pdf",
                status=IngestionStatus.FAILED,
                article_id=None,
                error_code="file_too_large",
                error_summary="file size 25 exceeds maximum 4 bytes",
            )
        )
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        ingestion_service=ingestion_service,
    )

    response = client.post(
        "/ingestion/files",
        data={"topic_id": str(DEFAULT_TOPIC_ID)},
        files={"file": ("report.pdf", b"way more than four bytes", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "file_too_large"
    ingestion_service.ingest_file.assert_awaited_once_with(
        DEFAULT_TOPIC_ID, "report.pdf", b"way more than four bytes", "application/pdf"
    )


def test_get_ingestion_attempts_returns_recent_attempts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    started = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    attempt = IngestionAttempt(
        topic_id=DEFAULT_TOPIC_ID,
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


def test_get_ingestion_attempts_serializes_source_less_attempt(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A direct paste/upload add (spec §3.2) records an attempt with
    # source_id=None; the response model must tolerate that or the whole
    # /ingestion/attempts listing 500s once any such attempt exists.
    started = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    attempt = IngestionAttempt(
        topic_id=DEFAULT_TOPIC_ID,
        id=_ATTEMPT_ID,
        source_id=None,
        requested_url="https://example.com/pasted",
        canonical_url="https://example.com/pasted",
        status=IngestionStatus.SUCCEEDED,
        article_id=_ARTICLE_ID,
        started_at=started,
        completed_at=started,
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.list_ingestion_attempts",
        AsyncMock(return_value=[attempt]),
    )

    client = make_client(monkeypatch)
    response = client.get("/ingestion/attempts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["source_id"] is None


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
