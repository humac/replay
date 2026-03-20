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
    import db as _db
    import auth as _auth
    import settings as _settings
    import server

    # Close any cached DB connection before switching paths
    _db.close_thread_connection()

    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "VIDEOS_DIR", data_dir / "videos")
    monkeypatch.setattr(server, "APP_ASSETS_DIR", data_dir / "app_assets")

    # Re-init DB module with test paths
    _db.init(data_dir, data_dir / "replay.db", data_dir / "app_assets")
    _settings.init(data_dir / "app_assets", server.STATIC_DIR)

    # Clear auth state between tests
    _auth._active_tokens.clear()
    _auth._login_attempts.clear()

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
        _db.close_thread_connection()


@pytest_asyncio.fixture()
async def auth_headers(client):
    """Log in and return auth headers."""
    resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
