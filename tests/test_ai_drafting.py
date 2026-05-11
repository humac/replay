"""Tests for Phase 8.1 AI drafting run audit lifecycle."""

from __future__ import annotations

import json

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
    user = _db.create_user(username, _auth.hash_password("password123"), "coach", username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], role, _now()),
        )
        conn.execute("UPDATE users SET last_team_id = ? WHERE id = ?", (team_id, user["id"]))
        conn.commit()
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
            {"type": "goal", "id": unlinked_goal["id"]},
        ],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "ai-context-other" not in serialized
    assert "UNLINKED PLAYER CANARY" not in serialized
    assert [ref["type"] for ref in result["audit"]["excluded_by_cross_team_scope"]] == ["note", "clip", "playlist", "goal", "match_summary"]
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
