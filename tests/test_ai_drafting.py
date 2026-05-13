"""Tests for Phase 8.1 AI drafting run audit lifecycle."""

from __future__ import annotations

import json
import time

import pytest

import auth as _auth
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
    user = _db.create_user(username, _auth.hash_password("password123"), "viewer", username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], role, _now()),
        )
        conn.execute("UPDATE users SET last_team_id = ? WHERE id = ?", (team_id, user["id"]))
        conn.commit()
    # Surface `user_id` so `services/visibility.py::is_privileged_coach`
    # can resolve membership-only privilege without falling back to the
    # legacy `users.role` short-circuit (removed in _migrate_v24).
    user["user_id"] = user["id"]
    return user


def test_ai_drafting_runs_schema_is_team_scoped(client):
    with _db.connect() as conn:
        columns = {row["name"]: row["type"].upper() for row in conn.execute("PRAGMA table_info(ai_drafting_runs)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(ai_drafting_runs)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert version >= 19
    for name in [
        "id",
        "team_id",
        "season_id",
        "created_by_user_id",
        "draft_target",
        "provider",
        "model",
        "status",
        "input_tokens",
        "output_tokens",
        "error_code",
        "error_message",
        "evidence_refs_json",
        "background_job_id",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    ]:
        assert name in columns
    assert columns["team_id"] == "TEXT"
    assert "idx_ai_drafting_runs_team_status" in indexes
    assert "idx_ai_drafting_runs_team_created" in indexes


def test_run_lifecycle_persists_success_and_failure_with_scope(client):
    from services import ai_drafting

    _create_team("ai-run-team-a")
    actor = _create_member("ai-run-team-a", "ai_run_admin_a")

    success = ai_drafting.create_run(
        team_id="ai-run-team-a",
        draft_target="player_summary",
        provider="mock-provider",
        model="mock-model-v1",
        created_by_user_id=actor["id"],
        evidence_refs=[{"type": "note", "id": "note-1", "visibility": "team", "excerpt": "must not persist"}],
        actor_user=actor,
    )
    assert success["status"] == "queued"
    assert success["evidence_refs"] == [{"type": "note", "id": "note-1", "visibility": "team"}]

    started = ai_drafting.start_run(success["id"], team_id="ai-run-team-a", actor_user=actor)
    assert started["status"] == "running"
    done = ai_drafting.succeed_run(
        success["id"],
        team_id="ai-run-team-a",
        input_tokens=321,
        output_tokens=42,
        actor_user=actor,
    )
    assert done["status"] == "succeeded"
    assert done["input_tokens"] == 321
    assert done["output_tokens"] == 42
    assert done["finished_at"]

    failed = ai_drafting.create_run(
        team_id="ai-run-team-a",
        draft_target="what_happened",
        provider="mock-provider",
        model="mock-model-v1",
        actor_user=actor,
    )
    ai_drafting.start_run(failed["id"], team_id="ai-run-team-a", actor_user=actor)
    failed = ai_drafting.fail_run(
        failed["id"],
        team_id="ai-run-team-a",
        error_code="provider_timeout",
        error_message="Provider timed out without raw prompt text",
        actor_user=actor,
    )
    assert failed["status"] == "failed"
    assert failed["error_code"] == "provider_timeout"
    assert failed["error_message"] == "Provider timed out without raw prompt text"

    listed = ai_drafting.list_runs("ai-run-team-a", actor_user=actor)
    assert [row["id"] for row in listed] == [failed["id"], success["id"]]
    assert ai_drafting.get_run(success["id"], team_id="ai-run-team-a", actor_user=actor)["status"] == "succeeded"


def test_team_a_cannot_access_team_b_runs(client):
    from services import ai_drafting

    _create_team("ai-run-team-a")
    _create_team("ai-run-team-b")
    actor_a = _create_member("ai-run-team-a", "ai_scope_admin_a")
    actor_b = _create_member("ai-run-team-b", "ai_scope_admin_b")

    run_b = ai_drafting.create_run(
        team_id="ai-run-team-b",
        draft_target="player_summary",
        provider="mock-provider",
        model="mock-model-v1",
        actor_user=actor_b,
    )

    assert ai_drafting.list_runs("ai-run-team-a", actor_user=actor_a) == []
    with pytest.raises(ai_drafting.AIDraftingAuthorizationError) as exc:
        ai_drafting.get_run(run_b["id"], team_id="ai-run-team-b", actor_user=actor_a)
    assert exc.value.status_code == 403
    with pytest.raises(ai_drafting.AIDraftingAuthorizationError):
        ai_drafting.start_run(run_b["id"], team_id="ai-run-team-b", actor_user=actor_a)


def test_player_and_guardian_cannot_read_ai_drafting_runs(client):
    from services import ai_drafting

    _create_team("ai-run-read-role")
    admin = _create_member("ai-run-read-role", "ai_read_admin", role="team_admin")
    player = _create_member("ai-run-read-role", "ai_read_player", role="player")
    guardian = _create_member("ai-run-read-role", "ai_read_guardian", role="guardian")
    run = ai_drafting.create_run(
        team_id="ai-run-read-role",
        draft_target="player_summary",
        provider="mock-provider",
        model="mock-model-v1",
        actor_user=admin,
    )

    for actor in [player, guardian]:
        with pytest.raises(ai_drafting.AIDraftingAuthorizationError):
            ai_drafting.list_runs("ai-run-read-role", actor_user=actor)
        with pytest.raises(ai_drafting.AIDraftingAuthorizationError):
            ai_drafting.get_run(run["id"], team_id="ai-run-read-role", actor_user=actor)


def test_unsupported_draft_target_is_rejected(client):
    from services import ai_drafting

    _create_team("ai-run-targets")
    actor = _create_member("ai-run-targets", "ai_target_admin")

    with pytest.raises(ai_drafting.AIDraftingValidationError) as exc:
        ai_drafting.create_run(
            team_id="ai-run-targets",
            draft_target="coach_private_note",
            provider="mock-provider",
            model="mock-model-v1",
            actor_user=actor,
        )
    assert exc.value.code == "unsupported_draft_target"


def test_privacy_canaries_raw_prompt_and_private_fields_are_not_persisted(client):
    from services import ai_drafting

    _create_team("ai-run-privacy")
    actor = _create_member("ai-run-privacy", "ai_privacy_admin")
    canary = "PRIVATE_PHASE8_RAW_PROMPT_CANARY"

    run = ai_drafting.create_run(
        team_id="ai-run-privacy",
        draft_target="why_it_matters",
        provider=canary,
        model=f"provider_output:{canary}",
        evidence_refs=[
            {
                "type": "note",
                "id": "note-private",
                "visibility": "private",
                "raw_prompt": canary,
                "prompt": canary,
                "provider_output": canary,
                "private_source_text": canary,
                "coach_private_note": canary,
                "body": canary,
                "reason": canary,
                "status": canary,
            },
            {
                "type": "note",
                "id": canary,
                "visibility": "private",
            },
        ],
        actor_user=actor,
    )

    failed = ai_drafting.fail_run(
        run["id"],
        team_id="ai-run-privacy",
        error_code=canary,
        error_message=f"Provider leaked {canary} in exception text",
        actor_user=actor,
    )
    serialized_run = json.dumps(failed, sort_keys=True)
    assert canary not in serialized_run
    assert "raw_prompt" not in serialized_run
    assert "provider_output" not in serialized_run
    assert failed["error_message"] == "AI drafting run failed"
    assert failed["error_code"] == "privacy_sanitized"
    assert failed["provider"] == "unknown"
    assert failed["model"] == "unknown"
    assert failed["evidence_refs"] == [{"type": "note", "id": "note-private", "visibility": "private"}]

    with _db.connect() as conn:
        raw = conn.execute(
            "SELECT evidence_refs_json FROM ai_drafting_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()["evidence_refs_json"]
        table_names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert canary not in raw
    assert "raw_prompt" not in raw
    assert "coach_private_note" not in raw
    assert "ai_drafting_runs" in table_names


def test_sqlite_to_postgres_helpers_include_ai_drafting_runs(client):
    import scripts.migrate_sqlite_to_postgres as migrate

    _create_team("ai-run-migration")
    actor = _create_member("ai-run-migration", "ai_migration_admin")
    from services import ai_drafting

    ai_drafting.create_run(
        team_id="ai-run-migration",
        draft_target="player_summary",
        provider="mock-provider",
        model="mock-model-v1",
        actor_user=actor,
    )

    with _db.connect() as conn:
        order = migrate.sqlite_table_order(conn)
        mirror = migrate.InMemoryPostgresMirror.from_sqlite(conn)
        summary = migrate.validate_migration(conn, mirror, order)

    assert "ai_drafting_runs" in order
    assert summary["row_counts"]["ai_drafting_runs"] == {"sqlite": 1, "postgres": 1}
    assert summary["scope_columns"]["ai_drafting_runs"]["sqlite_null_team_id"] == 0
    assert summary["privacy_canaries"]["ai_drafting_runs_private_payloads"] == {"sqlite": 0, "postgres": 0}
    assert "ai_drafting_runs" in migrate._SCOPE_TABLES
    assert "ai_drafting_runs" in migrate._PRIVACY_CANARY_TABLES


def _enable_ai_context(team_id: str, actor: dict, *, never_draft: list[str] | None = None) -> None:
    from services import team_settings

    team_settings.set_setting(team_id, "ai.drafting_enabled", True, actor_user=actor)
    team_settings.set_setting(team_id, "ai.allowed_draft_targets", ["player_summary", "what_happened"], actor_user=actor)
    if never_draft is not None:
        team_settings.set_setting(team_id, "ai.never_draft_for_visibilities", never_draft, actor_user=actor)


def _seed_ai_context_objects(team_id: str, actor: dict, *, prefix: str = "ai-context") -> dict:
    with _db.connect() as conn:
        season_id = f"{prefix}-season"
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (season_id, team_id, "Spring", "2026-01-01", "2026-06-01", _now()),
        )
        _db.upsert_match(conn, {
            "id": f"{prefix}-match",
            "home_team": "Replay",
            "away_team": "Visitors",
            "date": "2026-05-01",
            "slug": f"{prefix}-match",
            "created_at": _now(),
            "updated_at": _now(),
            "team_id": team_id,
            "season_id": season_id,
        })
        conn.commit()
    player = _db.create_player(f"{prefix} Player", team_id=team_id, season_id=season_id)
    note = _db.create_coaching_note({
        "match_id": f"{prefix}-match",
        "slot": "full",
        "timestamp_seconds": 12.0,
        "title": "Good scanning",
        "body": "Looked over shoulder before receiving",
        "visibility": "team",
        "player_ids": [player["id"]],
        "what_happened": "Checked shoulder twice",
        "why_it_matters": "Created time to turn",
        "what_to_do_next": "Repeat before first touch",
        "player_summary": "Strong awareness",
        "coach_private_note": "NOTE PRIVATE CANARY",
        "team_id": team_id,
        "season_id": season_id,
    }, actor=actor["id"])
    clip = _db.create_coaching_clip({
        "match_id": f"{prefix}-match",
        "slot": "full",
        "start_seconds": 10,
        "end_seconds": 16,
        "title": "Scanning clip",
        "description": "Receives under pressure",
        "visibility": "team",
        "player_ids": [player["id"]],
        "team_id": team_id,
    }, actor=actor["id"])
    playlist = _db.create_coaching_playlist({
        "title": "Awareness playlist",
        "description": "PLAYLIST PRIVATE DESCRIPTION CANARY",
        "visibility": "team",
        "note_ids": [note["id"]],
        "player_ids": [player["id"]],
        "team_id": team_id,
        "season_id": season_id,
    }, actor=actor["id"])
    goal = _db.create_player_goal({
        "player_id": player["id"],
        "title": "Scan before receiving",
        "description": "Scan early and often",
        "success_criteria": "Three shoulder checks per buildup",
        "visibility": "player",
        "status": "open",
        "coach_private_note": "GOAL PRIVATE CANARY",
        "source_note_id": note["id"],
        "team_id": team_id,
        "season_id": season_id,
    }, actor=actor["id"])
    summary = _db.create_coaching_match_summary({
        "match_id": f"{prefix}-match",
        "visibility": "team",
        "team_positives": "Built through midfield",
        "team_improvements": "Earlier support angles",
        "training_focus": "Scanning rondos",
        "body": "Compact match summary",
        "note_ids": [note["id"]],
        "clip_ids": [clip["id"]],
        "playlist_ids": [playlist["id"]],
        "team_id": team_id,
    }, actor=actor["id"])
    return {"season_id": season_id, "player": player, "note": note, "clip": clip, "playlist": playlist, "goal": goal, "summary": summary}


def test_ai_context_excludes_private_fields_and_keeps_compact_audit(client):
    from services import ai_context

    _create_team("ai-context-safe")
    actor = _create_member("ai-context-safe", "ai_context_safe_admin")
    _enable_ai_context("ai-context-safe", actor, never_draft=["private"])
    data = _seed_ai_context_objects("ai-context-safe", actor, prefix="ai-context-safe")

    result = ai_context.build_context(
        team_id="ai-context-safe",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[
            {"type": "note", "id": data["note"]["id"]},
            {"type": "clip", "id": data["clip"]["id"]},
            {"type": "playlist", "id": data["playlist"]["id"]},
            {"type": "goal", "id": data["goal"]["id"]},
            {"type": "match_summary", "id": data["summary"]["id"]},
            {"type": "player", "id": data["player"]["id"]},
        ],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "NOTE PRIVATE CANARY" not in serialized
    assert "GOAL PRIVATE CANARY" not in serialized
    assert "PLAYLIST PRIVATE DESCRIPTION CANARY" not in serialized
    assert "coach_private_note" not in serialized
    assert "tactical_board_json" not in serialized
    assert {ref["type"] for ref in result["audit"]["included"]} == {"note", "clip", "playlist", "goal", "match_summary", "player"}
    assert result["audit"]["excluded_by_visibility"] == []


def test_ai_context_cross_team_and_unlinked_player_data_never_appear(client):
    from services import ai_context

    _create_team("ai-context-team-a")
    _create_team("ai-context-team-b")
    actor_a = _create_member("ai-context-team-a", "ai_context_scope_admin_a")
    actor_b = _create_member("ai-context-team-b", "ai_context_scope_admin_b")
    _enable_ai_context("ai-context-team-a", actor_a, never_draft=["private"])
    own = _seed_ai_context_objects("ai-context-team-a", actor_a, prefix="ai-context-own")
    other = _seed_ai_context_objects("ai-context-team-b", actor_b, prefix="ai-context-other")
    unlinked_player = _db.create_player("Unlinked AI Context Player", team_id="ai-context-team-a", season_id=own["season_id"])
    unlinked_goal = _db.create_player_goal({
        "player_id": unlinked_player["id"],
        "title": "UNLINKED PLAYER CANARY",
        "visibility": "player",
        "team_id": "ai-context-team-a",
        "season_id": own["season_id"],
    }, actor=actor_a["id"])

    result = ai_context.build_context(
        team_id="ai-context-team-a",
        actor_user=actor_a,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[own["player"]["id"]],
        evidence_refs=[
            {"type": "note", "id": other["note"]["id"]},
            {"type": "clip", "id": other["clip"]["id"]},
            {"type": "playlist", "id": other["playlist"]["id"]},
            {"type": "goal", "id": other["goal"]["id"]},
            {"type": "match_summary", "id": other["summary"]["id"]},
            {"type": "player", "id": other["player"]["id"]},
            {"type": "goal", "id": unlinked_goal["id"]},
        ],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "ai-context-other" not in serialized
    assert "UNLINKED PLAYER CANARY" not in serialized
    assert [ref["type"] for ref in result["audit"]["excluded_by_cross_team_scope"]] == ["note", "clip", "playlist", "goal", "match_summary", "player"]
    assert result["audit"]["excluded_by_policy"] == [{"type": "goal", "id": str(unlinked_goal["id"]), "status": "excluded", "reason": "unlinked_player"}]


def test_ai_context_rejects_disallowed_draft_target_visibility(client):
    from services import ai_context

    _create_team("ai-context-target")
    actor = _create_member("ai-context-target", "ai_context_target_admin")
    _enable_ai_context("ai-context-target", actor)

    with pytest.raises(ai_context.AIContextValidationError) as exc:
        ai_context.build_context(
            team_id="ai-context-target",
            actor_user=actor,
            draft_target="player_summary",
            target_visibility="player",
            evidence_refs=[],
        )
    assert exc.value.code == "draft_not_allowed"


def test_ai_context_default_never_draft_excludes_player_visibility_source_and_opt_in_allows_it(client):
    from services import ai_context

    _create_team("ai-context-player-vis-default")
    actor = _create_member("ai-context-player-vis-default", "ai_context_player_vis_admin")
    _enable_ai_context("ai-context-player-vis-default", actor)
    data = _seed_ai_context_objects("ai-context-player-vis-default", actor, prefix="ai-context-player-vis")
    _db.update_coaching_note(data["note"]["id"], {"visibility": "player"})

    default_result = ai_context.build_context(
        team_id="ai-context-player-vis-default",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "note", "id": data["note"]["id"]}],
    )
    assert default_result["context"]["items"] == []
    assert default_result["audit"]["excluded_by_visibility"] == [
        {"type": "note", "id": str(data["note"]["id"]), "status": "excluded", "reason": "visibility_excluded"}
    ]

    _create_team("ai-context-player-vis-optin")
    actor_optin = _create_member("ai-context-player-vis-optin", "ai_context_player_vis_optin_admin")
    _enable_ai_context("ai-context-player-vis-optin", actor_optin, never_draft=["private"])
    optin = _seed_ai_context_objects("ai-context-player-vis-optin", actor_optin, prefix="ai-context-player-vis-optin")
    _db.update_coaching_note(optin["note"]["id"], {"visibility": "player"})

    optin_result = ai_context.build_context(
        team_id="ai-context-player-vis-optin",
        actor_user=actor_optin,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "note", "id": optin["note"]["id"]}],
    )
    assert optin_result["context"]["items"][0]["type"] == "note"
    assert optin_result["audit"]["excluded_by_visibility"] == []


