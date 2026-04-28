"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8090)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from contextlib import asynccontextmanager

import aiofiles
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

import auth as _auth
import db as _db
import live as _live
import log as _log
import media as _media
import settings as _settings
import streams as _streams
import uploads as _uploads
from models import (
    CreateMatchRequest, CreateUploadSessionRequest, CreateUserRequest,
    LiveAuthRequest, LoginRequest, UnblockStreamRequest,
    UpdateMatchRequest, UpdateUserRequest,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logger = _log.setup("replay")

DATA_DIR = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))

# ---------------------------------------------------------------------------
# Background task registry (M4)
# ---------------------------------------------------------------------------

_background_tasks: set[asyncio.Task] = set()

# Transcode tasks keyed by "{match_id}/{slot}" so delete_match can cancel them.
_transcode_tasks: dict[str, asyncio.Task] = {}


def _spawn_task(coro) -> asyncio.Task:
    """Create a tracked background task; log exceptions and auto-discard on completion."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    def _on_done(t: asyncio.Task):
        _background_tasks.discard(t)
        if not t.cancelled() and (exc := t.exception()):
            logger.error("Background task failed: %s", exc, exc_info=exc)
    task.add_done_callback(_on_done)
    return task


def _spawn_transcode(match_id: str, slot: str, src, dest) -> asyncio.Task:
    """Spawn a tracked transcode task, registering it for per-match cancellation."""
    key = f"{match_id}/{slot}"
    task = _spawn_task(_transcode_video(match_id, slot, src, dest))
    _transcode_tasks[key] = task
    task.add_done_callback(lambda _: _transcode_tasks.pop(key, None))
    return task


STATIC_DIR = Path(__file__).parent
MATCHES_FILE = DATA_DIR / "matches.json"
DB_FILE = DATA_DIR / "replay.db"
VIDEOS_DIR = DATA_DIR / "videos"
APP_ASSETS_DIR = DATA_DIR / "app_assets"

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup/shutdown lifecycle."""
    _db.init(DATA_DIR, DB_FILE, APP_ASSETS_DIR)
    _db.migrate_json_to_sqlite(MATCHES_FILE)
    _db.backfill_slugs()
    _settings.init(APP_ASSETS_DIR, STATIC_DIR)
    await _sweep_orphaned_transcodes()
    _spawn_task(_backfill_hls_for_existing_videos())
    _spawn_task(_media.backfill_thumbnails(videos_dir=VIDEOS_DIR, load_matches=_load_matches))
    sweeper = asyncio.create_task(_streams.sweeper_task())
    try:
        yield
    finally:
        sweeper.cancel()
        await _media.cancel_active_transcodes()
        pending = [t for t in _background_tasks if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="Replay", lifespan=lifespan)

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


def _enrich_match(match: dict) -> dict:
    """Add computed fields to a match dict."""
    match["has_thumbnail"] = (VIDEOS_DIR / match["id"] / "thumb.jpg").is_file()
    return match


async def _load_matches() -> list[dict]:
    async with MATCHES_LOCK:
        return [_enrich_match(m) for m in _db.load_matches_unlocked()]


async def _save_matches(matches: list[dict]):
    async with MATCHES_LOCK:
        _db.save_matches_unlocked(matches)


async def _set_video_status(
    match_id: str,
    slot: str,
    status: str,
    filename: str | None,
    *,
    error_info: dict | None = None,
):
    """Persist video status + filename to the database.

    When *status* is ``"error"`` and *error_info* is provided (with keys
    ``error_code``, ``reason``, ``details``), the error is also logged to the
    ``video_errors`` table for admin diagnostics.
    """
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

    if status == "error" and error_info:
        _db.log_video_error(
            match_id,
            slot,
            error_info.get("error_code", "unknown"),
            error_info.get("reason", "Unknown error"),
            error_info.get("details", ""),
        )


