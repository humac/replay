from __future__ import annotations

import os
import subprocess
import sys

import pytest


def _headers_for_role(role: str, username: str = "user") -> dict:
    import auth as _auth

    token = _auth.create_token(f"{username}-id", role, username)
    return {"Authorization": f"Bearer {token}"}


async def _create_team(client, auth_headers, *, name="North Stars", slug="north-stars", game_format="9v9"):
    resp = await client.post(
        "/api/admin/teams",
        headers=auth_headers,
        json={"name": name, "slug": slug, "game_format": game_format},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["coach", "viewer", "uploader", "team_admin"])
async def test_admin_team_endpoints_require_global_admin(client, role):
    resp = await client.get("/api/admin/teams", headers=_headers_for_role(role, role))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_global_admin_can_create_list_and_patch_teams(client, auth_headers):
    created = await _create_team(client, auth_headers)
    assert created["name"] == "North Stars"
    assert created["slug"] == "north-stars"
    assert created["game_format"] == "9v9"

    listed = await client.get("/api/admin/teams", headers=auth_headers)
    assert listed.status_code == 200
    assert any(team["id"] == created["id"] for team in listed.json())

    patched = await client.patch(
        f"/api/admin/teams/{created['id']}",
        headers=auth_headers,
        json={"name": "North Stars FC", "game_format": "11v11"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "North Stars FC"
    assert patched.json()["game_format"] == "11v11"


@pytest.mark.asyncio
async def test_global_admin_can_create_and_list_seasons(client, auth_headers):
    team = await _create_team(client, auth_headers, slug="season-team")
    resp = await client.post(
        f"/api/admin/teams/{team['id']}/seasons",
        headers=auth_headers,
        json={"name": "Spring 2026", "starts_on": "2026-01-01", "ends_on": "2026-06-30"},
    )
    assert resp.status_code == 200, resp.text
    season = resp.json()
    assert season["team_id"] == team["id"]
    assert season["name"] == "Spring 2026"

    listed = await client.get(f"/api/admin/teams/{team['id']}/seasons", headers=auth_headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [season["id"]]


@pytest.mark.asyncio
async def test_cli_and_api_reject_invalid_season_dates_through_shared_service(client, auth_headers, capsys):
    from tools import admin as admin_cli

    team = await _create_team(client, auth_headers, slug="invalid-season-date-team")
    api_resp = await client.post(
        f"/api/admin/teams/{team['id']}/seasons",
        headers=auth_headers,
        json={"name": "Bad API Season", "starts_on": "01-01-2026", "ends_on": ""},
    )
    assert api_resp.status_code == 422

    assert admin_cli.main([
        "seasons", "create", "--team", team["slug"], "--name", "Bad CLI Season", "--starts", "01-01-2026",
    ]) == 1
    capsys.readouterr()
    listed = await client.get(f"/api/admin/teams/{team['id']}/seasons", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_revoking_one_of_two_team_admins_leaves_one_admin(client, auth_headers):
    import db as _db

    team = await _create_team(client, auth_headers, slug="two-admin-team")
    user_a = _db.create_user("team-admin-a-pr14", "hash", "viewer", "Team Admin A")
    user_b = _db.create_user("team-admin-b-pr14", "hash", "viewer", "Team Admin B")
    granted_a = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": user_a["id"], "role": "team_admin"},
    )
    assert granted_a.status_code == 200, granted_a.text
    granted_b = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": user_b["id"], "role": "team_admin"},
    )
    assert granted_b.status_code == 200, granted_b.text

    revoked = await client.delete(
        f"/api/admin/teams/{team['id']}/memberships/{granted_a.json()['id']}",
        headers=auth_headers,
    )
    assert revoked.status_code == 200, revoked.text
    second_revoke = await client.delete(
        f"/api/admin/teams/{team['id']}/memberships/{granted_b.json()['id']}",
        headers=auth_headers,
    )
    assert second_revoke.status_code == 409

    memberships = await client.get(f"/api/admin/teams/{team['id']}/memberships", headers=auth_headers)
    assert sum(1 for row in memberships.json() if row["role"] == "team_admin") == 1


@pytest.mark.asyncio
async def test_membership_unknown_user_returns_404_and_duplicate_returns_409(client, auth_headers):
    import db as _db

    team = await _create_team(client, auth_headers, slug="membership-team")
    missing = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": "missing-user", "role": "coach"},
    )
    assert missing.status_code == 404

    user = _db.create_user("coach-pr14", "hash", "viewer", "Coach PR14")
    granted = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": user["id"], "role": "coach"},
    )
    assert granted.status_code == 200, granted.text

    duplicate = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": user["id"], "role": "coach"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_last_team_admin_membership_cannot_be_revoked(client, auth_headers):
    import db as _db

    team = await _create_team(client, auth_headers, slug="last-admin-team")
    admin_user = _db.create_user("team-admin-pr14", "hash", "viewer", "Team Admin")
    granted = await client.post(
        f"/api/admin/teams/{team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": admin_user["id"], "role": "team_admin"},
    )
    assert granted.status_code == 200, granted.text

    revoked = await client.delete(
        f"/api/admin/teams/{team['id']}/memberships/{granted.json()['id']}",
        headers=auth_headers,
    )
    assert revoked.status_code == 409


