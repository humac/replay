"""Tests for team-scoped settings registry and AI drafting guards."""

from __future__ import annotations

import pytest

import db as _db


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
    user = _db.create_user(username, "hash", "viewer", username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], role, _now()),
        )
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
