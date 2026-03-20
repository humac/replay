"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8090)
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import shutil
import time
import uuid
from pathlib import Path
from threading import Lock

import aiofiles
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

import media as _media
from models import CreateMatchRequest, CreateUploadSessionRequest, LoginRequest, UpdateMatchRequest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("replay")

DATA_DIR = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))
STATIC_DIR = Path(__file__).parent
MATCHES_FILE = DATA_DIR / "matches.json"
DB_FILE = DATA_DIR / "replay.db"
VIDEOS_DIR = DATA_DIR / "videos"
APP_ASSETS_DIR = DATA_DIR / "app_assets"

app = FastAPI(title="Replay")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(12 * 1024 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE_BYTES = int(os.environ.get("UPLOAD_CHUNK_SIZE_BYTES", str(16 * 1024 * 1024)))
TRANSCODE_CONCURRENCY = max(1, int(os.environ.get("TRANSCODE_CONCURRENCY", "2")))
MIN_FREE_DISK_BYTES = int(os.environ.get("MIN_FREE_DISK_BYTES", str(20 * 1024 * 1024 * 1024)))
UPLOAD_DISK_HEADROOM_MULTIPLIER = float(os.environ.get("UPLOAD_DISK_HEADROOM_MULTIPLIER", "2.2"))
STALE_UPLOAD_SESSION_SECONDS = int(os.environ.get("STALE_UPLOAD_SESSION_SECONDS", str(6 * 60 * 60)))
VIDEO_STREAM_CHUNK_BYTES = int(os.environ.get("VIDEO_STREAM_CHUNK_BYTES", str(1024 * 1024)))
HLS_SEGMENT_DURATION = int(os.environ.get("HLS_SEGMENT_DURATION", "6"))
TRANSCODE_SEMAPHORE = asyncio.Semaphore(TRANSCODE_CONCURRENCY)
MATCHES_LOCK = Lock()
HLS_BACKFILL_LOCK = asyncio.Lock()

HLS_VARIANT_PRESETS = [
    {
        "name": "1080p",
        "height": 1080,
        "width": 1920,
        "video_bitrate": "6000k",
        "maxrate": "6800k",
        "bufsize": "12000k",
        "audio_bitrate": "160k",
        "bandwidth": 7000000,
    },
    {
        "name": "720p",
        "height": 720,
        "width": 1280,
        "video_bitrate": "3200k",
        "maxrate": "3600k",
        "bufsize": "7200k",
        "audio_bitrate": "128k",
        "bandwidth": 3800000,
    },
    {
        "name": "480p",
        "height": 480,
        "width": 854,
        "video_bitrate": "1400k",
        "maxrate": "1600k",
        "bufsize": "3200k",
        "audio_bitrate": "128k",
        "bandwidth": 1800000,
    },
]

DEFAULT_APP_SETTINGS = {
    "app_name": "Replay",
    "nav_matches_label": "Matches",
    "nav_add_match_label": "Add Match",
    "nav_settings_label": "Settings",
    "season_title": "U12 GIRLS STEEL",
    "season_intro": "Missed a game? You can find all our match replays right here! (Subject to my attendance and the battery life of my camera.)",
    "main_team_name": "OSU Steel",
    "filter_all_label": "All Matches",
    "filter_home_label": "Home",
    "filter_away_label": "Away",
    "stat_matches_label": "Matches",
    "stat_ready_label": "Ready",
    "stat_processing_label": "Processing",
    "game_back_label": "Back to Matches",
    "game_replay_label": "Match Replay",
    "game_video_status_label": "Video Status",
    "download_label": "Download",
    "downloads_enabled": "1",
    "app_logo_filename": "",
    "favicon_filename": "",
}

EDITABLE_APP_SETTING_KEYS = {
    key for key in DEFAULT_APP_SETTINGS.keys()
    if key not in {"app_logo_filename", "favicon_filename"}
}

APP_ASSET_CONFIG = {
    "logo": {
        "setting_key": "app_logo_filename",
        "allowed_exts": {".png", ".jpg", ".jpeg", ".svg", ".webp"},
        "max_size": 20 * 1024 * 1024,
    },
    "favicon": {
        "setting_key": "favicon_filename",
        "allowed_exts": {".ico", ".png", ".svg"},
        "max_size": 5 * 1024 * 1024,
    },
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _load_settings_unlocked() -> dict[str, str]:
    settings = DEFAULT_APP_SETTINGS.copy()
    with _db_connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def _save_settings_unlocked(updates: dict[str, str]) -> dict[str, str]:
    if not updates:
        return _load_settings_unlocked()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _db_connect() as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            [(key, value, now) for key, value in updates.items()],
        )
        conn.commit()
    return _load_settings_unlocked()


def _load_settings() -> dict[str, str]:
    with MATCHES_LOCK:
        return _load_settings_unlocked()


def _save_settings(updates: dict[str, str]) -> dict[str, str]:
    with MATCHES_LOCK:
        return _save_settings_unlocked(updates)


def _versioned_static_path(filename: str) -> str:
    return f"/static/{filename}?v={_asset_version(filename)}"


def _app_asset_url(kind: str, settings: dict[str, str] | None = None) -> str:
    settings = settings or _load_settings()
    config = APP_ASSET_CONFIG[kind]
    filename = settings.get(config["setting_key"], "")
    if filename:
        asset_path = APP_ASSETS_DIR / filename
        if asset_path.is_file():
            return f"/api/app-assets/{kind}?v={asset_path.stat().st_mtime_ns}"
    if kind == "logo":
        return _versioned_static_path("logo.png")
    return _versioned_static_path("logo.png")


def _public_settings_payload() -> dict:
    settings = _load_settings()
    return {
        "settings": settings,
        "assets": {
            "logo_url": _app_asset_url("logo", settings),
            "favicon_url": _app_asset_url("favicon", settings),
        },
    }


def _normalize_setting_value(key: str, value) -> str:
    if value is None:
        return DEFAULT_APP_SETTINGS.get(key, "")
    if key == "downloads_enabled":
        if isinstance(value, bool):
            return "1" if value else "0"
        return "1" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "0"
    return str(value).strip()


def _asset_version(filename: str) -> str:
    path = STATIC_DIR / filename
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return "0"


def _render_index_html() -> str:
    html = (STATIC_DIR / "index.html").read_text()
    settings_payload = _public_settings_payload()
    app_name = html_lib.escape(settings_payload["settings"]["app_name"] or DEFAULT_APP_SETTINGS["app_name"])
    favicon_url = html_lib.escape(settings_payload["assets"]["favicon_url"], quote=True)
    html = re.sub(r'/static/styles\.css(?:\?v=[^"\']*)?', _versioned_static_path("styles.css"), html)
    html = re.sub(r'/static/script\.js(?:\?v=[^"\']*)?', _versioned_static_path("script.js"), html)
    html = re.sub(r'/static/logo\.png(?:\?v=[^"\']*)?', _app_asset_url("logo", settings_payload["settings"]), html)
    html = re.sub(r"<title>.*?</title>", f"<title>{app_name}</title>", html, count=1)
    favicon_link = f'<link rel="icon" href="{favicon_url}">'
    if 'rel="icon"' in html:
        html = re.sub(r'<link rel="icon"[^>]*>', favicon_link, html, count=1)
    else:
        html = html.replace("</head>", f"    {favicon_link}\n</head>")
    bootstrap = "<script>window.__APP_SETTINGS__ = " + json.dumps(settings_payload).replace("</", "<\\/") + ";</script>"
    if "window.__APP_SETTINGS__" not in html:
        html = html.replace("</head>", f"    {bootstrap}\n</head>")
    return html


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

import threading as _threading
_thread_local = _threading.local()


def _db_connect() -> sqlite3.Connection:
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


def _close_thread_db():
    """Close the thread-local DB connection (used by tests)."""
    conn = getattr(_thread_local, "db_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _thread_local.db_conn = None


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Return current schema version, or -1 if the version table doesn't exist."""
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else -1
    except sqlite3.OperationalError:
        return -1


def _set_schema_version(conn: sqlite3.Connection, version: int):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


# -- Migrations ---------------------------------------------------------------

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


_MIGRATIONS = [_migrate_v0, _migrate_v1]


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


def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    with _db_connect() as conn:
        _run_migrations(conn)


def _generate_slug(home_team: str, away_team: str, date: str) -> str:
    """Generate a URL-friendly slug from team names and date."""
    parts = [home_team or "home", "vs", away_team or "away"]
    if date:
        parts.append(date)
    raw = "-".join(parts)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").lower()
    return slug or "match"


def _ensure_unique_slug(conn: sqlite3.Connection, slug: str, exclude_id: str | None = None) -> str:
    """Return a unique slug, appending -2, -3, etc. if needed."""
    candidate = slug
    counter = 2
    while True:
        row = conn.execute("SELECT id FROM matches WHERE slug = ?", (candidate,)).fetchone()
        if row is None or (exclude_id and row["id"] == exclude_id):
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1


def _row_to_match(row: sqlite3.Row) -> dict:
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


def _upsert_match_unlocked(conn: sqlite3.Connection, match: dict):
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


def _migrate_json_to_sqlite_if_needed():
    if not MATCHES_FILE.exists():
        return
    with _db_connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"]
        if count > 0:
            return

        try:
            matches = json.loads(MATCHES_FILE.read_text())
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
            _upsert_match_unlocked(conn, match)

        conn.commit()
        backup = MATCHES_FILE.with_suffix(".json.migrated")
        try:
            MATCHES_FILE.rename(backup)
            logger.info("Migrated matches.json to SQLite and moved source to %s", backup)
        except Exception:
            logger.info("Migrated matches.json to SQLite (source file left in place)")


_init_db()
_migrate_json_to_sqlite_if_needed()


def _backfill_slugs():
    """Generate slugs for any matches that don't have one yet."""
    with _db_connect() as conn:
        rows = conn.execute("SELECT id, home_team, away_team, date FROM matches WHERE slug IS NULL OR slug = ''").fetchall()
        for row in rows:
            slug_base = _generate_slug(row["home_team"], row["away_team"], row["date"] or "")
            slug = _ensure_unique_slug(conn, slug_base, exclude_id=row["id"])
            conn.execute("UPDATE matches SET slug = ? WHERE id = ?", (slug, row["id"]))
        if rows:
            conn.commit()
            logger.info("Backfilled slugs for %d matches", len(rows))


_backfill_slugs()

# In-memory token store: {token_string: creation_timestamp}
_active_tokens: dict[str, float] = {}
TOKEN_TTL = 86400  # 24 hours
_MAX_ACTIVE_TOKENS = 100
_last_token_sweep: float = 0.0
_TOKEN_SWEEP_INTERVAL = 60.0  # seconds

# Login rate limiting: {ip: [timestamps]}
_login_attempts: dict[str, list[float]] = {}
_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 60.0  # seconds

# Origin validation (comma-separated hostnames, optional)
_ALLOWED_ORIGINS_RAW = os.environ.get("ALLOWED_ORIGINS", "")
_ALLOWED_ORIGINS: set[str] | None = (
    {h.strip().lower() for h in _ALLOWED_ORIGINS_RAW.split(",") if h.strip()}
    if _ALLOWED_ORIGINS_RAW.strip() else None
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _sweep_expired_tokens():
    """Bulk-remove expired tokens at most once per sweep interval."""
    global _last_token_sweep
    now = time.time()
    if now - _last_token_sweep < _TOKEN_SWEEP_INTERVAL:
        return
    _last_token_sweep = now
    expired = [t for t, ts in _active_tokens.items() if now - ts > TOKEN_TTL]
    for t in expired:
        del _active_tokens[t]
    # Also prune stale login-attempt entries
    stale_ips = [ip for ip, timestamps in _login_attempts.items()
                 if not any(now - ts < _LOGIN_RATE_WINDOW for ts in timestamps)]
    for ip in stale_ips:
        del _login_attempts[ip]


def _require_auth(request: Request):
    """Validate Bearer token from Authorization header. Raises 401 if invalid."""
    _sweep_expired_tokens()
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    token = auth_header[7:]
    created = _active_tokens.get(token)
    if created is None:
        raise HTTPException(401, "Invalid or expired token")
    if time.time() - created > TOKEN_TTL:
        del _active_tokens[token]
        raise HTTPException(401, "Token expired")


def _check_login_rate_limit(request: Request):
    """Raise 429 if too many login attempts from this IP."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_RATE_WINDOW]
    if len(attempts) >= _LOGIN_RATE_LIMIT:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    attempts.append(now)
    _login_attempts[ip] = attempts


def _validate_login_origin(request: Request):
    """Validate Origin header on login if ALLOWED_ORIGINS is configured."""
    if _ALLOWED_ORIGINS is None:
        return
    origin = request.headers.get("origin") or ""
    if not origin:
        return  # Non-browser client, allow
    # Extract hostname from origin (e.g. "https://example.com" -> "example.com")
    host = origin.split("//", 1)[-1].split("/")[0].split(":")[0].lower()
    if host not in _ALLOWED_ORIGINS:
        raise HTTPException(403, "Origin not allowed")


# ---------------------------------------------------------------------------
# Helpers — JSON persistence
# ---------------------------------------------------------------------------

def _load_matches_unlocked() -> list[dict]:
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [_row_to_match(row) for row in rows]


def _save_matches_unlocked(matches: list[dict]):
    with _db_connect() as conn:
        existing_ids = {row["id"] for row in conn.execute("SELECT id FROM matches").fetchall()}
        next_ids = {m["id"] for m in matches}

        for match in matches:
            _upsert_match_unlocked(conn, match)

        removed_ids = existing_ids - next_ids
        if removed_ids:
            conn.executemany("DELETE FROM matches WHERE id = ?", [(match_id,) for match_id in removed_ids])

        conn.commit()


def _load_matches() -> list[dict]:
    with MATCHES_LOCK:
        return _load_matches_unlocked()


def _save_matches(matches: list[dict]):
    with MATCHES_LOCK:
        _save_matches_unlocked(matches)


def _find_match(matches: list[dict], match_id: str) -> dict | None:
    return next((m for m in matches if m["id"] == match_id), None)


def _get_match_by_id(match_id: str) -> dict | None:
    """Single-match lookup — avoids loading all matches for read-only endpoints."""
    with _db_connect() as conn:
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return _row_to_match(row) if row else None


# ---------------------------------------------------------------------------
# Video status
# ---------------------------------------------------------------------------

def _get_video_status(match: dict, slot: str) -> str:
    """Get status for a video slot.  Backward-compatible with old data."""
    statuses = match.get("video_status") or {}
    if slot in statuses:
        return statuses[slot]
    # Legacy: file present but no status → assume ready
    if match.get("videos", {}).get(slot):
        return "ready"
    return "none"


def _set_video_status(match_id: str, slot: str, status: str, filename: str | None):
    """Persist video status + filename to matches.json."""
    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        match = _find_match(matches, match_id)
        if not match:
            return
        if "video_status" not in match:
            match["video_status"] = {}
        match["video_status"][slot] = status
        if filename:
            match["videos"][slot] = filename
        elif status == "error":
            match["videos"][slot] = None
        _save_matches_unlocked(matches)


# ---------------------------------------------------------------------------
# Helpers — File I/O (async, non-blocking)
# ---------------------------------------------------------------------------

async def _save_upload_file(upload: UploadFile, dest: Path, max_size_bytes: int | None = None) -> int:
    """Stream an upload to disk without blocking the event loop.

    Returns bytes written. Raises HTTPException(413) if max_size_bytes is exceeded.
    """
    bytes_written = 0
    async with aiofiles.open(dest, "wb") as f:
        while True:
            chunk = await upload.read(2 * 1024 * 1024)  # 2 MB
            if not chunk:
                break
            bytes_written += len(chunk)
            if max_size_bytes and bytes_written > max_size_bytes:
                raise HTTPException(413, f"Uploaded file exceeds max size of {max_size_bytes} bytes")
            await f.write(chunk)
    await upload.close()
    return bytes_written


async def _append_bytes_file(dest: Path, data: bytes):
    def _write():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "ab") as f:
            f.write(data)

    await asyncio.to_thread(_write)


def _get_upload_session(session_id: str) -> sqlite3.Row | None:
    with _db_connect() as conn:
        return conn.execute(
            "SELECT * FROM upload_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()


def _upload_session_payload(row: sqlite3.Row) -> dict:
    return {
        "session_id": row["id"],
        "match_id": row["match_id"],
        "slot": row["slot"],
        "size_bytes": row["size_bytes"],
        "chunk_size": row["chunk_size"],
        "total_chunks": row["total_chunks"],
        "next_index": row["next_index"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# HLS path helpers
# ---------------------------------------------------------------------------

def _slot_hls_dir(match_id: str, slot: str) -> Path:
    return _media.slot_hls_dir(VIDEOS_DIR, match_id, slot)


def _slot_hls_master_path(match_id: str, slot: str) -> Path:
    return _media.slot_hls_master_path(VIDEOS_DIR, match_id, slot)


def _ready_slots_missing_hls(matches: list[dict]) -> list[tuple[str, str]]:
    missing = []
    for match in matches:
        slots = ["full"] if match.get("format") != "two_halves" else ["first_half", "second_half"]
        for slot in slots:
            if _get_video_status(match, slot) != "ready":
                continue
            mp4_path = VIDEOS_DIR / match["id"] / f"{slot}.mp4"
            if not mp4_path.is_file():
                continue
            if _slot_hls_master_path(match["id"], slot).is_file():
                continue
            missing.append((match["id"], slot))
    return missing


# ---------------------------------------------------------------------------
# Disk space
# ---------------------------------------------------------------------------

def _required_free_bytes(size_bytes: int) -> int:
    return max(MIN_FREE_DISK_BYTES, int(math.ceil(size_bytes * UPLOAD_DISK_HEADROOM_MULTIPLIER)))


def _disk_stats_payload(required_bytes: int | None = None) -> dict:
    total, used, free = shutil.disk_usage(DATA_DIR)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "min_free_bytes": MIN_FREE_DISK_BYTES,
        "required_bytes": required_bytes,
        "upload_headroom_multiplier": UPLOAD_DISK_HEADROOM_MULTIPLIER,
        "enough_space": required_bytes is None or free >= required_bytes,
    }


def _ensure_disk_space(size_bytes: int):
    required_bytes = _required_free_bytes(size_bytes)
    stats = _disk_stats_payload(required_bytes)
    if stats["free_bytes"] < required_bytes:
        raise HTTPException(
            507,
            (
                f"Insufficient free disk space for upload. "
                f"Need about {required_bytes} bytes free and only have {stats['free_bytes']} bytes."
            ),
        )


def _upload_session_view(row: sqlite3.Row) -> dict:
    payload = _upload_session_payload(row)
    raw_path = Path(row["raw_path"])
    raw_exists = raw_path.exists()
    uploaded_bytes = raw_path.stat().st_size if raw_exists else 0
    now = time.time()
    payload.update(
        {
            "uploaded_bytes": uploaded_bytes,
            "progress_pct": round((uploaded_bytes / row["size_bytes"]) * 100, 1) if row["size_bytes"] else 0,
            "raw_exists": raw_exists,
            "raw_path": str(raw_path),
            "age_seconds": round(max(0, now - row["created_at"]), 1),
            "idle_seconds": round(max(0, now - row["updated_at"]), 1),
            "stale": (now - row["updated_at"]) >= STALE_UPLOAD_SESSION_SECONDS,
        }
    )
    return payload


def _find_active_upload_session(match_id: str, slot: str, size_bytes: int, ext: str) -> sqlite3.Row | None:
    with _db_connect() as conn:
        return conn.execute(
            """
            SELECT * FROM upload_sessions
            WHERE match_id = ? AND slot = ? AND size_bytes = ? AND ext = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (match_id, slot, size_bytes, ext),
        ).fetchone()


def _list_upload_session_views(statuses: tuple[str, ...] | None = None) -> list[dict]:
    with _db_connect() as conn:
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM upload_sessions WHERE status IN ({placeholders}) ORDER BY updated_at DESC",
                statuses,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM upload_sessions ORDER BY updated_at DESC"
            ).fetchall()
    return [_upload_session_view(row) for row in rows]


def _mark_upload_session_status(session_id: str, status: str) -> sqlite3.Row | None:
    row = _get_upload_session(session_id)
    if not row:
        return None

    raw_path = Path(row["raw_path"])
    raw_path.unlink(missing_ok=True)

    with _db_connect() as conn:
        conn.execute(
            "UPDATE upload_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), session_id),
        )
        conn.commit()

    return _get_upload_session(session_id)


def _cleanup_stale_upload_sessions() -> list[str]:
    cutoff = time.time() - STALE_UPLOAD_SESSION_SECONDS
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT id FROM upload_sessions WHERE status = 'active' AND updated_at < ?",
            (cutoff,),
        ).fetchall()

    cleaned = []
    for row in rows:
        updated = _mark_upload_session_status(row["id"], "cancelled")
        if updated:
            cleaned.append(row["id"])
    return cleaned