def test_standalone_cli_initializes_configured_db(tmp_path):
    data_dir = tmp_path / "standalone-data"
    env = os.environ.copy()
    env["REPLAY_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "tools.admin", "teams", "list"],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert data_dir.joinpath("replay.db").is_file()
    assert '"slug": "default-team"' in result.stdout


@pytest.mark.asyncio
async def test_api_and_cli_share_service_state(client, auth_headers, capsys):
    import db as _db
    from tools import admin as admin_cli

    api_team = await _create_team(client, auth_headers, name="API Team", slug="api-team", game_format="7v7")
    api_user = _db.create_user("api-cli-coach", "hash", "viewer", "API CLI Coach")
    api_membership = await client.post(
        f"/api/admin/teams/{api_team['id']}/memberships",
        headers=auth_headers,
        json={"user_id": api_user["id"], "role": "coach"},
    )
    assert api_membership.status_code == 200, api_membership.text

    assert admin_cli.main(["teams", "create", "--name", "CLI Team", "--slug", "cli-team", "--game-format", "9v9"]) == 0
    assert admin_cli.main(["seasons", "create", "--team", "cli-team", "--name", "CLI Spring", "--starts", "2026-01-01", "--ends", "2026-06-30"]) == 0
    cli_user = _db.create_user("cli-coach", "hash", "viewer", "CLI Coach")
    assert admin_cli.main(["memberships", "grant", "--team", "cli-team", "--user", cli_user["username"], "--role", "coach"]) == 0
    assert admin_cli.main(["memberships", "revoke", "--team", "cli-team", "--user", cli_user["username"], "--role", "coach"]) == 0
    capsys.readouterr()

    teams = (await client.get("/api/admin/teams", headers=auth_headers)).json()
    slugs = {team["slug"] for team in teams}
    assert {"api-team", "cli-team"}.issubset(slugs)

    cli_team = next(team for team in teams if team["slug"] == "cli-team")
    seasons = (await client.get(f"/api/admin/teams/{cli_team['id']}/seasons", headers=auth_headers)).json()
    assert [season["name"] for season in seasons] == ["CLI Spring"]

    api_memberships = (await client.get(f"/api/admin/teams/{api_team['id']}/memberships", headers=auth_headers)).json()
    assert any(row["user_id"] == api_user["id"] and row["role"] == "coach" for row in api_memberships)
    cli_memberships = (await client.get(f"/api/admin/teams/{cli_team['id']}/memberships", headers=auth_headers)).json()
    assert not any(row["user_id"] == cli_user["id"] and row["role"] == "coach" for row in cli_memberships)
