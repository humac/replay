"""Coach engagement + per-player development routes.

PR-BE 9/N — mechanical extraction from server.py.

Routes moved (2 handlers):
    GET /api/coach/engagement
    GET /api/coach/players/{player_id}/development

Both are coach/admin-only aggregation surfaces. Engagement uses
``services.engagement.build_coach_engagement_dashboard`` after scoping the
filters to the resolved team; per-player development uses the shared
``_build_player_development_profile`` helper which keeps the privacy ladder
single-sourced across coach and viewer surfaces (Phase 5a / Phase 5b — see
CLAUDE.md).

Privacy invariants preserved verbatim:
- The coach development surface keeps ``viewer_scoped=False`` so coaches
  see the raw note set including ``coach_private_note`` text, matching
  ``_filter_notes_for_user``'s short-circuit for privileged users.
- Filter validations (player / playlist / match / visibility) preserve the
  existing scope-checks before the aggregation runs, so an unknown
  cross-team id still 404s instead of leaking dashboard data.

Helpers that still live in ``server.py`` (``_resolve_coach_scope``,
``_scope_team_id``, ``_same_team``, ``_build_player_development_profile``)
are imported late inside each handler to break the
``server -> routers.coach_engagement -> server`` import cycle that would
otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import db as _db
from services import engagement as _engagement

router = APIRouter()


@router.get("/api/coach/engagement")
async def coach_engagement_dashboard(
    request: Request,
    player_id: str | None = None,
    playlist_id: int | None = None,
    match_id: str | None = None,
    visibility: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    from server import _resolve_coach_scope, _same_team, _scope_team_id
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


@router.get("/api/coach/players/{player_id}/development")
async def coach_player_development(player_id: str, request: Request):
    from server import _build_player_development_profile, _resolve_coach_scope, _scope_team_id
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    player = _db.get_player(player_id, team_id=team_id)
    if not player:
        raise HTTPException(404, "Player not found")
    return {"profile": _build_player_development_profile(player=player, user=user, viewer_scoped=False, team_id=team_id)}