def _cancel_conflicting_upload_sessions(match_id: str, slot: str):
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT id FROM upload_sessions WHERE match_id = ? AND slot = ? AND status = 'active'",
            (match_id, slot),
        ).fetchall()

    for row in rows:
        _mark_upload_session_status(row["id"], "replaced")


# ---------------------------------------------------------------------------
# Helpers — Media pipeline (delegated to media.py)
# ---------------------------------------------------------------------------

_MEDIA_KWARGS = dict(
    videos_dir=VIDEOS_DIR,
    hls_segment_duration=HLS_SEGMENT_DURATION,
    hls_variant_presets=HLS_VARIANT_PRESETS,
)


async def _build_hls_assets(source_mp4: Path, match_id: str, slot: str) -> bool:
    return await _media.build_hls_assets(source_mp4, match_id, slot, **_MEDIA_KWARGS)


async def _transcode_video(match_id: str, slot: str, src: Path, dest: Path):
    # Check disk space before starting a potentially long transcode
    try:
        src_size = src.stat().st_size if src.exists() else 0
        if src_size > 0:
            required = _required_free_bytes(src_size)
            stats = _disk_stats_payload(required)
            if stats["free_bytes"] < required:
                logger.error(
                    "Insufficient disk space to transcode %s/%s: need %d, have %d",
                    match_id, slot, required, stats["free_bytes"],
                )
                _set_video_status(match_id, slot, "error", None)
                return
    except Exception as exc:
        logger.warning("Disk space check failed before transcode %s/%s: %s", match_id, slot, exc)

    await _media.transcode_video(
        match_id, slot, src, dest,
        **_MEDIA_KWARGS,
        transcode_semaphore=TRANSCODE_SEMAPHORE,
        transcode_concurrency=TRANSCODE_CONCURRENCY,
        set_video_status=_set_video_status,
    )


