from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from analyst_engine.api import readiness
from analyst_engine.api.readiness import ComponentStatus, ReadinessStatus, check_readiness


class _ConnectionContext:
    def __init__(self, connection: Mock | None = None, error: Exception | None = None) -> None:
        self.connection = connection
        self.error = error

    async def __aenter__(self) -> Mock:
        if self.error is not None:
            raise self.error
        assert self.connection is not None
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


def _engine(*, revision: str | None = "b8e4c1a09f3d", error: Exception | None = None) -> Mock:
    connection = Mock()
    result = Mock()
    result.scalar_one_or_none.return_value = revision
    connection.execute = AsyncMock(return_value=result)
    engine = Mock()
    engine.connect.return_value = _ConnectionContext(connection, error)
    return engine


@pytest.mark.asyncio
async def test_readiness_accepts_current_migration_head() -> None:
    status = await check_readiness(_engine())

    assert status.status == "ready"
    assert status.components["database"].status == "ok"
    assert status.components["migrations"].status == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, "older-revision"])
async def test_readiness_rejects_missing_or_drifted_revision(revision: str | None) -> None:
    status = await check_readiness(_engine(revision=revision))

    assert status.status == "not_ready"
    assert status.components["database"].status == "ok"
    assert status.components["migrations"].status == "failed"
    assert status.components["migrations"].current_revision == revision


@pytest.mark.asyncio
async def test_readiness_redacts_database_exception_details() -> None:
    secret = "postgresql+asyncpg://admin:super-secret@database/analyst_engine"
    status = await check_readiness(_engine(error=RuntimeError(secret)))

    rendered = status.model_dump_json()
    assert status.status == "not_ready"
    assert status.components["database"].status == "failed"
    assert status.components["migrations"].status == "unknown"
    assert secret not in rendered
    assert "super-secret" not in rendered


@pytest.mark.asyncio
async def test_migration_configuration_failure_does_not_claim_database_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness, "_expected_head", Mock(side_effect=RuntimeError("bad config")))

    status = await check_readiness(_engine())

    assert status.status == "not_ready"
    assert status.components["database"].status == "unknown"
    assert status.components["migrations"].status == "failed"


@pytest.mark.asyncio
async def test_scheduler_readiness_command_returns_status_and_disposes_engine() -> None:
    engine = _engine()
    engine.dispose = AsyncMock()
    ready = AsyncMock(
        return_value=ReadinessStatus(
            status="ready",
            components={
                "database": ComponentStatus(status="ok"),
                "migrations": ComponentStatus(status="ok"),
            },
        )
    )

    exit_code = await readiness.run_readiness_check(
        settings_factory=Mock(),
        engine_factory=Mock(return_value=engine),
        readiness_checker=ready,
    )

    assert exit_code == 0
    ready.assert_awaited_once_with(engine)
    engine.dispose.assert_awaited_once()


def test_migration_head_is_resolved_from_repository_configuration() -> None:
    assert Path("alembic.ini").is_file()
