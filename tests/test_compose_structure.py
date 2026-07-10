"""Structural checks for the local Docker Compose topology."""

from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, Any]:
    document = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return cast(dict[str, Any], document)


def test_compose_declares_only_the_local_harness_services() -> None:
    compose = _compose()

    assert set(compose["services"]) == {"app", "postgres", "searxng"}
    assert compose["services"]["postgres"]["image"] == "pgvector/pgvector:0.8.0-pg16"
    assert compose["services"]["searxng"]["image"] == "searxng/searxng:2026.7.6-556d08c39"
    assert set(compose["volumes"]) == {"postgres_data", "searxng_config"}


def test_compose_requires_nonempty_database_and_search_secrets() -> None:
    services = _compose()["services"]

    assert services["postgres"]["environment"]["POSTGRES_PASSWORD"] == (
        "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
    )
    assert services["searxng"]["environment"]["SEARXNG_SECRET"] == (
        "${SEARXNG_SECRET_KEY:?SEARXNG_SECRET_KEY must be set}"
    )


def test_app_waits_for_healthy_dependencies_and_exposes_a_health_check() -> None:
    app = _compose()["services"]["app"]

    assert app["depends_on"] == {
        "postgres": {"condition": "service_healthy"},
        "searxng": {"condition": "service_healthy"},
    }
    assert app["environment"]["APP_PROCESS_MODE"] == "${APP_PROCESS_MODE:-api}"
    assert app["healthcheck"]["test"] == [
        "CMD-SHELL",
        "test -f /tmp/analyst-engine-ready",
    ]


def test_stateful_services_have_health_checks_and_named_storage() -> None:
    services = _compose()["services"]

    assert services["postgres"]["healthcheck"]["test"][0] == "CMD-SHELL"
    assert services["searxng"]["healthcheck"]["test"][0] == "CMD-SHELL"
    assert "postgres_data:/var/lib/postgresql/data" in services["postgres"]["volumes"]
    assert "searxng_config:/etc/searxng" in services["searxng"]["volumes"]
    assert services["searxng"]["ports"] == ["8080:8080"]


def test_searxng_settings_are_templated_without_a_hard_coded_secret() -> None:
    settings = (ROOT / "searxng" / "settings.yml").read_text(encoding="utf-8")

    assert 'secret_key: "${SEARXNG_SECRET}"' in settings


def test_searxng_bootstrap_initializes_named_volume_only_once() -> None:
    entrypoint = (ROOT / "searxng" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "[ ! -f /etc/searxng/settings.yml ]" in entrypoint
    assert 'os.environ["SEARXNG_SECRET"]' in entrypoint
    assert ".analyst-engine-initialized" not in entrypoint


def test_searxng_secret_lifecycle_is_documented_with_a_safe_rotation_path() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs" / "commands.md").read_text(encoding="utf-8")

    for document in (architecture, commands):
        assert "SEARXNG_SECRET_KEY" in document
        assert "analyst-engine_searxng_config" in document
        assert "PostgreSQL data" in document


def test_dockerignore_excludes_secrets_repository_metadata_and_local_state() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert {".env", ".env.*", ".git", ".venv", ".mypy_cache", "postgres-data"} <= set(dockerignore)


def test_app_entrypoint_has_explicit_api_and_scheduler_modes_without_jobs() -> None:
    entrypoint = (ROOT / "docker" / "app-entrypoint.sh").read_text(encoding="utf-8")

    assert "api | scheduler" in entrypoint
    assert "APScheduler" in entrypoint
    assert "register" not in entrypoint.lower()


def test_container_image_installs_playwright_chromium_for_future_ingestion() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12.13-slim-bookworm AS runtime")
    assert "uv run playwright install --with-deps chromium" in dockerfile
    assert '"crawl4ai>=0.7"' in project
    assert '"playwright>=1.52"' in project
