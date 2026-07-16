"""API tests for /sources routes."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from conftest import make_client
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.domain.models import Source, SourceFeed

_SOURCE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_FEED_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _persisted_source() -> Source:
    return Source(
        topic_id=DEFAULT_TOPIC_ID,
        id=_SOURCE_ID,
        stable_id="reuters",
        name="Reuters",
        normalized_domain="reuters.com",
    )


def _persisted_feed() -> SourceFeed:
    return SourceFeed(
        id=_FEED_ID,
        source_id=_SOURCE_ID,
        feed_url="https://example.com/feed.xml",
        feed_url_fingerprint="fp-example-feed",
        enabled=True,
        poll_interval_minutes=30,
    )


def test_post_sources_succeeds_without_api_key_when_unauthenticated_write_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _persisted_source()
    feed = _persisted_feed()
    upsert_source = AsyncMock(return_value=source)
    upsert_source_feed = AsyncMock(return_value=feed)
    monkeypatch.setattr("analyst_engine.api.app.upsert_source", upsert_source)
    monkeypatch.setattr("analyst_engine.api.app.upsert_source_feed", upsert_source_feed)
    monkeypatch.setattr(
        "analyst_engine.api.app.get_source_by_stable_id",
        AsyncMock(return_value=source),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.list_source_feeds_for_source",
        AsyncMock(return_value=[feed]),
    )

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.post(
        "/sources",
        json={
            "topic_id": str(DEFAULT_TOPIC_ID),
            "stable_id": "reuters",
            "name": "Reuters",
            "normalized_domain": "reuters.com",
            "feeds": [
                {
                    "feed_url": "https://example.com/feed.xml",
                    "enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stable_id"] == "reuters"
    assert body["name"] == "Reuters"
    assert body["normalized_domain"] == "reuters.com"
    assert len(body["feeds"]) == 1
    assert body["feeds"][0]["feed_url"] == "https://example.com/feed.xml"
    assert body["feeds"][0]["enabled"] is True
    upsert_source.assert_awaited_once()
    upsert_source_feed.assert_awaited_once()


def test_post_sources_returns_401_without_api_key_when_auth_required(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    upsert_source = AsyncMock()
    upsert_source_feed = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.upsert_source", upsert_source)
    monkeypatch.setattr("analyst_engine.api.app.upsert_source_feed", upsert_source_feed)

    client = make_client(monkeypatch, allow_unauthenticated_write=False)
    response = client.post(
        "/sources",
        json={
            "topic_id": str(DEFAULT_TOPIC_ID),
            "stable_id": "reuters",
            "name": "Reuters",
            "normalized_domain": "reuters.com",
            "feeds": [],
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "API key required"}
    upsert_source.assert_not_awaited()
    upsert_source_feed.assert_not_awaited()


def test_post_sources_rejects_private_feed_url_before_persistence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    upsert_source = AsyncMock()
    upsert_source_feed = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.upsert_source", upsert_source)
    monkeypatch.setattr("analyst_engine.api.app.upsert_source_feed", upsert_source_feed)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.post(
        "/sources",
        json={
            "topic_id": str(DEFAULT_TOPIC_ID),
            "stable_id": "reuters",
            "name": "Reuters",
            "normalized_domain": "reuters.com",
            "feeds": [{"feed_url": "http://127.0.0.1/feed.xml"}],
        },
    )

    assert response.status_code == 422
    assert "127.0.0.1" in response.json()["detail"]
    upsert_source.assert_not_awaited()
    upsert_source_feed.assert_not_awaited()


def test_get_sources_returns_sources_with_feeds_without_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source = _persisted_source()
    feed = _persisted_feed()
    monkeypatch.setattr(
        "analyst_engine.api.app.list_sources",
        AsyncMock(return_value=[source]),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.list_source_feeds_for_source",
        AsyncMock(return_value=[feed]),
    )

    client = make_client(monkeypatch, allow_unauthenticated_write=False)
    response = client.get("/sources")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(_SOURCE_ID)
    assert body[0]["stable_id"] == "reuters"
    assert body[0]["feeds"][0]["id"] == str(_FEED_ID)