async def _backfill_hls_for_existing_videos() -> dict:
    return await _media.backfill_hls_for_existing_videos(
        **_MEDIA_KWARGS,
        hls_backfill_lock=HLS_BACKFILL_LOCK,
        load_matches=_load_matches,
        ready_slots_missing_hls=_ready_slots_missing_hls,
    )


# ---------------------------------------------------------------------------
# Static / SPA
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_render_index_html(), headers=_SPA_NO_CACHE)


_SPA_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/match/{slug}")
@app.get("/match/{slug}/{slot}")
async def match_deep_link(slug: str, slot: str | None = None):
    """Serve the SPA shell for direct match links."""
    return HTMLResponse(_render_index_html(), headers=_SPA_NO_CACHE)


@app.get("/static/{filename}")
async def static_file(filename: str):
    filename = filename.split("?", 1)[0]
    if ".." in filename:
        raise HTTPException(400, "Invalid path")
    path = STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Not found")
    media_types = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".webp": "image/webp",
    }
    mt = media_types.get(path.suffix, "application/octet-stream")
    cache_header = "public, max-age=31536000, immutable"
    if path.suffix in {".css", ".js", ".html"}:
        cache_header = "no-store, no-cache, must-revalidate, max-age=0"
    return FileResponse(
        str(path),
        media_type=mt,
        headers={
            "Cache-Control": cache_header,
        },
    )


