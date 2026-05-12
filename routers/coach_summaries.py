"""Coach match summaries routes.

PR-BE 8/N — mechanical extraction from server.py.

Routes moved (5 handlers):
    GET    /api/coach/match-summaries
    GET    /api/coach/match-summaries/{summary_id}
    POST   /api/coach/match-summaries
    PATCH  /api/coach/match-summaries/{summary_id}
    DELETE /api/coach/match-summaries/{summary_id}

Match coaching summaries (Phase 8) are match-level coach narratives with
linked note / clip / playlist evidence. PATCH validation must evaluate the
merged existing + incoming state so an update cannot clear every text
field — that merged-state check (``_validate_match_summary_has_text`` on
``merged_payload``) is preserved verbatim. Linked-evidence resolution
still flows through ``_validate_match_summary_sources`` /
``_sanitize_match_summary_sources`` server-side so viewer payloads can't
hydrate cross-team or out-of-scope sources.

Privacy invariants preserved verbatim:
- PR-AUTH's ``_tenancy.assert_can_delete_coach_object(...)`` gate on the
  match-summary DELETE handler is preserved verbatim. The lookup remains
  "fetch summary, scope to team, then check delete authority" so the
  privacy ladder cannot be reordered into a probing oracle.

Helpers that still live in ``server.py``
(``_resolve_coach_scope``, ``_scope_team_id``, ``_same_team``,
``_require_match_in_team``, ``_require_summary_in_team``,
``_validate_match_summary_has_text``, ``_validate_match_summary_sources``,
``_sanitize_match_summary_sources``, ``_log_activity``) are imported late
inside each handler to break the
``server -> routers.coach_summaries -> server`` import cycle that would
otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import db as _db
import tenancy as _tenancy
from models import (
    CreateMatchSummaryRequest,
    UpdateMatchSummaryRequest,
)

router = APIRouter()


@router.get("/api/coach/match-summaries")
async def coach_list_match_summaries(request: Request, match_id: str | None = None):
    from server import (
        _require_match_in_team,
        _resolve_coach_scope,
        _same_team,
        _sanitize_match_summary_sources,
        _scope_team_id,
    )
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    if match_id:
        _require_match_in_team(match_id, team_id)
    summaries = [s for s in _db.list_coaching_match_summaries(match_id=match_id) if _same_team(s, team_id)]
    return {"summaries": [_sanitize_match_summary_sources(s, team_id) for s in summaries]}


@router.get("/api/coach/match-summaries/{summary_id}")
async def coach_get_match_summary(summary_id: int, request: Request):
    from server import (
        _require_summary_in_team,
        _resolve_coach_scope,
        _sanitize_match_summary_sources,
        _scope_team_id,
    )
    _user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    summary = _sanitize_match_summary_sources(_require_summary_in_team(summary_id, team_id), team_id)
    return {"summary": summary}


@router.post("/api/coach/match-summaries")
async def coach_create_match_summary(request: Request, body: CreateMatchSummaryRequest):
    from server import (
        _log_activity,
        _require_match_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _validate_match_summary_sources,
    )
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


@router.patch("/api/coach/match-summaries/{summary_id}")
async def coach_update_match_summary(summary_id: int, request: Request, body: UpdateMatchSummaryRequest):
    from server import (
        _log_activity,
        _require_summary_in_team,
        _resolve_coach_scope,
        _scope_team_id,
        _validate_match_summary_has_text,
        _validate_match_summary_sources,
    )
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


@router.delete("/api/coach/match-summaries/{summary_id}")
async def coach_delete_match_summary(summary_id: int, request: Request):
    from server import (
        _log_activity,
        _require_summary_in_team,
        _resolve_coach_scope,
        _scope_team_id,
    )
    user, scope = _resolve_coach_scope(request)
    team_id = _scope_team_id(scope)
    summary = _require_summary_in_team(summary_id, team_id)
    _tenancy.assert_can_delete_coach_object(scope, "match_summary", created_by_user_id=summary.get("created_by"))
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
