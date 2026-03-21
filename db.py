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


_MIGRATIONS = [_migrate_v0, _migrate_v1, _migrate_v2, _migrate_v3]


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
    return {
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
    }


def upsert_match(conn: sqlite3.Connection, match: dict):
    conn.execute(
        """
        INSERT INTO matches (
            id, home_team, away_team, date, time, location, score_home, score_away,
            format, videos_json, video_status_json, home_logo, away_logo, created_at, slug
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            slug=excluded.slug
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
        ),
    )


def load_matches_unlocked() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches ORDER BY created_at DESC, id DESC"
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


def list_users() -> list[dict]:
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
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


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