# ---------------------------------------------------------------------------
# Settings & app asset endpoints
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_public_settings():
    return _public_settings_payload()


@app.get("/api/admin/settings")
async def get_admin_settings(request: Request):
    _require_auth(request)
    return _public_settings_payload()


@app.put("/api/admin/settings")
async def update_admin_settings(request: Request):
    _require_auth(request)
    body = await request.json()
    updates = {
        key: _normalize_setting_value(key, value)
        for key, value in body.items()
        if key in EDITABLE_APP_SETTING_KEYS
    }
    settings = _save_settings(updates)
    return {
        "ok": True,
        "settings": settings,
        "assets": {
            "logo_url": _app_asset_url("logo", settings),
            "favicon_url": _app_asset_url("favicon", settings),
        },
    }


@app.post("/api/admin/settings/asset")
async def upload_app_asset(file: UploadFile, request: Request):
    _require_auth(request)
    kind = request.query_params.get("kind", "logo")
    if kind not in APP_ASSET_CONFIG:
        raise HTTPException(400, "kind must be logo or favicon")

    config = APP_ASSET_CONFIG[kind]
    filename = file.filename or f"{kind}.png"
    ext = Path(filename).suffix.lower()
    if ext not in config["allowed_exts"]:
        raise HTTPException(400, f"Unsupported {kind} format")

    settings = _load_settings()
    current_name = settings.get(config["setting_key"], "")
    if current_name:
        (APP_ASSETS_DIR / current_name).unlink(missing_ok=True)

    dest_name = f"app_{kind}{ext}"
    dest = APP_ASSETS_DIR / dest_name
    await _save_upload_file(file, dest, max_size_bytes=config["max_size"])
    settings = _save_settings({config["setting_key"]: dest_name})
    return {
        "ok": True,
        "kind": kind,
        "filename": dest_name,
        "settings": settings,
        "assets": {
            "logo_url": _app_asset_url("logo", settings),
            "favicon_url": _app_asset_url("favicon", settings),
        },
    }


