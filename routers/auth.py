"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
from models import LoginRequest

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


@router.get("/api/auth/check")
async def auth_check(request: Request):
    try:
        user = _auth.require_auth(request)
        return {"authenticated": True, "role": user["role"], "roles": user.get("roles", []), "username": user["username"]}
    except HTTPException:
        return {"authenticated": False}
