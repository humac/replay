"""Tests for settings endpoints."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_get_public_settings(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "settings" in data
    assert "assets" in data
    assert data["settings"]["app_name"]  # should have a default


async def test_update_settings_requires_auth(client):
    resp = await client.put("/api/admin/settings", json={"app_name": "Test"})
    assert resp.status_code == 401


async def test_update_settings(client, auth_headers):
    resp = await client.put(
        "/api/admin/settings",
        json={"app_name": "My Replay App"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["settings"]["app_name"] == "My Replay App"


async def test_updated_settings_persist(client, auth_headers):
    await client.put(
        "/api/admin/settings",
        json={"season_title": "2026 Season"},
        headers=auth_headers,
    )

    resp = await client.get("/api/settings")
    assert resp.json()["settings"]["season_title"] == "2026 Season"


async def test_email_settings_endpoints_removed(client, auth_headers):
    """Email delivery / Brevo settings were removed; the admin endpoints
    must be gone and email keys must never surface in public settings."""
    assert (
        await client.get("/api/admin/email/settings", headers=auth_headers)
    ).status_code in (404, 405)
    assert (
        await client.patch(
            "/api/admin/email/settings",
            headers=auth_headers,
            json={"email_provider": "brevo"},
        )
    ).status_code in (404, 405)

    public = await client.get("/api/settings")
    assert "email_provider" not in public.json()["settings"]