@app.get("/api/app-assets/{kind}")
async def serve_app_asset(kind: str):
    if kind not in APP_ASSET_CONFIG:
        raise HTTPException(400, "Invalid asset kind")
    settings = _load_settings()
    filename = settings.get(APP_ASSET_CONFIG[kind]["setting_key"], "")
    if not filename:
        raise HTTPException(404, "Asset not configured")
    asset_path = APP_ASSETS_DIR / filename
    if not asset_path.is_file():
        raise HTTPException(404, "Asset not found")
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
    }
    mt = media_types.get(asset_path.suffix.lower(), "application/octet-stream")
    headers = {"Cache-Control": "public, max-age=3600, immutable"}
    if asset_path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["Content-Disposition"] = f"inline; filename=\"{asset_path.name}\""
    return FileResponse(
        str(asset_path),
        media_type=mt,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request, body: LoginRequest):
    _check_login_rate_limit(request)
    _validate_login_origin(request)
    if not secrets.compare_digest(body.username, ADMIN_USER) or \
       not secrets.compare_digest(body.password, ADMIN_PASS):
        raise HTTPException(401, "Invalid credentials")
    # Enforce token cap
    _sweep_expired_tokens()
    if len(_active_tokens) >= _MAX_ACTIVE_TOKENS:
        oldest_token = min(_active_tokens, key=_active_tokens.get)
        del _active_tokens[oldest_token]
    token = secrets.token_hex(32)
    _active_tokens[token] = time.time()
    return {"token": token}


@app.post("/api/logout")
async def logout(request: Request):
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        _active_tokens.pop(auth_header[7:], None)
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    try:
        _require_auth(request)
        return {"authenticated": True}
    except HTTPException:
        return {"authenticated": False}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@app.get("/api/admin/diagnostics")
