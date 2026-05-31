"""Phase 9.2 durable session and password-reset tests."""

from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.asyncio


async def _login(client, username: str, password: str = "password123") -> tuple[str, dict[str, str]]:
    resp = await client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return token, {"Authorization": f"Bearer {token}"}


def _create_user(username: str, *, password: str = "password123", enabled: bool = True) -> dict:
    import auth as _auth
    import db as _db

    user = _db.create_user(username, _auth.hash_password(password), "viewer", username.title())
    if not enabled:
        _db.update_user(user["id"], enabled=False)
    return user


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def test_legacy_in_memory_helper_token_without_db_user_still_authorizes(client):
    import auth as _auth
    import db as _db

    token = _auth.create_token("synthetic-user-id", "coach", "synthetic-user")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/users", headers=headers)
    assert resp.status_code == 403
    with _db.connect() as conn:
        rows = conn.execute("SELECT * FROM user_sessions WHERE token_hash = ?", (_sha256(token),)).fetchall()
    assert rows == []


async def test_login_persists_hashed_session_token_only(client):
    import db as _db

    user = _create_user("durable-session-user")
    token, headers = await _login(client, user["username"])

    with _db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user["id"],)).fetchall()]
    assert len(rows) == 1
    assert rows[0]["token_hash"] == _sha256(token)
    assert token not in str(rows[0])

    resp = await client.get("/api/auth/check", headers=headers)
    assert resp.json()["authenticated"] is True


async def test_logout_revokes_durable_session(client):
    import db as _db

    user = _create_user("logout-session-user")
    token, headers = await _login(client, user["username"])

    resp = await client.post("/api/logout", headers=headers)
    assert resp.status_code == 200

    with _db.connect() as conn:
        row = conn.execute("SELECT revoked_at FROM user_sessions WHERE token_hash = ?", (_sha256(token),)).fetchone()
    assert row["revoked_at"] is not None
    assert (await client.get("/api/auth/check", headers=headers)).json()["authenticated"] is False


async def test_disabled_real_user_non_persisted_session_cannot_continue(client):
    import auth as _auth
    import db as _db

    user = _create_user("disabled-nonpersisted-user")
    token = _auth.create_token(user["id"], user["role"], user["username"])
    _db.update_user(user["id"], enabled=False)

    resp = await client.get("/api/auth/check", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["authenticated"] is False


async def test_disabled_user_session_cannot_continue(client):
    import db as _db

    user = _create_user("disabled-session-user")
    _token, headers = await _login(client, user["username"])
    _db.update_user(user["id"], enabled=False)

    resp = await client.get("/api/auth/check", headers=headers)
    assert resp.json()["authenticated"] is False


async def test_account_self_service_routes_removed(client):
    """Account self-service (password change, email verification, password
    reset) was removed. Confirm the routes are gone — durable sessions and
    admin-managed accounts remain."""
    user = _create_user("removed-surface-user")
    _token, headers = await _login(client, user["username"])

    assert (
        await client.post(
            "/api/me/password",
            headers=headers,
            json={"current_password": "password123", "new_password": "NewPassword!234"},
        )
    ).status_code in (404, 405)
    assert (
        await client.post("/api/me/email-verification/request", headers=headers)
    ).status_code in (404, 405)
    assert (
        await client.post("/api/auth/password-reset/request", json={"username": user["username"]})
    ).status_code in (404, 405)
