"""Database connection, schema migrations, and match persistence."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import log as _log

logger = _log.setup("replay")

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

def _migrate_v1(conn: sqlite3.Connection):
    """Single squashed schema for the single-team VOD + live-streaming app.

    Greenfield install — no production data and no migration compatibility is
    required, so the historical v0..v26 migration chain (which built up and then
    tore down the coaching / multi-tenant subsystems) has been collapsed into
    one clean CREATE-TABLE pass. Every statement is idempotent (IF NOT EXISTS)
    so a re-run is a no-op.

    Surviving tables: users, user_sessions, matches, video_errors,
    activity_events, background_jobs, settings, settings_audit, upload_sessions.
    Account self-service (user_profiles / password_reset_tokens /
    email_verification_tokens) and the team/season/coaching tables are gone.
    background_jobs keeps its team_id column — the durable queue keys rows by a
    constant team_id="default".
    """
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
            created_at TEXT,
            slug TEXT,
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_slug ON matches(slug)")

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
            updated_at REAL NOT NULL,
            first_chunk_hash TEXT
        )
        """
    )

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_errors_match ON video_errors(match_id)")

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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )

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


_MIGRATIONS = [
    _migrate_v1,
]


def _run_migrations(conn: sqlite3.Connection):
    """Apply any pending schema migrations."""
    current = _get_schema_version(conn)
    target = len(_MIGRATIONS)  # versions are 1-based for the squashed schema
    for offset, migrate_fn in enumerate(_MIGRATIONS):
        version = offset + 1
        if version > current:
            migrate_fn(conn)
            logger.info("Applied schema migration v%d", version)
    if target > current:
        _set_schema_version(conn, target)
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
    return result


def upsert_match(conn: sqlite3.Connection, match: dict):
    conn.execute(
        """
        INSERT INTO matches (
            id, home_team, away_team, date, time, location, score_home, score_away,
            format, videos_json, video_status_json, home_logo, away_logo, created_at, slug,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            updated_at=excluded.updated_at
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
        ),
    )


def load_matches_unlocked(limit: int | None = None) -> list[dict]:
    with connect() as conn:
        if limit is not None:
            rows = conn.execute(
                "SELECT * FROM matches ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM matches ORDER BY created_at DESC, id DESC",
            ).fetchall()
        return [row_to_match(row) for row in rows]


def search_matches(
    q: str | None = None,
    page: int = 1,
    limit: int = 50,
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
            conn.executemany("DELETE FROM matches WHERE id = ?", [(mid,) for mid in removed_ids])

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
    return {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "display_name": row["display_name"] or "",
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
        conn.commit()
    return {"id": user_id, "username": username, "role": role, "display_name": display_name,
            "enabled": True, "created_at": now, "updated_at": now}


def get_user_by_username(username: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


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


def list_users(*, allow_unscoped: bool = False) -> list[dict]:
    # ``allow_unscoped`` is retained for call-site compatibility (the multi-team
    # scoping layer was removed) and is intentionally ignored.
    del allow_unscoped
    with connect() as conn:
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
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def count_enabled_global_admins(exclude_user_id: str | None = None) -> int:
    """Count enabled users with the ``admin`` role.

    Used by the Admin > Users delete/disable last-admin guard.
    """
    sql = (
        "SELECT COUNT(*) AS n FROM users "
        "WHERE enabled = 1 AND (',' || REPLACE(role, ' ', '') || ',') LIKE '%,admin,%'"
    )
    params: list = []
    if exclude_user_id:
        sql += " AND id != ?"
        params.append(exclude_user_id)
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["n"]) if row else 0


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
