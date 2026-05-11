"""Tests for team-scoped settings registry and AI drafting guards."""

from __future__ import annotations

import pytest

import db as _db
import auth as _auth


async def _login(client, username: str, password: str = "password123") -> dict:
    resp = await client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _now() -> str:
    return "2026-05-11T00:00:00Z"


def _create_team(team_id: str) -> None:
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO teams (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
            (team_id, team_id.replace("-", " ").title(), team_id, _now()),
        )
        conn.commit()


def _create_member(team_id: str, username: str, *, role: str = "team_admin") -> dict:
    user = _db.create_user(username, _auth.hash_password("password123"), "coach", username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], role, _now()),
        )
        conn.execute("UPDATE users SET last_team_id = ? WHERE id = ?", (team_id, user["id"]))
        conn.commit()
    return user


def _create_api_user(team_id: str, username: str, *, team_role: str, app_role: str = "coach") -> dict:
    user = _db.create_user(username, _auth.hash_password("password123"), app_role, username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], team_role, _now()),
        )
        conn.execute("UPDATE users SET last_team_id = ? WHERE id = ?", (team_id, user["id"]))
        conn.commit()
    return user


def test_team_settings_schema_and_unique_scope(client):
    with _db.connect() as conn:
        columns = {row["name"]: row["type"].upper() for row in conn.execute("PRAGMA table_info(team_settings)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(team_settings)")}

    assert columns["team_id"] == "TEXT"
    assert columns["key"] == "TEXT"
    assert columns["value_json"] == "TEXT"
    assert columns["updated_at"] == "TEXT"
    assert columns["updated_by"] == "TEXT"
    assert "idx_team_settings_team_key" in indexes


def test_defaults_and_valid_setting_writes(client):
    from services import team_settings

    _create_team("settings-team-a")
    actor = _create_member("settings-team-a", "settings-admin-a")

    defaults = team_settings.list_settings("settings-team-a", actor_user=actor)
    assert defaults["ai.drafting_enabled"] is False
    assert defaults["ai.never_draft_for_visibilities"] == ["private", "player"]
    assert defaults["notes.default_visibility"] == "private"
    assert defaults["goals.default_visibility"] == "player"

    saved = team_settings.set_setting("settings-team-a", "ai.tone", "technical", actor_user=actor)
    assert saved["key"] == "ai.tone"
    assert saved["value"] == "technical"
    assert saved["updated_by"] == actor["id"]

    team_settings.set_setting(
        "settings-team-a",
        "ai.allowed_draft_targets",
        ["player_summary", "what_happened", "goal_success_criteria"],
        actor_user=actor,
    )
    assert team_settings.get_setting("settings-team-a", "ai.allowed_draft_targets", actor_user=actor) == [
        "player_summary",
        "what_happened",
        "goal_success_criteria",
    ]


def test_auth_payload_user_id_can_read_and_write_without_mutating_defaults(client):
    from services import team_settings

    _create_team("settings-team-auth-payload")
    actor = _create_member("settings-team-auth-payload", "settings-auth-payload-admin")
    auth_payload = {"user_id": actor["id"], "username": actor["username"], "role": actor["role"]}

    defaults = team_settings.list_settings("settings-team-auth-payload", actor_user=auth_payload)
    defaults["ai.never_draft_for_visibilities"].append("team")

    assert team_settings.get_setting(
        "settings-team-auth-payload", "ai.never_draft_for_visibilities", actor_user=auth_payload
    ) == ["private", "player"]
    saved = team_settings.set_setting("settings-team-auth-payload", "ai.tone", "encouraging", actor_user=auth_payload)
    assert saved["updated_by"] == actor["id"]


def test_invalid_key_type_and_enum_raise_structured_validation(client):
    from services import team_settings

    _create_team("settings-team-validation")
    actor = _create_member("settings-team-validation", "settings-validation-admin")

    invalid_cases = [
        ("ai.unknown", True, "unsupported_key"),
        ("ai.drafting_enabled", "yes", "invalid_type"),
        ("ai.tone", "cheerful", "invalid_enum"),
        ("ai.allowed_draft_targets", ["player_summary", "unsupported_raw_target"], "invalid_enum"),
        ("ai.allowed_draft_targets", "player_summary", "invalid_type"),
        ("goals.default_visibility", "private", "invalid_enum"),
    ]
    for key, value, code in invalid_cases:
        with pytest.raises(team_settings.TeamSettingValidationError) as exc:
            team_settings.set_setting("settings-team-validation", key, value, actor_user=actor)
        assert exc.value.status_code == 422
        assert exc.value.code == code
        assert exc.value.key == key


def test_team_scope_guard_prevents_cross_team_read_and_write(client):
    from services import team_settings

    _create_team("settings-team-a")
    _create_team("settings-team-b")
    actor_a = _create_member("settings-team-a", "settings-scope-admin-a")
    actor_b = _create_member("settings-team-b", "settings-scope-admin-b")

    team_settings.set_setting("settings-team-b", "ai.tone", "encouraging", actor_user=actor_b)

    with pytest.raises(team_settings.TeamSettingAuthorizationError) as read_exc:
        team_settings.get_setting("settings-team-b", "ai.tone", actor_user=actor_a)
    assert read_exc.value.status_code == 403

    with pytest.raises(team_settings.TeamSettingAuthorizationError) as write_exc:
        team_settings.set_setting("settings-team-b", "ai.tone", "technical", actor_user=actor_a)
    assert write_exc.value.status_code == 403


