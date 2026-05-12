"""Coach player goals routes.

PR-BE 7/N — mechanical extraction from server.py.

Routes moved (4 handlers):
    GET    /api/coach/goals
    POST   /api/coach/goals
    PATCH  /api/coach/goals/{goal_id}
    DELETE /api/coach/goals/{goal_id}

Player goals (Phase 7) are first-class action items with visibility
(``player`` / ``coach``), priority, optional ``target_date`` /
``success_criteria``, coach-only ``coach_private_note``, status history,
and viewer reflections. The mechanical move preserves the coach-only
``coach_private_note`` scrubbing (which lives in
``services.visibility.goals_with_visible_sources`` and applies to viewer
payloads only — the coach surface here intentionally sees the full
goal) and the viewer-filtered / scrubbed source hydration verbatim.

Privacy invariants preserved verbatim:
- PR-AUTH's ``_tenancy.assert_can_delete_coach_object(...)`` gate on
  the goal DELETE handler is preserved verbatim. The lookup remains
  "fetch goal, check team, then check delete authority" so the
  privacy ladder cannot be reordered into a probing oracle.

Helpers that still live in ``server.py``
(``_resolve_coach_scope``, ``_scope_team_id``, ``_same_team``,
``_require_player_in_team``, ``_require_scoped_item``,
``_validate_goal_source_links``, ``_log_activity``,
``_goals_with_visible_sources``, ``_goal_with_visible_sources``)
are imported late inside each handler to break the
``server -> routers.coach_goals -> server`` import cycle that would
otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import db as _db
import tenancy as _tenancy
from models import (
    CreatePlayerGoalRequest,
    UpdatePlayerGoalRequest,
)

router = APIRouter()


@router.get("/api/coach/goals")
async def coach_list_goals(request: Request, player_id: str | None = None):
    from server import (
        _goals_with_visible_sources,
        _require_player_in_team,
        _resolve_coach_scope,
        _same_team,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if player_id:
        _require_player_in_team(player_id, team_id)
    goals = [g for g in _db.list_player_goals(player_id=player_id) if _same_team(g, team_id)]
    return {"goals": _goals_with_visible_sources(goals, user, team_id=team_id)}


@router.post("/api/coach/goals")
async def coach_create_goal(request: Request, body: CreatePlayerGoalRequest):
    from server import (
        _goal_with_visible_sources,
        _log_activity,
        _require_player_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _validate_goal_source_links,
    )
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


@router.patch("/api/coach/goals/{goal_id}")
async def coach_update_goal(goal_id: int, request: Request, body: UpdatePlayerGoalRequest):
    from server import (
        _goal_with_visible_sources,
        _log_activity,
        _require_player_in_team,
        _require_scoped_item,
        _resolve_coach_scope,
        _scope_team_id,
        _validate_goal_source_links,
    )
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


@router.delete("/api/coach/goals/{goal_id}")
async def coach_delete_goal(goal_id: int, request: Request):
    from server import (
        _log_activity,
        _require_scoped_item,
        _resolve_coach_scope,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    existing = _require_scoped_item(_db.get_player_goal(goal_id), team_id, "Goal not found")
    _tenancy.assert_can_delete_coach_object(scope, "goal", created_by_user_id=existing.get("created_by"))
    if not _db.delete_player_goal(goal_id):
        raise HTTPException(404, "Goal not found")
    _log_activity("coach.goal_deleted", severity="warning", message=f"Player goal deleted: {existing.get('title', goal_id) if existing else goal_id}", actor=user["username"], metadata={"goal_id": goal_id})
    return {"ok": True}
