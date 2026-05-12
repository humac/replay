"""Database connection, schema migrations, and match persistence."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import log as _log

logger = _log.setup("replay")

_STRICT_TENANCY_TRUE_VALUES = {"1", "true", "yes", "on"}
_VALID_DB_BACKENDS = {"sqlite", "postgres"}
_POSTGRES_URL_PREFIXES = ("postgresql://", "postgresql+psycopg://")


def strict_tenancy_enabled() -> bool:
    return os.getenv("REPLAY_STRICT_TENANCY", "").strip().lower() in _STRICT_TENANCY_TRUE_VALUES


def configured_database_url() -> str | None:
    """Return the configured database URL, if one was provided."""
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


def configured_db_backend() -> str:
    """Return the requested DB backend for Phase 6 Postgres lane configuration.

    Phase 6.2 introduces a Postgres compose/test lane but does not switch the
    application runtime away from SQLite. Callers that need a real Postgres
    connection should use connect_postgres() explicitly.
    """
    explicit = os.getenv("REPLAY_DB_BACKEND", "").strip().lower()
    if explicit:
        if explicit not in _VALID_DB_BACKENDS:
            allowed = ", ".join(sorted(_VALID_DB_BACKENDS))
            raise RuntimeError(f"REPLAY_DB_BACKEND must be one of: {allowed}")
        return explicit

    url = configured_database_url()
    if url and url.startswith(_POSTGRES_URL_PREFIXES):
        return "postgres"
    return "sqlite"


def postgres_runtime_requested() -> bool:
    """Whether env config requests Postgres for the future runtime path."""
    return configured_db_backend() == "postgres"


def connect_postgres(database_url: str | None = None):
    """Open an explicit psycopg connection for the Phase 6.2 Postgres lane.

    This helper is intentionally separate from connect(), which remains the
    SQLite runtime connection until the later Alembic/runtime migration PRs.
    """
    url = (database_url or configured_database_url() or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for Postgres connections")
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.removeprefix("postgresql+psycopg://")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised only when dependency missing
        raise RuntimeError("psycopg is required for Postgres support") from exc

    return psycopg.connect(url, row_factory=dict_row)


def _require_team_scope_for_strict(helper: str, team_id: str | None, *, allow_unscoped: bool = False) -> None:
    if strict_tenancy_enabled() and team_id is None and not allow_unscoped:
        raise RuntimeError(
            f"{helper} requires team_id when REPLAY_STRICT_TENANCY=1; "
            "pass team_id=... or allow_unscoped=True for documented global/legacy reads"
        )

_thread_local = threading.local()

# Set by init() at startup
DB_FILE: Path = Path("replay.db")
DATA_DIR: Path = Path(".")
APP_ASSETS_DIR: Path = Path("app_assets")


def init(data_dir: Path, db_file: Path, app_assets_dir: Path):
    """Configure module-level paths and run migrations."""
    global DB_FILE, DATA_DIR, APP_ASSETS_DIR
    DB_FILE = db_file
    DATA_DIR = data_dir
    APP_ASSETS_DIR = app_assets_dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if postgres_runtime_requested():
        logger.warning(
            "Postgres database configuration detected; Phase 6.2 provides the "
            "Postgres compose/test lane only, and app runtime migrations still "
            "use SQLite until the Alembic/runtime migration PRs land"
        )
    with connect() as conn:
        _run_migrations(conn)


def connect() -> sqlite3.Connection:
    """Return a thread-local cached SQLite connection."""
    conn = getattr(_thread_local, "db_conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.Error:
            pass
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _thread_local.db_conn = conn
    return conn


def close_thread_connection():
    """Close the thread-local DB connection (used by tests)."""
    conn = getattr(_thread_local, "db_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _thread_local.db_conn = None


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

def _get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else -1
    except sqlite3.OperationalError:
        return -1


def _set_schema_version(conn: sqlite3.Connection, version: int):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.execute(f"PRAGMA user_version = {int(version)}")


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def _migrate_v0(conn: sqlite3.Connection):
    """Initial schema: matches, upload_sessions, settings tables."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            date TEXT,
            time TEXT,
            location TEXT,
            score_home INTEGER,
            score_away INTEGER,
            format TEXT,
            videos_json TEXT NOT NULL,
            video_status_json TEXT NOT NULL,
            home_logo TEXT,
            away_logo TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_sessions (
            id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            ext TEXT NOT NULL,
            raw_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            chunk_size INTEGER NOT NULL,
            total_chunks INTEGER NOT NULL,
            next_index INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )


def _migrate_v1(conn: sqlite3.Connection):
    """Add slug column to matches."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
    if "slug" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN slug TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_slug ON matches(slug)")


def _migrate_v2(conn: sqlite3.Connection):
    """Add users table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            display_name TEXT DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _migrate_v3(conn: sqlite3.Connection):
    """Add video_errors table for persisting transcode failure details."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            error_code TEXT NOT NULL,
            reason TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_video_errors_match ON video_errors(match_id)"
    )


def _migrate_v4(conn: sqlite3.Connection):
    """Add first_chunk_hash column to upload_sessions for upload fingerprinting."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(upload_sessions)").fetchall()}
    if "first_chunk_hash" not in cols:
        conn.execute("ALTER TABLE upload_sessions ADD COLUMN first_chunk_hash TEXT")


