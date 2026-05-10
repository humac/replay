"""Tenancy migration and helper tests.

Phase 1 PR 1.1 adds the additive team/season/membership foundation while
preserving legacy global role strings for recovery endpoints.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import auth as _auth
import db as _db


@pytest.fixture()
def fresh_db(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_file = data_dir / "replay.db"
    assets_dir = data_dir / "app_assets"
    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    yield _db
    _db.close_thread_connection()


def _insert_legacy_user(conn, user_id: str, username: str, role: str):
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at)
        VALUES (?, ?, 'hash', ?, '', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        (user_id, username, role),
    )


def test_v14_migration_is_idempotent_and_creates_default_scope_once(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db._migrate_v14(conn)
        fresh_db._migrate_v14(conn)
        conn.commit()

        teams = conn.execute("SELECT * FROM teams ORDER BY id").fetchall()
        seasons = conn.execute("SELECT * FROM seasons ORDER BY id").fetchall()

    assert len(teams) == 1
    assert teams[0]["name"] == "Default Team"
    assert teams[0]["slug"] == "default-team"
    assert teams[0]["game_format"] == "11v11"
    assert len(seasons) == 1
    assert seasons[0]["team_id"] == teams[0]["id"]
    assert seasons[0]["name"] == "Default Season"


def test_v14_adds_nullable_users_last_team_id_for_legacy_users(fresh_db):
    with fresh_db.connect() as conn:
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert "last_team_id" in cols
        assert cols["last_team_id"]["notnull"] == 0

    legacy = fresh_db.create_user("legacy", "hash", "viewer")
    assert fresh_db.get_user_by_id(legacy["id"])["last_team_id"] is None


def test_legacy_users_are_backfilled_to_default_memberships(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_file = data_dir / "replay.db"
    assets_dir = data_dir / "app_assets"
    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)

    # Simulate a pre-tenancy DB: remove v14 artifacts, lower schema version,
    # seed legacy roles, then re-run migrations.
    with _db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS team_user_memberships")
        conn.execute("DROP TABLE IF EXISTS seasons")
        conn.execute("DROP TABLE IF EXISTS teams")
        conn.execute("UPDATE schema_version SET version = 13")
        _insert_legacy_user(conn, "u-admin", "admin", "admin")
        _insert_legacy_user(conn, "u-coach", "coach", "coach,uploader")
        _insert_legacy_user(conn, "u-multi", "multi", "coach,viewer,parent")
        _insert_legacy_user(conn, "u-viewer", "viewer", "viewer")
        _insert_legacy_user(conn, "u-family", "family", "family")
        _insert_legacy_user(conn, "u-player", "player", "player")
        _insert_legacy_user(conn, "u-other", "other", "uploader")
        conn.commit()
    _db.close_thread_connection()

    _db.init(data_dir, db_file, assets_dir)

    default_team = _db.get_default_team()
    assert default_team is not None
    admin_memberships = _db.list_user_memberships("u-admin")
    assert len(admin_memberships) == 1
    assert {
        "team_id": admin_memberships[0]["team_id"],
        "user_id": admin_memberships[0]["user_id"],
        "role": admin_memberships[0]["role"],
        "created_at": admin_memberships[0]["created_at"],
    } == {
        "team_id": default_team["id"],
        "user_id": "u-admin",
        "role": "team_admin",
        "created_at": "2026-01-01T00:00:00Z",
    }
    assert [m["role"] for m in _db.list_user_memberships("u-coach")] == ["coach"]
    assert [m["role"] for m in _db.list_user_memberships("u-multi")] == ["coach", "guardian", "viewer"]
    assert [m["role"] for m in _db.list_user_memberships("u-viewer")] == ["viewer"]
    assert [m["role"] for m in _db.list_user_memberships("u-family")] == ["guardian"]
    assert [m["role"] for m in _db.list_user_memberships("u-player")] == ["player"]
    assert _db.list_user_memberships("u-other") == []

    _db.close_thread_connection()


def test_global_admin_role_string_is_preserved_for_recovery(fresh_db):
    user = fresh_db.create_user("root", "hash", "admin")

    stored = fresh_db.get_user_by_id(user["id"])
    assert stored["role"] == "admin"
    assert _auth.has_role(stored, "admin") is True
    assert _auth.has_role(stored, "coach") is True


def test_default_scope_helpers_return_expected_rows(fresh_db):
    team = fresh_db.get_default_team()
    assert team is not None
    assert team["slug"] == "default-team"

    season = fresh_db.get_default_season()
    assert season is not None
    assert season["team_id"] == team["id"]
    assert fresh_db.get_default_season(team["id"])["id"] == season["id"]


def test_new_users_receive_default_memberships_after_v14(fresh_db):
    user = fresh_db.create_user("newcoach", "hash", "coach,viewer")

    assert [m["role"] for m in fresh_db.list_user_memberships(user["id"])] == ["coach", "viewer"]


def test_role_updates_refresh_default_memberships(fresh_db):
    user = fresh_db.create_user("rolechange", "hash", "viewer")
    assert [m["role"] for m in fresh_db.list_user_memberships(user["id"])] == ["viewer"]

    assert fresh_db.update_user(user["id"], role="coach,parent") is True

    assert [m["role"] for m in fresh_db.list_user_memberships(user["id"])] == ["coach", "guardian"]
