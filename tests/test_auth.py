"""Tests for auth flow: login, logout, rate limiting, token lifecycle."""

from __future__ import annotations

import time

import pytest


pytestmark = pytest.mark.asyncio


async def test_login_success(client):
    resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) == 64  # hex(32)


async def test_login_bad_credentials(client):
    resp = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_missing_fields(client):
    resp = await client.post("/api/login", json={})
    assert resp.status_code == 422

    resp = await client.post("/api/login", json={"username": "admin"})
    assert resp.status_code == 422


async def test_login_rate_limit(client):
    """6th failed attempt within the window should be rejected with 429."""
    for i in range(5):
        resp = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401, f"Attempt {i+1} should be 401"

    resp = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 429


async def test_rate_limit_does_not_block_after_window(client, monkeypatch):
    """After the rate window expires, login should work again."""
    import server

    for _ in range(5):
        await client.post("/api/login", json={"username": "admin", "password": "wrong"})

    # Fast-forward time past the rate window
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + server._LOGIN_RATE_WINDOW + 1)

    resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200


async def test_logout_invalidates_token(client, auth_headers):
    # Token should work
    resp = await client.get("/api/auth/check", headers=auth_headers)
    assert resp.json()["authenticated"] is True

    # Logout
    resp = await client.post("/api/logout", headers=auth_headers)
    assert resp.status_code == 200

    # Token should no longer work
    resp = await client.get("/api/auth/check", headers=auth_headers)
    assert resp.json()["authenticated"] is False


async def test_auth_check_unauthenticated(client):
    resp = await client.get("/api/auth/check")
    assert resp.json()["authenticated"] is False


async def test_token_expiry(client, monkeypatch):
    """Expired tokens should be rejected."""
    import server

    resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fast-forward past TTL
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + server.TOKEN_TTL + 1)

    resp = await client.get("/api/auth/check", headers=headers)
    assert resp.json()["authenticated"] is False


async def test_token_sweep(client, monkeypatch):
    """Sweep should remove expired tokens."""
    import server

    # Create several tokens
    for _ in range(5):
        await client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert len(server._active_tokens) == 5

    # Fast-forward past TTL and force sweep
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + server.TOKEN_TTL + 1)
    monkeypatch.setattr(server, "_last_token_sweep", 0.0)
    server._sweep_expired_tokens()

    assert len(server._active_tokens) == 0


async def test_token_cap(client, monkeypatch):
    """When token cap is reached, oldest token is evicted."""
    import server

    monkeypatch.setattr(server, "_MAX_ACTIVE_TOKENS", 3)
    tokens = []
    for _ in range(4):
        resp = await client.post("/api/login", json={"username": "admin", "password": "admin"})
        tokens.append(resp.json()["token"])

    assert len(server._active_tokens) <= 3
    # The first token should have been evicted
    assert tokens[0] not in server._active_tokens