async def _sweep_orphaned_transcodes():
    """Flip any 'transcoding' slot left over from a previous process to 'error'.

    Transcode jobs are in-process asyncio tasks — they cannot survive a
    container restart. Any slot still in 'transcoding' at startup is by
    definition orphaned, so move it to 'error' (with a clear error_code) so
    it shows up in the admin "Failed Slots" list and can be retried via the
    existing UI button instead of stalling forever.
    """
    matches = await _load_matches()
    orphans: list[tuple[str, str]] = []
    for match in matches:
        for slot, status in (match.get("video_status") or {}).items():
            if status == "transcoding":
                orphans.append((match["id"], slot))
    for match_id, slot in orphans:
        await _set_video_status(match_id, slot, "error", None, error_info={
            "error_code": "transcode_orphaned_at_startup",
            "reason": "Transcode worker did not survive a server restart",
            "details": "Slot was 'transcoding' when the server started — the in-process job is gone. Use Retry to start a fresh transcode from the source file.",
        })
    if orphans:
        logger.warning("Reset %d orphaned 'transcoding' slot(s) to 'error': %s",
                       len(orphans), ", ".join(f"{m}/{s}" for m, s in orphans))


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
            # Use verify_slot_assets so a partially-written master.m3u8 (from
            # a prior interrupted HLS build) is treated as missing, not complete.
            report = _media.verify_slot_assets(VIDEOS_DIR, match["id"], slot)
            if report["hls_complete"]:
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
                await _set_video_status(match_id, slot, "error", None, error_info={
                    "error_code": "disk_full",
                    "reason": "Insufficient disk space to transcode",
                    "details": f"Need {required} bytes, have {stats['free_bytes']} bytes",
                })
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


@app.get("/match")
@app.get("/match/{slug}")
@app.get("/match/{slug}/{slot}")
async def match_deep_link(slug: str | None = None, slot: str | None = None):
    """Serve the SPA shell for direct match links. The SPA's history routing
    drops the user on the season view when there's no slug or no matching
    record — preferable to a hard 404 on a stale share."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


@app.get("/live")
async def live_deep_link():
    """Serve the SPA shell for the Watch Live deep link."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


