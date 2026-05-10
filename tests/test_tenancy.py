"""Tenancy migration and default-scope tests.

Phase 1 PR 1.1/1.2 are intentionally additive: they create the team,
season, and membership tables, add nullable tenant columns to core rows,
and backfill legacy single-team deployments without changing user-visible
behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlite3

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


def _cols(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _column_info(conn, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_names(conn, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name = ?",
            (table,),
        ).fetchall()
    }


def _assert_not_null(conn, table: str, column: str) -> None:
    info = _column_info(conn, table)
    assert info[column]["notnull"] == 1, f"{table}.{column} should be NOT NULL"


def _assert_insert_null_fails(conn, table: str, insert_sql: str, params: tuple) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        conn.execute(insert_sql, params)


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]


def _force_tenancy_columns_nullable_for_legacy_test(conn) -> None:
    """Downgrade scoped columns to PR 1.2's nullable contract for migration tests.

    The test suite boots the current schema, then rewinds schema_version to
    simulate an older deployment. Once PR 1.3 makes tenant columns NOT NULL,
    we need to restore the pre-PR-1.3 shape before clearing values and rerunning
    migrations.
    """
    for table, columns in {
        "matches": {"team_id", "season_id"},
        "players": {"team_id", "season_id"},
        "player_user_links": {"team_id"},
        "coaching_notes": {"team_id"},
        "coaching_clips": {"team_id"},
        "coaching_playlists": {"team_id", "season_id"},
        "player_goals": {"team_id", "season_id"},
        "coaching_match_summaries": {"team_id"},
    }.items():
        create_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()["sql"]
        new_sql = create_sql.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_legacy_nullable", 1)
        if new_sql == create_sql:
            new_sql = create_sql.replace(f'CREATE TABLE "{table}"', f"CREATE TABLE {table}_legacy_nullable", 1)
        for column in columns:
            new_sql = new_sql.replace(f"{column} TEXT NOT NULL", f"{column} TEXT")
        if new_sql == create_sql:
            continue
        indexes = [
            row["sql"]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (table,),
            ).fetchall()
        ]
        conn.execute(f"DROP TABLE IF EXISTS {table}_legacy_nullable")
        conn.execute(new_sql)
        col_names = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        cols_sql = ", ".join(col_names)
        conn.execute(f"INSERT INTO {table}_legacy_nullable ({cols_sql}) SELECT {cols_sql} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_legacy_nullable RENAME TO {table}")
        for index_sql in indexes:
            conn.execute(index_sql)


def _seed_match(conn, match_id: str = "match-1") -> None:
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO matches (
            id, home_team, away_team, date, time, location, score_home, score_away,
            format, videos_json, video_status_json, home_logo, away_logo, created_at,
            slug, updated_at
        ) VALUES (?, 'Home', 'Away', '2026-01-01', '', '', NULL, NULL,
            'full', '{}', '{}', NULL, NULL, ?, ?, ?)
        """,
        (match_id, now, match_id, now),
    )


def _seed_legacy_v13_database(tmp_path: Path):
    data_dir = tmp_path / "legacy"
    db_file = data_dir / "replay.db"
    assets_dir = data_dir / "app_assets"
    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    with _db.connect() as conn:
        # Simulate a deployment whose schema_version predates Phase 1 tenancy.
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version(version) VALUES (13)")
        # The repository migrator always applies the latest schema on init.
        # To exercise the Phase 1 migrator idempotently, rewind the version,
        # remove default tenancy rows, and clear scope values from core rows.
        _force_tenancy_columns_nullable_for_legacy_test(conn)
        for table in ["team_user_memberships", "seasons", "teams"]:
            conn.execute(f"DELETE FROM {table}")
        for table in [
            "matches", "players", "player_user_links", "coaching_notes", "coaching_clips",
            "coaching_playlists", "player_goals", "coaching_match_summaries",
        ]:
            if "team_id" in _cols(conn, table):
                conn.execute(f"UPDATE {table} SET team_id = NULL")
            if "season_id" in _cols(conn, table):
                conn.execute(f"UPDATE {table} SET season_id = NULL")
        conn.commit()
    return data_dir, db_file, assets_dir


