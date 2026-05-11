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

    resp = await client.get("/api/admin/teams", headers=headers)
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


async def test_password_change_revokes_existing_sessions_and_requires_new_password(client):
    user = _create_user("password-change-user")
    _token_a, headers_a = await _login(client, user["username"], "password123")
    _token_b, headers_b = await _login(client, user["username"], "password123")

    resp = await client.post(
        "/api/me/password",
        headers=headers_a,
        json={"current_password": "password123", "new_password": "NewPassword!234"},
    )
    assert resp.status_code == 200

    assert (await client.get("/api/auth/check", headers=headers_a)).json()["authenticated"] is False
    assert (await client.get("/api/auth/check", headers=headers_b)).json()["authenticated"] is False
    assert (await client.post("/api/login", json={"username": user["username"], "password": "password123"})).status_code == 401
    assert (await client.post("/api/login", json={"username": user["username"], "password": "NewPassword!234"})).status_code == 200


async def test_email_verification_stores_token_hash_and_marks_profile(client):
    import db as _db

    user = _create_user("email-verify-user")
    _db.upsert_user_profile(user["id"], {"email": "verify-me@example.com"})
    _token, headers = await _login(client, user["username"])

    resp = await client.post("/api/me/email-verification/request", headers=headers)
    assert resp.status_code == 200
    verification_token = resp.json()["verification_token"]

    with _db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM email_verification_tokens WHERE user_id = ?", (user["id"],)).fetchall()]
    assert len(rows) == 1
    assert rows[0]["token_hash"] == _sha256(verification_token)
    assert verification_token not in str(rows[0])

    resp = await client.post("/api/me/email-verification/confirm", json={"token": verification_token})
    assert resp.status_code == 200
    assert _db.get_user_profile(user["id"])["email_verified_at"] is not None

    reused = await client.post("/api/me/email-verification/confirm", json={"token": verification_token})
    assert reused.status_code == 400


async def test_email_change_clears_verified_timestamp(client):
    import auth as _auth
    import db as _db

    user = _create_user("email-change-verify-user")
    _db.upsert_user_profile(user["id"], {"email": "old@example.com"})
    token = _auth.create_email_verification_token_for_user(user["id"])
    assert token
    assert _auth.verify_email_with_token(token)
    assert _db.get_user_profile(user["id"])["email_verified_at"] is not None
    _login_token, headers = await _login(client, user["username"])

    resp = await client.patch("/api/me/profile", headers=headers, json={"email": "new@example.com"})
    assert resp.status_code == 200
    assert resp.json()["profile"]["email_verified_at"] is None
    profile = _db.get_user_profile(user["id"])
    assert profile["email"] == "new@example.com"
    assert profile["email_verified_at"] is None


async def test_password_reset_request_is_generic_without_dev_delivery(client):
    existing = _create_user("password-reset-generic-user")

    known = await client.post("/api/auth/password-reset/request", json={"username": existing["username"]})
    unknown = await client.post("/api/auth/password-reset/request", json={"username": "missing-password-reset-user"})

    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == {"ok": True}
    assert unknown.json() == {"ok": True}


async def test_password_reset_stores_token_hash_and_rejects_reuse(client, monkeypatch):
    import db as _db

    user = _create_user("password-reset-user")
    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    resp = await client.post("/api/auth/password-reset/request", json={"username": user["username"]})
    assert resp.status_code == 200
    reset_token = resp.json()["reset_token"]
    assert reset_token

    with _db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM password_reset_tokens WHERE user_id = ?", (user["id"],)).fetchall()]
    assert len(rows) == 1
    assert rows[0]["token_hash"] == _sha256(reset_token)
    assert reset_token not in str(rows[0])

    resp = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "ResetPassword!234"},
    )
    assert resp.status_code == 200
    assert (await client.post("/api/login", json={"username": user["username"], "password": "ResetPassword!234"})).status_code == 200

    reused = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "AnotherPassword!234"},
    )
    assert reused.status_code == 400