@app.get("/admin")
@app.get("/admin/{section}")
async def admin_deep_link(section: str | None = None):
    """Serve the SPA shell for /admin/* dashboard routes. Auth + role gating
    are handled client-side once the SPA boots; non-admin users land on the
    season view automatically."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


@app.get("/static/{filepath:path}")
async def static_file(filepath: str):
    filepath = filepath.split("?", 1)[0]
    if ".." in filepath:
        raise HTTPException(400, "Invalid path")
    path = (STATIC_DIR / filepath).resolve()
    if STATIC_DIR.resolve() not in path.parents and path != STATIC_DIR.resolve():
        raise HTTPException(400, "Invalid path")
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
    _auth.require_role(request, "admin")
    return await _public_settings_payload()


@app.put("/api/admin/settings")
async def update_admin_settings(request: Request):
    _auth.require_role(request, "admin")
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
    _auth.require_role(request, "admin")
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
# Live streaming (MediaMTX bridge)
# ---------------------------------------------------------------------------

async def _stream_key() -> str:
    """Cached read of the configured live stream key, generating one lazily."""
    async with MATCHES_LOCK:
        return _settings.get_or_create_stream_key_unlocked()


@app.get("/api/live/status")
async def live_status():
    """Public — does the camera have an active publish session?"""
    settings = await _load_settings()
    if settings.get("live_enabled", "1") != "1":
        return {"enabled": False, "active": False, "ready": False}
    key = await _stream_key()
    info = await _live.check_publisher_active(key)
    return {
        "enabled": True,
        "active": info["active"],
        "ready": info["ready"],
        "reachable": info.get("reachable", False),
    }


@app.api_route("/api/live/hls/{asset_path:path}", methods=["GET", "HEAD", "OPTIONS"])
async def live_hls_proxy(asset_path: str, request: Request):
    """Reverse-proxy MediaMTX's LL-HLS playlist + segments to the browser.

    Accepts HEAD so AVPlayer / AirPlay receivers can probe the URL before
    starting playback (a GET-only route returns 405 and the receiver
    silently aborts after the user enters the AirPlay PIN).  Accepts
    OPTIONS so cross-origin clients (Chromecast Default Media Receiver,
    browser fetch) can preflight.
    """
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, If-Range, If-Modified-Since, If-None-Match",
                "Access-Control-Max-Age": "86400",
            },
        )

    settings = await _load_settings()
    if settings.get("live_enabled", "1") != "1":
        raise HTTPException(404, "Live streaming is disabled")
    if not asset_path:
        raise HTTPException(400, "Missing HLS asset path")

    ip = _streams.client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    if _streams.registry.is_blocked(ip, "live", None, None):
        return Response(status_code=403, content="Stream killed by admin")

    try:
        key = await _stream_key()
        status_code, headers, body = await _live.proxy_hls(
            asset_path,
            key,
            method=request.method,
            request_headers=dict(request.headers),
        )
    except ValueError:
        raise HTTPException(400, "Invalid HLS asset path")
    except Exception as exc:
        logger.warning("Live HLS proxy error for %s: %s", asset_path, exc)
        raise HTTPException(502, "Upstream live stream unavailable")

    if request.method.upper() == "HEAD":
        return StreamingResponse(body, status_code=status_code, headers=headers)

    session = _streams.registry.touch("live", None, None, ip, user_agent)
    wrapped = _streams.wrap_iter(body, session)
    return StreamingResponse(wrapped, status_code=status_code, headers=headers)


@app.post("/api/live/auth")
async def live_auth_webhook(body: LiveAuthRequest):
    """Webhook MediaMTX calls to authorise an RTMP publish.

    Reads/api/etc. are excluded in mediamtx.yml so this only ever sees
    publish attempts.  Allow if the path matches the configured stream key.
    """
    key = await _stream_key()
    payload = body.model_dump()
    allowed, reason = _live.validate_publish_auth(payload, key)
    if not allowed:
        _live.record_rejection(payload, reason)
        logger.info(
            "Live auth rejected (%s): action=%s path=%s protocol=%s ip=%s",
            reason, body.action, body.path, body.protocol, body.ip,
        )
        raise HTTPException(401, "Invalid stream key")
    logger.info("Live auth accepted: ip=%s protocol=%s", body.ip, body.protocol)
    return {"ok": True}


@app.get("/api/admin/live/diagnostics")
async def admin_live_diagnostics(request: Request):
    """Admin: bundled diagnostics for live ingest troubleshooting."""
    _auth.require_role(request, "admin")
    key = await _stream_key()
    return await _live.get_diagnostics(key)


@app.get("/api/admin/live/config")
async def admin_live_config(request: Request):
    """Admin: full config including the stream key, plus a ready-to-paste RTMP URL."""
    _auth.require_role(request, "admin")
    settings = await _load_settings()
    key = await _stream_key()
    return {
        "enabled": settings.get("live_enabled", "1") == "1",
        "stream_key": key,
        "stream_path": _live.stream_path(key),
        "rtmp_public_url": settings.get("live_rtmp_public_url", "") or "",
        "offline_message": settings.get("live_offline_message", ""),
    }


@app.post("/api/admin/live/rotate-key")
async def admin_live_rotate_key(request: Request):
    """Admin: generate a new stream key and invalidate the old one."""
    _auth.require_role(request, "admin")
    async with MATCHES_LOCK:
        new_key = _settings.rotate_stream_key_unlocked()
    logger.info("Live stream key rotated by %s", _auth.require_auth(request)["username"])
    return {"ok": True, "stream_key": new_key, "stream_path": _live.stream_path(new_key)}


# ---------------------------------------------------------------------------
# Admin: active streaming connections
# ---------------------------------------------------------------------------

def _match_label(match_id: str) -> str | None:
    match = _db.get_match_by_id(match_id)
    if not match:
        return None
    home = match.get("home_team", "?")
    away = match.get("away_team", "?")
    return f"{home} vs {away}"


@app.get("/api/admin/streams")
async def admin_active_streams(request: Request):
    """Admin: list currently-active streaming connections + active kill blocks."""
    _auth.require_role(request, "admin")
    return {
        "active": _streams.serialize_active(match_label_resolver=_match_label),
        "blocks": _streams.registry.list_blocks(),
    }


@app.post("/api/admin/streams/{session_id}/kill")
async def admin_kill_stream(session_id: str, request: Request):
    """Admin: cancel a running stream and short-list the (ip, target) so it can't immediately reconnect."""
    user = _auth.require_role(request, "admin")
    killed = _streams.registry.kill(session_id)
    if not killed:
        raise HTTPException(404, "Session not found")
    logger.info("admin.action", extra={"action": "kill_stream", "actor": user["username"], "target_id": session_id})
    return {"ok": True, "killed": True}


