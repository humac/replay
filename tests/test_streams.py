"""Tests for the streams registry, client-IP resolution, and admin endpoints."""

from __future__ import annotations

import time

import pytest
from starlette.requests import Request

import streams as _streams


def _make_request(headers: dict, peer: str | None = "127.0.0.1") -> Request:
    """Build a Starlette Request just enough for header / client.host access."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer, 12345) if peer else None,
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# client_ip
# ---------------------------------------------------------------------------

def test_client_ip_prefers_cf_connecting_ip():
    req = _make_request({
        "cf-connecting-ip": "203.0.113.7",
        "x-forwarded-for": "203.0.113.99, 10.0.0.1",
    })
    assert _streams.client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_xff_first_hop():
    req = _make_request({"x-forwarded-for": "203.0.113.42, 10.0.0.1"})
    assert _streams.client_ip(req) == "203.0.113.42"


def test_client_ip_falls_back_to_peer():
    req = _make_request({}, peer="198.51.100.5")
    assert _streams.client_ip(req) == "198.51.100.5"


def test_client_ip_unknown_when_no_peer():
    req = _make_request({}, peer=None)
    assert _streams.client_ip(req) == "unknown"


def test_client_ip_true_client_ip_header():
    req = _make_request({"true-client-ip": "203.0.113.10"})
    assert _streams.client_ip(req) == "203.0.113.10"


# ---------------------------------------------------------------------------
# StreamRegistry
# ---------------------------------------------------------------------------

@pytest.fixture
def reg():
    r = _streams.StreamRegistry()
    yield r
    r.reset()


def test_touch_reuses_session_for_same_viewer(reg):
    a = reg.touch("live", None, None, "1.1.1.1", "ua")
    b = reg.touch("live", None, None, "1.1.1.1", "ua")
    assert a.id == b.id
    assert len(reg.list_active()) == 1


def test_touch_creates_new_session_for_different_ip(reg):
    a = reg.touch("live", None, None, "1.1.1.1", "ua")
    b = reg.touch("live", None, None, "2.2.2.2", "ua")
    assert a.id != b.id
    assert len(reg.list_active()) == 2


def test_touch_creates_new_session_for_different_match(reg):
    a = reg.touch("vod-hls", "m1", "full", "1.1.1.1", "ua")
    b = reg.touch("vod-hls", "m2", "full", "1.1.1.1", "ua")
    assert a.id != b.id


def test_register_long_always_creates(reg):
    a = reg.register_long("vod-mp4", "m1", "full", "1.1.1.1", "ua")
    b = reg.register_long("vod-mp4", "m1", "full", "1.1.1.1", "ua")
    assert a.id != b.id


def test_kill_sets_cancel_and_blocks(reg):
    s = reg.touch("live", None, None, "1.1.1.1", "ua")
    assert reg.kill(s.id) is True
    assert s.cancel.is_set()
    assert reg.is_blocked("1.1.1.1", "live", None, None) is True


def test_kill_returns_false_for_unknown_session(reg):
    assert reg.kill("does-not-exist") is False


def test_block_expires(reg):
    reg.block(("1.1.1.1", "live", "", ""), ttl=0)
    # Brief sleep so the expiry stamp passes
    time.sleep(0.01)
    assert reg.is_blocked("1.1.1.1", "live", None, None) is False


def test_unblock_clears_entry(reg):
    reg.block(("1.1.1.1", "live", "", ""), ttl=300)
    assert reg.is_blocked("1.1.1.1", "live", None, None) is True
    assert reg.unblock(("1.1.1.1", "live", "", "")) is True
    assert reg.is_blocked("1.1.1.1", "live", None, None) is False


def test_sweep_drops_idle_hls_session(reg):
    s = reg.touch("vod-hls", "m1", "full", "1.1.1.1", "ua")
    s.last_activity = time.time() - 60  # well past idle threshold
    pruned = reg.sweep(idle_seconds=15)
    assert pruned == 1
    assert reg.get(s.id) is None


def test_sweep_keeps_long_running_mp4_session(reg):
    s = reg.register_long("vod-mp4", "m1", "full", "1.1.1.1", "ua")
    s.last_activity = time.time() - 600
    reg.sweep(idle_seconds=15)
    # MP4 sessions are owned by their handler — sweep must not drop them.
    assert reg.get(s.id) is not None


def test_add_bytes_increments_counter(reg):
    s = reg.touch("live", None, None, "1.1.1.1", "ua")
    reg.add_bytes(s.id, 1000)
    reg.add_bytes(s.id, 500)
    assert reg.get(s.id).bytes_sent == 1500


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_streams_requires_admin(client):
    """Unauthenticated callers get 401."""
    resp = await client.get("/api/admin/streams")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_streams_viewer_forbidden(client, auth_headers):
    """Viewer-role users get 403."""
    await client.post("/api/users", json={
        "username": "viewer_streams_test",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    login = await client.post("/api/login", json={
        "username": "viewer_streams_test", "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    resp = await client.get("/api/admin/streams", headers=viewer_headers)
    assert resp.status_code == 403
    kill = await client.post("/api/admin/streams/abc/kill", headers=viewer_headers)
    assert kill.status_code == 403


@pytest.mark.asyncio
async def test_admin_streams_empty(client, auth_headers):
    _streams.registry.reset()
    resp = await client.get("/api/admin/streams", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] == []
    assert data["blocks"] == []


@pytest.mark.asyncio
async def test_admin_kill_unknown_session(client, auth_headers):
    _streams.registry.reset()
    resp = await client.post("/api/admin/streams/does-not-exist/kill", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_kill_session_then_unblock(client, auth_headers):
    _streams.registry.reset()
    s = _streams.registry.touch("live", None, None, "1.1.1.1", "ua")
    resp = await client.post(f"/api/admin/streams/{s.id}/kill", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["killed"] is True
    # The block should now show up
    listing = await client.get("/api/admin/streams", headers=auth_headers)
    blocks = listing.json()["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["ip"] == "1.1.1.1"
    assert blocks[0]["kind"] == "live"

    # Clear it
    unblock = await client.request(
        "DELETE",
        "/api/admin/streams/blocks",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"ip": "1.1.1.1", "kind": "live", "match_id": None, "slot": None},
    )
    assert unblock.status_code == 200
    assert unblock.json()["cleared"] is True
