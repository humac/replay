"""Coach clips routes.

PR-BE 5/N — mechanical extraction from server.py.

Routes moved (7 handlers):
    GET    /api/coach/clips
    GET    /api/coach/clips/{clip_id}
    POST   /api/coach/clips
    PATCH  /api/coach/clips/{clip_id}
    DELETE /api/coach/clips/{clip_id}
    GET    /api/coach/clips/{clip_id}/thumbnail
    POST   /api/coach/clips/{clip_id}/thumbnail/regenerate

Coaching clips (Phase 4a — backend only)

Clips are first-class coaching objects: a saved [start, end] window
of a match slot, optionally seeded from a note via ``source_note_id``.
Visibility uses the same ladder as notes/playlists. The clip's
drawing is captured as a snapshot at create time so the clip stays
self-contained even if the source note is later edited or deleted.

**Privacy invariant**: when a clip is created from ``source_note_id``,
the create handler defaults a small set of fields from the source
note (match_id / slot / category / drawing) but NEVER copies any
coach-private text — neither ``coach_private_note`` nor anything else
from the note's body. The clip's own ``title`` / ``description`` come
from the request body or empty defaults; the source note's text
fields are never auto-copied. This keeps ``coach_private_note``
scoped to its single defense-in-depth surface
(``_strip_private_fields``) and prevents a clip from accidentally
re-publishing private text under a more permissive visibility.

Privacy invariants preserved verbatim:
- The clip thumbnail GET is the documented signed-in-user-readable
  surface (mirrors the note thumbnail pattern) and continues to call
  ``_can_view_coach_clip`` plus ``_thumb_path_within_videos_dir``
  containment so private-clip thumbnails cannot leak. Per-viewer
  ``Cache-Control: no-cache, must-revalidate`` + per-clip ``ETag``
  keep shared caches from replaying responses across users.
- PR-AUTH's ``_tenancy.assert_can_delete_coach_object(...)`` gate on
  the clip DELETE handler is preserved verbatim.

Helpers that still live in ``server.py`` (``_resolve_coach_scope``,
``_scope_team_id``, ``_require_match_in_team``, ``_require_players_in_team``,
``_require_note_in_team``, ``_require_clip_in_team``, ``_same_team``,
``_log_activity``, ``_spawn_task``, ``_slot_mp4_path``, ``VIDEOS_DIR``,
and ``_can_view_coach_clip`` re-exported from ``services.visibility``)
are imported late inside each handler to break the
``server -> routers.coach_clips -> server`` import cycle that would
otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

import auth as _auth
import db as _db
import log as _log
import media as _media
import tenancy as _tenancy
from services import thumbnails as _thumbs
from models import (
    CreateCoachingClipRequest,
    UpdateCoachingClipRequest,
)

router = APIRouter()


@router.get("/api/coach/clips")
async def coach_list_clips(request: Request, match_id: str | None = None):
    from server import _require_match_in_team, _resolve_coach_scope, _same_team, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    return {"clips": [c for c in _db.list_coaching_clips(match_id=match_id) if _same_team(c, team_id)]}


@router.get("/api/coach/clips/{clip_id}")
async def coach_get_clip(clip_id: int, request: Request):
    from server import _require_clip_in_team, _resolve_coach_scope, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    clip = _require_clip_in_team(clip_id, team_id)
    return {"clip": clip}


@router.post("/api/coach/clips")
async def coach_create_clip(request: Request, body: CreateCoachingClipRequest):
    from server import (
        VIDEOS_DIR,
        _log_activity,
        _require_match_in_team,
        _require_note_in_team,
        _require_players_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _slot_mp4_path,
        _spawn_task,
    )
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


@router.patch("/api/coach/clips/{clip_id}")
async def coach_update_clip(clip_id: int, request: Request, body: UpdateCoachingClipRequest):
    from server import (
        VIDEOS_DIR,
        _log_activity,
        _require_clip_in_team,
        _require_players_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _slot_mp4_path,
        _spawn_task,
    )
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


@router.delete("/api/coach/clips/{clip_id}")
async def coach_delete_clip(clip_id: int, request: Request):
    from server import (
        VIDEOS_DIR,
        _log_activity,
        _require_clip_in_team,
        _resolve_coach_scope,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    clip = _require_clip_in_team(clip_id, team_id)
    _tenancy.assert_can_delete_coach_object(scope, "clip", created_by_username=clip.get("created_by"))
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
@router.get("/api/coach/clips/{clip_id}/thumbnail")
async def coach_get_clip_thumbnail(clip_id: int, request: Request):
    """Serve the per-clip thumbnail JPEG.

    - Any signed-in user can call this; visibility is enforced per-clip
      via `_can_view_coach_clip`.
    - Returns 404 when the clip does not exist OR when the user cannot
      see it OR when the thumbnail file is missing OR when the
      computed path would escape `VIDEOS_DIR`. Same response shape
      across all four cases so a probing viewer cannot distinguish them.
    """
    from server import VIDEOS_DIR, _can_view_coach_clip, _same_team, _scope_team_id
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


@router.post("/api/coach/clips/{clip_id}/thumbnail/regenerate")
async def coach_regenerate_clip_thumbnail(clip_id: int, request: Request):
    """Coach/admin manual trigger for the clip thumbnail generator.
    Useful when the source video lands AFTER the clip was created or
    when a coach edits start_seconds. Synchronous on purpose — the
    caller wants to know whether the refresh succeeded so the UI can
    re-fetch the image."""
    from server import (
        VIDEOS_DIR,
        _require_clip_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _slot_mp4_path,
    )
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
