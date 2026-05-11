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

        saved_last_team_id = None
        saved_last_season_id = None
        if user_id:
            user_row = conn.execute("SELECT last_team_id, last_season_id FROM users WHERE id = ?", (user_id,)).fetchone()
            saved_last_team_id = user_row["last_team_id"] if user_row else None
            saved_last_season_id = user_row["last_season_id"] if user_row else None
        if selected_team is None and saved_last_team_id:
            selected_team = _team_by_slug_or_id(conn, team_id=saved_last_team_id)
            membership = _membership_for_team(conn, str(user_id), saved_last_team_id) if selected_team else None
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

        selected_season_id = explicit_season_id
        if not selected_season_id and saved_last_team_id == selected_team["id"]:
            selected_season_id = saved_last_season_id
        try:
            selected_season = _season_for_team(conn, selected_team["id"], selected_season_id)
        except HTTPException as exc:
            if selected_season_id and not explicit_season_id and exc.status_code == 403:
                raise HTTPException(409, "Team selection required") from exc
            raise
        return Scope(
            user=user,
            team=selected_team,
            season=selected_season,
            membership=membership,
            effective_role=effective_role,
            is_global_admin=is_global_admin,
        )


def _serialize_team(team: dict[str, Any] | None) -> dict[str, Any] | None:
    if team is None:
        return None
    return {
        "id": team.get("id"),
        "slug": team.get("slug") or "",
        "name": team.get("name") or "",
        "game_format": team.get("game_format") or "full",
    }


def _serialize_season(season: dict[str, Any] | None) -> dict[str, Any] | None:
    if season is None:
        return None
    return {
        "id": season.get("id"),
        "team_id": season.get("team_id"),
        "name": season.get("name") or "",
        "starts_on": season.get("starts_on") or "",
        "ends_on": season.get("ends_on") or "",
        "created_at": season.get("created_at") or "",
    }


def _serialize_membership(membership: dict[str, Any] | None) -> dict[str, Any] | None:
    if membership is None:
        return None
    role = normalize_team_role(membership.get("role"))
    return {
        "id": membership.get("id"),
        "team_id": membership.get("team_id"),
        "role": role,
        "capabilities": sorted(ROLE_CAPABILITIES.get(role, set())),
        "created_at": membership.get("created_at") or "",
    }


def _serialize_scope(scope: Scope | None) -> dict[str, Any] | None:
    if scope is None:
        return None
    return {
        "team": _serialize_team(scope.team),
        "season": _serialize_season(scope.season),
        "membership": _serialize_membership(scope.membership),
        "effective_role": scope.effective_role,
        "capabilities": sorted(ROLE_CAPABILITIES.get(scope.effective_role, set())),
        "is_global_admin": scope.is_global_admin,
    }