async def admin_diagnostics(request: Request):
    _require_auth(request)
    _cleanup_stale_upload_sessions()

    matches = _load_matches()
    upload_sessions = _list_upload_session_views(("active", "completed", "cancelled", "replaced"))[:12]
    hls_missing_slots = _ready_slots_missing_hls(matches)
    transcoding_count = sum(
        1
        for match in matches
        for status in (match.get("video_status") or {}).values()
        if status == "transcoding"
    )
    ready_count = sum(
        1
        for match in matches
        for status in (match.get("video_status") or {}).values()
        if status == "ready"
    )

    return {
        "counts": {
            "matches": len(matches),
            "transcoding_slots": transcoding_count,
            "ready_slots": ready_count,
            "hls_missing_slots": len(hls_missing_slots),
            "active_tokens": len(_active_tokens),
        },
        "disk": _disk_stats_payload(),
        "upload_limits": {
            "max_upload_size_bytes": MAX_UPLOAD_SIZE_BYTES,
            "chunk_size_bytes": UPLOAD_CHUNK_SIZE_BYTES,
            "stale_upload_session_seconds": STALE_UPLOAD_SESSION_SECONDS,
        },
        "transcode": {
            "concurrency_limit": TRANSCODE_CONCURRENCY,
        },
        "hls": {
            "backfill_running": HLS_BACKFILL_LOCK.locked(),
        },
        "upload_sessions": upload_sessions,
    }


@app.post("/api/admin/backfill-hls")
async def admin_backfill_hls(request: Request):
    _require_auth(request)
    result = await _backfill_hls_for_existing_videos()
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Matches CRUD
# ---------------------------------------------------------------------------

@app.get("/api/matches")
async def list_matches():
    return _load_matches()


@app.post("/api/matches")
async def create_match(request: Request, body: CreateMatchRequest):
    _require_auth(request)
    match_id = f"match-{int(time.time() * 1000)}"

    slug_base = _generate_slug(body.home_team, body.away_team, body.date)

    match = {
        "id": match_id,
        "home_team": body.home_team,
        "away_team": body.away_team,
        "date": body.date,
        "time": body.time,
        "location": body.location,
        "score_home": body.score_home,
        "score_away": body.score_away,
        "format": body.format,
        "videos": {"full": None, "first_half": None, "second_half": None},
        "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
        "home_logo": None,
        "away_logo": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "slug": "",
    }

    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)

    with MATCHES_LOCK:
        with _db_connect() as conn:
            match["slug"] = _ensure_unique_slug(conn, slug_base)
        matches = _load_matches_unlocked()
        matches.append(match)
        _save_matches_unlocked(matches)
    return match


@app.put("/api/matches/{match_id}")
async def update_match(match_id: str, request: Request, body: UpdateMatchRequest):
    _require_auth(request)
    updates = body.model_dump(exclude_unset=True)
    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        match = _find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

        slug_fields_changed = False
        for key, value in updates.items():
            if key in ("home_team", "away_team", "date") and value != match.get(key):
                slug_fields_changed = True
            match[key] = value

        if slug_fields_changed or not match.get("slug"):
            slug_base = _generate_slug(match["home_team"], match["away_team"], match.get("date", ""))
            with _db_connect() as conn:
                match["slug"] = _ensure_unique_slug(conn, slug_base, exclude_id=match["id"])

        _save_matches_unlocked(matches)
        return match


@app.delete("/api/matches/{match_id}")
async def delete_match(match_id: str, request: Request):
    _require_auth(request)
    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        match = _find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

    vid_dir = VIDEOS_DIR / match_id
    if vid_dir.exists():
        shutil.rmtree(str(vid_dir))

    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        matches = [m for m in matches if m["id"] != match_id]
        _save_matches_unlocked(matches)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Video Upload & Streaming
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-video/session")
async def create_upload_session(match_id: str, request: Request, body: CreateUploadSessionRequest):
    _require_auth(request)
    _cleanup_stale_upload_sessions()
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    filename = body.filename.strip()
    size_bytes = body.size_bytes
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(413, f"Uploaded file exceeds max size of {MAX_UPLOAD_SIZE_BYTES} bytes")

    ext = Path(filename).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    existing = _find_active_upload_session(match_id, slot, size_bytes, ext)
    if existing:
        logger.info(
            "Reusing active upload session: %s match=%s slot=%s next_index=%d",
            existing["id"],
            match_id,
            slot,
            existing["next_index"],
        )
        return _upload_session_payload(existing)

    _ensure_disk_space(size_bytes)
    _cancel_conflicting_upload_sessions(match_id, slot)

    vid_dir = VIDEOS_DIR / match_id
    vid_dir.mkdir(parents=True, exist_ok=True)
    raw_path = vid_dir / f"{slot}_raw{ext}"
    raw_path.unlink(missing_ok=True)

    session_id = uuid.uuid4().hex
    chunk_size = UPLOAD_CHUNK_SIZE_BYTES
    total_chunks = max(1, math.ceil(size_bytes / chunk_size))
    now = time.time()

    with _db_connect() as conn:
        conn.execute(
            """
            INSERT INTO upload_sessions (
                id, match_id, slot, ext, raw_path, size_bytes, chunk_size,
                total_chunks, next_index, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?)
            """,
            (
                session_id,
                match_id,
                slot,
                ext,
                str(raw_path),
                size_bytes,
                chunk_size,
                total_chunks,
                now,
                now,
            ),
        )
        conn.commit()

    logger.info(
        "Chunked upload session created: %s match=%s slot=%s size=%d chunks=%d",
        session_id,
        match_id,
        slot,
        size_bytes,
        total_chunks,
    )
    return {
        "session_id": session_id,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "next_index": 0,
    }