def test_ai_context_private_note_is_permanently_excluded_even_when_setting_allows_private(client):
    from services import ai_context

    _create_team("ai-context-private-permanent")
    actor = _create_member("ai-context-private-permanent", "ai_context_private_permanent_admin")
    _enable_ai_context("ai-context-private-permanent", actor, never_draft=[])
    data = _seed_ai_context_objects("ai-context-private-permanent", actor, prefix="ai-context-private-permanent")
    _db.update_coaching_note(data["note"]["id"], {"visibility": "private", "body": "PRIVATE NOTE POLICY CANARY"})

    result = ai_context.build_context(
        team_id="ai-context-private-permanent",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "note", "id": data["note"]["id"]}],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "PRIVATE NOTE POLICY CANARY" not in serialized
    assert result["context"]["items"] == []
    assert result["audit"]["excluded_by_permanent_policy"] == [
        {"type": "note", "id": str(data["note"]["id"]), "status": "excluded", "reason": "private_source_excluded"}
    ]


def test_ai_context_target_player_filter_applies_to_player_profile_refs(client):
    from services import ai_context

    _create_team("ai-context-player-filter")
    actor = _create_member("ai-context-player-filter", "ai_context_player_filter_admin")
    _enable_ai_context("ai-context-player-filter", actor, never_draft=["private"])
    data = _seed_ai_context_objects("ai-context-player-filter", actor, prefix="ai-context-player-filter")
    unlinked_player = _db.create_player("UNLINKED PROFILE CANARY", team_id="ai-context-player-filter", season_id=data["season_id"])

    result = ai_context.build_context(
        team_id="ai-context-player-filter",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[data["player"]["id"]],
        evidence_refs=[{"type": "player", "id": unlinked_player["id"]}],
    )

    assert result["context"]["items"] == []
    assert "UNLINKED PROFILE CANARY" not in json.dumps(result, sort_keys=True)
    assert result["audit"]["excluded_by_policy"] == [
        {"type": "player", "id": unlinked_player["id"], "status": "excluded", "reason": "unlinked_player"}
    ]


