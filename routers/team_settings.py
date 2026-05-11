"""Coach/team settings API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import tenancy as _tenancy
from models import PatchTeamSettingsRequest
from services import team_settings as _team_settings

router = APIRouter(prefix="/api/coach/team/settings", tags=["team-settings"])


def _can_edit_scope(scope: _tenancy.Scope) -> bool:
    if scope.is_global_admin:
        return True
    return _tenancy.role_has_capability(scope.effective_role, "team_settings:manage")


def _settings_payload(scope: _tenancy.Scope, user: dict[str, Any]) -> dict[str, Any]:
    settings = _team_settings.list_settings(scope.team["id"], actor_user=user)
    return {
        "team_id": scope.team["id"],
        "team": scope.team,
        "season": scope.season,
        "effective_role": scope.effective_role,
        "can_edit": _can_edit_scope(scope),
        "settings": settings,
        "schema": _team_settings.TEAM_SETTING_SCHEMAS,
    }


def _validation_detail(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {"code": "team_settings_validation_failed", "errors": errors}


@router.get("")
async def get_team_settings(request: Request):
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("coach", "team_admin"),
        allow_global_admin_override=True,
    )
    try:
        return _settings_payload(scope, user)
    except _team_settings.TeamSettingAuthorizationError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.patch("")
async def patch_team_settings(payload: PatchTeamSettingsRequest, request: Request):
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        require_role=("coach", "team_admin"),
        allow_global_admin_override=True,
    )
    if not _can_edit_scope(scope):
        raise HTTPException(403, "Team admin permissions are required to edit team settings")

    normalized: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for key, value in payload.settings.items():
        try:
            normalized[key] = _team_settings.validate_value(key, value)
        except _team_settings.TeamSettingValidationError as exc:
            errors.append({"key": exc.key or key, "code": exc.code, "detail": exc.detail})
    if errors:
        raise HTTPException(422, _validation_detail(errors))

    try:
        for key, value in normalized.items():
            _team_settings.set_setting(scope.team["id"], key, value, actor_user=user)
        return _settings_payload(scope, user)
    except _team_settings.TeamSettingAuthorizationError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except _team_settings.TeamSettingValidationError as exc:
        raise HTTPException(422, _validation_detail([{"key": exc.key, "code": exc.code, "detail": exc.detail}])) from exc
