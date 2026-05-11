"""Coach AI drafting API routes for Phase 8.4."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import db as _db
import tenancy as _tenancy
from models import CoachAIDraftRequest
from services import ai_providers as _ai_providers
from services import team_settings as _team_settings

router = APIRouter(prefix="/api/coach/ai", tags=["coach-ai"])

_MAX_SYNC_PROMPT_CHARS = 4000
_RESOURCE_TYPES_WITH_VISIBILITY = {"note", "clip", "playlist", "goal", "match_summary"}
_EVIDENCE_TYPES_WITH_SCOPE = {"note", "clip", "playlist", "goal", "match_summary", "player", "development_profile", "review"}
_ALLOWED_AI_DRAFT_ROLES = {"coach", "team_admin"}


def _detail(error_code: str, error_message: str) -> dict[str, str]:
    return {"error_code": error_code, "error_message": error_message}


def _normalize_type(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")


def _safe_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get_resource(resource_type: str, resource_id: Any, team_id: str) -> dict | None:
    ref_id = _safe_id(resource_id)
    if not ref_id:
        return None
    try:
        if resource_type == "note":
            return _db.get_coaching_note(int(ref_id), team_id=team_id)
        if resource_type == "clip":
            return _db.get_coaching_clip(int(ref_id), team_id=team_id)
        if resource_type == "playlist":
            return _db.get_coaching_playlist(int(ref_id), team_id=team_id)
        if resource_type == "goal":
            return _db.get_player_goal(int(ref_id), team_id=team_id)
        if resource_type == "match_summary":
            return _db.get_coaching_match_summary(int(ref_id), team_id=team_id)
        if resource_type in {"player", "development_profile"}:
            return _db.get_player(ref_id, team_id=team_id)
        if resource_type == "review":
            return _db.get_coaching_review_for_ai_context(int(ref_id), team_id)
    except (TypeError, ValueError):
        return None
    return None



def _derive_target_visibility(payload: CoachAIDraftRequest, team_id: str) -> tuple[str, dict | None]:
    resource_type = _normalize_type(payload.target_resource_type)
    client_visibility = payload.target_visibility or payload.proposed_visibility
    if resource_type in _RESOURCE_TYPES_WITH_VISIBILITY:
        item = _get_resource(resource_type, payload.target_resource_id, team_id)
        if item is None:
            raise HTTPException(404, _detail("target_resource_unavailable", "Target resource is not available in this team scope"))
        derived = str(item.get("visibility") or "").strip()
        if client_visibility and client_visibility != derived:
            raise HTTPException(409, _detail("target_visibility_mismatch", "Target visibility does not match the server-derived resource visibility"))
        return derived, item
    if resource_type in {"player", "development_profile"}:
        if payload.target_resource_id is not None:
            item = _get_resource(resource_type, payload.target_resource_id, team_id)
            if item is None:
                raise HTTPException(404, _detail("target_resource_unavailable", "Target resource is not available in this team scope"))
        else:
            item = None
        if not client_visibility:
            raise HTTPException(422, _detail("target_visibility_required", "target_visibility is required for this draft target"))
        return client_visibility, item
    raise HTTPException(422, _detail("unsupported_target_resource_type", "Unsupported target_resource_type"))


def _reject_cross_team_evidence(evidence_refs: list[dict[str, Any]], team_id: str) -> None:
    for ref in evidence_refs or []:
        if not isinstance(ref, dict):
            continue
        ref_type = _normalize_type(str(ref.get("type") or ""))
        if ref_type not in _EVIDENCE_TYPES_WITH_SCOPE:
            continue
        ref_id = ref.get("id")
        if _get_resource(ref_type, ref_id, team_id) is None:
            raise HTTPException(403, _detail("resource_reference_unavailable", "Evidence reference is not available in this team scope"))


def _status_for_provider_failure(error_code: str | None) -> int:
    if error_code in {"drafting_disabled", "context_error"}:
        return 403
    if error_code in {"provider_not_configured", "provider_secret_missing", "provider_unsupported"}:
        return 503
    return 502


@router.post("/draft")
def draft(payload: CoachAIDraftRequest, request: Request):
    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=payload.team_id,
        season_id=payload.season_id,
        require_role="viewer",
        allow_global_admin_override=False,
    )
    if _tenancy.normalize_team_role(scope.effective_role) not in _ALLOWED_AI_DRAFT_ROLES:
        raise HTTPException(403, _detail("coach_access_required", "AI drafting requires coach access"))
    team_id = scope.team["id"]

    prompt = payload.coach_prompt or ""
    if len(prompt) > _MAX_SYNC_PROMPT_CHARS:
        # Existing durable job payloads would require storing the raw prompt to
        # process later. Fail safely until a privacy-preserving enqueue path is added.
        raise HTTPException(413, _detail("prompt_too_long", "Coach prompt is too long for synchronous drafting"))

    target_visibility, target_item = _derive_target_visibility(payload, team_id)
    if not _team_settings.can_generate_draft(team_id, payload.draft_target, visibility=target_visibility, actor_user=user):
        raise HTTPException(403, _detail("drafting_disabled", "AI drafting is not enabled for this target and visibility"))
    _reject_cross_team_evidence(payload.evidence_refs, team_id)

    target_player_ids = list(payload.target_player_ids)
    if not target_player_ids and target_item:
        if target_item.get("player_id") is not None:
            target_player_ids = [str(target_item["player_id"])]
        elif target_item.get("player_ids"):
            target_player_ids = [str(pid) for pid in target_item.get("player_ids") or []]
        elif _normalize_type(payload.target_resource_type) in {"player", "development_profile"} and target_item.get("id") is not None:
            target_player_ids = [str(target_item["id"])]

    result = _ai_providers.generate_draft(
        team_id=team_id,
        actor_user=user,
        draft_target=payload.draft_target,
        target_visibility=target_visibility,
        evidence_refs=payload.evidence_refs,
        target_player_ids=target_player_ids,
        instruction=prompt or None,
    )
    if not result.get("ok"):
        raise HTTPException(_status_for_provider_failure(result.get("error_code")), _detail(result.get("error_code") or "draft_failed", result.get("error_message") or "AI drafting failed"))
    return {
        "ok": True,
        "text": result.get("text") or "",
        "run": result.get("run"),
        "target_visibility": target_visibility,
    }
