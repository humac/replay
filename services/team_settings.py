"""Team-scoped settings registry for AI governance and coaching defaults."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import db as _db
from tenancy import role_has_capability

AI_DRAFT_TARGETS = {
    "player_summary",
    "what_happened",
    "why_it_matters",
    "what_to_do_next",
    "clip_title",
    "clip_description",
    "goal_description",
    "goal_success_criteria",
    "summary_team_positives",
    "summary_team_improvements",
    "summary_training_focus",
}
PERMANENTLY_EXCLUDED_DRAFT_TARGETS = {"coach_private_note"}
COACHING_VISIBILITIES = {"private", "team", "player", "unlisted"}
NEVER_DRAFT_VISIBILITIES = {"private", "player"}
GOAL_VISIBILITIES = {"player", "coach"}

# Closed schema registry. Keep value types JSON-native so a future API layer can
# translate TeamSettingValidationError.status_code to HTTP 422 without importing
# FastAPI here.
TEAM_SETTING_SCHEMAS: dict[str, dict[str, Any]] = {
    "ai.drafting_enabled": {"kind": "bool", "default": False},
    "ai.allowed_draft_targets": {
        "kind": "array_enum",
        "choices": sorted(AI_DRAFT_TARGETS),
        "default": [],
        "max_items": len(AI_DRAFT_TARGETS),
    },
    "ai.tone": {"kind": "enum", "choices": ["direct", "encouraging", "technical"], "default": "direct"},
    "ai.never_draft_for_visibilities": {
        "kind": "array_enum",
        "choices": sorted(NEVER_DRAFT_VISIBILITIES),
        "default": ["private", "player"],
        "max_items": len(NEVER_DRAFT_VISIBILITIES),
    },
    "notes.default_visibility": {
        "kind": "enum",
        "choices": ["private", "team", "player", "unlisted"],
        "default": "private",
    },
    "summaries.default_visibility": {
        "kind": "enum",
        "choices": ["private", "team", "player", "unlisted"],
        "default": "private",
    },
    "goals.default_visibility": {"kind": "enum", "choices": ["player", "coach"], "default": "player"},
}


@dataclass
class TeamSettingValidationError(ValueError):
    key: str
    code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:  # pragma: no cover - dataclass repr is enough; human helper
        return self.detail


@dataclass
class TeamSettingAuthorizationError(PermissionError):
    detail: str
    status_code: int = 403

    def __str__(self) -> str:  # pragma: no cover
        return self.detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TeamSettingValidationError("", "invalid_json", "Setting value must be JSON serializable") from exc


def _json_loads(value_json: str) -> Any:
    return json.loads(value_json)


def _actor_id(actor_user: dict[str, Any] | None) -> str:
    if not actor_user:
        return ""
    return str(actor_user.get("id") or actor_user.get("user_id") or actor_user.get("username") or "")


def _is_global_admin(actor_user: dict[str, Any] | None) -> bool:
    roles = {part.strip().lower() for part in str((actor_user or {}).get("role") or "").split(",") if part.strip()}
    return "admin" in roles


def _require_team_scope(conn: sqlite3.Connection, team_id: str, actor_user: dict[str, Any] | None, *, write: bool) -> None:
    row = conn.execute("SELECT id FROM teams WHERE id = ?", (team_id,)).fetchone()
    if row is None:
        raise TeamSettingAuthorizationError("Team not found", status_code=404)
    if _is_global_admin(actor_user):
        return
    user_id = _actor_id(actor_user)
    if not user_id:
        raise TeamSettingAuthorizationError("Team membership is required")
    rows = conn.execute(
        "SELECT role FROM team_user_memberships WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    ).fetchall()
    capability = "team_settings:manage" if write else "team:read"
    if not any(role_has_capability(row["role"], capability) for row in rows):
        raise TeamSettingAuthorizationError("Team membership is required")


def _schema_for(key: str) -> dict[str, Any]:
    if key not in TEAM_SETTING_SCHEMAS:
        raise TeamSettingValidationError(key, "unsupported_key", "Unsupported team setting key")
    return TEAM_SETTING_SCHEMAS[key]


def validate_value(key: str, value: Any) -> Any:
    spec = _schema_for(key)
    kind = spec["kind"]
    if kind == "bool":
        if type(value) is not bool:
            raise TeamSettingValidationError(key, "invalid_type", f"{key} must be a boolean")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            raise TeamSettingValidationError(key, "invalid_type", f"{key} must be a string")
        if value not in spec["choices"]:
            raise TeamSettingValidationError(key, "invalid_enum", f"Unsupported value for {key}")
        return value
    if kind == "array_enum":
        if not isinstance(value, list):
            raise TeamSettingValidationError(key, "invalid_type", f"{key} must be an array")
        if len(value) > int(spec.get("max_items", len(value))):
            raise TeamSettingValidationError(key, "too_many_items", f"{key} has too many entries")
        choices = set(spec["choices"])
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise TeamSettingValidationError(key, "invalid_type", f"{key} entries must be strings")
            if item not in choices:
                raise TeamSettingValidationError(key, "invalid_enum", f"Unsupported value for {key}")
            if item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized
    raise TeamSettingValidationError(key, "unsupported_type", f"Unsupported schema type for {key}")


def _default_value(key: str) -> Any:
    return copy.deepcopy(TEAM_SETTING_SCHEMAS[key]["default"])


def _row_to_setting(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "team_id": row["team_id"],
        "key": row["key"],
        "value": _json_loads(row["value_json"]),
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"] or "",
    }


def list_settings(team_id: str, *, actor_user: dict[str, Any] | None = None) -> dict[str, Any]:
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, write=False)
        rows = conn.execute("SELECT * FROM team_settings WHERE team_id = ?", (team_id,)).fetchall()
    values = {key: _default_value(key) for key in TEAM_SETTING_SCHEMAS}
    for row in rows:
        if row["key"] in TEAM_SETTING_SCHEMAS:
            values[row["key"]] = _json_loads(row["value_json"])
    return values


def get_setting(team_id: str, key: str, *, actor_user: dict[str, Any] | None = None) -> Any:
    _schema_for(key)
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, write=False)
        row = conn.execute("SELECT * FROM team_settings WHERE team_id = ? AND key = ?", (team_id, key)).fetchone()
    if row is None:
        return _default_value(key)
    return _json_loads(row["value_json"])


def set_setting(team_id: str, key: str, value: Any, *, actor_user: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = validate_value(key, value)
    value_json = _json_dumps(normalized)
    now = _now_iso()
    actor_id = _actor_id(actor_user)
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, write=True)
        prior_row = conn.execute(
            "SELECT value_json FROM team_settings WHERE team_id = ? AND key = ?",
            (team_id, key),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO team_settings (team_id, key, value_json, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(team_id, key) DO UPDATE SET
                value_json=excluded.value_json,
                updated_at=excluded.updated_at,
                updated_by=excluded.updated_by
            """,
            (team_id, key, value_json, now, actor_id),
        )
        conn.commit()
    old_value = _json_loads(prior_row["value_json"]) if prior_row else _default_value(key)
    if old_value != normalized:
        _db.log_activity_event(
            "team_settings.updated",
            message=f"Team setting {key} updated",
            actor=actor_id,
            metadata={"team_id": team_id, "key": key},
        )
    with _db.connect() as conn:
        return _row_to_setting(conn.execute("SELECT * FROM team_settings WHERE team_id = ? AND key = ?", (team_id, key)).fetchone())


def can_generate_draft(
    team_id: str,
    target: str,
    *,
    visibility: str | None,
    actor_user: dict[str, Any] | None = None,
) -> bool:
    """Return whether a draft may be generated for a target and target-resource visibility.

    The visibility is the current/proposed visibility of the target resource for
    fields without a fixed visibility. `coach_private_note` is permanently
    excluded regardless of registry settings.
    """
    if target in PERMANENTLY_EXCLUDED_DRAFT_TARGETS:
        return False
    if target not in AI_DRAFT_TARGETS:
        return False
    settings = list_settings(team_id, actor_user=actor_user)
    if not settings["ai.drafting_enabled"]:
        return False
    if target not in settings["ai.allowed_draft_targets"]:
        return False
    if visibility is None:
        return False
    if visibility not in COACHING_VISIBILITIES and visibility not in GOAL_VISIBILITIES:
        return False
    if visibility in settings["ai.never_draft_for_visibilities"]:
        return False
    return True
