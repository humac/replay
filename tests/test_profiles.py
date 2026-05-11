"""Phase 9.1 user profile schema and /api/me profile tests."""

from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.asyncio


async def _login(client, username: str, password: str = "password123") -> dict[str, str]:
    resp = await client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _create_user(username: str, *, display_name: str = "") -> dict:
    import auth as _auth
    import db as _db

    return _db.create_user(username, _auth.hash_password("password123"), "viewer", display_name)


async def test_user_profiles_schema_preserves_legacy_username_accounts(client):
    import db as _db

    user = _create_user("legacy-profile-user", display_name="Legacy User")
    with _db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(user_profiles)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(user_profiles)")}
        assert {
            "user_id",
            "email",
            "normalized_email",
            "email_verified_at",
            "first_name",
            "last_name",
            "phone",
            "timezone",
            "locale",
            "preferred_contact_method",
            "updated_at",
        }.issubset(columns)
        assert "idx_user_profiles_normalized_email" in indexes
        profile = _db.get_user_profile(user["id"])

    assert profile["user_id"] == user["id"]
    assert profile["email"] is None
    assert profile["normalized_email"] is None


async def test_me_returns_full_profile_without_sensitive_fields(client):
    import db as _db

    user = _create_user("profile-me-user", display_name="Profile User")
    _db.upsert_user_profile(
        user["id"],
        {
            "email": "  Person@Example.COM ",
            "first_name": "Pat",
            "last_name": "Profile",
            "phone": "+15555550123",
            "timezone": "America/New_York",
            "locale": "en-US",
            "preferred_contact_method": "email",
        },
    )
    headers = await _login(client, user["username"])

    resp = await client.get("/api/me", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["profile"] == {
        "email": "Person@Example.COM",
        "email_verified_at": None,
        "first_name": "Pat",
        "last_name": "Profile",
        "phone": "+15555550123",
        "timezone": "America/New_York",
        "locale": "en-US",
        "preferred_contact_method": "email",
    }
    assert "password_hash" not in str(data)
    assert "normalized_email" not in data["profile"]


async def test_patch_me_profile_normalizes_email_and_rejects_duplicate(client):
    import db as _db

    first = _create_user("profile-unique-a")
    second = _create_user("profile-unique-b")
    headers_a = await _login(client, first["username"])
    headers_b = await _login(client, second["username"])

    resp = await client.patch(
        "/api/me/profile",
        headers=headers_a,
        json={"email": " Shared@Example.COM ", "first_name": "Shared"},
    )
    assert resp.status_code == 200
    assert resp.json()["profile"]["email"] == "Shared@Example.COM"
    with _db.connect() as conn:
        stored = conn.execute("SELECT normalized_email FROM user_profiles WHERE user_id = ?", (first["id"],)).fetchone()
    assert stored["normalized_email"] == "shared@example.com"

    resp = await client.patch("/api/me/profile", headers=headers_b, json={"email": "shared@example.com"})
    assert resp.status_code == 409


async def test_patch_me_profile_allows_clearing_nullable_email(client):
    import db as _db

    user = _create_user("profile-null-email")
    _db.upsert_user_profile(user["id"], {"email": "clear-me@example.com"})
    headers = await _login(client, user["username"])

    resp = await client.patch("/api/me/profile", headers=headers, json={"email": ""})

    assert resp.status_code == 200
    assert resp.json()["profile"]["email"] is None
    with _db.connect() as conn:
        stored = conn.execute("SELECT email, normalized_email FROM user_profiles WHERE user_id = ?", (user["id"],)).fetchone()
    assert stored["email"] is None
    assert stored["normalized_email"] is None


async def test_delete_user_removes_profile_pii(client):
    import db as _db

    user = _create_user("profile-delete-pii")
    _db.upsert_user_profile(user["id"], {"email": "delete-me@example.com", "phone": "+15555550111"})

    assert _db.delete_user(user["id"]) is True

    with _db.connect() as conn:
        profile_rows = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user["id"],)).fetchall()
    assert profile_rows == []


async def test_patch_me_profile_cannot_edit_role_or_memberships(client):
    import db as _db

    user = _create_user("profile-no-escalate")
    headers = await _login(client, user["username"])

    with _db.connect() as conn:
        before_roles = [dict(row) for row in conn.execute("SELECT team_id, role FROM team_user_memberships WHERE user_id = ?", (user["id"],)).fetchall()]

    resp = await client.patch(
        "/api/me/profile",
        headers=headers,
        json={"first_name": "Nope", "role": "admin", "memberships": [{"team_id": "x", "role": "team_admin"}]},
    )

    assert resp.status_code == 422
    assert _db.get_user_by_id(user["id"])["role"] == "viewer"
    with _db.connect() as conn:
        after_roles = [dict(row) for row in conn.execute("SELECT team_id, role FROM team_user_memberships WHERE user_id = ?", (user["id"],)).fetchall()]
    assert after_roles == before_roles