def test_ai_context_development_profile_alias_is_compact_and_safe(client):
    from services import ai_context

    _create_team("ai-context-dev-profile")
    actor = _create_member("ai-context-dev-profile", "ai_context_dev_profile_admin")
    _enable_ai_context("ai-context-dev-profile", actor, never_draft=["private"])
    data = _seed_ai_context_objects("ai-context-dev-profile", actor, prefix="ai-context-dev-profile")
    _db.update_player(data["player"]["id"], notes="PLAYER PRIVATE NOTES CANARY")

    result = ai_context.build_context(
        team_id="ai-context-dev-profile",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[data["player"]["id"]],
        evidence_refs=[{"type": "development_profile", "id": data["player"]["id"]}],
    )

    assert result["context"]["items"] == [
        {
            "type": "development_profile",
            "id": data["player"]["id"],
            "display_name": data["player"]["display_name"],
            "jersey_number": data["player"].get("jersey_number", ""),
            "active": True,
            "team_id": "ai-context-dev-profile",
        }
    ]
    assert "PLAYER PRIVATE NOTES CANARY" not in json.dumps(result, sort_keys=True)


def test_ai_context_engagement_ref_uses_actual_compact_payload_keys(client):
    from services import ai_context

    _create_team("ai-context-engagement")
    actor = _create_member("ai-context-engagement", "ai_context_engagement_admin")
    _enable_ai_context("ai-context-engagement", actor, never_draft=["private"])
    _seed_ai_context_objects("ai-context-engagement", actor, prefix="ai-context-engagement")

    result = ai_context.build_context(
        team_id="ai-context-engagement",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "engagement", "id": "dashboard"}],
    )

    item = result["context"]["items"][0]
    assert item["type"] == "engagement"
    assert item["id"] == "dashboard"
    assert set(item) == {"type", "id", "summary", "by_player", "by_match", "unreviewed_assigned_items", "players_with_no_recent_feedback", "most_watched"}
    assert isinstance(item["by_player"], list)
    assert isinstance(item["by_match"], list)


