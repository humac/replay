"""Matches domain routes: CRUD, admin recovery, video streaming/HLS, logos, thumbnails.

PR-BE 1/N — mechanical extraction from server.py. Handler bodies and decorator
paths are verbatim copies. Late imports from `server` break the circular import
that would otherwise occur because server.py imports this module to register
the router.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import auth as _auth
import db as _db
import media as _media
import streams as _streams
from models import CreateMatchRequest, UpdateMatchRequest

router = APIRouter()


@router.get("/api/admin/matches/{match_id}/errors")
async def admin_match_errors(match_id: str, request: Request):
    _auth.require_role(request, "admin")
    errors = _db.get_video_errors(match_id=match_id, limit=50)
    return {"errors": errors}


@router.post("/api/admin/matches/{match_id}/slots/{slot}/retry")
async def admin_retry_transcode(match_id: str, slot: str, request: Request):
    """Re-transcode a slot from the existing MP4 or raw upload file.

    Default mode: only `error` slots can be retried. Pass `?force=true` to
    retranscode a `ready` slot — useful for picking up new encoder settings
    (QSV, 1440p tier, audio bitrate) on already-completed matches without a
    fresh upload. `transcoding` slots are always rejected.
    """
    from server import (
        MATCHES_LOCK,
        _find_slot_raw_path,
        _get_video_status,
        _log_activity,
        _set_video_status,
        _slot_mp4_path,
        _slot_mp4_write_path,
        _slot_raw_path,
        _spawn_transcode,
        logger,
    )
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


@router.post("/api/admin/matches/{match_id}/slots/{slot}/regenerate-hls")
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
    from server import (
        _log_activity,
        _regen_hls_tasks,
        _run_regen_hls_task,
        _slot_mp4_path,
        _spawn_task,
        logger,
    )
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


@router.post("/api/admin/matches/{match_id}/regenerate-thumbnail")
async def admin_regenerate_thumbnail(match_id: str, request: Request):
    """Regenerate the match thumbnail from a chosen (or auto-picked) ready slot.

    Optional `?slot=<full|first_half|second_half>` query param picks which
    video to extract from. Without it, falls back to the same priority order
    as the startup backfill task: full > first_half > second_half. This
    overwrites the existing thumb.jpg on disk.
    """
    from server import (
        VIDEOS_DIR,
        _get_video_status,
        _log_activity,
        _slot_mp4_path,
        logger,
    )
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


@router.get("/api/admin/matches/{match_id}/verify")
async def admin_verify_assets(match_id: str, request: Request):
    """Check asset integrity for all slots in a match."""
    from server import ORIGINALS_DIR, VIDEOS_DIR, _get_video_status
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


@router.get("/api/matches")
async def list_matches(
    request: Request,
    q: str | None = None,
    page: int | None = None,
    limit: int | None = None,
):
    from server import MATCHES_LOCK, _enrich_match
    if q is not None or page is not None or limit is not None:
        clamped_limit = max(1, min(limit or 50, 200))
        matches, total = _db.search_matches(q=q, page=page or 1, limit=clamped_limit)
        return {"matches": [_enrich_match(m) for m in matches], "total": total, "page": page or 1, "limit": clamped_limit}
    # No query params: return the 500 most-recent matches to bound payload size.
    async with MATCHES_LOCK:
        matches = _db.load_matches_unlocked(limit=500)
    return [_enrich_match(m) for m in matches]


@router.post("/api/matches")
async def create_match(request: Request, body: CreateMatchRequest):
    from server import MATCHES_LOCK, VIDEOS_DIR, _log_activity, _now_ms
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


@router.put("/api/matches/{match_id}")
async def update_match(match_id: str, request: Request, body: UpdateMatchRequest):
    from server import MATCHES_LOCK, _log_activity, _now_ms
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


@router.delete("/api/matches/{match_id}")
async def delete_match(match_id: str, request: Request):
    import shutil
    from server import (
        MATCHES_LOCK,
        ORIGINALS_DIR,
        VIDEOS_DIR,
        _log_activity,
        _transcode_tasks,
        logger,
    )
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


@router.get("/api/matches/{match_id}/video/{slot}")
async def stream_video(match_id: str, slot: str, request: Request):
    from server import _get_video_status, _range_file_response, _slot_mp4_path
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


@router.get("/api/matches/{match_id}/transcode-progress/{slot}")
async def transcode_progress(match_id: str, slot: str):
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    progress = _media.get_transcode_progress(match_id, slot)
    if not progress:
        return {"active": False}
    return {"active": True, **progress}


@router.post("/api/matches/{match_id}/heartbeat")
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


@router.get("/api/matches/{match_id}/download/{slot}")
async def download_video(match_id: str, slot: str, request: Request):
    from server import (
        _get_video_status,
        _load_settings,
        _range_file_response,
        _slot_mp4_path,
    )
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

def _hls_response_headers(cache_control: str) -> dict[str, str]:
    return {
        "Cache-Control": cache_control,
        "Access-Control-Allow-Origin": "*",
    }


@router.get("/api/matches/{match_id}/hls/{slot}/master.m3u8")
async def stream_hls_master(match_id: str, slot: str, request: Request):
    return await _stream_hls_master_common(match_id, slot, request)


async def _stream_hls_master_common(match_id: str, slot: str, request: Request):
    from server import VIDEOS_DIR, _get_video_status
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

    master_path = _media.existing_slot_hls_master_path(VIDEOS_DIR, match_id, slot)
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


@router.get("/api/matches/{match_id}/hls/{slot}/{asset_path:path}")
async def stream_hls_asset(match_id: str, slot: str, asset_path: str, request: Request):
    return await _stream_hls_asset_common(match_id, slot, asset_path, request)


async def _stream_hls_asset_common(match_id: str, slot: str, asset_path: str, request: Request):
    from server import VIDEOS_DIR
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "Invalid slot")
    if not asset_path or ".." in asset_path:
        raise HTTPException(400, "Invalid asset path")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    base_dir = _media.existing_slot_hls_dir(VIDEOS_DIR, match_id, slot).resolve()
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


# ---------------------------------------------------------------------------
# Logo Upload & Serving
# ---------------------------------------------------------------------------

@router.post("/api/matches/{match_id}/upload-logo")
async def upload_logo(match_id: str, file: UploadFile, request: Request):
    """Upload a team logo.  Query param: team=home|away"""
    from server import MATCHES_LOCK, VIDEOS_DIR, _save_upload_file
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


@router.get("/api/matches/{match_id}/logo/{team}")
async def serve_logo(match_id: str, team: str):
    from server import VIDEOS_DIR
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


@router.get("/api/matches/{match_id}/thumbnail")
async def serve_thumbnail(match_id: str):
    from server import VIDEOS_DIR
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