@app.delete("/api/admin/streams/blocks")
async def admin_unblock_stream(payload: UnblockStreamRequest, request: Request):
    """Admin: clear a kill-block early so the affected viewer can rejoin."""
    user = _auth.require_role(request, "admin")
    key = (payload.ip, payload.kind, payload.match_id or "", payload.slot or "")
    cleared = _streams.registry.unblock(key)
    logger.info("admin.action", extra={"action": "unblock_stream", "actor": user["username"], "target_ip": payload.ip, "kind": payload.kind})
    return {"ok": True, "cleared": cleared}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request, body: LoginRequest):
    _auth.check_login_rate_limit(request)
    _auth.validate_login_origin(request)
    user = _auth.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = _auth.create_token(user["user_id"], user["role"], user["username"])
    return {"token": token, "role": user["role"], "username": user["username"]}


@app.post("/api/logout")
async def logout(request: Request):
    _auth.revoke_token(request)
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    try:
        user = _auth.require_auth(request)
        return {"authenticated": True, "role": user["role"], "username": user["username"]}
    except HTTPException:
        return {"authenticated": False}


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

@app.get("/api/users")
async def list_users(request: Request):
    _auth.require_role(request, "admin")
    users = _db.list_users()
    # Strip password hashes from response
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in users
    ]


@app.post("/api/users")
async def create_user(request: Request, body: CreateUserRequest):
    _auth.require_role(request, "admin")
    existing = _db.get_user_by_username(body.username)
    if existing:
        raise HTTPException(409, "Username already exists")
    password_hash = _auth.hash_password(body.password)
    user = _db.create_user(body.username, password_hash, body.role, body.display_name)
    return {"ok": True, "user": user}


