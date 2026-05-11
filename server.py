"""Replay — Standalone match viewer with manual video upload.

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8090)
"""

from __future__ import annotations

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
from pathlib import Path
from typing import Iterable

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
import tenancy as _tenancy
import uploads as _uploads
from routers.admin import router as admin_router
from routers.admin_teams import router as admin_teams_router
from routers.auth import router as auth_router
from services import activity as _activity
from services import engagement as _engagement
from services import thumbnails as _thumbs
from services.visibility import (
    ACTIVE_GOAL_STATUSES as _ACTIVE_GOAL_STATUSES,
    can_view_coach_clip as _can_view_coach_clip,
    can_view_coach_note as _can_view_coach_note,
    filter_clips_for_user as _filter_clips_for_user,
    filter_goals_for_user as _filter_goals_for_user,
    filter_match_summaries_for_user as _filter_match_summaries_for_user,
    filter_notes_for_user as _filter_notes_for_user,
    filter_playlists_for_user as _filter_playlists_for_user,
    goal_with_visible_sources as _goal_with_visible_sources,
    goals_with_visible_sources as _goals_with_visible_sources,
    strip_private_fields as _strip_private_fields,
)
from models import (
    CreateCoachingClipRequest, CreateCoachingNoteRequest, CreateCoachingPlaylistRequest,
    CreateMatchRequest, CreateMatchSummaryRequest, CreatePlayerGoalReflectionRequest,
    CreatePlayerGoalRequest, CreatePlayerRequest, CreatePlayerUserLinkRequest,
    CreateUploadSessionRequest, LiveAuthRequest,
    MarkCoachingReviewRequest, StartCaptureRequest, UnblockStreamRequest,
    UpdateCoachingClipRequest, UpdateCoachingNoteRequest, UpdateCoachingPlaylistRequest,
    UpdateMatchRequest, UpdateMatchSummaryRequest, UpdatePlayerGoalRequest,
    UpdatePlayerRequest,
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
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_teams_router)

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
_coach_note_activity_label = _activity.coach_note_activity_label
_streams.set_activity_logger(_activity.stream_activity_logger)


def _thumb_path_within_videos_dir(thumb: Path) -> bool:
    return _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR)


def _coach_note_thumbnail_candidates(note: dict | None, note_id: int) -> list[Path]:
    return _thumbs.coach_note_thumbnail_candidates(note, note_id, VIDEOS_DIR)


def _coach_clip_thumbnail_candidates(clip: dict | None, clip_id: int) -> list[Path]:
    return _thumbs.coach_clip_thumbnail_candidates(clip, clip_id, VIDEOS_DIR)


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
    if isinstance(match_or_id, dict):
        return match_or_id.get("team_id")
    match = _db.get_match_by_id(str(match_or_id))
    return match.get("team_id") if match else None


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


