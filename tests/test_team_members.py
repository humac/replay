from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.asyncio


def _token_headers(user: dict) -> dict:
    import auth as _auth

    token = _auth.create_token(user["id"], user["role"], user["username"])
    return {"Authorization": f"Bearer {token}"}


def _create_user(username: str, *, role: str = "viewer", display_name: str | None = None) -> dict:
    import auth as _auth
    import db as _db

    return _db.create_user(username, _auth.hash_password("Passw0rd!"), role, display_name or username.title())


def _create_team(team_id: str, *, slug: str | None = None) -> dict:
    import db as _db
    from services import teams as _teams

    team = _teams.create_team(name=team_id.replace("-", " ").title(), slug=slug or team_id, game_format="9v9")
    with _db.connect() as conn:
        season = _teams.create_season(team_id=team["id"], name="Spring")
    team["season_id"] = season["id"]
    return team


def _grant(team_id: str, user_id: str, role: str) -> dict:
    from services import teams as _teams

    return _teams.grant_membership(team_id=team_id, user_id=user_id, role=role)


async def test_team_admin_lists_only_own_team_memberships(client):
    team_a = _create_team("members-team-a")
    team_b = _create_team("members-team-b")
    admin = _create_user("members-admin")
    coach_a = _create_user("members-coach-a")
    coach_b = _create_user("members-coach-b")
    _grant(team_a["id"], admin["id"], "team_admin")
    _grant(team_a["id"], coach_a["id"], "coach")
    _grant(team_b["id"], coach_b["id"], "coach")

    own = await client.get(f"/api/team/memberships?team_id={team_a['id']}", headers=_token_headers(admin))
    assert own.status_code == 200, own.text
    assert {row["user_id"] for row in own.json()} == {admin["id"], coach_a["id"]}

    wrong_team = await client.get(f"/api/team/memberships?team_id={team_b['id']}", headers=_token_headers(admin))
    assert wrong_team.status_code == 403


async def test_team_admin_can_grant_revoke_and_revoked_user_loses_team_access(client):
    team = _create_team("members-grant-revoke")
    admin = _create_user("members-grant-admin")
    coach = _create_user("members-grant-coach")
    _grant(team["id"], admin["id"], "team_admin")
    headers = _token_headers(admin)

    granted = await client.post(
        "/api/team/memberships",
        headers=headers,
        json={"team_id": team["id"], "user_id": coach["id"], "role": "coach"},
    )
    assert granted.status_code == 200, granted.text
    coach_headers = _token_headers(coach)
    visible = await client.get(f"/api/team/memberships?team_id={team['id']}", headers=coach_headers)
    assert visible.status_code == 403

    revoked = await client.delete(
        f"/api/team/memberships/{granted.json()['id']}?team_id={team['id']}",
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    scope = await client.put("/api/me/scope", headers=coach_headers, json={"team_id": team["id"], "season_id": team["season_id"]})
    assert scope.status_code in {403, 404}


async def test_team_admin_cannot_remove_last_team_admin(client):
    team = _create_team("members-last-admin")
    admin = _create_user("members-last-admin-user")
    membership = _grant(team["id"], admin["id"], "team_admin")

    resp = await client.delete(
        f"/api/team/memberships/{membership['id']}?team_id={team['id']}",
        headers=_token_headers(admin),
    )
    assert resp.status_code == 409


async def test_team_invite_accept_existing_user_and_reject_replay(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("invite-existing-team")
    admin = _create_user("invite-existing-admin")
    target = _create_user("invite-existing-target")
    _db.upsert_user_profile(target["id"], {"email": "Target@Example.com"})
    _grant(team["id"], admin["id"], "team_admin")

    invite = await client.post(
        "/api/team/invites",
        headers=_token_headers(admin),
        json={"team_id": team["id"], "email": " target@example.com ", "role": "coach"},
    )
    assert invite.status_code == 200, invite.text
    token = invite.json()["invite_token"]
    assert token
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _db.connect() as conn:
        row = conn.execute("SELECT token_hash FROM team_invites WHERE id = ?", (invite.json()["id"],)).fetchone()
    assert row["token_hash"] == token_hash
    assert token not in row["token_hash"]

    accepted = await client.post("/api/team/invites/accept", json={"token": token, "user_id": target["id"]})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["membership"]["user_id"] == target["id"]
    assert "password_hash" not in accepted.json()["user"]
    listed = await client.get(f"/api/team/invites?team_id={team['id']}", headers=_token_headers(admin))
    assert listed.status_code == 200, listed.text
    assert "token_hash" not in listed.json()[0]
    assert "token_hash" not in invite.json()

    replay = await client.post("/api/team/invites/accept", json={"token": token, "user_id": target["id"]})
    assert replay.status_code == 409


async def test_existing_user_invite_requires_matching_profile_email(client, monkeypatch):
    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("invite-email-match-team")
    admin = _create_user("invite-email-match-admin")
    target = _create_user("invite-email-match-target")
    _grant(team["id"], admin["id"], "team_admin")

    invite = await client.post(
        "/api/team/invites",
        headers=_token_headers(admin),
        json={"team_id": team["id"], "email": "match-required@example.com", "role": "coach"},
    )
    assert invite.status_code == 200, invite.text

    accepted = await client.post("/api/team/invites/accept", json={"token": invite.json()["invite_token"], "user_id": target["id"]})
    assert accepted.status_code == 403


async def test_expired_invite_persists_expired_status(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("invite-expired-team")
    admin = _create_user("invite-expired-admin")
    target = _create_user("invite-expired-target")
    _db.upsert_user_profile(target["id"], {"email": "expired@example.com"})
    _grant(team["id"], admin["id"], "team_admin")
    invite = await client.post(
        "/api/team/invites",
        headers=_token_headers(admin),
        json={"team_id": team["id"], "email": "expired@example.com", "role": "coach"},
    )
    assert invite.status_code == 200, invite.text
    with _db.connect() as conn:
        conn.execute("UPDATE team_invites SET expires_at = 1 WHERE id = ?", (invite.json()["id"],))
        conn.commit()

    accepted = await client.post("/api/team/invites/accept", json={"token": invite.json()["invite_token"], "user_id": target["id"]})
    assert accepted.status_code == 410
    with _db.connect() as conn:
        row = conn.execute("SELECT status FROM team_invites WHERE id = ?", (invite.json()["id"],)).fetchone()
    assert row["status"] == "expired"


async def test_team_invite_accept_new_user_links_guardian_players(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("invite-new-team")
    admin = _create_user("invite-new-admin")
    _grant(team["id"], admin["id"], "team_admin")
    player = _db.create_player("Invite Player", team_id=team["id"], season_id=team["season_id"])

    invite = await client.post(
        "/api/team/invites",
        headers=_token_headers(admin),
        json={
            "team_id": team["id"],
            "season_id": team["season_id"],
            "email": "new-guardian@example.com",
            "role": "guardian",
            "player_ids": [player["id"]],
        },
    )
    assert invite.status_code == 200, invite.text

    accepted = await client.post(
        "/api/team/invites/accept",
        json={
            "token": invite.json()["invite_token"],
            "username": "new_guardian_invited",
            "password": "Passw0rd!",
            "display_name": "New Guardian",
        },
    )
    assert accepted.status_code == 200, accepted.text
    user_id = accepted.json()["user"]["id"]
    assert accepted.json()["membership"]["role"] == "guardian"
    assert player["id"] in _db.linked_player_ids_for_user(user_id, team["id"])
