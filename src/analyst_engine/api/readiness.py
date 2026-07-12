"""Database and migration readiness checks for the active API runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from analyst_engine.config import Settings
from analyst_engine.persistence.engine import get_async_engine

ROOT = Path(__file__).resolve().parents[3]


class ComponentStatus(BaseModel):
    """Sanitized health state for one runtime dependency."""

    status: Literal["ok", "failed", "unknown"]
    current_revision: str | None = None
    expected_revision: str | None = None


class ReadinessStatus(BaseModel):
    """Structured readiness response safe for unauthenticated health probes."""

    status: Literal["ready", "not_ready"]
    components: dict[str, ComponentStatus]


def _expected_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("readiness requires exactly one migration head")
    return heads[0]


async def check_readiness(engine: AsyncEngine) -> ReadinessStatus:
    """Check connectivity and migration state without leaking failure details."""
    try:
        expected_revision = _expected_head()
    except Exception:
        return ReadinessStatus(
            status="not_ready",
            components={
                "database": ComponentStatus(status="unknown"),
                "migrations": ComponentStatus(status="failed"),
            },
        )

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current_revision = result.scalar_one_or_none()
    except Exception:
        return ReadinessStatus(
            status="not_ready",
            components={
                "database": ComponentStatus(status="failed"),
                "migrations": ComponentStatus(status="unknown"),
            },
        )

    migrations_ok = current_revision == expected_revision
    return ReadinessStatus(
        status="ready" if migrations_ok else "not_ready",
        components={
            "database": ComponentStatus(status="ok"),
            "migrations": ComponentStatus(
                status="ok" if migrations_ok else "failed",
                current_revision=current_revision,
                expected_revision=expected_revision,
            ),
        },
    )


async def run_readiness_check(
    *,
    settings_factory: Callable[[], Settings] = Settings,
    engine_factory: Callable[[Settings], AsyncEngine] = get_async_engine,
    readiness_checker: Callable[[AsyncEngine], Awaitable[ReadinessStatus]] = check_readiness,
) -> int:
    """Run the shared readiness check for non-HTTP process modes."""
    engine = engine_factory(settings_factory())
    try:
        status = await readiness_checker(engine)
        return 0 if status.status == "ready" else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_readiness_check()))