def test_ai_context_engagement_ref_is_excluded_for_player_targeted_context(client):
    from services import ai_context

    _create_team("ai-context-engagement-targeted")
    actor = _create_member("ai-context-engagement-targeted", "ai_context_engagement_targeted_admin")
    _enable_ai_context("ai-context-engagement-targeted", actor, never_draft=["private"])
    data = _seed_ai_context_objects("ai-context-engagement-targeted", actor, prefix="ai-context-engagement-targeted")

    result = ai_context.build_context(
        team_id="ai-context-engagement-targeted",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[data["player"]["id"]],
        evidence_refs=[{"type": "engagement", "id": "dashboard"}],
    )

    assert result["context"]["items"] == []
    assert result["audit"]["excluded_by_policy"] == [
        {"type": "engagement", "id": "dashboard", "status": "excluded", "reason": "target_player_scope_required"}
    ]


def test_ai_context_malformed_numeric_and_unsafe_audit_refs_are_safely_excluded(client):
    from services import ai_context

    _create_team("ai-context-bad-refs")
    actor = _create_member("ai-context-bad-refs", "ai_context_bad_refs_admin")
    _enable_ai_context("ai-context-bad-refs", actor, never_draft=["private"])
    canary = "PRIVATE_PROMPT_CANARY should never reflect in audit"

    result = ai_context.build_context(
        team_id="ai-context-bad-refs",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[
            {"type": "note", "id": "not-a-number"},
            {"type": "unsupported:" + canary, "id": canary},
            {"type": "unsupportedSafeType", "id": "SafeLookingCanary"},
        ],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert canary not in serialized
    assert "SafeLookingCanary" not in serialized
    assert result["context"]["items"] == []
    assert result["audit"]["excluded_by_policy"] == [
        {"type": "note", "id": "redacted", "status": "excluded", "reason": "invalid_ref_id"},
        {"type": "unknown", "id": "redacted", "status": "excluded", "reason": "unsupported_ref"},
        {"type": "unknown", "id": "redacted", "status": "excluded", "reason": "unsupported_ref"},
    ]


def test_ai_context_review_ref_is_compact_and_safe(client, monkeypatch):
    from services import ai_context

    _create_team("ai-context-review")
    actor = _create_member("ai-context-review", "ai_context_review_admin")
    player_user = _create_member("ai-context-review", "ai_context_review_player", role="player")
    _enable_ai_context("ai-context-review", actor, never_draft=["private"])
    data = _seed_ai_context_objects("ai-context-review", actor, prefix="ai-context-review")
    _db.link_player_user(data["player"]["id"], player_user["id"], "self")
    _db.mark_coaching_review(player_user["id"], data["note"]["id"], None, reflection="PRIVATE REFLECTION CANARY")
    review = _db.list_coaching_reviews(user_id=player_user["id"])[0]
    monkeypatch.setattr(ai_context._db, "list_coaching_reviews", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unscoped review list should not be used")))

    result = ai_context.build_context(
        team_id="ai-context-review",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "review", "id": review["id"]}],
    )

    assert result["context"]["items"] == [
        {
            "type": "review",
            "id": str(review["id"]),
            "note_id": data["note"]["id"],
            "playlist_id": None,
            "reviewed_at": review["reviewed_at"],
        }
    ]
    assert "PRIVATE REFLECTION CANARY" not in json.dumps(result, sort_keys=True)


