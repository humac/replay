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


async def test_live_status_marks_stale_publisher_offline(client, monkeypatch):
    """If MediaMTX says ready=true but the HLS playlist's last segment is
    older than STALE_SEGMENT_AGE_SECONDS (camera stopped sending video but
    kept the RTMP socket open), status reports offline."""
    import live as _live

    async def fake_list_paths():
        return True, [{
            "name": _live.stream_path("test-secret-123"),
            "ready": True,
            "source": {"type": "rtmpConn", "id": "x"},
            "tracks": ["H264"],
            "bytesReceived": 1000,
        }]

    async def fake_age(_stream_key):
        return _live.STALE_SEGMENT_AGE_SECONDS + 30.0

    import settings as _settings
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})
    monkeypatch.setattr(_live, "_list_paths", fake_list_paths)
    monkeypatch.setattr(_live, "_last_segment_age", fake_age)

    resp = await client.get("/api/live/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is False
    assert data["ready"] is False


async def test_live_status_keeps_active_when_segments_fresh(client, monkeypatch):
    """ready=true plus a fresh HLS segment should report active even on a
    slow uplink where individual gaps approach but stay under the threshold."""
    import live as _live

    async def fake_list_paths():
        return True, [{
            "name": _live.stream_path("test-secret-123"),
            "ready": True,
            "source": {"type": "rtmpConn", "id": "x"},
            "tracks": ["H264"],
            "bytesReceived": 1000,
        }]

    async def fake_age(_stream_key):
        # 60s old — slow uplink but inside the 90s threshold.
        return 60.0

    import settings as _settings
    _settings.save_unlocked({"live_stream_key": "test-secret-123"})
    monkeypatch.setattr(_live, "_list_paths", fake_list_paths)
    monkeypatch.setattr(_live, "_last_segment_age", fake_age)

    resp = await client.get("/api/live/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["ready"] is True


# ---------------------------------------------------------------------------
# _last_segment_age — direct parser tests
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _patch_hls_fetch(monkeypatch, *, text: str | None = None,
                     status_code: int = 200, raise_exc=None):
    """Replace httpx.AsyncClient.get with a stub that returns / raises
    whatever the test wants. The helper reaches into the live module's
    httpx import so existing httpx.AsyncClient instances elsewhere are
    unaffected."""
    import live as _live

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_exc):
            return False
        async def get(self, _url):
            if raise_exc is not None:
                raise raise_exc
            return _FakeResp(status_code, text or "")

    monkeypatch.setattr(_live.httpx, "AsyncClient", _StubClient)


async def test_last_segment_age_parses_recent_pdt(monkeypatch):
    """A PDT 30s in the past should produce an age of roughly 30 seconds."""
    import live as _live
    from datetime import datetime, timezone, timedelta

    pdt = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    playlist = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        f"#EXT-X-PROGRAM-DATE-TIME:{pdt}\n"
        "#EXTINF:3.96,\n"
        "seg.ts\n"
    )
    _patch_hls_fetch(monkeypatch, text=playlist)

    age = await _live._last_segment_age("any-key")
    assert age is not None
    assert 28 <= age <= 35  # generous slack for test scheduling


async def test_last_segment_age_uses_last_pdt_in_playlist(monkeypatch):
    """Multiple PDT entries — only the last one matters (it's the live edge)."""
    import live as _live
    from datetime import datetime, timezone, timedelta

    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    playlist = (
        f"#EXT-X-PROGRAM-DATE-TIME:{old}\n"
        "seg1.ts\n"
        f"#EXT-X-PROGRAM-DATE-TIME:{recent}\n"
        "seg2.ts\n"
    )
    _patch_hls_fetch(monkeypatch, text=playlist)

    age = await _live._last_segment_age("any-key")
    assert age is not None
    assert age < 30  # i.e. it picked the recent one, not the 600s-old one


async def test_last_segment_age_returns_none_when_no_pdt(monkeypatch):
    """A playlist without any PDT lines (e.g. before first segment cut)."""
    import live as _live

    _patch_hls_fetch(monkeypatch, text="#EXTM3U\n#EXT-X-VERSION:3\n")
    assert await _live._last_segment_age("any-key") is None


async def test_last_segment_age_returns_none_on_malformed_pdt(monkeypatch):
    """Garbage in the PDT value → None, not an exception."""
    import live as _live

    _patch_hls_fetch(
        monkeypatch,
        text="#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:not-a-real-date\nseg.ts\n",
    )
    assert await _live._last_segment_age("any-key") is None


async def test_last_segment_age_returns_none_on_http_error(monkeypatch):
    """MediaMTX unreachable → None, swallowed cleanly."""
    import httpx
    import live as _live

    _patch_hls_fetch(monkeypatch, raise_exc=httpx.ConnectError("nope"))
    assert await _live._last_segment_age("any-key") is None


