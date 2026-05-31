"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8091)
"""

from __future__ import annotations

__version__ = "1.0.0"

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from contextlib import asynccontextmanager, suppress

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
from routers.admin import router as admin_router
from routers.admin_ops import router as admin_ops_router
from routers.auth import router as auth_router
from routers.live import router as live_router
from routers.matches import router as matches_router
from routers.settings import router as settings_router
from routers.uploads import router as uploads_router
from services import activity as _activity
from services import jobs as _jobs
from services import thumbnails as _thumbs
from models import (
    CreateMatchRequest,
    CreateUploadSessionRequest, LiveAuthRequest,
    StartCaptureRequest, UnblockStreamRequest,
    UpdateMatchRequest,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logger = _log.setup("replay")


def _now_ms() -> str:
    """Return current UTC time as ISO-8601 with millisecond precision, e.g. 2026-01-02T03:04:05.678Z."""
    t = time.time()
    ms = int(t * 1000) % 1000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{ms:03d}Z"

DATA_DIR = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))

# Single-team VOD: the durable jobs queue still carries a team_id column, so
# all internally-enqueued jobs (transcodes) use this constant tenant id.
DEFAULT_JOB_TEAM_ID = "default"

# ---------------------------------------------------------------------------
# Background task registry (M4)
# ---------------------------------------------------------------------------

_background_tasks: set[asyncio.Task] = set()

# Transcode tasks keyed by "{match_id}/{slot}" so delete_match can cancel them.
_transcode_tasks: dict[str, asyncio.Task] = {}

# Regen-HLS tasks keyed by "{match_id}/{slot}". Tracked separately from
# _transcode_tasks because regen doesn't change the slot's video_status
# (the MP4 is still ready) — we just need to know which slots are
# rebuilding their HLS ladder so the admin diagnostics endpoint can
# surface a "regenerating HLS" pill and the frontend can poll for
# completion. Cleared on task completion.
#
# Value is (task, started_monotonic_seconds) so the diagnostics endpoint
# can publish elapsed time per slot. Time is monotonic so NTP jumps don't
# corrupt the elapsed value.
_regen_hls_tasks: dict[str, tuple[asyncio.Task, float]] = {}


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


async def _job_recovery_loop(interval_seconds: float = 30.0) -> None:
    """Periodically recover expired durable job leases during app runtime."""
    while True:
        try:
            result = _jobs.recover_stuck()
            if result.get("requeued") or result.get("failed"):
                logger.warning(
                    "Recovered stuck background jobs: requeued=%s failed=%s",
                    result.get("requeued", 0),
                    result.get("failed", 0),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Background job stuck-recovery sweep failed: %s", exc)
        await asyncio.sleep(interval_seconds)


async def _job_heartbeat_loop(job_id: int, worker_id: str, *, interval_seconds: float = 300.0, lease_seconds: int = 3600) -> None:
    """Keep long in-process jobs from expiring while their worker is still alive."""
    while True:
        await asyncio.sleep(interval_seconds)
        if _jobs.heartbeat(job_id, worker_id, lease_seconds=lease_seconds) != 1:
            logger.warning("Background job %s heartbeat was not accepted for worker %s", job_id, worker_id)
            return


def _spawn_transcode(match_id: str, slot: str, src, dest) -> asyncio.Task:
    """Spawn a tracked transcode task, registering it for per-match cancellation."""
    key = f"{match_id}/{slot}"
    job_id = _jobs.enqueue(
        "transcode",
        {"match_id": match_id, "slot": slot, "src": str(src), "dest": str(dest)},
        team_id=DEFAULT_JOB_TEAM_ID,
    )
    worker_id = f"in-process-transcode:{key}:{job_id}"
    task = _spawn_task(_run_transcode_job(job_id, worker_id, match_id, slot, src, dest))
    _transcode_tasks[key] = task
    def _cleanup(_):
        _transcode_tasks.pop(key, None)
    task.add_done_callback(_cleanup)
    return task


async def _run_transcode_job(job_id: int, worker_id: str, match_id: str, slot: str, src, dest) -> None:
    """Bridge a durable transcode job row to the existing in-process transcode path."""
    job = _jobs.start(job_id, worker_id, lease_seconds=3600)
    if job is None:
        logger.warning("Transcode job %s was not pending when task started", job_id)
        return
    if not _db.get_match_by_id(match_id):
        _jobs.fail(job_id, worker_id, "transcode resource no longer exists")
        return
    heartbeat_task = asyncio.create_task(_job_heartbeat_loop(job_id, worker_id))
    try:
        await _transcode_video(match_id, slot, src, dest)
    except asyncio.CancelledError:
        _jobs.fail(job_id, worker_id, "transcode task cancelled")
        raise
    except Exception as exc:
        _jobs.fail(job_id, worker_id, str(exc))
        raise
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
    refreshed = _db.get_match_by_id(match_id)
    status = _get_video_status(refreshed, slot) if refreshed else None
    if status == "ready":
        _jobs.complete(job_id, worker_id, {"match_id": match_id, "slot": slot, "status": status})
    else:
        error_text = "transcode finished without ready status"
        if refreshed:
            error_info = (refreshed.get("video_errors") or {}).get(slot) if isinstance(refreshed.get("video_errors"), dict) else None
            if error_info:
                error_text = json.dumps(error_info, separators=(",", ":"))
        _jobs.fail(job_id, worker_id, error_text)


STATIC_DIR = Path(__file__).parent
MATCHES_FILE = DATA_DIR / "matches.json"
DB_FILE = DATA_DIR / "replay.db"
VIDEOS_DIR = DATA_DIR / "videos"
APP_ASSETS_DIR = DATA_DIR / "app_assets"

# Optional staging directory for the SPA's static assets (script.js, styles.css,
# js/, logo.png). When set, the replay container populates this directory on
# startup so Caddy — which can't read from /app on the replay container — can
# bind-mount it read-only and serve /static/* via sendfile() instead of paying
# uvicorn's overhead per request. See `_stage_static_assets` and the
# `replay_static` named volume in docker-compose-intel.yml.
STATIC_EXPORT_DIR = (
    Path(os.environ["REPLAY_STATIC_EXPORT_DIR"])
    if os.environ.get("REPLAY_STATIC_EXPORT_DIR")
    else None
)

# Files / dirs (relative to STATIC_DIR) that the SPA needs at /static/*.
# Anything outside this allowlist stays on the replay app (Python endpoint
# still serves it). Whitelisting keeps us from accidentally shipping things
# like .env, *.py, or replay.db into Caddy's serving root.
#
# `index.html` is intentionally NOT exported — the SPA shell goes through
# the FastAPI rendering route at `/`, `/match/...`, etc., not `/static/`.
_STATIC_EXPORT_PATHS = (
    "script.js",
    "styles.css",
    "styles",       # split CSS modules loaded by index.html
    "logo.png",
    "js",           # whole directory (utils.js, api.js, etc.)
)

# Cold storage for raw uploads + finished MP4s. Set REPLAY_ORIGINALS_DIR to a
# bind mount on a separate (cheaper, larger) pool to keep the SSD pool free
# for HLS segments + thumbnails. When unset, falls back to VIDEOS_DIR for the
# legacy single-volume layout (no migration required for existing deploys).
ORIGINALS_DIR = Path(os.environ.get("REPLAY_ORIGINALS_DIR") or str(VIDEOS_DIR))

def _stage_static_assets() -> dict:
    """Copy the SPA's static assets from STATIC_DIR to STATIC_EXPORT_DIR.

    No-op when REPLAY_STATIC_EXPORT_DIR is unset (single-container layout
    where uvicorn serves /static/* directly). When set, runs at startup and
    syncs each entry in `_STATIC_EXPORT_PATHS` over to the export directory,
    preserving mtimes via shutil.copy2 so subsequent runs only re-copy what
    actually changed.

    The export directory becomes a shared named volume; Caddy mounts it
    read-only at /srv/static and serves /static/* via sendfile().

    Returns a small dict for logging — copy/skip counts + the export root.
    """
    if STATIC_EXPORT_DIR is None:
        return {"enabled": False}
    STATIC_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    src_root = STATIC_DIR.resolve()
    dst_root = STATIC_EXPORT_DIR.resolve()
    copied = 0
    skipped = 0

    def _sync_file(src: Path, dst: Path) -> None:
        nonlocal copied, skipped
        try:
            src_st = src.stat()
        except FileNotFoundError:
            # Allowlisted path that doesn't exist in this build (e.g. an
            # asset that was renamed) — silently skip rather than fail boot.
            return
        try:
            dst_st = dst.stat()
        except FileNotFoundError:
            dst_st = None
        # Re-copy when sizes or mtimes diverge. Cheaper than reading both
        # files to byte-compare; "good enough" because dst is owned only
        # by this process.
        if (dst_st is not None and dst_st.st_size == src_st.st_size
                and int(dst_st.st_mtime) == int(src_st.st_mtime)):
            skipped += 1
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    for rel in _STATIC_EXPORT_PATHS:
        src = src_root / rel
        dst = dst_root / rel
        if src.is_dir():
            for child in src.rglob("*"):
                if not child.is_file():
                    continue
                rel_child = child.relative_to(src_root)
                _sync_file(child, dst_root / rel_child)
        elif src.is_file():
            _sync_file(src, dst)

    return {
        "enabled": True,
        "export_dir": str(STATIC_EXPORT_DIR),
        "copied": copied,
        "skipped": skipped,
    }


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup/shutdown lifecycle."""
    _db.init(DATA_DIR, DB_FILE, APP_ASSETS_DIR)
    _db.migrate_json_to_sqlite(MATCHES_FILE)
    _db.backfill_slugs()
    _settings.init(APP_ASSETS_DIR, STATIC_DIR)
    # Resize the transcode semaphore to whatever the settings table says
    # (which itself reflects the env-var fallback on first boot).
    await TRANSCODE_SEMAPHORE.resize(current_transcode_concurrency())
    await _sweep_orphaned_transcodes()
    _uploads.cleanup_stale_sessions(current_stale_upload_session_seconds())
    # Drop any <slot>.tmp / <slot>.old staging dirs left over from a regen
    # that crashed or was killed by the previous container's exit. The
    # atomic-rename swap in media.build_hls_assets normally cleans these
    # up itself; this catches the case where the container died between
    # rename steps.
    try:
        removed = _media.cleanup_hls_staging_dirs(VIDEOS_DIR)
        if removed:
            logger.info("Swept %d orphan HLS staging dir(s) on startup.", removed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HLS staging-dir cleanup failed: %s", exc)
    # Make sure the originals directory exists. When tiered (different
    # path from VIDEOS_DIR), the host side is a bind mount and the
    # mountpoint inside the container needs to exist before first write.
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    # Stage SPA static assets to the shared volume Caddy serves. No-op when
    # REPLAY_STATIC_EXPORT_DIR is unset (single-container layout).
    static_report = _stage_static_assets()
    if static_report.get("enabled"):
        logger.info(
            "Staged static assets to %s (copied=%d, skipped=%d)",
            static_report["export_dir"], static_report["copied"], static_report["skipped"],
        )
    _spawn_task(_backfill_hls_for_existing_videos())
    _spawn_task(_media.backfill_thumbnails(
        videos_dir=VIDEOS_DIR, originals_dir=ORIGINALS_DIR, load_matches=_load_matches,
    ))
    sweeper = asyncio.create_task(_streams.sweeper_task())
    job_recovery = asyncio.create_task(_job_recovery_loop())
    try:
        yield
    finally:
        sweeper.cancel()
        job_recovery.cancel()
        with suppress(asyncio.CancelledError):
            await job_recovery
        await _media.cancel_active_transcodes()
        pending = [t for t in _background_tasks if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="Replay", version=__version__, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_ops_router)
app.include_router(live_router)
app.include_router(matches_router)
app.include_router(settings_router)
app.include_router(uploads_router)


# Shared secret MediaMTX sends in X-Internal-Secret when calling /api/live/auth.
# Configure via mediamtx.yml authHTTPHeaders. If unset the endpoint is open
# (backwards-compatible) but logs a warning on first request.
LIVE_AUTH_SECRET = os.environ.get("LIVE_AUTH_SECRET", "")
LIVE_AUTH_ALLOW_INSECURE = os.environ.get("LIVE_AUTH_ALLOW_INSECURE", "0") == "1"

# All other tuning knobs are now stored in the settings table (with env-var
# fallback on first boot — see settings.TUNING_KNOBS). Read them via the
# helpers below. _DEFAULT_TRANSCODE_CONCURRENCY is only used for the initial
# semaphore size at import time; the actual size tracks the setting via
# `ResizableSemaphore.resize()` whenever the admin updates it.
_DEFAULT_TRANSCODE_CONCURRENCY = max(
    1, int(os.environ.get("TRANSCODE_CONCURRENCY", "2"))
)


class ResizableSemaphore:
    """Semaphore whose limit can grow or shrink at runtime.

    Widening: release the wrapped semaphore (n_new - n_old) extra times so
    additional waiters proceed. Narrowing: stash a "shrink debt" counter and
    swallow that many releases inside `release()` until we're back at the new
    limit. In-flight holders are never disturbed — they just complete normally.
    """

    def __init__(self, n: int):
        n = max(1, int(n))
        self._inner = asyncio.Semaphore(n)
        self._n = n
        self._shrink_debt = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self._inner.acquire()

    def release(self) -> None:
        if self._shrink_debt > 0:
            self._shrink_debt -= 1
            return
        self._inner.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    @property
    def limit(self) -> int:
        return self._n

    async def resize(self, new_n: int) -> None:
        new_n = max(1, int(new_n))
        async with self._lock:
            delta = new_n - self._n
            if delta > 0:
                for _ in range(delta):
                    self._inner.release()
            elif delta < 0:
                self._shrink_debt += -delta
            self._n = new_n


TRANSCODE_SEMAPHORE = ResizableSemaphore(_DEFAULT_TRANSCODE_CONCURRENCY)
MATCHES_LOCK = asyncio.Lock()
HLS_BACKFILL_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Tuning knob accessors — read live values from the settings table.
# Each call hits `_settings.load_unlocked()` which is a single SELECT against
# the settings table; cheap, and means UI changes take effect immediately.
# ---------------------------------------------------------------------------

def _settings_snapshot() -> dict[str, str]:
    return _settings.load_unlocked()


def current_max_upload_size_bytes() -> int:
    return _settings.get_int(_settings_snapshot(), "max_upload_size_bytes", 12 * 1024 * 1024 * 1024)


def current_upload_chunk_size_bytes() -> int:
    return _settings.get_int(_settings_snapshot(), "upload_chunk_size_bytes", 16 * 1024 * 1024)


def current_transcode_concurrency() -> int:
    return _settings.get_int(_settings_snapshot(), "transcode_concurrency", 2)


def current_min_free_disk_bytes() -> int:
    return _settings.get_int(_settings_snapshot(), "min_free_disk_bytes", 20 * 1024 * 1024 * 1024)


def current_upload_disk_headroom_multiplier() -> float:
    return _settings.get_float(_settings_snapshot(), "upload_disk_headroom_multiplier", 2.2)


def current_stale_upload_session_seconds() -> int:
    return _settings.get_int(_settings_snapshot(), "stale_upload_session_seconds", 6 * 60 * 60)


def current_video_stream_chunk_bytes() -> int:
    return _settings.get_int(_settings_snapshot(), "video_stream_chunk_bytes", 1024 * 1024)


def current_hls_segment_duration() -> int:
    return _settings.get_int(_settings_snapshot(), "hls_segment_duration", 6)


def current_hls_variant_presets() -> list[dict]:
    return _settings.get_hls_variant_presets(_settings_snapshot())


def current_replay_hwaccel() -> str:
    return _settings.get_str(_settings_snapshot(), "replay_hwaccel", "auto")

# Per-IP rate limit for /api/live/auth to prevent log-spam from scanners.
_live_auth_attempts: dict[str, list[float]] = {}
_LIVE_AUTH_RATE_LIMIT = 30
_LIVE_AUTH_RATE_WINDOW = 60.0

# HLS variant ladder is now stored in the settings table; read it via
# `current_hls_variant_presets()` whenever a transcode is about to start.

# ---------------------------------------------------------------------------
# Async wrappers around module functions (lock-protected)
# ---------------------------------------------------------------------------


async def _load_settings() -> dict[str, str]:
    async with MATCHES_LOCK:
        return _settings.load_unlocked()


async def _save_settings(updates: dict[str, str], *, actor: str | None = None) -> dict[str, str]:
    async with MATCHES_LOCK:
        return _settings.save_unlocked(updates, actor=actor)


async def _public_settings_payload() -> dict:
    settings = await _load_settings()
    return _settings.public_payload(settings)


async def _admin_settings_payload() -> dict:
    settings = await _load_settings()
    payload = _settings.admin_payload(settings)
    payload["audit"] = _settings.list_audit_entries(20)
    return payload


_log_activity = _activity.log_activity
_streams.set_activity_logger(_activity.stream_activity_logger)


def _thumb_path_within_videos_dir(thumb: Path) -> bool:
    return _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR)


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
    old_status = None
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            return
        if "video_status" not in match:
            match["video_status"] = {}
        old_status = match["video_status"].get(slot)
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
    if old_status != status:
        if status == "transcoding":
            _log_activity(
                "transcode.started",
                severity="info",
                message="Transcode started",
                match_id=match_id,
                slot=slot,
                metadata={"old_status": old_status},
            )
        elif status == "ready":
            _log_activity(
                "transcode.succeeded",
                severity="success",
                message="Transcode finished",
                match_id=match_id,
                slot=slot,
                metadata={"old_status": old_status, "filename": filename or ""},
            )
        elif status == "error":
            info = error_info or {}
            _log_activity(
                "transcode.failed",
                severity="error",
                message=info.get("reason") or "Transcode failed",
                match_id=match_id,
                slot=slot,
                metadata={
                    "old_status": old_status,
                    "error_code": info.get("error_code", "unknown"),
                    "details": info.get("details", ""),
                },
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

def _team_id_for_match(match_or_id) -> str | None:
    # Single-team VOD: matches are no longer team-scoped, so all media lives
    # in the flat legacy layout (`<root>/<match_id>/...`). Returning None makes
    # every media path helper resolve to that layout.
    return None


def _slot_hls_dir(match_id: str, slot: str) -> Path:
    return _media.existing_slot_hls_dir(VIDEOS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _slot_hls_write_dir(match_id: str, slot: str) -> Path:
    return _media.slot_hls_dir(VIDEOS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _slot_hls_master_path(match_id: str, slot: str) -> Path:
    return _media.existing_slot_hls_master_path(VIDEOS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _slot_mp4_path(match_id: str, slot: str) -> Path:
    """Finished MP4 read path. Try team-aware storage, then legacy."""
    return _media.existing_slot_mp4_path(ORIGINALS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _slot_mp4_write_path(match_id: str, slot: str) -> Path:
    """Finished MP4 write path. New transcodes land in team-aware storage."""
    return _media.slot_mp4_path(ORIGINALS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _slot_raw_path(match_id: str, slot: str, ext: str) -> Path:
    """Raw upload destination for a slot. Cold pool when tiered."""
    return _media.slot_raw_path(ORIGINALS_DIR, match_id, slot, ext, team_id=_team_id_for_match(match_id))


def _find_slot_raw_path(match_id: str, slot: str) -> Path | None:
    """Existing raw upload (.mp4 then .mkv), or None."""
    return _media.find_slot_raw_path(ORIGINALS_DIR, match_id, slot, team_id=_team_id_for_match(match_id))


def _ready_slots_missing_hls(matches: list[dict]) -> list[tuple[str, str, str | None]]:
    missing = []
    for match in matches:
        slots = ["full"] if match.get("format") != "two_halves" else ["first_half", "second_half"]
        for slot in slots:
            if _get_video_status(match, slot) != "ready":
                continue
            mp4_path = _slot_mp4_path(match["id"], slot)
            if not mp4_path.is_file():
                continue
            # Use verify_slot_assets so a partially-written master.m3u8 (from
            # a prior interrupted HLS build) is treated as missing, not complete.
            report = _media.verify_slot_assets(VIDEOS_DIR, match["id"], slot, originals_dir=ORIGINALS_DIR, team_id=match.get("team_id"))
            if report["hls_complete"]:
                continue
            missing.append((match["id"], slot, match.get("team_id")))
    return missing


# ---------------------------------------------------------------------------
# Disk space
# ---------------------------------------------------------------------------

def _required_free_bytes(size_bytes: int) -> int:
    return max(
        current_min_free_disk_bytes(),
        int(math.ceil(size_bytes * current_upload_disk_headroom_multiplier())),
    )


def _pool_stats(path: Path) -> dict | None:
    """`shutil.disk_usage` wrapped + tagged. None if the path can't be stat'd
    (e.g. a temporarily unavailable bind mount). Used by both the upload
    pre-flight guard and the diagnostics endpoints."""
    try:
        total, used, free = shutil.disk_usage(path)
    except OSError:
        return None
    return {"path": str(path), "total": total, "used": used, "free": free}


def _disk_stats_payload(required_bytes: int | None = None) -> dict:
    """Per-pool free space + the headroom guard the uploader must satisfy.

    The guard targets `ORIGINALS_DIR` (where raw uploads + finished MP4s
    actually land — see PR #18 storage tiering). On legacy single-volume
    layouts ORIGINALS_DIR aliases VIDEOS_DIR, so this is just one pool.
    The historical top-level `free_bytes` / `enough_space` keys are kept
    pointing at the originals pool so existing callers (admin diagnostics
    UI, the transcode pre-flight) get the right answer without code
    changes.
    """
    ssd = _pool_stats(DATA_DIR)
    # Walk the cold pool only when it differs from DATA_DIR. ORIGINALS_DIR
    # may live anywhere under or outside DATA_DIR; resolved-path equality
    # catches symlink aliasing too.
    pools: dict = {"ssd": ssd}
    cold = None
    try:
        same_pool = ORIGINALS_DIR.resolve() == DATA_DIR.resolve()
    except OSError:
        same_pool = False
    if not same_pool:
        cold = _pool_stats(ORIGINALS_DIR)
        pools["originals"] = cold

    # Target pool for an upload is the cold pool when tiered, else SSD.
    target = cold if cold is not None else ssd
    target_free = target["free"] if target else 0
    target_total = target["total"] if target else 0
    target_used = target["used"] if target else 0

    return {
        "total_bytes": target_total,
        "used_bytes": target_used,
        "free_bytes": target_free,
        "min_free_bytes": current_min_free_disk_bytes(),
        "required_bytes": required_bytes,
        "upload_headroom_multiplier": current_upload_disk_headroom_multiplier(),
        "enough_space": required_bytes is None or target_free >= required_bytes,
        "target_pool": "originals" if cold is not None else "ssd",
        "pools": pools,
    }


def _ensure_disk_space(size_bytes: int):
    required_bytes = _required_free_bytes(size_bytes)
    stats = _disk_stats_payload(required_bytes)
    if stats["free_bytes"] < required_bytes:
        pool_label = stats.get("target_pool", "ssd")
        raise HTTPException(
            507,
            (
                f"Insufficient free disk space on the {pool_label} pool for upload. "
                f"Need about {required_bytes} bytes free and only have {stats['free_bytes']} bytes."
            ),
        )


# ---------------------------------------------------------------------------
# Helpers — Media pipeline (delegated to media.py)
# ---------------------------------------------------------------------------

def _media_kwargs() -> dict:
    """Snapshot the live tuning settings for a single media call. Called per-job
    so admin edits to segment duration / ladder / hwaccel take effect on the
    next transcode without a restart."""
    return dict(
        videos_dir=VIDEOS_DIR,
        hls_segment_duration=current_hls_segment_duration(),
        hls_variant_presets=current_hls_variant_presets(),
        hwaccel_preference=current_replay_hwaccel(),
    )


async def _build_hls_assets(source_mp4: Path, match_id: str, slot: str) -> bool:
    return await _media.build_hls_assets(
        source_mp4, match_id, slot, **_media_kwargs(), team_id=_team_id_for_match(match_id)
    )


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
        **_media_kwargs(),
        transcode_semaphore=TRANSCODE_SEMAPHORE,
        transcode_concurrency=current_transcode_concurrency(),
        set_video_status=_set_video_status,
        team_id=_team_id_for_match(match_id),
    )


async def _backfill_hls_for_existing_videos() -> dict:
    return await _media.backfill_hls_for_existing_videos(
        **_media_kwargs(),
        originals_dir=ORIGINALS_DIR,
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


# Dev-only: when REPLAY_DEV=1, rewrite ES-module `import './js/foo.js'`
# statements at serve time so each import URL carries `?v=<mtime_ns>`. This
# closes the soft-refresh staleness gap — without it, a Cmd+R after editing
# a js/*.js module would re-fetch script.js (already versioned) but reuse
# the disk-cached module because
# the `import './js/foo.js'` URL never changes. With this on, every save
# flips the URL the import resolves to.
# Strictly opt-in via env var so prod is byte-for-byte unchanged.
_REPLAY_DEV = os.environ.get("REPLAY_DEV", "").strip().lower() in ("1", "true", "yes")

_DEV_IMPORT_RE = re.compile(rb"""(import\s+(?:[\w*{}\s,]+\s+from\s+)?['"])(\./js/[\w-]+\.js)(['"])""")


def _rewrite_dev_imports(path: Path, body: bytes) -> bytes:
    """Add ?v=<mtime_ns> to relative ./js/*.js imports inside script.js / js/*.js."""
    static_root = STATIC_DIR.resolve()
    def repl(match: "re.Match[bytes]") -> bytes:
        rel = match.group(2).decode()  # "./js/foo.js"
        target = (path.parent / rel).resolve()
        try:
            target.relative_to(static_root)  # safety: stay inside /static
            v = target.stat().st_mtime_ns
        except (FileNotFoundError, ValueError):
            return match.group(0)
        new_url = f"{rel}?v={v}".encode()
        return match.group(1) + new_url + match.group(3)
    return _DEV_IMPORT_RE.sub(repl, body)


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

    # Dev-only soft-refresh helper: rewrite JS module imports to include
    # ?v=<mtime>. Off by default; set REPLAY_DEV=1 to enable.
    if _REPLAY_DEV and path.suffix == ".js":
        body = path.read_bytes()
        rewritten = _rewrite_dev_imports(path, body)
        return Response(
            content=rewritten,
            media_type=mt,
            headers={"Cache-Control": cache_header},
        )

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

# ---------------------------------------------------------------------------
# Live streaming (MediaMTX bridge)
# ---------------------------------------------------------------------------

async def _stream_key() -> str:
    """Cached read of the configured live stream key, generating one lazily."""
    async with MATCHES_LOCK:
        return _settings.get_or_create_stream_key_unlocked()


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


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

_diag_disk_cache: dict = {"ts": 0.0, "data": []}


def _cached_disk_usage_by_match() -> list[dict]:
    """Walk VIDEOS_DIR + ORIGINALS_DIR to tally per-match disk use, cached
    for 60 s. When tiered (different paths), totals are summed across both
    trees so the admin sees the true on-disk footprint of each match."""
    now = time.time()
    if now - _diag_disk_cache["ts"] < 60:
        return _diag_disk_cache["data"]
    totals: dict[str, int] = {}
    seen_roots: set = set()
    for root in (VIDEOS_DIR, ORIGINALS_DIR):
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen_roots or not root.is_dir():
            continue
        seen_roots.add(resolved)
        for d in root.iterdir():
            if not d.is_dir():
                continue
            try:
                total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            except OSError:
                continue
            if total > 0:
                totals[d.name] = totals.get(d.name, 0) + total
    result = sorted(
        ({"match_id": k, "bytes": v} for k, v in totals.items()),
        key=lambda x: x["bytes"], reverse=True,
    )[:5]
    _diag_disk_cache["ts"] = now
    _diag_disk_cache["data"] = result
    return result


# ---------------------------------------------------------------------------
# Performance Tuning panel — host signals, throughput rollups, transcode RT
# ---------------------------------------------------------------------------

try:
    import psutil as _psutil  # type: ignore
except Exception:  # pragma: no cover — psutil is in requirements.txt
    _psutil = None

# NIC byte counters from the previous /api/admin/performance call. Used to
# compute per-NIC bytes-per-second deltas without forcing the caller to poll.
_perf_prev_net: dict = {"ts": 0.0, "tx": 0, "rx": 0}

# Previous iGPU busy reading per engine — required because i915's `busy`
# sysfs file is a monotonic ns-since-boot counter. A single read is
# meaningless; only the delta between two reads taken `dt` seconds apart
# yields a real busy %. None on first call (returns None to the caller).
_perf_prev_gpu: dict = {"ts": 0.0, "engines": {}}  # name → ns-since-boot


def _intel_gpu_busy_pct() -> float | None:
    """Estimate iGPU busy % by diffing two reads of the i915 per-engine
    `busy` sysfs counter. Returns None if the sysfs files don't exist
    (non-Intel host) or this is the first call (no previous sample to
    diff against).

    Pattern matches the NIC bps delta a few lines down: cache the last
    reading on the module, compute (curr - prev) / (now - prev_ts) on the
    next call, and clamp to [0, 100].
    """
    base = Path("/sys/class/drm/card0/engine")
    if not base.exists():
        return None
    now = time.time()
    curr: dict[str, int] = {}
    for engine_dir in base.iterdir():
        busy_file = engine_dir / "busy"
        if busy_file.is_file():
            try:
                curr[engine_dir.name] = int(busy_file.read_text().strip())
            except (OSError, ValueError):
                continue
    if not curr:
        return None

    prev = _perf_prev_gpu
    prev_engines = prev.get("engines") or {}
    dt = now - prev.get("ts", 0.0)
    # Update the cache before any early-return so the *next* call has a
    # baseline to diff against.
    _perf_prev_gpu.update(ts=now, engines=curr)

    if not prev_engines or dt <= 0:
        return None

    # Average per-engine busy ratios. Each engine's `busy` advances by at
    # most `dt * 1e9` ns (one full second of GPU time per wall second), so
    # delta_ns / (dt * 1e9) gives a 0..1 fraction; multiply by 100.
    ratios: list[float] = []
    for name, ns in curr.items():
        prev_ns = prev_engines.get(name)
        if prev_ns is None:
            continue  # engine appeared mid-flight; wait for next call
        delta = max(0, ns - prev_ns)
        pct = (delta / (dt * 1_000_000_000.0)) * 100.0
        ratios.append(min(100.0, max(0.0, pct)))
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 1)


def _host_signals() -> dict:
    """Snapshot of CPU/RAM/swap/load/NIC. Falls back gracefully if psutil
    is missing (returns just `os.getloadavg`)."""
    out: dict = {}
    try:
        out["loadavg"] = list(os.getloadavg())
    except (OSError, AttributeError):
        out["loadavg"] = None

    if _psutil is None:
        out["psutil_available"] = False
        return out

    out["psutil_available"] = True
    try:
        out["cpu_percent"] = _psutil.cpu_percent(interval=None)
        out["cpu_count"] = _psutil.cpu_count(logical=True)
    except Exception:
        out["cpu_percent"] = None
        out["cpu_count"] = None
    try:
        vm = _psutil.virtual_memory()
        out["memory"] = {
            "total": vm.total, "available": vm.available, "used": vm.used,
            "percent": vm.percent,
        }
    except Exception:
        out["memory"] = None
    try:
        sm = _psutil.swap_memory()
        out["swap"] = {"total": sm.total, "used": sm.used, "percent": sm.percent}
    except Exception:
        out["swap"] = None

    # Per-NIC bytes; fold into a single tx/rx delta for the panel.
    try:
        now = time.time()
        net = _psutil.net_io_counters(pernic=False)
        prev = _perf_prev_net
        delta_seconds = max(0.001, now - prev["ts"]) if prev["ts"] else None
        out["net"] = {
            "bytes_sent_total": net.bytes_sent,
            "bytes_recv_total": net.bytes_recv,
        }
        if delta_seconds is not None:
            out["net"]["bps_tx"] = round(max(0, net.bytes_sent - prev["tx"]) * 8 / delta_seconds, 1)
            out["net"]["bps_rx"] = round(max(0, net.bytes_recv - prev["rx"]) * 8 / delta_seconds, 1)
        _perf_prev_net.update(ts=now, tx=net.bytes_sent, rx=net.bytes_recv)
    except Exception:
        out["net"] = None

    out["intel_gpu_busy_pct"] = _intel_gpu_busy_pct()
    return out


def _disk_pools() -> dict:
    """Free/used for the SSD (DATA_DIR) plus the originals dir if it differs.

    Mirrors the `pools` sub-dict in `_disk_stats_payload` so the Performance
    Tuning panel surfaces cold-pool capacity alongside the SSD pool. When
    ORIGINALS_DIR aliases DATA_DIR (single-volume layout), only `ssd` is
    populated.
    """
    return _disk_stats_payload()["pools"]


async def _run_regen_hls_task(match_id: str, slot: str, mp4_path: Path, actor: str):
    """Background worker: rebuilds the HLS variant ladder for *match_id/slot*.

    Spawned by the admin regen-hls endpoint so the HTTP response can return
    202 Accepted in <100 ms instead of holding the connection open for
    minutes — Cloudflare's 100 s edge timeout was returning 524 to the
    browser even though the server was still working.

    All failure paths log to ``video_errors`` so they surface in the admin
    Recent Errors panel; the response from the original POST is already
    long gone by the time those happen.
    """
    try:
        ok = await _build_hls_assets(mp4_path, match_id, slot)
    except Exception as exc:
        logger.exception(
            "regen_hls.crash %s/%s: %s", match_id, slot, exc,
            extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "phase": "exception"},
        )
        _db.log_video_error(
            match_id, slot,
            "REGEN_HLS_CRASH",
            f"Regen HLS crashed: {type(exc).__name__}",
            f"{type(exc).__name__}: {exc}\nTriggered by {actor}. See server log for full traceback.",
        )
        _log_activity(
            "hls.regenerate_failed",
            severity="error",
            message=f"HLS regeneration crashed: {type(exc).__name__}",
            match_id=match_id,
            slot=slot,
            actor=actor,
        )
        return
    if not ok:
        logger.warning(
            "regen_hls.failed %s/%s — all variant methods exhausted (see preceding warnings for ffmpeg stderr tails)",
            match_id, slot,
            extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "phase": "all_failed"},
        )
        _db.log_video_error(
            match_id, slot,
            "REGEN_HLS_FAILED",
            "Regen HLS failed — every variant exhausted hwaccel + CPU fallback.",
            f"Triggered by {actor}. Check the server log for the per-variant ffmpeg stderr tails (lines tagged 'HLS variant {match_id}/{slot}/<name> <method> failed').",
        )
        _log_activity(
            "hls.regenerate_failed",
            severity="error",
            message="HLS regeneration failed",
            match_id=match_id,
            slot=slot,
            actor=actor,
        )
        return
    logger.info(
        "admin.action regen_hls.done %s/%s by %s",
        match_id, slot, actor,
        extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "phase": "done"},
    )
    _log_activity(
        "hls.regenerate_succeeded",
        severity="success",
        message="HLS regeneration finished",
        match_id=match_id,
        slot=slot,
        actor=actor,
    )


# ---------------------------------------------------------------------------
# Matches CRUD
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Video Streaming (upload routes moved to routers/uploads.py)
# ---------------------------------------------------------------------------


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

        chunk_bytes = current_video_stream_chunk_bytes()

        def _iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    if session is not None and session.cancel.is_set():
                        break
                    chunk = f.read(min(chunk_bytes, remaining))
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
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("REPLAY_PORT", "8091"))
    logger.info("Replay server starting on port %d (data: %s)", port, DATA_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=600)