def test_tenancy_schema_creates_default_team_season_membership_tables(fresh_db):
    with fresh_db.connect() as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"teams", "seasons", "team_user_memberships"}.issubset(names)
        assert {"id", "name", "slug", "game_format", "created_at"}.issubset(_cols(conn, "teams"))
        assert {"id", "team_id", "name", "starts_on", "ends_on", "created_at"}.issubset(_cols(conn, "seasons"))
        assert {"id", "team_id", "user_id", "role", "created_at"}.issubset(_cols(conn, "team_user_memberships"))
        assert "last_team_id" in _cols(conn, "users")

        team = conn.execute("SELECT * FROM teams WHERE slug = 'default-team'").fetchone()
        season = conn.execute("SELECT * FROM seasons WHERE team_id = ? AND name = 'Default Season'", (team["id"],)).fetchone()
        assert team["name"] == "Default Team"
        assert season is not None


def test_tenancy_columns_exist_on_core_tables_with_expected_season_placement(fresh_db):
    with fresh_db.connect() as conn:
        expectations = {
            "matches": {"team_id", "season_id"},
            "players": {"team_id", "season_id"},
            "player_user_links": {"team_id"},
            "coaching_notes": {"team_id", "season_id"},
            "coaching_clips": {"team_id"},
            "coaching_playlists": {"team_id", "season_id"},
            "player_goals": {"team_id", "season_id"},
            "coaching_match_summaries": {"team_id"},
        }
        for table, expected in expectations.items():
            assert expected.issubset(_cols(conn, table)), table

        # Join/review/history tables inherit scope through parents in PR 1.2.
        for table in [
            "coaching_note_players",
            "coaching_note_tags",
            "coaching_clip_players",
            "coaching_playlist_items",
            "coaching_playlist_players",
            "coaching_match_summary_notes",
            "coaching_match_summary_clips",
            "coaching_match_summary_playlists",
            "coaching_reviews",
            "player_goal_status_history",
            "player_goal_reflections",
        ]:
            assert "team_id" not in _cols(conn, table), table


def test_pr_1_3_fresh_schema_enforces_non_null_scope_contract(fresh_db):
    """Fresh DB schema enforces PR 1.3 NOT NULL only where safe."""
    with fresh_db.connect() as conn:
        for table, columns in {
            "matches": ["team_id", "season_id"],
            "players": ["team_id", "season_id"],
            "player_user_links": ["team_id"],
            "coaching_notes": ["team_id"],
            "coaching_clips": ["team_id"],
            "coaching_playlists": ["team_id", "season_id"],
            "player_goals": ["team_id", "season_id"],
            "coaching_match_summaries": ["team_id"],
        }.items():
            for column in columns:
                _assert_not_null(conn, table, column)

        # Video coaching notes intentionally keep season_id nullable; they are
        # match scoped and PR 1.3 must not over-constrain observation/video rows.
        assert _column_info(conn, "coaching_notes")["season_id"]["notnull"] == 0