async def test_last_segment_age_returns_none_on_non_200(monkeypatch):
    """404 / 502 from MediaMTX → None."""
    import live as _live

    _patch_hls_fetch(monkeypatch, status_code=404, text="not found")
    assert await _live._last_segment_age("any-key") is None


async def test_last_segment_age_handles_crlf_line_endings(monkeypatch):
    """Some MediaMTX builds emit \\r\\n. The PDT regex must not eat the CR."""
    import live as _live
    from datetime import datetime, timezone, timedelta

    pdt = (datetime.now(timezone.utc) - timedelta(seconds=15)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    playlist = f"#EXTM3U\r\n#EXT-X-PROGRAM-DATE-TIME:{pdt}\r\nseg.ts\r\n"
    _patch_hls_fetch(monkeypatch, text=playlist)

    age = await _live._last_segment_age("any-key")
    assert age is not None
    assert 13 <= age <= 20


async def test_last_segment_age_returns_none_for_empty_stream_key(monkeypatch):
    """No stream key configured → None without making any HTTP call."""
    import live as _live

    called = {"hit": False}

    class _ShouldNotCall:
        def __init__(self, *_a, **_k): pass
        async def __aenter__(self): called["hit"] = True; return self
        async def __aexit__(self, *_): return False
        async def get(self, _url): called["hit"] = True; return _FakeResp(200)

    monkeypatch.setattr(_live.httpx, "AsyncClient", _ShouldNotCall)
    assert await _live._last_segment_age("") is None
    assert called["hit"] is False


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


def _patch_hls_proxy_response(monkeypatch, status_code=200, body=b"#EXTM3U\n",
                              headers=None):
    """Stub httpx.AsyncClient for proxy_hls — it uses build_request + send
    with stream=True, so we need a different shape than _patch_hls_fetch."""
    import live as _live

    class _StubResp:
        def __init__(self):
            self.status_code = status_code
            self.headers = headers or {"Content-Type": "application/vnd.apple.mpegurl"}
        async def aiter_bytes(self):
            yield body
        async def aclose(self):
            pass

    class _StubClient:
        def __init__(self, *_a, **_k):
            pass
        def build_request(self, _method, _url, headers=None):
            return object()
        async def send(self, _req, stream=False):
            return _StubResp()
        async def aclose(self):
            pass

    monkeypatch.setattr(_live.httpx, "AsyncClient", _StubClient)


async def test_live_hls_proxy_caches_segments_aggressively(monkeypatch):
    """.ts segments are content-addressed and immutable — long max-age."""
    import live as _live

    _patch_hls_proxy_response(monkeypatch, body=b"\x00\x00\x00\x01")
    _, headers, body = await _live.proxy_hls("seg42.ts", "any-key")
    async for _ in body:
        pass
    assert headers["Cache-Control"] == "public, max-age=60, immutable"


async def test_live_hls_proxy_caches_playlists_briefly(monkeypatch):
    """Playlists change every segment — short cache so CDNs dedupe but
    don't fall behind the live edge."""
    import live as _live

    _patch_hls_proxy_response(monkeypatch, body=b"#EXTM3U\n")
    _, headers, body = await _live.proxy_hls("main_stream.m3u8", "any-key")
    async for _ in body:
        pass
    assert headers["Cache-Control"] == "public, max-age=1, must-revalidate"


async def test_live_hls_proxy_does_not_cache_errors(monkeypatch):
    """Never cache 4xx/5xx — even for normally-cacheable extensions."""
    import live as _live

    _patch_hls_proxy_response(monkeypatch, status_code=404, body=b"not found")
    status, headers, body = await _live.proxy_hls("seg42.ts", "any-key")
    async for _ in body:
        pass
    assert status == 404
    assert headers["Cache-Control"] == "no-store"


async def test_live_hls_proxy_overrides_mediamtx_cache_control(monkeypatch):
    """MediaMTX sends Cache-Control: no-store; we replace it, not append."""
    import live as _live

    _patch_hls_proxy_response(
        monkeypatch,
        body=b"\x00",
        headers={
            "Content-Type": "video/mp2t",
            "Cache-Control": "no-store",
        },
    )
    _, headers, body = await _live.proxy_hls("seg42.ts", "any-key")
    async for _ in body:
        pass
    # Single Cache-Control header with our value, not MediaMTX's no-store.
    assert headers["Cache-Control"] == "public, max-age=60, immutable"


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
# /live deep-link — must serve the SPA shell, not 404
# ---------------------------------------------------------------------------

async def test_live_deep_link_serves_spa(client):
    resp = await client.get("/live")
    assert resp.status_code == 200
    body = resp.text
    assert "<html" in body.lower()
    # Sanity-check it's the actual SPA, not some other 200.
    assert "/static/script.js" in body


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