def build_me_scope_summary(request: Request | Any | None, user: dict[str, Any]) -> dict[str, Any]:
    """Return the authenticated user's safe team/season scope summary.

    This is intentionally read-only and self-scoped. It lists only the
    caller's memberships and eligible teams/seasons; it never exposes other
    users, player links, password hashes, or admin membership-list fields.
    """
    user_id = str(user.get("user_id") or user.get("id") or "")
    role_value = user.get("role") or ""
    roles = sorted({part.strip().lower() for part in role_value.split(",") if part.strip()})
    is_global_admin = _is_global_admin(user)

    with _db.connect() as conn:
        db_user = conn.execute(
            "SELECT id, username, role, display_name, enabled, last_team_id, last_season_id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone() if user_id else None
        if db_user is not None:
            role_value = db_user["role"] or role_value
            roles = sorted({part.strip().lower() for part in role_value.split(",") if part.strip()})
            user_payload = {
                "id": db_user["id"],
                "username": db_user["username"],
                "display_name": db_user["display_name"] or "",
                "role": role_value,
                "roles": roles,
                "is_global_admin": "admin" in roles,
                "last_team_id": db_user["last_team_id"],
                "last_season_id": db_user["last_season_id"],
            }
        else:
            user_payload = {
                "id": user_id,
                "username": user.get("username") or "",
                "display_name": user.get("display_name") or "",
                "role": role_value,
                "roles": roles,
                "is_global_admin": is_global_admin,
                "last_team_id": None,
                "last_season_id": None,
            }

        membership_rows = conn.execute(
            """
            SELECT
                m.id, m.team_id, m.user_id, m.role, m.created_at,
                t.slug AS team_slug, t.name AS team_name, t.game_format AS team_game_format,
                t.created_at AS team_created_at
            FROM team_user_memberships AS m
            JOIN teams AS t ON t.id = m.team_id
            WHERE m.user_id = ?
            ORDER BY t.name COLLATE NOCASE ASC, m.team_id ASC, m.role ASC, m.id ASC
            """,
            (user_id,),
        ).fetchall() if user_id else []
        memberships = [dict(row) for row in membership_rows]

        by_team: dict[str, dict[str, Any]] = {}
        for membership in memberships:
            by_team.setdefault(membership["team_id"], {
                "id": membership["team_id"],
                "slug": membership.get("team_slug") or "",
                "name": membership.get("team_name") or "",
                "game_format": membership.get("team_game_format") or "full",
                "created_at": membership.get("team_created_at") or "",
                "memberships": [],
            })["memberships"].append(membership)

        seasons_by_team: dict[str, list[dict[str, Any]]] = {team_id: [] for team_id in by_team}
        if by_team:
            placeholders = ",".join("?" for _ in by_team)
            season_rows = conn.execute(
                f"""
                SELECT * FROM seasons
                WHERE team_id IN ({placeholders})
                ORDER BY team_id ASC, starts_on ASC, created_at ASC, name COLLATE NOCASE ASC
                """,
                tuple(by_team.keys()),
            ).fetchall()
            for row in season_rows:
                season = _serialize_season(dict(row))
                if season is not None:
                    seasons_by_team.setdefault(season["team_id"], []).append(season)

    membership_payload = []
    for membership in memberships:
        role = normalize_team_role(membership.get("role"))
        membership_payload.append({
            "id": membership.get("id"),
            "team_id": membership.get("team_id"),
            "team_slug": membership.get("team_slug") or "",
            "team_name": membership.get("team_name") or "",
            "role": role,
            "capabilities": sorted(ROLE_CAPABILITIES.get(role, set())),
            "created_at": membership.get("created_at") or "",
        })

    teams_payload = []
    for team in by_team.values():
        best = _best_membership(team["memberships"])
        role = normalize_team_role(best.get("role") if best else None)
        teams_payload.append({
            "id": team["id"],
            "slug": team["slug"],
            "name": team["name"],
            "game_format": team["game_format"],
            "membership_role": role,
            "capabilities": sorted(ROLE_CAPABILITIES.get(role, set())),
            "seasons": seasons_by_team.get(team["id"], []),
        })

    active_scope = None
    selection_required = False
    has_explicit_selector = any(
        _query_value(request, name)
        for name in ("team", "team_id", "season_id")
    )
    try:
        active_scope = _serialize_scope(resolve_scope(request, user))
    except HTTPException as exc:
        if has_explicit_selector and exc.status_code in {403, 404, 409}:
            selection_required = False
        elif exc.status_code == 409 and str(exc.detail) == "Team selection required":
            selection_required = True
        elif exc.status_code == 403 and str(exc.detail) == "Team membership required":
            selection_required = False
        else:
            raise

    saved_team_id = user_payload.get("last_team_id")
    saved_season_id = user_payload.get("last_season_id")
    saved_season_is_eligible = any(
        season.get("id") == saved_season_id
        for season in seasons_by_team.get(str(saved_team_id), [])
    )
    if saved_team_id not in by_team or (saved_season_id and not saved_season_is_eligible):
        user_payload["last_team_id"] = None
        user_payload["last_season_id"] = None

    return {
        "user": user_payload,
        "profile": _db.public_user_profile(_db.get_user_profile(user_id)) if user_id else _db.public_user_profile({}),
        "memberships": membership_payload,
        "teams": teams_payload,
        "seasons": [season for team_id in sorted(seasons_by_team) for season in seasons_by_team[team_id]],
        "active_scope": active_scope,
        "selection_required": selection_required,
    }


def save_active_scope(request: Request | Any | None, user: dict[str, Any], *, team_id: str, season_id: str) -> dict[str, Any]:
    """Validate and persist the caller's active team/season selection."""
    user_id = str(user.get("user_id") or user.get("id") or "")
    if not user_id:
        raise HTTPException(401, "Authentication required")
    try:
        scope = resolve_scope(request, user, team_id=team_id, season_id=season_id)
    except HTTPException as exc:
        if exc.status_code in {403, 404, 409}:
            raise HTTPException(403, "Scope selection is not available") from exc
        raise
    _db.set_user_active_scope(user_id, scope.team["id"], scope.season["id"] if scope.season else "")
    return build_me_scope_summary(request, user)



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


# ---------------------------------------------------------------------------
# Coach-object delete authorization (PR-AUTH)
#
# Centralizes the "can this membership delete this coach object?" check across
# notes / clips / playlists / goals / match_summaries. Routes already enforce
# team-scope ownership separately via `_require_*_in_team`; this helper layers
# creator-vs-other-coach gating on top so an assistant_coach cannot delete a
# different coach's object.
# ---------------------------------------------------------------------------

_VALID_COACH_OBJECT_TYPES = frozenset({
    "note", "clip", "playlist", "goal", "match_summary",
})


def assert_can_delete_coach_object(
    scope: Scope,
    obj_type: str,
    *,
    created_by_user_id: str | None,
) -> None:
    """Raise HTTPException if the actor in ``scope`` cannot delete a coach
    object of type ``obj_type`` whose creator is ``created_by_user_id``.

    Policy:
    - Unknown ``obj_type`` → 422 (closed enum, defense in depth).
    - Actor whose effective role has ``coach_object:delete_others`` →
      allowed for any creator (still inside the same team scope, which
      the caller has already verified via ``_require_*_in_team``).
    - Actor with only ``coach_object:delete_own`` → allowed only when
      ``created_by_user_id`` matches the actor's identity. ``created_by``
      on coach objects stores the actor's ``username`` (not user_id), so
      we compare against ``scope.user["username"]``. A creator with no
      recorded username (``None``/empty) is treated as "not owned by the
      actor" so a missing audit field cannot grant deletion.
    - Otherwise → 403.
    """
    if obj_type not in _VALID_COACH_OBJECT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported coach object type: {obj_type}")
    caps = ROLE_CAPABILITIES.get(normalize_team_role(scope.effective_role), set())
    if "coach_object:delete_others" in caps:
        return
    actor_username = (scope.user.get("username") if scope.user else None) or ""
    creator = (created_by_user_id or "").strip()
    if (
        "coach_object:delete_own" in caps
        and creator
        and actor_username
        and str(creator) == str(actor_username)
    ):
        return
    raise HTTPException(status_code=403, detail="You do not have permission to delete this coach object")
