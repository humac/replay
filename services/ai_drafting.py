"""Team-scoped AI drafting run audit helpers for Phase 8.1.

This module intentionally does not call AI providers and does not persist raw
prompts, provider outputs, or private source text. It records only bounded run
metadata and compact evidence references so later phases can attach provider and
context-builder behavior without changing the audit lifecycle.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import db as _db
from services.team_settings import AI_DRAFT_TARGETS, PERMANENTLY_EXCLUDED_DRAFT_TARGETS
from tenancy import role_has_capability

RUN_STATUSES = {"queued", "running", "succeeded", "failed"}
MAX_EVIDENCE_REFS = 50
MAX_REF_STRING_LENGTH = 128
_ALLOWED_EVIDENCE_KEYS = ("type", "id", "visibility", "status", "reason")
_ALLOWED_EVIDENCE_TYPES = {
    "note",
    "clip",
    "playlist",
    "match",
    "match_summary",
    "goal",
    "player",
    "development_profile",
    "review",
    "background_job",
}
_ALLOWED_EVIDENCE_VISIBILITIES = {"private", "team", "player", "unlisted", "public"}
_ALLOWED_EVIDENCE_STATUSES = {"included", "excluded", "redacted", "unavailable"}
_ALLOWED_EVIDENCE_REASONS = {
    "selected_by_coach",
    "linked_to_target",
    "team_visible",
    "visibility_excluded",
    "not_found",
    "redacted_private",
}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PRIVATE_PAYLOAD_MARKERS = (
    "raw_prompt",
    "prompt:",
    "provider_output",
    "private_source_text",
    "coach_private_note",
    "private_phase8_raw_prompt_canary",
)


@dataclass
class AIDraftingValidationError(ValueError):
    code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:  # pragma: no cover - human convenience
        return self.detail


@dataclass
class AIDraftingAuthorizationError(PermissionError):
    detail: str
    status_code: int = 403

    def __str__(self) -> str:  # pragma: no cover
        return self.detail


@dataclass
class AIDraftingNotFoundError(LookupError):
    detail: str
    status_code: int = 404

    def __str__(self) -> str:  # pragma: no cover
        return self.detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor_id(actor_user: dict[str, Any] | None) -> str:
    if not actor_user:
        return ""
    return str(actor_user.get("id") or actor_user.get("user_id") or actor_user.get("username") or "")


def _is_global_admin(actor_user: dict[str, Any] | None) -> bool:
    roles = {part.strip().lower() for part in str((actor_user or {}).get("role") or "").split(",") if part.strip()}
    return "admin" in roles


def _require_team_scope(
    conn: sqlite3.Connection,
    team_id: str,
    actor_user: dict[str, Any] | None,
    *,
    capability: str,
) -> None:
    if not isinstance(team_id, str) or not team_id:
        raise AIDraftingValidationError("invalid_team_id", "team_id is required")
    row = conn.execute("SELECT id FROM teams WHERE id = ?", (team_id,)).fetchone()
    if row is None:
        raise AIDraftingNotFoundError("Team not found")
    if _is_global_admin(actor_user):
        return
    user_id = _actor_id(actor_user)
    if not user_id:
        raise AIDraftingAuthorizationError("Team membership is required")
    rows = conn.execute(
        "SELECT role FROM team_user_memberships WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    ).fetchall()
    if not any(role_has_capability(row["role"], capability) for row in rows):
        raise AIDraftingAuthorizationError("Team membership is required")


def _validate_short_string(name: str, value: str | None, *, required: bool = True, max_length: int = 120) -> str | None:
    if value is None:
        if required:
            raise AIDraftingValidationError(f"invalid_{name}", f"{name} is required")
        return None
    if not isinstance(value, str) or not value.strip():
        if required:
            raise AIDraftingValidationError(f"invalid_{name}", f"{name} is required")
        return None
    value = value.strip()
    if len(value) > max_length:
        raise AIDraftingValidationError(f"{name}_too_long", f"{name} is too long")
    return value


def _validate_draft_target(draft_target: str) -> str:
    target = _validate_short_string("draft_target", draft_target)
    if target in PERMANENTLY_EXCLUDED_DRAFT_TARGETS or target not in AI_DRAFT_TARGETS:
        raise AIDraftingValidationError("unsupported_draft_target", "Unsupported AI draft target")
    return target


def _contains_private_payload_marker(value: str | None) -> bool:
    text = (value or "").lower()
    return any(marker in text for marker in _PRIVATE_PAYLOAD_MARKERS)


def _safe_evidence_value(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        raise AIDraftingValidationError("invalid_evidence_ref", "Evidence reference values must be strings")
    text = str(value).strip()
    if not text or _contains_private_payload_marker(text):
        return None
    if key == "type":
        return text if text in _ALLOWED_EVIDENCE_TYPES else None
    if key == "id":
        return text if _SAFE_ID_RE.fullmatch(text) else None
    if key == "visibility":
        return text if text in _ALLOWED_EVIDENCE_VISIBILITIES else None
    if key == "status":
        return text if text in _ALLOWED_EVIDENCE_STATUSES else None
    if key == "reason":
        return text if text in _ALLOWED_EVIDENCE_REASONS else None
    return None


def _safe_error_message(error_message: str) -> str:
    message = _validate_short_string("error_message", error_message, max_length=500) or "AI drafting run failed"
    if _contains_private_payload_marker(message):
        return "AI drafting run failed"
    return message


def _safe_metadata_string(name: str, value: str, *, fallback: str = "unknown", max_length: int = 120) -> str:
    text = _validate_short_string(name, value, max_length=max_length) or fallback
    if _contains_private_payload_marker(text):
        return fallback
    return text


def sanitize_evidence_refs(evidence_refs: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Return compact, bounded refs while dropping raw/private text fields.

    Allowed keys deliberately exclude prompt/body/content/output/private fields.
    Values are coerced to short strings and empty values are omitted.
    """
    if evidence_refs is None:
        return []
    if not isinstance(evidence_refs, list):
        raise AIDraftingValidationError("invalid_evidence_refs", "evidence_refs must be a list")
    if len(evidence_refs) > MAX_EVIDENCE_REFS:
        raise AIDraftingValidationError("too_many_evidence_refs", "Too many evidence references")
    sanitized: list[dict[str, str]] = []
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            raise AIDraftingValidationError("invalid_evidence_ref", "Evidence references must be objects")
        clean: dict[str, str] = {}
        for key in _ALLOWED_EVIDENCE_KEYS:
            safe_value = _safe_evidence_value(key, ref.get(key))
            if safe_value is not None:
                clean[key] = safe_value
        if clean.get("type") and clean.get("id"):
            sanitized.append(clean)
    return sanitized


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AIDraftingValidationError("invalid_json", "AI drafting run metadata must be JSON serializable") from exc


