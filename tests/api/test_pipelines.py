"""API tests for /pipelines routes."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from conftest import make_client
from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.domain.models import Cadence, WorkflowStatus
from analyst_engine.pipeline.daily_brief import DailyPipelineResult
from analyst_engine.pipeline.periodic_brief import PeriodicPipelineResult

_TARGET_DATE = date(2026, 7, 13)
_WORKFLOW_RUN_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
_BRIEF_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _pipeline_result(*, is_no_content: bool) -> DailyPipelineResult:
    return DailyPipelineResult(
        target_date=_TARGET_DATE,
        feeds_polled=2,
        articles_succeeded=5,
        articles_duplicate=1,
        articles_failed=0,
        batches_created=1,
        batches_reused=0,
        summaries_created=1,
        summaries_reused=0,
        summaries_selected=1,
        is_no_content=is_no_content,
        workflow_run_id=None if is_no_content else _WORKFLOW_RUN_ID,
        workflow_status=None if is_no_content else WorkflowStatus.SUCCEEDED,
        brief_id=None if is_no_content else _BRIEF_ID,
        topic_id=DEFAULT_TOPIC_ID,
    )


def test_post_pipelines_daily_requires_auth_and_maps_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pipeline = Mock(run=AsyncMock(return_value=_pipeline_result(is_no_content=False)))
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        pipeline=pipeline,
    )

    unauthenticated = client.post(
        "/pipelines/daily",
        json={"target_date": "2026-07-13", "topic_id": str(DEFAULT_TOPIC_ID)},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "API key required"}
    pipeline.run.assert_not_awaited()

    authenticated = client.post(
        "/pipelines/daily",
        headers={"X-API-Key": "test-secret"},
        json={"target_date": "2026-07-13", "topic_id": str(DEFAULT_TOPIC_ID)},
    )

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert body == {
        "topic_id": str(DEFAULT_TOPIC_ID),
        "target_date": "2026-07-13",
        "feeds_polled": 2,
        "articles_succeeded": 5,
        "articles_duplicate": 1,
        "articles_failed": 0,
        "batches_created": 1,
        "batches_reused": 0,
        "summaries_created": 1,
        "summaries_reused": 0,
        "summaries_selected": 1,
        "is_no_content": False,
        "workflow_run_id": str(_WORKFLOW_RUN_ID),
        "workflow_status": "succeeded",
        "brief_id": str(_BRIEF_ID),
    }
    pipeline.run.assert_awaited_once_with(_TARGET_DATE, topic_id=DEFAULT_TOPIC_ID)


def test_post_pipelines_daily_maps_no_content_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pipeline = Mock(run=AsyncMock(return_value=_pipeline_result(is_no_content=True)))
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        pipeline=pipeline,
    )

    response = client.post(
        "/pipelines/daily",
        json={"target_date": "2026-07-13", "topic_id": str(DEFAULT_TOPIC_ID)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_no_content"] is True
    assert body["workflow_run_id"] is None
    assert body["workflow_status"] is None
    assert body["brief_id"] is None


def _periodic_result(*, cadence: Cadence, is_no_content: bool) -> PeriodicPipelineResult:
    covered_start = date(2026, 7, 6) if cadence is Cadence.WEEKLY else date(2026, 7, 1)
    covered_end = date(2026, 7, 12) if cadence is Cadence.WEEKLY else date(2026, 7, 31)
    return PeriodicPipelineResult(
        cadence=cadence,
        covered_start=covered_start,
        covered_end=covered_end,
        summaries_selected=0 if is_no_content else 3,
        is_no_content=is_no_content,
        workflow_run_id=None if is_no_content else _WORKFLOW_RUN_ID,
        workflow_status=None if is_no_content else WorkflowStatus.SUCCEEDED,
        brief_id=None if is_no_content else _BRIEF_ID,
        topic_id=DEFAULT_TOPIC_ID,
    )


def test_post_pipelines_weekly_requires_auth_and_maps_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    weekly_pipeline = Mock(
        run=AsyncMock(return_value=_periodic_result(cadence=Cadence.WEEKLY, is_no_content=False))
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        weekly_pipeline=weekly_pipeline,
    )

    unauthenticated = client.post(
        "/pipelines/weekly",
        json={"target_date": "2026-07-08", "topic_id": str(DEFAULT_TOPIC_ID)},
    )
    assert unauthenticated.status_code == 401
    weekly_pipeline.run.assert_not_awaited()

    authenticated = client.post(
        "/pipelines/weekly",
        headers={"X-API-Key": "test-secret"},
        json={"target_date": "2026-07-08", "topic_id": str(DEFAULT_TOPIC_ID)},
    )

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert body == {
        "topic_id": str(DEFAULT_TOPIC_ID),
        "cadence": "weekly",
        "covered_start": "2026-07-06",
        "covered_end": "2026-07-12",
        "summaries_selected": 3,
        "is_no_content": False,
        "workflow_run_id": str(_WORKFLOW_RUN_ID),
        "workflow_status": "succeeded",
        "brief_id": str(_BRIEF_ID),
    }
    weekly_pipeline.run.assert_awaited_once_with(date(2026, 7, 8), topic_id=DEFAULT_TOPIC_ID)


def test_post_pipelines_weekly_maps_no_content_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    weekly_pipeline = Mock(
        run=AsyncMock(return_value=_periodic_result(cadence=Cadence.WEEKLY, is_no_content=True))
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        weekly_pipeline=weekly_pipeline,
    )

    response = client.post(
        "/pipelines/weekly", json={"target_date": "2026-07-08", "topic_id": str(DEFAULT_TOPIC_ID)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_no_content"] is True
    assert body["workflow_run_id"] is None
    assert body["workflow_status"] is None
    assert body["brief_id"] is None


def test_post_pipelines_monthly_requires_auth_and_maps_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monthly_pipeline = Mock(
        run=AsyncMock(return_value=_periodic_result(cadence=Cadence.MONTHLY, is_no_content=False))
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        monthly_pipeline=monthly_pipeline,
    )

    unauthenticated = client.post(
        "/pipelines/monthly",
        json={"target_date": "2026-07-15", "topic_id": str(DEFAULT_TOPIC_ID)},
    )
    assert unauthenticated.status_code == 401
    monthly_pipeline.run.assert_not_awaited()

    authenticated = client.post(
        "/pipelines/monthly",
        headers={"X-API-Key": "test-secret"},
        json={"target_date": "2026-07-15", "topic_id": str(DEFAULT_TOPIC_ID)},
    )

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert body == {
        "topic_id": str(DEFAULT_TOPIC_ID),
        "cadence": "monthly",
        "covered_start": "2026-07-01",
        "covered_end": "2026-07-31",
        "summaries_selected": 3,
        "is_no_content": False,
        "workflow_run_id": str(_WORKFLOW_RUN_ID),
        "workflow_status": "succeeded",
        "brief_id": str(_BRIEF_ID),
    }
    monthly_pipeline.run.assert_awaited_once_with(date(2026, 7, 15), topic_id=DEFAULT_TOPIC_ID)


def test_post_pipelines_monthly_maps_no_content_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monthly_pipeline = Mock(
        run=AsyncMock(return_value=_periodic_result(cadence=Cadence.MONTHLY, is_no_content=True))
    )
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        monthly_pipeline=monthly_pipeline,
    )

    response = client.post(
        "/pipelines/monthly", json={"target_date": "2026-07-15", "topic_id": str(DEFAULT_TOPIC_ID)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_no_content"] is True
    assert body["workflow_run_id"] is None
    assert body["workflow_status"] is None
    assert body["brief_id"] is None