@app.get("/coach")
async def coach_deep_link():
    """Serve the SPA shell for the coaching workspace."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


@app.get("/feedback")
async def feedback_deep_link():
    """Serve the SPA shell for signed-in player/family feedback."""
    return HTMLResponse(await _render_index_html(), headers=_SPA_NO_CACHE)


# Dev-only: when REPLAY_DEV=1, rewrite ES-module `import './js/foo.js'`
# statements at serve time so each import URL carries `?v=<mtime_ns>`. This
# closes the soft-refresh staleness gap — without it, a Cmd+R after editing
# js/coaching.js would re-fetch script.js (already versioned) but reuse the
# disk-cached coaching.js because the `import './js/coaching.js'` URL never
# changes. With this on, every save flips the URL the import resolves to.
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

@app.get("/api/settings")
async def get_public_settings():
    return await _public_settings_payload()


@app.get("/api/admin/settings")
async def get_admin_settings(request: Request):
    _auth.require_role(request, "admin")
    return await _admin_settings_payload()


@app.put("/api/admin/settings")
async def update_admin_settings(request: Request):
    user = _auth.require_role(request, "admin")
    body = await request.json()
    updates: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, value in body.items():
        if key not in _settings.EDITABLE_APP_SETTING_KEYS:
            continue
        try:
            updates[key] = _settings.normalize_value(key, value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise HTTPException(400, {"message": "Invalid settings", "errors": errors})

    actor = user.get("username") if isinstance(user, dict) else None
    settings = await _save_settings(updates, actor=actor)

    # Apply live-reloadable side effects (semaphore resize). Other knobs are
    # picked up on the next call site read — see current_*() helpers.
    if "transcode_concurrency" in updates:
        await TRANSCODE_SEMAPHORE.resize(_settings.get_int(settings, "transcode_concurrency", 2))

    if updates:
        tuning_keys = [key for key in updates if key in _settings.TUNING_KNOBS]
        event_type = "settings.tuning_updated" if tuning_keys else "settings.updated"
        _log_activity(
            event_type,
            severity="info",
            message="Tuning settings saved" if tuning_keys else "Settings saved",
            actor=actor,
            metadata={"keys": sorted(updates.keys()), "tuning_keys": sorted(tuning_keys)},
        )

    return {
        "ok": True,
        "settings": settings,
        "assets": {
            "logo_url": _settings.app_asset_url("logo", settings),
            "favicon_url": _settings.app_asset_url("favicon", settings),
        },
        "tuning_knobs": {
            key: dict(spec) for key, spec in _settings.TUNING_KNOBS.items()
        },
        "audit": _settings.list_audit_entries(20),
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
    actor = _auth.require_auth(request)["username"]
    settings = await _save_settings({config["setting_key"]: dest_name}, actor=actor)
    _log_activity(
        "settings.asset_updated",
        severity="info",
        message=f"{kind.title()} asset updated",
        actor=actor,
        metadata={"kind": kind, "filename": dest_name},
    )
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
            query_string=request.url.query,
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
async def live_auth_webhook(body: LiveAuthRequest, request: Request):
    """Webhook MediaMTX calls to authorise an RTMP publish.

    Reads/api/etc. are excluded in mediamtx.yml so this only ever sees
    publish attempts.  Allow if the path matches the configured stream key.
    """
    ip = _streams.client_ip(request)
    now = time.time()
    attempts = _live_auth_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LIVE_AUTH_RATE_WINDOW]
    if not attempts:
        _live_auth_attempts.pop(ip, None)
    if len(attempts) >= _LIVE_AUTH_RATE_LIMIT:
        raise HTTPException(429, "Too many requests")
    attempts.append(now)
    _live_auth_attempts[ip] = attempts

    if LIVE_AUTH_SECRET:
        # MediaMTX 1.18 dropped support for authHTTPHeaders, so we accept
        # the shared secret either as the X-Internal-Secret header (for
        # callers that can set headers) or as the password half of HTTP
        # Basic Auth in the URL (which is what MediaMTX uses now —
        # authHTTPAddress: http://_:<secret>@replay:8090/api/live/auth).
        provided = request.headers.get("x-internal-secret") or ""
        if not provided:
            auth_header = request.headers.get("authorization") or ""
            if auth_header.lower().startswith("basic "):
                try:
                    decoded = base64.b64decode(auth_header.split(None, 1)[1]).decode("utf-8", "replace")
                    _, _, provided = decoded.partition(":")
                except Exception:
                    provided = ""
        if not secrets.compare_digest(provided, LIVE_AUTH_SECRET):
            raise HTTPException(401, "Unauthorized")
    elif LIVE_AUTH_ALLOW_INSECURE:
        if not hasattr(live_auth_webhook, "_warned"):
            live_auth_webhook._warned = True
            logger.warning("LIVE_AUTH_SECRET is not set; insecure live auth is enabled via LIVE_AUTH_ALLOW_INSECURE=1")
    else:
        raise HTTPException(503, "Live auth misconfigured: set LIVE_AUTH_SECRET")

    key = await _stream_key()
    payload = body.model_dump()
    allowed, reason = _live.validate_publish_auth(payload, key)
    if not allowed:
        _live.record_rejection(payload, reason)
        logger.info(
            "Live auth rejected (%s): action=%s path=%s protocol=%s ip=%s",
            reason, body.action, body.path, body.protocol, body.ip,
            extra={"reason": reason, "action": body.action, "path": body.path,
                   "protocol": body.protocol, "ip": body.ip},
        )
        raise HTTPException(401, "Invalid stream key")
    logger.info(
        "Live auth accepted: ip=%s protocol=%s", body.ip, body.protocol,
        extra={"ip": body.ip, "protocol": body.protocol},
    )
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
    actor = _auth.require_auth(request)["username"]
    logger.info("Live stream key rotated by %s", actor)
    _log_activity(
        "live.key_rotated",
        severity="warning",
        message="Live stream key rotated",
        actor=actor,
    )
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
    _log_activity(
        "stream.killed",
        severity="warning",
        message="Stream killed",
        actor=user["username"],
        metadata={"session_id": session_id},
    )
    return {"ok": True, "killed": True}


@app.delete("/api/admin/streams/blocks")
async def admin_unblock_stream(payload: UnblockStreamRequest, request: Request):
    """Admin: clear a kill-block early so the affected viewer can rejoin."""
    user = _auth.require_role(request, "admin")
    key = (payload.ip, payload.kind, payload.match_id or "", payload.slot or "")
    cleared = _streams.registry.unblock(key)
    logger.info("admin.action", extra={"action": "unblock_stream", "actor": user["username"], "target_ip": payload.ip, "kind": payload.kind})
    if cleared:
        _log_activity(
            "stream.unblocked",
            severity="info",
            message="Stream block cleared",
            match_id=payload.match_id,
            slot=payload.slot,
            actor=user["username"],
            metadata={"ip": payload.ip, "kind": payload.kind},
        )
    return {"ok": True, "cleared": cleared}


# ---------------------------------------------------------------------------
# Coaching workspace
# ---------------------------------------------------------------------------

def _require_coach(request: Request) -> dict:
    return _auth.require_role(request, "admin", "coach")


def _resolve_coach_scope(request: Request) -> tuple[dict, _tenancy.Scope]:
    user = _require_coach(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("team_admin", "coach"),
        allow_global_admin_override=True,
    )
    return user, scope


def _resolve_feedback_scope(request: Request) -> tuple[dict, _tenancy.Scope]:
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(request, user, allow_global_admin_override=True)
    return user, scope


def _scope_team_id(scope: _tenancy.Scope) -> str:
    return str(scope.team["id"])


def _require_scoped_item(item: dict | None, team_id: str, detail: str):
    if not item or not _same_team(item, team_id):
        raise HTTPException(404, detail)
    return item


def _require_match_in_team(match_id: str | None, team_id: str) -> dict:
    if not match_id:
        raise HTTPException(404, "Match not found")
    match = _db.get_match_by_id(match_id)
    return _require_scoped_item(match, team_id, "Match not found")


def _require_player_in_team(player_id: str, team_id: str) -> dict:
    return _require_scoped_item(_db.get_player(player_id, team_id=team_id), team_id, "Player not found")


def _require_note_in_team(note_id: int, team_id: str) -> dict:
    return _require_scoped_item(_db.get_coaching_note(note_id), team_id, "Note not found")


def _require_clip_in_team(clip_id: int, team_id: str) -> dict:
    return _require_scoped_item(_db.get_coaching_clip(clip_id), team_id, "Clip not found")


def _require_playlist_in_team(playlist_id: int, team_id: str) -> dict:
    return _require_scoped_item(_db.get_coaching_playlist(playlist_id), team_id, "Playlist not found")


def _require_summary_in_team(summary_id: int, team_id: str) -> dict:
    return _require_scoped_item(_db.get_coaching_match_summary(summary_id), team_id, "Match summary not found")


def _require_players_in_team(player_ids: list[str], team_id: str) -> None:
    for player_id in player_ids:
        _require_player_in_team(player_id, team_id)


def _require_notes_in_team(note_ids: list[int], team_id: str) -> None:
    for note_id in note_ids:
        _require_note_in_team(note_id, team_id)


def _require_clips_in_team(clip_ids: list[int], team_id: str) -> None:
    for clip_id in clip_ids:
        _require_clip_in_team(clip_id, team_id)


def _require_playlists_in_team(playlist_ids: list[int], team_id: str) -> None:
    for playlist_id in playlist_ids:
        _require_playlist_in_team(playlist_id, team_id)


def _same_team(item: dict | None, team_id: str | None) -> bool:
    return item is not None and (team_id is None or str(item.get("team_id")) == str(team_id))




def _validate_goal_source_links(data: dict, player_id: str, team_id: str | None = None):
    if team_id is not None:
        _require_player_in_team(player_id, team_id)
    elif not _db.get_player(player_id, allow_unscoped=True):
        raise HTTPException(404, "Player not found")
    note_id = data.get("source_note_id")
    if note_id is not None:
        note = _db.get_coaching_note(note_id)
        if not note or (team_id and not _same_team(note, team_id)):
            raise HTTPException(404, "Source note not found")
        if player_id not in (note.get("player_ids") or []):
            raise HTTPException(400, "Source note is not linked to this player")
    clip_id = data.get("source_clip_id")
    if clip_id is not None:
        clip = _db.get_coaching_clip(clip_id)
        if not clip or (team_id and not _same_team(clip, team_id)):
            raise HTTPException(404, "Source clip not found")
        if player_id not in (clip.get("player_ids") or []):
            raise HTTPException(400, "Source clip is not linked to this player")
    playlist_id = data.get("source_playlist_id")
    if data.get("source_playlist_item_note_id") is not None and playlist_id is None:
        raise HTTPException(400, "source_playlist_id is required for a playlist item source")
    if playlist_id is not None:
        playlist = _db.get_coaching_playlist(playlist_id)
        if not playlist or (team_id and not _same_team(playlist, team_id)):
            raise HTTPException(404, "Source playlist not found")
        item_note_id = data.get("source_playlist_item_note_id")
        if player_id not in (playlist.get("player_ids") or []) and item_note_id is None:
            raise HTTPException(400, "Source playlist is not linked to this player")
        if item_note_id is not None:
            if item_note_id not in (playlist.get("note_ids") or []):
                raise HTTPException(400, "Playlist item is not in source playlist")
            note = _db.get_coaching_note(item_note_id)
            if not note or (team_id and not _same_team(note, team_id)) or player_id not in (note.get("player_ids") or []):
                raise HTTPException(400, "Playlist item is not linked to this player")
    target_match_id = data.get("target_match_id")
    if target_match_id:
        if team_id is not None:
            _require_match_in_team(target_match_id, team_id)
        elif not _db.get_match_by_id(target_match_id):
            raise HTTPException(404, "Target match not found")

def _playlists_with_items(playlists: list[dict], notes: list[dict] | None = None) -> list[dict]:
    notes_by_id = {note["id"]: note for note in (notes if notes is not None else _db.list_coaching_notes())}
    hydrated = []
    for playlist in playlists:
        item_notes = [
            notes_by_id[note_id]
            for note_id in playlist.get("note_ids", [])
            if note_id in notes_by_id
        ]
        hydrated.append({**playlist, "note_ids": [note["id"] for note in item_notes], "items": item_notes})
    return hydrated


@app.get("/api/coach/players")
async def coach_list_players(request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    return {"players": _db.list_players(include_inactive=True, team_id=team_id)}


@app.get("/api/coach/users")
async def coach_list_linkable_users(request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    return {
        "users": [
            {k: v for k, v in u.items() if k != "password_hash"}
            for u in _db.list_users(team_id=team_id)
        ]
    }


@app.post("/api/coach/players")
async def coach_create_player(request: Request, body: CreatePlayerRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    season_id = scope.season["id"] if scope.season else None
    player = _db.create_player(
        body.display_name,
        jersey_number=body.jersey_number,
        active=body.active,
        notes=body.notes,
        team_id=team_id,
        season_id=season_id,
    )
    _log_activity(
        "coach.player_created",
        severity="info",
        message=f"Roster player added: {player.get('display_name')}",
        actor=user["username"],
        metadata={"player_id": player.get("id")},
    )
    return {"ok": True, "player": player}


@app.patch("/api/coach/players/{player_id}")
async def coach_update_player(player_id: str, request: Request, body: UpdatePlayerRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    _require_player_in_team(player_id, team_id)
    updates = body.model_dump(exclude_unset=True)
    if updates and not _db.update_player(player_id, **updates):
        raise HTTPException(404, "Player not found")
    player = _db.get_player(player_id, team_id=team_id)
    if not player:
        raise HTTPException(404, "Player not found")
    _log_activity(
        "coach.player_updated",
        severity="info",
        message=f"Roster player updated: {player.get('display_name')}",
        actor=user["username"],
        metadata={"player_id": player_id, "fields": sorted(updates.keys())},
    )
    return {"ok": True, "player": player}


@app.delete("/api/coach/players/{player_id}")
async def coach_delete_player(player_id: str, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    player = _require_player_in_team(player_id, team_id)
    if not _db.delete_player(player_id):
        raise HTTPException(404, "Player not found")
    _log_activity(
        "coach.player_deleted",
        severity="warning",
        message=f"Roster player deleted: {player.get('display_name', player_id) if player else player_id}",
        actor=user["username"],
        metadata={"player_id": player_id},
    )
    return {"ok": True}


@app.post("/api/coach/player-links")
async def coach_link_player_user(request: Request, body: CreatePlayerUserLinkRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    _require_player_in_team(body.player_id, team_id)
    if not _db.get_user_by_id(body.user_id) or not _db.user_has_team_membership(body.user_id, team_id):
        raise HTTPException(404, "User not found")
    player = _db.link_player_user(body.player_id, body.user_id, body.relationship)
    _log_activity(
        "coach.player_linked",
        severity="info",
        message=f"Roster link updated: {player.get('display_name', body.player_id)}",
        actor=user["username"],
        metadata={"player_id": body.player_id, "user_id": body.user_id, "relationship": body.relationship},
    )
    return {"ok": True, "player": player}


@app.delete("/api/coach/player-links/{link_id}")
async def coach_delete_player_user_link(link_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    link = _db.get_player_user_link(link_id)
    if not link or (team_id is not None and link.get("team_id") != team_id):
        raise HTTPException(404, "Link not found")
    if not _db.delete_player_user_link(link_id):
        raise HTTPException(404, "Link not found")
    _log_activity(
        "coach.player_unlinked",
        severity="warning",
        message="Roster account link removed",
        actor=user["username"],
        metadata={"link_id": link_id},
    )
    return {"ok": True}


@app.get("/api/coach/notes")
async def coach_list_notes(request: Request, match_id: str | None = None):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    return {"notes": [n for n in _db.list_coaching_notes(match_id=match_id) if _same_team(n, team_id)]}


@app.post("/api/coach/notes")
async def coach_create_note(request: Request, body: CreateCoachingNoteRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    # Phase 6a — observation notes have no `match_id` so we only check
    # the match-exists invariant for video notes. Pydantic's
    # `validate_context_invariants` already rejects a video note with
    # missing match_id / slot / timestamp_seconds before we get here.
    if body.match_id:
        _require_match_in_team(body.match_id, team_id)
    _require_players_in_team(body.player_ids, team_id)
    payload = body.model_dump()
    payload["team_id"] = team_id
    note = _db.create_coaching_note(payload, actor=user["username"])
    _log_activity(
        "coach.note_created",
        severity="info",
        message=f"Coaching note created: {_coach_note_activity_label(note)}",
        match_id=note.get("match_id"),
        slot=note.get("slot"),
        actor=user["username"],
        metadata={
            "note_id": note.get("id"),
            "visibility": note.get("visibility"),
            "note_context": note.get("note_context"),
        },
    )
    # Phase 3a: kick the per-note thumbnail generator off in the
    # background. Best-effort — the spawn helper swallows failures so
    # the response below is unaffected. If the source video isn't
    # transcoded yet (`<match>/<slot>.mp4` missing), the generator
    # logs a warning and returns False; the coach can manually
    # regenerate later via the POST regenerate endpoint.
    #
    # Phase 6a: observation notes have no video timestamp so we skip
    # generation entirely — there is no source frame to capture.
    if note.get("note_context") == "video":
        _spawn_task(_thumbs.spawn_coach_note_thumbnail(note, videos_dir=VIDEOS_DIR, slot_mp4_path=_slot_mp4_path))
    return {"ok": True, "note": note}


@app.patch("/api/coach/notes/{note_id}")
async def coach_update_note(note_id: int, request: Request, body: UpdateCoachingNoteRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_note_in_team(note_id, team_id)
    updates = body.model_dump(exclude_unset=True)
    _require_players_in_team(updates.get("player_ids") or [], team_id)
    # Phase 6a — validate the MERGED state so a partial PATCH can't
    # leave a video note in an invalid shape. Examples:
    #   - PATCH `note_context: "video"` on an observation row that has
    #     no `match_id`/`slot`/`timestamp_seconds` → must require the
    #     three anchoring fields (either already in the row or in this
    #     PATCH) before the row flips to 'video'.
    #   - PATCH `match_id: null` on a video note (without flipping
    #     context) → would leave a video note un-anchored. Reject.
    # The merged-state validation here is the source of truth; the
    # request-shape validators (Pydantic) only know about this PATCH.
    merged = {**existing}
    for k, v in updates.items():
        merged[k] = v
    merged_context = merged.get("note_context") or "video"
    if merged_context == "video":
        for key in ("match_id", "slot", "timestamp_seconds"):
            if merged.get(key) in (None, ""):
                raise HTTPException(
                    422, f"video notes require {key}"
                )
        if not (merged.get("title") or "").strip():
            raise HTTPException(422, "title must not be empty")
        _require_match_in_team(merged["match_id"], team_id)
    else:
        # Phase 6b (#113) — observation notes do not require a title.
        # `_OBSERVATION_CONTENT_FIELDS` (in models.py) already enforces
        # that at least one of title / body / player_summary /
        # what_happened / why_it_matters / what_to_do_next /
        # event_title is present (or `tactical_board_json`). Mirror
        # that here on the merged state so a PATCH that clears the
        # title cannot leave the row with no meaningful content.
        # `tactical_board_json` is an explicit `None` sentinel for
        # "clear the board" so we keep the truthy check on the merged
        # value (a cleared board doesn't count as content).
        meaningful = (
            (merged.get("tactical_board_json") is not None)
            or any(
                (merged.get(name) or "").strip()
                for name in (
                    "title", "body", "player_summary", "what_happened",
                    "why_it_matters", "what_to_do_next", "event_title",
                )
            )
        )
        if not meaningful:
            raise HTTPException(
                422,
                "observation notes require at least one of: title, body, "
                "player_summary, what_happened, why_it_matters, "
                "what_to_do_next, event_title, or tactical_board_json",
            )
    if merged_context != "video" and merged.get("match_id"):
        _require_match_in_team(merged["match_id"], team_id)
    note = _db.update_coaching_note(note_id, updates) or existing
    _log_activity(
        "coach.note_updated",
        severity="info",
        message=f"Coaching note updated: {_coach_note_activity_label(note)}",
        match_id=note.get("match_id"),
        slot=note.get("slot"),
        actor=user["username"],
        metadata={
            "note_id": note_id,
            "fields": sorted(updates.keys()),
            "note_context": note.get("note_context"),
        },
    )
    # Phase 3a: regenerate the thumbnail if the moment moved. Only
    # `match_id`, `slot`, and `timestamp_seconds` change which frame
    # the still represents — purely textual edits (title, body,
    # structured fields, tags, visibility) leave the thumbnail
    # accurate, so we skip the regen and the existing JPEG keeps
    # serving. Same best-effort spawn pattern as create.
    #
    # Phase 6a: observation notes never have a video frame to capture,
    # so we suppress regeneration whenever the (post-update) note is
    # an observation.
    moment_fields = {"match_id", "slot", "timestamp_seconds"}
    new_context = note.get("note_context") or "video"
    old_context = existing.get("note_context") or "video"
    if new_context == "video" and moment_fields.intersection(updates.keys()):
        _spawn_task(_thumbs.spawn_coach_note_thumbnail(note, videos_dir=VIDEOS_DIR, slot_mp4_path=_slot_mp4_path))
    elif old_context == "video" and new_context == "observation":
        # Phase 6b (#114) — flipping a video note to an observation
        # leaves the original JPEG orphaned on disk; nothing serves
        # it (`GET /api/coach/notes/{id}/thumbnail` short-circuits to
        # 404 for observation notes) and `delete_coaching_note` would
        # skip the unlink because the row no longer has a match_id /
        # video context. Clean it up best-effort using the existing
        # `_thumb_path_within_videos_dir` containment guard so a
        # corrupted DB row can't escape `VIDEOS_DIR`. The PATCH
        # response is unaffected if the unlink fails.
        prior_match_id = existing.get("match_id")
        if prior_match_id:
            try:
                for thumb in _thumbs.coach_note_thumbnail_candidates(existing, note_id, VIDEOS_DIR):
                    if _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR):
                        thumb.unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                _log.setup("replay").warning(
                    "Could not unlink stale coach note thumbnail for note %s: %s",
                    note_id, exc,
                )
    return {"ok": True, "note": note}


@app.delete("/api/coach/notes/{note_id}")
async def coach_delete_note(note_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    note = _require_note_in_team(note_id, team_id)
    if not _db.delete_coaching_note(note_id):
        raise HTTPException(404, "Note not found")
    label = _coach_note_activity_label(note) if note else ""
    _log_activity(
        "coach.note_deleted",
        severity="warning",
        message=f"Coaching note deleted: {label or note_id}",
        match_id=note.get("match_id") if note else None,
        slot=note.get("slot") if note else None,
        actor=user["username"],
        metadata={"note_id": note_id},
    )
    # Phase 3a: clean up the per-note thumbnail too. Best-effort — a
    # missing file is fine; an OS error is logged but not raised. The
    # `_thumb_path_within_videos_dir` containment check matches the
    # defense-in-depth pattern used by `serve_logo` / `serve_thumbnail`
    # so a corrupted DB row that escapes its match folder cannot trick
    # this handler into unlinking a file outside `VIDEOS_DIR`.
    try:
        # Phase 6a — observation notes have no `match_id`, so the
        # thumbnail path is meaningless. Skip the unlink attempt
        # entirely. Video notes still clean up their JPEG.
        for thumb in _thumbs.coach_note_thumbnail_candidates(note, note_id, VIDEOS_DIR):
            if _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR):
                thumb.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        _log.setup("replay").warning(
            "Could not unlink coach note thumbnail for note %s: %s", note_id, exc
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
@app.get("/api/coach/notes/{note_id}/thumbnail")
async def coach_get_note_thumbnail(note_id: int, request: Request):
    """Serve the per-note thumbnail JPEG.

    - Any signed-in user can call this; visibility is enforced per-note
      via `_can_view_coach_note`.
    - Returns 404 when the note does not exist OR when the user cannot
      see it OR when the thumbnail file is missing OR when the
      computed path would escape `VIDEOS_DIR`. The same 404 covers all
      four cases so a probing viewer cannot distinguish them.
    """
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("team_admin", "coach") if _auth.has_role(user, "admin", "coach") else None,
        allow_global_admin_override=True,
    )
    team_id = _scope_team_id(scope)
    note = _db.get_coaching_note(note_id)
    if not note or not _same_team(note, team_id):
        raise HTTPException(404, "Thumbnail not found")
    if not _can_view_coach_note(user, note, team_id=team_id):
        raise HTTPException(404, "Thumbnail not found")
    # Phase 6a — observation notes never have a video frame, so the
    # path resolution would only land on a missing-file 404 anyway.
    # Short-circuit explicitly so the response is consistent regardless
    # of file-system race conditions and a viewer can't probe whether
    # an observation note exists by polling the thumbnail endpoint.
    if (note.get("note_context") or "video") != "video" or not note.get("match_id"):
        raise HTTPException(404, "Thumbnail not found")
    try:
        thumb = _media.existing_coach_note_thumbnail_path(VIDEOS_DIR, note["match_id"], note_id, team_id=note.get("team_id"))
    except ValueError:
        raise HTTPException(404, "Thumbnail not found")
    # Defense-in-depth: refuse to serve a path that escapes VIDEOS_DIR.
    # Same response shape as the missing-file branch so a viewer can't
    # use a probing match_id to distinguish containment-fail from
    # not-generated-yet.
    if not _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR):
        raise HTTPException(404, "Thumbnail not found")
    if not thumb.is_file():
        raise HTTPException(404, "Thumbnail not generated yet")
    # Match `serve_thumbnail`'s caching policy exactly: revalidate every
    # request via mtime ETag so a coach who calls /thumbnail/regenerate
    # sees the new JPEG immediately on the next browser refresh, while
    # cached copies are still served cheaply when the file is unchanged.
    # Crucially this is NOT `Cache-Control: public` — the response is
    # access-controlled per-viewer (private notes are coach-only,
    # player-tagged notes only reach linked family) so a shared cache
    # must NOT be allowed to replay it across users.
    mtime = int(thumb.stat().st_mtime)
    return FileResponse(
        str(thumb),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "ETag": f'"{mtime}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/coach/notes/{note_id}/thumbnail/regenerate")
async def coach_regenerate_note_thumbnail(note_id: int, request: Request):
    """Coach/admin manual trigger for the thumbnail generator. Useful
    when the source video lands AFTER the note was created (the original
    create-time generation will have failed silently because the MP4
    didn't exist yet) or when a coach wants to refresh after editing a
    note's timestamp.

    Synchronous on purpose — the caller wants to know whether the
    refresh succeeded so the UI can re-fetch the image. Returns
    `{ok: bool, generated: bool}` so the frontend can distinguish
    "regen ran and produced a file" from "regen ran but the source
    video is still missing"."""
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    note = _require_note_in_team(note_id, team_id)
    # Phase 6a — observation notes have no video frame to extract.
    # Return the same `generated: false` shape callers already handle
    # for the source-video-missing case so frontend code paths don't
    # need a new branch.
    if (note.get("note_context") or "video") != "video" or not note.get("match_id"):
        return {"ok": True, "generated": False}
    ok = await _thumbs.regenerate_coach_note_thumbnail(
        note,
        note_id,
        videos_dir=VIDEOS_DIR,
        slot_mp4_path=_slot_mp4_path,
    )
    return {"ok": True, "generated": ok}


@app.get("/api/coach/playlists")
async def coach_list_playlists(request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlists = [p for p in _db.list_coaching_playlists() if _same_team(p, team_id)]
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    return {"playlists": _playlists_with_items(playlists, notes)}


@app.get("/api/coach/playlists/{playlist_id}")
async def coach_get_playlist(playlist_id: int, request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlist = _require_playlist_in_team(playlist_id, team_id)
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    return {"playlist": _playlists_with_items([playlist], notes)[0]}


@app.post("/api/coach/playlists")
async def coach_create_playlist(request: Request, body: CreateCoachingPlaylistRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    season_id = scope.season["id"] if scope.season else None
    _require_notes_in_team(body.note_ids, team_id)
    _require_players_in_team(body.player_ids, team_id)
    payload = body.model_dump()
    payload["team_id"] = team_id
    payload["season_id"] = season_id
    playlist = _db.create_coaching_playlist(payload, actor=user["username"])
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    playlist = _playlists_with_items([playlist], notes)[0]
    _log_activity(
        "coach.playlist_created",
        severity="info",
        message=f"Coaching playlist created: {playlist.get('title')}",
        actor=user["username"],
        metadata={"playlist_id": playlist.get("id"), "visibility": playlist.get("visibility")},
    )
    return {"ok": True, "playlist": playlist}


@app.patch("/api/coach/playlists/{playlist_id}")
async def coach_update_playlist(playlist_id: int, request: Request, body: UpdateCoachingPlaylistRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_playlist_in_team(playlist_id, team_id)
    updates = body.model_dump(exclude_unset=True)
    _require_notes_in_team(updates.get("note_ids") or [], team_id)
    _require_players_in_team(updates.get("player_ids") or [], team_id)
    playlist = _db.update_coaching_playlist(playlist_id, updates) or existing
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    playlist = _playlists_with_items([playlist], notes)[0]
    _log_activity(
        "coach.playlist_updated",
        severity="info",
        message=f"Coaching playlist updated: {playlist.get('title')}",
        actor=user["username"],
        metadata={"playlist_id": playlist_id, "fields": sorted(updates.keys())},
    )
    return {"ok": True, "playlist": playlist}


@app.delete("/api/coach/playlists/{playlist_id}")
async def coach_delete_playlist(playlist_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlist = _require_playlist_in_team(playlist_id, team_id)
    if not _db.delete_coaching_playlist(playlist_id):
        raise HTTPException(404, "Playlist not found")
    _log_activity(
        "coach.playlist_deleted",
        severity="warning",
        message=f"Coaching playlist deleted: {playlist.get('title', playlist_id) if playlist else playlist_id}",
        actor=user["username"],
        metadata={"playlist_id": playlist_id},
    )
    return {"ok": True}


def _validate_match_summary_has_text(payload: dict) -> None:
    if not any((payload.get(name) or "").strip() for name in ("team_positives", "team_improvements", "training_focus", "body")):
        raise HTTPException(422, "match summary requires at least one text field")


def _validate_match_summary_sources(match_id: str, payload: dict, team_id: str | None = None) -> None:
    for note_id in payload.get("note_ids") or []:
        note = _db.get_coaching_note(note_id)
        if not note or (team_id and not _same_team(note, team_id)):
            raise HTTPException(404, f"Note not found: {note_id}")
        if note.get("match_id") != match_id:
            raise HTTPException(422, f"Note {note_id} is not linked to match {match_id}")
    for clip_id in payload.get("clip_ids") or []:
        clip = _db.get_coaching_clip(clip_id)
        if not clip or (team_id and not _same_team(clip, team_id)):
            raise HTTPException(404, f"Clip not found: {clip_id}")
        if clip.get("match_id") != match_id:
            raise HTTPException(422, f"Clip {clip_id} is not linked to match {match_id}")
    for playlist_id in payload.get("playlist_ids") or []:
        playlist = _db.get_coaching_playlist(playlist_id)
        if not playlist or (team_id and not _same_team(playlist, team_id)):
            raise HTTPException(404, f"Playlist not found: {playlist_id}")
        for note_id in playlist.get("note_ids") or []:
            note = _db.get_coaching_note(note_id)
            if note and (note.get("match_id") != match_id or (team_id and not _same_team(note, team_id))):
                raise HTTPException(422, f"Playlist {playlist_id} contains a note from a different match")


def _sanitize_match_summary_sources(summary: dict, team_id: str | None) -> dict:
    out = dict(summary)
    out["note_ids"] = [
        note_id for note_id in (summary.get("note_ids") or [])
        if _same_team(_db.get_coaching_note(note_id), team_id)
    ]
    out["clip_ids"] = [
        clip_id for clip_id in (summary.get("clip_ids") or [])
        if _same_team(_db.get_coaching_clip(clip_id), team_id)
    ]
    out["playlist_ids"] = [
        playlist_id for playlist_id in (summary.get("playlist_ids") or [])
        if _same_team(_db.get_coaching_playlist(playlist_id), team_id)
    ]
    return out


@app.get("/api/coach/match-summaries")
async def coach_list_match_summaries(request: Request, match_id: str | None = None):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    summaries = [s for s in _db.list_coaching_match_summaries(match_id=match_id) if _same_team(s, team_id)]
    return {"summaries": [_sanitize_match_summary_sources(s, team_id) for s in summaries]}


@app.get("/api/coach/match-summaries/{summary_id}")
async def coach_get_match_summary(summary_id: int, request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    summary = _sanitize_match_summary_sources(_require_summary_in_team(summary_id, team_id), team_id)
    return {"summary": summary}


@app.post("/api/coach/match-summaries")
async def coach_create_match_summary(request: Request, body: CreateMatchSummaryRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    _require_match_in_team(body.match_id, team_id)
    payload = body.model_dump()
    payload["team_id"] = team_id
    _validate_match_summary_sources(body.match_id, payload, team_id)
    summary = _db.create_coaching_match_summary(payload, actor=user["username"])
    _log_activity(
        "coach.match_summary_created",
        severity="info",
        message=f"Match coaching summary created for {summary.get('match_id')}",
        match_id=summary.get("match_id"),
        actor=user["username"],
        metadata={"summary_id": summary.get("id"), "visibility": summary.get("visibility")},
    )
    return {"ok": True, "summary": summary}


@app.patch("/api/coach/match-summaries/{summary_id}")
async def coach_update_match_summary(summary_id: int, request: Request, body: UpdateMatchSummaryRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_summary_in_team(summary_id, team_id)
    updates = body.model_dump(exclude_unset=True)
    merged_payload = dict(existing)
    merged_payload.update(updates)
    _validate_match_summary_has_text(merged_payload)
    source_payload = dict(existing)
    source_payload.update({k: v for k, v in updates.items() if k in {"note_ids", "clip_ids", "playlist_ids"}})
    _validate_match_summary_sources(existing["match_id"], source_payload, team_id)
    summary = _db.update_coaching_match_summary(summary_id, updates) or existing
    _log_activity(
        "coach.match_summary_updated",
        severity="info",
        message=f"Match coaching summary updated for {summary.get('match_id')}",
        match_id=summary.get("match_id"),
        actor=user["username"],
        metadata={"summary_id": summary_id, "fields": sorted(updates.keys())},
    )
    return {"ok": True, "summary": summary}


@app.delete("/api/coach/match-summaries/{summary_id}")
async def coach_delete_match_summary(summary_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    summary = _require_summary_in_team(summary_id, team_id)
    if not _db.delete_coaching_match_summary(summary_id):
        raise HTTPException(404, "Match summary not found")
    _log_activity(
        "coach.match_summary_deleted",
        severity="info",
        message=f"Match coaching summary deleted for {summary.get('match_id') if summary else summary_id}",
        match_id=summary.get("match_id") if summary else None,
        actor=user["username"],
        metadata={"summary_id": summary_id},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Coaching clips (Phase 4a — backend only)
#
# Clips are first-class coaching objects: a saved [start, end] window
# of a match slot, optionally seeded from a note via `source_note_id`.
# Visibility uses the same ladder as notes/playlists. The clip's
# drawing is captured as a snapshot at create time so the clip stays
# self-contained even if the source note is later edited or deleted.
#
# **Privacy invariant**: when a clip is created from `source_note_id`,
# the create handler defaults a small set of fields from the source
# note (match_id / slot / category / drawing) but NEVER copies any
# coach-private text — neither `coach_private_note` nor anything else
# from the note's body. The clip's own `title` / `description` come
# from the request body or empty defaults; the source note's text
# fields are never auto-copied. This keeps `coach_private_note`
# scoped to its single defense-in-depth surface (`_strip_private_fields`)
# and prevents a clip from accidentally re-publishing private text
# under a more permissive visibility.
# ---------------------------------------------------------------------------


@app.get("/api/coach/clips")
async def coach_list_clips(request: Request, match_id: str | None = None):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    return {"clips": [c for c in _db.list_coaching_clips(match_id=match_id) if _same_team(c, team_id)]}


@app.get("/api/coach/clips/{clip_id}")
async def coach_get_clip(clip_id: int, request: Request):
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    clip = _require_clip_in_team(clip_id, team_id)
    return {"clip": clip}


@app.post("/api/coach/clips")
async def coach_create_clip(request: Request, body: CreateCoachingClipRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    _require_match_in_team(body.match_id, team_id)
    _require_players_in_team(body.player_ids, team_id)
    payload = body.model_dump()
    # `source_note_id` is an OPTIONAL forward-compat reference. When the
    # coach provides one, this handler verifies the note exists and
    # then — only when the request body didn't ship its own `drawing`
    # — copies the source note's drawing snapshot onto the clip. That
    # is the ONLY field defaulted from the source note in Phase 4a.
    #
    # Privacy invariant (locked in by `test_clip_source_note_does_not_leak_private_text`):
    # `match_id`, `slot`, `start_seconds`, `end_seconds`, `title`,
    # `description`, `category`, `visibility`, and `player_ids` come
    # from the explicit clip request, never from the source note. We
    # also do NOT auto-copy any of the note's text fields — `body`,
    # `coach_private_note`, `what_happened`, `why_it_matters`,
    # `what_to_do_next`, `player_summary`, source title — because a
    # clip can carry a more permissive visibility than its source note,
    # and silently re-publishing private text through a `team` /
    # `unlisted` clip would be a privacy leak.
    if payload.get("source_note_id") is not None:
        source = _require_note_in_team(payload["source_note_id"], team_id)
        # We trust the request body for `match_id` / `slot` / `category`
        # / window / title / etc. — the coach explicitly authored those.
        # Do NOT silently rewrite to the source's match (would surprise
        # the coach) and do NOT validate request fields against the
        # source (a coach may legitimately re-anchor a clip to a
        # different slot of the same match).
        if not payload.get("drawing"):
            payload["drawing"] = source.get("drawing") or {}
    payload["team_id"] = team_id
    clip = _db.create_coaching_clip(payload, actor=user["username"])
    _log_activity(
        "coach.clip_created",
        severity="info",
        message=f"Coaching clip created: {clip.get('title')}",
        match_id=clip.get("match_id"),
        slot=clip.get("slot"),
        actor=user["username"],
        metadata={
            "clip_id": clip.get("id"),
            "visibility": clip.get("visibility"),
            "duration_seconds": clip.get("duration_seconds"),
            "source_note_id": clip.get("source_note_id"),
        },
    )
    # Phase 4e — best-effort clip thumbnail generation. Schedule AFTER
    # the response is built so a missing source MP4 / ffmpeg crash never
    # blocks clip save. The serving endpoint just returns 404 when the
    # JPEG is absent, and the manual regenerate endpoint lets the coach
    # retry once the source video lands.
    _spawn_task(_thumbs.spawn_coach_clip_thumbnail(clip, videos_dir=VIDEOS_DIR, slot_mp4_path=_slot_mp4_path))
    return {"ok": True, "clip": clip}


@app.patch("/api/coach/clips/{clip_id}")
async def coach_update_clip(clip_id: int, request: Request, body: UpdateCoachingClipRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_clip_in_team(clip_id, team_id)
    updates = body.model_dump(exclude_unset=True)
    # Window invariant when only one endpoint is being changed: merge
    # against the existing row before re-checking. The Pydantic model
    # already validated the all-fields-supplied case; this catches the
    # half-supplied case too.
    if "start_seconds" in updates or "end_seconds" in updates:
        new_start = updates.get("start_seconds", existing["start_seconds"])
        new_end = updates.get("end_seconds", existing["end_seconds"])
        if new_end <= new_start:
            raise HTTPException(422, "end_seconds must be greater than start_seconds")
        if new_end - new_start > 120.0:
            raise HTTPException(422, "clip duration must be 120 seconds or less")
    _require_players_in_team(updates.get("player_ids") or [], team_id)
    clip = _db.update_coaching_clip(clip_id, updates) or existing
    _log_activity(
        "coach.clip_updated",
        severity="info",
        message=f"Coaching clip updated: {clip.get('title')}",
        match_id=clip.get("match_id"),
        slot=clip.get("slot"),
        actor=user["username"],
        metadata={"clip_id": clip_id, "fields": sorted(updates.keys())},
    )
    # Phase 4e — regenerate the clip thumbnail when the start_seconds
    # changes. `match_id` and `slot` are immutable for clips today
    # (`UpdateCoachingClipRequest` rejects them with `extra="forbid"`)
    # so start_seconds is the only field that can shift the captured
    # frame. Scheduled as a background task; failures don't block save.
    if "start_seconds" in updates and updates["start_seconds"] != existing.get("start_seconds"):
        _spawn_task(_thumbs.spawn_coach_clip_thumbnail(clip, videos_dir=VIDEOS_DIR, slot_mp4_path=_slot_mp4_path))
    return {"ok": True, "clip": clip}


@app.delete("/api/coach/clips/{clip_id}")
async def coach_delete_clip(clip_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    clip = _require_clip_in_team(clip_id, team_id)
    if not _db.delete_coaching_clip(clip_id):
        raise HTTPException(404, "Clip not found")
    # Phase 4e — clean up the per-clip thumbnail JPEG. Same defense-in-
    # depth path-containment check as note delete: a corrupted DB row's
    # `match_id` containing `..` must NOT be allowed to unlink a file
    # outside `VIDEOS_DIR`. `unlink(missing_ok=True)` is a no-op when
    # the file was never generated. Best-effort — a missing file is
    # fine; an OS error is logged but not raised, so a permission /
    # read-only-FS failure can never surface as a 500 after the DB row
    # was already deleted (matches `coach_delete_note` exactly).
    if clip:
        try:
            for thumb in _thumbs.coach_clip_thumbnail_candidates(clip, clip_id, VIDEOS_DIR):
                if _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR):
                    thumb.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            _log.setup("replay").warning(
                "Could not unlink coach clip thumbnail for clip %s: %s", clip_id, exc
            )
    _log_activity(
        "coach.clip_deleted",
        severity="warning",
        message=f"Coaching clip deleted: {clip.get('title', clip_id) if clip else clip_id}",
        match_id=clip.get("match_id") if clip else None,
        slot=clip.get("slot") if clip else None,
        actor=user["username"],
        metadata={"clip_id": clip_id},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
@app.get("/api/coach/clips/{clip_id}/thumbnail")
async def coach_get_clip_thumbnail(clip_id: int, request: Request):
    """Serve the per-clip thumbnail JPEG.

    - Any signed-in user can call this; visibility is enforced per-clip
      via `_can_view_coach_clip`.
    - Returns 404 when the clip does not exist OR when the user cannot
      see it OR when the thumbnail file is missing OR when the
      computed path would escape `VIDEOS_DIR`. Same response shape
      across all four cases so a probing viewer cannot distinguish them.
    """
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("team_admin", "coach") if _auth.has_role(user, "admin", "coach") else None,
        allow_global_admin_override=True,
    )
    team_id = _scope_team_id(scope)
    # PR #108 review fix-up — normalize the 404 detail across all four
    # not-servable cases (unknown clip / unauthorized / path-escape /
    # missing file) so a viewer cannot distinguish them by response
    # body. The note GET still uses two distinct strings ("Thumbnail
    # not found" vs "Thumbnail not generated yet") for backwards
    # compatibility; the clip GET is new in Phase 4e and ships with
    # the cleaner shape from day one.
    clip = _db.get_coaching_clip(clip_id)
    if not clip or not _same_team(clip, team_id):
        raise HTTPException(404, "Thumbnail not found")
    if not _can_view_coach_clip(user, clip, team_id=team_id):
        raise HTTPException(404, "Thumbnail not found")
    try:
        thumb = _media.existing_clip_thumbnail_path(VIDEOS_DIR, clip["match_id"], clip_id, team_id=clip.get("team_id"))
    except ValueError:
        raise HTTPException(404, "Thumbnail not found")
    if not _thumbs.thumb_path_within_videos_dir(thumb, VIDEOS_DIR):
        raise HTTPException(404, "Thumbnail not found")
    if not thumb.is_file():
        raise HTTPException(404, "Thumbnail not found")
    mtime = int(thumb.stat().st_mtime)
    return FileResponse(
        str(thumb),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "ETag": f'"{mtime}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/coach/clips/{clip_id}/thumbnail/regenerate")
async def coach_regenerate_clip_thumbnail(clip_id: int, request: Request):
    """Coach/admin manual trigger for the clip thumbnail generator.
    Useful when the source video lands AFTER the clip was created or
    when a coach edits start_seconds. Synchronous on purpose — the
    caller wants to know whether the refresh succeeded so the UI can
    re-fetch the image."""
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    clip = _require_clip_in_team(clip_id, team_id)
    ok = await _thumbs.regenerate_coach_clip_thumbnail(
        clip,
        clip_id,
        videos_dir=VIDEOS_DIR,
        slot_mp4_path=_slot_mp4_path,
    )
    return {"ok": True, "generated": ok}


@app.get("/api/coach/goals")
async def coach_list_goals(request: Request, player_id: str | None = None):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if player_id:
        _require_player_in_team(player_id, team_id)
    goals = [g for g in _db.list_player_goals(player_id=player_id) if _same_team(g, team_id)]
    return {"goals": _goals_with_visible_sources(goals, user, team_id=team_id)}


@app.post("/api/coach/goals")
async def coach_create_goal(request: Request, body: CreatePlayerGoalRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    season_id = scope.season["id"] if scope.season else None
    data = body.model_dump()
    _require_player_in_team(data["player_id"], team_id)
    _validate_goal_source_links(data, data["player_id"], team_id)
    data["team_id"] = team_id
    data["season_id"] = season_id
    goal = _db.create_player_goal(data, actor=user["username"])
    _log_activity("coach.goal_created", severity="info", message=f"Player goal created: {goal.get('title')}", actor=user["username"], metadata={"goal_id": goal.get("id"), "player_id": goal.get("player_id")})
    return {"ok": True, "goal": _goal_with_visible_sources(goal, user, team_id=team_id)}


@app.patch("/api/coach/goals/{goal_id}")
async def coach_update_goal(goal_id: int, request: Request, body: UpdatePlayerGoalRequest):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_scoped_item(_db.get_player_goal(goal_id), team_id, "Goal not found")
    updates = body.model_dump(exclude_unset=True)
    merged = {**existing, **updates}
    _require_player_in_team(merged["player_id"], team_id)
    _validate_goal_source_links(merged, existing["player_id"], team_id)
    goal = _db.update_player_goal(goal_id, updates, actor=user["username"])
    _log_activity("coach.goal_updated", severity="info", message=f"Player goal updated: {goal.get('title')}", actor=user["username"], metadata={"goal_id": goal_id, "fields": sorted(updates.keys())})
    return {"ok": True, "goal": _goal_with_visible_sources(goal, user, team_id=team_id)}


@app.delete("/api/coach/goals/{goal_id}")
async def coach_delete_goal(goal_id: int, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_scoped_item(_db.get_player_goal(goal_id), team_id, "Goal not found")
    if not _db.delete_player_goal(goal_id):
        raise HTTPException(404, "Goal not found")
    _log_activity("coach.goal_deleted", severity="warning", message=f"Player goal deleted: {existing.get('title', goal_id) if existing else goal_id}", actor=user["username"], metadata={"goal_id": goal_id})
    return {"ok": True}


@app.get("/api/my-feedback/goals")
async def my_feedback_goals(request: Request):
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    goals = _filter_goals_for_user([g for g in _db.list_player_goals() if _same_team(g, team_id)], user, team_id=team_id)
    return {"goals": _goals_with_visible_sources(goals, user, team_id=team_id)}


@app.post("/api/my-feedback/goals/{goal_id}/reflection")
async def my_feedback_goal_reflection(goal_id: int, request: Request, body: CreatePlayerGoalReflectionRequest):
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    goal = _db.get_player_goal(goal_id)
    if not goal or not _same_team(goal, team_id) or goal not in _filter_goals_for_user([goal], user, team_id=team_id):
        raise HTTPException(404, "Goal not found")
    reflection = _db.add_player_goal_reflection(goal_id, user.get("user_id"), body.reflection)
    return {"ok": True, "reflection": {k: v for k, v in reflection.items() if k != "user_id"}}


@app.get("/api/my-feedback")
async def my_feedback(request: Request):
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    players = []
    if user.get("user_id"):
        linked = set(_db.linked_player_ids_for_user(user["user_id"], team_id=team_id))
        players = [p for p in _db.list_players(include_inactive=True, team_id=team_id) if p["id"] in linked]
    all_notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    notes = _filter_notes_for_user(all_notes, user, team_id=team_id)
    # Phase 1 privacy invariant: `coach_private_note` must never reach a
    # viewer. The top-level `notes[]` is already scrubbed by
    # `_filter_notes_for_user`, but `_playlists_with_items` embeds full
    # note objects under `playlists[].items[]` — pass a scrubbed source
    # for that hydration too. Coach/admin call sites get the raw list
    # (no scrub needed). See PR #73 review + the playlist-leak test in
    # tests/test_coaching.py.
    is_privileged = _auth.has_role(user, "admin", "coach")
    items_source = all_notes if is_privileged else [_strip_private_fields(n) for n in all_notes]
    playlists = _playlists_with_items(_filter_playlists_for_user([p for p in _db.list_coaching_playlists() if _same_team(p, team_id)], user, team_id=team_id), items_source)
    visible_note_ids = {n["id"] for n in notes}
    visible_playlist_ids = {p["id"] for p in playlists}
    reviews = [
        r for r in (_db.list_coaching_reviews(user.get("user_id")) if user.get("user_id") else [])
        if (r.get("note_id") is None or r.get("note_id") in visible_note_ids)
        and (r.get("playlist_id") is None or r.get("playlist_id") in visible_playlist_ids)
    ]
    # Phase 4a: clips are first-class objects with the same visibility
    # ladder as notes / playlists. The clip's stored `drawing_json` is a
    # snapshot taken at clip-create time (not a live link to the source
    # note), so a viewer who can see the clip sees the exact visual
    # context the coach saved — no risk of pulling fresh `coach_private_note`
    # text via `source_note_id` because the drawing is JSON metadata, not
    # the source note's body. The clip itself never carries text from
    # the source note's private fields.
    clips = _filter_clips_for_user([c for c in _db.list_coaching_clips() if _same_team(c, team_id)], user, team_id=team_id)
    goals = _filter_goals_for_user([g for g in _db.list_player_goals() if _same_team(g, team_id)], user, team_id=team_id)
    match_summaries = [
        _sanitize_match_summary_sources(s, team_id)
        for s in _filter_match_summaries_for_user([s for s in _db.list_coaching_match_summaries() if _same_team(s, team_id)], user, team_id=team_id)
    ]
    return {
        "players": players, "notes": notes, "playlists": playlists,
        "reviews": reviews, "clips": clips, "goals": _goals_with_visible_sources(goals, user, team_id=team_id),
        "match_summaries": match_summaries,
    }


# ---------------------------------------------------------------------------
# Phase 5a — Player development profile aggregation
#
# Two endpoints share one builder so the aggregation rules (theme counts,
# recent items, review status, focus-area derivation) stay single-sourced
# and the privacy ladder cannot drift between coach and viewer surfaces:
#
#   GET /api/coach/players/{player_id}/development          (coach/admin)
#   GET /api/my-feedback/players/{player_id}/development    (linked viewer)
#
# Privacy invariants:
#   - The coach surface uses the raw note list (so `coach_private_note`
#     stays visible to coach/admin, matching `_filter_notes_for_user`'s
#     short-circuit for privileged users).
#   - The viewer surface filters notes/clips/playlists through the same
#     helpers `/api/my-feedback` uses, so anything excluded there is also
#     excluded here (private notes, unrelated player-specific notes, and
#     `coach_private_note` text via `_strip_private_fields`).
#   - The viewer endpoint additionally requires the player to be linked
#     to the signed-in user's account; otherwise it returns 404 — same
#     code as "unknown player" so an unrelated viewer cannot probe
#     whether a given roster id exists.
#   - Reviews are scoped to the signed-in user on the viewer surface;
#     the coach surface returns the player's full assigned-review set
#     (filtered to items linked to that player).
#
# No new tables. No schema changes. No payload changes to the existing
# /api/my-feedback or /api/coach/* endpoints. Phase 5b will add the UI.
# Phase 6 will introduce explicit player_goals; until then the
# "current_focus_areas" list is derived from recent corrections /
# individual_goal notes and clearly labelled as derived in the response
# shape (`source: "derived_from_recent_notes"`).
# ---------------------------------------------------------------------------


_RECENT_LIMIT = 5
_TOP_LIMIT = 5
_NOTE_TYPES = ("positive", "correction", "question", "team_concept", "individual_goal")


def _notes_for_player(notes: list[dict], player_id: str) -> list[dict]:
    return [n for n in notes if player_id in (n.get("player_ids") or [])]


def _clips_for_player(clips: list[dict], player_id: str) -> list[dict]:
    return [c for c in clips if player_id in (c.get("player_ids") or [])]


def _playlists_for_player(playlists: list[dict], player_id: str, player_note_ids: set[int]) -> list[dict]:
    """A playlist is "for" the player when either it is explicitly
    associated with that player (via `coaching_playlist_players`, exposed
    as `player_ids`) OR when at least one of its ordered items is a note
    the player is tagged on. Playlists already inherit visibility from
    the caller-side filter."""
    out: list[dict] = []
    for playlist in playlists:
        if player_id in (playlist.get("player_ids") or []):
            out.append(playlist)
            continue
        if any(note_id in player_note_ids for note_id in (playlist.get("note_ids") or [])):
            out.append(playlist)
    return out


def _top_counter(values: list[str], limit: int = _TOP_LIMIT) -> list[dict]:
    """Return the most common values as a list of {value, count} dicts.
    Stable for ties (insertion order)."""
    counts: dict[str, int] = {}
    for v in values:
        if not v:
            continue
        counts[v] = counts.get(v, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": k, "count": c} for k, c in ordered[:limit]]


def _theme_counts(notes: list[dict]) -> dict:
    """Phase 1 / Phase 5a aggregation. `note_type` is a closed enum
    (see `_VALID_NOTE_TYPES` in models.py) so we report counts for each
    bucket explicitly rather than just whatever shows up — that way a
    coach can see "0 positives" instead of the field silently missing."""
    by_type: dict[str, int] = {t: 0 for t in _NOTE_TYPES}
    for note in notes:
        t = note.get("note_type") or "correction"
        by_type[t] = by_type.get(t, 0) + 1
    pos = by_type.get("positive", 0)
    cor = by_type.get("correction", 0)
    ratio: float | None
    if cor > 0:
        ratio = round(pos / cor, 2)
    elif pos > 0:
        ratio = None  # all positive, no correction baseline — leave undefined
    else:
        ratio = None
    return {
        "by_note_type": by_type,
        "positive_count": pos,
        "correction_count": cor,
        "question_count": by_type.get("question", 0),
        "team_concept_count": by_type.get("team_concept", 0),
        "individual_goal_count": by_type.get("individual_goal", 0),
        "positive_to_correction_ratio": ratio,
        "top_categories": _top_counter([n.get("category") or "" for n in notes]),
        "top_tags": _top_counter([t for n in notes for t in (n.get("tags") or [])]),
    }


def _sort_recent(items: list[dict], key: str = "updated_at") -> list[dict]:
    """Sort newest-first by ISO timestamp string. Falls back to
    `created_at` then to id-stable ordering so ties stay deterministic."""
    return sorted(
        items,
        key=lambda item: (item.get(key) or item.get("created_at") or "", item.get("id") or 0),
        reverse=True,
    )


def _summarize_review_status(
    *,
    notes: list[dict],
    playlists: list[dict],
    reviews: list[dict],
) -> dict:
    """Aggregate review/reflection state across the items already
    filtered for the caller's role. Clip review tracking is not
    implemented yet (`coaching_reviews` only carries note_id /
    playlist_id) so we report that explicitly so the UI doesn't display
    a misleading 0/N for clips."""
    note_ids = {n["id"] for n in notes}
    playlist_ids = {p["id"] for p in playlists}
    note_reviews = [r for r in reviews if r.get("note_id") in note_ids]
    playlist_reviews = [r for r in reviews if r.get("playlist_id") in playlist_ids]
    # `_db.list_coaching_reviews` returns rows ORDER BY reviewed_at DESC,
    # so each sub-list above is individually DESC-sorted — but their
    # concatenation is NOT globally sorted (the first playlist review
    # could pre-date the last note review). Build one globally sorted
    # list and source BOTH `latest_reviewed_at` and `latest_reflection`
    # from it so they can never disagree. (PR #103 review fix.)
    all_reviews_sorted = _sort_recent(note_reviews + playlist_reviews, key="reviewed_at")
    latest_reviewed_at = all_reviews_sorted[0]["reviewed_at"] if all_reviews_sorted else None
    reflections_sorted = [r for r in all_reviews_sorted if (r.get("reflection") or "").strip()]
    latest_reflection_row = reflections_sorted[0] if reflections_sorted else None
    return {
        "notes": {
            "assigned_count": len(note_ids),
            "reviewed_count": len({r["note_id"] for r in note_reviews if r.get("note_id")}),
        },
        "playlists": {
            "assigned_count": len(playlist_ids),
            "reviewed_count": len({r["playlist_id"] for r in playlist_reviews if r.get("playlist_id")}),
        },
        "clips": {
            "assigned_count": 0,  # filled in by caller
            "review_supported": False,
        },
        "latest_reviewed_at": latest_reviewed_at,
        "reflection_count": len(reflections_sorted),
        "latest_reflection": (
            {
                "note_id": latest_reflection_row.get("note_id"),
                "playlist_id": latest_reflection_row.get("playlist_id"),
                "reflection": latest_reflection_row["reflection"],
                "reviewed_at": latest_reflection_row["reviewed_at"],
            }
            if latest_reflection_row
            else None
        ),
    }


def _derive_focus_areas(notes: list[dict]) -> list[dict]:
    """Phase 6 will add real `player_goals`. Until then we surface
    "what to do next" cues from recent correction / individual_goal
    notes and label them as derived so any future client UI doesn't
    treat them as formal goals."""
    candidates = [
        n for n in notes
        if n.get("note_type") in {"correction", "individual_goal"}
        and (n.get("what_to_do_next") or "").strip()
    ]
    recent = _sort_recent(candidates)[:_RECENT_LIMIT]
    return [
        {
            "note_id": n["id"],
            "note_type": n.get("note_type"),
            "category": n.get("category"),
            "what_to_do_next": n.get("what_to_do_next") or "",
            "match_id": n.get("match_id"),
            "slot": n.get("slot"),
            "updated_at": n.get("updated_at"),
            "source": "derived_from_recent_notes",
        }
        for n in recent
    ]


def _build_player_development_profile(
    *,
    player: dict,
    user: dict,
    viewer_scoped: bool,
    team_id: str | None = None,
) -> dict:
    """Single source of truth for both endpoints. When `viewer_scoped`
    is True, all source lists are filtered through the same helpers
    that gate `/api/my-feedback`; otherwise the raw lists are used so a
    coach/admin sees the full data set including private notes."""
    all_notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    all_clips = [c for c in _db.list_coaching_clips() if _same_team(c, team_id)]
    all_playlists = [p for p in _db.list_coaching_playlists() if _same_team(p, team_id)]
    all_goals = [g for g in _db.list_player_goals() if _same_team(g, team_id)]
    if viewer_scoped:
        # Defense-in-depth: `_filter_notes_for_user` short-circuits for
        # admin/coach callers and returns the raw list (with
        # `coach_private_note` un-stripped). A coach/admin who happens
        # to be linked to this player via `player_user_links` can hit
        # this viewer endpoint, so we must NOT rely on that helper to
        # scrub for us. Always run every note flowing into a
        # `viewer_scoped=True` profile through `_strip_private_fields`
        # so `coach_private_note` is `""` regardless of caller role.
        # (PR #103 review fix — keeps the `viewer_scoped: true` payload
        # contract honest even for coach callers.)
        notes_source = [
            _strip_private_fields(n) for n in _filter_notes_for_user(all_notes, user, team_id=team_id)
        ]
        clips_source = _filter_clips_for_user(all_clips, user, team_id=team_id)
        playlists_source = _filter_playlists_for_user(all_playlists, user, team_id=team_id)
        goals_source = _goals_with_visible_sources(_filter_goals_for_user(all_goals, user, team_id=team_id), user, team_id=team_id)
    else:
        notes_source = all_notes
        clips_source = all_clips
        playlists_source = all_playlists
        goals_source = _goals_with_visible_sources(all_goals, user, team_id=team_id)

    pid = player["id"]
    notes = _notes_for_player(notes_source, pid)
    clips = _clips_for_player(clips_source, pid)
    note_ids = {n["id"] for n in notes}
    playlists = _playlists_for_player(playlists_source, pid, note_ids)
    goals = [g for g in goals_source if g.get("player_id") == pid]
    active_goals = [g for g in goals if g.get("status") in _ACTIVE_GOAL_STATUSES]

    # Reviews on the viewer surface are scoped to the signed-in user so
    # other linked-account reviews never leak. On the coach surface we
    # report the full assigned-review set across all users so the coach
    # can see who has engaged with what.
    if viewer_scoped:
        reviews = [
            r for r in (_db.list_coaching_reviews(user.get("user_id")) if user.get("user_id") else [])
            if (r.get("note_id") is None or r.get("note_id") in note_ids)
            and (r.get("playlist_id") is None or r.get("playlist_id") in {p["id"] for p in playlists})
        ]
    else:
        reviews = _db.list_coaching_reviews()

    review_summary = _summarize_review_status(notes=notes, playlists=playlists, reviews=reviews)
    review_summary["clips"]["assigned_count"] = len(clips)

    notes_recent = _sort_recent(notes)
    clips_recent = _sort_recent(clips)
    playlists_recent = _sort_recent(playlists)

    recent_positives = [n for n in notes_recent if n.get("note_type") == "positive"][:_RECENT_LIMIT]
    recent_corrections = [n for n in notes_recent if n.get("note_type") == "correction"][:_RECENT_LIMIT]

    profile = {
        "player": {
            "id": player["id"],
            "display_name": player.get("display_name") or "",
            "jersey_number": player.get("jersey_number") or "",
            "active": bool(player.get("active", True)),
            "notes_field": player.get("notes") or "",
            "links_count": len(player.get("links") or []),
        },
        "counts": {
            "notes": len(notes),
            "clips": len(clips),
            "playlists": len(playlists),
            "goals": len(active_goals),
        },
        "themes": _theme_counts(notes),
        "review_status": review_summary,
        "recent_notes": notes_recent[:_RECENT_LIMIT],
        "recent_positives": recent_positives,
        "recent_corrections": recent_corrections,
        "recent_clips": clips_recent[:_RECENT_LIMIT],
        "active_goals": active_goals,
        "recent_playlists": [
            {
                "id": p["id"], "title": p.get("title") or "",
                "visibility": p.get("visibility"), "item_count": len(p.get("note_ids") or []),
                "updated_at": p.get("updated_at"),
            }
            for p in playlists_recent[:_RECENT_LIMIT]
        ],
        "current_focus_areas": _derive_focus_areas(notes),
        "viewer_scoped": viewer_scoped,
    }

    if not viewer_scoped:
        # Coach surface: lightweight linked-account summary so the coach
        # can see how the player connects to family/player accounts
        # without re-fetching the roster. Values come from the same
        # `links` list `/api/coach/players` already returns to coach/admin.
        profile["linked_accounts"] = [
            {
                "user_id": link.get("user_id"),
                "username": link.get("username"),
                "display_name": link.get("display_name") or "",
                "relationship": link.get("relationship"),
            }
            for link in (player.get("links") or [])
        ]

    return profile


@app.get("/api/coach/engagement")
async def coach_engagement_dashboard(
    request: Request,
    player_id: str | None = None,
    playlist_id: int | None = None,
    match_id: str | None = None,
    visibility: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if player_id and not _db.get_player(player_id, team_id=team_id):
        raise HTTPException(404, "Player not found")
    if playlist_id is not None and not _same_team(_db.get_coaching_playlist(playlist_id) or {}, team_id):
        raise HTTPException(404, "Playlist not found")
    if match_id and not _same_team(_db.get_match_by_id(match_id) or {}, team_id):
        raise HTTPException(404, "Match not found")
    if visibility and visibility not in {"player", "team"}:
        raise HTTPException(422, "Invalid visibility filter")
    return {"engagement": _engagement.build_coach_engagement_dashboard(player_id=player_id, playlist_id=playlist_id, match_id=match_id, visibility=visibility, start_date=start_date, end_date=end_date, team_id=team_id)}


@app.get("/api/coach/players/{player_id}/development")
async def coach_player_development(player_id: str, request: Request):
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    player = _db.get_player(player_id, team_id=team_id)
    if not player:
        raise HTTPException(404, "Player not found")
    return {"profile": _build_player_development_profile(player=player, user=user, viewer_scoped=False, team_id=team_id)}


@app.get("/api/my-feedback/players/{player_id}/development")
async def my_feedback_player_development(player_id: str, request: Request):
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    # Coach/admin viewing their own /my-feedback profile would see the
    # raw set; defer to the dedicated coach endpoint instead so the two
    # surfaces don't quietly diverge in payload shape. Here we always
    # gate on "is this player linked to the requesting user" — using the
    # same 404 we'd return for an unknown player so an unrelated viewer
    # cannot probe whether a roster id exists.
    if not user.get("user_id"):
        raise HTTPException(404, "Player not found")
    linked_player_ids = set(_db.linked_player_ids_for_user(user["user_id"], team_id=team_id))
    if player_id not in linked_player_ids:
        raise HTTPException(404, "Player not found")
    player = _db.get_player(player_id, team_id=team_id)
    if not player:
        raise HTTPException(404, "Player not found")
    return {"profile": _build_player_development_profile(player=player, user=user, viewer_scoped=True, team_id=team_id)}


@app.post("/api/my-feedback/review")
async def mark_my_feedback_review(request: Request, body: MarkCoachingReviewRequest):
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    if not user.get("user_id"):
        raise HTTPException(403, "Feedback review tracking requires a database user")
    if not body.note_id and not body.playlist_id:
        raise HTTPException(422, "note_id or playlist_id is required")
    visible_note_ids = {n["id"] for n in _filter_notes_for_user([n for n in _db.list_coaching_notes() if _same_team(n, team_id)], user, team_id=team_id)}
    visible_playlist_ids = {p["id"] for p in _filter_playlists_for_user([p for p in _db.list_coaching_playlists() if _same_team(p, team_id)], user, team_id=team_id)}
    if body.note_id and body.note_id not in visible_note_ids:
        raise HTTPException(403, "Note is not visible to this user")
    if body.playlist_id and body.playlist_id not in visible_playlist_ids:
        raise HTTPException(403, "Playlist is not visible to this user")
    review = _db.mark_coaching_review(user["user_id"], body.note_id, body.playlist_id, body.reflection)
    return {"ok": True, "review": review}


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


@app.get("/api/admin/diagnostics")
async def admin_diagnostics(request: Request):
    _auth.require_role(request, "admin")
    stale_seconds = current_stale_upload_session_seconds()
    _uploads.cleanup_stale_sessions(stale_seconds)

    matches = await _load_matches()
    upload_sessions = _uploads.list_session_views(stale_seconds, ("active", "completed", "cancelled", "replaced"))[:12]
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
    recent_activity = _db.get_activity_events(limit=20, max_age_hours=72)

    disk_by_match = await asyncio.to_thread(_cached_disk_usage_by_match)

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
            "max_upload_size_bytes": current_max_upload_size_bytes(),
            "chunk_size_bytes": current_upload_chunk_size_bytes(),
            "stale_upload_session_seconds": stale_seconds,
        },
        "transcode": {
            "concurrency_limit": current_transcode_concurrency(),
            "gpu": _media.get_gpu_health(),
        },
        "hls": {
            "backfill_running": HLS_BACKFILL_LOCK.locked(),
        },
        "upload_sessions": upload_sessions,
        "failed_slots": failed_slots,
        "active_jobs": active_jobs,
        # Slots whose HLS variant ladder is currently being rebuilt by an
        # admin-triggered regen (fire-and-forget background task). Each entry
        # is { key: "match_id/slot", elapsed_seconds: float } so the frontend
        # can show "regenerating HLS · 2:34" instead of just a binary state.
        # Elapsed comes from a monotonic clock so NTP jumps don't corrupt it.
        "regen_hls_in_flight": [
            {"key": key, "elapsed_seconds": max(0.0, time.monotonic() - started)}
            for key, (task, started) in _regen_hls_tasks.items()
            if task and not task.done()
        ],
        "recent_errors": recent_errors,
        "recent_activity": recent_activity,
    }


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


@app.get("/api/admin/performance")
async def admin_performance(request: Request):
    """Aggregated throughput + host + transcode signals for the Performance
    Tuning panel. Single round-trip per refresh; bundles cleanly for export."""
    _auth.require_role(request, "admin")

    settings = await _load_settings()
    history = _media.get_transcode_history()
    samples = _streams.get_throughput_samples()
    capture = _streams.capture_status()
    active_sessions = [s.to_dict() for s in _streams.registry.list_active()]

    # Tail-summary: last sample's bps and the trailing average over ~30 s.
    last = samples[-1] if samples else None
    tail_window = samples[-30:] if samples else []
    avg_live_bps = sum(s.get("bps_live_out", 0) for s in tail_window) / max(1, len(tail_window))
    avg_vod_bps = sum(s.get("bps_vod_out", 0) for s in tail_window) / max(1, len(tail_window))

    # Recent transcode realtime factors — newest first for display.
    recent_rt = [h for h in reversed(history) if h.get("rt_factor") is not None][:10]

    redacted_settings = {
        # Tuning knobs only — never leak the full settings table here. Stream
        # key is already stripped because admin_payload omits PRIVATE_SETTING_KEYS.
        key: settings.get(key, "")
        for key in _settings.TUNING_KNOBS.keys()
    }

    return {
        "ts": _now_ms(),
        "host": _host_signals(),
        "disk": _disk_pools(),
        "throughput": {
            "samples": samples,
            "last": last,
            "avg_live_bps_30s": round(avg_live_bps, 1),
            "avg_vod_bps_30s": round(avg_vod_bps, 1),
            "capture": capture,
        },
        "transcode": {
            "concurrency_limit": current_transcode_concurrency(),
            "gpu": _media.get_gpu_health(),
            "recent": recent_rt,
            "history_size": len(history),
        },
        "active_sessions": active_sessions,
        "tuning_settings": redacted_settings,
    }


@app.post("/api/admin/performance/capture")
async def admin_performance_capture(request: Request, body: StartCaptureRequest | None = None):
    """Start a high-frequency capture window. The sweeper samples at 1 Hz
    instead of the regular interval for `body.seconds` seconds. Body is
    optional; default 60 s, validated to [5, 600] by the Pydantic model."""
    _auth.require_role(request, "admin")
    seconds = body.seconds if body is not None else 60.0
    return _streams.start_capture_window(seconds=seconds)


@app.post("/api/admin/backfill-hls")
async def admin_backfill_hls(request: Request):
    user = _auth.require_role(request, "admin")
    result = await _backfill_hls_for_existing_videos()
    logger.info("admin.action", extra={"action": "backfill_hls", "actor": user["username"]})
    _log_activity(
        "hls.backfill",
        severity="info",
        message="HLS backfill completed",
        actor=user["username"],
        metadata=result,
    )
    return {"ok": True, **result}


@app.get("/api/admin/matches/{match_id}/errors")
async def admin_match_errors(match_id: str, request: Request):
    _auth.require_role(request, "admin")
    errors = _db.get_video_errors(match_id=match_id, limit=50)
    return {"errors": errors}


@app.post("/api/admin/matches/{match_id}/slots/{slot}/retry")
async def admin_retry_transcode(match_id: str, slot: str, request: Request):
    """Re-transcode a slot from the existing MP4 or raw upload file.

    Default mode: only `error` slots can be retried. Pass `?force=true` to
    retranscode a `ready` slot — useful for picking up new encoder settings
    (QSV, 1440p tier, audio bitrate) on already-completed matches without a
    fresh upload. `transcoding` slots are always rejected.
    """
    user = _auth.require_role(request, "admin")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    force = (request.query_params.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}

    # CAS: status 'error' (or 'ready' with ?force) → 'transcoding' inside the
    # lock so concurrent retries are rejected before either reaches the FS.
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        current_status = _get_video_status(match, slot)
        allowed = {"error"} if not force else {"error", "ready"}
        if current_status not in allowed:
            hint = "" if force else " (pass ?force=true to re-transcode a ready slot)"
            raise HTTPException(
                409,
                f"Slot status is '{current_status}', must be {sorted(allowed)} to retry{hint}",
            )
        match.setdefault("video_status", {})[slot] = "transcoding"
        _db.save_matches_unlocked(matches)

    existing_final_path = _slot_mp4_path(match_id, slot)
    final_path = _slot_mp4_write_path(match_id, slot)

    # Prefer raw upload file if it still exists; otherwise re-stage the
    # existing MP4 as a raw file. Both live on ORIGINALS_DIR.
    src = _find_slot_raw_path(match_id, slot)
    if src is None and existing_final_path.is_file():
        # Re-transcode from the existing MP4. Promote it to a raw-named path
        # first so source and destination are distinct — transcode_video does
        # `dest.unlink(missing_ok=True)` before invoking ffmpeg, which would
        # otherwise delete its own input.
        raw_promoted = _slot_raw_path(match_id, slot, ".mp4")
        try:
            raw_promoted.parent.mkdir(parents=True, exist_ok=True)
            existing_final_path.rename(raw_promoted)
        except OSError as exc:
            await _set_video_status(match_id, slot, "error", None, error_info={
                "error_code": "retry_rename_failed",
                "reason": str(exc),
                "details": f"Failed to stage {existing_final_path.name} → {raw_promoted.name} for retry",
            })
            raise HTTPException(500, "Failed to stage source file for retry") from exc
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
    logger.info(
        "admin.action",
        extra={
            "action": "retry_transcode" if not force else "force_retranscode",
            "actor": user["username"],
            "target_id": match_id,
            "slot": slot,
        },
    )
    _log_activity(
        "transcode.retry_requested" if not force else "transcode.force_requested",
        severity="warning" if force else "info",
        message="Force re-transcode requested" if force else "Transcode retry requested",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"source": src.name, "forced": force},
    )
    return {"ok": True, "status": "transcoding", "source": src.name, "forced": force}


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


@app.post("/api/admin/matches/{match_id}/slots/{slot}/regenerate-hls")
async def admin_regenerate_hls(match_id: str, slot: str, request: Request):
    """Kick off an async HLS regeneration and return 202 immediately.

    Why fire-and-forget: the actual ffmpeg work to re-segment a multi-GB
    MP4 across 3 variants typically takes 1–10 minutes. Cloudflare (and
    most edge proxies) cap origin response latency around 100 s — the
    previous synchronous handler hit Cloudflare's 524 every time, even
    though the server-side work was succeeding. Now we validate the
    request synchronously (slot, match, mp4 exists, no regen already in
    flight), spawn ``_run_regen_hls_task`` as a tracked background task,
    and return 202 with a job key the frontend can poll. Failures land
    in the ``video_errors`` table (so they show up in the admin Recent
    Errors panel) and in stdout (so they're greppable in the container
    log).
    """
    user = _auth.require_role(request, "admin")
    actor = user.get("username") if isinstance(user, dict) else "?"
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _db.get_match_by_id(match_id)
    if not match:
        logger.info(
            "regen_hls.skipped: match_not_found %s", match_id,
            extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "reason": "match_not_found"},
        )
        raise HTTPException(404, "Match not found")

    mp4_path = _slot_mp4_path(match_id, slot)
    if not mp4_path.is_file():
        logger.warning(
            "regen_hls.skipped: mp4_not_found %s/%s at %s", match_id, slot, mp4_path,
            extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "reason": "mp4_not_found"},
        )
        _db.log_video_error(
            match_id, slot,
            "REGEN_HLS_MP4_MISSING",
            "Regen HLS skipped — MP4 not found on disk.",
            f"Expected at {mp4_path}. The slot may need a Re-transcode (or a fresh upload) before HLS can be rebuilt.",
        )
        raise HTTPException(404, f"MP4 file not found on disk at {mp4_path}")

    key = f"{match_id}/{slot}"
    existing = _regen_hls_tasks.get(key)
    if existing is not None:
        existing_task, _ = existing
        if not existing_task.done():
            logger.info(
                "regen_hls.skipped: already_in_flight %s/%s", match_id, slot,
                extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "reason": "already_in_flight"},
            )
            raise HTTPException(409, "An HLS regeneration is already in flight for this slot.")

    logger.info(
        "regen_hls.start %s/%s by %s (mp4=%s, %s bytes) — running async, response is 202",
        match_id, slot, actor, mp4_path, mp4_path.stat().st_size,
        extra={"action": "regenerate_hls", "actor": actor, "target_id": match_id, "slot": slot, "phase": "start"},
    )
    _log_activity(
        "hls.regenerate_started",
        severity="info",
        message="HLS regeneration started",
        match_id=match_id,
        slot=slot,
        actor=actor,
        metadata={"bytes": mp4_path.stat().st_size},
    )
    task = _spawn_task(_run_regen_hls_task(match_id, slot, mp4_path, actor))
    _regen_hls_tasks[key] = (task, time.monotonic())
    task.add_done_callback(lambda _t: _regen_hls_tasks.pop(key, None))
    return JSONResponse(
        status_code=202,
        content={"ok": True, "slot": slot, "status": "regenerating", "match_id": match_id},
    )


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
            mp4_path = _slot_mp4_path(match_id, slot)
            if mp4_path.is_file():
                chosen_slot = slot
                break
    if not chosen_slot:
        raise HTTPException(
            404,
            "No ready slot available — request a specific slot or wait for a transcode to complete",
        )

    mp4_path = _slot_mp4_path(match_id, chosen_slot)
    thumb_path = VIDEOS_DIR / match_id / "thumb.jpg"
    thumb_path.unlink(missing_ok=True)
    ok = await _media.generate_thumbnail(mp4_path, thumb_path)
    if not ok:
        raise HTTPException(500, "Thumbnail generation failed")
    logger.info("admin.action", extra={"action": "regenerate_thumbnail", "actor": user["username"], "target_id": match_id, "slot": chosen_slot})
    _log_activity(
        "thumbnail.regenerated",
        severity="success",
        message="Thumbnail regenerated",
        match_id=match_id,
        slot=chosen_slot,
        actor=user["username"],
    )
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
        report = _media.verify_slot_assets(VIDEOS_DIR, match_id, slot, originals_dir=ORIGINALS_DIR)
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
    _log_activity(
        "database.exported",
        severity="info",
        message="Database exported",
        actor=user["username"],
    )
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
async def list_matches(
    request: Request,
    q: str | None = None,
    page: int | None = None,
    limit: int | None = None,
    team_id: str | None = None,
    season_id: str | None = None,
):
    scoped = bool(team_id or season_id)
    scope = None
    if scoped:
        user = _auth.require_auth(request)
        scope = _tenancy.resolve_scope(
            request,
            user,
            team_id=team_id,
            season_id=season_id,
            require_role="match:read",
            allow_global_admin_override=True,
        )
        team_id = scope.team["id"]
        season_id = scope.season["id"] if scope.season else season_id

    if q is not None or page is not None or limit is not None:
        clamped_limit = max(1, min(limit or 50, 200))
        matches, total = _db.search_matches(q=q, page=page or 1, limit=clamped_limit)
        if scoped:
            matches = [m for m in matches if str(m.get("team_id")) == str(team_id)]
            if season_id:
                matches = [m for m in matches if str(m.get("season_id")) == str(season_id)]
            total = len(matches)
        return {"matches": [_enrich_match(m) for m in matches], "total": total, "page": page or 1, "limit": clamped_limit}
    # No query params: return the 500 most-recent matches to bound payload size.
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked(limit=500)
    if scoped:
        matches = [m for m in matches if str(m.get("team_id")) == str(team_id)]
        if season_id:
            matches = [m for m in matches if str(m.get("season_id")) == str(season_id)]
    return [_enrich_match(m) for m in matches]


@app.post("/api/matches")
async def create_match(request: Request, body: CreateMatchRequest):
    user = _auth.require_role(request, "admin", "uploader")
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
        "updated_at": _now_ms(),
        "slug": "",
    }

    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)

    async with MATCHES_LOCK:
        with _db.connect() as conn:
            match["slug"] = _db.ensure_unique_slug(conn, slug_base)
        matches = _db.load_matches_unlocked()
        matches.append(match)
        _db.save_matches_unlocked(matches)
    _log_activity(
        "match.created",
        severity="info",
        message=f"Match added: {body.home_team} vs {body.away_team}",
        match_id=match_id,
        actor=user["username"],
        metadata={"slug": match["slug"], "format": body.format},
    )
    return match


@app.put("/api/matches/{match_id}")
async def update_match(match_id: str, request: Request, body: UpdateMatchRequest):
    user = _auth.require_role(request, "admin", "uploader")
    updates = body.model_dump(exclude_unset=True)
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked()
        match = _db.find_match(matches, match_id)
        if not match:
            raise HTTPException(404, "Match not found")

        if_match = request.headers.get("if-match", "").strip('"')
        if if_match and if_match != match.get("updated_at", ""):
            raise HTTPException(409, "Match was modified by another user. Reload and try again.")

        slug_fields_changed = False
        for key, value in updates.items():
            if key in ("home_team", "away_team", "date") and value != match.get(key):
                slug_fields_changed = True
            match[key] = value

        if slug_fields_changed or not match.get("slug"):
            slug_base = _db.generate_slug(match["home_team"], match["away_team"], match.get("date", ""))
            with _db.connect() as conn:
                match["slug"] = _db.ensure_unique_slug(conn, slug_base, exclude_id=match["id"])

        match["updated_at"] = _now_ms()
        _db.save_matches_unlocked(matches)
        updated_match = dict(match)
    _log_activity(
        "match.updated",
        severity="info",
        message=f"Match updated: {updated_match.get('home_team', '')} vs {updated_match.get('away_team', '')}",
        match_id=match_id,
        actor=user["username"],
        metadata={"fields": sorted(updates.keys())},
    )
    return updated_match


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

    # Remove both the hot-path tree (HLS, thumbnail) and the cold-path tree
    # (raw uploads + finished MP4). When tiered they're separate volumes;
    # when collapsed they're the same path and the second rmtree is a no-op.
    cleanup_dirs = {VIDEOS_DIR / match_id, ORIGINALS_DIR / match_id}
    team_id = match.get("team_id") if match else None
    if team_id:
        try:
            cleanup_dirs.add(_media.slot_hls_dir(VIDEOS_DIR, match_id, "full", team_id=team_id).parents[1])
            cleanup_dirs.add(_media.match_originals_dir(ORIGINALS_DIR, match_id, team_id=team_id))
        except ValueError:
            pass
    for d in cleanup_dirs:
        if d.exists():
            shutil.rmtree(str(d))
    logger.info("admin.action", extra={"action": "delete_match", "actor": user["username"], "target_id": match_id})
    _log_activity(
        "match.deleted",
        severity="warning",
        message=f"Match deleted: {match.get('home_team', '')} vs {match.get('away_team', '')}",
        match_id=match_id,
        actor=user["username"],
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Video Upload & Streaming
# ---------------------------------------------------------------------------

@app.post("/api/matches/{match_id}/upload-video/session")
async def create_upload_session(match_id: str, request: Request, body: CreateUploadSessionRequest):
    user = _auth.require_role(request, "admin", "uploader")
    stale_seconds = current_stale_upload_session_seconds()
    _uploads.cleanup_stale_sessions(stale_seconds)
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    filename = body.filename.strip()
    size_bytes = body.size_bytes
    max_upload = current_max_upload_size_bytes()
    if size_bytes > max_upload:
        raise HTTPException(413, f"Uploaded file exceeds max size of {max_upload} bytes")

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
            existing["id"], match_id, slot, existing["next_index"],
            extra={"session_id": existing["id"], "match_id": match_id, "slot": slot},
        )
        return _uploads.session_payload(existing)

    _ensure_disk_space(size_bytes)
    _uploads.cancel_conflicting_sessions(match_id, slot)

    # Raw upload lands on the cold pool (ORIGINALS_DIR). Make sure the per-
    # match directory there exists first; the SSD-side videos directory is
    # also ensured because thumbnails + HLS still write to it post-transcode.
    (ORIGINALS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    raw_path = _slot_raw_path(match_id, slot, ext)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)

    session_id = uuid.uuid4().hex
    chunk_size = current_upload_chunk_size_bytes()
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
        session_id, match_id, slot, size_bytes, total_chunks,
        extra={"session_id": session_id, "match_id": match_id, "slot": slot,
               "size_bytes": size_bytes, "total_chunks": total_chunks},
    )
    _log_activity(
        "upload.started",
        severity="info",
        message="Upload started",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"session_id": session_id, "filename": filename, "size_bytes": size_bytes},
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
    stale_seconds = current_stale_upload_session_seconds()
    if status_param == "all":
        sessions = _uploads.list_session_views(stale_seconds, None)
    else:
        statuses = tuple(part.strip() for part in status_param.split(",") if part.strip())[:8]
        sessions = _uploads.list_session_views(stale_seconds, statuses or ("active",))
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
    return _uploads.session_view(row, current_stale_upload_session_seconds())


@app.delete("/api/uploads/sessions/{session_id}")
async def cancel_upload_session(session_id: str, request: Request):
    user = _auth.require_role(request, "admin", "uploader")
    row = _uploads.mark_session_status(session_id, "cancelled")
    if not row:
        raise HTTPException(404, "Upload session not found")
    _log_activity(
        "upload.cancelled",
        severity="warning",
        message="Upload cancelled",
        match_id=row["match_id"],
        slot=row["slot"],
        actor=user["username"],
        metadata={"session_id": session_id},
    )
    return {"ok": True, "session": _uploads.session_view(row, current_stale_upload_session_seconds())}


@app.post("/api/uploads/sessions/cleanup")
async def cleanup_upload_sessions(request: Request):
    _auth.require_role(request, "admin")
    cleaned = _uploads.cleanup_stale_sessions(current_stale_upload_session_seconds())
    expired = _uploads.cleanup_old_completed_sessions()
    orphaned = _uploads.cleanup_orphaned_raw_files(VIDEOS_DIR, originals_dir=ORIGINALS_DIR)
    return {
        "ok": True,
        "cleaned_session_ids": cleaned,
        "count": len(cleaned),
        "expired_sessions": expired,
        "orphaned_files_removed": len(orphaned),
    }


@app.post("/api/uploads/sessions/{session_id}/complete")
async def complete_upload_session(session_id: str, request: Request):
    user = _auth.require_role(request, "admin", "uploader")
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
    final_path = _slot_mp4_write_path(match_id, slot)

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
        session_id, match_id, slot, actual_size,
        extra={"session_id": session_id, "match_id": match_id, "slot": slot, "size_bytes": actual_size},
    )
    _log_activity(
        "upload.completed",
        severity="success",
        message="Upload completed",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"session_id": session_id, "size_bytes": actual_size},
    )
    _spawn_transcode(match_id, slot, raw_path, final_path)
    return {"ok": True, "status": "transcoding", "slot": slot, "size_mb": round(actual_size / 1e6, 1)}

@app.post("/api/matches/{match_id}/upload-video")
async def upload_video(match_id: str, file: UploadFile, request: Request):
    """Upload a video file (MP4 / MKV).  Query param: slot=full|first_half|second_half"""
    user = _auth.require_role(request, "admin", "uploader")
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

    # Raw upload + finished MP4 live on the cold pool (ORIGINALS_DIR);
    # HLS + thumbnails will land on VIDEOS_DIR after transcode.
    (ORIGINALS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)

    raw_path = _slot_raw_path(match_id, slot, ext)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    max_upload = current_max_upload_size_bytes()
    logger.info(
        "Upload started: %s/%s filename=%s max_size_bytes=%d",
        match_id, slot, fname, max_upload,
        extra={"match_id": match_id, "slot": slot, "upload_filename": fname},
    )
    started_at = time.time()
    try:
        bytes_written = await _save_upload_file(file, raw_path, max_size_bytes=max_upload)
    except HTTPException:
        raw_path.unlink(missing_ok=True)
        raise

    size_mb = round(bytes_written / 1e6, 1)
    elapsed = round(time.time() - started_at, 2)
    logger.info(
        "Upload saved: %s/%s (%s MB in %ss) — starting transcode",
        match_id, slot, size_mb, elapsed,
        extra={"match_id": match_id, "slot": slot, "size_mb": size_mb, "elapsed_s": elapsed},
    )
    _log_activity(
        "upload.completed",
        severity="success",
        message="Upload completed",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"filename": fname, "size_bytes": bytes_written, "elapsed_s": elapsed},
    )

    await _set_video_status(match_id, slot, "transcoding", None)

    final_path = _slot_mp4_write_path(match_id, slot)
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

    vid_path = _slot_mp4_path(match_id, slot)
    if not vid_path.is_file():
        raise HTTPException(404, "Video not found")

    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-mp4", match_id, slot):
        raise HTTPException(403, "Stream killed by admin")

    return _range_file_response(
        vid_path, "video/mp4", request,
        match_id=match_id, slot=slot, kind="vod-mp4",
    )


@app.get("/api/transcode-progress")
async def all_transcode_progress():
    """Return progress for every active transcode job in one request."""
    return {
        key: {"active": True, **prog}
        for key, prog in _media.get_all_transcode_progress().items()
    }


@app.get("/api/matches/{match_id}/transcode-progress/{slot}")
async def transcode_progress(match_id: str, slot: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    progress = _media.get_transcode_progress(match_id, slot)
    if not progress:
        return {"active": False}
    return {"active": True, **progress}


@app.post("/api/matches/{match_id}/heartbeat")
async def vod_playback_heartbeat(match_id: str, request: Request):
    """Keep a VOD HLS viewer's session warm in the streams registry.

    HLS segments for VOD are served directly by Caddy from the bind-mount
    (see CLAUDE.md "Caddy reverse proxy serves VOD HLS segments directly"),
    so segment fetches never reach FastAPI and don't update last_activity.
    Without a heartbeat, an active viewer is reaped after HLS_IDLE_SECONDS
    (~15 s) and disappears from the admin UI mid-playback.

    js/player.js pings this every ~10 s while a video is playing. The
    endpoint just calls registry.touch() — same path the master/variant
    playlist fetches take — so the session stays current. No body, no
    side effects, no auth required (viewers are anonymous).
    """
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    ip = _streams.client_ip(request)
    if _streams.registry.is_blocked(ip, "vod-hls", match_id, slot):
        # Mirror the playlist endpoint's behavior so the player can detect
        # an admin kill and stop pinging.
        raise HTTPException(403, "Stream killed by admin")
    _streams.registry.touch(
        "vod-hls", match_id, slot, ip, request.headers.get("user-agent", ""),
    )
    return {"ok": True}


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

    vid_path = _slot_mp4_path(match_id, slot)
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

@app.get("/api/matches/{match_id}/hls/teams/{team_id}/{slot}/master.m3u8")
async def stream_hls_master_team(match_id: str, team_id: str, slot: str, request: Request):
    return await _stream_hls_master_common(match_id, slot, request, team_id=team_id)


def _hls_response_headers(cache_control: str) -> dict[str, str]:
    return {
        "Cache-Control": cache_control,
        "Access-Control-Allow-Origin": "*",
    }


@app.get("/api/matches/{match_id}/hls/{slot}/master.m3u8")
async def stream_hls_master(match_id: str, slot: str, request: Request):
    return await _stream_hls_master_common(match_id, slot, request)


async def _stream_hls_master_common(match_id: str, slot: str, request: Request, *, team_id: str | None = None):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    if team_id is not None and str(match.get("team_id") or "") != team_id:
        raise HTTPException(404, "HLS playlist not found")

    status = _get_video_status(match, slot)
    if status == "transcoding":
        raise HTTPException(404, "HLS not ready yet")
    if status == "error":
        raise HTTPException(500, "Video processing failed")

    master_path = _media.existing_slot_hls_master_path(VIDEOS_DIR, match_id, slot, team_id=match.get("team_id"))
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
        # Playlists must NOT be `immutable` — re-transcode rewrites them.
        # 60s revalidation matches the live HLS proxy policy in live.py.
        headers=_hls_response_headers("public, max-age=60, must-revalidate"),
    )


@app.get("/api/matches/{match_id}/hls/teams/{team_id}/{slot}/{asset_path:path}")
async def stream_hls_asset_team(match_id: str, team_id: str, slot: str, asset_path: str, request: Request):
    return await _stream_hls_asset_common(match_id, slot, asset_path, request, team_id=team_id)


@app.get("/api/matches/{match_id}/hls/{slot}/{asset_path:path}")
async def stream_hls_asset(match_id: str, slot: str, asset_path: str, request: Request):
    return await _stream_hls_asset_common(match_id, slot, asset_path, request)


async def _stream_hls_asset_common(match_id: str, slot: str, asset_path: str, request: Request, *, team_id: str | None = None):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    if not asset_path or ".." in asset_path:
        raise HTTPException(400, "Invalid asset path")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    if team_id is not None and str(match.get("team_id") or "") != team_id:
        raise HTTPException(404, "HLS asset not found")

    base_dir = _media.existing_slot_hls_dir(VIDEOS_DIR, match_id, slot, team_id=match.get("team_id")).resolve()
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
    cache_header = "public, max-age=31536000, immutable"
    if target_path.suffix == ".m3u8":
        media_type = "application/vnd.apple.mpegurl"
        # Variant playlists revalidate too — see master.m3u8 above.
        cache_header = "public, max-age=60, must-revalidate"
    elif target_path.suffix == ".ts":
        media_type = "video/mp2t"
    elif target_path.suffix in (".m4s", ".mp4"):
        media_type = "video/mp4"

    return FileResponse(
        str(target_path),
        media_type=media_type,
        headers=_hls_response_headers(cache_header),
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
    if VIDEOS_DIR.resolve() not in logo_path.resolve().parents:
        raise HTTPException(400, "Invalid path")
    if not logo_path.is_file():
        raise HTTPException(404, "Logo file not found")

    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".svg": "image/svg+xml", ".webp": "image/webp"}
    mt = media_types.get(logo_path.suffix.lower(), "image/png")
    # Stored-XSS hardening for user-uploaded SVGs. Logos are write-gated
    # to admin/uploader, so this is defense-in-depth — a compromised
    # uploader account or a careless paste of a third-party SVG should
    # not be able to execute script in the replay app's origin. Caddy
    # serves these files directly when present (Caddyfile @match_logo);
    # this fallback path must keep the same headers so behavior is
    # identical regardless of who answers the request.
    headers = {"X-Content-Type-Options": "nosniff"}
    if logo_path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["Content-Disposition"] = f"inline; filename=\"{logo_path.name}\""
    return FileResponse(str(logo_path), media_type=mt, headers=headers)


@app.get("/api/matches/{match_id}/thumbnail")
async def serve_thumbnail(match_id: str):
    thumb_path = VIDEOS_DIR / match_id / "thumb.jpg"
    if VIDEOS_DIR.resolve() not in thumb_path.resolve().parents:
        raise HTTPException(400, "Invalid path")
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