def test_pr_1_3_null_scope_writes_fail_where_contract_is_non_null(fresh_db):
    now = "2026-03-01T00:00:00Z"
    with fresh_db.connect() as conn:
        _assert_insert_null_fails(
            conn,
            "matches",
            """
            INSERT INTO matches (
                id, home_team, away_team, date, time, location, score_home, score_away,
                format, videos_json, video_status_json, home_logo, away_logo, created_at,
                slug, updated_at, team_id, season_id
            ) VALUES ('null-match', 'Home', 'Away', '2026-03-01', '', '', NULL, NULL,
                'full', '{}', '{}', NULL, NULL, ?, 'null-match', ?, NULL, 'default-season')
            """,
            (now, now),
        )
        _assert_insert_null_fails(
            conn,
            "players",
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('null-player', 'Null Player', '', 1, '', ?, ?, 'default-team', NULL)
            """,
            (now, now),
        )
        _assert_insert_null_fails(
            conn,
            "coaching_notes",
            """
            INSERT INTO coaching_notes (
                match_id, slot, timestamp_seconds, title, body, category, visibility,
                drawing_json, created_by, created_at, updated_at, note_context, team_id, season_id
            ) VALUES (NULL, NULL, NULL, 'Null team note', '', 'other', 'private', '{}', 'coach', ?, ?, 'observation', NULL, NULL)
            """,
            (now, now),
        )

        # Privacy/scope canary: video notes may still carry NULL season_id when
        # team_id is present, preserving the PR 1.1/1.2 table-by-table contract.
        conn.execute(
            """
            INSERT INTO coaching_notes (
                match_id, slot, timestamp_seconds, title, body, category, visibility,
                drawing_json, created_by, created_at, updated_at, note_context, team_id, season_id
            ) VALUES ('missing-match-ok-for-schema', 'full', 1, 'Video season nullable', '', 'other', 'private', '{}', 'coach', ?, ?, 'video', 'default-team', NULL)
            """,
            (now, now),
        )


def test_pr_1_3_scope_indexes_exist_for_frequent_tenant_filters(fresh_db):
    with fresh_db.connect() as conn:
        expected_indexes = {
            "matches": {"idx_matches_team", "idx_matches_team_season"},
            "players": {"idx_players_team", "idx_players_team_season"},
            "player_user_links": {"idx_player_user_links_team", "idx_player_user_links_team_player"},
            "coaching_notes": {"idx_coaching_notes_team", "idx_coaching_notes_team_match"},
            "coaching_clips": {"idx_coaching_clips_team", "idx_coaching_clips_team_match"},
            "coaching_playlists": {"idx_coaching_playlists_team", "idx_coaching_playlists_team_season"},
            "player_goals": {"idx_player_goals_team", "idx_player_goals_team_player"},
            "coaching_match_summaries": {"idx_coaching_match_summaries_team", "idx_coaching_match_summaries_team_match"},
        }
        for table, indexes in expected_indexes.items():
            assert indexes.issubset(_index_names(conn, table)), table


def test_existing_users_backfill_to_expected_default_memberships(tmp_path):
    data_dir, db_file, assets_dir = _seed_legacy_v13_database(tmp_path)
    with _db.connect() as conn:
        now = "2026-01-01T00:00:00Z"
        users = [
            ("admin-id", "legacy_admin", "admin"),
            ("coach-id", "legacy_coach", "coach,uploader"),
            ("viewer-id", "legacy_viewer", "viewer"),
            ("uploader-id", "legacy_uploader", "uploader"),
        ]
        conn.executemany(
            "INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at) VALUES (?, ?, 'hash', ?, '', 1, ?, ?)",
            [(uid, username, role, now, now) for uid, username, role in users],
        )
        conn.commit()

    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    with _db.connect() as conn:
        team = conn.execute("SELECT * FROM teams WHERE slug = 'default-team'").fetchone()
        memberships = conn.execute(
            "SELECT user_id, role FROM team_user_memberships WHERE team_id = ? ORDER BY user_id, role",
            (team["id"],),
        ).fetchall()
        assert {(row["user_id"], row["role"]) for row in memberships} == {
            ("admin-id", "team_admin"),
            ("coach-id", "coach"),
            ("viewer-id", "guardian"),
        }
        assert _db.get_user_by_id("admin-id")["role"] == "admin"
        assert _db.get_user_by_id("admin-id").get("last_team_id") is None


def test_migration_backfills_legacy_rows_preserves_counts_and_is_idempotent(tmp_path):
    data_dir, db_file, assets_dir = _seed_legacy_v13_database(tmp_path)
    with _db.connect() as conn:
        now = "2026-01-01T00:00:00Z"
        conn.execute("INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at) VALUES ('viewer-id', 'viewer', 'hash', 'viewer', '', 1, ?, ?)", (now, now))
        _seed_match(conn, "match-1")
        conn.execute("INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at) VALUES ('player-1', 'Player One', '9', 1, '', ?, ?)", (now, now))
        conn.execute("INSERT INTO player_user_links (player_id, user_id, relationship, created_at) VALUES ('player-1', 'viewer-id', 'parent', ?)", (now,))
        conn.execute("INSERT INTO coaching_notes (id, match_id, slot, timestamp_seconds, title, body, category, visibility, drawing_json, created_by, created_at, updated_at, note_context) VALUES (1, 'match-1', 'full', 12, 'Video note', '', 'other', 'team', '{}', 'coach', ?, ?, 'video')", (now, now))
        conn.execute("INSERT INTO coaching_notes (id, match_id, slot, timestamp_seconds, title, body, category, visibility, drawing_json, created_by, created_at, updated_at, note_context, event_title) VALUES (2, NULL, NULL, NULL, 'Observation', '', 'other', 'player', '{}', 'coach', ?, ?, 'observation', 'Practice')", (now, now))
        conn.execute("INSERT INTO coaching_clips (id, match_id, slot, start_seconds, end_seconds, title, description, category, visibility, drawing_json, created_by, created_at, updated_at) VALUES (1, 'match-1', 'full', 5, 10, 'Clip', '', 'other', 'team', '{}', 'coach', ?, ?)", (now, now))
        conn.execute("INSERT INTO coaching_playlists (id, title, description, visibility, pre_roll_seconds, post_roll_seconds, created_by, created_at, updated_at) VALUES (1, 'Playlist', '', 'team', 5, 8, 'coach', ?, ?)", (now, now))
        conn.execute("INSERT INTO player_goals (id, player_id, title, description, visibility, priority, target_date, success_criteria, coach_private_note, context, status, target_match_id, created_by, created_at, updated_at) VALUES (1, 'player-1', 'Goal', '', 'player', 'medium', '', '', '', 'season_goal', 'open', NULL, 'coach', ?, ?)", (now, now))
        conn.execute("INSERT INTO coaching_match_summaries (id, match_id, visibility, team_positives, team_improvements, training_focus, body, created_by, created_at, updated_at) VALUES (1, 'match-1', 'team', '', '', '', 'Summary', 'coach', ?, ?)", (now, now))
        before = {table: _count(conn, table) for table in ["matches", "players", "player_user_links", "coaching_notes", "coaching_clips", "coaching_playlists", "player_goals", "coaching_match_summaries"]}
        conn.commit()

    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)

    with _db.connect() as conn:
        after = {table: _count(conn, table) for table in before}
        assert after == before
        assert _count(conn, "teams") == 1
        assert _count(conn, "seasons") == 1
        default_team = conn.execute("SELECT id FROM teams WHERE slug='default-team'").fetchone()["id"]
        default_season = conn.execute("SELECT id FROM seasons WHERE team_id=?", (default_team,)).fetchone()["id"]
        for table in ["matches", "players", "player_user_links", "coaching_notes", "coaching_clips", "coaching_playlists", "player_goals", "coaching_match_summaries"]:
            assert conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE team_id IS NULL").fetchone()["c"] == 0, table
        assert conn.execute("SELECT COUNT(*) AS c FROM matches WHERE season_id = ?", (default_season,)).fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM players WHERE season_id = ?", (default_season,)).fetchone()["c"] == 1
        assert conn.execute("SELECT season_id FROM coaching_notes WHERE id = 1").fetchone()["season_id"] is None
        assert conn.execute("SELECT season_id FROM coaching_notes WHERE id = 2").fetchone()["season_id"] == default_season
        assert conn.execute("SELECT season_id FROM coaching_playlists WHERE id = 1").fetchone()["season_id"] == default_season
        assert conn.execute("SELECT season_id FROM player_goals WHERE id = 1").fetchone()["season_id"] == default_season


def test_observation_notes_linked_only_to_player_inherit_player_scope(fresh_db):
    now = "2026-02-01T00:00:00Z"
    with fresh_db.connect() as conn:
        conn.execute(
            "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('team-two', 'Team Two', 'team-two', 'full', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('season-two', 'team-two', 'Spring', '', '', ?)",
            (now,),
        )
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('player-two', 'Scoped Player Two', '2', 1, '', ?, ?, 'team-two', 'season-two')
            """,
            (now, now),
        )
        conn.commit()

    note = fresh_db.create_coaching_note({
        "note_context": "observation",
        "title": "Player scoped observation",
        "event_title": "Training",
        "player_ids": ["player-two"],
    })

    with fresh_db.connect() as conn:
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (note["id"],)).fetchone()) == ("team-two", "season-two")