def test_ai_context_review_ref_obeys_source_visibility_and_target_player_scope(client):
    from services import ai_context

    _create_team("ai-context-review-scope")
    actor = _create_member("ai-context-review-scope", "ai_context_review_scope_admin")
    player_user = _create_member("ai-context-review-scope", "ai_context_review_scope_player", role="player")
    _enable_ai_context("ai-context-review-scope", actor)  # default excludes player-visible context
    data = _seed_ai_context_objects("ai-context-review-scope", actor, prefix="ai-context-review-scope")
    _db.update_coaching_note(data["note"]["id"], {"visibility": "player"})
    other_player = _db.create_player("Review Other Player", team_id="ai-context-review-scope", season_id=data["season_id"])
    _db.link_player_user(data["player"]["id"], player_user["id"], "self")
    _db.mark_coaching_review(player_user["id"], data["note"]["id"], None, reflection="REVIEW SCOPE CANARY")
    review = _db.list_coaching_reviews(user_id=player_user["id"])[0]

    player_visibility_result = ai_context.build_context(
        team_id="ai-context-review-scope",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[data["player"]["id"]],
        evidence_refs=[{"type": "review", "id": review["id"]}],
    )
    assert player_visibility_result["context"]["items"] == []
    assert player_visibility_result["audit"]["excluded_by_visibility"] == [
        {"type": "review", "id": str(review["id"]), "status": "excluded", "reason": "visibility_excluded"}
    ]

    _enable_ai_context("ai-context-review-scope", actor, never_draft=["private"])
    wrong_player_result = ai_context.build_context(
        team_id="ai-context-review-scope",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        target_player_ids=[other_player["id"]],
        evidence_refs=[{"type": "review", "id": review["id"]}],
    )
    serialized = json.dumps(wrong_player_result, sort_keys=True)
    assert "REVIEW SCOPE CANARY" not in serialized
    assert wrong_player_result["context"]["items"] == []
    assert wrong_player_result["audit"]["excluded_by_policy"] == [
        {"type": "review", "id": str(review["id"]), "status": "excluded", "reason": "unlinked_player"}
    ]


