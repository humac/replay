"""Admin operational + transcode-progress routes.

PR-BE 12b/N — mechanical extraction from server.py.

Routes moved (6 handlers):
    GET  /api/admin/diagnostics            (counts + activity feed + recent errors)
    GET  /api/admin/performance            (host/throughput/transcode snapshot, 5 s poll)
    POST /api/admin/performance/capture    (start high-frequency capture window)
    POST /api/admin/backfill-hls           (VOD admin recovery)
    POST /api/admin/export-database        (privileged SQLite backup download)
    GET  /api/transcode-progress           (snapshot of active transcode progress)

Per CLAUDE.md:
- Admin overview "Recent Activity" renders ``diagnostics.recent_activity``
  from persisted ``activity_events`` (see ``_db.get_activity_events``).
- The Performance Tuning panel polls ``/api/admin/performance`` every 5 s.
- backfill-hls is a VOD recovery path; export-database is a privileged
  data export gated on the ``admin`` role.
- ``GET /api/transcode-progress`` is a plain HTTP poll (NOT SSE/WebSocket)
  used by the uploads UI for active-job progress.

Late imports of server-side helpers (``_auth``, ``_db``, ``_media``,
``_settings``, ``_streams``, ``_uploads``, ``_load_settings``,
``_load_matches``, etc.) break the ``server -> routers.admin_ops ->
server`` import cycle that would otherwise occur at startup.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from models import StartCaptureRequest

router = APIRouter()


@router.get("/api/admin/diagnostics")
async def admin_diagnostics(request: Request):
    from server import (
        HLS_BACKFILL_LOCK,
        _auth,
        _cached_disk_usage_by_match,
        _db,
        _disk_stats_payload,
        _load_matches,
        _media,
        _ready_slots_missing_hls,
        _regen_hls_tasks,
        _uploads,
        current_max_upload_size_bytes,
        current_stale_upload_session_seconds,
        current_transcode_concurrency,
        current_upload_chunk_size_bytes,
    )

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


@router.get("/api/admin/performance")
async def admin_performance(request: Request):
    """Aggregated throughput + host + transcode signals for the Performance
    Tuning panel. Single round-trip per refresh; bundles cleanly for export."""
    from server import (
        _auth,
        _disk_pools,
        _host_signals,
        _load_settings,
        _media,
        _now_ms,
        _settings,
        _streams,
        current_transcode_concurrency,
    )

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


@router.post("/api/admin/performance/capture")
async def admin_performance_capture(request: Request, body: StartCaptureRequest | None = None):
    """Start a high-frequency capture window. The sweeper samples at 1 Hz
    instead of the regular interval for `body.seconds` seconds. Body is
    optional; default 60 s, validated to [5, 600] by the Pydantic model."""
    from server import _auth, _streams

    _auth.require_role(request, "admin")
    seconds = body.seconds if body is not None else 60.0
    return _streams.start_capture_window(seconds=seconds)


@router.post("/api/admin/backfill-hls")
async def admin_backfill_hls(request: Request):
    from server import (
        _auth,
        _backfill_hls_for_existing_videos,
        _log_activity,
        logger,
    )

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


@router.post("/api/admin/export-database")
async def admin_export_database(request: Request):
    """Download the SQLite database file as a backup."""
    from server import DB_FILE, _auth, _log_activity, logger

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


@router.get("/api/transcode-progress")
async def all_transcode_progress():
    """Return progress for every active transcode job in one request."""
    from server import _media

    return {
        key: {"active": True, **prog}
        for key, prog in _media.get_all_transcode_progress().items()
    }
