"""Tenant scope resolution and scoped team-role capability helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

import db as _db


ROLE_CAPABILITIES: dict[str, set[str]] = {
    "global_admin": {
        "global_admin",
        "team:read",
        "roster:manage",
        "membership:manage",
        "team_settings:manage",
        "ai_settings:manage",
        "storage_settings:manage",
        "match:read",
        "match:write",
        "coach_object:read",
        "coach_object:write",
        "coach_object:edit",
        "coach_object:delete_own",
        "coach_object:delete_others",
        "feedback:read_linked",
    },
    "team_admin": {
        "team:read",
        "roster:manage",
        "membership:manage",
        "team_settings:manage",
        "ai_settings:manage",
        "match:read",
        "match:write",
        "coach_object:read",
        "coach_object:write",
        "coach_object:edit",
        "coach_object:delete_own",
        "coach_object:delete_others",
        "feedback:read_linked",
    },
    "coach": {
        "team:read",
        "roster:read",
        "roster:manage",
        "match:read",
        "coach_object:read",
        "coach_object:write",
        "coach_object:edit",
        "coach_object:delete_own",
        "coach_object:delete_others",
        "feedback:read_linked",
    },
    "assistant_coach": {
        "team:read",
        "roster:read",
        "match:read",
        "coach_object:read",
        "coach_object:write",
        "coach_object:edit",
        "coach_object:delete_own",
    },
    "guardian": {
        "team:read",
        "feedback:read_linked",
    },
    "player": {
        "team:read",
        "feedback:read_linked",
    },
    "viewer": {
        "team:read",
    },
}

_ROLE_ALIASES = {
    "assistant-coach": "assistant_coach",
    "assistant coach": "assistant_coach",
    "family": "guardian",
}

_ROLE_PRECEDENCE = ["team_admin", "coach", "assistant_coach", "guardian", "player", "viewer"]


@dataclass(frozen=True)
class Scope:
    user: dict[str, Any]
    team: dict[str, Any]
    season: dict[str, Any] | None
    membership: dict[str, Any] | None
    effective_role: str
    is_global_admin: bool


def normalize_team_role(role: str | None) -> str:
    value = (role or "viewer").strip().lower().replace("-", "_").replace(" ", "_")
    return _ROLE_ALIASES.get(value, value)


def role_has_capability(role: str | None, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES.get(normalize_team_role(role), set())


def _is_global_admin(user: dict[str, Any]) -> bool:
    return "admin" in {part.strip().lower() for part in (user.get("role") or "").split(",") if part.strip()}


def _query_value(request: Request | Any | None, name: str) -> str | None:
    if request is None:
        return None
    query = getattr(request, "query_params", None)
    if query is None:
        return None
    if hasattr(query, "get"):
        value = query.get(name)
    else:
        value = None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _team_by_slug_or_id(conn, *, slug: str | None = None, team_id: str | None = None) -> dict[str, Any] | None:
    if team_id:
        row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
    elif slug:
        row = conn.execute("SELECT * FROM teams WHERE slug = ?", (slug,)).fetchone()
    else:
        return None
    return dict(row) if row else None


def _season_for_team(conn, team_id: str, season_id: str | None = None) -> dict[str, Any] | None:
    if season_id:
        row = conn.execute("SELECT * FROM seasons WHERE id = ? AND team_id = ?", (season_id, team_id)).fetchone()
        if row is None:
            raise HTTPException(403, "Season is not available for the resolved team")
        return dict(row)
    row = conn.execute(
        """
        SELECT * FROM seasons
        WHERE team_id = ?
        ORDER BY CASE WHEN name = 'Default Season' THEN 0 ELSE 1 END, created_at ASC, id ASC
        LIMIT 1
        """,
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


def _memberships_for_user(conn, user_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT m.*, t.slug AS team_slug, t.name AS team_name
        FROM team_user_memberships m
        JOIN teams t ON t.id = m.team_id
        WHERE m.user_id = ?
        ORDER BY m.team_id, m.role
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _membership_for_team(conn, user_id: str, team_id: str) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT * FROM team_user_memberships WHERE user_id = ? AND team_id = ?",
        (user_id, team_id),
    ).fetchall()
    memberships = [dict(row) for row in rows]
    return _best_membership(memberships)


def _best_membership(memberships: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not memberships:
        return None
    by_role = {normalize_team_role(m["role"]): m for m in memberships}
    for role in _ROLE_PRECEDENCE:
        if role in by_role:
            return by_role[role]
    return memberships[0]


def _role_satisfies(role: str, required: str) -> bool:
    required = normalize_team_role(required)
    role = normalize_team_role(role)
    if role == required:
        return True
    if required in ROLE_CAPABILITIES:
        # Role inheritance without route-local special cases.
        if required == "team_admin":
            return role == "global_admin"
        if required == "coach":
            return role_has_capability(role, "coach_object:write")
        if required == "viewer":
            return role_has_capability(role, "team:read")
        return False
    return role_has_capability(role, required)


def role_satisfies_any(role: str, required: str | list[str] | tuple[str, ...] | set[str] | None) -> bool:
    if required is None:
        return True
    required_items = [required] if isinstance(required, str) else list(required)
    return any(_role_satisfies(role, item) for item in required_items)


def resolve_scope(
    request: Request | Any | None,
    user: dict[str, Any],
    *,
    team: str | None = None,
    team_id: str | None = None,
    season_id: str | None = None,
    require_role: str | list[str] | tuple[str, ...] | set[str] | None = None,
    allow_global_admin_override: bool = False,
) -> Scope:
    """Resolve the active team/season and scoped membership for a request.

    Normal team-scoped resources require a ``team_user_memberships`` row even
    when ``users.role`` contains legacy ``coach`` or ``admin``. Break-glass
    global/system admin behavior is only enabled by callers that pass
    ``allow_global_admin_override=True`` or use ``auth.require_global_admin``.
    """
    explicit_slug = team or _query_value(request, "team")
    explicit_team_id = team_id or _query_value(request, "team_id")
    explicit_season_id = season_id or _query_value(request, "season_id")
    is_global_admin = _is_global_admin(user)
    user_id = user.get("user_id")

    with _db.connect() as conn:
        if explicit_slug and explicit_team_id:
            slug_team = _team_by_slug_or_id(conn, slug=explicit_slug)
            id_team = _team_by_slug_or_id(conn, team_id=explicit_team_id)
            if slug_team is None or id_team is None:
                raise HTTPException(404, "Team not found")
            if slug_team["id"] != id_team["id"]:
                raise HTTPException(409, "Conflicting team selectors")
            selected_team = id_team
        else:
            selected_team = _team_by_slug_or_id(conn, slug=explicit_slug, team_id=explicit_team_id)
        if (explicit_slug or explicit_team_id) and selected_team is None:
            raise HTTPException(404, "Team not found")

        explicit_season_row = None
        if explicit_season_id:
            explicit_season_row = conn.execute("SELECT * FROM seasons WHERE id = ?", (explicit_season_id,)).fetchone()
            if explicit_season_row is None:
                raise HTTPException(404, "Season not found")
            if selected_team is None:
                selected_team = _team_by_slug_or_id(conn, team_id=explicit_season_row["team_id"])
            elif selected_team["id"] != explicit_season_row["team_id"]:
                raise HTTPException(403, "Season is not available for the resolved team")

        memberships: list[dict[str, Any]] = []
        membership: dict[str, Any] | None = None
        if user_id:
            memberships = _memberships_for_user(conn, str(user_id))

        if selected_team is None and user_id:
            user_row = conn.execute("SELECT last_team_id FROM users WHERE id = ?", (user_id,)).fetchone()
            last_team_id = user_row["last_team_id"] if user_row else None
            if last_team_id:
                selected_team = _team_by_slug_or_id(conn, team_id=last_team_id)
                membership = _membership_for_team(conn, str(user_id), last_team_id) if selected_team else None
                if selected_team is not None and membership is None:
                    raise HTTPException(409, "Team selection required")

        if selected_team is None and len({m["team_id"] for m in memberships}) == 1:
            selected_team = _team_by_slug_or_id(conn, team_id=memberships[0]["team_id"])

        if selected_team is None:
            if allow_global_admin_override and is_global_admin:
                selected_team = _db.get_default_team(conn=conn)
            elif len({m["team_id"] for m in memberships}) > 1:
                raise HTTPException(409, "Team selection required")
            else:
                raise HTTPException(403, "Team membership required")

        if membership is None and user_id:
            membership = _membership_for_team(conn, str(user_id), selected_team["id"])

        override_global_admin = allow_global_admin_override and is_global_admin
        if override_global_admin:
            effective_role = "global_admin"
        elif membership is None:
            raise HTTPException(403, "Team membership required")
        else:
            effective_role = normalize_team_role(membership["role"])

        if require_role is not None and not role_satisfies_any(effective_role, require_role):
            raise HTTPException(403, "Insufficient team permissions")

        selected_season = _season_for_team(conn, selected_team["id"], explicit_season_id)
        return Scope(
            user=user,
            team=selected_team,
            season=selected_season,
            membership=membership,
            effective_role=effective_role,
            is_global_admin=is_global_admin,
        )


def require_team_role(
    request: Request,
    user: dict[str, Any],
    team_id: str,
    *roles: str,
    allow_global_admin_override: bool = False,
) -> Scope:
    """Require a membership role/capability for a concrete team id."""
    return resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role=list(roles) or None,
        allow_global_admin_override=allow_global_admin_override,
    )


def current_team(request: Request, user: dict[str, Any]) -> dict[str, Any]:
    """Return the resolved current team for compatibility with the PR 2.1 contract."""
    return resolve_scope(request, user).team
