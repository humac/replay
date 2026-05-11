"""Authentication routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import db as _db
import tenancy as _tenancy
from models import (
    EmailVerificationConfirmRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PatchMeProfileRequest,
    UpdateActiveScopeRequest,
)

router = APIRouter()


@router.post("/api/login")
async def login(request: Request, body: LoginRequest):
    _auth.check_login_rate_limit(request)
    _auth.validate_login_origin(request)
    user = _auth.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = _auth.create_token(user["user_id"], user["role"], user["username"], request=request)
    return {"token": token, "role": user["role"], "roles": sorted(_auth.role_set(user["role"])), "username": user["username"]}


@router.post("/api/logout")
async def logout(request: Request):
    _auth.revoke_token(request)
    return {"ok": True}


@router.post("/api/auth/password-reset/request")
async def request_password_reset(request: Request, body: PasswordResetRequest):
    _auth.check_password_reset_rate_limit(request, body.username)
    reset_token = _auth.create_password_reset_token_for_username(body.username)
    payload = {"ok": True}
    if reset_token and os.environ.get("REPLAY_DEV_TOKEN_DELIVERY") == "1":
        payload["reset_token"] = reset_token
    return payload


@router.post("/api/auth/password-reset/confirm")
async def confirm_password_reset(body: PasswordResetConfirmRequest):
    if not _auth.reset_password_with_token(body.token, body.new_password):
        raise HTTPException(400, "Invalid or expired password reset token")
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


@router.post("/api/me/password")
async def change_me_password(request: Request, body: PasswordChangeRequest):
    user = _auth.require_auth(request)
    user_id = str(user.get("user_id") or "")
    if not user_id:
        raise HTTPException(403, "Password changes are only available for database users")
    if not _auth.change_password(user_id, body.current_password, body.new_password):
        raise HTTPException(400, "Current password is invalid")
    return {"ok": True}


@router.post("/api/me/email-verification/request")
async def request_me_email_verification(request: Request):
    user = _auth.require_auth(request)
    user_id = str(user.get("user_id") or "")
    if not user_id:
        raise HTTPException(403, "Email verification is only available for database users")
    token = _auth.create_email_verification_token_for_user(user_id)
    if not token:
        raise HTTPException(400, "Profile email is required before verification")
    return {"ok": True, "verification_token": token}


@router.post("/api/me/email-verification/confirm")
async def confirm_me_email_verification(body: EmailVerificationConfirmRequest):
    if not _auth.verify_email_with_token(body.token):
        raise HTTPException(400, "Invalid or expired email verification token")
    return {"ok": True}


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