@app.get("/api/uploads/sessions")
async def list_upload_sessions(request: Request):
    _require_auth(request)
    status_param = (request.query_params.get("status") or "active").strip().lower()
    if status_param == "all":
        sessions = _list_upload_session_views(None)
    else:
        statuses = tuple(part.strip() for part in status_param.split(",") if part.strip())
        sessions = _list_upload_session_views(statuses or ("active",))
    return {"sessions": sessions}


@app.put("/api/uploads/sessions/{session_id}/chunk")
async def upload_session_chunk(session_id: str, request: Request):
    _require_auth(request)
    try:
        index = int(request.query_params.get("index", "-1"))
    except ValueError:
        raise HTTPException(400, "index must be an integer")

    row = _get_upload_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    if row["status"] != "active":
        raise HTTPException(409, "Upload session is not active")
    if index < 0 or index >= row["total_chunks"]:
        raise HTTPException(400, "index out of range")

    # Idempotent retry of already-written chunk.
    if index < row["next_index"]:
        return {"ok": True, "next_index": row["next_index"]}

    if index > row["next_index"]:
        raise HTTPException(409, f"Expected chunk index {row['next_index']}")

    data = await request.body()
    if not data:
        raise HTTPException(400, "empty chunk body")
    if len(data) > row["chunk_size"]:
        raise HTTPException(400, "chunk exceeds session chunk_size")

    raw_path = Path(row["raw_path"])
    await _append_bytes_file(raw_path, data)

    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE upload_sessions
            SET next_index = next_index + 1, updated_at = ?
            WHERE id = ?
            """,
            (time.time(), session_id),
        )
        conn.commit()

    return {"ok": True, "next_index": index + 1}


@app.get("/api/uploads/sessions/{session_id}")
async def get_upload_session(session_id: str, request: Request):
    _require_auth(request)
    row = _get_upload_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    return _upload_session_view(row)


@app.delete("/api/uploads/sessions/{session_id}")
async def cancel_upload_session(session_id: str, request: Request):
    _require_auth(request)
    row = _mark_upload_session_status(session_id, "cancelled")
    if not row:
        raise HTTPException(404, "Upload session not found")
    return {"ok": True, "session": _upload_session_view(row)}


@app.post("/api/uploads/sessions/cleanup")
async def cleanup_upload_sessions(request: Request):
    _require_auth(request)
    cleaned = _cleanup_stale_upload_sessions()
    return {"ok": True, "cleaned_session_ids": cleaned, "count": len(cleaned)}


@app.post("/api/uploads/sessions/{session_id}/complete")
async def complete_upload_session(session_id: str, request: Request):
    _require_auth(request)
    row = _get_upload_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    if row["status"] != "active":
        raise HTTPException(409, "Upload session is not active")
    if row["next_index"] != row["total_chunks"]:
        raise HTTPException(409, "Upload incomplete")

    raw_path = Path(row["raw_path"])
    if not raw_path.exists():
        raise HTTPException(500, "Uploaded file not found")
    actual_size = raw_path.stat().st_size
    if actual_size != row["size_bytes"]:
        raise HTTPException(409, f"Uploaded size mismatch: expected {row['size_bytes']}, got {actual_size}")

    match_id = row["match_id"]
    slot = row["slot"]
    final_path = VIDEOS_DIR / match_id / f"{slot}.mp4"

    _set_video_status(match_id, slot, "transcoding", None)

    with _db_connect() as conn:
        conn.execute(
            "UPDATE upload_sessions SET status = 'completed', updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        conn.commit()

    logger.info(
        "Chunked upload complete: %s match=%s slot=%s size=%d",
        session_id,
        match_id,
        slot,
        actual_size,
    )
    asyncio.create_task(_transcode_video(match_id, slot, raw_path, final_path))
    return {"ok": True, "status": "transcoding", "slot": slot, "size_mb": round(actual_size / 1e6, 1)}

@app.post("/api/matches/{match_id}/upload-video")
async def upload_video(match_id: str, file: UploadFile, request: Request):
    """Upload a video file (MP4 / MKV).  Query param: slot=full|first_half|second_half

    The raw file is saved with async I/O, then transcoding starts in the
    background (GPU → CPU fallback).  The endpoint returns immediately so
    subsequent uploads are not blocked.
    """
    _require_auth(request)
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    fname = file.filename or "video.mp4"
    ext = Path(fname).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    vid_dir = VIDEOS_DIR / match_id
    vid_dir.mkdir(parents=True, exist_ok=True)

    # Save raw upload (non-blocking async I/O)
    raw_path = vid_dir / f"{slot}_raw{ext}"
    logger.info(
        "Upload started: %s/%s filename=%s max_size_bytes=%d",
        match_id,
        slot,
        fname,
        MAX_UPLOAD_SIZE_BYTES,
    )
    started_at = time.time()
    try:
        bytes_written = await _save_upload_file(file, raw_path, max_size_bytes=MAX_UPLOAD_SIZE_BYTES)
    except HTTPException:
        raw_path.unlink(missing_ok=True)
        raise

    size_mb = round(bytes_written / 1e6, 1)
    elapsed = round(time.time() - started_at, 2)
    logger.info(
        "Upload saved: %s/%s (%s MB in %ss) — starting transcode",
        match_id,
        slot,
        size_mb,
        elapsed,
    )

    # Mark as transcoding
    _set_video_status(match_id, slot, "transcoding", None)

    # Kick off background transcoding
    final_path = vid_dir / f"{slot}.mp4"
    asyncio.create_task(_transcode_video(match_id, slot, raw_path, final_path))

    return {"ok": True, "slot": slot, "size_mb": size_mb, "status": "transcoding"}


@app.get("/api/matches/{match_id}/video/{slot}")
async def stream_video(match_id: str, slot: str, request: Request):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    status = _get_video_status(match, slot)
    if status == "transcoding":
        return JSONResponse(
            {"status": "transcoding", "message": "Video is being processed"},
            status_code=202,
        )
    if status == "error":
        raise HTTPException(500, "Video processing failed — check server logs")

    vid_path = VIDEOS_DIR / match_id / f"{slot}.mp4"
    if not vid_path.is_file():
        raise HTTPException(404, "Video not found")

    return _range_file_response(vid_path, "video/mp4", request)


@app.get("/api/matches/{match_id}/download/{slot}")
async def download_video(match_id: str, slot: str, request: Request):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    settings = _load_settings()
    if settings.get("downloads_enabled", "1") != "1":
        raise HTTPException(403, "Downloads are disabled")

    status = _get_video_status(match, slot)
    if status == "transcoding":
        raise HTTPException(409, "Video is still processing")
    if status == "error":
        raise HTTPException(500, "Video processing failed")

    vid_path = VIDEOS_DIR / match_id / f"{slot}.mp4"
    if not vid_path.is_file():
        raise HTTPException(404, "Video not found")

    slug_parts = [match.get("home_team", "home"), "vs", match.get("away_team", "away"), slot]
    safe_name = "_".join(re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_") or "match" for part in slug_parts)
    return _range_file_response(
        vid_path,
        "video/mp4",
        request,
        content_disposition=f'attachment; filename="{safe_name}.mp4"',
    )


@app.on_event("startup")
async def startup_backfill_hls():
    asyncio.create_task(_backfill_hls_for_existing_videos())


# ---------------------------------------------------------------------------
# HLS streaming
# ---------------------------------------------------------------------------

@app.get("/api/matches/{match_id}/hls/{slot}/master.m3u8")
async def stream_hls_master(match_id: str, slot: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    status = _get_video_status(match, slot)
    if status == "transcoding":
        raise HTTPException(404, "HLS not ready yet")
    if status == "error":
        raise HTTPException(500, "Video processing failed")

    master_path = _slot_hls_master_path(match_id, slot)
    if not master_path.is_file():
        raise HTTPException(404, "HLS playlist not found")

    return FileResponse(
        str(master_path),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "public, max-age=3600, immutable"},
    )


@app.get("/api/matches/{match_id}/hls/{slot}/{asset_path:path}")
async def stream_hls_asset(match_id: str, slot: str, asset_path: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    if not asset_path or ".." in asset_path:
        raise HTTPException(400, "Invalid asset path")

    base_dir = _slot_hls_dir(match_id, slot).resolve()
    target_path = (base_dir / asset_path).resolve()
    if base_dir not in target_path.parents:
        raise HTTPException(400, "Invalid asset path")
    if not target_path.is_file():
        raise HTTPException(404, "HLS asset not found")

    media_type = "application/octet-stream"
    if target_path.suffix == ".m3u8":
        media_type = "application/vnd.apple.mpegurl"
    elif target_path.suffix == ".ts":
        media_type = "video/mp2t"

    return FileResponse(
        str(target_path),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600, immutable"},
    )


def _range_file_response(file_path: Path, media_type: str, request: Request, content_disposition: str | None = None):
    """Serve a file with Range-request support for video seeking."""
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600, immutable",
    }
    if content_disposition:
        common_headers["Content-Disposition"] = content_disposition

    if range_header:
        range_spec = range_header.replace("bytes=", "").strip()
        parts = range_spec.split("-")
        try:
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except ValueError:
            raise HTTPException(416, "Invalid range request")

        if start >= file_size or start < 0:
            raise HTTPException(416, "Requested range not satisfiable")
        end = min(end, file_size - 1)
        length = end - start + 1

        def _iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(VIDEO_STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            _iter_range(),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                **common_headers,
            },
        )

    return FileResponse(
        str(file_path),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            **common_headers,
        },
    )


# ---------------------------------------------------------------------------
# Logo Upload & Serving
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-logo")
async def upload_logo(match_id: str, file: UploadFile, request: Request):
    """Upload a team logo.  Query param: team=home|away"""
    _require_auth(request)
    team = request.query_params.get("team", "home")
    if team not in ("home", "away"):
        raise HTTPException(400, "team must be home or away")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    fname = file.filename or "logo.png"
    ext = Path(fname).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(400, "Unsupported image format")

    vid_dir = VIDEOS_DIR / match_id
    vid_dir.mkdir(parents=True, exist_ok=True)

    dest = vid_dir / f"{team}_logo{ext}"
    await _save_upload_file(file, dest, max_size_bytes=20 * 1024 * 1024)

    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        match = _find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        match[f"{team}_logo"] = dest.name
        _save_matches_unlocked(matches)
    return {"ok": True, "team": team, "filename": dest.name}


@app.get("/api/matches/{match_id}/logo/{team}")
async def serve_logo(match_id: str, team: str):
    if team not in ("home", "away"):
        raise HTTPException(400, "Invalid team")

    match = _get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    logo_name = match.get(f"{team}_logo")
    if not logo_name:
        raise HTTPException(404, "No logo uploaded")

    logo_path = VIDEOS_DIR / match_id / logo_name
    if not logo_path.is_file():
        raise HTTPException(404, "Logo file not found")

    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".svg": "image/svg+xml", ".webp": "image/webp"}
    mt = media_types.get(logo_path.suffix.lower(), "image/png")
    headers = {}
    if logo_path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["Content-Disposition"] = f"inline; filename=\"{logo_path.name}\""
    return FileResponse(str(logo_path), media_type=mt, headers=headers)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("REPLAY_PORT", "8090"))
    logger.info("Replay server starting on port %d (data: %s)", port, DATA_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=600)
