from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from analyst_engine.api.app import create_app
from analyst_engine.api.readiness import ComponentStatus, ReadinessStatus


def _runtime() -> Mock:
    runtime = Mock()
    runtime.settings = Mock()
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