def _migrate_v5(conn: sqlite3.Connection):
    """Add updated_at column to matches table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")


def _migrate_v6(conn: sqlite3.Connection):
    """Add settings_audit table — one row per admin-driven settings change.

    Used by the admin Settings page so a coding agent (or the user) can
    review and roll back recent tuning changes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            key TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT NOT NULL,
            actor TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_settings_audit_ts ON settings_audit(ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_settings_audit_key ON settings_audit(key)")


def _migrate_v7(conn: sqlite3.Connection):
    """Add activity_events table for the admin overview feed."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL DEFAULT '',
            match_id TEXT,
            slot TEXT,
            actor TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_events_created ON activity_events(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_events_match ON activity_events(match_id)")


def _migrate_v8(conn: sqlite3.Connection):
    """Add coaching workspace tables: roster, notes, overlays, playlists."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            jersey_number TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS player_user_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            relationship TEXT NOT NULL DEFAULT 'family',
            created_at TEXT NOT NULL,
            UNIQUE(player_id, user_id),
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_user_links_player ON player_user_links(player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_user_links_user ON player_user_links(user_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            timestamp_seconds REAL NOT NULL,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'other',
            visibility TEXT NOT NULL DEFAULT 'private',
            drawing_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_notes_match ON coaching_notes(match_id, slot, timestamp_seconds)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_notes_visibility ON coaching_notes(visibility)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_note_players (
            note_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            PRIMARY KEY(note_id, player_id),
            FOREIGN KEY(note_id) REFERENCES coaching_notes(id) ON DELETE CASCADE,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_note_players_player ON coaching_note_players(player_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_note_tags (
            note_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY(note_id, tag),
            FOREIGN KEY(note_id) REFERENCES coaching_notes(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            pre_roll_seconds REAL NOT NULL DEFAULT 5,
            post_roll_seconds REAL NOT NULL DEFAULT 8,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_playlists_visibility ON coaching_playlists(visibility)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_playlist_items (
            playlist_id INTEGER NOT NULL,
            note_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY(playlist_id, note_id),
            FOREIGN KEY(playlist_id) REFERENCES coaching_playlists(id) ON DELETE CASCADE,
            FOREIGN KEY(note_id) REFERENCES coaching_notes(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_playlist_players (
            playlist_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            PRIMARY KEY(playlist_id, player_id),
            FOREIGN KEY(playlist_id) REFERENCES coaching_playlists(id) ON DELETE CASCADE,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_playlist_players_player ON coaching_playlist_players(player_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            note_id INTEGER,
            playlist_id INTEGER,
            reflection TEXT DEFAULT '',
            reviewed_at TEXT NOT NULL,
            UNIQUE(user_id, note_id, playlist_id)
        )
        """
    )


def _migrate_v9(conn: sqlite3.Connection):
    """Add structured coaching-note fields (Phase 1 of the coaching analysis
    roadmap). Each new column is optional and ships with a safe default so
    existing notes round-trip unchanged.

    - `note_type` — tone of the note (correction / positive / question /
      team_concept / individual_goal). Default 'correction' preserves the
      legacy implied behaviour.
    - `what_happened` / `why_it_matters` / `what_to_do_next` — coaching-
      point structure that templates (Phase 2) will pre-fill.
    - `player_summary` — short, age-appropriate text shown to players in
      My Feedback. Falls back to `body` when blank.
    - `coach_private_note` — internal coach-only note, never sent to
      viewers (filtered out by `_filter_notes_for_user` in server.py)."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(coaching_notes)").fetchall()}
    if "note_type" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN note_type TEXT NOT NULL DEFAULT 'correction'")
    if "what_happened" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN what_happened TEXT NOT NULL DEFAULT ''")
    if "why_it_matters" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN why_it_matters TEXT NOT NULL DEFAULT ''")
    if "what_to_do_next" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN what_to_do_next TEXT NOT NULL DEFAULT ''")
    if "player_summary" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN player_summary TEXT NOT NULL DEFAULT ''")
    if "coach_private_note" not in cols:
        conn.execute("ALTER TABLE coaching_notes ADD COLUMN coach_private_note TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_notes_note_type ON coaching_notes(note_type)")


def _migrate_v11(conn: sqlite3.Connection):
    """Phase 6a — observation notes.

    Coaching notes can now represent either a `video` note (existing
    behavior, anchored to `match_id` + `slot` + `timestamp_seconds`)
    or an `observation` note (no video, attached to a practice / game /
    meeting / tactical concept / other event, optionally carrying a
    `tactical_board_json` sketch).

    Schema-wise this is purely additive:

    - `note_context TEXT NOT NULL DEFAULT 'video'` — every existing row
      becomes a video note, preserving current behavior with no data
      migration. The Pydantic + DB layers default to `'video'` for old
      payloads and old rows.
    - `event_title` / `event_date` / `event_type` / `tactical_board_json`
      — optional, default empty / NULL. Video notes leave them empty.

    `match_id` / `slot` / `timestamp_seconds` stay declared `NOT NULL`
    in the original `_migrate_v8` CREATE TABLE — but observation notes
    need to omit them. SQLite doesn't support dropping NOT NULL via
    `ALTER TABLE`, so we re-create the table without those constraints
    and copy every row over. This is the safest path: SQLite lets us
    swap tables atomically inside the migration's implicit txn, and
    re-running the migration is safe because the post-condition is
    `pragma table_info(coaching_notes).match_id.notnull == 0`.

    Re-running the migration is safe: each ADD COLUMN is idempotent via
    the `cols` check, the table-rebuild is gated on the same check
    (skipped when `match_id` is already nullable), and the indexes use
    `IF NOT EXISTS`.
    """
    cols_info = {row["name"]: row for row in conn.execute("PRAGMA table_info(coaching_notes)").fetchall()}

    if "note_context" not in cols_info:
        conn.execute(
            "ALTER TABLE coaching_notes ADD COLUMN note_context TEXT NOT NULL DEFAULT 'video'"
        )
    if "event_title" not in cols_info:
        conn.execute(
            "ALTER TABLE coaching_notes ADD COLUMN event_title TEXT NOT NULL DEFAULT ''"
        )
    if "event_date" not in cols_info:
        # Stored as ISO-date text (YYYY-MM-DD) when supplied; empty
        # string otherwise. Kept TEXT so a future format extension
        # (e.g. ISO datetime) doesn't require another migration.
        conn.execute(
            "ALTER TABLE coaching_notes ADD COLUMN event_date TEXT NOT NULL DEFAULT ''"
        )
    if "event_type" not in cols_info:
        conn.execute(
            "ALTER TABLE coaching_notes ADD COLUMN event_type TEXT NOT NULL DEFAULT ''"
        )
    if "tactical_board_json" not in cols_info:
        # NULL means "no board"; an empty object `{}` would also be
        # valid but NULL keeps the storage tighter and lets the
        # row-mapper distinguish "never set" from "explicitly cleared".
        conn.execute(
            "ALTER TABLE coaching_notes ADD COLUMN tactical_board_json TEXT"
        )

    # Re-create the table to drop NOT NULL on the moment-anchoring
    # columns. Skip when the rebuild has already happened. `pragma
    # table_info` returns sqlite3.Row objects; index by name into a
    # plain dict so we can read the `notnull` flag uniformly.
    info = {
        r["name"]: {"notnull": r["notnull"]}
        for r in conn.execute("PRAGMA table_info(coaching_notes)").fetchall()
    }
    needs_rebuild = any(
        info.get(key, {}).get("notnull")
        for key in ("match_id", "slot", "timestamp_seconds")
    )

    if needs_rebuild:
        # Drop indexes that point at the old table; re-created below.
        conn.execute("DROP INDEX IF EXISTS idx_coaching_notes_match")
        conn.execute("DROP INDEX IF EXISTS idx_coaching_notes_visibility")
        conn.execute("DROP INDEX IF EXISTS idx_coaching_notes_note_type")
        conn.execute(
            """
            CREATE TABLE coaching_notes_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT,
                slot TEXT,
                timestamp_seconds REAL,
                title TEXT NOT NULL,
                body TEXT DEFAULT '',
                category TEXT NOT NULL DEFAULT 'other',
                visibility TEXT NOT NULL DEFAULT 'private',
                drawing_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                note_type TEXT NOT NULL DEFAULT 'correction',
                what_happened TEXT NOT NULL DEFAULT '',
                why_it_matters TEXT NOT NULL DEFAULT '',
                what_to_do_next TEXT NOT NULL DEFAULT '',
                player_summary TEXT NOT NULL DEFAULT '',
                coach_private_note TEXT NOT NULL DEFAULT '',
                note_context TEXT NOT NULL DEFAULT 'video',
                event_title TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                tactical_board_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO coaching_notes_new (
                id, match_id, slot, timestamp_seconds, title, body, category,
                visibility, drawing_json, created_by, created_at, updated_at,
                note_type, what_happened, why_it_matters, what_to_do_next,
                player_summary, coach_private_note, note_context, event_title,
                event_date, event_type, tactical_board_json
            )
            SELECT
                id, match_id, slot, timestamp_seconds, title, body, category,
                visibility, drawing_json, created_by, created_at, updated_at,
                note_type, what_happened, why_it_matters, what_to_do_next,
                player_summary, coach_private_note, note_context, event_title,
                event_date, event_type, tactical_board_json
            FROM coaching_notes
            """
        )
        conn.execute("DROP TABLE coaching_notes")
        conn.execute("ALTER TABLE coaching_notes_new RENAME TO coaching_notes")

    # Re-create indexes (idempotent — IF NOT EXISTS).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_notes_match "
        "ON coaching_notes(match_id, slot, timestamp_seconds)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_notes_visibility "
        "ON coaching_notes(visibility)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_notes_note_type "
        "ON coaching_notes(note_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_notes_note_context "
        "ON coaching_notes(note_context)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_notes_event_date "
        "ON coaching_notes(event_date)"
    )


def _migrate_v10(conn: sqlite3.Connection):
    """Add `coaching_clips` + `coaching_clip_players` (Phase 4a).

    Clips are first-class coaching objects: a coach selects a
    `[start_seconds, end_seconds]` window of a match slot, optionally
    seeded from an existing note (`source_note_id`), and saves it as a
    reusable moment that can later be added to playlists, exported, or
    referenced from My Feedback. Phase 4a adds the schema + backend
    only; the Coach Review clip UI and MP4 export ship in later
    phases.

    Schema choices intentionally mirror `coaching_notes` so the same
    visibility ladder + linked-player rules apply unchanged:
      - `match_id` / `slot` are the source video coordinates
      - `start_seconds` / `end_seconds` define the window (server-side
        validators clamp end > start and cap duration)
      - `category` / `visibility` come from the existing note enums
      - `source_note_id` is a nullable forward-compat reference; if the
        note is later deleted the clip stays valid (we set NULL via
        `delete_coaching_note`'s cascade-by-hand rather than ON DELETE
        SET NULL so SQLite's older versions behave consistently)
      - `drawing_json` is a snapshot of the source note's drawing
        captured at clip-create time. Storing a copy means the clip is
        self-contained — the linked note can be edited or deleted
        without losing the visual context the coach saw when authoring.

    `coaching_clip_players` mirrors `coaching_note_players` exactly so
    the same `linked_player_ids_for_user` filter logic applies."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'other',
            visibility TEXT NOT NULL DEFAULT 'private',
            source_note_id INTEGER,
            drawing_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_note_id) REFERENCES coaching_notes(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_clips_match "
        "ON coaching_clips(match_id, slot, start_seconds)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_clips_visibility "
        "ON coaching_clips(visibility)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_clips_source_note "
        "ON coaching_clips(source_note_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_clip_players (
            clip_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            PRIMARY KEY(clip_id, player_id),
            FOREIGN KEY(clip_id) REFERENCES coaching_clips(id) ON DELETE CASCADE,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_clip_players_player "
        "ON coaching_clip_players(player_id)"
    )


def _migrate_v12(conn: sqlite3.Connection):
    """Add Phase 7 player goals, status history, and reflections."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS player_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'player',
            priority TEXT NOT NULL DEFAULT 'medium',
            target_date TEXT NOT NULL DEFAULT '',
            success_criteria TEXT NOT NULL DEFAULT '',
            coach_private_note TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT 'next_match',
            status TEXT NOT NULL DEFAULT 'open',
            source_note_id INTEGER,
            source_clip_id INTEGER,
            source_playlist_id INTEGER,
            source_playlist_item_note_id INTEGER,
            target_match_id TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    goal_cols = {row["name"] for row in conn.execute("PRAGMA table_info(player_goals)").fetchall()}
    for name, ddl in {
        "visibility": "ALTER TABLE player_goals ADD COLUMN visibility TEXT NOT NULL DEFAULT 'player'",
        "priority": "ALTER TABLE player_goals ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'",
        "target_date": "ALTER TABLE player_goals ADD COLUMN target_date TEXT NOT NULL DEFAULT ''",
        "success_criteria": "ALTER TABLE player_goals ADD COLUMN success_criteria TEXT NOT NULL DEFAULT ''",
        "coach_private_note": "ALTER TABLE player_goals ADD COLUMN coach_private_note TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in goal_cols:
            conn.execute(ddl)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goals_player ON player_goals(player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goals_status ON player_goals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goals_visibility ON player_goals(visibility)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS player_goal_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goal_status_history_goal ON player_goal_status_history(goal_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS player_goal_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            reflection TEXT NOT NULL DEFAULT '',
            needs_coach_follow_up INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goal_reflections_goal ON player_goal_reflections(goal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goal_reflections_user ON player_goal_reflections(user_id)")


def _migrate_v13(conn: sqlite3.Connection):
    """Add match-level coaching summaries (Phase 8)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_match_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private',
            team_positives TEXT NOT NULL DEFAULT '',
            team_improvements TEXT NOT NULL DEFAULT '',
            training_focus TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_match_summaries_match "
        "ON coaching_match_summaries(match_id, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coaching_match_summaries_visibility "
        "ON coaching_match_summaries(visibility)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_match_summary_notes (
            summary_id INTEGER NOT NULL,
            note_id INTEGER NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(summary_id, note_id),
            FOREIGN KEY(summary_id) REFERENCES coaching_match_summaries(id) ON DELETE CASCADE,
            FOREIGN KEY(note_id) REFERENCES coaching_notes(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_match_summary_clips (
            summary_id INTEGER NOT NULL,
            clip_id INTEGER NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(summary_id, clip_id),
            FOREIGN KEY(summary_id) REFERENCES coaching_match_summaries(id) ON DELETE CASCADE,
            FOREIGN KEY(clip_id) REFERENCES coaching_clips(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coaching_match_summary_playlists (
            summary_id INTEGER NOT NULL,
            playlist_id INTEGER NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(summary_id, playlist_id),
            FOREIGN KEY(summary_id) REFERENCES coaching_match_summaries(id) ON DELETE CASCADE,
            FOREIGN KEY(playlist_id) REFERENCES coaching_playlists(id) ON DELETE CASCADE
        )
        """
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table_column_info(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _rebuild_table_with_not_null_text_columns(
    conn: sqlite3.Connection,
    table: str,
    not_null_columns: set[str],
) -> None:
    info = _table_column_info(conn, table)
    if all(info[column]["notnull"] for column in not_null_columns):
        return

    create_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if create_row is None or not create_row["sql"]:
        raise RuntimeError(f"Cannot rebuild missing table {table}")

    temp_table = f"{table}_v15_nonnull"
    create_sql = create_row["sql"]
    temp_sql = re.sub(
        rf"^CREATE\s+TABLE\s+\"?{re.escape(table)}\"?",
        f"CREATE TABLE {temp_table}",
        create_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    for column in not_null_columns:
        temp_sql = re.sub(
            rf"(\b{re.escape(column)}\s+TEXT)(?!\s+NOT\s+NULL)",
            r"\1 NOT NULL",
            temp_sql,
            count=1,
            flags=re.IGNORECASE,
        )

    index_sql = [
        row["sql"]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name = ? AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(temp_sql)
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    columns_sql = ", ".join(columns)
    conn.execute(f"INSERT INTO {temp_table} ({columns_sql}) SELECT {columns_sql} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")
    for sql in index_sql:
        conn.execute(sql)


def _ensure_default_team_and_season(conn: sqlite3.Connection) -> tuple[str, str]:
    now = _now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO teams (id, name, slug, game_format, created_at)
        VALUES ('default-team', 'Default Team', 'default-team', 'full', ?)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO seasons (id, team_id, name, starts_on, ends_on, created_at)
        VALUES ('default-season', 'default-team', 'Default Season', '', '', ?)
        """,
        (now,),
    )
    return "default-team", "default-season"


def _membership_roles_for_global_role(role: str | None) -> list[str]:
    parts = {part.strip().lower() for part in (role or "").split(",") if part.strip()}
    memberships: list[str] = []
    if "admin" in parts:
        memberships.append("team_admin")
    if "coach" in parts:
        memberships.append("coach")
    if "viewer" in parts or "player" in parts or "family" in parts or "guardian" in parts:
        memberships.append("guardian")
    return memberships


def _backfill_user_memberships(conn: sqlite3.Connection, team_id: str) -> None:
    now = _now_iso()
    rows = conn.execute("SELECT id, role FROM users").fetchall()
    for row in rows:
        for membership_role in _membership_roles_for_global_role(row["role"]):
            conn.execute(
                """
                INSERT OR IGNORE INTO team_user_memberships (team_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (team_id, row["id"], membership_role, now),
            )


def _backfill_default_scope(conn: sqlite3.Connection) -> None:
    team_id, season_id = _ensure_default_team_and_season(conn)
    _backfill_user_memberships(conn, team_id)

    conn.execute("UPDATE matches SET team_id = COALESCE(team_id, ?), season_id = COALESCE(season_id, ?)", (team_id, season_id))
    conn.execute("UPDATE players SET team_id = COALESCE(team_id, ?), season_id = COALESCE(season_id, ?)", (team_id, season_id))
    conn.execute(
        """
        UPDATE player_user_links
        SET team_id = COALESCE(
            team_id,
            (SELECT team_id FROM players WHERE players.id = player_user_links.player_id),
            ?
        )
        """,
        (team_id,),
    )
    conn.execute(
        """
        UPDATE coaching_notes
        SET team_id = COALESCE(
                team_id,
                (SELECT team_id FROM matches WHERE matches.id = coaching_notes.match_id),
                (SELECT team_id FROM players WHERE players.id = (SELECT player_id FROM coaching_note_players WHERE coaching_note_players.note_id = coaching_notes.id LIMIT 1)),
                ?
            ),
            season_id = CASE
                WHEN note_context = 'observation' THEN COALESCE(
                    season_id,
                    (SELECT season_id FROM matches WHERE matches.id = coaching_notes.match_id),
                    (SELECT season_id FROM players WHERE players.id = (SELECT player_id FROM coaching_note_players WHERE coaching_note_players.note_id = coaching_notes.id LIMIT 1)),
                    ?
                )
                ELSE season_id
            END
        """,
        (team_id, season_id),
    )
    conn.execute(
        """
        UPDATE coaching_clips
        SET team_id = COALESCE(team_id, (SELECT team_id FROM matches WHERE matches.id = coaching_clips.match_id), ?)
        """,
        (team_id,),
    )
    conn.execute("UPDATE coaching_playlists SET team_id = COALESCE(team_id, ?), season_id = COALESCE(season_id, ?)", (team_id, season_id))
    conn.execute(
        """
        UPDATE player_goals
        SET team_id = COALESCE(team_id, (SELECT team_id FROM players WHERE players.id = player_goals.player_id), ?),
            season_id = COALESCE(season_id, (SELECT season_id FROM players WHERE players.id = player_goals.player_id), ?)
        """,
        (team_id, season_id),
    )
    conn.execute(
        """
        UPDATE coaching_match_summaries
        SET team_id = COALESCE(team_id, (SELECT team_id FROM matches WHERE matches.id = coaching_match_summaries.match_id), ?)
        """,
        (team_id,),
    )


def _migrate_v14(conn: sqlite3.Connection):
    """Add Phase 1 team/season tenancy tables, columns, and default backfill."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            game_format TEXT NOT NULL DEFAULT 'full',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seasons (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            name TEXT NOT NULL,
            starts_on TEXT,
            ends_on TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seasons_team ON seasons(team_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_user_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(team_id, user_id, role)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_user_memberships_user ON team_user_memberships(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_user_memberships_team ON team_user_memberships(team_id)")

    _add_column_if_missing(conn, "users", "last_team_id", "TEXT")
    for table in [
        "matches", "players", "player_user_links", "coaching_notes", "coaching_clips",
        "coaching_playlists", "player_goals", "coaching_match_summaries",
    ]:
        _add_column_if_missing(conn, table, "team_id", "TEXT")
    for table in ["matches", "players", "coaching_notes", "coaching_playlists", "player_goals"]:
        _add_column_if_missing(conn, table, "season_id", "TEXT")

    _backfill_default_scope(conn)


def _migrate_v15(conn: sqlite3.Connection):
    """Enforce PR 1.3 non-null tenant scope contract and tenant indexes."""
    _backfill_default_scope(conn)

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
        _rebuild_table_with_not_null_text_columns(conn, table, columns)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_team ON matches(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_team_season ON matches(team_id, season_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_players_team_season ON players(team_id, season_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_user_links_team ON player_user_links(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_user_links_team_player ON player_user_links(team_id, player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_notes_team ON coaching_notes(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_notes_team_match ON coaching_notes(team_id, match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_clips_team ON coaching_clips(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_clips_team_match ON coaching_clips(team_id, match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_playlists_team ON coaching_playlists(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_playlists_team_season ON coaching_playlists(team_id, season_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goals_team ON player_goals(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_goals_team_player ON player_goals(team_id, player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_match_summaries_team ON coaching_match_summaries(team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coaching_match_summaries_team_match ON coaching_match_summaries(team_id, match_id)")


def _migrate_v16(conn: sqlite3.Connection):
    """Add active season persistence for Phase 4 scope selection."""
    _add_column_if_missing(conn, "users", "last_season_id", "TEXT")


def _migrate_v17(conn: sqlite3.Connection):
    """Add durable background job rows for Phase 6.3 in-process workers."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_version INTEGER NOT NULL DEFAULT 1,
            idempotency_key TEXT,
            team_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            scheduled_at TEXT NOT NULL,
            locked_until TEXT,
            locked_by TEXT,
            last_heartbeat TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_text TEXT,
            result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_due ON background_jobs(status, scheduled_at) WHERE status = 'pending'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease ON background_jobs(status, locked_until) WHERE status = 'running'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_team ON background_jobs(team_id, status)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON background_jobs(team_id, kind, idempotency_key) WHERE idempotency_key IS NOT NULL")


def _migrate_v18(conn: sqlite3.Connection):
    """Add per-team settings rows for AI governance and coaching defaults."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_settings (
            team_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT,
            PRIMARY KEY (team_id, key)
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_team_settings_team_key ON team_settings(team_id, key)")


def _migrate_v19(conn: sqlite3.Connection):
    """Add Phase 8.1 team-scoped AI drafting run audit rows."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_drafting_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL,
            season_id TEXT,
            created_by_user_id TEXT,
            draft_target TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            input_tokens INTEGER,
            output_tokens INTEGER,
            error_code TEXT,
            error_message TEXT,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            background_job_id INTEGER,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(background_job_id) REFERENCES background_jobs(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_drafting_runs_team_status "
        "ON ai_drafting_runs(team_id, status, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_drafting_runs_team_created "
        "ON ai_drafting_runs(team_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_drafting_runs_background_job "
        "ON ai_drafting_runs(background_job_id) WHERE background_job_id IS NOT NULL"
    )


def _migrate_v20(conn: sqlite3.Connection):
    """Add Phase 9.1 companion user profile rows."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            email TEXT,
            normalized_email TEXT,
            email_verified_at TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            timezone TEXT,
            locale TEXT,
            preferred_contact_method TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_normalized_email "
        "ON user_profiles(normalized_email) WHERE normalized_email IS NOT NULL"
    )


def _migrate_v21(conn: sqlite3.Connection):
    """Add durable hashed session and password reset token tables."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            user_agent TEXT,
            ip_address TEXT,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            revoked_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id, revoked_at, expires_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id, used_at, expires_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_user ON email_verification_tokens(user_id, used_at, expires_at)")


def _migrate_v22(conn: sqlite3.Connection):
    """Add team invitation tokens for member onboarding."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_invites (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            season_id TEXT,
            normalized_email TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            token_hash TEXT NOT NULL UNIQUE,
            expires_at REAL NOT NULL,
            accepted_at REAL,
            revoked_at REAL,
            created_at REAL NOT NULL,
            created_by_user_id TEXT,
            accepted_by_user_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(team_id) REFERENCES teams(id),
            FOREIGN KEY(season_id) REFERENCES seasons(id),
            FOREIGN KEY(created_by_user_id) REFERENCES users(id),
            FOREIGN KEY(accepted_by_user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_invites_team_status ON team_invites(team_id, status, expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_invites_email ON team_invites(normalized_email, status)")


_MIGRATIONS = [
    _migrate_v0, _migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4,
    _migrate_v5, _migrate_v6, _migrate_v7, _migrate_v8, _migrate_v9,
    _migrate_v10, _migrate_v11, _migrate_v12, _migrate_v13, _migrate_v14,
    _migrate_v15, _migrate_v16, _migrate_v17, _migrate_v18, _migrate_v19,
    _migrate_v20, _migrate_v21, _migrate_v22,
]


def _run_migrations(conn: sqlite3.Connection):
    """Apply any pending schema migrations."""
    current = _get_schema_version(conn)
    for version, migrate_fn in enumerate(_MIGRATIONS):
        if version > current:
            migrate_fn(conn)
            logger.info("Applied schema migration v%d", version)
    if len(_MIGRATIONS) - 1 > current:
        _set_schema_version(conn, len(_MIGRATIONS) - 1)
        conn.commit()


# ---------------------------------------------------------------------------
# Match helpers
# ---------------------------------------------------------------------------

def generate_slug(home_team: str, away_team: str, date: str) -> str:
    """Generate a URL-friendly slug from team names and date."""
    parts = [home_team or "home", "vs", away_team or "away"]
    if date:
        parts.append(date)
    raw = "-".join(parts)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").lower()
    return slug or "match"


def ensure_unique_slug(conn: sqlite3.Connection, slug: str, exclude_id: str | None = None) -> str:
    """Return a unique slug, appending -2, -3, etc. if needed."""
    candidate = slug
    counter = 2
    while True:
        row = conn.execute("SELECT id FROM matches WHERE slug = ?", (candidate,)).fetchone()
        if row is None or (exclude_id and row["id"] == exclude_id):
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1


def row_to_match(row: sqlite3.Row) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    result = {
        "id": row["id"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "date": row["date"] or "",
        "time": row["time"] or "",
        "location": row["location"] or "",
        "score_home": row["score_home"],
        "score_away": row["score_away"],
        "format": row["format"] or "full",
        "videos": json.loads(row["videos_json"] or "{}"),
        "video_status": json.loads(row["video_status_json"] or "{}"),
        "home_logo": row["home_logo"],
        "away_logo": row["away_logo"],
        "created_at": row["created_at"] or "",
        "slug": row["slug"] or "",
        "updated_at": row["updated_at"] or "",
    }
    if "team_id" in keys:
        result["team_id"] = row["team_id"]
    if "season_id" in keys:
        result["season_id"] = row["season_id"]
    return result


def upsert_match(conn: sqlite3.Connection, match: dict):
    team_id = match.get("team_id") or get_default_team(conn=conn)["id"]
    season_id = match.get("season_id") or get_default_season(team_id, conn=conn)["id"]
    conn.execute(
        """
        INSERT INTO matches (
            id, home_team, away_team, date, time, location, score_home, score_away,
            format, videos_json, video_status_json, home_logo, away_logo, created_at, slug,
            updated_at, team_id, season_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            home_team=excluded.home_team,
            away_team=excluded.away_team,
            date=excluded.date,
            time=excluded.time,
            location=excluded.location,
            score_home=excluded.score_home,
            score_away=excluded.score_away,
            format=excluded.format,
            videos_json=excluded.videos_json,
            video_status_json=excluded.video_status_json,
            home_logo=excluded.home_logo,
            away_logo=excluded.away_logo,
            created_at=excluded.created_at,
            slug=excluded.slug,
            updated_at=excluded.updated_at,
            team_id=excluded.team_id,
            season_id=excluded.season_id
        """,
        (
            match["id"],
            match.get("home_team", ""),
            match.get("away_team", ""),
            match.get("date", ""),
            match.get("time", ""),
            match.get("location", ""),
            match.get("score_home"),
            match.get("score_away"),
            match.get("format", "full"),
            json.dumps(match.get("videos", {})),
            json.dumps(match.get("video_status", {})),
            match.get("home_logo"),
            match.get("away_logo"),
            match.get("created_at", ""),
            match.get("slug", ""),
            match.get("updated_at", ""),
            team_id,
            season_id,
        ),
    )


def load_matches_unlocked(
    limit: int | None = None,
    team_id: str | None = None,
    season_id: str | None = None,
) -> list[dict]:
    with connect() as conn:
        where_clauses = []
        params: list = []
        if team_id:
            where_clauses.append("team_id = ?")
            params.append(team_id)
        if season_id:
            where_clauses.append("season_id = ?")
            params.append(season_id)
        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        if limit is not None:
            rows = conn.execute(
                f"SELECT * FROM matches{where_sql} ORDER BY created_at DESC, id DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM matches{where_sql} ORDER BY created_at DESC, id DESC",
                params,
            ).fetchall()
        return [row_to_match(row) for row in rows]


def search_matches(
    q: str | None = None,
    page: int = 1,
    limit: int = 50,
    team_id: str | None = None,
    season_id: str | None = None,
) -> tuple[list[dict], int]:
    """Search and paginate matches.  Returns (matches, total_count)."""
    with connect() as conn:
        where_clauses = []
        params: list = []
        if q:
            where_clauses.append(
                "(home_team LIKE ? COLLATE NOCASE OR away_team LIKE ? COLLATE NOCASE"
                " OR location LIKE ? COLLATE NOCASE)"
            )
            pattern = f"%{q}%"
            params.extend([pattern, pattern, pattern])
        if team_id:
            where_clauses.append("team_id = ?")
            params.append(team_id)
        if season_id:
            where_clauses.append("season_id = ?")
            params.append(season_id)

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total = conn.execute(f"SELECT COUNT(*) FROM matches{where_sql}", params).fetchone()[0]

        offset = (max(1, page) - 1) * limit
        rows = conn.execute(
            f"SELECT * FROM matches{where_sql} ORDER BY date DESC, created_at DESC, id DESC"
            f" LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [row_to_match(row) for row in rows], total


def save_matches_unlocked(matches: list[dict]):
    with connect() as conn:
        existing_ids = {row["id"] for row in conn.execute("SELECT id FROM matches").fetchall()}
        next_ids = {m["id"] for m in matches}

        for match in matches:
            upsert_match(conn, match)

        removed_ids = existing_ids - next_ids
        if removed_ids:
            for match_id in removed_ids:
                _delete_match_coaching_children(conn, match_id)
            conn.executemany("DELETE FROM matches WHERE id = ?", [(mid,) for mid in removed_ids])

        conn.commit()


def _delete_match_coaching_children(conn: sqlite3.Connection, match_id: str) -> None:
    """Delete coaching rows tied to a match without relying on FK cascades."""
    summary_rows = conn.execute("SELECT id FROM coaching_match_summaries WHERE match_id = ?", (match_id,)).fetchall()
    for row in summary_rows:
        summary_id = row["id"]
        conn.execute("DELETE FROM coaching_match_summary_notes WHERE summary_id = ?", (summary_id,))
        conn.execute("DELETE FROM coaching_match_summary_clips WHERE summary_id = ?", (summary_id,))
        conn.execute("DELETE FROM coaching_match_summary_playlists WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM coaching_match_summaries WHERE match_id = ?", (match_id,))

    clip_rows = conn.execute("SELECT id FROM coaching_clips WHERE match_id = ?", (match_id,)).fetchall()
    for row in clip_rows:
        clip_id = row["id"]
        conn.execute("DELETE FROM coaching_match_summary_clips WHERE clip_id = ?", (clip_id,))
        conn.execute("DELETE FROM coaching_clip_players WHERE clip_id = ?", (clip_id,))
        conn.execute("UPDATE player_goals SET source_clip_id = NULL WHERE source_clip_id = ?", (clip_id,))
    conn.execute("DELETE FROM coaching_clips WHERE match_id = ?", (match_id,))

    note_rows = conn.execute("SELECT id FROM coaching_notes WHERE match_id = ?", (match_id,)).fetchall()
    for row in note_rows:
        note_id = row["id"]
        conn.execute("DELETE FROM coaching_match_summary_notes WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_note_players WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_note_tags WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_playlist_items WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_reviews WHERE note_id = ?", (note_id,))
        conn.execute("UPDATE player_goals SET source_note_id = NULL WHERE source_note_id = ?", (note_id,))
        conn.execute("UPDATE player_goals SET source_playlist_item_note_id = NULL WHERE source_playlist_item_note_id = ?", (note_id,))
    conn.execute("DELETE FROM coaching_notes WHERE match_id = ?", (match_id,))


def delete_match_coaching_children(match_id: str) -> None:
    with connect() as conn:
        _delete_match_coaching_children(conn, match_id)
        conn.commit()


def get_match_by_id(match_id: str) -> dict | None:
    """Single-match lookup — avoids loading all matches for read-only endpoints."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return row_to_match(row) if row else None


def find_match(matches: list[dict], match_id: str) -> dict | None:
    return next((m for m in matches if m["id"] == match_id), None)


def migrate_json_to_sqlite(matches_file: Path):
    """One-time migration from matches.json to SQLite."""
    if not matches_file.exists():
        return
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"]
        if count > 0:
            return

        try:
            matches = json.loads(matches_file.read_text())
        except Exception:
            logger.warning("Could not read matches.json for migration")
            return

        for match in matches:
            if "videos" not in match:
                match["videos"] = {"full": None, "first_half": None, "second_half": None}
            if "video_status" not in match:
                match["video_status"] = {
                    "full": "ready" if match.get("videos", {}).get("full") else "none",
                    "first_half": "ready" if match.get("videos", {}).get("first_half") else "none",
                    "second_half": "ready" if match.get("videos", {}).get("second_half") else "none",
                }
            upsert_match(conn, match)

        conn.commit()
        backup = matches_file.with_suffix(".json.migrated")
        try:
            matches_file.rename(backup)
            logger.info("Migrated matches.json to SQLite and moved source to %s", backup)
        except Exception:
            logger.info("Migrated matches.json to SQLite (source file left in place)")


def backfill_slugs():
    """Generate slugs for any matches that don't have one yet."""
    with connect() as conn:
        rows = conn.execute("SELECT id, home_team, away_team, date FROM matches WHERE slug IS NULL OR slug = ''").fetchall()
        for row in rows:
            slug_base = generate_slug(row["home_team"], row["away_team"], row["date"] or "")
            slug = ensure_unique_slug(conn, slug_base, exclude_id=row["id"])
            conn.execute("UPDATE matches SET slug = ? WHERE id = ?", (slug, row["id"]))
        if rows:
            conn.commit()
            logger.info("Backfilled slugs for %d matches", len(rows))


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def _row_to_user(row: sqlite3.Row) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    result = {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "display_name": row["display_name"] or "",
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if "last_team_id" in keys:
        result["last_team_id"] = row["last_team_id"]
    if "last_season_id" in keys:
        result["last_season_id"] = row["last_season_id"]
    return result


def create_user(username: str, password_hash: str, role: str, display_name: str = "") -> dict:
    import uuid
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    user_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (user_id, username, password_hash, role, display_name, now, now),
        )
        team_id, _season_id = _default_scope(conn)
        _backfill_user_memberships(conn, team_id)
        conn.commit()
    return {"id": user_id, "username": username, "role": role, "display_name": display_name,
            "enabled": True, "created_at": now, "updated_at": now, "last_team_id": None, "last_season_id": None}


def get_user_by_username(username: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


class DuplicateEmailError(ValueError):
    """Raised when a profile email is already assigned to another account."""


_PROFILE_FIELDS = {
    "email",
    "first_name",
    "last_name",
    "phone",
    "timezone",
    "locale",
    "preferred_contact_method",
}


def _normalize_profile_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip()
    return cleaned.lower() or None


def _row_to_profile(row: sqlite3.Row | None, user_id: str) -> dict:
    if row is None:
        return {
            "user_id": user_id,
            "email": None,
            "normalized_email": None,
            "email_verified_at": None,
            "first_name": None,
            "last_name": None,
            "phone": None,
            "timezone": None,
            "locale": None,
            "preferred_contact_method": None,
            "created_at": None,
            "updated_at": None,
        }
    return dict(row)


def public_user_profile(profile: dict) -> dict:
    return {
        "email": profile.get("email"),
        "email_verified_at": profile.get("email_verified_at"),
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "phone": profile.get("phone"),
        "timezone": profile.get("timezone"),
        "locale": profile.get("locale"),
        "preferred_contact_method": profile.get("preferred_contact_method"),
    }


def get_user_profile(user_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_profile(row, user_id)


def upsert_user_profile(user_id: str, fields: dict[str, Any]) -> dict:
    updates = {key: fields[key] for key in _PROFILE_FIELDS if key in fields}
    if "email" in updates:
        email = (updates["email"] or "").strip() or None
        updates["email"] = email
        updates["normalized_email"] = _normalize_profile_email(email)
    now = _now_iso()
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise ValueError("Unknown user")
        existing = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if not updates and existing is not None:
            return dict(existing)
        if not updates:
            updates = {}
        merged = _row_to_profile(existing, user_id)
        previous_normalized_email = merged.get("normalized_email")
        merged.update(updates)
        if "normalized_email" in updates and updates.get("normalized_email") != previous_normalized_email:
            merged["email_verified_at"] = None
        merged["created_at"] = merged.get("created_at") or now
        merged["updated_at"] = now
        try:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    user_id, email, normalized_email, email_verified_at, first_name, last_name,
                    phone, timezone, locale, preferred_contact_method, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email = excluded.email,
                    normalized_email = excluded.normalized_email,
                    email_verified_at = excluded.email_verified_at,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    phone = excluded.phone,
                    timezone = excluded.timezone,
                    locale = excluded.locale,
                    preferred_contact_method = excluded.preferred_contact_method,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    merged.get("email"),
                    merged.get("normalized_email"),
                    merged.get("email_verified_at"),
                    merged.get("first_name"),
                    merged.get("last_name"),
                    merged.get("phone"),
                    merged.get("timezone"),
                    merged.get("locale"),
                    merged.get("preferred_contact_method"),
                    merged.get("created_at"),
                    merged.get("updated_at"),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "user_profiles.normalized_email" in str(exc) or "idx_user_profiles_normalized_email" in str(exc):
                raise DuplicateEmailError(str(exc)) from exc
            raise
        conn.commit()
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_profile(row, user_id)


def create_user_session(user_id: str, token_hash: str, *, ttl: float, user_agent: str = "", ip_address: str = "") -> dict:
    now = time.time()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (user_id, token_hash, user_agent, ip_address, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (user_id, token_hash, user_agent, ip_address, now, now + ttl),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(row)


def get_active_session_by_hash(token_hash: str) -> dict | None:
    now = time.time()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, u.username, u.role, u.enabled
            FROM user_sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        session = dict(row)
        if session.get("revoked_at") is not None or float(session["expires_at"]) <= now or not bool(session.get("enabled")):
            return None
        return session


def revoke_session_by_hash(token_hash: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE user_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE token_hash = ?",
            (time.time(), token_hash),
        )
        conn.commit()


def revoke_user_sessions(user_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE user_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE user_id = ? AND revoked_at IS NULL",
            (time.time(), user_id),
        )
        conn.commit()


def create_password_reset_token(user_id: str, token_hash: str, *, ttl: float) -> dict:
    now = time.time()
    with connect() as conn:
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)",
            (user_id, token_hash, now, now + ttl),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(row)


def consume_password_reset_token(token_hash: str) -> dict | None:
    now = time.time()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT prt.*, u.enabled
            FROM password_reset_tokens AS prt
            JOIN users AS u ON u.id = prt.user_id
            WHERE prt.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        token = dict(row)
        if token.get("used_at") is not None or float(token["expires_at"]) <= now or not bool(token.get("enabled")):
            return None
        conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now, token["id"]))
        conn.commit()
        return token


def create_email_verification_token(user_id: str, token_hash: str, email: str, *, ttl: float) -> dict:
    now = time.time()
    with connect() as conn:
        conn.execute(
            "INSERT INTO email_verification_tokens (user_id, token_hash, email, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (user_id, token_hash, email, now, now + ttl),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM email_verification_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(row)


def consume_email_verification_token(token_hash: str) -> dict | None:
    now = time.time()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT evt.*, u.enabled
            FROM email_verification_tokens AS evt
            JOIN users AS u ON u.id = evt.user_id
            WHERE evt.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        token = dict(row)
        if token.get("used_at") is not None or float(token["expires_at"]) <= now or not bool(token.get("enabled")):
            return None
        conn.execute("UPDATE email_verification_tokens SET used_at = ? WHERE id = ?", (now, token["id"]))
        conn.execute(
            "UPDATE user_profiles SET email_verified_at = ?, updated_at = ? WHERE user_id = ? AND normalized_email = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), token["user_id"], _normalize_profile_email(token["email"])),
        )
        conn.commit()
        return token


def user_has_team_membership(user_id: str, team_id: str | None) -> bool:
    if team_id is None:
        return bool(get_user_by_id(user_id))
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM team_user_memberships WHERE user_id = ? AND team_id = ? LIMIT 1",
            (user_id, team_id),
        ).fetchone()
        return row is not None


def user_has_coach_membership(user_id: str | None) -> bool:
    """Return True when the user has a team_user_memberships row with a role
    that grants coach-level access on any team.

    Used by privacy/visibility helpers and the SPA nav gate to detect
    "this user is a coach somewhere" without relying on the legacy
    ``users.role`` column — which never updates when a user is invited
    as a coach via the team membership system and stays at e.g.
    ``viewer``. Membership roles considered: ``coach``, ``team_admin``.
    Global admins are intentionally NOT inferred here; their privileged
    status comes from the legacy ``users.role='admin'`` check upstream.
    """
    if not user_id:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM team_user_memberships WHERE user_id = ? AND role IN ('coach', 'team_admin') LIMIT 1",
            (user_id,),
        ).fetchone()
        return row is not None


def list_users(team_id: str | None = None, *, allow_unscoped: bool = False) -> list[dict]:
    _require_team_scope_for_strict("list_users", team_id, allow_unscoped=allow_unscoped)
    with connect() as conn:
        if team_id is not None:
            rows = conn.execute(
                """
                SELECT DISTINCT users.*
                FROM users
                JOIN team_user_memberships tum ON tum.user_id = users.id
                WHERE tum.team_id = ?
                ORDER BY users.created_at ASC
                """,
                (team_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [_row_to_user(r) for r in rows]


def update_user(user_id: str, **fields) -> bool:
    allowed = {"username", "password_hash", "role", "display_name", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    updates["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]
    with connect() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        conn.commit()
    return True


def delete_user(user_id: str) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM player_user_links WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM coaching_reviews WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


def set_user_active_scope(user_id: str, team_id: str, season_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET last_team_id = ?, last_season_id = ?, updated_at = ? WHERE id = ?",
            (team_id, season_id, _now_iso(), user_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Coaching helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_default_team(*, conn: sqlite3.Connection | None = None) -> dict:
    """Return the single-team default team, creating it if needed."""
    own_conn = conn is None
    db_conn = conn or connect()
    _ensure_default_team_and_season(db_conn)
    row = db_conn.execute("SELECT * FROM teams WHERE slug = 'default-team'").fetchone()
    if own_conn:
        db_conn.commit()
    return dict(row)


def get_default_season(team_id: str | None = None, *, conn: sqlite3.Connection | None = None) -> dict:
    """Return the default season for a team, creating it if needed."""
    own_conn = conn is None
    db_conn = conn or connect()
    default_team_id, _ = _ensure_default_team_and_season(db_conn)
    resolved_team_id = team_id or default_team_id
    row = db_conn.execute(
        "SELECT * FROM seasons WHERE team_id = ? AND name = 'Default Season' ORDER BY created_at ASC, id ASC LIMIT 1",
        (resolved_team_id,),
    ).fetchone()
    if row is None and resolved_team_id != default_team_id:
        now = _now_iso()
        season_id = f"{resolved_team_id}-default-season"
        db_conn.execute(
            "INSERT OR IGNORE INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, 'Default Season', '', '', ?)",
            (season_id, resolved_team_id, now),
        )
        row = db_conn.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if own_conn:
        db_conn.commit()
    return dict(row)


def list_user_memberships(user_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM team_user_memberships WHERE user_id = ? ORDER BY team_id, role",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def _default_scope(conn: sqlite3.Connection) -> tuple[str, str]:
    team = get_default_team(conn=conn)
    season = get_default_season(team["id"], conn=conn)
    return team["id"], season["id"]


def _resolve_note_scope(
    conn: sqlite3.Connection,
    *,
    match_id: str | None,
    note_context: str,
    player_ids: list[str] | None = None,
    team_id: str | None = None,
    season_id: str | None = None,
) -> tuple[str, str | None]:
    default_team_id, default_season_id = _default_scope(conn)
    match_row = None
    if match_id:
        match_row = conn.execute("SELECT team_id, season_id FROM matches WHERE id = ?", (match_id,)).fetchone()
    player_row = None
    if player_ids:
        player_row = conn.execute("SELECT team_id, season_id FROM players WHERE id = ?", (player_ids[0],)).fetchone()
    resolved_team_id = (
        team_id
        or (match_row["team_id"] if match_row and match_row["team_id"] else None)
        or (player_row["team_id"] if player_row and player_row["team_id"] else None)
        or default_team_id
    )
    if note_context == "observation":
        resolved_season_id = (
            season_id
            or (match_row["season_id"] if match_row and match_row["season_id"] else None)
            or (player_row["season_id"] if player_row and player_row["season_id"] else None)
            or default_season_id
        )
    else:
        resolved_season_id = season_id
    return resolved_team_id, resolved_season_id


def _row_to_player(row: sqlite3.Row, links: list[dict] | None = None) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "jersey_number": row["jersey_number"] or "",
        "active": bool(row["active"]),
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "team_id": row["team_id"] if "team_id" in keys else "",
        "season_id": row["season_id"] if "season_id" in keys else "",
        "links": links or [],
    }


def _links_for_players(conn: sqlite3.Connection, player_ids: list[str]) -> dict[str, list[dict]]:
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        f"""
        SELECT l.id, l.player_id, l.user_id, l.relationship, l.created_at,
               u.username, u.display_name
        FROM player_user_links l
        JOIN users u ON u.id = l.user_id
        WHERE l.player_id IN ({placeholders})
        ORDER BY u.username COLLATE NOCASE
        """,
        player_ids,
    ).fetchall()
    grouped: dict[str, list[dict]] = {pid: [] for pid in player_ids}
    for row in rows:
        grouped.setdefault(row["player_id"], []).append({
            "id": row["id"],
            "player_id": row["player_id"],
            "user_id": row["user_id"],
            "relationship": row["relationship"],
            "created_at": row["created_at"],
            "username": row["username"],
            "display_name": row["display_name"] or "",
        })
    return grouped


def list_players(*, include_inactive: bool = True, team_id: str | None = None, allow_unscoped: bool = False) -> list[dict]:
    _require_team_scope_for_strict("list_players", team_id, allow_unscoped=allow_unscoped)
    with connect() as conn:
        where_parts = [] if include_inactive else ["active = 1"]
        params: list = []
        if team_id is not None:
            where_parts.append("team_id = ?")
            params.append(team_id)
        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        rows = conn.execute(
            f"SELECT * FROM players {where} ORDER BY active DESC, jersey_number + 0 ASC, display_name COLLATE NOCASE",
            params,
        ).fetchall()
        ids = [row["id"] for row in rows]
        links = _links_for_players(conn, ids)
        return [_row_to_player(row, links.get(row["id"], [])) for row in rows]


def player_exists(player_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM players WHERE id = ? LIMIT 1", (player_id,)).fetchone()
        return row is not None


def get_player(player_id: str, team_id: str | None = None, *, allow_unscoped: bool = False) -> dict | None:
    _require_team_scope_for_strict("get_player", team_id, allow_unscoped=allow_unscoped)
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM players WHERE id = ? AND team_id = ?", (player_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if not row:
            return None
        links = _links_for_players(conn, [player_id])
        return _row_to_player(row, links.get(player_id, []))


def create_player(display_name: str, jersey_number: str = "", active: bool = True, notes: str = "", *, team_id: str | None = None, season_id: str | None = None) -> dict:
    import uuid
    player_id = str(uuid.uuid4())
    now = _now_iso()
    with connect() as conn:
        default_team_id, default_season_id = _default_scope(conn)
        team_id = team_id or default_team_id
        season_id = season_id or default_season_id
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (player_id, display_name, jersey_number, 1 if active else 0, notes, now, now, team_id, season_id),
        )
        conn.commit()
    return get_player(player_id, team_id=team_id) or {
        "id": player_id, "display_name": display_name, "jersey_number": jersey_number,
        "active": active, "notes": notes, "created_at": now, "updated_at": now,
        "team_id": team_id, "season_id": season_id, "links": [],
    }


def update_player(player_id: str, **fields) -> bool:
    allowed = {"display_name", "jersey_number", "active", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "active" in updates:
        updates["active"] = 1 if updates["active"] else 0
    if not updates:
        return False
    updates["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [player_id]
    with connect() as conn:
        cur = conn.execute(f"UPDATE players SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0


def delete_player(player_id: str) -> bool:
    with connect() as conn:
        goal_rows = conn.execute("SELECT id FROM player_goals WHERE player_id = ?", (player_id,)).fetchall()
        goal_ids = [row["id"] for row in goal_rows]
        if goal_ids:
            placeholders = ",".join("?" for _ in goal_ids)
            conn.execute(f"DELETE FROM player_goal_status_history WHERE goal_id IN ({placeholders})", goal_ids)
            conn.execute(f"DELETE FROM player_goal_reflections WHERE goal_id IN ({placeholders})", goal_ids)
            conn.execute(f"DELETE FROM player_goals WHERE id IN ({placeholders})", goal_ids)
        conn.execute("DELETE FROM player_user_links WHERE player_id = ?", (player_id,))
        conn.execute("DELETE FROM coaching_note_players WHERE player_id = ?", (player_id,))
        conn.execute("DELETE FROM coaching_playlist_players WHERE player_id = ?", (player_id,))
        # Phase 4a (PR #95 review follow-up): clips also link to players
        # via `coaching_clip_players`. SQLite's `ON DELETE CASCADE`
        # declared on that table requires `PRAGMA foreign_keys = ON`,
        # which the rest of this codebase doesn't enable — clean up the
        # join rows explicitly so deleting a player leaves no orphan
        # clip-player references.
        conn.execute("DELETE FROM coaching_clip_players WHERE player_id = ?", (player_id,))
        cur = conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
        conn.commit()
        return cur.rowcount > 0


def link_player_user(player_id: str, user_id: str, relationship: str) -> dict:
    now = _now_iso()
    with connect() as conn:
        player = conn.execute("SELECT team_id FROM players WHERE id = ?", (player_id,)).fetchone()
        team_id = player["team_id"] if player and player["team_id"] else _default_scope(conn)[0]
        conn.execute(
            """
            INSERT INTO player_user_links (player_id, user_id, relationship, created_at, team_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, user_id) DO UPDATE SET relationship = excluded.relationship, team_id = excluded.team_id
            """,
            (player_id, user_id, relationship, now, team_id),
        )
        conn.commit()
    player = get_player(player_id, team_id=team_id)
    return player or {}


def get_player_user_link(link_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM player_user_links WHERE id = ?", (link_id,)).fetchone()
        return dict(row) if row else None


def delete_player_user_link(link_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM player_user_links WHERE id = ?", (link_id,))
        conn.commit()
        return cur.rowcount > 0


def linked_player_ids_for_user(user_id: str | None, team_id: str | None = None, *, allow_unscoped: bool = False) -> list[str]:
    _require_team_scope_for_strict("linked_player_ids_for_user", team_id, allow_unscoped=allow_unscoped)
    if not user_id:
        return []
    with connect() as conn:
        if team_id is not None:
            rows = conn.execute(
                "SELECT player_id FROM player_user_links WHERE user_id = ? AND team_id = ?",
                (user_id, team_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT player_id FROM player_user_links WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [row["player_id"] for row in rows]


def _note_child_data(conn: sqlite3.Connection, note_ids: list[int]) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    if not note_ids:
        return {}, {}
    placeholders = ",".join("?" for _ in note_ids)
    players: dict[int, list[str]] = {note_id: [] for note_id in note_ids}
    tags: dict[int, list[str]] = {note_id: [] for note_id in note_ids}
    for row in conn.execute(
        f"SELECT note_id, player_id FROM coaching_note_players WHERE note_id IN ({placeholders})",
        note_ids,
    ).fetchall():
        players.setdefault(row["note_id"], []).append(row["player_id"])
    for row in conn.execute(
        f"SELECT note_id, tag FROM coaching_note_tags WHERE note_id IN ({placeholders}) ORDER BY tag",
        note_ids,
    ).fetchall():
        tags.setdefault(row["note_id"], []).append(row["tag"])
    return players, tags


def _row_to_note(row: sqlite3.Row, player_ids: list[str] | None = None, tags: list[str] | None = None) -> dict:
    try:
        drawing = json.loads(row["drawing_json"] or "{}")
    except Exception:
        drawing = {}
    # Defensively `_row_get` the v9 / v11 columns so existing call sites
    # that mock a sqlite3.Row without those keys (or older snapshots
    # that haven't migrated yet) still get a sane default instead of a
    # KeyError. sqlite3.Row supports `keys()`; mappings support `in`.
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    # Phase 6b (#116) — return type widened to `Any`. `_opt` is used for
    # both string fields and the JSON-encoded `tactical_board_json`
    # blob, so claiming `str` is misleading and a static checker would
    # complain about the JSON callsite.
    def _opt(key: str, default: Any = "") -> Any:
        return row[key] if key in keys else default
    # Phase 6a — observation notes. `tactical_board_json` is stored as
    # text JSON (or NULL); decode defensively so a corrupted blob
    # surfaces as `None` rather than a 500. The rest of the new fields
    # follow the same `_opt` defensive read pattern as the v9 columns.
    raw_board = _opt("tactical_board_json", "") if "tactical_board_json" in keys else ""
    if raw_board:
        try:
            tactical_board = json.loads(raw_board)
        except Exception:
            tactical_board = None
    else:
        tactical_board = None
    return {
        "id": row["id"],
        # match_id / slot / timestamp_seconds are nullable for
        # observation notes (Phase 6a). Existing video notes still
        # carry all three.
        "match_id": row["match_id"],
        "slot": row["slot"],
        "timestamp_seconds": row["timestamp_seconds"],
        "title": row["title"],
        "body": row["body"] or "",
        "category": row["category"],
        "visibility": row["visibility"],
        "drawing": drawing,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "player_ids": player_ids or [],
        "tags": tags or [],
        # Phase 1 structured fields (see _migrate_v9). Present on every
        # note after migration; default to empty / "correction".
        "note_type": _opt("note_type", "correction") or "correction",
        "what_happened": _opt("what_happened", ""),
        "why_it_matters": _opt("why_it_matters", ""),
        "what_to_do_next": _opt("what_to_do_next", ""),
        "player_summary": _opt("player_summary", ""),
        "coach_private_note": _opt("coach_private_note", ""),
        "team_id": _opt("team_id", ""),
        "season_id": _opt("season_id", ""),
        # Phase 6a — observation note fields. `note_context` defaults
        # to 'video' so legacy clients that ignore it keep behaving
        # as before. `tactical_board_json` is None (not {}) when unset.
        "note_context": _opt("note_context", "video") or "video",
        "event_title": _opt("event_title", ""),
        "event_date": _opt("event_date", ""),
        "event_type": _opt("event_type", ""),
        "tactical_board_json": tactical_board,
    }


def list_coaching_notes(match_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if match_id:
            rows = conn.execute(
                "SELECT * FROM coaching_notes WHERE match_id = ? ORDER BY slot, timestamp_seconds, id",
                (match_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM coaching_notes ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        ids = [row["id"] for row in rows]
        players, tags = _note_child_data(conn, ids)
        return [_row_to_note(row, players.get(row["id"], []), tags.get(row["id"], [])) for row in rows]


def get_coaching_note(note_id: int, team_id: str | None = None) -> dict | None:
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM coaching_notes WHERE id = ? AND team_id = ?", (note_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM coaching_notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return None
        players, tags = _note_child_data(conn, [note_id])
        return _row_to_note(row, players.get(note_id, []), tags.get(note_id, []))


def _replace_note_children(conn: sqlite3.Connection, note_id: int, player_ids: list[str], tags: list[str]) -> None:
    conn.execute("DELETE FROM coaching_note_players WHERE note_id = ?", (note_id,))
    conn.execute("DELETE FROM coaching_note_tags WHERE note_id = ?", (note_id,))
    if player_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_note_players (note_id, player_id) VALUES (?, ?)",
            [(note_id, player_id) for player_id in player_ids],
        )
    if tags:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_note_tags (note_id, tag) VALUES (?, ?)",
            [(note_id, tag) for tag in tags],
        )


def create_coaching_note(data: dict, *, actor: str | None = None) -> dict:
    now = _now_iso()
    # Phase 6a — observation notes: match_id / slot / timestamp_seconds
    # may be absent for `note_context == 'observation'`. `.get(...)`
    # returns None which the schema now allows for those columns.
    # `tactical_board_json` is stored as JSON text or NULL.
    board = data.get("tactical_board_json")
    board_json = json.dumps(board) if board is not None else None
    with connect() as conn:
        team_id, season_id = _resolve_note_scope(
            conn,
            match_id=data.get("match_id"),
            note_context=data.get("note_context", "video"),
            player_ids=data.get("player_ids") or [],
            team_id=data.get("team_id"),
            season_id=data.get("season_id"),
        )
        cur = conn.execute(
            """
            INSERT INTO coaching_notes (
                match_id, slot, timestamp_seconds, title, body, category, visibility,
                drawing_json, created_by, created_at, updated_at,
                note_type, what_happened, why_it_matters, what_to_do_next,
                player_summary, coach_private_note,
                note_context, event_title, event_date, event_type, tactical_board_json,
                team_id, season_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("match_id"), data.get("slot"), data.get("timestamp_seconds"),
                data["title"], data.get("body", ""), data.get("category", "other"),
                data.get("visibility", "private"), json.dumps(data.get("drawing") or {}),
                actor, now, now,
                data.get("note_type", "correction"),
                data.get("what_happened", ""),
                data.get("why_it_matters", ""),
                data.get("what_to_do_next", ""),
                data.get("player_summary", ""),
                data.get("coach_private_note", ""),
                data.get("note_context", "video"),
                data.get("event_title", ""),
                data.get("event_date", ""),
                data.get("event_type", ""),
                board_json,
                team_id,
                season_id,
            ),
        )
        note_id = cur.lastrowid
        _replace_note_children(conn, note_id, data.get("player_ids") or [], data.get("tags") or [])
        conn.commit()
    return get_coaching_note(note_id) or {}


def update_coaching_note(note_id: int, data: dict) -> dict | None:
    scalar_allowed = {
        "timestamp_seconds", "title", "body", "category", "visibility",
        # Phase 1 structured-note fields — partial update. Only the keys
        # the request actually sends are written; the rest round-trip
        # untouched.
        "note_type", "what_happened", "why_it_matters", "what_to_do_next",
        "player_summary", "coach_private_note",
        # Phase 6a — observation note fields. `match_id` / `slot` are
        # writable so a coach can flip between video and observation
        # contexts (e.g. attach the note to a match later). The route
        # handler validates the merged state so a video note can't end
        # up with `match_id` cleared but `note_context` still 'video'.
        "match_id", "slot", "note_context", "event_title", "event_date", "event_type",
    }
    # `None` values clear nullable columns (match_id / slot /
    # timestamp_seconds for observation notes). Allow them through for
    # those keys, but for the legacy keys keep the original behavior
    # (skip None so unset PATCH fields don't blank stored text).
    nullable_keys = {"match_id", "slot", "timestamp_seconds"}
    updates = {
        k: v for k, v in data.items()
        if k in scalar_allowed and (v is not None or k in nullable_keys)
    }
    if "drawing" in data and data["drawing"] is not None:
        updates["drawing_json"] = json.dumps(data["drawing"])
    # `tactical_board_json` is the only non-scalar observation field —
    # it's stored as JSON text. Allow explicit None to clear the
    # stored sketch (NULL in the DB).
    if "tactical_board_json" in data:
        board = data["tactical_board_json"]
        updates["tactical_board_json"] = json.dumps(board) if board is not None else None
    # PR #95 review follow-up: a join-table-only PATCH (player_ids /
    # tags only) is still a real edit and must bump `updated_at` so
    # the row surfaces in `ORDER BY updated_at` lists. Compute that
    # flag BEFORE we add `updated_at` to the dict.
    join_changed = "player_ids" in data or "tags" in data
    updates["updated_at"] = _now_iso()
    with connect() as conn:
        # Run the UPDATE if the request changed anything beyond the
        # auto-added `updated_at` (len > 1) OR if a join-table edit
        # happened — both cases need `updated_at` to advance.
        if len(updates) > 1 or join_changed:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [note_id]
            conn.execute(f"UPDATE coaching_notes SET {set_clause} WHERE id = ?", values)
        if join_changed:
            existing = get_coaching_note(note_id) or {}
            _replace_note_children(
                conn,
                note_id,
                data.get("player_ids") if data.get("player_ids") is not None else existing.get("player_ids", []),
                data.get("tags") if data.get("tags") is not None else existing.get("tags", []),
            )
        if len(updates) > 1 or join_changed:
            row = conn.execute("SELECT match_id, note_context, team_id, season_id FROM coaching_notes WHERE id = ?", (note_id,)).fetchone()
            if row:
                player_rows = conn.execute(
                    "SELECT player_id FROM coaching_note_players WHERE note_id = ? ORDER BY player_id",
                    (note_id,),
                ).fetchall()
                scope_inputs_changed = any(key in data for key in ("match_id", "note_context", "player_ids"))
                team_id, season_id = _resolve_note_scope(
                    conn,
                    match_id=row["match_id"],
                    note_context=row["note_context"] or "video",
                    player_ids=[player_row["player_id"] for player_row in player_rows],
                    team_id=None if scope_inputs_changed else row["team_id"],
                    season_id=None if scope_inputs_changed else row["season_id"],
                )
                conn.execute(
                    "UPDATE coaching_notes SET team_id = ?, season_id = ? WHERE id = ?",
                    (team_id, season_id, note_id),
                )
        conn.commit()
    return get_coaching_note(note_id)


def delete_coaching_note(note_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM coaching_note_players WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_note_tags WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_playlist_items WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_reviews WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM coaching_match_summary_notes WHERE note_id = ?", (note_id,))
        # Phase 4a: clips reference notes via `source_note_id`. The
        # column has `ON DELETE SET NULL` declared, but SQLite needs
        # `PRAGMA foreign_keys = ON` for that to fire and the rest of
        # this codebase doesn't enable it (every other related table is
        # cleaned up manually here). Keep that pattern: NULL out the FK
        # explicitly so clips stay valid with their snapshot drawing
        # intact.
        conn.execute(
            "UPDATE coaching_clips SET source_note_id = NULL WHERE source_note_id = ?",
            (note_id,),
        )
        conn.execute(
            "UPDATE player_goals SET source_note_id = NULL WHERE source_note_id = ?",
            (note_id,),
        )
        conn.execute(
            "UPDATE player_goals SET source_playlist_item_note_id = NULL WHERE source_playlist_item_note_id = ?",
            (note_id,),
        )
        cur = conn.execute("DELETE FROM coaching_notes WHERE id = ?", (note_id,))
        conn.commit()
        return cur.rowcount > 0


def _playlist_child_data(conn: sqlite3.Connection, playlist_ids: list[int]) -> tuple[dict[int, list[int]], dict[int, list[str]]]:
    if not playlist_ids:
        return {}, {}
    placeholders = ",".join("?" for _ in playlist_ids)
    items: dict[int, list[int]] = {playlist_id: [] for playlist_id in playlist_ids}
    players: dict[int, list[str]] = {playlist_id: [] for playlist_id in playlist_ids}
    for row in conn.execute(
        f"SELECT playlist_id, note_id FROM coaching_playlist_items WHERE playlist_id IN ({placeholders}) ORDER BY position",
        playlist_ids,
    ).fetchall():
        items.setdefault(row["playlist_id"], []).append(row["note_id"])
    for row in conn.execute(
        f"SELECT playlist_id, player_id FROM coaching_playlist_players WHERE playlist_id IN ({placeholders})",
        playlist_ids,
    ).fetchall():
        players.setdefault(row["playlist_id"], []).append(row["player_id"])
    return items, players


def _row_to_playlist(row: sqlite3.Row, note_ids: list[int] | None = None, player_ids: list[str] | None = None) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"] or "",
        "visibility": row["visibility"],
        "pre_roll_seconds": row["pre_roll_seconds"],
        "post_roll_seconds": row["post_roll_seconds"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "team_id": row["team_id"] if "team_id" in keys else "",
        "season_id": row["season_id"] if "season_id" in keys else "",
        "note_ids": note_ids or [],
        "player_ids": player_ids or [],
    }


def list_coaching_playlists() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM coaching_playlists ORDER BY updated_at DESC, id DESC").fetchall()
        ids = [row["id"] for row in rows]
        items, players = _playlist_child_data(conn, ids)
        return [_row_to_playlist(row, items.get(row["id"], []), players.get(row["id"], [])) for row in rows]


def get_coaching_playlist(playlist_id: int, team_id: str | None = None) -> dict | None:
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM coaching_playlists WHERE id = ? AND team_id = ?", (playlist_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM coaching_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not row:
            return None
        items, players = _playlist_child_data(conn, [playlist_id])
        return _row_to_playlist(row, items.get(playlist_id, []), players.get(playlist_id, []))


def _replace_playlist_children(conn: sqlite3.Connection, playlist_id: int, note_ids: list[int], player_ids: list[str]) -> None:
    conn.execute("DELETE FROM coaching_playlist_items WHERE playlist_id = ?", (playlist_id,))
    conn.execute("DELETE FROM coaching_playlist_players WHERE playlist_id = ?", (playlist_id,))
    if note_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_playlist_items (playlist_id, note_id, position) VALUES (?, ?, ?)",
            [(playlist_id, note_id, idx) for idx, note_id in enumerate(note_ids)],
        )
    if player_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_playlist_players (playlist_id, player_id) VALUES (?, ?)",
            [(playlist_id, player_id) for player_id in player_ids],
        )


def create_coaching_playlist(data: dict, *, actor: str | None = None) -> dict:
    now = _now_iso()
    with connect() as conn:
        team_id, season_id = _default_scope(conn)
        cur = conn.execute(
            """
            INSERT INTO coaching_playlists (
                title, description, visibility, pre_roll_seconds, post_roll_seconds,
                created_by, created_at, updated_at, team_id, season_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["title"], data.get("description", ""), data.get("visibility", "private"),
                data.get("pre_roll_seconds", 5.0), data.get("post_roll_seconds", 8.0),
                actor, now, now, data.get("team_id") or team_id, data.get("season_id") or season_id,
            ),
        )
        playlist_id = cur.lastrowid
        _replace_playlist_children(conn, playlist_id, data.get("note_ids") or [], data.get("player_ids") or [])
        conn.commit()
    return get_coaching_playlist(playlist_id) or {}


def update_coaching_playlist(playlist_id: int, data: dict) -> dict | None:
    scalar_allowed = {"title", "description", "visibility", "pre_roll_seconds", "post_roll_seconds"}
    updates = {k: v for k, v in data.items() if k in scalar_allowed and v is not None}
    updates["updated_at"] = _now_iso()
    with connect() as conn:
        if len(updates) > 1:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [playlist_id]
            conn.execute(f"UPDATE coaching_playlists SET {set_clause} WHERE id = ?", values)
        if "note_ids" in data or "player_ids" in data:
            existing = get_coaching_playlist(playlist_id) or {}
            _replace_playlist_children(
                conn,
                playlist_id,
                data.get("note_ids") if data.get("note_ids") is not None else existing.get("note_ids", []),
                data.get("player_ids") if data.get("player_ids") is not None else existing.get("player_ids", []),
            )
        conn.commit()
    return get_coaching_playlist(playlist_id)


def delete_coaching_playlist(playlist_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM coaching_playlist_items WHERE playlist_id = ?", (playlist_id,))
        conn.execute("DELETE FROM coaching_playlist_players WHERE playlist_id = ?", (playlist_id,))
        conn.execute("DELETE FROM coaching_reviews WHERE playlist_id = ?", (playlist_id,))
        conn.execute("DELETE FROM coaching_match_summary_playlists WHERE playlist_id = ?", (playlist_id,))
        conn.execute(
            "UPDATE player_goals SET source_playlist_id = NULL, source_playlist_item_note_id = NULL WHERE source_playlist_id = ?",
            (playlist_id,),
        )
        cur = conn.execute("DELETE FROM coaching_playlists WHERE id = ?", (playlist_id,))
        conn.commit()
        return cur.rowcount > 0


def mark_coaching_review(user_id: str, note_id: int | None, playlist_id: int | None, reflection: str = "") -> dict:
    now = _now_iso()
    with connect() as conn:
        if note_id is not None:
            existing = conn.execute(
                "SELECT id FROM coaching_reviews WHERE user_id = ? AND note_id = ?",
                (user_id, note_id),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM coaching_reviews WHERE user_id = ? AND playlist_id = ?",
                (user_id, playlist_id),
            ).fetchone()
        if existing:
            conn.execute(
                "UPDATE coaching_reviews SET reflection = ?, reviewed_at = ? WHERE id = ?",
                (reflection, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO coaching_reviews (user_id, note_id, playlist_id, reflection, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, note_id, playlist_id, reflection, now),
            )
        conn.commit()
    return {"user_id": user_id, "note_id": note_id, "playlist_id": playlist_id, "reflection": reflection, "reviewed_at": now}


def list_coaching_reviews(user_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM coaching_reviews WHERE user_id = ? ORDER BY reviewed_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM coaching_reviews ORDER BY reviewed_at DESC").fetchall()
        return [dict(row) for row in rows]


def coaching_source_exists(ref_type: str, ref_id: int) -> bool:
    tables = {
        "note": "coaching_notes",
        "clip": "coaching_clips",
        "playlist": "coaching_playlists",
        "goal": "player_goals",
        "match_summary": "coaching_match_summaries",
    }
    table = tables.get(ref_type)
    if table is None:
        return False
    with connect() as conn:
        row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (ref_id,)).fetchone()
        return row is not None


def get_coaching_review_for_ai_context(review_id: int, team_id: str) -> dict | None:
    """Return compact review metadata scoped by source team, excluding reflection text."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.note_id, r.playlist_id, r.reviewed_at
            FROM coaching_reviews r
            LEFT JOIN coaching_notes n ON n.id = r.note_id
            LEFT JOIN coaching_playlists p ON p.id = r.playlist_id
            WHERE r.id = ? AND (n.team_id = ? OR p.team_id = ?)
            """,
            (review_id, team_id, team_id),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Coaching clips (Phase 4a)
#
# Clips are first-class coaching objects — a saved [start, end] window
# of a match slot, optionally seeded from a note. They use the SAME
# visibility ladder as notes / playlists (private / team / player /
# unlisted) and the SAME `linked_player_ids_for_user` join pattern, so
# `_filter_clips_for_user` in server.py is a thin wrapper over the
# existing logic.
#
# Source-note linkage: `source_note_id` is a nullable FK with
# `ON DELETE SET NULL` — if the source note is deleted the clip stays
# valid (the coach copied the relevant context into the clip's own
# `title` / `description` / `drawing_json` fields at create time).
# ---------------------------------------------------------------------------


def _clip_player_data(conn: sqlite3.Connection, clip_ids: list[int]) -> dict[int, list[str]]:
    """Mirror of `_note_child_data` but only returns the player join.
    Clips don't carry tags, so the second member of that tuple is
    intentionally absent here."""
    if not clip_ids:
        return {}
    placeholders = ",".join("?" for _ in clip_ids)
    players: dict[int, list[str]] = {clip_id: [] for clip_id in clip_ids}
    for row in conn.execute(
        f"SELECT clip_id, player_id FROM coaching_clip_players WHERE clip_id IN ({placeholders})",
        clip_ids,
    ).fetchall():
        players.setdefault(row["clip_id"], []).append(row["player_id"])
    return players


def _row_to_clip(row: sqlite3.Row, player_ids: list[str] | None = None) -> dict:
    try:
        drawing = json.loads(row["drawing_json"] or "{}")
    except Exception:
        drawing = {}
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "id": row["id"],
        "match_id": row["match_id"],
        "slot": row["slot"],
        "start_seconds": row["start_seconds"],
        "end_seconds": row["end_seconds"],
        "duration_seconds": float(row["end_seconds"]) - float(row["start_seconds"]),
        "title": row["title"],
        "description": row["description"] or "",
        "category": row["category"],
        "visibility": row["visibility"],
        "source_note_id": row["source_note_id"],
        "drawing": drawing,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "team_id": row["team_id"] if "team_id" in keys else "",
        "player_ids": player_ids or [],
    }


def list_coaching_clips(match_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if match_id:
            rows = conn.execute(
                "SELECT * FROM coaching_clips WHERE match_id = ? "
                "ORDER BY slot, start_seconds, id",
                (match_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM coaching_clips ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        ids = [row["id"] for row in rows]
        players = _clip_player_data(conn, ids)
        return [_row_to_clip(row, players.get(row["id"], [])) for row in rows]


def get_coaching_clip(clip_id: int, team_id: str | None = None) -> dict | None:
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM coaching_clips WHERE id = ? AND team_id = ?", (clip_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM coaching_clips WHERE id = ?", (clip_id,)).fetchone()
        if not row:
            return None
        players = _clip_player_data(conn, [clip_id])
        return _row_to_clip(row, players.get(clip_id, []))


def _replace_clip_children(conn: sqlite3.Connection, clip_id: int, player_ids: list[str]) -> None:
    conn.execute("DELETE FROM coaching_clip_players WHERE clip_id = ?", (clip_id,))
    if player_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_clip_players (clip_id, player_id) VALUES (?, ?)",
            [(clip_id, player_id) for player_id in player_ids],
        )


def create_coaching_clip(data: dict, *, actor: str | None = None) -> dict:
    now = _now_iso()
    with connect() as conn:
        default_team_id, _default_season_id = _default_scope(conn)
        match_row = conn.execute("SELECT team_id FROM matches WHERE id = ?", (data["match_id"],)).fetchone()
        team_id = data.get("team_id") or (match_row["team_id"] if match_row and match_row["team_id"] else default_team_id)
        cur = conn.execute(
            """
            INSERT INTO coaching_clips (
                match_id, slot, start_seconds, end_seconds, title, description,
                category, visibility, source_note_id, drawing_json,
                created_by, created_at, updated_at, team_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["match_id"], data["slot"],
                float(data["start_seconds"]), float(data["end_seconds"]),
                data["title"], data.get("description", ""),
                data.get("category", "other"), data.get("visibility", "private"),
                data.get("source_note_id"),
                json.dumps(data.get("drawing") or {}),
                actor, now, now, team_id,
            ),
        )
        clip_id = cur.lastrowid
        _replace_clip_children(conn, clip_id, data.get("player_ids") or [])
        conn.commit()
    return get_coaching_clip(clip_id) or {}


def update_coaching_clip(clip_id: int, data: dict) -> dict | None:
    """Partial-update. Mirrors `update_coaching_note` — only the keys the
    request actually sends are written; the rest round-trip untouched.
    `source_note_id` is intentionally NOT updatable (the clip's
    drawing/title were captured from a specific note at create time;
    rebinding to a different source mid-life would silently change the
    visual context). If a coach wants to re-anchor, they delete + recreate."""
    scalar_allowed = {
        "start_seconds", "end_seconds", "title", "description",
        "category", "visibility",
    }
    updates = {k: v for k, v in data.items() if k in scalar_allowed and v is not None}
    if "drawing" in data and data["drawing"] is not None:
        updates["drawing_json"] = json.dumps(data["drawing"])
    # PR #95 review follow-up: a join-table-only PATCH (player_ids only)
    # is still a real edit and must bump `updated_at` so the row
    # surfaces in `ORDER BY updated_at` lists. Compute that flag BEFORE
    # we add `updated_at` to the dict.
    join_changed = "player_ids" in data
    updates["updated_at"] = _now_iso()
    with connect() as conn:
        # Run the UPDATE if the request changed anything beyond the
        # auto-added `updated_at` (len > 1) OR if a join-table edit
        # happened — both cases need `updated_at` to advance.
        if len(updates) > 1 or join_changed:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [clip_id]
            conn.execute(f"UPDATE coaching_clips SET {set_clause} WHERE id = ?", values)
        if join_changed:
            existing = get_coaching_clip(clip_id) or {}
            _replace_clip_children(
                conn,
                clip_id,
                data.get("player_ids") if data.get("player_ids") is not None else existing.get("player_ids", []),
            )
        conn.commit()
    return get_coaching_clip(clip_id)


def delete_coaching_clip(clip_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM coaching_clip_players WHERE clip_id = ?", (clip_id,))
        conn.execute("DELETE FROM coaching_match_summary_clips WHERE clip_id = ?", (clip_id,))
        conn.execute(
            "UPDATE player_goals SET source_clip_id = NULL WHERE source_clip_id = ?",
            (clip_id,),
        )
        cur = conn.execute("DELETE FROM coaching_clips WHERE id = ?", (clip_id,))
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Player goals (Phase 7)
# ---------------------------------------------------------------------------


def _row_to_goal(row: sqlite3.Row, history: list[dict] | None = None, reflections: list[dict] | None = None) -> dict:
    refl = reflections or []
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "id": row["id"], "player_id": row["player_id"], "title": row["title"] or "",
        "description": row["description"] or "", "context": row["context"] or "next_match",
        "visibility": row["visibility"] or "player", "priority": row["priority"] or "medium",
        "target_date": row["target_date"] or "", "success_criteria": row["success_criteria"] or "",
        "coach_private_note": row["coach_private_note"] or "",
        "status": row["status"] or "open", "source_note_id": row["source_note_id"],
        "source_clip_id": row["source_clip_id"], "source_playlist_id": row["source_playlist_id"],
        "source_playlist_item_note_id": row["source_playlist_item_note_id"], "target_match_id": row["target_match_id"],
        "created_by": row["created_by"] or "", "created_at": row["created_at"], "updated_at": row["updated_at"],
        "team_id": row["team_id"] if "team_id" in keys else "",
        "season_id": row["season_id"] if "season_id" in keys else "",
        "status_history": history or [], "reflections": refl, "latest_reflection": refl[0] if refl else None,
        "needs_coach_follow_up": any(r.get("needs_coach_follow_up") for r in refl),
    }


def _goal_history(conn: sqlite3.Connection, goal_ids: list[int]) -> dict[int, list[dict]]:
    if not goal_ids:
        return {}
    placeholders = ",".join("?" for _ in goal_ids)
    out: dict[int, list[dict]] = {gid: [] for gid in goal_ids}
    rows = conn.execute(f"SELECT * FROM player_goal_status_history WHERE goal_id IN ({placeholders}) ORDER BY changed_at ASC, id ASC", goal_ids).fetchall()
    for row in rows:
        out.setdefault(row["goal_id"], []).append(dict(row))
    return out


def _goal_reflections(conn: sqlite3.Connection, goal_ids: list[int]) -> dict[int, list[dict]]:
    if not goal_ids:
        return {}
    placeholders = ",".join("?" for _ in goal_ids)
    out: dict[int, list[dict]] = {gid: [] for gid in goal_ids}
    rows = conn.execute(f"SELECT * FROM player_goal_reflections WHERE goal_id IN ({placeholders}) ORDER BY updated_at DESC, id DESC", goal_ids).fetchall()
    for row in rows:
        item = dict(row)
        item["needs_coach_follow_up"] = bool(item.get("needs_coach_follow_up"))
        out.setdefault(row["goal_id"], []).append(item)
    return out


def _hydrate_goals(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    ids = [row["id"] for row in rows]
    history = _goal_history(conn, ids)
    reflections = _goal_reflections(conn, ids)
    return [_row_to_goal(row, history.get(row["id"], []), reflections.get(row["id"], [])) for row in rows]


def list_player_goals(player_id: str | None = None, *, statuses: list[str] | None = None) -> list[dict]:
    where: list[str] = []
    params: list = []
    if player_id:
        where.append("player_id = ?")
        params.append(player_id)
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        where.append(f"status IN ({placeholders})")
        params.extend(statuses)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM player_goals{where_sql} ORDER BY updated_at DESC, id DESC", params).fetchall()
        return _hydrate_goals(conn, rows)


def get_player_goal(goal_id: int, team_id: str | None = None) -> dict | None:
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM player_goals WHERE id = ? AND team_id = ?", (goal_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM player_goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return None
        return _hydrate_goals(conn, [row])[0]


def create_player_goal(data: dict, *, actor: str | None = None) -> dict:
    now = _now_iso()
    with connect() as conn:
        default_team_id, default_season_id = _default_scope(conn)
        player_row = conn.execute("SELECT team_id, season_id FROM players WHERE id = ?", (data["player_id"],)).fetchone()
        team_id = data.get("team_id") or (player_row["team_id"] if player_row and player_row["team_id"] else default_team_id)
        season_id = data.get("season_id") or (player_row["season_id"] if player_row and player_row["season_id"] else default_season_id)
        cur = conn.execute(
            """
            INSERT INTO player_goals (player_id, title, description, visibility, priority, target_date,
                success_criteria, coach_private_note, context, status, source_note_id,
                source_clip_id, source_playlist_id, source_playlist_item_note_id, target_match_id, created_by, created_at, updated_at,
                team_id, season_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (data["player_id"], data["title"], data.get("description", ""), data.get("visibility", "player"),
             data.get("priority", "medium"), data.get("target_date", ""), data.get("success_criteria", ""),
             data.get("coach_private_note", ""), data.get("context", "next_match"), data.get("status", "open"),
             data.get("source_note_id"), data.get("source_clip_id"), data.get("source_playlist_id"), data.get("source_playlist_item_note_id"),
             data.get("target_match_id"), actor or "", now, now, team_id, season_id),
        )
        goal_id = cur.lastrowid
        conn.execute("INSERT INTO player_goal_status_history (goal_id, status, changed_by, changed_at) VALUES (?, ?, ?, ?)", (goal_id, data.get("status", "open"), actor or "", now))
        conn.commit()
    return get_player_goal(goal_id)


def update_player_goal(goal_id: int, data: dict, *, actor: str | None = None) -> dict | None:
    existing = get_player_goal(goal_id)
    if not existing:
        return None
    allowed = {"title", "description", "visibility", "priority", "target_date", "success_criteria", "coach_private_note", "context", "status", "source_note_id", "source_clip_id", "source_playlist_id", "source_playlist_item_note_id", "target_match_id"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return existing
    now = _now_iso()
    updates["updated_at"] = now
    with connect() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE player_goals SET {set_clause} WHERE id = ?", list(updates.values()) + [goal_id])
        if "status" in updates and updates["status"] != existing.get("status"):
            conn.execute("INSERT INTO player_goal_status_history (goal_id, status, changed_by, changed_at) VALUES (?, ?, ?, ?)", (goal_id, updates["status"], actor or "", now))
        conn.commit()
    return get_player_goal(goal_id)


def delete_player_goal(goal_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM player_goal_status_history WHERE goal_id = ?", (goal_id,))
        conn.execute("DELETE FROM player_goal_reflections WHERE goal_id = ?", (goal_id,))
        cur = conn.execute("DELETE FROM player_goals WHERE id = ?", (goal_id,))
        conn.commit()
        return cur.rowcount > 0


def add_player_goal_reflection(goal_id: int, user_id: str, reflection: str) -> dict:
    now = _now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO player_goal_reflections (goal_id, user_id, reflection, needs_coach_follow_up, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (goal_id, user_id, reflection, now, now),
        )
        row = conn.execute("SELECT * FROM player_goal_reflections WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.commit()
        item = dict(row)
        item["needs_coach_follow_up"] = bool(item.get("needs_coach_follow_up"))
        return item


# Match-level coaching summaries (Phase 8)
# ---------------------------------------------------------------------------


def _summary_child_data(conn: sqlite3.Connection, summary_ids: list[int]) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[int, list[int]]]:
    if not summary_ids:
        return {}, {}, {}
    placeholders = ",".join("?" for _ in summary_ids)
    notes: dict[int, list[int]] = {summary_id: [] for summary_id in summary_ids}
    clips: dict[int, list[int]] = {summary_id: [] for summary_id in summary_ids}
    playlists: dict[int, list[int]] = {summary_id: [] for summary_id in summary_ids}
    for row in conn.execute(
        f"SELECT summary_id, note_id FROM coaching_match_summary_notes WHERE summary_id IN ({placeholders}) ORDER BY position",
        summary_ids,
    ).fetchall():
        notes.setdefault(row["summary_id"], []).append(row["note_id"])
    for row in conn.execute(
        f"SELECT summary_id, clip_id FROM coaching_match_summary_clips WHERE summary_id IN ({placeholders}) ORDER BY position",
        summary_ids,
    ).fetchall():
        clips.setdefault(row["summary_id"], []).append(row["clip_id"])
    for row in conn.execute(
        f"SELECT summary_id, playlist_id FROM coaching_match_summary_playlists WHERE summary_id IN ({placeholders}) ORDER BY position",
        summary_ids,
    ).fetchall():
        playlists.setdefault(row["summary_id"], []).append(row["playlist_id"])
    return notes, clips, playlists


def _row_to_match_summary(
    row: sqlite3.Row,
    note_ids: list[int] | None = None,
    clip_ids: list[int] | None = None,
    playlist_ids: list[int] | None = None,
) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "id": row["id"],
        "match_id": row["match_id"],
        "visibility": row["visibility"],
        "team_positives": row["team_positives"] or "",
        "team_improvements": row["team_improvements"] or "",
        "training_focus": row["training_focus"] or "",
        "body": row["body"] or "",
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "team_id": row["team_id"] if "team_id" in keys else "",
        "note_ids": note_ids or [],
        "clip_ids": clip_ids or [],
        "playlist_ids": playlist_ids or [],
    }


def list_coaching_match_summaries(match_id: str | None = None) -> list[dict]:
    with connect() as conn:
        if match_id:
            rows = conn.execute(
                "SELECT * FROM coaching_match_summaries WHERE match_id = ? ORDER BY updated_at DESC, id DESC",
                (match_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM coaching_match_summaries ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        ids = [row["id"] for row in rows]
        notes, clips, playlists = _summary_child_data(conn, ids)
        return [
            _row_to_match_summary(row, notes.get(row["id"], []), clips.get(row["id"], []), playlists.get(row["id"], []))
            for row in rows
        ]


def get_coaching_match_summary(summary_id: int, team_id: str | None = None) -> dict | None:
    with connect() as conn:
        if team_id is not None:
            row = conn.execute("SELECT * FROM coaching_match_summaries WHERE id = ? AND team_id = ?", (summary_id, team_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM coaching_match_summaries WHERE id = ?", (summary_id,)).fetchone()
        if not row:
            return None
        notes, clips, playlists = _summary_child_data(conn, [summary_id])
        return _row_to_match_summary(row, notes.get(summary_id, []), clips.get(summary_id, []), playlists.get(summary_id, []))


def _replace_summary_children(
    conn: sqlite3.Connection,
    summary_id: int,
    note_ids: list[int],
    clip_ids: list[int],
    playlist_ids: list[int],
) -> None:
    conn.execute("DELETE FROM coaching_match_summary_notes WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM coaching_match_summary_clips WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM coaching_match_summary_playlists WHERE summary_id = ?", (summary_id,))
    if note_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_match_summary_notes (summary_id, note_id, position) VALUES (?, ?, ?)",
            [(summary_id, note_id, idx) for idx, note_id in enumerate(note_ids)],
        )
    if clip_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_match_summary_clips (summary_id, clip_id, position) VALUES (?, ?, ?)",
            [(summary_id, clip_id, idx) for idx, clip_id in enumerate(clip_ids)],
        )
    if playlist_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO coaching_match_summary_playlists (summary_id, playlist_id, position) VALUES (?, ?, ?)",
            [(summary_id, playlist_id, idx) for idx, playlist_id in enumerate(playlist_ids)],
        )


def create_coaching_match_summary(data: dict, *, actor: str | None = None) -> dict:
    now = _now_iso()
    with connect() as conn:
        default_team_id, _default_season_id = _default_scope(conn)
        match_row = conn.execute("SELECT team_id FROM matches WHERE id = ?", (data["match_id"],)).fetchone()
        team_id = data.get("team_id") or (match_row["team_id"] if match_row and match_row["team_id"] else default_team_id)
        cur = conn.execute(
            """
            INSERT INTO coaching_match_summaries (
                match_id, visibility, team_positives, team_improvements,
                training_focus, body, created_by, created_at, updated_at, team_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["match_id"], data.get("visibility", "private"),
                data.get("team_positives", ""), data.get("team_improvements", ""),
                data.get("training_focus", ""), data.get("body", ""),
                actor, now, now, team_id,
            ),
        )
        summary_id = cur.lastrowid
        _replace_summary_children(
            conn,
            summary_id,
            data.get("note_ids") or [],
            data.get("clip_ids") or [],
            data.get("playlist_ids") or [],
        )
        conn.commit()
    return get_coaching_match_summary(summary_id) or {}


def update_coaching_match_summary(summary_id: int, data: dict) -> dict | None:
    scalar_allowed = {"visibility", "team_positives", "team_improvements", "training_focus", "body"}
    updates = {k: v for k, v in data.items() if k in scalar_allowed and v is not None}
    join_changed = "note_ids" in data or "clip_ids" in data or "playlist_ids" in data
    updates["updated_at"] = _now_iso()
    with connect() as conn:
        if len(updates) > 1 or join_changed:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [summary_id]
            conn.execute(f"UPDATE coaching_match_summaries SET {set_clause} WHERE id = ?", values)
        if join_changed:
            existing = get_coaching_match_summary(summary_id) or {}
            _replace_summary_children(
                conn,
                summary_id,
                data.get("note_ids") if data.get("note_ids") is not None else existing.get("note_ids", []),
                data.get("clip_ids") if data.get("clip_ids") is not None else existing.get("clip_ids", []),
                data.get("playlist_ids") if data.get("playlist_ids") is not None else existing.get("playlist_ids", []),
            )
        conn.commit()
    return get_coaching_match_summary(summary_id)


def delete_coaching_match_summary(summary_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM coaching_match_summary_notes WHERE summary_id = ?", (summary_id,))
        conn.execute("DELETE FROM coaching_match_summary_clips WHERE summary_id = ?", (summary_id,))
        conn.execute("DELETE FROM coaching_match_summary_playlists WHERE summary_id = ?", (summary_id,))
        cur = conn.execute("DELETE FROM coaching_match_summaries WHERE id = ?", (summary_id,))
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Video error helpers
# ---------------------------------------------------------------------------

def log_video_error(
    match_id: str,
    slot: str,
    error_code: str,
    reason: str,
    details: str = "",
) -> int:
    """Insert a video error record and return its ID."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO video_errors (match_id, slot, error_code, reason, details, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (match_id, slot, error_code, reason, details, now),
        )
        conn.commit()
        return cursor.lastrowid


def get_video_errors(
    match_id: str | None = None,
    slot: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return recent video errors, optionally filtered by match/slot."""
    where = []
    params: list = []
    if match_id:
        where.append("match_id = ?")
        params.append(match_id)
    if slot:
        where.append("slot = ?")
        params.append(slot)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM video_errors{where_sql} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "id": r["id"],
                "match_id": r["match_id"],
                "slot": r["slot"],
                "error_code": r["error_code"],
                "reason": r["reason"],
                "details": r["details"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def count_video_errors() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM video_errors").fetchone()[0]


def log_activity_event(
    event_type: str,
    *,
    severity: str = "info",
    message: str = "",
    match_id: str | None = None,
    slot: str | None = None,
    actor: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Insert an admin activity feed event and return its ID."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata_json = json.dumps(metadata or {}, sort_keys=True)
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO activity_events (
                event_type, severity, message, match_id, slot, actor,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                severity,
                message,
                match_id,
                slot,
                actor or "",
                metadata_json,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_activity_events(limit: int = 20, max_age_hours: int | None = 72) -> list[dict]:
    """Return newest activity feed events, optionally limited to recent hours."""
    where_sql = ""
    params: list = []
    if max_age_hours is not None:
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - (max_age_hours * 3600)),
        )
        where_sql = " WHERE created_at >= ?"
        params.append(cutoff)
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM activity_events{where_sql} ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    events = []
    for r in rows:
        try:
            metadata = json.loads(r["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        events.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "severity": r["severity"],
                "message": r["message"],
                "match_id": r["match_id"],
                "slot": r["slot"],
                "actor": r["actor"] or "",
                "metadata": metadata,
                "created_at": r["created_at"],
            }
        )
    return events
