"""Global-admin team/season/membership CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
from models import CreateAdminMembershipRequest, CreateAdminSeasonRequest, CreateAdminTeamRequest, UpdateAdminTeamRequest
from services import teams as _teams

router = APIRouter(prefix="/api/admin/teams", tags=["admin-teams"])


def _require_global_admin(request: Request) -> dict:
    return _auth.require_global_admin(request)


def _call_service(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except _teams.TeamServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("")
async def list_teams(request: Request):
    _require_global_admin(request)
    return _call_service(_teams.list_teams)


@router.post("")
async def create_team(payload: CreateAdminTeamRequest, request: Request):
    _require_global_admin(request)
    return _call_service(
        _teams.create_team,
        name=payload.name,
        slug=payload.slug,
        game_format=payload.game_format,
    )


@router.patch("/{team_id}")
async def update_team(team_id: str, payload: UpdateAdminTeamRequest, request: Request):
    _require_global_admin(request)
    return _call_service(
        _teams.update_team,
        team_id,
        name=payload.name,
        game_format=payload.game_format,
    )


@router.get("/{team_id}/seasons")
async def list_seasons(team_id: str, request: Request):
    _require_global_admin(request)
    return _call_service(_teams.list_seasons, team_id)


@router.post("/{team_id}/seasons")
async def create_season(team_id: str, payload: CreateAdminSeasonRequest, request: Request):
    _require_global_admin(request)
    return _call_service(
        _teams.create_season,
        team_id=team_id,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )


@router.get("/{team_id}/memberships")
async def list_memberships(team_id: str, request: Request):
    _require_global_admin(request)
    return _call_service(_teams.list_memberships, team_id)


@router.post("/{team_id}/memberships")
async def grant_membership(team_id: str, payload: CreateAdminMembershipRequest, request: Request):
    _require_global_admin(request)
    return _call_service(_teams.grant_membership, team_id=team_id, user_id=payload.user_id, role=payload.role)


@router.delete("/{team_id}/memberships/{membership_id}")
async def revoke_membership(team_id: str, membership_id: int, request: Request):
    _require_global_admin(request)
    return _call_service(_teams.revoke_membership, team_id=team_id, membership_id=membership_id)
