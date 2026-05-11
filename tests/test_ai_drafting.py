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
