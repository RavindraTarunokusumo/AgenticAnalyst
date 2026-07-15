"""Smoke test for the /ui static file mount."""

from __future__ import annotations

from conftest import make_client


def test_ui_root_serves_index_html(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch)
    response = client.get("/ui/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_ui_mount_does_not_shadow_existing_routes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch)

    assert client.get("/healthz").status_code == 200