def test_observation_note_with_match_inherits_match_scope(fresh_db):
    now = "2026-02-01T00:00:00Z"
    with fresh_db.connect() as conn:
        conn.execute(
            "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('match-team', 'Match Team', 'match-team', 'full', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('match-season', 'match-team', 'Fall', '', '', ?)",
            (now,),
        )
        conn.execute(
            """
            INSERT INTO matches (
                id, home_team, away_team, date, time, location, score_home, score_away,
                format, videos_json, video_status_json, home_logo, away_logo, created_at,
                slug, updated_at, team_id, season_id
            ) VALUES ('match-two', 'Match', 'Scope', '2026-02-01', '', '', NULL, NULL,
                'full', '{}', '{}', NULL, NULL, ?, 'match-two', ?, 'match-team', 'match-season')
            """,
            (now, now),
        )
        conn.commit()

    note = fresh_db.create_coaching_note({
        "note_context": "observation",
        "match_id": "match-two",
        "title": "Match scoped observation",
        "event_title": "Training",
    })

    with fresh_db.connect() as conn:
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (note["id"],)).fetchone()) == ("match-team", "match-season")


def test_observation_note_update_recomputes_player_scope(fresh_db):
    now = "2026-02-01T00:00:00Z"
    with fresh_db.connect() as conn:
        conn.execute("INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('update-team', 'Update Team', 'update-team', 'full', ?)", (now,))
        conn.execute("INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('update-season', 'update-team', 'Spring', '', '', ?)", (now,))
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('update-player', 'Update Player', '3', 1, '', ?, ?, 'update-team', 'update-season')
            """,
            (now, now),
        )
        conn.commit()

    note = fresh_db.create_coaching_note({"note_context": "observation", "title": "Unscoped observation", "event_title": "Training"})
    updated = fresh_db.update_coaching_note(note["id"], {"player_ids": ["update-player"]})
    assert updated is not None

    with fresh_db.connect() as conn:
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (note["id"],)).fetchone()) == ("update-team", "update-season")


def test_observation_note_update_preserves_explicit_scope_on_scalar_edit(fresh_db):
    now = "2026-02-01T00:00:00Z"
    with fresh_db.connect() as conn:
        conn.execute("INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('explicit-team', 'Explicit Team', 'explicit-team', 'full', ?)", (now,))
        conn.execute("INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('explicit-season', 'explicit-team', 'Spring', '', '', ?)", (now,))
        conn.commit()

    note = fresh_db.create_coaching_note({
        "note_context": "observation",
        "title": "Explicit observation",
        "event_title": "Training",
        "team_id": "explicit-team",
        "season_id": "explicit-season",
    })
    updated = fresh_db.update_coaching_note(note["id"], {"title": "Edited explicit observation"})
    assert updated is not None

    with fresh_db.connect() as conn:
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (note["id"],)).fetchone()) == ("explicit-team", "explicit-season")


def test_player_user_link_backfill_inherits_player_team(tmp_path):
    data_dir, db_file, assets_dir = _seed_legacy_v13_database(tmp_path)
    now = "2026-02-01T00:00:00Z"
    with _db.connect() as conn:
        conn.execute("INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('link-team', 'Link Team', 'link-team', 'full', ?)", (now,))
        conn.execute("INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('link-season', 'link-team', 'Spring', '', '', ?)", (now,))
        conn.execute("INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at) VALUES ('link-user', 'link_user', 'hash', 'viewer', '', 1, ?, ?)", (now, now))
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('link-player', 'Link Player', '4', 1, '', ?, ?, 'link-team', 'link-season')
            """,
            (now, now),
        )
        conn.execute("INSERT INTO player_user_links (player_id, user_id, relationship, created_at, team_id) VALUES ('link-player', 'link-user', 'parent', ?, NULL)", (now,))
        conn.commit()

    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    with _db.connect() as conn:
        assert conn.execute("SELECT team_id FROM player_user_links WHERE player_id='link-player' AND user_id='link-user'").fetchone()["team_id"] == "link-team"