def _row_to_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        evidence_refs = json.loads(row["evidence_refs_json"] or "[]")
    except json.JSONDecodeError:
        evidence_refs = []
    return {
        "id": row["id"],
        "team_id": row["team_id"],
        "season_id": row["season_id"],
        "created_by_user_id": row["created_by_user_id"],
        "draft_target": row["draft_target"],
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [],
        "background_job_id": row["background_job_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
    }


def _select_run(conn: sqlite3.Connection, run_id: int, team_id: str | None = None) -> dict[str, Any]:
    if team_id is None:
        row = conn.execute("SELECT * FROM ai_drafting_runs WHERE id = ?", (run_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM ai_drafting_runs WHERE id = ? AND team_id = ?", (run_id, team_id)).fetchone()
    run = _row_to_run(row)
    if run is None:
        raise AIDraftingNotFoundError("AI drafting run not found")
    return run


def create_run(
    *,
    team_id: str,
    draft_target: str,
    provider: str,
    model: str,
    season_id: str | None = None,
    created_by_user_id: str | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    background_job_id: int | None = None,
    actor_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _validate_draft_target(draft_target)
    provider = _safe_metadata_string("provider", provider)
    model = _safe_metadata_string("model", model)
    season_id = _validate_short_string("season_id", season_id, required=False, max_length=80)
    created_by_user_id = _validate_short_string("created_by_user_id", created_by_user_id, required=False, max_length=80)
    refs = sanitize_evidence_refs(evidence_refs)
    now = _now_iso()
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:write")
        if season_id:
            season = conn.execute("SELECT id FROM seasons WHERE id = ? AND team_id = ?", (season_id, team_id)).fetchone()
            if season is None:
                raise AIDraftingValidationError("invalid_season", "season_id must belong to the run team")
        cur = conn.execute(
            """
            INSERT INTO ai_drafting_runs (
                team_id, season_id, created_by_user_id, draft_target, provider, model, status,
                evidence_refs_json, background_job_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (team_id, season_id, created_by_user_id, target, provider, model, _json_dumps(refs), background_job_id, now, now),
        )
        conn.commit()
        return _select_run(conn, int(cur.lastrowid), team_id)


def get_run(run_id: int, *, team_id: str, actor_user: dict[str, Any] | None = None) -> dict[str, Any]:
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:read")
        return _select_run(conn, int(run_id), team_id)


def list_runs(
    team_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
    actor_user: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if status is not None and status not in RUN_STATUSES:
        raise AIDraftingValidationError("invalid_status", "Unsupported AI drafting run status")
    limit = max(1, min(int(limit), 100))
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:read")
        if status:
            rows = conn.execute(
                """
                SELECT * FROM ai_drafting_runs
                WHERE team_id = ? AND status = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (team_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM ai_drafting_runs
                WHERE team_id = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (team_id, limit),
            ).fetchall()
        return [_row_to_run(row) for row in rows if row is not None]


def start_run(run_id: int, *, team_id: str, actor_user: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _now_iso()
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:edit")
        cur = conn.execute(
            """
            UPDATE ai_drafting_runs
            SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ? AND team_id = ? AND status IN ('queued', 'running')
            """,
            (now, now, int(run_id), team_id),
        )
        if cur.rowcount == 0:
            _select_run(conn, int(run_id), team_id)
            raise AIDraftingValidationError("invalid_status_transition", "AI drafting run cannot be started")
        conn.commit()
        return _select_run(conn, int(run_id), team_id)


def succeed_run(
    run_id: int,
    *,
    team_id: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    actor_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:edit")
        cur = conn.execute(
            """
            UPDATE ai_drafting_runs
            SET status = 'succeeded', input_tokens = ?, output_tokens = ?, error_code = NULL,
                error_message = NULL, finished_at = ?, updated_at = ?
            WHERE id = ? AND team_id = ? AND status IN ('queued', 'running')
            """,
            (input_tokens, output_tokens, now, now, int(run_id), team_id),
        )
        if cur.rowcount == 0:
            _select_run(conn, int(run_id), team_id)
            raise AIDraftingValidationError("invalid_status_transition", "AI drafting run cannot be succeeded")
        conn.commit()
        return _select_run(conn, int(run_id), team_id)


def fail_run(
    run_id: int,
    *,
    team_id: str,
    error_code: str,
    error_message: str,
    actor_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = _safe_metadata_string("error_code", error_code, fallback="privacy_sanitized", max_length=80)
    message = _safe_error_message(error_message)
    now = _now_iso()
    with _db.connect() as conn:
        _require_team_scope(conn, team_id, actor_user, capability="coach_object:edit")
        cur = conn.execute(
            """
            UPDATE ai_drafting_runs
            SET status = 'failed', error_code = ?, error_message = ?, finished_at = ?, updated_at = ?
            WHERE id = ? AND team_id = ? AND status IN ('queued', 'running')
            """,
            (code, message, now, now, int(run_id), team_id),
        )
        if cur.rowcount == 0:
            _select_run(conn, int(run_id), team_id)
            raise AIDraftingValidationError("invalid_status_transition", "AI drafting run cannot be failed")
        conn.commit()
        return _select_run(conn, int(run_id), team_id)
