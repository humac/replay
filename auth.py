"""Authentication — token management, login rate limiting, origin validation, multi-user."""

from __future__ import annotations

import hashlib
import os
import secrets
import time

from fastapi import HTTPException, Request

import db as _db

# In-memory token store: {token_string: {created, user_id, role, username}}
_active_tokens: dict[str, dict] = {}
TOKEN_TTL = 86400  # 24 hours
_MAX_ACTIVE_TOKENS = max(1, int(os.environ.get("MAX_ACTIVE_TOKENS", "1000")))
_last_token_sweep: float = 0.0
_TOKEN_SWEEP_INTERVAL = 60.0  # seconds

# Login rate limiting: {ip: [timestamps]}
_login_attempts: dict[str, list[float]] = {}
_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 60.0  # seconds

# Origin validation (comma-separated hostnames, optional)
_ALLOWED_ORIGINS_RAW = os.environ.get("ALLOWED_ORIGINS", "")
_ALLOWED_ORIGINS: set[str] | None = (
    {h.strip().lower() for h in _ALLOWED_ORIGINS_RAW.split(",") if h.strip()}
    if _ALLOWED_ORIGINS_RAW.strip() else None
)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
if not ADMIN_PASS:
    raise RuntimeError(
        "ADMIN_PASS environment variable is not set. "
        "Set a strong password in your environment or .env.local before starting the server."
    )


def role_set(role: str | None) -> set[str]:
    """Parse a stored role string.

    Historically Replay stored exactly one role in ``users.role``. Coaching
    adds combined access like ``coach,uploader`` without a disruptive schema
    rewrite, so permission checks normalize to a set.
    """
    roles = {part.strip().lower() for part in (role or "").split(",") if part.strip()}
    if "admin" in roles:
        roles.update({"coach", "uploader", "viewer"})
    return roles or {"viewer"}


def has_role(user: dict, *roles: str) -> bool:
    return bool(role_set(user.get("role")).intersection(roles))


# ---------------------------------------------------------------------------
# Password hashing (scrypt, stdlib only)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password using scrypt. Returns 'scrypt:<salt_hex>:<hash_hex>'."""
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt:{salt.hex()}:{h.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored scrypt hash."""
    try:
        parts = stored_hash.split(":")
        if len(parts) != 3 or parts[0] != "scrypt":
            return False
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
        h = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return secrets.compare_digest(h, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def sweep_expired_tokens():
    """Bulk-remove expired tokens at most once per sweep interval."""
    global _last_token_sweep
    now = time.time()
    if now - _last_token_sweep < _TOKEN_SWEEP_INTERVAL:
        return
    _last_token_sweep = now
    expired = [t for t, info in _active_tokens.items() if now - info["created"] > TOKEN_TTL]
    for t in expired:
        del _active_tokens[t]
    # Also prune stale login-attempt entries
    stale_ips = [ip for ip, timestamps in _login_attempts.items()
                 if not any(now - ts < _LOGIN_RATE_WINDOW for ts in timestamps)]
    for ip in stale_ips:
        del _login_attempts[ip]


def require_auth(request: Request) -> dict:
    """Validate Bearer token. Returns user info dict. Raises 401 if invalid."""
    sweep_expired_tokens()
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    token = auth_header[7:]
    info = _active_tokens.get(token)
    if info is None:
        raise HTTPException(401, "Invalid or expired token")
    if time.time() - info["created"] > TOKEN_TTL:
        del _active_tokens[token]
        raise HTTPException(401, "Token expired")
    roles = sorted(role_set(info.get("role")))
    return {
        "user_id": info.get("user_id"),
        "role": info["role"],
        "roles": roles,
        "username": info["username"],
    }


def require_role(request: Request, *roles: str) -> dict:
    """Validate token and check that the user has one of the given roles. Raises 403 if not."""
    user = require_auth(request)
    if not has_role(user, *roles):
        raise HTTPException(403, "Insufficient permissions")
    return user


def require_global_admin(request: Request) -> dict:
    """Require the legacy global/system admin role for recovery and cross-team operations."""
    return require_role(request, "admin")


def require_team_role(request: Request, team_id: str, *roles: str, allow_global_admin_override: bool = False):
    """Require the current user to have a scoped team membership role/capability."""
    import tenancy as _tenancy

    user = require_auth(request)
    return _tenancy.require_team_role(
        request,
        user,
        team_id,
        *roles,
        allow_global_admin_override=allow_global_admin_override,
    )


# Compatibility alias for callers that follow the internal helper naming used
# in the platform plan.
_require_team_role = require_team_role
_require_global_admin = require_global_admin


def check_login_rate_limit(request: Request):
    """Raise 429 if too many login attempts from this IP."""
    # Imported lazily to avoid a top-level circular import (streams imports nothing
    # back into auth, but server.py wires both together).
    import streams as _streams
    ip = _streams.client_ip(request)
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_RATE_WINDOW]
    if len(attempts) >= _LOGIN_RATE_LIMIT:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    attempts.append(now)
    _login_attempts[ip] = attempts


def validate_login_origin(request: Request):
    """Validate Origin header on login if ALLOWED_ORIGINS is configured."""
    if _ALLOWED_ORIGINS is None:
        return
    origin = request.headers.get("origin") or ""
    if not origin:
        return  # Non-browser client, allow
    host = origin.split("//", 1)[-1].split("/")[0].split(":")[0].lower()
    if host not in _ALLOWED_ORIGINS:
        raise HTTPException(403, "Origin not allowed")


def create_token(user_id: str | None, role: str, username: str) -> str:
    """Create a new auth token with associated user info."""
    sweep_expired_tokens()
    if len(_active_tokens) >= _MAX_ACTIVE_TOKENS:
        oldest_token = min(_active_tokens, key=lambda t: _active_tokens[t]["created"])
        del _active_tokens[oldest_token]
    token = secrets.token_hex(32)
    _active_tokens[token] = {
        "created": time.time(),
        "user_id": user_id,
        "role": role,
        "username": username,
    }
    return token


def revoke_token(request: Request):
    """Remove the token from the active set."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        _active_tokens.pop(auth_header[7:], None)


def active_token_count() -> int:
    return len(_active_tokens)


# ---------------------------------------------------------------------------
# Multi-user authentication
# ---------------------------------------------------------------------------

def authenticate_user(username: str, password: str) -> dict | None:
    """Authenticate against env-var admin first, then DB users.

    Returns user info dict on success, None on failure.

    Note: the env-var superadmin (ADMIN_USER/ADMIN_PASS) is checked before the
    DB user table and always bypasses the DB ``enabled`` flag.  If a deployer
    sets ADMIN_USER to a username that also exists as a disabled DB user, the
    env-var credentials still grant access.  This is intentional — the env-var
    admin is a break-glass override — but operators should avoid reusing the
    same name as a DB account.
    """
    # Check env-var superadmin
    if (secrets.compare_digest(username, ADMIN_USER) and
            secrets.compare_digest(password, ADMIN_PASS)):
        return {"user_id": None, "role": "admin", "username": ADMIN_USER}

    # Check DB users
    user = _db.get_user_by_username(username)
    if user and user["enabled"] and verify_password(password, user["password_hash"]):
        return {"user_id": user["id"], "role": user["role"], "username": user["username"]}

    return None
