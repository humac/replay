"""Tests for multi-user support: user CRUD, role-based access, authentication."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_user(client, auth_headers):
    """Admin can create a new user."""
    resp = await client.post("/api/users", json={
        "username": "viewer1",
        "password": "password123",
        "role": "viewer",
        "display_name": "Test Viewer",
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert data["user"]["username"] == "viewer1"
    assert data["user"]["role"] == "viewer"
    assert "password_hash" not in data["user"]


@pytest.mark.asyncio
async def test_create_user_duplicate(client, auth_headers):
    """Cannot create a user with an existing username."""
    await client.post("/api/users", json={
        "username": "dup_user",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/users", json={
        "username": "dup_user",
        "password": "password456",
        "role": "viewer",
    }, headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_users(client, auth_headers):
    """Admin can list users."""
    await client.post("/api/users", json={
        "username": "list_user",
        "password": "password123",
        "role": "uploader",
    }, headers=auth_headers)
    resp = await client.get("/api/users", headers=auth_headers)
    assert resp.status_code == 200
    users = resp.json()
    assert any(u["username"] == "list_user" for u in users)
    assert all("password_hash" not in u for u in users)


@pytest.mark.asyncio
async def test_update_user(client, auth_headers):
    """Admin can update a user's role."""
    resp = await client.post("/api/users", json={
        "username": "update_me",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    user_id = resp.json()["user"]["id"]

    resp = await client.patch(f"/api/users/{user_id}", json={
        "role": "uploader",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "uploader"


@pytest.mark.asyncio
async def test_delete_user(client, auth_headers):
    """Admin can delete a user."""
    resp = await client.post("/api/users", json={
        "username": "delete_me",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    user_id = resp.json()["user"]["id"]

    resp = await client.delete(f"/api/users/{user_id}", headers=auth_headers)
    assert resp.status_code == 200

    # Verify deleted
    resp = await client.get("/api/users", headers=auth_headers)
    assert not any(u["id"] == user_id for u in resp.json())


@pytest.mark.asyncio
async def test_login_as_db_user(client, auth_headers):
    """A DB-stored user can log in."""
    await client.post("/api/users", json={
        "username": "myuser",
        "password": "securepass123",
        "role": "uploader",
    }, headers=auth_headers)

    resp = await client.post("/api/login", json={
        "username": "myuser",
        "password": "securepass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "uploader"
    assert data["username"] == "myuser"
    assert "token" in data


@pytest.mark.asyncio
async def test_login_returns_role(client):
    """Login response includes role for env-var admin."""
    resp = await client.post("/api/login", json={
        "username": "admin",
        "password": "admin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_auth_check_returns_role(client, auth_headers):
    """Auth check returns role info."""
    resp = await client.get("/api/auth/check", headers=auth_headers)
    data = resp.json()
    assert data["authenticated"]
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_disabled_user_cannot_login(client, auth_headers):
    """A disabled user cannot log in."""
    resp = await client.post("/api/users", json={
        "username": "disabled_user",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    user_id = resp.json()["user"]["id"]

    # Disable
    await client.patch(f"/api/users/{user_id}", json={"enabled": False}, headers=auth_headers)

    # Try to login
    resp = await client.post("/api/login", json={
        "username": "disabled_user",
        "password": "password123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_viewer_cannot_create_match(client, auth_headers):
    """Viewer role cannot create matches."""
    # Create viewer user
    await client.post("/api/users", json={
        "username": "justviewing",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)

    # Login as viewer
    resp = await client.post("/api/login", json={
        "username": "justviewing",
        "password": "password123",
    })
    viewer_token = resp.json()["token"]
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    # Try to create match
    resp = await client.post("/api/matches", json={
        "home_team": "Team A",
        "away_team": "Team B",
    }, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_uploader_can_create_match(client, auth_headers):
    """Uploader role can create matches."""
    await client.post("/api/users", json={
        "username": "uploader1",
        "password": "password123",
        "role": "uploader",
    }, headers=auth_headers)

    resp = await client.post("/api/login", json={
        "username": "uploader1",
        "password": "password123",
    })
    uploader_token = resp.json()["token"]
    uploader_headers = {"Authorization": f"Bearer {uploader_token}"}

    resp = await client.post("/api/matches", json={
        "home_team": "Team A",
        "away_team": "Team B",
    }, headers=uploader_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_uploader_cannot_delete_match(client, auth_headers):
    """Uploader role cannot delete matches (admin only)."""
    # Create match as admin
    resp = await client.post("/api/matches", json={
        "home_team": "Team X",
        "away_team": "Team Y",
    }, headers=auth_headers)
    matches = await client.get("/api/matches")
    match_id = matches.json()[0]["id"]

    # Create uploader
    await client.post("/api/users", json={
        "username": "uploader_nd",
        "password": "password123",
        "role": "uploader",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "uploader_nd",
        "password": "password123",
    })
    uploader_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    # Try to delete
    resp = await client.delete(f"/api/matches/{match_id}", headers=uploader_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_manage_users(client, auth_headers):
    """Viewer cannot access user management endpoints."""
    await client.post("/api/users", json={
        "username": "nonadmin",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "nonadmin",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get("/api/users", headers=viewer_headers)
    assert resp.status_code == 403

    resp = await client.post("/api/users", json={
        "username": "hacker",
        "password": "password123",
        "role": "admin",
    }, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_env_admin_still_works(client):
    """Env-var superadmin login still works even with DB users."""
    resp = await client.post("/api/login", json={
        "username": "admin",
        "password": "admin",
    })
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
