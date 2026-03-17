"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8090)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("replay")

DATA_DIR = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))
STATIC_DIR = Path(__file__).parent
MATCHES_FILE = DATA_DIR / "matches.json"
DB_FILE = DATA_DIR / "replay.db"
VIDEOS_DIR = DATA_DIR / "videos"

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


def _asset_version(filename: str) -> str:
    path = STATIC_DIR / filename
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return "0"


def _render_index_html() -> str:
    html = (STATIC_DIR / "index.html").read_text()
    replacements = {
        '/static/styles.css': f'/static/styles.css?v={_asset_version("styles.css")}',
        '/static/script.js': f'/static/script.js?v={_asset_version("script.js")}',
        '/static/logo.png': f'/static/logo.png?v={_asset_version("logo.png")}',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db_connect() as conn:
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
        conn.commit()


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
    }


def _upsert_match_unlocked(conn: sqlite3.Connection, match: dict):
    conn.execute(
        """
        INSERT INTO matches (
            id, home_team, away_team, date, time, location, score_home, score_away,
            format, videos_json, video_status_json, home_logo, away_logo, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            created_at=excluded.created_at
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

# In-memory token store: {token_string: creation_timestamp}
_active_tokens: dict[str, float] = {}
TOKEN_TTL = 86400  # 24 hours


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_auth(request: Request):
    """Validate Bearer token from Authorization header. Raises 401 if invalid."""
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


def _slot_hls_dir(match_id: str, slot: str) -> Path:
    return VIDEOS_DIR / match_id / "hls" / slot


def _slot_hls_master_path(match_id: str, slot: str) -> Path:
    return _slot_hls_dir(match_id, slot) / "master.m3u8"


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
# Helpers — Transcoding (GPU-first, CPU fallback)
# ---------------------------------------------------------------------------

async def _probe_codecs(src: Path) -> tuple[str | None, str | None]:
    """Return (video_codec, audio_codec) of *src*."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None, None
        data = json.loads(stdout)
        v_codec = a_codec = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and not v_codec:
                v_codec = s.get("codec_name")
            elif s.get("codec_type") == "audio" and not a_codec:
                a_codec = s.get("codec_name")
        return v_codec, a_codec
    except Exception:
        return None, None


async def _probe_video_dimensions(src: Path) -> tuple[int | None, int | None]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None, None
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                return int(width) if width else None, int(height) if height else None
        return None, None
    except Exception:
        return None, None


async def _run_ffmpeg(cmd: list[str]) -> tuple[bool, str]:
    """Run an ffmpeg command; return (success, stderr_tail)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    tail = stderr[-500:].decode(errors="replace") if stderr else ""
    return proc.returncode == 0, tail


def _build_hls_variants(width: int | None, height: int | None) -> list[dict]:
    selected = []
    source_height = height or 0
    source_width = width or 0

    for preset in HLS_VARIANT_PRESETS:
        if source_height >= preset["height"] or source_width >= preset["width"]:
            selected.append(dict(preset))

    if selected:
        return selected

    fallback_height = max(240, source_height or 480)
    if fallback_height % 2:
        fallback_height -= 1
    return [{
        "name": f"{fallback_height}p",
        "height": fallback_height,
        "width": source_width or 854,
        "video_bitrate": "1400k",
        "maxrate": "1600k",
        "bufsize": "3200k",
        "audio_bitrate": "128k",
        "bandwidth": 1800000,
    }]


async def _build_hls_assets(source_mp4: Path, match_id: str, slot: str) -> bool:
    width, height = await _probe_video_dimensions(source_mp4)
    variants = _build_hls_variants(width, height)
    hls_dir = _slot_hls_dir(match_id, slot)
    shutil.rmtree(hls_dir, ignore_errors=True)
    hls_dir.mkdir(parents=True, exist_ok=True)

    generated_variants = []
    for variant in variants:
        variant_dir = hls_dir / variant["name"]
        variant_dir.mkdir(parents=True, exist_ok=True)
        playlist_path = variant_dir / "index.m3u8"
        segment_pattern = variant_dir / "segment_%03d.ts"

        ok, err = await _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(source_mp4),
            "-vf", f"scale=-2:{variant['height']}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "main",
            "-crf", "20",
            "-g", "48",
            "-keyint_min", "48",
            "-sc_threshold", "0",
            "-b:v", variant["video_bitrate"],
            "-maxrate", variant["maxrate"],
            "-bufsize", variant["bufsize"],
            "-c:a", "aac",
            "-b:a", variant["audio_bitrate"],
            "-ac", "2",
            "-ar", "48000",
            "-f", "hls",
            "-hls_time", str(HLS_SEGMENT_DURATION),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(segment_pattern),
            str(playlist_path),
        ])
        if not ok:
            logger.warning("HLS variant generation failed %s/%s/%s: %s", match_id, slot, variant['name'], err)
            continue
        generated_variants.append(variant)

    if not generated_variants:
        shutil.rmtree(hls_dir, ignore_errors=True)
        return False

    master_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for variant in generated_variants:
        master_lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={variant['bandwidth']},RESOLUTION={variant['width']}x{variant['height']}"
        )
        master_lines.append(f"{variant['name']}/index.m3u8")

    _slot_hls_master_path(match_id, slot).write_text("\n".join(master_lines) + "\n")
    return True


async def _backfill_hls_for_existing_videos() -> dict:
    if HLS_BACKFILL_LOCK.locked():
        return {"started": False, "reason": "already-running", "processed": 0, "generated": 0}

    async with HLS_BACKFILL_LOCK:
        matches = _load_matches()
        candidates = _ready_slots_missing_hls(matches)
        generated = 0

        for match_id, slot in candidates:
            mp4_path = VIDEOS_DIR / match_id / f"{slot}.mp4"
            try:
                ok = await _build_hls_assets(mp4_path, match_id, slot)
                if ok:
                    generated += 1
                    logger.info("Backfilled HLS assets for %s/%s", match_id, slot)
            except Exception:
                logger.exception("Failed to backfill HLS for %s/%s", match_id, slot)

        return {
            "started": True,
            "processed": len(candidates),
            "generated": generated,
        }


async def _transcode_video(match_id: str, slot: str, src: Path, dest: Path):
    """Background task: transcode *src* → *dest* (H.264 / AAC, faststart).

    Strategy:
      1. If input is already H.264 (+AAC), remux (stream-copy) — fastest.
      2. Try GPU transcode with h264_nvenc.
      3. Fall back to CPU libx264.
    """
    try:
        async with TRANSCODE_SEMAPHORE:
            logger.info("Transcode acquired for %s/%s (max concurrency=%d)", match_id, slot, TRANSCODE_CONCURRENCY)
            v_codec, a_codec = await _probe_codecs(src)
            logger.info("Probe %s/%s: video=%s audio=%s", match_id, slot, v_codec, a_codec)
            shutil.rmtree(_slot_hls_dir(match_id, slot), ignore_errors=True)
            dest.unlink(missing_ok=True)

            # --- 1. Remux if already browser-friendly ---
            if v_codec == "h264" and a_codec in ("aac", None):
                logger.info("Remuxing (stream copy) %s/%s", match_id, slot)
                ok, err = await _run_ffmpeg([
                    "ffmpeg", "-y", "-i", str(src),
                    "-c", "copy", "-movflags", "+faststart",
                    str(dest),
                ])
                if ok:
                    src.unlink(missing_ok=True)
                    hls_ok = await _build_hls_assets(dest, match_id, slot)
                    _set_video_status(match_id, slot, "ready", dest.name)
                    logger.info("Remux done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                    return
                logger.warning("Remux failed, will transcode: %s", err)

            # --- 2. GPU transcode (NVENC) ---
            logger.info("GPU transcode %s/%s", match_id, slot)
            ok, err = await _run_ffmpeg([
                "ffmpeg", "-y",
                "-hwaccel", "cuda",
                "-i", str(src),
                "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                "-cq", "23", "-b:v", "0",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(dest),
            ])
            if ok:
                src.unlink(missing_ok=True)
                hls_ok = await _build_hls_assets(dest, match_id, slot)
                _set_video_status(match_id, slot, "ready", dest.name)
                logger.info("GPU transcode done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                return
            logger.warning("GPU transcode failed, falling back to CPU: %s", err)

            # --- 3. CPU fallback (libx264) ---
            logger.info("CPU transcode %s/%s", match_id, slot)
            ok, err = await _run_ffmpeg([
                "ffmpeg", "-y",
                "-i", str(src),
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(dest),
            ])
            if ok:
                src.unlink(missing_ok=True)
                hls_ok = await _build_hls_assets(dest, match_id, slot)
                _set_video_status(match_id, slot, "ready", dest.name)
                logger.info("CPU transcode done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                return

            logger.error("All transcode methods failed %s/%s: %s", match_id, slot, err)
            _set_video_status(match_id, slot, "error", None)
            src.unlink(missing_ok=True)

    except Exception as exc:
        logger.exception("Transcode error %s/%s: %s", match_id, slot, exc)
        _set_video_status(match_id, slot, "error", None)
        src.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Static / SPA
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        _render_index_html(),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


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
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if not secrets.compare_digest(username, ADMIN_USER) or \
       not secrets.compare_digest(password, ADMIN_PASS):
        raise HTTPException(401, "Invalid credentials")
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
async def create_match(request: Request):
    _require_auth(request)
    body = await request.json()
    match_id = f"match-{int(time.time() * 1000)}"
    match = {
        "id": match_id,
        "home_team": body.get("home_team", "").strip(),
        "away_team": body.get("away_team", "").strip(),
        "date": body.get("date", ""),
        "time": body.get("time", ""),
        "location": body.get("location", ""),
        "score_home": body.get("score_home"),
        "score_away": body.get("score_away"),
        "format": body.get("format", "full"),
        "videos": {"full": None, "first_half": None, "second_half": None},
        "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
        "home_logo": None,
        "away_logo": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not match["home_team"] or not match["away_team"]:
        raise HTTPException(400, "home_team and away_team are required")

    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)

    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        matches.append(match)
        _save_matches_unlocked(matches)
    return match


@app.put("/api/matches/{match_id}")
async def update_match(match_id: str, request: Request):
    _require_auth(request)
    body = await request.json()
    with MATCHES_LOCK:
        matches = _load_matches_unlocked()
        match = _find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

        updatable = ["home_team", "away_team", "date", "time", "location",
                     "score_home", "score_away", "format"]
        for key in updatable:
            if key in body:
                match[key] = body[key]

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
async def create_upload_session(match_id: str, request: Request):
    _require_auth(request)
    _cleanup_stale_upload_sessions()
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    body = await request.json()
    filename = (body.get("filename") or "video.mp4").strip()
    size_bytes = int(body.get("size_bytes") or 0)
    if size_bytes <= 0:
        raise HTTPException(400, "size_bytes must be > 0")
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(413, f"Uploaded file exceeds max size of {MAX_UPLOAD_SIZE_BYTES} bytes")

    ext = Path(filename).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    matches = _load_matches()
    match = _find_match(matches, match_id)
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

    matches = _load_matches()
    match = _find_match(matches, match_id)
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

    matches = _load_matches()
    match = _find_match(matches, match_id)
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


@app.on_event("startup")
async def startup_backfill_hls():
    asyncio.create_task(_backfill_hls_for_existing_videos())


@app.get("/api/matches/{match_id}/hls/{slot}/master.m3u8")
async def stream_hls_master(match_id: str, slot: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    matches = _load_matches()
    match = _find_match(matches, match_id)
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


def _range_file_response(file_path: Path, media_type: str, request: Request):
    """Serve a file with Range-request support for video seeking."""
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600, immutable",
    }

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

    matches = _load_matches()
    match = _find_match(matches, match_id)
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

    matches = _load_matches()
    match = _find_match(matches, match_id)
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
    return FileResponse(str(logo_path), media_type=mt)


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
