"""Shared fixtures for Replay test suite."""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def data_dir(tmp_path):
    """Provide an isolated data directory for each test."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "videos").mkdir()
    (d / "app_assets").mkdir()
    return d


@pytest_asyncio.fixture()
async def client(data_dir, monkeypatch):
    """Return an httpx AsyncClient wired to a fresh app instance."""
    import server

    # Close any cached DB connection before switching paths
    server._close_thread_db()

    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "DB_FILE", data_dir / "replay.db")
    monkeypatch.setattr(server, "VIDEOS_DIR", data_dir / "videos")
    monkeypatch.setattr(server, "APP_ASSETS_DIR", data_dir / "app_assets")
    server._init_db()

    # Clear state between tests
    server._active_tokens.clear()
    server._login_attempts.clear()

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
        server._close_thread_db()


@pytest_asyncio.fixture()
async def auth_headers(client):
    """Log in and return auth headers."""
    resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