def test_db_helpers_create_rows_in_default_scope(fresh_db):
    default_team = fresh_db.get_default_team()
    default_season = fresh_db.get_default_season(default_team["id"])
    match = {
        "id": "helper-match",
        "home_team": "Scope",
        "away_team": "Default",
        "date": "2026-02-01",
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "slug": "helper-match",
    }
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, match)
        conn.commit()
    player = fresh_db.create_player("Scoped Player")
    note = fresh_db.create_coaching_note({"match_id": match["id"], "slot": "full", "timestamp_seconds": 1.0, "title": "Scoped note"})
    observation = fresh_db.create_coaching_note({"note_context": "observation", "title": "Scoped observation", "event_title": "Training"})
    clip = fresh_db.create_coaching_clip({"match_id": match["id"], "slot": "full", "start_seconds": 1, "end_seconds": 4, "title": "Scoped clip"})
    playlist = fresh_db.create_coaching_playlist({"title": "Scoped playlist"})
    goal = fresh_db.create_player_goal({"player_id": player["id"], "title": "Scoped goal", "context": "season_goal"})
    summary = fresh_db.create_coaching_match_summary({"match_id": match["id"], "body": "Scoped summary"})

    with fresh_db.connect() as conn:
        assert tuple(conn.execute("SELECT team_id, season_id FROM matches WHERE id = ?", (match["id"],)).fetchone()) == (default_team["id"], default_season["id"])
        assert tuple(conn.execute("SELECT team_id, season_id FROM players WHERE id = ?", (player["id"],)).fetchone()) == (default_team["id"], default_season["id"])
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (note["id"],)).fetchone()) == (default_team["id"], None)
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_notes WHERE id = ?", (observation["id"],)).fetchone()) == (default_team["id"], default_season["id"])
        assert conn.execute("SELECT team_id FROM coaching_clips WHERE id = ?", (clip["id"],)).fetchone()["team_id"] == default_team["id"]
        assert tuple(conn.execute("SELECT team_id, season_id FROM coaching_playlists WHERE id = ?", (playlist["id"],)).fetchone()) == (default_team["id"], default_season["id"])
        assert tuple(conn.execute("SELECT team_id, season_id FROM player_goals WHERE id = ?", (goal["id"],)).fetchone()) == (default_team["id"], default_season["id"])
        assert conn.execute("SELECT team_id FROM coaching_match_summaries WHERE id = ?", (summary["id"],)).fetchone()["team_id"] == default_team["id"]


