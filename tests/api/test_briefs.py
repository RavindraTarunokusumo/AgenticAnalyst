"""API tests for /briefs routes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

from conftest import make_client
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.domain.models import (
    Article,
    BatchSummary,
    Brief,
    Cadence,
    Citation,
    Source,
)

_BRIEF_ID = UUID("11111111-1111-1111-1111-111111111111")
_SUMMARY_ID = UUID("22222222-2222-2222-2222-222222222222")
_ARTICLE_ID = UUID("33333333-3333-3333-3333-333333333333")
_MISSING_ARTICLE_ID = UUID("44444444-4444-4444-4444-444444444444")
_SOURCE_ID = UUID("55555555-5555-5555-5555-555555555555")
_RUN_ID = UUID("66666666-6666-6666-6666-666666666666")
_BATCH_ID = UUID("77777777-7777-7777-7777-777777777777")
_CREATED_AT = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _list_brief() -> Brief:
    return Brief(
        topic_id=DEFAULT_TOPIC_ID,
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 13),
        content="Daily brief body",
        cited_batch_summary_ids=[_SUMMARY_ID],
        cited_article_ids=[_ARTICLE_ID],
        created_by_run_id=_RUN_ID,
        created_at=_CREATED_AT,
    )


def test_get_briefs_defaults_to_daily_and_uses_tomorrow_cutoff(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    brief = _list_brief()
    list_prior_briefs = AsyncMock(return_value=[brief])
    monkeypatch.setattr("analyst_engine.api.app.list_prior_briefs", list_prior_briefs)

    client = make_client(monkeypatch)
    response = client.get("/briefs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(_BRIEF_ID)
    assert body[0]["cadence"] == "daily"
    list_prior_briefs.assert_awaited_once()
    assert list_prior_briefs.await_args is not None
    assert list_prior_briefs.await_args.args[1] == Cadence.DAILY
    assert list_prior_briefs.await_args.kwargs["before"] == date.today() + timedelta(days=1)
    assert list_prior_briefs.await_args.kwargs["topic_id"] is None


def test_get_briefs_forwards_topic_id_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    list_prior_briefs = AsyncMock(return_value=[])
    monkeypatch.setattr("analyst_engine.api.app.list_prior_briefs", list_prior_briefs)

    client = make_client(monkeypatch)
    response = client.get("/briefs", params={"topic_id": str(DEFAULT_TOPIC_ID)})

    assert response.status_code == 200
    assert response.json() == []
    list_prior_briefs.assert_awaited_once()
    assert list_prior_briefs.await_args is not None
    assert list_prior_briefs.await_args.kwargs["topic_id"] == DEFAULT_TOPIC_ID


def test_get_briefs_passes_weekly_cadence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    list_prior_briefs = AsyncMock(return_value=[])
    monkeypatch.setattr("analyst_engine.api.app.list_prior_briefs", list_prior_briefs)

    client = make_client(monkeypatch)
    response = client.get("/briefs", params={"cadence": "weekly"})

    assert response.status_code == 200
    assert response.json() == []
    assert list_prior_briefs.await_args is not None
    assert list_prior_briefs.await_args.args[1] == Cadence.WEEKLY


def test_get_briefs_rejects_unknown_cadence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    list_prior_briefs = AsyncMock()
    monkeypatch.setattr("analyst_engine.api.app.list_prior_briefs", list_prior_briefs)

    client = make_client(monkeypatch)
    response = client.get("/briefs", params={"cadence": "not-real"})

    assert response.status_code == 422
    assert response.json() == {"detail": "unknown cadence"}
    list_prior_briefs.assert_not_awaited()


def test_get_brief_detail_returns_404_for_unknown_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "analyst_engine.api.app.get_brief_by_id",
        AsyncMock(return_value=None),
    )

    client = make_client(monkeypatch)
    response = client.get(f"/briefs/{_BRIEF_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "brief not found"}


def test_get_brief_detail_resolves_citation_joins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source = Source(
        topic_id=DEFAULT_TOPIC_ID,
        id=_SOURCE_ID,
        stable_id="ft",
        name="Financial Times",
        normalized_domain="ft.com",
    )
    article = Article(
        topic_id=DEFAULT_TOPIC_ID,
        id=_ARTICLE_ID,
        source_id=_SOURCE_ID,
        url="https://www.ft.com/content/markets-rally",
        url_fingerprint="fp-markets-rally",
        title="Markets rally on policy shift",
        published_at=_CREATED_AT,
    )
    summary = BatchSummary(
        id=_SUMMARY_ID,
        batch_id=_BATCH_ID,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Policy shift lifted risk assets.",
        source_notes=None,
        entities=["Fed"],
        topics=["macro"],
        citations=[
            Citation(
                article_id=_ARTICLE_ID,
                excerpt="Risk assets climbed after the announcement.",
            )
        ],
    )
    brief = Brief(
        topic_id=DEFAULT_TOPIC_ID,
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 13),
        content="Policy shift lifted risk assets across regions.",
        cited_batch_summary_ids=[_SUMMARY_ID],
        cited_article_ids=[_ARTICLE_ID],
        created_by_run_id=_RUN_ID,
        created_at=_CREATED_AT,
    )
    monkeypatch.setattr("analyst_engine.api.app.get_brief_by_id", AsyncMock(return_value=brief))
    monkeypatch.setattr(
        "analyst_engine.api.app.get_batch_summaries_by_ids",
        AsyncMock(return_value=[summary]),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.get_articles_by_ids",
        AsyncMock(return_value=[article]),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.get_sources_by_ids",
        AsyncMock(return_value=[source]),
    )

    client = make_client(monkeypatch)
    response = client.get(f"/briefs/{_BRIEF_ID}")

    assert response.status_code == 200
    citation = response.json()["cited_summaries"][0]["citations"][0]
    assert citation["article_title"] == "Markets rally on policy shift"
    assert citation["article_url"] == "https://www.ft.com/content/markets-rally"
    assert citation["source_name"] == "Financial Times"
    assert citation["excerpt"] == "Risk assets climbed after the announcement."


def test_get_brief_detail_degrades_missing_article_citations(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    summary = BatchSummary(
        id=_SUMMARY_ID,
        batch_id=_BATCH_ID,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Orphan citation summary.",
        citations=[Citation(article_id=_MISSING_ARTICLE_ID, excerpt="Missing source excerpt.")],
    )
    brief = Brief(
        topic_id=DEFAULT_TOPIC_ID,
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 13),
        content="Brief with orphan citation.",
        cited_batch_summary_ids=[_SUMMARY_ID],
        cited_article_ids=[_MISSING_ARTICLE_ID],
        created_by_run_id=_RUN_ID,
        created_at=_CREATED_AT,
    )
    monkeypatch.setattr("analyst_engine.api.app.get_brief_by_id", AsyncMock(return_value=brief))
    monkeypatch.setattr(
        "analyst_engine.api.app.get_batch_summaries_by_ids",
        AsyncMock(return_value=[summary]),
    )
    monkeypatch.setattr("analyst_engine.api.app.get_articles_by_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr("analyst_engine.api.app.get_sources_by_ids", AsyncMock(return_value=[]))

    client = make_client(monkeypatch)
    response = client.get(f"/briefs/{_BRIEF_ID}")

    assert response.status_code == 200
    citation = response.json()["cited_summaries"][0]["citations"][0]
    assert citation["article_id"] == str(_MISSING_ARTICLE_ID)
    assert citation["article_title"] == ""
    assert citation["article_url"] == ""
    assert citation["source_name"] == ""
