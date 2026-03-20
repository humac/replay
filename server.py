"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8090)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

import auth as _auth
import db as _db
import log as _log
import media as _media
import settings as _settings
import uploads as _uploads
from models import CreateMatchRequest, CreateUploadSessionRequest, LoginRequest, UpdateMatchRequest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logger = _log.setup("replay")

DATA_DIR = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))
STATIC_DIR = Path(__file__).parent
MATCHES_FILE = DATA_DIR / "matches.json"
DB_FILE = DATA_DIR / "replay.db"
VIDEOS_DIR = DATA_DIR / "videos"
APP_ASSETS_DIR = DATA_DIR / "app_assets"

app = FastAPI(title="Replay")

MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(12 * 1024 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE_BYTES = int(os.environ.get("UPLOAD_CHUNK_SIZE_BYTES", str(16 * 1024 * 1024)))
TRANSCODE_CONCURRENCY = max(1, int(os.environ.get("TRANSCODE_CONCURRENCY", "2")))
MIN_FREE_DISK_BYTES = int(os.environ.get("MIN_FREE_DISK_BYTES", str(20 * 1024 * 1024 * 1024)))
UPLOAD_DISK_HEADROOM_MULTIPLIER = float(os.environ.get("UPLOAD_DISK_HEADROOM_MULTIPLIER", "2.2"))
STALE_UPLOAD_SESSION_SECONDS = int(os.environ.get("STALE_UPLOAD_SESSION_SECONDS", str(6 * 60 * 60)))
VIDEO_STREAM_CHUNK_BYTES = int(os.environ.get("VIDEO_STREAM_CHUNK_BYTES", str(1024 * 1024)))
HLS_SEGMENT_DURATION = int(os.environ.get("HLS_SEGMENT_DURATION", "6"))
TRANSCODE_SEMAPHORE = asyncio.Semaphore(TRANSCODE_CONCURRENCY)
MATCHES_LOCK = asyncio.Lock()
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

# ---------------------------------------------------------------------------
# Module initialization
# ---------------------------------------------------------------------------

_db.init(DATA_DIR, DB_FILE, APP_ASSETS_DIR)
_db.migrate_json_to_sqlite(MATCHES_FILE)
_db.backfill_slugs()
_settings.init(APP_ASSETS_DIR, STATIC_DIR)

# ---------------------------------------------------------------------------
# Async wrappers around module functions (lock-protected)
# ---------------------------------------------------------------------------


async def _load_settings() -> dict[str, str]:
    async with MATCHES_LOCK:
        return _settings.load_unlocked()


async def _save_settings(updates: dict[str, str]) -> dict[str, str]:
    async with MATCHES_LOCK:
        return _settings.save_unlocked(updates)


async def _public_settings_payload() -> dict:
    settings = await _load_settings()
    return _settings.public_payload(settings)


async def _render_index_html() -> str:
    settings_payload = await _public_settings_payload()
    return _settings.render_index_html(settings_payload)


async def _load_matches() -> list[dict]:
    async with MATCHES_LOCK:
        return _db.load_matches_unlocked()


async def _save_matches(matches: list[dict]):
    async with MATCHES_LOCK:
        _db.save_matches_unlocked(matches)


async def _set_video_status(match_id: str, slot: str, status: str, filename: str | None):
    """Persist video status + filename to the database."""
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            return
        if "video_status" not in match:
            match["video_status"] = {}
        match["video_status"][slot] = status
        if filename:
            match["videos"][slot] = filename
        elif status == "error":
            match["videos"][slot] = None
        _db.save_matches_unlocked(matches)


# ---------------------------------------------------------------------------
# Video status helpers
# ---------------------------------------------------------------------------

def _get_video_status(match: dict, slot: str) -> str:
    """Get status for a video slot.  Backward-compatible with old data."""
    statuses = match.get("video_status") or {}
    if slot in statuses:
        return statuses[slot]
    if match.get("videos", {}).get(slot):
        return "ready"
    return "none"


# ---------------------------------------------------------------------------
# Helpers — File I/O (async, non-blocking)
# ---------------------------------------------------------------------------

async def _save_upload_file(upload: UploadFile, dest: Path, max_size_bytes: int | None = None) -> int:
    """Stream an upload to disk without blocking the event loop."""
    bytes_written = 0
    async with aiofiles.open(dest, "wb") as f:
        while True:
            chunk = await upload.read(2 * 1024 * 1024)
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
                await _set_video_status(match_id, slot, "error", None)
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
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


_SPA_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/match/{slug}")
@app.get("/match/{slug}/{slot}")
async def match_deep_link(slug: str, slot: str | None = None):
    """Serve the SPA shell for direct match links."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


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
    return await _public_settings_payload()


@app.get("/api/admin/settings")
async def get_admin_settings(request: Request):
    _auth.require_auth(request)
    return await _public_settings_payload()


@app.put("/api/admin/settings")
async def update_admin_settings(request: Request):
    _auth.require_auth(request)
    body = await request.json()
    updates = {
        key: _settings.normalize_value(key, value)
        for key, value in body.items()
        if key in _settings.EDITABLE_APP_SETTING_KEYS
    }
    settings = await _save_settings(updates)
    return {
        "ok": True,
        "settings": settings,
        "assets": {
            "logo_url": _settings.app_asset_url("logo", settings),
            "favicon_url": _settings.app_asset_url("favicon", settings),
        },
    }


@app.post("/api/admin/settings/asset")
async def upload_app_asset(file: UploadFile, request: Request):
    _auth.require_auth(request)
    kind = request.query_params.get("kind", "logo")
    if kind not in _settings.APP_ASSET_CONFIG:
        raise HTTPException(400, "kind must be logo or favicon")

    config = _settings.APP_ASSET_CONFIG[kind]
    filename = file.filename or f"{kind}.png"
    ext = Path(filename).suffix.lower()
    if ext not in config["allowed_exts"]:
        raise HTTPException(400, f"Unsupported {kind} format")

    settings = await _load_settings()
    current_name = settings.get(config["setting_key"], "")
    if current_name:
        (APP_ASSETS_DIR / current_name).unlink(missing_ok=True)

    dest_name = f"app_{kind}{ext}"
    dest = APP_ASSETS_DIR / dest_name
    await _save_upload_file(file, dest, max_size_bytes=config["max_size"])
    settings = await _save_settings({config["setting_key"]: dest_name})
    return {
        "ok": True,
        "kind": kind,
        "filename": dest_name,
        "settings": settings,
        "assets": {
            "logo_url": _settings.app_asset_url("logo", settings),
            "favicon_url": _settings.app_asset_url("favicon", settings),
        },
    }


@app.get("/api/app-assets/{kind}")
async def serve_app_asset(kind: str):
    if kind not in _settings.APP_ASSET_CONFIG:
        raise HTTPException(400, "Invalid asset kind")
    settings = await _load_settings()
    filename = settings.get(_settings.APP_ASSET_CONFIG[kind]["setting_key"], "")
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
    _auth.check_login_rate_limit(request)
    _auth.validate_login_origin(request)
    import secrets as _secrets
    if not _secrets.compare_digest(body.username, _auth.ADMIN_USER) or \
       not _secrets.compare_digest(body.password, _auth.ADMIN_PASS):
        raise HTTPException(401, "Invalid credentials")
    token = _auth.create_token()
    return {"token": token}


@app.post("/api/logout")
async def logout(request: Request):
    _auth.revoke_token(request)
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    try:
        _auth.require_auth(request)
        return {"authenticated": True}
    except HTTPException:
        return {"authenticated": False}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@app.get("/api/admin/diagnostics")
async def admin_diagnostics(request: Request):
    _auth.require_auth(request)
    _uploads.cleanup_stale_sessions(STALE_UPLOAD_SESSION_SECONDS)

    matches = await _load_matches()
    upload_sessions = _uploads.list_session_views(STALE_UPLOAD_SESSION_SECONDS, ("active", "completed", "cancelled", "replaced"))[:12]
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
            "active_tokens": _auth.active_token_count(),
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
    _auth.require_auth(request)
    result = await _backfill_hls_for_existing_videos()
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Matches CRUD
# ---------------------------------------------------------------------------

@app.get("/api/matches")
async def list_matches():
    return await _load_matches()


@app.post("/api/matches")
async def create_match(request: Request, body: CreateMatchRequest):
    _auth.require_auth(request)
    match_id = f"match-{int(time.time() * 1000)}"

    slug_base = _db.generate_slug(body.home_team, body.away_team, body.date)

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

    async with MATCHES_LOCK:
        with _db.connect() as conn:
            match["slug"] = _db.ensure_unique_slug(conn, slug_base)
        matches = _db.load_matches_unlocked()
        matches.append(match)
        _db.save_matches_unlocked(matches)
    return match


@app.put("/api/matches/{match_id}")
async def update_match(match_id: str, request: Request, body: UpdateMatchRequest):
    _auth.require_auth(request)
    updates = body.model_dump(exclude_unset=True)
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

        slug_fields_changed = False
        for key, value in updates.items():
            if key in ("home_team", "away_team", "date") and value != match.get(key):
                slug_fields_changed = True
            match[key] = value

        if slug_fields_changed or not match.get("slug"):
            slug_base = _db.generate_slug(match["home_team"], match["away_team"], match.get("date", ""))
            with _db.connect() as conn:
                match["slug"] = _db.ensure_unique_slug(conn, slug_base, exclude_id=match["id"])

        _db.save_matches_unlocked(matches)
        return match


@app.delete("/api/matches/{match_id}")
async def delete_match(match_id: str, request: Request):
    _auth.require_auth(request)
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

    vid_dir = VIDEOS_DIR / match_id
    if vid_dir.exists():
        shutil.rmtree(str(vid_dir))

    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        matches = [m for m in matches if m["id"] != match_id]
        _db.save_matches_unlocked(matches)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Video Upload & Streaming
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-video/session")
async def create_upload_session(match_id: str, request: Request, body: CreateUploadSessionRequest):
    _auth.require_auth(request)
    _uploads.cleanup_stale_sessions(STALE_UPLOAD_SESSION_SECONDS)
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

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    existing = _uploads.find_active_session(match_id, slot, size_bytes, ext)
    if existing:
        logger.info(
            "Reusing active upload session: %s match=%s slot=%s next_index=%d",
            existing["id"],
            match_id,
            slot,
            existing["next_index"],
        )
        return _uploads.session_payload(existing)

    _ensure_disk_space(size_bytes)
    _uploads.cancel_conflicting_sessions(match_id, slot)

    vid_dir = VIDEOS_DIR / match_id
    vid_dir.mkdir(parents=True, exist_ok=True)
    raw_path = vid_dir / f"{slot}_raw{ext}"
    raw_path.unlink(missing_ok=True)

    session_id = uuid.uuid4().hex
    chunk_size = UPLOAD_CHUNK_SIZE_BYTES
    total_chunks = max(1, math.ceil(size_bytes / chunk_size))
    now = time.time()

    with _db.connect() as conn:
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
    _auth.require_auth(request)
    status_param = (request.query_params.get("status") or "active").strip().lower()
    if status_param == "all":
        sessions = _uploads.list_session_views(STALE_UPLOAD_SESSION_SECONDS, None)
    else:
        statuses = tuple(part.strip() for part in status_param.split(",") if part.strip())
        sessions = _uploads.list_session_views(STALE_UPLOAD_SESSION_SECONDS, statuses or ("active",))
    return {"sessions": sessions}


@app.put("/api/uploads/sessions/{session_id}/chunk")
async def upload_session_chunk(session_id: str, request: Request):
    _auth.require_auth(request)
    try:
        index = int(request.query_params.get("index", "-1"))
    except ValueError:
        raise HTTPException(400, "index must be an integer")

    row = _uploads.get_session(session_id)
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

    with _db.connect() as conn:
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
    _auth.require_auth(request)
    row = _uploads.get_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    return _uploads.session_view(row, STALE_UPLOAD_SESSION_SECONDS)


@app.delete("/api/uploads/sessions/{session_id}")
async def cancel_upload_session(session_id: str, request: Request):
    _auth.require_auth(request)
    row = _uploads.mark_session_status(session_id, "cancelled")
    if not row:
        raise HTTPException(404, "Upload session not found")
    return {"ok": True, "session": _uploads.session_view(row, STALE_UPLOAD_SESSION_SECONDS)}


@app.post("/api/uploads/sessions/cleanup")
async def cleanup_upload_sessions(request: Request):
    _auth.require_auth(request)
    cleaned = _uploads.cleanup_stale_sessions(STALE_UPLOAD_SESSION_SECONDS)
    return {"ok": True, "cleaned_session_ids": cleaned, "count": len(cleaned)}


@app.post("/api/uploads/sessions/{session_id}/complete")
async def complete_upload_session(session_id: str, request: Request):
    _auth.require_auth(request)
    row = _uploads.get_session(session_id)
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

    await _set_video_status(match_id, slot, "transcoding", None)

    with _db.connect() as conn:
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
    """Upload a video file (MP4 / MKV).  Query param: slot=full|first_half|second_half"""
    _auth.require_auth(request)
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    fname = file.filename or "video.mp4"
    ext = Path(fname).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    vid_dir = VIDEOS_DIR / match_id
    vid_dir.mkdir(parents=True, exist_ok=True)

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

    await _set_video_status(match_id, slot, "transcoding", None)

    final_path = vid_dir / f"{slot}.mp4"
    asyncio.create_task(_transcode_video(match_id, slot, raw_path, final_path))

    return {"ok": True, "slot": slot, "size_mb": size_mb, "status": "transcoding"}


@app.get("/api/matches/{match_id}/video/{slot}")
async def stream_video(match_id: str, slot: str, request: Request):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _db.get_match_by_id(match_id)
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

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    settings = await _load_settings()
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

    match = _db.get_match_by_id(match_id)
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
    _auth.require_auth(request)
    team = request.query_params.get("team", "home")
    if team not in ("home", "away"):
        raise HTTPException(400, "team must be home or away")

    match = _db.get_match_by_id(match_id)
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

    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        match[f"{team}_logo"] = dest.name
        _db.save_matches_unlocked(matches)
    return {"ok": True, "team": team, "filename": dest.name}


@app.get("/api/matches/{match_id}/logo/{team}")
async def serve_logo(match_id: str, team: str):
    if team not in ("home", "away"):
        raise HTTPException(400, "Invalid team")

    match = _db.get_match_by_id(match_id)
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
