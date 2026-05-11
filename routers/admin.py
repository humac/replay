"""Admin user-management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import db as _db
import log as _log
from models import CreateUserRequest, UpdateUserRequest
from services.activity import log_activity

logger = _log.setup("replay")
router = APIRouter()


@router.get("/api/users")
async def list_users(request: Request):
    _auth.require_role(request, "admin")
    users = _db.list_users(allow_unscoped=True)
    # Strip password hashes from response
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in users
    ]


@router.post("/api/users")
async def create_user(request: Request, body: CreateUserRequest):
    actor = _auth.require_role(request, "admin")
    existing = _db.get_user_by_username(body.username)
    if existing:
        raise HTTPException(409, "Username already exists")
    password_hash = _auth.hash_password(body.password)
    user = _db.create_user(body.username, password_hash, body.role, body.display_name)
    log_activity(
        "user.created",
        severity="info",
        message=f"User created: {body.username}",
        actor=actor["username"],
        metadata={"target_user_id": user.get("id"), "role": body.role},
    )
    return {"ok": True, "user": user}


@router.patch("/api/users/{user_id}")
async def update_user(user_id: str, request: Request, body: UpdateUserRequest):
    actor = _auth.require_role(request, "admin")
    user = _db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    updates = {}
    if body.password is not None:
        updates["password_hash"] = _auth.hash_password(body.password)
    if body.role is not None:
        updates["role"] = body.role
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.enabled is not None:
        updates["enabled"] = 1 if body.enabled else 0
    if not updates:
        return {"ok": True}
    _db.update_user(user_id, **updates)
    updated = _db.get_user_by_id(user_id)
    logger.info("admin.action", extra={"action": "update_user", "actor": actor["username"], "target_id": user_id, "fields": list(updates)})
    log_activity(
        "user.updated",
        severity="info",
        message=f"User updated: {updated.get('username', user_id)}",
        actor=actor["username"],
        metadata={"target_user_id": user_id, "fields": list(updates)},
    )
    return {"ok": True, "user": {k: v for k, v in updated.items() if k != "password_hash"}}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    user = _auth.require_role(request, "admin")
    target = _db.get_user_by_id(user_id)
    if not _db.delete_user(user_id):
        raise HTTPException(404, "User not found")
    logger.info("admin.action", extra={"action": "delete_user", "actor": user["username"], "target_id": user_id})
    log_activity(
        "user.deleted",
        severity="warning",
        message=f"User deleted: {target.get('username', user_id) if target else user_id}",
        actor=user["username"],
        metadata={"target_user_id": user_id},
    )
    return {"ok": True}