class _ScopeRequest:
    def __init__(self, **query):
        self.query_params = query
        self.headers = {}


def _insert_team_with_season(conn, team_id: str, slug: str, season_id: str | None = None):
    now = "2026-04-01T00:00:00Z"
    season_id = season_id or f"{team_id}-season"
    conn.execute(
        "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES (?, ?, ?, 'full', ?)",
        (team_id, team_id.replace('-', ' ').title(), slug, now),
    )
    conn.execute(
        "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, 'Default Season', '', '', ?)",
        (season_id, team_id, now),
    )
    return season_id


def _insert_user(conn, user_id: str, username: str, role: str = "viewer", last_team_id: str | None = None):
    now = "2026-04-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at, last_team_id)
        VALUES (?, ?, 'hash', ?, '', 1, ?, ?, ?)
        """,
        (user_id, username, role, now, now, last_team_id),
    )


def _grant_membership(conn, team_id: str, user_id: str, role: str):
    conn.execute(
        "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, '2026-04-01T00:00:00Z')",
        (team_id, user_id, role),
    )


def test_pr_2_1_resolve_scope_allows_single_team_membership_by_default(fresh_db):
    import tenancy

    with fresh_db.connect() as conn:
        team = fresh_db.get_default_team(conn=conn)
        season = fresh_db.get_default_season(team["id"], conn=conn)
        _insert_user(conn, "coach-scope", "coach_scope", "coach")
        conn.execute("DELETE FROM team_user_memberships WHERE user_id = 'coach-scope'")
        _grant_membership(conn, team["id"], "coach-scope", "coach")
        conn.commit()

    scope = tenancy.resolve_scope(
        _ScopeRequest(),
        {"user_id": "coach-scope", "username": "coach_scope", "role": "coach"},
        require_role="coach",
    )
    assert scope.team["id"] == team["id"]
    assert scope.season["id"] == season["id"]
    assert scope.membership["role"] == "coach"
    assert scope.effective_role == "coach"
    assert scope.is_global_admin is False


def test_pr_2_1_explicit_team_requires_membership_even_with_legacy_coach_role(fresh_db):
    import tenancy
    from fastapi import HTTPException

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "team-a", "team-a")
        _insert_team_with_season(conn, "team-b", "team-b")
        _insert_user(conn, "coach-a", "coach_a", "coach")
        _grant_membership(conn, "team-a", "coach-a", "coach")
        conn.commit()

    scope = tenancy.resolve_scope(
        _ScopeRequest(team="team-a"),
        {"user_id": "coach-a", "username": "coach_a", "role": "coach"},
        require_role="coach",
    )
    assert scope.team["id"] == "team-a"

    with pytest.raises(HTTPException) as exc:
        tenancy.resolve_scope(
            _ScopeRequest(team="team-b"),
            {"user_id": "coach-a", "username": "coach_a", "role": "coach"},
            require_role="coach",
        )
    assert exc.value.status_code == 403


def test_pr_2_1_multi_team_user_without_selected_scope_requires_selection(fresh_db):
    import tenancy
    from fastapi import HTTPException

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "multi-a", "multi-a")
        _insert_team_with_season(conn, "multi-b", "multi-b")
        _insert_user(conn, "multi-coach", "multi_coach", "coach")
        _grant_membership(conn, "multi-a", "multi-coach", "coach")
        _grant_membership(conn, "multi-b", "multi-coach", "coach")
        conn.commit()

    with pytest.raises(HTTPException) as exc:
        tenancy.resolve_scope(
            _ScopeRequest(),
            {"user_id": "multi-coach", "username": "multi_coach", "role": "coach"},
            require_role="coach",
        )
    assert exc.value.status_code == 409
    assert "selection" in str(exc.value.detail).lower()


def test_pr_2_1_saved_last_team_breaks_multi_team_tie(fresh_db):
    import tenancy

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "saved-a", "saved-a")
        _insert_team_with_season(conn, "saved-b", "saved-b")
        _insert_user(conn, "saved-coach", "saved_coach", "coach", last_team_id="saved-b")
        _grant_membership(conn, "saved-a", "saved-coach", "coach")
        _grant_membership(conn, "saved-b", "saved-coach", "coach")
        conn.commit()

    scope = tenancy.resolve_scope(
        _ScopeRequest(),
        {"user_id": "saved-coach", "username": "saved_coach", "role": "coach"},
        require_role="coach",
    )
    assert scope.team["id"] == "saved-b"


def test_pr_2_1_assistant_coach_capability_limits_are_centralized():
    import tenancy

    assert tenancy.role_has_capability("assistant_coach", "coach_object:write")
    assert tenancy.role_has_capability("assistant_coach", "coach_object:edit")
    assert not tenancy.role_has_capability("assistant_coach", "membership:manage")
    assert not tenancy.role_has_capability("assistant_coach", "team_settings:manage")
    assert not tenancy.role_has_capability("assistant_coach", "ai_settings:manage")
    assert not tenancy.role_has_capability("assistant_coach", "global_admin")
    assert not tenancy.role_has_capability("assistant_coach", "coach_object:delete_others")


def test_pr_2_1_explicit_global_admin_override_is_not_implicit(fresh_db):
    import tenancy
    from fastapi import HTTPException

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "admin-target", "admin-target")
        conn.commit()

    global_admin = {"user_id": None, "username": "admin", "role": "admin"}
    with pytest.raises(HTTPException) as exc:
        tenancy.resolve_scope(
            _ScopeRequest(team="admin-target"),
            global_admin,
            require_role="team_admin",
        )
    assert exc.value.status_code == 403

    scope = tenancy.resolve_scope(
        _ScopeRequest(team="admin-target"),
        global_admin,
        require_role="team_admin",
        allow_global_admin_override=True,
    )
    assert scope.team["id"] == "admin-target"
    assert scope.membership is None
    assert scope.effective_role == "global_admin"
    assert scope.is_global_admin is True


def test_pr_2_1_explicit_global_admin_override_wins_over_low_membership(fresh_db):
    import tenancy
    from fastapi import HTTPException

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "admin-member-target", "admin-member-target")
        _insert_user(conn, "db-admin", "db_admin", "admin")
        _grant_membership(conn, "admin-member-target", "db-admin", "guardian")
        conn.commit()

    db_admin = {"user_id": "db-admin", "username": "db_admin", "role": "admin"}
    with pytest.raises(HTTPException) as exc:
        tenancy.resolve_scope(
            _ScopeRequest(team="admin-member-target"),
            db_admin,
            require_role="team_admin",
        )
    assert exc.value.status_code == 403

    scope = tenancy.resolve_scope(
        _ScopeRequest(team="admin-member-target"),
        db_admin,
        require_role="team_admin",
        allow_global_admin_override=True,
    )
    assert scope.membership["role"] == "guardian"
    assert scope.effective_role == "global_admin"
    assert scope.is_global_admin is True


def test_pr_2_1_explicit_season_id_resolves_owning_team(fresh_db):
    import tenancy

    with fresh_db.connect() as conn:
        _insert_team_with_season(conn, "season-team-a", "season-team-a", "season-a")
        _insert_team_with_season(conn, "season-team-b", "season-team-b", "season-b")
        _insert_user(conn, "season-coach", "season_coach", "coach")
        _grant_membership(conn, "season-team-a", "season-coach", "coach")
        _grant_membership(conn, "season-team-b", "season-coach", "coach")
        conn.commit()

    scope = tenancy.resolve_scope(
        _ScopeRequest(season_id="season-b"),
        {"user_id": "season-coach", "username": "season_coach", "role": "coach"},
        require_role="coach",
    )
    assert scope.team["id"] == "season-team-b"
    assert scope.season["id"] == "season-b"
