"""Viewer ``/api/my-feedback`` routes.

PR-BE 10/N — mechanical extraction from server.py.

Routes moved (5 handlers):
    GET  /api/my-feedback
    GET  /api/my-feedback/goals
    POST /api/my-feedback/goals/{goal_id}/reflection
    GET  /api/my-feedback/players/{player_id}/development
    POST /api/my-feedback/review

These are the viewer-side (player / family-account / signed-in user)
read endpoints. Every payload that crosses the privacy boundary flows
through the shared visibility helpers:

- ``_filter_notes_for_user`` + ``_strip_private_fields`` scrub
  ``coach_private_note`` on the top-level notes list AND on the note
  bodies embedded under ``playlists[].items[]`` (defense in depth — see
  PR #73 and the playlist-leak test in tests/test_coaching.py).
- ``_filter_clips_for_user`` / ``_filter_playlists_for_user`` /
  ``_filter_goals_for_user`` / ``_filter_match_summaries_for_user``
  apply the same visibility ladder for the rest of the bundle.
- The per-player development viewer endpoint returns **404** for both
  unknown players AND viewers unrelated to the player so a viewer
  cannot probe whether a roster id exists.
- ``mark_my_feedback_review`` re-validates that the target note /
  playlist is visible to the signed-in user before recording a review,
  so a guessed id cannot be turned into a reflection write.

Helpers that still live in ``server.py`` (``_resolve_feedback_scope``,
``_scope_team_id``, ``_same_team``, ``_strip_private_fields``,
``_filter_notes_for_user``, ``_filter_clips_for_user``,
``_filter_playlists_for_user``, ``_filter_goals_for_user``,
``_filter_match_summaries_for_user``, ``_playlists_with_items``,
``_goals_with_visible_sources``, ``_sanitize_match_summary_sources``,
``_build_player_development_profile``) are imported late inside each
handler to break the ``server -> routers.feedback -> server`` import
cycle that would otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import db as _db
from models import (
    CreatePlayerGoalReflectionRequest,
    MarkCoachingReviewRequest,
)

router = APIRouter()


@router.get("/api/my-feedback/goals")
async def my_feedback_goals(request: Request):
    from server import (
        _filter_goals_for_user,
        _goals_with_visible_sources,
        _resolve_feedback_scope,
        _same_team,
        _scope_team_id,
    )
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    goals = _filter_goals_for_user([g for g in _db.list_player_goals() if _same_team(g, team_id)], user, team_id=team_id)
    return {"goals": _goals_with_visible_sources(goals, user, team_id=team_id)}


@router.post("/api/my-feedback/goals/{goal_id}/reflection")
async def my_feedback_goal_reflection(goal_id: int, request: Request, body: CreatePlayerGoalReflectionRequest):
    from server import (
        _filter_goals_for_user,
        _resolve_feedback_scope,
        _same_team,
        _scope_team_id,
    )
    user, scope = _resolve_feedback_scope(request)
    team_id = _scope_team_id(scope)
    goal = _db.get_player_goal(goal_id)
    if not goal or not _same_team(goal, team_id) or goal not in _filter_goals_for_user([goal], user, team_id=team_id):
        raise HTTPException(404, "Goal not found")
    reflection = _db.add_player_goal_reflection(goal_id, user.get("user_id"), body.reflection)
    return {"ok": True, "reflection": {k: v for k, v in reflection.items() if k != "user_id"}}


@router.get("/api/my-feedback")
async def my_feedback(request: Request):
    from server import (
        _filter_clips_for_user,
        _filter_goals_for_user,
        _filter_match_summaries_for_user,
        _filter_notes_for_user,
        _filter_playlists_for_user,
        _goals_with_visible_sources,
        _playlists_with_items,
        _resolve_feedback_scope,
        _same_team,
        _sanitize_match_summary_sources,
        _scope_team_id,
        _strip_private_fields,
    )
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
    is_privileged = _auth.is_privileged_coach(user)
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


@router.get("/api/my-feedback/players/{player_id}/development")
async def my_feedback_player_development(player_id: str, request: Request):
    from server import (
        _build_player_development_profile,
        _resolve_feedback_scope,
        _scope_team_id,
    )
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


@router.post("/api/my-feedback/review")
async def mark_my_feedback_review(request: Request, body: MarkCoachingReviewRequest):
    from server import (
        _filter_notes_for_user,
        _filter_playlists_for_user,
        _resolve_feedback_scope,
        _same_team,
        _scope_team_id,
    )
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
