from __future__ import annotations

import csv
import hashlib
import io

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


def _csv_text(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _table_counts() -> dict[str, int]:
    import db as _db

    tables = [
        "players",
        "player_user_links",
        "team_invites",
        "team_user_memberships",
        "users",
        "user_profiles",
        "activity_events",
    ]
    with _db.connect() as conn:
        return {table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] for table in tables}


async def test_roster_import_preview_valid_csv_returns_plan_without_db_writes(client):
    team = _create_team("roster-preview-team")
    admin = _create_user("roster-preview-admin")
    _grant(team["id"], admin["id"], "team_admin")
    payload = {
        "csv_text": _csv_text([
            {"display_name": "Avery Lopez", "jersey_number": "4", "position": "Defender", "guardian_email": "Parent@Example.com"},
            {"display_name": "Mika Chen", "jersey_number": "9", "position": "Forward", "guardian_email": " parent@example.com "},
        ])
    }

    before = _table_counts()
    resp = await client.post(
        f"/api/coach/players/import/preview?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["summary"]["create_players"] == 2
    assert body["summary"]["guardian_invites"] == 1
    assert body["summary"]["errors"] == 0
    assert all(row["status"] != "error" for row in body["rows"])
    assert _table_counts() == before


async def test_roster_import_commit_creates_players_single_guardian_invite_and_accept_links_both(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("roster-commit-team")
    admin = _create_user("roster-commit-admin")
    _grant(team["id"], admin["id"], "team_admin")
    payload = {
        "csv_text": _csv_text([
            {"display_name": "Avery Lopez", "jersey_number": "4", "position": "Defender", "guardian_email": "Parent@Example.com"},
            {"display_name": "Mika Chen", "jersey_number": "9", "position": "Forward", "guardian_email": " parent@example.com "},
        ])
    }

    resp = await client.post(
        f"/api/coach/players/import/commit?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["created_players"] == 2
    assert body["summary"]["guardian_invites"] == 1
    assert body["summary"]["linked_existing_users"] == 0
    assert "token_hash" not in body["guardian_invites"][0]
    token = body["guardian_invites"][0]["invite_token"]
    assert token
    with _db.connect() as conn:
        invites = conn.execute("SELECT * FROM team_invites WHERE team_id = ?", (team["id"],)).fetchall()
        assert len(invites) == 1
        assert invites[0]["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert token not in invites[0]["token_hash"]
        assert len(_db.list_players(team_id=team["id"])) == 2

    accepted = await client.post(
        "/api/team/invites/accept",
        json={"token": token, "username": "parent_imported", "password": "Passw0rd!", "display_name": "Imported Parent"},
    )
    assert accepted.status_code == 200, accepted.text
    linked = set(_db.linked_player_ids_for_user(accepted.json()["user"]["id"], team["id"]))
    assert linked == {row["player"]["id"] for row in body["rows"]}


async def test_roster_import_existing_guardian_email_links_same_account_to_multiple_players(client):
    import db as _db

    team = _create_team("roster-existing-guardian-team")
    admin = _create_user("roster-existing-admin")
    guardian = _create_user("roster-existing-guardian")
    _db.upsert_user_profile(guardian["id"], {"email": "Parent@Example.com"})
    _grant(team["id"], admin["id"], "team_admin")
    payload = {
        "csv_text": _csv_text([
            {"display_name": "Avery Lopez", "jersey_number": "4", "position": "Defender", "guardian_email": "parent@example.com"},
            {"display_name": "Mika Chen", "jersey_number": "9", "position": "Forward", "guardian_email": "Parent@Example.com"},
        ])
    }

    resp = await client.post(
        f"/api/coach/players/import/commit?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["guardian_invites"] == 0
    assert body["summary"]["linked_existing_users"] == 2
    assert len(body["guardian_invites"]) == 0
    linked = set(_db.linked_player_ids_for_user(guardian["id"], team["id"]))
    assert linked == {row["player"]["id"] for row in body["rows"]}
    with _db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM team_invites WHERE team_id = ?", (team["id"],)).fetchone()["n"] == 0
        membership = conn.execute(
            "SELECT role FROM team_user_memberships WHERE team_id = ? AND user_id = ?",
            (team["id"], guardian["id"]),
        ).fetchone()
    assert membership["role"] == "guardian"


async def test_roster_import_reimport_reuses_existing_players_and_pending_invite(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("roster-reimport-team")
    admin = _create_user("roster-reimport-admin")
    _grant(team["id"], admin["id"], "team_admin")
    payload = {
        "csv_text": _csv_text([
            {"display_name": "Avery Lopez", "jersey_number": "4", "position": "Defender", "guardian_email": "parent@example.com"},
        ])
    }

    first = await client.post(
        f"/api/coach/players/import/commit?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/coach/players/import/commit?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )
    assert second.status_code == 200, second.text
    assert second.json()["summary"]["created_players"] == 0
    assert second.json()["summary"]["existing_players"] == 1
    with _db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM players WHERE team_id = ?", (team["id"],)).fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM team_invites WHERE team_id = ?", (team["id"],)).fetchone()["n"] == 1


async def test_roster_import_commit_rejects_wrong_team_player_id_without_writes(client):
    import db as _db

    team_a = _create_team("roster-wrong-team-a")
    team_b = _create_team("roster-wrong-team-b")
    admin = _create_user("roster-wrong-team-admin")
    _grant(team_a["id"], admin["id"], "team_admin")
    player_b = _db.create_player("Other Team", jersey_number="2", team_id=team_b["id"], season_id=team_b["season_id"])
    payload = {
        "csv_text": _csv_text([
            {"player_id": player_b["id"], "display_name": "Other Team", "jersey_number": "2", "position": "Defender", "guardian_email": "parent@example.com"},
        ])
    }
    before = _table_counts()

    resp = await client.post(
        f"/api/coach/players/import/commit?team_id={team_a['id']}&season_id={team_a['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )

    assert resp.status_code == 409, resp.text
    assert _table_counts() == before


async def test_roster_import_family_sees_only_linked_imported_players(client, monkeypatch):
    import db as _db

    monkeypatch.setenv("REPLAY_DEV_TOKEN_DELIVERY", "1")
    team = _create_team("roster-family-team")
    admin = _create_user("roster-family-admin")
    _grant(team["id"], admin["id"], "team_admin")
    payload = {
        "csv_text": _csv_text([
            {"display_name": "Avery Lopez", "jersey_number": "4", "position": "Defender", "guardian_email": "parent-a@example.com"},
            {"display_name": "Mika Chen", "jersey_number": "9", "position": "Forward", "guardian_email": "parent-b@example.com"},
        ])
    }
    imported = await client.post(
        f"/api/coach/players/import/commit?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers(admin),
        json=payload,
    )
    assert imported.status_code == 200, imported.text
    invite_a = next(inv for inv in imported.json()["guardian_invites"] if inv["normalized_email"] == "parent-a@example.com")
    accepted = await client.post(
        "/api/team/invites/accept",
        json={"token": invite_a["invite_token"], "username": "parent_a_imported", "password": "Passw0rd!", "display_name": "Parent A"},
    )
    assert accepted.status_code == 200, accepted.text

    feedback = await client.get(
        f"/api/my-feedback?team_id={team['id']}&season_id={team['season_id']}",
        headers=_token_headers({**accepted.json()["user"], "role": "viewer"}),
    )
    assert feedback.status_code == 200, feedback.text
    assert {p["display_name"] for p in feedback.json()["players"]} == {"Avery Lopez"}
    assert "Mika Chen" not in {p["display_name"] for p in feedback.json()["players"]}
