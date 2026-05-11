"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import db as _db
import tenancy as _tenancy
from models import LoginRequest, PatchMeProfileRequest, UpdateActiveScopeRequest

router = APIRouter()


@router.post("/api/login")
async def login(request: Request, body: LoginRequest):
    _auth.check_login_rate_limit(request)
    _auth.validate_login_origin(request)
    user = _auth.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = _auth.create_token(user["user_id"], user["role"], user["username"])
    return {"token": token, "role": user["role"], "roles": sorted(_auth.role_set(user["role"])), "username": user["username"]}


@router.post("/api/logout")
async def logout(request: Request):
    _auth.revoke_token(request)
    return {"ok": True}


@router.get("/api/me")
async def me(request: Request):
    user = _auth.require_auth(request)
    return _tenancy.build_me_scope_summary(request, user)


@router.patch("/api/me/profile")
async def update_me_profile(request: Request, body: PatchMeProfileRequest):
    user = _auth.require_auth(request)
    user_id = str(user.get("user_id") or user.get("id") or "")
    if not user_id:
        raise HTTPException(401, "Authentication required")
    try:
        profile = _db.upsert_user_profile(user_id, body.model_dump(exclude_unset=True))
    except _db.DuplicateEmailError as exc:
        raise HTTPException(409, "Email is already in use") from exc
    return {"profile": _db.public_user_profile(profile)}


@router.put("/api/me/scope")
async def update_me_scope(request: Request, body: UpdateActiveScopeRequest):
    user = _auth.require_auth(request)
    return _tenancy.save_active_scope(request, user, team_id=body.team_id, season_id=body.season_id)


@router.get("/api/auth/check")
async def auth_check(request: Request):
    try:
        user = _auth.require_auth(request)
        return {"authenticated": True, "role": user["role"], "roles": user.get("roles", []), "username": user["username"]}
    except HTTPException:
        return {"authenticated": False}