def _enable_ai_provider(team_id: str, actor: dict, *, targets: list[str] | None = None, never_draft: list[str] | None = None) -> None:
    from services import team_settings

    team_settings.set_setting(team_id, "ai.drafting_enabled", True, actor_user=actor)
    team_settings.set_setting(team_id, "ai.allowed_draft_targets", targets or ["player_summary", "what_happened"], actor_user=actor)
    team_settings.set_setting(team_id, "ai.never_draft_for_visibilities", never_draft or ["private"], actor_user=actor)


def test_ai_provider_successful_mock_draft_records_succeeded_run(client, monkeypatch):
    from services import ai_providers

    _create_team("ai-provider-success")
    actor = _create_member("ai-provider-success", "ai_provider_success_admin")
    _enable_ai_provider("ai-provider-success", actor)
    data = _seed_ai_context_objects("ai-provider-success", actor, prefix="ai-provider-success")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")
    monkeypatch.setenv("REPLAY_AI_PROVIDER_MODEL", "mock-model-test")

    result = ai_providers.generate_draft(
        team_id="ai-provider-success",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "note", "id": data["note"]["id"]}],
    )

    assert result["ok"] is True
    assert "Mock draft" in result["text"]
    assert result["run"]["status"] == "succeeded"
    assert result["run"]["provider"] == "mock"
    assert result["run"]["model"] == "mock-model-test"
    assert result["run"]["input_tokens"] >= 1
    assert result["run"]["output_tokens"] >= 1

    with _db.connect() as conn:
        row = conn.execute("SELECT * FROM ai_drafting_runs WHERE id = ?", (result["run"]["id"],)).fetchone()
    assert row["status"] == "succeeded"
    assert row["error_message"] is None


def test_ai_provider_failure_is_recorded_without_raw_response_or_prompt(client, monkeypatch, caplog):
    from services import ai_providers

    _create_team("ai-provider-failure")
    actor = _create_member("ai-provider-failure", "ai_provider_failure_admin")
    _enable_ai_provider("ai-provider-failure", actor)
    canary = "PRIVATE_RAW_PROMPT_PROVIDER_SECRET_CANARY"
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")
    monkeypatch.setenv("REPLAY_AI_PROVIDER_MODEL", "mock-model-test")
    provider = ai_providers.MockAIProvider(fail_with=f"provider_output:{canary}")

    result = ai_providers.generate_draft(
        team_id="ai-provider-failure",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        instruction=canary,
        provider=provider,
    )

    assert result["ok"] is False
    assert result["error_code"] == "provider_error"
    assert result["text"] == ""
    assert result["run"]["status"] == "failed"
    serialized = json.dumps(result, sort_keys=True)
    assert canary not in serialized
    assert "provider_output" not in serialized
    with _db.connect() as conn:
        raw_rows = [dict(row) for row in conn.execute("SELECT * FROM ai_drafting_runs")]
    assert canary not in json.dumps(raw_rows, sort_keys=True)
    assert canary not in caplog.text


