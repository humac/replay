"""Coach playlists routes.

PR-BE 6/N — mechanical extraction from server.py.

Routes moved (5 handlers):
    GET    /api/coach/playlists
    GET    /api/coach/playlists/{playlist_id}
    POST   /api/coach/playlists
    PATCH  /api/coach/playlists/{playlist_id}
    DELETE /api/coach/playlists/{playlist_id}

Coaching playlists are ordered note references that grant access to
their item moments inside the playlist session even when those notes
are private as standalone feedback. The GET endpoints hydrate items
via ``_playlists_with_items`` against the team-scoped note list so
the visibility ladder is applied uniformly. The mechanical move keeps
this behavior verbatim — both the team/season scope wiring and the
``_playlists_with_items(...)`` embedding are preserved.

Privacy invariants preserved verbatim:
- PR-AUTH's ``_tenancy.assert_can_delete_coach_object(...)`` gate on
  the playlist DELETE handler is preserved verbatim. The lookup
  remains "fetch playlist, check team, then check delete authority"
  so the privacy ladder cannot be reordered into a probing oracle.

Helpers that still live in ``server.py`` (``_resolve_coach_scope``,
``_scope_team_id``, ``_require_playlist_in_team``,
``_require_notes_in_team``, ``_require_players_in_team``,
``_same_team``, ``_log_activity``, and ``_playlists_with_items``)
are imported late inside each handler to break the
``server -> routers.coach_playlists -> server`` import cycle that
would otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import db as _db
import tenancy as _tenancy
from models import (
    CreateCoachingPlaylistRequest,
    UpdateCoachingPlaylistRequest,
)

router = APIRouter()


@router.get("/api/coach/playlists")
async def coach_list_playlists(request: Request):
    from server import _playlists_with_items, _resolve_coach_scope, _same_team, _scope_team_id
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlists = [p for p in _db.list_coaching_playlists() if _same_team(p, team_id)]
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    return {"playlists": _playlists_with_items(playlists, notes)}


@router.get("/api/coach/playlists/{playlist_id}")
async def coach_get_playlist(playlist_id: int, request: Request):
    from server import (
        _playlists_with_items,
        _require_playlist_in_team,
        _resolve_coach_scope,
        _same_team,
        _scope_team_id,
    )
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlist = _require_playlist_in_team(playlist_id, team_id)
    notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    return {"playlist": _playlists_with_items([playlist], notes)[0]}


@router.post("/api/coach/playlists")
async def coach_create_playlist(request: Request, body: CreateCoachingPlaylistRequest):
    from server import (
        _log_activity,
        _playlists_with_items,
        _require_notes_in_team,
        _require_players_in_team,
        _resolve_coach_scope,
        _same_team,
        _scope_team_id,
    )
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


@router.patch("/api/coach/playlists/{playlist_id}")
async def coach_update_playlist(playlist_id: int, request: Request, body: UpdateCoachingPlaylistRequest):
    from server import (
        _log_activity,
        _playlists_with_items,
        _require_notes_in_team,
        _require_players_in_team,
        _require_playlist_in_team,
        _resolve_coach_scope,
        _same_team,
        _scope_team_id,
    )
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


@router.delete("/api/coach/playlists/{playlist_id}")
async def coach_delete_playlist(playlist_id: int, request: Request):
    from server import (
        _log_activity,
        _require_playlist_in_team,
        _resolve_coach_scope,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    playlist = _require_playlist_in_team(playlist_id, team_id)
    _tenancy.assert_can_delete_coach_object(scope, "playlist", created_by_username=playlist.get("created_by"))
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
