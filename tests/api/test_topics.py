"""API tests for /topics CRUD routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from conftest import make_client
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.domain.models import Source, SourceFeed, Topic
from analyst_engine.persistence.repositories import TopicInUseError, TopicNotFoundError

_TOPIC_ID = DEFAULT_TOPIC_ID
_SOURCE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_FEED_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_CREATED_AT = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
_UPDATED_AT = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


def _topic(**overrides: object) -> Topic:
    data: dict[str, object] = {
        "id": _TOPIC_ID,
        "name": "US-Iran conflict",
        "description": "Track military and diplomatic developments.",
        "interest_detail": None,
        "keywords": ["Iran", "Strait of Hormuz"],
        "created_at": _CREATED_AT,
        "updated_at": _UPDATED_AT,
    }
    data.update(overrides)
    return Topic(**data)


def _source() -> Source:
    return Source(
        topic_id=_TOPIC_ID,
        id=_SOURCE_ID,
        stable_id="reuters",
        name="Reuters",
        normalized_domain="reuters.com",
    )


def _feed() -> SourceFeed:
    return SourceFeed(
        id=_FEED_ID,
        source_id=_SOURCE_ID,
        feed_url="https://example.com/feed.xml",
        feed_url_fingerprint="fp-example-feed",
        enabled=True,
        poll_interval_minutes=30,
    )


def test_post_topics_creates_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _topic()
    create_topic = AsyncMock(return_value=created)
    monkeypatch.setattr("analyst_engine.api.app.create_topic", create_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.post(
        "/topics",
        json={
            "name": "US-Iran conflict",
            "description": "Track military and diplomatic developments.",
            "keywords": ["Iran", "Strait of Hormuz"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(_TOPIC_ID)
    assert body["name"] == "US-Iran conflict"
    assert body["keywords"] == ["Iran", "Strait of Hormuz"]
    assert body["interest_detail"] is None
    create_topic.assert_awaited_once()
    assert create_topic.await_args is not None
    persisted = create_topic.await_args.args[1]
    assert isinstance(persisted, Topic)
    assert persisted.name == "US-Iran conflict"
    assert persisted.keywords == ["Iran", "Strait of Hormuz"]


def test_post_topics_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    create_topic = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.create_topic", create_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=False)
    response = client.post(
        "/topics",
        json={
            "name": "US-Iran conflict",
            "description": "Track developments.",
            "keywords": ["Iran"],
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "API key required"}
    create_topic.assert_not_awaited()


def test_post_topics_rejects_empty_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    create_topic = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.create_topic", create_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.post(
        "/topics",
        json={
            "name": "Empty keywords",
            "description": "Should fail domain validation.",
            "keywords": [],
        },
    )

    assert response.status_code == 422
    create_topic.assert_not_awaited()


def test_get_topics_lists_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "analyst_engine.api.app.list_topics",
        AsyncMock(return_value=[_topic()]),
    )

    client = make_client(monkeypatch)
    response = client.get("/topics")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(_TOPIC_ID)
    assert body[0]["name"] == "US-Iran conflict"


def test_get_topic_returns_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "analyst_engine.api.app.get_topic",
        AsyncMock(return_value=_topic()),
    )

    client = make_client(monkeypatch)
    response = client.get(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 200
    assert response.json()["id"] == str(_TOPIC_ID)


def test_get_topic_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "analyst_engine.api.app.get_topic",
        AsyncMock(return_value=None),
    )

    client = make_client(monkeypatch)
    response = client.get(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "topic not found"}


def test_put_topics_updates_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    updated = _topic(
        name="Updated name",
        description="Updated description",
        interest_detail="Q: scope? A: military only",
        keywords=["Iran", "Israel"],
    )
    update_topic = AsyncMock(return_value=updated)
    monkeypatch.setattr("analyst_engine.api.app.update_topic", update_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.put(
        f"/topics/{_TOPIC_ID}",
        json={
            "name": "Updated name",
            "description": "Updated description",
            "interest_detail": "Q: scope? A: military only",
            "keywords": ["Iran", "Israel"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated name"
    assert body["keywords"] == ["Iran", "Israel"]
    update_topic.assert_awaited_once()
    assert update_topic.await_args is not None
    persisted = update_topic.await_args.args[1]
    assert persisted.id == _TOPIC_ID
    assert persisted.name == "Updated name"


def test_put_topics_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    update_topic = AsyncMock(side_effect=TopicNotFoundError("missing"))
    monkeypatch.setattr("analyst_engine.api.app.update_topic", update_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.put(
        f"/topics/{_TOPIC_ID}",
        json={
            "name": "Updated name",
            "description": "Updated description",
            "interest_detail": None,
            "keywords": ["Iran"],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "topic not found"}


def test_put_topics_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    update_topic = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.update_topic", update_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=False)
    response = client.put(
        f"/topics/{_TOPIC_ID}",
        json={
            "name": "Updated name",
            "description": "Updated description",
            "interest_detail": None,
            "keywords": ["Iran"],
        },
    )

    assert response.status_code == 401
    update_topic.assert_not_awaited()


def test_delete_topics_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_topic = AsyncMock(return_value=None)
    monkeypatch.setattr("analyst_engine.api.app.delete_topic", delete_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.delete(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 204
    assert response.content == b""
    delete_topic.assert_awaited_once()


def test_delete_topics_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_topic = AsyncMock(side_effect=TopicNotFoundError("missing"))
    monkeypatch.setattr("analyst_engine.api.app.delete_topic", delete_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.delete(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "topic not found"}


def test_delete_topics_returns_409_when_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_topic = AsyncMock(side_effect=TopicInUseError("has sources"))
    monkeypatch.setattr("analyst_engine.api.app.delete_topic", delete_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=True)
    response = client.delete(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 409
    assert response.json() == {"detail": "topic in use"}


def test_delete_topics_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_topic = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.delete_topic", delete_topic)

    client = make_client(monkeypatch, allow_unauthenticated_write=False)
    response = client.delete(f"/topics/{_TOPIC_ID}")

    assert response.status_code == 401
    delete_topic.assert_not_awaited()


def test_get_topic_sources_returns_sources_with_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "analyst_engine.api.app.list_sources_for_topic",
        AsyncMock(return_value=[_source()]),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.list_source_feeds_for_source",
        AsyncMock(return_value=[_feed()]),
    )

    client = make_client(monkeypatch)
    response = client.get(f"/topics/{_TOPIC_ID}/sources")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(_SOURCE_ID)
    assert body[0]["stable_id"] == "reuters"
    assert body[0]["feeds"][0]["id"] == str(_FEED_ID)
