"""Team-scoped membership and invite routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

import auth as _auth
from models import AcceptTeamInviteRequest, TeamInviteRequest, TeamMembershipRequest
from services import team_members as _team_members
from services import teams as _teams

router = APIRouter(prefix="/api/team", tags=["team-members"])


def _call_service(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except _teams.TeamServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/memberships")
async def list_team_memberships(request: Request, team_id: str = Query(..., min_length=1)):
    actor = _auth.require_auth(request)
    return _call_service(_team_members.list_memberships, team_id, actor)


@router.post("/memberships")
async def grant_team_membership(request: Request, payload: TeamMembershipRequest):
    actor = _auth.require_auth(request)
    return _call_service(
        _team_members.grant_membership,
        payload.team_id,
        payload.user_id,
        payload.role,
        actor,
    )


@router.delete("/memberships/{membership_id}")
async def revoke_team_membership(request: Request, membership_id: int, team_id: str = Query(..., min_length=1)):
    actor = _auth.require_auth(request)
    return _call_service(_team_members.revoke_membership, team_id, membership_id, actor)


@router.get("/invites")
async def list_team_invites(request: Request, team_id: str = Query(..., min_length=1)):
    actor = _auth.require_auth(request)
    return _call_service(_team_members.list_invites, team_id, actor)


@router.post("/invites")
async def create_team_invite(request: Request, payload: TeamInviteRequest):
    actor = _auth.require_auth(request)
    return _call_service(
        _team_members.create_invite,
        team_id=payload.team_id,
        email=payload.email,
        role=payload.role,
        season_id=payload.season_id,
        player_ids=payload.player_ids,
        actor=actor,
    )


@router.post("/invites/{invite_id}/revoke")
async def revoke_team_invite(request: Request, invite_id: str, team_id: str = Query(..., min_length=1)):
    actor = _auth.require_auth(request)
    return _call_service(_team_members.revoke_invite, team_id, invite_id, actor)


@router.post("/invites/accept")
async def accept_team_invite(payload: AcceptTeamInviteRequest):
    return _call_service(
        _team_members.accept_invite,
        token=payload.token,
        user_id=payload.user_id,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
    )