@app.patch("/api/users/{user_id}")
async def update_user(user_id: str, request: Request, body: UpdateUserRequest):
    actor = _auth.require_role(request, "admin")
    user = _db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    updates = {}
    if body.password is not None:
        updates["password_hash"] = _auth.hash_password(body.password)
    if body.role is not None:
        updates["role"] = body.role
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.enabled is not None:
        updates["enabled"] = 1 if body.enabled else 0
    if not updates:
        return {"ok": True}
    _db.update_user(user_id, **updates)
    updated = _db.get_user_by_id(user_id)
    logger.info("admin.action", extra={"action": "update_user", "actor": actor["username"], "target_id": user_id, "fields": list(updates)})
    return {"ok": True, "user": {k: v for k, v in updated.items() if k != "password_hash"}}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    user = _auth.require_role(request, "admin")
    if not _db.delete_user(user_id):
        raise HTTPException(404, "User not found")
    logger.info("admin.action", extra={"action": "delete_user", "actor": user["username"], "target_id": user_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@app.get("/api/admin/diagnostics")
async def admin_diagnostics(request: Request):
    _auth.require_role(request, "admin")
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

    # Failed slots
    failed_slots = []
    for match in matches:
        vs = match.get("video_status") or {}
        for s, st in vs.items():
            if st == "error":
                failed_slots.append({"match_id": match["id"], "slot": s,
                                      "home_team": match.get("home_team", ""),
                                      "away_team": match.get("away_team", "")})

    # Active transcode jobs
    active_jobs = []
    for match in matches:
        vs = match.get("video_status") or {}
        for s, st in vs.items():
            if st == "transcoding":
                prog = _media.get_transcode_progress(match["id"], s)
                job = {"match_id": match["id"], "slot": s,
                       "home_team": match.get("home_team", ""),
                       "away_team": match.get("away_team", "")}
                if prog:
                    job.update({"pct": prog.get("pct", 0), "stage": prog.get("stage", ""),
                                "elapsed_s": round(time.time() - prog.get("started_at", time.time()), 1)})
                active_jobs.append(job)

    # Recent errors from DB
    recent_errors = _db.get_video_errors(limit=10)

    # Disk usage by match (top 5)
    disk_by_match = []
    if VIDEOS_DIR.is_dir():
        for d in VIDEOS_DIR.iterdir():
            if d.is_dir():
                total_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                if total_size > 0:
                    disk_by_match.append({"match_id": d.name, "bytes": total_size})
        disk_by_match.sort(key=lambda x: x["bytes"], reverse=True)
        disk_by_match = disk_by_match[:5]

    return {
        "counts": {
            "matches": len(matches),
            "transcoding_slots": transcoding_count,
            "ready_slots": ready_count,
            "failed_slots": len(failed_slots),
            "hls_missing_slots": len(hls_missing_slots),
            "active_tokens": _auth.active_token_count(),
        },
        "disk": _disk_stats_payload(),
        "disk_usage_by_match": disk_by_match,
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
        "failed_slots": failed_slots,
        "active_jobs": active_jobs,
        "recent_errors": recent_errors,
    }


@app.post("/api/admin/backfill-hls")
async def admin_backfill_hls(request: Request):
    user = _auth.require_role(request, "admin")
    result = await _backfill_hls_for_existing_videos()
    logger.info("admin.action", extra={"action": "backfill_hls", "actor": user["username"]})
    return {"ok": True, **result}


@app.get("/api/admin/matches/{match_id}/errors")
async def admin_match_errors(match_id: str, request: Request):
    _auth.require_role(request, "admin")
    errors = _db.get_video_errors(match_id=match_id, limit=50)
    return {"errors": errors}


@app.post("/api/admin/matches/{match_id}/slots/{slot}/retry")
async def admin_retry_transcode(match_id: str, slot: str, request: Request):
    """Retry a failed transcode from the existing MP4 or raw upload file."""
    user = _auth.require_role(request, "admin")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    # CAS: status 'error' → 'transcoding' inside the lock so concurrent retries
    # are rejected before either reaches the filesystem.
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        current_status = _get_video_status(match, slot)
        if current_status != "error":
            raise HTTPException(409, f"Slot status is '{current_status}', must be 'error' to retry")
        match.setdefault("video_status", {})[slot] = "transcoding"
        _db.save_matches_unlocked(matches)

    vid_dir = VIDEOS_DIR / match_id
    final_path = vid_dir / f"{slot}.mp4"

    # Prefer raw upload file if it still exists; otherwise use the MP4
    src = None
    for ext in (".mp4", ".mkv"):
        raw = vid_dir / f"{slot}_raw{ext}"
        if raw.is_file():
            src = raw
            break
    if src is None and final_path.is_file():
        # Re-transcode from the existing MP4. Promote it to a raw-named path
        # first so source and destination are distinct — transcode_video does
        # `dest.unlink(missing_ok=True)` before invoking ffmpeg, which would
        # otherwise delete its own input.
        raw_promoted = vid_dir / f"{slot}_raw.mp4"
        final_path.rename(raw_promoted)
        src = raw_promoted

    if src is None:
        # Source file missing — revert status back to error so admin can see it
        await _set_video_status(match_id, slot, "error", None, error_info={
            "error_code": "retry_source_missing",
            "reason": "No source file found for retry",
            "details": "Neither raw upload nor MP4 exists on disk",
        })
        raise HTTPException(
            404,
            "No source file found — neither raw upload nor MP4 exists on disk",
        )

    _spawn_transcode(match_id, slot, src, final_path)
    logger.info("admin.action", extra={"action": "retry_transcode", "actor": user["username"], "target_id": match_id, "slot": slot})
    return {"ok": True, "status": "transcoding", "source": src.name}


@app.post("/api/admin/matches/{match_id}/slots/{slot}/regenerate-hls")
async def admin_regenerate_hls(match_id: str, slot: str, request: Request):
    """Regenerate HLS assets from an existing MP4 without re-transcoding."""
    user = _auth.require_role(request, "admin")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    mp4_path = VIDEOS_DIR / match_id / f"{slot}.mp4"
    if not mp4_path.is_file():
        raise HTTPException(404, "MP4 file not found on disk")

    ok = await _build_hls_assets(mp4_path, match_id, slot)
    if not ok:
        raise HTTPException(500, "HLS generation failed")
    logger.info("admin.action", extra={"action": "regenerate_hls", "actor": user["username"], "target_id": match_id, "slot": slot})
    return {"ok": True, "slot": slot}


@app.post("/api/admin/matches/{match_id}/regenerate-thumbnail")
async def admin_regenerate_thumbnail(match_id: str, request: Request):
    """Regenerate the match thumbnail from a chosen (or auto-picked) ready slot.

    Optional `?slot=<full|first_half|second_half>` query param picks which
    video to extract from. Without it, falls back to the same priority order
    as the startup backfill task: full > first_half > second_half. This
    overwrites the existing thumb.jpg on disk.
    """
    user = _auth.require_role(request, "admin")
    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    requested = (request.query_params.get("slot") or "").strip()
    if requested and requested not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    slot_order = (requested,) if requested else ("full", "first_half", "second_half")
    chosen_slot = None
    for slot in slot_order:
        if _get_video_status(match, slot) == "ready":
            mp4_path = VIDEOS_DIR / match_id / f"{slot}.mp4"
            if mp4_path.is_file():
                chosen_slot = slot
                break
    if not chosen_slot:
        raise HTTPException(
            404,
            "No ready slot available — request a specific slot or wait for a transcode to complete",
        )

    mp4_path = VIDEOS_DIR / match_id / f"{chosen_slot}.mp4"
    thumb_path = VIDEOS_DIR / match_id / "thumb.jpg"
    thumb_path.unlink(missing_ok=True)
    ok = await _media.generate_thumbnail(mp4_path, thumb_path)
    if not ok:
        raise HTTPException(500, "Thumbnail generation failed")
    logger.info("admin.action", extra={"action": "regenerate_thumbnail", "actor": user["username"], "target_id": match_id, "slot": chosen_slot})
    return {"ok": True, "slot": chosen_slot}


@app.get("/api/admin/matches/{match_id}/verify")
async def admin_verify_assets(match_id: str, request: Request):
    """Check asset integrity for all slots in a match."""
    _auth.require_role(request, "admin")
    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    slots = {}
    for slot in ("full", "first_half", "second_half"):
        status = _get_video_status(match, slot)
        if status == "none":
            continue
        report = _media.verify_slot_assets(VIDEOS_DIR, match_id, slot)
        report["status"] = status
        slots[slot] = report
    return {"match_id": match_id, "slots": slots}


@app.post("/api/admin/export-database")
async def admin_export_database(request: Request):
    """Download the SQLite database file as a backup."""
    user = _auth.require_role(request, "admin")
    if not DB_FILE.is_file():
        raise HTTPException(404, "Database file not found")
    date_str = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    logger.info("admin.action", extra={"action": "export_database", "actor": user["username"]})
    return FileResponse(
        str(DB_FILE),
        media_type="application/x-sqlite3",
        headers={
            "Content-Disposition": f'attachment; filename="replay-backup-{date_str}.db"',
        },
    )


# ---------------------------------------------------------------------------
# Matches CRUD
# ---------------------------------------------------------------------------

@app.get("/api/matches")
async def list_matches(q: str | None = None, page: int | None = None, limit: int | None = None):
    if q is not None or page is not None or limit is not None:
        clamped_limit = max(1, min(limit or 50, 200))
        matches, total = _db.search_matches(q=q, page=page or 1, limit=clamped_limit)
        return {"matches": [_enrich_match(m) for m in matches], "total": total, "page": page or 1, "limit": clamped_limit}
    return await _load_matches()


@app.post("/api/matches")
async def create_match(request: Request, body: CreateMatchRequest):
    _auth.require_role(request, "admin", "uploader")
    # Timestamp prefix keeps IDs sortable in logs; the random suffix prevents
    # collisions when two POSTs land in the same millisecond (silently turning
    # the upsert into an overwrite of the first row).
    match_id = f"match-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

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
    _auth.require_role(request, "admin", "uploader")
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
    user = _auth.require_role(request, "admin")
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        # Remove from DB first while holding the lock; no concurrent request can
        # find this match_id after this point, making the subsequent rmtree safe.
        matches = [m for m in matches if m["id"] != match_id]
        _db.save_matches_unlocked(matches)
        with _db.connect() as conn:
            conn.execute("DELETE FROM upload_sessions WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM video_errors WHERE match_id = ?", (match_id,))
            conn.commit()
        for slot in ("full", "first_half", "second_half"):
            task = _transcode_tasks.pop(f"{match_id}/{slot}", None)
            if task:
                task.cancel()

    vid_dir = VIDEOS_DIR / match_id
    if vid_dir.exists():
        shutil.rmtree(str(vid_dir))
    logger.info("admin.action", extra={"action": "delete_match", "actor": user["username"], "target_id": match_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Video Upload & Streaming
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-video/session")
async def create_upload_session(match_id: str, request: Request, body: CreateUploadSessionRequest):
    _auth.require_role(request, "admin", "uploader")
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

    first_chunk_hash = body.first_chunk_hash or None
    existing = _uploads.find_active_session(match_id, slot, size_bytes, ext, first_chunk_hash)
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
                total_chunks, next_index, status, created_at, updated_at, first_chunk_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?)
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
                first_chunk_hash,
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
    _auth.require_role(request, "admin", "uploader")
    status_param = (request.query_params.get("status") or "active").strip().lower()
    if status_param == "all":
        sessions = _uploads.list_session_views(STALE_UPLOAD_SESSION_SECONDS, None)
    else:
        statuses = tuple(part.strip() for part in status_param.split(",") if part.strip())
        sessions = _uploads.list_session_views(STALE_UPLOAD_SESSION_SECONDS, statuses or ("active",))
    return {"sessions": sessions}


@app.put("/api/uploads/sessions/{session_id}/chunk")
async def upload_session_chunk(session_id: str, request: Request):
    _auth.require_role(request, "admin", "uploader")
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

    # Defense-in-depth: verify that the first chunk belongs to the same file that
    # created this session. Guards against two uploaders who both passed the same
    # (size, ext) fingerprint to bind — unlikely but conceivable.
    if index == 0 and row["first_chunk_hash"]:
        actual = hashlib.sha256(data[:65536]).hexdigest()
        if actual != row["first_chunk_hash"]:
            raise HTTPException(
                409,
                "First-chunk fingerprint mismatch — this session belongs to a different file",
            )

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
    _auth.require_role(request, "admin", "uploader")
    row = _uploads.get_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    return _uploads.session_view(row, STALE_UPLOAD_SESSION_SECONDS)


@app.delete("/api/uploads/sessions/{session_id}")
async def cancel_upload_session(session_id: str, request: Request):
    _auth.require_role(request, "admin", "uploader")
    row = _uploads.mark_session_status(session_id, "cancelled")
    if not row:
        raise HTTPException(404, "Upload session not found")
    return {"ok": True, "session": _uploads.session_view(row, STALE_UPLOAD_SESSION_SECONDS)}


@app.post("/api/uploads/sessions/cleanup")
async def cleanup_upload_sessions(request: Request):
    _auth.require_role(request, "admin")
    cleaned = _uploads.cleanup_stale_sessions(STALE_UPLOAD_SESSION_SECONDS)
    expired = _uploads.cleanup_old_completed_sessions()
    orphaned = _uploads.cleanup_orphaned_raw_files(VIDEOS_DIR)
    return {
        "ok": True,
        "cleaned_session_ids": cleaned,
        "count": len(cleaned),
        "expired_sessions": expired,
        "orphaned_files_removed": len(orphaned),
    }


@app.post("/api/uploads/sessions/{session_id}/complete")
async def complete_upload_session(session_id: str, request: Request):
    _auth.require_role(request, "admin", "uploader")
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

    # CAS: only the first concurrent /complete call wins; the conditional UPDATE
    # ensures exactly one caller transitions 'active' → 'completed' and spawns
    # the transcode task.
    with _db.connect() as conn:
        cursor = conn.execute(
            "UPDATE upload_sessions SET status = 'completed', updated_at = ? WHERE id = ? AND status = 'active'",
            (time.time(), session_id),
        )
        conn.commit()
    if cursor.rowcount != 1:
        raise HTTPException(409, "Upload session is not active")

    await _set_video_status(match_id, slot, "transcoding", None)

    logger.info(
        "Chunked upload complete: %s match=%s slot=%s size=%d",
        session_id,
        match_id,
        slot,
        actual_size,
    )
    _spawn_transcode(match_id, slot, raw_path, final_path)
    return {"ok": True, "status": "transcoding", "slot": slot, "size_mb": round(actual_size / 1e6, 1)}

@app.post("/api/matches/{match_id}/upload-video")
async def upload_video(match_id: str, file: UploadFile, request: Request):
    """Upload a video file (MP4 / MKV).  Query param: slot=full|first_half|second_half"""
    _auth.require_role(request, "admin", "uploader")
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
    _spawn_transcode(match_id, slot, raw_path, final_path)

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

    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-mp4", match_id, slot):
        raise HTTPException(403, "Stream killed by admin")

    return _range_file_response(
        vid_path, "video/mp4", request,
        match_id=match_id, slot=slot, kind="vod-mp4",
    )


@app.get("/api/matches/{match_id}/transcode-progress/{slot}")
async def transcode_progress(match_id: str, slot: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    progress = _media.get_transcode_progress(match_id, slot)
    if not progress:
        return {"active": False}
    return {"active": True, **progress}


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

    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-mp4", match_id, slot):
        raise HTTPException(403, "Stream killed by admin")

    slug_parts = [match.get("home_team", "home"), "vs", match.get("away_team", "away"), slot]
    safe_name = "_".join(re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_") or "match" for part in slug_parts)
    return _range_file_response(
        vid_path,
        "video/mp4",
        request,
        content_disposition=f'attachment; filename="{safe_name}.mp4"',
        match_id=match_id, slot=slot, kind="vod-mp4",
    )


# ---------------------------------------------------------------------------
# HLS streaming
# ---------------------------------------------------------------------------

@app.get("/api/matches/{match_id}/hls/{slot}/master.m3u8")
async def stream_hls_master(match_id: str, slot: str, request: Request):
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

    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-hls", match_id, slot):
        raise HTTPException(403, "Stream killed by admin")
    _streams.registry.touch(
        "vod-hls", match_id, slot, ip, request.headers.get("user-agent", ""),
    )

    return FileResponse(
        str(master_path),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "public, max-age=3600, immutable"},
    )


@app.get("/api/matches/{match_id}/hls/{slot}/{asset_path:path}")
async def stream_hls_asset(match_id: str, slot: str, asset_path: str, request: Request):
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

    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-hls", match_id, slot):
        raise HTTPException(403, "Stream killed by admin")
    sess = _streams.registry.touch(
        "vod-hls", match_id, slot, ip, request.headers.get("user-agent", ""),
    )
    # Approximate bytes_sent — FileResponse buffers internally so this is the
    # closest we can get without an ASGI-level wrapper.
    try:
        sess.bytes_sent += target_path.stat().st_size
    except OSError:
        pass

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


def _range_file_response(
    file_path: Path,
    media_type: str,
    request: Request,
    content_disposition: str | None = None,
    *,
    match_id: str | None = None,
    slot: str | None = None,
    kind: str | None = None,
):
    """Serve a file with Range-request support for video seeking.

    When ``kind`` is supplied, the active byte transfer is registered with
    the streams registry so admins can see and kill it.
    """
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

        session = None
        if kind:
            session = _streams.registry.register_long(
                kind, match_id, slot,
                _streams.client_ip(request),
                request.headers.get("user-agent", ""),
            )

        def _iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    if session is not None and session.cancel.is_set():
                        break
                    chunk = f.read(min(VIDEO_STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    if session is not None:
                        _streams.registry.add_bytes(session.id, len(chunk))
                    yield chunk

        body = _iter_range()
        if session is not None:
            body = _wrap_unregister(body, session.id)

        return StreamingResponse(
            body,
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


def _wrap_unregister(body, session_id: str):
    """Generator wrapper that always unregisters the session on iterator close."""
    try:
        for chunk in body:
            yield chunk
    finally:
        _streams.registry.unregister(session_id)


# ---------------------------------------------------------------------------
# Logo Upload & Serving
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-logo")
async def upload_logo(match_id: str, file: UploadFile, request: Request):
    """Upload a team logo.  Query param: team=home|away"""
    _auth.require_role(request, "admin", "uploader")
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


@app.get("/api/matches/{match_id}/thumbnail")
async def serve_thumbnail(match_id: str):
    thumb_path = VIDEOS_DIR / match_id / "thumb.jpg"
    if not thumb_path.is_file():
        raise HTTPException(404, "No thumbnail available")
    # Validate against mtime so admins regenerating the thumbnail see the new
    # one immediately, but cached copies are still served when unchanged.
    mtime = int(thumb_path.stat().st_mtime)
    headers = {
        "Cache-Control": "no-cache, must-revalidate",
        "ETag": f'"{mtime}"',
    }
    return FileResponse(str(thumb_path), media_type="image/jpeg", headers=headers)


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
