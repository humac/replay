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
import tenancy as _tenancy
import uploads as _uploads
from routers.admin import router as admin_router
from routers.admin_teams import router as admin_teams_router
from routers.auth import router as auth_router
from routers.coach_ai import router as coach_ai_router
from routers.coach_clips import router as coach_clips_router
from routers.coach_goals import router as coach_goals_router
from routers.coach_notes import router as coach_notes_router
from routers.coach_playlists import router as coach_playlists_router
from routers.coach_summaries import router as coach_summaries_router
from routers.live import router as live_router
from routers.matches import router as matches_router
from routers.team_members import router as team_members_router
from routers.team_settings import router as team_settings_router
from routers.uploads import router as uploads_router
from services import activity as _activity
from services import engagement as _engagement
from services import jobs as _jobs
from services import roster_import as _roster_import
from services import teams as _teams
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
    CreateUploadSessionRequest, EnqueueJobRequest, LiveAuthRequest,
    MarkCoachingReviewRequest, RosterImportRequest, StartCaptureRequest, UnblockStreamRequest,
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
    team_id = _team_id_for_match(match_id)
    if not team_id:
        raise RuntimeError(f"Cannot enqueue transcode job without team scope for match {match_id}")
    job_id = _jobs.enqueue(
        "transcode",
        {"match_id": match_id, "slot": slot, "src": str(src), "dest": str(dest)},
        team_id=team_id,
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
    match = _db.get_match_by_id(match_id)
    if not match or str(match.get("team_id")) != str(job["team_id"]):
        _jobs.fail(job_id, worker_id, "transcode resource no longer belongs to job team")
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


app = FastAPI(title="Replay", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_teams_router)
app.include_router(team_members_router)
app.include_router(team_settings_router)
app.include_router(coach_ai_router)
app.include_router(coach_clips_router)
app.include_router(coach_goals_router)
app.include_router(coach_notes_router)
app.include_router(coach_playlists_router)
app.include_router(coach_summaries_router)
app.include_router(live_router)
app.include_router(matches_router)
app.include_router(uploads_router)


def _serialize_job_for_api(job: dict) -> dict:
    payload = job.get("payload") or {}
    if job.get("kind") == "transcode":
        payload = {key: payload.get(key) for key in ("match_id", "slot") if payload.get(key) is not None}
    return {
        "id": job["id"],
        "kind": job["kind"],
        "team_id": job["team_id"],
        "status": job["status"],
        "attempts": job["attempts"],
        "max_attempts": job["max_attempts"],
        "payload": payload,
        "payload_version": job.get("payload_version", 1),
        "idempotency_key": job.get("idempotency_key"),
        "scheduled_at": job.get("scheduled_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "result": job.get("result"),
        "error_text": job.get("error_text"),
    }


JOB_KIND_CAPABILITIES = {
    "thumbnail": "match:write",
    "transcode": "match:write",
}


def _job_write_capability(kind: str) -> str:
    if kind == "ai_draft":
        raise HTTPException(
            status_code=422,
            detail="ai_draft jobs cannot be enqueued via /api/jobs; use POST /api/coach/ai/draft",
        )
    try:
        return JOB_KIND_CAPABILITIES[kind]
    except KeyError as exc:
        raise HTTPException(422, "Unsupported job kind") from exc


def _normalize_job_payload(kind: str, payload: dict, team_id: str) -> dict:
    if kind == "ai_draft":
        # Defense in depth: even if a future change re-adds ai_draft to the
        # capability map, never persist a user-supplied ai_draft payload through
        # this route — raw prompts / private source text would land in
        # background_jobs.payload_json. POST /api/coach/ai/draft is the only
        # AI draft API.
        raise HTTPException(
            status_code=422,
            detail="ai_draft jobs cannot be enqueued via /api/jobs; use POST /api/coach/ai/draft",
        )
    payload_json = json.dumps(payload, separators=(",", ":"))
    if len(payload_json.encode("utf-8")) > 10_000:
        raise HTTPException(422, "Job payload is too large")
    if payload.get("team_id") is not None and str(payload.get("team_id")) != team_id:
        raise HTTPException(403, "Job payload team does not match resolved team")
    allowed_keys = {"match_id", "slot", "team_id"} if kind == "transcode" else {"match_id", "slot", "team_id"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise HTTPException(422, "Unsupported job payload fields")
    match_id = str(payload.get("match_id") or "").strip()
    if not match_id:
        raise HTTPException(422, "match_id is required")
    match = _db.get_match_by_id(match_id)
    if not match or str(match.get("team_id")) != team_id:
        raise HTTPException(404, "Match not found")
    normalized = {"match_id": match_id}
    if payload.get("slot") is not None:
        normalized["slot"] = str(payload.get("slot")).strip()
    return normalized


def _normalize_scheduled_at(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "scheduled_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _require_job_access(request: Request, user: dict, *, team_id: str, kind: str):
    return _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role=_job_write_capability(kind),
        allow_global_admin_override=False,
    )


@app.post("/api/jobs")
async def enqueue_job(request: Request, body: EnqueueJobRequest):
    user = _auth.require_auth(request)
    kind = body.kind
    payload = body.payload
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=body.team_id,
        require_role=_job_write_capability(kind),
        allow_global_admin_override=False,
    )
    team_id = str(scope.team["id"])
    payload = _normalize_job_payload(kind, payload, team_id)
    job_id = _jobs.enqueue(
        kind,
        payload,
        team_id=team_id,
        idempotency_key=body.idempotency_key,
        scheduled_at=_normalize_scheduled_at(body.scheduled_at),
        max_attempts=body.max_attempts,
        payload_version=body.payload_version,
    )
    job = _jobs.get(job_id, team_id=team_id)
    return _serialize_job_for_api(job)


@app.get("/api/jobs")
async def list_jobs(request: Request, team_id: str, status: str | None = None, kind: str | None = None, limit: int = 50):
    user = _auth.require_auth(request)
    required_capability = _job_write_capability(kind) if kind else "match:write"
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role=required_capability,
        allow_global_admin_override=False,
    )
    rows = _jobs.list_for_team(str(scope.team["id"]), status=status, kind=kind, limit=limit)
    return [_serialize_job_for_api(row) for row in rows]


@app.post("/api/jobs/lease")
async def reject_worker_lease_route():
    raise HTTPException(404, "Not found")


@app.post("/api/jobs/{job_id}/heartbeat")
@app.post("/api/jobs/{job_id}/complete")
@app.post("/api/jobs/{job_id}/fail")
async def reject_worker_lifecycle_route(job_id: int):
    raise HTTPException(404, "Not found")


@app.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: int, team_id: str):
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role="team:read",
        allow_global_admin_override=False,
    )
    job = _jobs.get(job_id, team_id=str(scope.team["id"]))
    if job is None:
        raise HTTPException(404, "Job not found")
    _require_job_access(request, user, team_id=str(scope.team["id"]), kind=job["kind"])
    return _serialize_job_for_api(job)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int, team_id: str):
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role="team:read",
        allow_global_admin_override=False,
    )
    resolved_team_id = str(scope.team["id"])
    job = _jobs.get(job_id, team_id=resolved_team_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    _require_job_access(request, user, team_id=resolved_team_id, kind=job["kind"])
    if job["status"] != "pending":
        raise HTTPException(409, "Only pending jobs can be cancelled")
    if _jobs.cancel(job_id, team_id=resolved_team_id) != 1:
        raise HTTPException(409, "Only pending jobs can be cancelled")
    refreshed = _jobs.get(job_id, team_id=resolved_team_id)
    return _serialize_job_for_api(refreshed)


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
# Coaching workspace
# ---------------------------------------------------------------------------

def _require_coach(request: Request) -> dict:
    """Authenticate a coach-route caller.

    Phase PR-AUTH: legacy ``users.role`` is no longer a precondition for
    reaching ``/api/coach/*``. Membership-based gating happens in
    ``_resolve_coach_scope`` via ``_tenancy.resolve_scope``, which
    requires a team-scoped ``coach``/``team_admin`` membership row (or
    explicit global-admin override). A signed-in user without a relevant
    membership still gets 403, but a viewer-role user WITH a coach
    membership now passes — fixing the regression where invite-only
    coaches could not access their own Coach workspace.
    """
    return _auth.require_auth(request)


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


# ---------------------------------------------------------------------------
# Coach match summary routes have moved to ``routers/coach_summaries.py``
# (PR-BE 8/N).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Coaching clips routes have moved to ``routers/coach_clips.py``
# (PR-BE 5/N).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Coach player goals routes have moved to ``routers/coach_goals.py``
# (PR-BE 7/N).
# ---------------------------------------------------------------------------


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

# ---------------------------------------------------------------------------
# Video Streaming (upload routes moved to routers/uploads.py)
# ---------------------------------------------------------------------------


@app.get("/api/transcode-progress")
async def all_transcode_progress():
    """Return progress for every active transcode job in one request."""
    return {
        key: {"active": True, **prog}
        for key, prog in _media.get_all_transcode_progress().items()
    }


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
    port = int(os.environ.get("REPLAY_PORT", "8090"))
    logger.info("Replay server starting on port %d (data: %s)", port, DATA_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=600)
