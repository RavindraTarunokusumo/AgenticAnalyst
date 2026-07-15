from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from conftest import make_client
from fastapi.testclient import TestClient

from analyst_engine.api.app import create_app
from analyst_engine.api.readiness import ComponentStatus, ReadinessStatus
from analyst_engine.domain.models import Cadence, WorkflowStatus
from analyst_engine.pipeline.daily_brief import DailyPipelineResult
from analyst_engine.pipeline.periodic_brief import PeriodicPipelineResult


def _runtime() -> Mock:
    runtime = Mock()
    runtime.settings = Mock()
    # Explicit, not relying on Mock's default truthiness: these tests exercise
    # /workflows/trigger's dependency wiring, not auth policy, so they opt into
    # the local-dev-only lenient path deliberately rather than by accident.
    runtime.settings.allow_unauthenticated_write = True
    runtime.engine = Mock()
    runtime.session_factory = Mock()
    runtime.gateway = Mock()
    runtime.checkpointer_factory = Mock()
    runtime.close = AsyncMock()
    return runtime


def test_healthz_reports_process_health_without_checking_dependencies() -> None:
    runtime = _runtime()
    readiness_checker = AsyncMock()
    app = create_app(
        settings_factory=Mock(),
        runtime_factory=AsyncMock(return_value=runtime),
        readiness_checker=readiness_checker,
    )

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    readiness_checker.assert_not_awaited()


def test_readyz_uses_active_runtime_engine_and_reports_ready() -> None:
    runtime = _runtime()
    readiness = ReadinessStatus(
        status="ready",
        components={
            "database": ComponentStatus(status="ok"),
            "migrations": ComponentStatus(
                status="ok",
                current_revision="963e5ab691b1",
                expected_revision="963e5ab691b1",
            ),
        },
    )
    readiness_checker = AsyncMock(return_value=readiness)
    app = create_app(
        settings_factory=Mock(),
        runtime_factory=AsyncMock(return_value=runtime),
        readiness_checker=readiness_checker,
    )

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == readiness.model_dump(exclude_none=True)
    readiness_checker.assert_awaited_once_with(runtime.engine)


def test_readyz_returns_503_and_redacts_dependency_failure() -> None:
    runtime = _runtime()
    secret = "postgresql+asyncpg://admin:super-secret@database/analyst_engine"
    readiness_checker = AsyncMock(
        return_value=ReadinessStatus(
            status="not_ready",
            components={
                "database": ComponentStatus(status="failed"),
                "migrations": ComponentStatus(status="unknown"),
            },
        )
    )
    readiness_checker.side_effect = None
    app = create_app(
        settings_factory=Mock(),
        runtime_factory=AsyncMock(return_value=runtime),
        readiness_checker=readiness_checker,
    )

    with TestClient(app) as client:
        response = client.get("/readyz")

    body = response.text
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert secret not in body
    assert "super-secret" not in body


def test_trigger_daily_delegates_to_pipeline_not_runner_directly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Regression test for the daily-cadence bypass fix (spec 5.3): /workflows/
    trigger's daily branch must call the pipeline, not runner.run_daily
    directly, so it always selects real evidence rather than an empty context.
    """
    result = DailyPipelineResult(
        target_date=date(2026, 7, 12),
        feeds_polled=0,
        articles_succeeded=0,
        articles_duplicate=0,
        articles_failed=0,
        batches_created=0,
        batches_reused=0,
        summaries_created=0,
        summaries_reused=0,
        summaries_selected=1,
        is_no_content=False,
        workflow_run_id=uuid4(),
        workflow_status=WorkflowStatus.SUCCEEDED,
        brief_id=None,
    )
    pipeline = Mock(run=AsyncMock(return_value=result))
    client = make_client(monkeypatch, allow_unauthenticated_write=True, pipeline=pipeline)

    response = client.post(
        "/workflows/trigger",
        json={
            "cadence": "daily",
            "covered_start": "2026-07-12",
            "covered_end": "2026-07-12",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(result.workflow_run_id)
    assert body["status"] == "succeeded"
    assert body["idempotency_key"] == "daily:2026-07-12:2026-07-12"
    pipeline.run.assert_awaited_once_with(date(2026, 7, 12))


def test_trigger_weekly_delegates_to_weekly_pipeline_with_normalized_window(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result = PeriodicPipelineResult(
        cadence=Cadence.WEEKLY,
        covered_start=date(2026, 7, 6),
        covered_end=date(2026, 7, 12),
        summaries_selected=2,
        is_no_content=False,
        workflow_run_id=uuid4(),
        workflow_status=WorkflowStatus.SUCCEEDED,
        brief_id=None,
    )
    weekly_pipeline = Mock(run=AsyncMock(return_value=result))
    client = make_client(
        monkeypatch, allow_unauthenticated_write=True, weekly_pipeline=weekly_pipeline
    )

    response = client.post(
        "/workflows/trigger",
        json={
            "cadence": "weekly",
            "covered_start": "2026-07-08",
            "covered_end": "2026-07-08",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(result.workflow_run_id)
    # The idempotency key reflects the pipeline's own normalized window
    # (Mon-Sun), not the raw covered_start submitted in the request.
    assert body["idempotency_key"] == "weekly:2026-07-06:2026-07-12"
    weekly_pipeline.run.assert_awaited_once_with(date(2026, 7, 8))


def test_trigger_returns_409_when_pipeline_reports_no_content(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result = PeriodicPipelineResult(
        cadence=Cadence.MONTHLY,
        covered_start=date(2026, 7, 1),
        covered_end=date(2026, 7, 31),
        summaries_selected=0,
        is_no_content=True,
        workflow_run_id=None,
        workflow_status=None,
        brief_id=None,
    )
    monthly_pipeline = Mock(run=AsyncMock(return_value=result))
    client = make_client(
        monkeypatch, allow_unauthenticated_write=True, monthly_pipeline=monthly_pipeline
    )

    response = client.post(
        "/workflows/trigger",
        json={
            "cadence": "monthly",
            "covered_start": "2026-07-15",
            "covered_end": "2026-07-15",
        },
    )

    assert response.status_code == 409


def test_trigger_rejects_unknown_cadence_before_pipeline_invocation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pipeline = Mock(run=AsyncMock())
    weekly_pipeline = Mock(run=AsyncMock())
    monthly_pipeline = Mock(run=AsyncMock())
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        pipeline=pipeline,
        weekly_pipeline=weekly_pipeline,
        monthly_pipeline=monthly_pipeline,
    )

    response = client.post(
        "/workflows/trigger",
        json={
            "cadence": "quarterly",
            "covered_start": "2026-07-12",
            "covered_end": "2026-09-30",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown cadence"}
    pipeline.run.assert_not_awaited()
    weekly_pipeline.run.assert_not_awaited()
    monthly_pipeline.run.assert_not_awaited()