def test_draft_target_visibility_guard_and_permanent_private_note_exclusion(client):
    from services import team_settings

    _create_team("settings-team-draft")
    actor = _create_member("settings-team-draft", "settings-draft-admin")
    team_settings.set_setting("settings-team-draft", "ai.drafting_enabled", True, actor_user=actor)
    team_settings.set_setting(
        "settings-team-draft",
        "ai.allowed_draft_targets",
        ["player_summary", "what_happened", "clip_description"],
        actor_user=actor,
    )

    assert team_settings.can_generate_draft(
        "settings-team-draft", "what_happened", visibility="team", actor_user=actor
    ) is True
    assert team_settings.can_generate_draft(
        "settings-team-draft", "what_happened", visibility="private", actor_user=actor
    ) is False
    assert team_settings.can_generate_draft(
        "settings-team-draft", "clip_description", visibility="player", actor_user=actor
    ) is False
    assert team_settings.can_generate_draft(
        "settings-team-draft", "clip_description", visibility=None, actor_user=actor
    ) is False
    assert team_settings.can_generate_draft(
        "settings-team-draft", "coach_private_note", visibility="team", actor_user=actor
    ) is False


def test_raw_json_cannot_smuggle_unsupported_ai_targets(client):
    from services import team_settings

    _create_team("settings-team-smuggle")
    actor = _create_member("settings-team-smuggle", "settings-smuggle-admin")

    with pytest.raises(team_settings.TeamSettingValidationError):
        team_settings.set_setting(
            "settings-team-smuggle",
            "ai.allowed_draft_targets",
            ["player_summary", {"target": "coach_private_note"}],
            actor_user=actor,
        )

    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT value_json FROM team_settings WHERE team_id = ? AND key = ?",
            ("settings-team-smuggle", "ai.allowed_draft_targets"),
        ).fetchall()
    assert rows == []


@pytest.mark.asyncio
async def test_api_coach_can_read_active_team_settings(client):
    _create_team("api-settings-read-team")
    coach = _create_api_user("api-settings-read-team", "api_settings_reader", team_role="coach")
    headers = await _login(client, coach["username"])

    resp = await client.get("/api/coach/team/settings", headers=headers)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["team_id"] == "api-settings-read-team"
    assert payload["can_edit"] is False
    assert payload["settings"]["ai.drafting_enabled"] is False
    assert payload["settings"]["ai.never_draft_for_visibilities"] == ["private", "player"]


@pytest.mark.asyncio
async def test_api_team_admin_can_patch_ai_governance_controls(client):
    _create_team("api-settings-admin-team")
    admin = _create_api_user("api-settings-admin-team", "api_settings_admin", team_role="team_admin")
    headers = await _login(client, admin["username"])

    resp = await client.patch(
        "/api/coach/team/settings",
        json={
            "settings": {
                "ai.drafting_enabled": True,
                "ai.allowed_draft_targets": ["player_summary", "what_happened"],
                "ai.tone": "technical",
                "ai.never_draft_for_visibilities": ["private"],
            }
        },
        headers=headers,
    )

    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert settings["ai.drafting_enabled"] is True
    assert settings["ai.allowed_draft_targets"] == ["player_summary", "what_happened"]
    assert settings["ai.tone"] == "technical"
    assert settings["ai.never_draft_for_visibilities"] == ["private"]


@pytest.mark.asyncio
async def test_api_coach_cannot_toggle_ai_or_relax_never_draft(client):
    _create_team("api-settings-coach-denied-team")
    coach = _create_api_user("api-settings-coach-denied-team", "api_settings_coach_denied", team_role="coach")
    headers = await _login(client, coach["username"])

    toggle_resp = await client.patch(
        "/api/coach/team/settings",
        json={"settings": {"ai.drafting_enabled": True}},
        headers=headers,
    )
    relax_resp = await client.patch(
        "/api/coach/team/settings",
        json={"settings": {"ai.never_draft_for_visibilities": ["private"]}},
        headers=headers,
    )

    assert toggle_resp.status_code == 403
    assert relax_resp.status_code == 403


@pytest.mark.asyncio
async def test_api_patch_validates_each_key_with_structured_422(client):
    _create_team("api-settings-validation-team")
    admin = _create_api_user("api-settings-validation-team", "api_settings_validation_admin", team_role="team_admin")
    headers = await _login(client, admin["username"])

    resp = await client.patch(
        "/api/coach/team/settings",
        json={"settings": {"ai.tone": "cheerful", "goals.default_visibility": "private"}},
        headers=headers,
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "team_settings_validation_failed"
    errors = detail["errors"]
    assert {error["key"] for error in errors} == {"ai.tone", "goals.default_visibility"}
    assert all(error["code"] == "invalid_enum" for error in errors)


@pytest.mark.asyncio
async def test_api_cross_team_settings_access_rejected(client):
    _create_team("api-settings-team-a")
    _create_team("api-settings-team-b")
    actor = _create_api_user("api-settings-team-a", "api_settings_wrong_team", team_role="team_admin")
    headers = await _login(client, actor["username"])

    read_resp = await client.get("/api/coach/team/settings?team_id=api-settings-team-b", headers=headers)
    patch_resp = await client.patch(
        "/api/coach/team/settings?team_id=api-settings-team-b",
        json={"settings": {"ai.tone": "technical"}},
        headers=headers,
    )

    assert read_resp.status_code in {403, 404}
    assert patch_resp.status_code in {403, 404}
