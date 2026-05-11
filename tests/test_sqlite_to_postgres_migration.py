from __future__ import annotations

import sqlite3

import pytest

from scripts import migrate_sqlite_to_postgres as migrator


def _sqlite_fixture() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE teams (id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE matches (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            title TEXT,
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );
        CREATE TABLE coaching_notes (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            match_id TEXT,
            visibility TEXT NOT NULL DEFAULT 'team',
            body TEXT,
            coach_private_note TEXT,
            FOREIGN KEY(team_id) REFERENCES teams(id),
            FOREIGN KEY(match_id) REFERENCES matches(id)
        );
        CREATE TABLE coaching_note_players (
            note_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            PRIMARY KEY(note_id, player_id),
            FOREIGN KEY(note_id) REFERENCES coaching_notes(id)
        );
        INSERT INTO teams (id, name) VALUES ('team-b', 'B'), ('team-a', 'A');
        INSERT INTO matches (id, team_id, title) VALUES ('match-a', 'team-a', 'A Match');
        INSERT INTO coaching_notes (id, team_id, match_id, visibility, body, coach_private_note)
        VALUES ('note-private', 'team-a', 'match-a', 'private', 'body', 'coach only');
        """
    )
    return conn


def test_table_dependency_order_parents_before_children():
    conn = _sqlite_fixture()

    ordered = migrator.sqlite_table_order(conn)

    assert ordered.index("teams") < ordered.index("matches")
    assert ordered.index("matches") < ordered.index("coaching_notes")
    assert ordered.index("coaching_notes") < ordered.index("coaching_note_players")
    assert "sqlite_sequence" not in ordered


def test_sqlite_schema_converts_to_postgres_ddl_with_safe_identifiers():
    conn = _sqlite_fixture()

    ddl = migrator.postgres_create_table_sql(conn, "coaching_notes")

    assert 'CREATE TABLE IF NOT EXISTS "coaching_notes"' in ddl
    assert '"id" TEXT PRIMARY KEY' in ddl
    assert '"team_id" TEXT NOT NULL' in ddl
    assert '"coach_private_note" TEXT' in ddl
    assert "FOREIGN KEY" not in ddl  # validated explicitly after import, not in schema bootstrap


def test_sqlite_schema_converts_composite_primary_key_to_table_constraint():
    conn = _sqlite_fixture()

    ddl = migrator.postgres_create_table_sql(conn, "coaching_note_players")

    assert '"note_id" TEXT NOT NULL' in ddl
    assert '"player_id" TEXT NOT NULL' in ddl
    assert 'PRIMARY KEY ("note_id", "player_id")' in ddl
    assert '"note_id" TEXT PRIMARY KEY' not in ddl

def test_validation_summary_detects_row_scope_fk_and_privacy_canary_counts():
    sqlite_conn = _sqlite_fixture()
    pg = migrator.InMemoryPostgresMirror.from_sqlite(sqlite_conn)

    summary = migrator.validate_migration(sqlite_conn, pg, ["teams", "matches", "coaching_notes"])

    assert summary["row_counts"] == {
        "teams": {"sqlite": 2, "postgres": 2},
        "matches": {"sqlite": 1, "postgres": 1},
        "coaching_notes": {"sqlite": 1, "postgres": 1},
    }
    assert summary["scope_columns"]["matches"] == {
        "sqlite_null_team_id": 0,
        "postgres_null_team_id": 0,
        "sqlite_team_distribution": {"team-a": 1},
        "postgres_team_distribution": {"team-a": 1},
    }
    assert summary["foreign_keys"] == []
    assert summary["privacy_canaries"]["coaching_notes_private_payloads"] == {"sqlite": 1, "postgres": 1}


def test_validation_summary_reports_foreign_key_mismatches():
    sqlite_conn = _sqlite_fixture()
    pg = migrator.InMemoryPostgresMirror.from_sqlite(sqlite_conn)
    pg.delete_row("teams", "id", "team-a")

    summary = migrator.validate_migration(sqlite_conn, pg, ["teams", "matches", "coaching_notes"])

    assert summary["foreign_keys"] == [
        {
            "table": "matches",
            "column": "team_id",
            "parent_table": "teams",
            "parent_column": "id",
            "postgres_orphans": 1,
        },
        {
            "table": "coaching_notes",
            "column": "team_id",
            "parent_table": "teams",
            "parent_column": "id",
            "postgres_orphans": 1,
        },
    ]


def test_validation_summary_reports_team_distribution_mismatches():
    sqlite_conn = _sqlite_fixture()
    pg = migrator.InMemoryPostgresMirror.from_sqlite(sqlite_conn)
    pg.tables["matches"][0]["team_id"] = "team-b"

    summary = migrator.validate_migration(sqlite_conn, pg, ["teams", "matches", "coaching_notes"])

    assert summary["scope_columns"]["matches"]["sqlite_null_team_id"] == 0
    assert summary["scope_columns"]["matches"]["postgres_null_team_id"] == 0
    assert summary["scope_columns"]["matches"]["sqlite_team_distribution"] == {"team-a": 1}
    assert summary["scope_columns"]["matches"]["postgres_team_distribution"] == {"team-b": 1}
    with pytest.raises(RuntimeError, match="scope_mismatches"):
        migrator._assert_validation_clean(summary)


def test_migrate_rejects_missing_sqlite_path(tmp_path):
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="SQLite database not found"):
        migrator.migrate(missing, "postgresql://replay:***@localhost:5432/replay")
