"""Tests for the live streaming endpoints (MediaMTX bridge)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# /api/live/auth — webhook MediaMTX uses to validate incoming publishes
# ---------------------------------------------------------------------------

async def test_live_auth_accepts_correct_path(client):
    """A publish to live/<configured-key> over RTMP should be accepted."""
    import settings as _settings

    # Force a known stream key.
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})

    resp = await client.post(
        "/api/live/auth",
        json={
            "user": "",
            "password": "",
            "ip": "10.0.0.5",
            "action": "publish",
            "path": "live/test-secret-123",
            "protocol": "rtmp",
            "id": "session-1",
            "query": "",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_live_auth_rejects_wrong_key(client):
    import settings as _settings
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})

    resp = await client.post(
        "/api/live/auth",
        json={
            "action": "publish",
            "path": "live/wrong-key",
            "protocol": "rtmp",
        },
    )
    assert resp.status_code == 401


async def test_live_auth_rejects_non_publish_action(client):
    """Reads/api/etc. are excluded in mediamtx.yml but the server still denies."""
    import settings as _settings
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})

    resp = await client.post(
        "/api/live/auth",
        json={
            "action": "read",
            "path": "live/test-secret-123",
            "protocol": "hls",
        },
    )
    assert resp.status_code == 401


async def test_live_auth_rejects_wrong_protocol(client):
    import settings as _settings
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})

    resp = await client.post(
        "/api/live/auth",
        json={
            "action": "publish",
            "path": "live/test-secret-123",
            "protocol": "webrtc",  # not rtmp/rtmps
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/live/status — public liveness probe
# ---------------------------------------------------------------------------

async def test_live_status_returns_offline_when_mediamtx_unreachable(client):
    """No real MediaMTX on the test network — status should report offline."""
    resp = await client.get("/api/live/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["active"] is False
    assert data["ready"] is False


async def test_live_status_disabled_when_setting_off(client):
    import settings as _settings
    _settings.save_unlocked({"live_enabled": "0"})

    resp = await client.get("/api/live/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["active"] is False


# ---------------------------------------------------------------------------
# /api/live/hls/* — proxy
# ---------------------------------------------------------------------------

async def test_live_hls_proxy_502_when_mediamtx_unreachable(client):
    """Proxying to a non-existent MediaMTX should surface 502, not 500."""
    resp = await client.get("/api/live/hls/index.m3u8")
    assert resp.status_code == 502


async def test_live_hls_proxy_disabled_returns_404(client):
    import settings as _settings
    _settings.save_unlocked({"live_enabled": "0"})

    resp = await client.get("/api/live/hls/index.m3u8")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/admin/live/* — admin-only management
# ---------------------------------------------------------------------------

async def test_admin_live_config_requires_auth(client):
    resp = await client.get("/api/admin/live/config")
    assert resp.status_code == 401


async def test_admin_live_config_returns_stream_key(client, auth_headers):
    resp = await client.get("/api/admin/live/config", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "stream_key" in data
    assert len(data["stream_key"]) >= 16  # generated entropy
    assert data["stream_path"] == f"live/{data['stream_key']}"
    assert data["enabled"] is True


async def test_admin_live_rotate_changes_key(client, auth_headers):
    first = (await client.get("/api/admin/live/config", headers=auth_headers)).json()
    rotated = await client.post("/api/admin/live/rotate-key", headers=auth_headers)
    assert rotated.status_code == 200
    new_key = rotated.json()["stream_key"]
    assert new_key != first["stream_key"]

    # Subsequent reads should match the new key
    after = (await client.get("/api/admin/live/config", headers=auth_headers)).json()
    assert after["stream_key"] == new_key


async def test_admin_live_rotate_requires_admin(client):
    resp = await client.post("/api/admin/live/rotate-key")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Stream key never appears in the public settings payload
# ---------------------------------------------------------------------------

async def test_public_settings_never_exposes_stream_key(client, auth_headers):
    # Force the key to exist
    await client.get("/api/admin/live/config", headers=auth_headers)

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert "live_stream_key" not in settings


# ---------------------------------------------------------------------------
# /api/admin/live/diagnostics
# ---------------------------------------------------------------------------

async def test_admin_live_diagnostics_requires_auth(client):
    resp = await client.get("/api/admin/live/diagnostics")
    assert resp.status_code == 401


async def test_admin_live_diagnostics_shape(client, auth_headers):
    """When MediaMTX is unreachable (test env), shape should still be sensible."""
    import live as _live
    _live.clear_rejections()

    resp = await client.get("/api/admin/live/diagnostics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["reachable"] is False
    assert "stream_path" in data and data["stream_path"].startswith("live/")
    assert data["publisher"] is None
    assert data["paths"] == []
    assert data["rtmp_connections"] == []
    assert data["recent_rejections"] == []


async def test_admin_live_diagnostics_captures_rejections(client, auth_headers):
    """Rejected /api/live/auth attempts should show up in the diagnostics buffer."""
    import live as _live
    import settings as _settings
    _live.clear_rejections()
    _settings.save_unlocked({"live_stream_key": "valid-key-xyz"})

    # Send a publish with the wrong key.
    bad = await client.post(
        "/api/live/auth",
        json={
            "action": "publish",
            "path": "live/totally-wrong",
            "protocol": "rtmp",
            "ip": "203.0.113.99",
            "id": "x",
        },
    )
    assert bad.status_code == 401

    # Diagnostics should show that rejection.
    resp = await client.get("/api/admin/live/diagnostics", headers=auth_headers)
    rejections = resp.json()["recent_rejections"]
    assert len(rejections) >= 1
    last = rejections[0]
    assert last["ip"] == "203.0.113.99"
    assert last["path"] == "live/totally-wrong"
    assert last["action"] == "publish"
    assert "stream key did not match" in last["reason"]