def test_ai_provider_timeout_returns_safe_response_and_records_failure(client, monkeypatch):
    from services import ai_providers

    _create_team("ai-provider-timeout")
    actor = _create_member("ai-provider-timeout", "ai_provider_timeout_admin")
    _enable_ai_provider("ai-provider-timeout", actor)
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")
    monkeypatch.setenv("REPLAY_AI_PROVIDER_TIMEOUT_SECONDS", "0.01")

    started = time.monotonic()
    result = ai_providers.generate_draft(
        team_id="ai-provider-timeout",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        provider=ai_providers.MockAIProvider(delay_seconds=0.1),
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["error_code"] == "provider_timeout"
    assert result["text"] == ""
    assert result["run"]["status"] == "failed"
    assert result["run"]["error_message"] == "AI provider timed out"
    assert elapsed < 0.05


def test_ai_provider_passes_timeout_to_adapter_without_background_thread(client, monkeypatch):
    from services import ai_providers

    class TimeoutAwareProvider:
        def __init__(self):
            self.timeout_seconds = None

        def generate(self, request, *, timeout_seconds=None):
            self.timeout_seconds = timeout_seconds
            raise ai_providers.AIProviderTimeout("adapter timeout")

    _create_team("ai-provider-timeout-contract")
    actor = _create_member("ai-provider-timeout-contract", "ai_provider_timeout_contract_admin")
    _enable_ai_provider("ai-provider-timeout-contract", actor)
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")
    monkeypatch.setenv("REPLAY_AI_PROVIDER_TIMEOUT_SECONDS", "0.75")
    provider = TimeoutAwareProvider()

    result = ai_providers.generate_draft(
        team_id="ai-provider-timeout-contract",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        provider=provider,
    )

    assert result["ok"] is False
    assert result["error_code"] == "provider_timeout"
    assert provider.timeout_seconds == 0.75


def test_ai_provider_preserves_development_profile_audit_refs(client, monkeypatch):
    from services import ai_providers

    _create_team("ai-provider-development-profile")
    actor = _create_member("ai-provider-development-profile", "ai_provider_development_profile_admin")
    _enable_ai_provider("ai-provider-development-profile", actor)
    data = _seed_ai_context_objects("ai-provider-development-profile", actor, prefix="ai-provider-development-profile")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    result = ai_providers.generate_draft(
        team_id="ai-provider-development-profile",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[{"type": "development_profile", "id": data["player"]["id"]}],
    )

    assert result["ok"] is True
    assert {ref["type"] for ref in result["run"]["evidence_refs"]} == {"development_profile"}


def test_ai_provider_fail_closed_without_provider_calls_for_disabled_absent_or_missing_secret(client, monkeypatch):
    from services import ai_providers

    class CountingProvider(ai_providers.MockAIProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            return super().generate(request)

    _create_team("ai-provider-gates")
    actor = _create_member("ai-provider-gates", "ai_provider_gates_admin")
    provider = CountingProvider()
    monkeypatch.delenv("REPLAY_AI_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAY_AI_PROVIDER_API_KEY", raising=False)

    disabled = ai_providers.generate_draft(
        team_id="ai-provider-gates",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        provider=provider,
    )
    assert disabled["ok"] is False
    assert disabled["error_code"] == "drafting_disabled"

    _enable_ai_provider("ai-provider-gates", actor)
    absent = ai_providers.generate_draft(
        team_id="ai-provider-gates",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        provider=provider,
    )
    assert absent["ok"] is False
    assert absent["error_code"] == "provider_not_configured"

    monkeypatch.setenv("REPLAY_AI_PROVIDER", "openai")
    missing_secret = ai_providers.generate_draft(
        team_id="ai-provider-gates",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
        provider=provider,
    )
    assert missing_secret["ok"] is False
    assert missing_secret["error_code"] == "provider_secret_missing"
    assert provider.calls == 0


def test_ai_provider_unknown_non_mock_provider_fails_closed_without_call(client, monkeypatch):
    from services import ai_providers

    _create_team("ai-provider-unknown")
    actor = _create_member("ai-provider-unknown", "ai_provider_unknown_admin")
    _enable_ai_provider("ai-provider-unknown", actor)
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "future-provider")
    monkeypatch.setenv("REPLAY_AI_PROVIDER_API_KEY", "SECRET_AI_KEY_CANARY")

    result = ai_providers.generate_draft(
        team_id="ai-provider-unknown",
        actor_user=actor,
        draft_target="player_summary",
        target_visibility="team",
        evidence_refs=[],
    )

    assert result["ok"] is False
    assert result["error_code"] == "provider_unsupported"
    assert "SECRET_AI_KEY_CANARY" not in json.dumps(result, sort_keys=True)


def _auth_headers_for(user: dict) -> dict[str, str]:
    token = _auth.create_token(user["id"], user.get("role", "coach"), user["username"])
    return {"Authorization": f"Bearer {token}"}


async def _post_ai_draft(client, user: dict, payload: dict) -> object:
    return await client.post("/api/coach/ai/draft", json=payload, headers=_auth_headers_for(user))


def _base_ai_api_payload(team_id: str, data: dict, **overrides) -> dict:
    payload = {
        "team_id": team_id,
        "draft_target": "player_summary",
        "target_resource_type": "note",
        "target_resource_id": data["note"]["id"],
        "target_visibility": "team",
        "evidence_refs": [{"type": "note", "id": data["note"]["id"]}],
        "coach_prompt": "Keep it concise.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_requires_coach_access(client, monkeypatch):
    _create_team("ai-api-role")
    coach = _create_member("ai-api-role", "ai_api_role_coach", role="team_admin")
    viewer = _create_member("ai-api-role", "ai_api_role_viewer", role="viewer")
    assistant = _create_member("ai-api-role", "ai_api_role_assistant", role="assistant_coach")
    _enable_ai_provider("ai-api-role", coach, never_draft=["private"])
    data = _seed_ai_context_objects("ai-api-role", coach, prefix="ai-api-role")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, viewer, _base_ai_api_payload("ai-api-role", data))
    assistant_response = await _post_ai_draft(client, assistant, _base_ai_api_payload("ai-api-role", data))

    assert response.status_code == 403
    assert assistant_response.status_code == 403


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_requires_team_settings_opt_in(client, monkeypatch):
    _create_team("ai-api-opt-in")
    coach = _create_member("ai-api-opt-in", "ai_api_opt_in_coach", role="team_admin")
    data = _seed_ai_context_objects("ai-api-opt-in", coach, prefix="ai-api-opt-in")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-opt-in", data))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "drafting_disabled"


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_rejects_disallowed_target(client, monkeypatch):
    _create_team("ai-api-target")
    coach = _create_member("ai-api-target", "ai_api_target_coach", role="team_admin")
    _enable_ai_provider("ai-api-target", coach, targets=["what_happened"], never_draft=["private"])
    data = _seed_ai_context_objects("ai-api-target", coach, prefix="ai-api-target")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-target", data, draft_target="player_summary"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "drafting_disabled"


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_rejects_player_visible_target_by_policy(client, monkeypatch):
    _create_team("ai-api-player-policy")
    coach = _create_member("ai-api-player-policy", "ai_api_player_policy_coach", role="team_admin")
    _enable_ai_provider("ai-api-player-policy", coach, never_draft=["private", "player"])
    data = _seed_ai_context_objects("ai-api-player-policy", coach, prefix="ai-api-player-policy")
    _db.update_coaching_note(data["note"]["id"], {"visibility": "player"})
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-player-policy", data, target_visibility="player"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "drafting_disabled"


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_rejects_client_visibility_mismatch(client, monkeypatch):
    _create_team("ai-api-visibility-mismatch")
    coach = _create_member("ai-api-visibility-mismatch", "ai_api_visibility_mismatch_coach", role="team_admin")
    _enable_ai_provider("ai-api-visibility-mismatch", coach, never_draft=["private", "player"])
    data = _seed_ai_context_objects("ai-api-visibility-mismatch", coach, prefix="ai-api-visibility-mismatch")
    _db.update_coaching_note(data["note"]["id"], {"visibility": "player"})
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-visibility-mismatch", data, target_visibility="team"))

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "target_visibility_mismatch"


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_rejects_cross_team_resource_reference(client, monkeypatch):
    _create_team("ai-api-cross-a")
    _create_team("ai-api-cross-b")
    coach_a = _create_member("ai-api-cross-a", "ai_api_cross_a_coach", role="team_admin")
    coach_b = _create_member("ai-api-cross-b", "ai_api_cross_b_coach", role="team_admin")
    _enable_ai_provider("ai-api-cross-a", coach_a, never_draft=["private"])
    own = _seed_ai_context_objects("ai-api-cross-a", coach_a, prefix="ai-api-cross-own")
    other = _seed_ai_context_objects("ai-api-cross-b", coach_b, prefix="ai-api-cross-other")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(
        client,
        coach_a,
        _base_ai_api_payload("ai-api-cross-a", own, evidence_refs=[{"type": "note", "id": other["note"]["id"]}]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "resource_reference_unavailable"

    missing = await _post_ai_draft(
        client,
        coach_a,
        _base_ai_api_payload("ai-api-cross-a", own, evidence_refs=[{"type": "note", "id": "999999"}]),
    )
    assert missing.status_code == 403
    assert missing.json()["detail"]["error_code"] == "resource_reference_unavailable"


@pytest.mark.asyncio
async def test_coach_ai_draft_endpoint_records_authenticated_actor_id(client, monkeypatch):
    _create_team("ai-api-actor")
    coach = _create_member("ai-api-actor", "ai_api_actor_coach", role="team_admin")
    _enable_ai_provider("ai-api-actor", coach, never_draft=["private"])
    data = _seed_ai_context_objects("ai-api-actor", coach, prefix="ai-api-actor")
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-actor", data))

    assert response.status_code == 200
    assert response.json()["run"]["created_by_user_id"] == coach["id"]


@pytest.mark.asyncio
async def test_coach_ai_draft_output_is_not_visible_in_my_feedback_until_saved(client, monkeypatch):
    _create_team("ai-api-not-published")
    coach = _create_member("ai-api-not-published", "ai_api_not_published_coach", role="team_admin")
    player_user = _create_member("ai-api-not-published", "ai_api_not_published_player", role="player")
    _enable_ai_provider("ai-api-not-published", coach, never_draft=["private"])
    data = _seed_ai_context_objects("ai-api-not-published", coach, prefix="ai-api-not-published")
    _db.link_player_user(data["player"]["id"], player_user["id"], "self")
    draft_text = "AI_DRAFT_NOT_PUBLISHED_CANARY"
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-not-published", data, coach_prompt=draft_text))

    assert response.status_code == 200
    assert response.json()["ok"] is True
    feedback = await client.get("/api/my-feedback?team_id=ai-api-not-published", headers=_auth_headers_for(player_user))
    assert feedback.status_code == 200
    assert draft_text not in json.dumps(feedback.json(), sort_keys=True)


@pytest.mark.asyncio
async def test_coach_ai_draft_long_prompt_rejected_without_persisting_prompt_or_job_payload(client, monkeypatch):
    _create_team("ai-api-long-prompt")
    coach = _create_member("ai-api-long-prompt", "ai_api_long_prompt_coach", role="team_admin")
    _enable_ai_provider("ai-api-long-prompt", coach, never_draft=["private"])
    data = _seed_ai_context_objects("ai-api-long-prompt", coach, prefix="ai-api-long-prompt")
    canary = "LONG_PROMPT_PRIVATE_CANARY"
    monkeypatch.setenv("REPLAY_AI_PROVIDER", "mock")

    response = await _post_ai_draft(client, coach, _base_ai_api_payload("ai-api-long-prompt", data, coach_prompt=canary + ("x" * 6000)))

    assert response.status_code == 413
    serialized = json.dumps(response.json(), sort_keys=True)
    assert canary not in serialized
    with _db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT payload_json, error_text, result_json FROM background_jobs")]
        runs = [dict(row) for row in conn.execute("SELECT * FROM ai_drafting_runs")]
    assert canary not in json.dumps(rows, sort_keys=True)
    assert canary not in json.dumps(runs, sort_keys=True)
