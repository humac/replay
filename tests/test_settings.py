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


async def test_email_settings_are_admin_managed_and_hidden_publicly(client, auth_headers):
    import settings as _settings

    resp = await client.patch(
        "/api/admin/email/settings",
        headers=auth_headers,
        json={
            "email_provider": "brevo",
            "email_public_base_url": " https://replay.example.test ",
            "email_from": " noreply@example.test ",
            "email_from_name": " Replay Ops ",
            "email_brevo_api_key": "brevo-secret",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["settings"] == {
        "email_provider": "brevo",
        "email_public_base_url": "https://replay.example.test",
        "email_from": "noreply@example.test",
        "email_from_name": "Replay Ops",
    }
    assert "brevo-secret" not in resp.text
    assert body["status"]["has_brevo_api_key"] is True
    assert body["status"]["brevo_api_key_source"] == "settings"

    public = await client.get("/api/settings")
    public_text = public.text
    assert "email_provider" not in public.json()["settings"]
    assert "brevo-secret" not in public_text

    config = _settings.email_effective_config()
    assert config["email_provider"] == "brevo"
    assert config["email_brevo_api_key"] == "brevo-secret"


async def test_email_settings_are_not_writable_through_generic_settings(client, auth_headers, monkeypatch):
    monkeypatch.delenv("REPLAY_EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAY_PUBLIC_BASE_URL", raising=False)

    resp = await client.put(
        "/api/admin/settings",
        headers=auth_headers,
        json={
            "email_provider": "brevo",
            "email_public_base_url": "https://replay.example.test",
        },
    )
    assert resp.status_code == 200, resp.text

    email = await client.get("/api/admin/email/settings", headers=auth_headers)
    assert email.status_code == 200, email.text
    assert email.json()["settings"]["email_provider"] == "disabled"
    assert email.json()["settings"]["email_public_base_url"] == ""


async def test_email_settings_can_clear_saved_brevo_key(client, auth_headers):
    saved = await client.patch(
        "/api/admin/email/settings",
        headers=auth_headers,
        json={"email_provider": "brevo", "email_brevo_api_key": "brevo-secret"},
    )
    assert saved.status_code == 200, saved.text

    cleared = await client.patch(
        "/api/admin/email/settings",
        headers=auth_headers,
        json={"clear_brevo_api_key": True},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"]["has_brevo_api_key"] is False
