"""Coach roster + notes + player-links routes.

PR-BE 4/N — mechanical extraction from server.py.

Routes moved (15 handlers):
    GET    /api/coach/players
    GET    /api/coach/users
    POST   /api/coach/players/import/preview
    POST   /api/coach/players/import/commit
    POST   /api/coach/players
    PATCH  /api/coach/players/{player_id}
    DELETE /api/coach/players/{player_id}
    POST   /api/coach/player-links
    DELETE /api/coach/player-links/{link_id}
    GET    /api/coach/notes
    POST   /api/coach/notes
    PATCH  /api/coach/notes/{note_id}
    DELETE /api/coach/notes/{note_id}
    GET    /api/coach/notes/{note_id}/thumbnail
    POST   /api/coach/notes/{note_id}/thumbnail/regenerate

Privacy invariants preserved verbatim:
- The thumbnail GET is the documented `/api/coach/*` namespace exception
  (any signed-in user) and continues to call ``_can_view_coach_note`` plus
  ``_thumb_path_within_videos_dir`` containment so private-note thumbnails
  cannot leak.
- ``coach_private_note`` scrubbing happens in ``services.visibility`` /
  ``_filter_notes_for_user`` upstream of every viewer-facing surface.
- PR-AUTH's ``_tenancy.assert_can_delete_coach_object(...)`` gate on the
  notes DELETE handler is preserved verbatim.

Helpers that still live in ``server.py`` (``_resolve_coach_scope``,
``_scope_team_id``, ``_require_match_in_team``, ``_require_player_in_team``,
``_require_players_in_team``, ``_require_note_in_team``, ``_same_team``,
``_can_view_coach_note``, ``_coach_note_activity_label``, ``_log_activity``,
``_spawn_task``, ``_slot_mp4_path``, ``VIDEOS_DIR``) are imported late inside
each handler to break the ``server -> routers.coach_notes -> server`` import
cycle that would otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

import auth as _auth
import db as _db
import log as _log
import media as _media
import tenancy as _tenancy
from services import roster_import as _roster_import
from services import teams as _teams
from services import thumbnails as _thumbs
from models import (
    CreateCoachingNoteRequest,
    CreatePlayerRequest,
    CreatePlayerUserLinkRequest,
    RosterImportRequest,
    UpdateCoachingNoteRequest,
    UpdatePlayerRequest,
)

router = APIRouter()


@router.get("/api/coach/players")
async def coach_list_players(request: Request):
    from server import _resolve_coach_scope, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    return {"players": _db.list_players(include_inactive=True, team_id=team_id)}


@router.get("/api/coach/users")
async def coach_list_linkable_users(request: Request):
    from server import _resolve_coach_scope, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    return {
        "users": [
            {k: v for k, v in u.items() if k != "password_hash"}
            for u in _db.list_users(team_id=team_id)
        ]
    }


def _resolve_roster_import_scope(request: Request) -> tuple[dict, _tenancy.Scope]:
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("team_admin",),
        allow_global_admin_override=False,
    )
    return user, scope


def _call_roster_import(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except _roster_import.RosterImportError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except _teams.TeamServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/api/coach/players/import/preview")
async def coach_preview_roster_import(request: Request, body: RosterImportRequest):
    from server import _scope_team_id
    user, scope = _resolve_roster_import_scope(request)
    team_id = _scope_team_id(scope)
    season_id = scope.season["id"] if scope.season else None
    return _call_roster_import(
        _roster_import.preview_roster_import,
        csv_text=body.csv_text,
        team_id=team_id,
        season_id=season_id,
        actor=user,
    )


@router.post("/api/coach/players/import/commit")
async def coach_commit_roster_import(request: Request, body: RosterImportRequest):
    from server import _log_activity, _scope_team_id
    user, scope = _resolve_roster_import_scope(request)
    team_id = _scope_team_id(scope)
    season_id = scope.season["id"] if scope.season else None
    result = _call_roster_import(
        _roster_import.commit_roster_import,
        csv_text=body.csv_text,
        team_id=team_id,
        season_id=season_id,
        actor=user,
    )
    if result.get("ok"):
        _log_activity(
            "coach.roster_imported",
            severity="info",
            message="Roster CSV import committed",
            actor=user["username"],
            metadata={"team_id": team_id, "summary": result.get("summary", {})},
        )
    return result


@router.post("/api/coach/players")
async def coach_create_player(request: Request, body: CreatePlayerRequest):
    from server import _log_activity, _resolve_coach_scope, _scope_team_id
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


@router.patch("/api/coach/players/{player_id}")
async def coach_update_player(player_id: str, request: Request, body: UpdatePlayerRequest):
    from server import _log_activity, _require_player_in_team, _resolve_coach_scope, _scope_team_id
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


@router.delete("/api/coach/players/{player_id}")
async def coach_delete_player(player_id: str, request: Request):
    from server import _log_activity, _require_player_in_team, _resolve_coach_scope, _scope_team_id
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


@router.post("/api/coach/player-links")
async def coach_link_player_user(request: Request, body: CreatePlayerUserLinkRequest):
    from server import _log_activity, _require_player_in_team, _resolve_coach_scope, _scope_team_id
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


@router.delete("/api/coach/player-links/{link_id}")
async def coach_delete_player_user_link(link_id: int, request: Request):
    from server import _log_activity, _resolve_coach_scope, _scope_team_id
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


@router.get("/api/coach/notes")
async def coach_list_notes(request: Request, match_id: str | None = None):
    from server import _require_match_in_team, _resolve_coach_scope, _same_team, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    return {"notes": [n for n in _db.list_coaching_notes(match_id=match_id) if _same_team(n, team_id)]}


@router.post("/api/coach/notes")
async def coach_create_note(request: Request, body: CreateCoachingNoteRequest):
    from server import (
        VIDEOS_DIR,
        _coach_note_activity_label,
        _log_activity,
        _require_match_in_team,
        _require_players_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _slot_mp4_path,
        _spawn_task,
    )
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


@router.patch("/api/coach/notes/{note_id}")
async def coach_update_note(note_id: int, request: Request, body: UpdateCoachingNoteRequest):
    from server import (
        VIDEOS_DIR,
        _coach_note_activity_label,
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


@router.delete("/api/coach/notes/{note_id}")
async def coach_delete_note(note_id: int, request: Request):
    from server import (
        VIDEOS_DIR,
        _coach_note_activity_label,
        _log_activity,
        _require_note_in_team,
        _resolve_coach_scope,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    note = _require_note_in_team(note_id, team_id)
    _tenancy.assert_can_delete_coach_object(scope, "note", created_by_user_id=note.get("created_by"))
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
@router.get("/api/coach/notes/{note_id}/thumbnail")
async def coach_get_note_thumbnail(note_id: int, request: Request):
    """Serve the per-note thumbnail JPEG.

    - Any signed-in user can call this; visibility is enforced per-note
      via `_can_view_coach_note`.
    - Returns 404 when the note does not exist OR when the user cannot
      see it OR when the thumbnail file is missing OR when the
      computed path would escape `VIDEOS_DIR`. The same 404 covers all
      four cases so a probing viewer cannot distinguish them.
    """
    from server import VIDEOS_DIR, _can_view_coach_note, _same_team, _scope_team_id
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


@router.post("/api/coach/notes/{note_id}/thumbnail/regenerate")
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
    from server import (
        VIDEOS_DIR,
        _require_note_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _slot_mp4_path,
    )
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
