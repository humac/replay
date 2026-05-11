"""Privacy-safe AI context builder for Replay coaching sources.

Phase 8.2 is service-only: it gathers compact, provider-ready context from
team-scoped coaching objects, applies the same visibility governance used for AI
drafting settings, and returns audit metadata without storing/logging prompts or
private source text.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

import db as _db
from services import engagement as _engagement
from services import visibility as _visibility
from services.team_settings import can_generate_draft, list_settings


SUPPORTED_EVIDENCE_TYPES = {"note", "clip", "playlist", "goal", "match_summary", "player", "development_profile", "review", "engagement"}
_NUMERIC_REF_TYPES = {"note", "clip", "playlist", "goal", "match_summary", "review"}
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_EVIDENCE_REFS = 50


@dataclass
class AIContextValidationError(ValueError):
    code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.detail


def _safe_token(value: Any, *, fallback: str = "redacted") -> str:
    text = str(value or "").strip()
    return text if _SAFE_REF_RE.fullmatch(text) else fallback


def _safe_ref(ref_type: str, ref_id: Any, *, reason: str, status: str = "excluded") -> dict[str, str]:
    return {"type": _safe_token(ref_type, fallback="unknown"), "id": _safe_token(ref_id), "status": status, "reason": reason}


def _included_ref(ref_type: str, ref_id: Any) -> dict[str, str]:
    return {"type": _safe_token(ref_type, fallback="unknown"), "id": _safe_token(ref_id), "status": "included", "reason": "selected_by_coach"}


def _empty_audit() -> dict[str, list[dict[str, str]]]:
    return {
        "included": [],
        "excluded_by_visibility": [],
        "excluded_by_cross_team_scope": [],
        "excluded_by_permanent_policy": [],
        # Back-compat/future-test friendly alias for policy exclusions.
        "excluded_by_policy": [],
    }


def _add_policy_exclusion(audit: dict[str, list[dict[str, str]]], entry: dict[str, str]) -> None:
    audit["excluded_by_permanent_policy"].append(entry)
    audit["excluded_by_policy"].append(entry)


def _normalize_refs(evidence_refs: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if evidence_refs is None:
        return []
    if not isinstance(evidence_refs, list):
        raise AIContextValidationError("invalid_evidence_refs", "evidence_refs must be a list")
    normalized: list[dict[str, str]] = []
    for ref in evidence_refs[:_MAX_EVIDENCE_REFS]:
        if not isinstance(ref, dict):
            raise AIContextValidationError("invalid_evidence_ref", "Evidence refs must be objects")
        ref_type = str(ref.get("type") or "").strip()
        ref_id = ref.get("id")
        if ref_type not in SUPPORTED_EVIDENCE_TYPES:
            normalized.append({"type": "unknown", "id": "redacted", "invalid": "unsupported_ref"})
            continue
        if ref_id in (None, ""):
            normalized.append({"type": ref_type, "id": "redacted", "invalid": "invalid_ref_id"})
            continue
        text_id = str(ref_id).strip()
        if not _SAFE_REF_RE.fullmatch(text_id):
            normalized.append({"type": ref_type, "id": "redacted", "invalid": "invalid_ref_id"})
            continue
        if ref_type in _NUMERIC_REF_TYPES and not text_id.isdigit():
            normalized.append({"type": ref_type, "id": "redacted", "invalid": "invalid_ref_id"})
            continue
        normalized.append({"type": ref_type, "id": text_id})
    return normalized


def _team_visible_item(
    *,
    item: dict | None,
    team_id: str,
    actor_user: dict[str, Any],
    filter_fn: Callable[[list[dict], dict[str, Any], str | None], list[dict]],
) -> tuple[dict | None, str | None]:
    if not item:
        return None, "not_found"
    if not _visibility.same_team(item, team_id):
        return None, "cross_team_scope"
    visible = filter_fn([item], actor_user, team_id)
    if not visible:
        return None, "visibility_denied"
    return visible[0], None


def _source_visibility_allowed(item: dict, never_draft_visibilities: set[str]) -> bool:
    visibility = item.get("visibility")
    return visibility not in never_draft_visibilities


def _safe_note(note: dict) -> dict[str, Any]:
    return {
        "type": "note",
        "id": str(note["id"]),
        "visibility": note.get("visibility", "private"),
        "title": note.get("title", ""),
        "category": note.get("category", ""),
        "note_type": note.get("note_type", ""),
        "player_ids": [str(pid) for pid in note.get("player_ids", [])],
        "tags": list(note.get("tags", [])),
        "match_id": note.get("match_id"),
        "slot": note.get("slot"),
        "timestamp_seconds": note.get("timestamp_seconds"),
        "summary": note.get("player_summary") or note.get("what_happened") or note.get("body", ""),
        "what_happened": note.get("what_happened", ""),
        "why_it_matters": note.get("why_it_matters", ""),
        "what_to_do_next": note.get("what_to_do_next", ""),
    }


def _safe_clip(clip: dict) -> dict[str, Any]:
    return {
        "type": "clip",
        "id": str(clip["id"]),
        "visibility": clip.get("visibility", "private"),
        "title": clip.get("title", ""),
        "description": clip.get("description", ""),
        "category": clip.get("category", ""),
        "player_ids": [str(pid) for pid in clip.get("player_ids", [])],
        "match_id": clip.get("match_id"),
        "slot": clip.get("slot"),
        "start_seconds": clip.get("start_seconds"),
        "end_seconds": clip.get("end_seconds"),
        "source_note_id": clip.get("source_note_id"),
    }


def _safe_playlist(playlist: dict) -> dict[str, Any]:
    return {
        "type": "playlist",
        "id": str(playlist["id"]),
        "visibility": playlist.get("visibility", "private"),
        "title": playlist.get("title", ""),
        # Intentionally omit playlist descriptions in the MVP.
        "note_ids": [str(nid) for nid in playlist.get("note_ids", [])],
        "player_ids": [str(pid) for pid in playlist.get("player_ids", [])],
        "pre_roll_seconds": playlist.get("pre_roll_seconds"),
        "post_roll_seconds": playlist.get("post_roll_seconds"),
    }


def _safe_goal(goal: dict) -> dict[str, Any]:
    return {
        "type": "goal",
        "id": str(goal["id"]),
        "visibility": goal.get("visibility", "player"),
        "player_id": str(goal.get("player_id", "")),
        "title": goal.get("title", ""),
        "description": goal.get("description", ""),
        "success_criteria": goal.get("success_criteria", ""),
        "status": goal.get("status", ""),
        "priority": goal.get("priority", ""),
        "source_note_id": goal.get("source_note_id"),
        "source_clip_id": goal.get("source_clip_id"),
        "source_playlist_id": goal.get("source_playlist_id"),
    }


def _safe_summary(summary: dict) -> dict[str, Any]:
    return {
        "type": "match_summary",
        "id": str(summary["id"]),
        "visibility": summary.get("visibility", "private"),
        "match_id": summary.get("match_id"),
        "team_positives": summary.get("team_positives", ""),
        "team_improvements": summary.get("team_improvements", ""),
        "training_focus": summary.get("training_focus", ""),
        "body": summary.get("body", ""),
        "note_ids": [str(nid) for nid in summary.get("note_ids", [])],
        "clip_ids": [str(cid) for cid in summary.get("clip_ids", [])],
        "playlist_ids": [str(pid) for pid in summary.get("playlist_ids", [])],
    }


def _safe_player(player: dict) -> dict[str, Any]:
    return {
        "type": "player",
        "id": str(player["id"]),
        "display_name": player.get("display_name", ""),
        "jersey_number": player.get("jersey_number", ""),
        "active": bool(player.get("active", True)),
        "team_id": player.get("team_id", ""),
    }


def _safe_development_profile(player: dict) -> dict[str, Any]:
    out = _safe_player(player)
    out["type"] = "development_profile"
    return out


def _safe_engagement(payload: dict, ref_id: str) -> dict[str, Any]:
    return {
        "type": "engagement",
        "id": ref_id,
        "summary": payload.get("summary") or {},
        "by_player": payload.get("by_player") or [],
        "by_match": payload.get("by_match") or [],
        "unreviewed_assigned_items": payload.get("unreviewed_assigned_items") or [],
        "players_with_no_recent_feedback": payload.get("players_with_no_recent_feedback") or [],
        "most_watched": payload.get("most_watched") or [],
    }


def _safe_review(review: dict) -> dict[str, Any]:
    return {
        "type": "review",
        "id": str(review["id"]),
        "note_id": review.get("note_id"),
        "playlist_id": review.get("playlist_id"),
        "reviewed_at": review.get("reviewed_at"),
    }


def _player_intersects(item: dict, target_player_ids: set[str]) -> bool:
    if not target_player_ids:
        return True
    if item.get("player_id") is not None:
        return str(item.get("player_id")) in target_player_ids
    item_players = {str(pid) for pid in item.get("player_ids", [])}
    if item_players:
        return bool(item_players.intersection(target_player_ids))
    if item.get("id") is not None and item.get("display_name") is not None:
        return str(item.get("id")) in target_player_ids
    return True



def _exists_unscoped(ref_type: str, ref_id: int) -> bool:
    return _db.coaching_source_exists(ref_type, ref_id)


def _review_scope_item(review: dict, team_id: str) -> dict | None:
    note_id = review.get("note_id")
    if note_id is not None:
        return _db.get_coaching_note(int(note_id), team_id=team_id)
    playlist_id = review.get("playlist_id")
    if playlist_id is not None:
        return _db.get_coaching_playlist(int(playlist_id), team_id=team_id)
    return None


def build_context(
    *,
    team_id: str,
    actor_user: dict[str, Any],
    draft_target: str,
    target_visibility: str,
    evidence_refs: list[dict[str, Any]] | None = None,
    target_player_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build compact AI context and privacy audit metadata.

    The returned object is intentionally structured data rather than a raw
    prompt. Callers in later phases can format it for a provider without this
    service ever storing prompt text.
    """
    if not can_generate_draft(team_id, draft_target, visibility=target_visibility, actor_user=actor_user):
        raise AIContextValidationError("draft_not_allowed", "AI drafting is not allowed for this target and visibility", 403)

    settings = list_settings(team_id, actor_user=actor_user)
    never_draft_visibilities = set(settings["ai.never_draft_for_visibilities"])
    target_players = {str(pid) for pid in (target_player_ids or []) if pid}
    audit = _empty_audit()
    items: list[dict[str, Any]] = []

    for ref in _normalize_refs(evidence_refs):
        ref_type = ref["type"]
        ref_id = ref["id"]
        if ref.get("invalid"):
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason=ref["invalid"]))
            continue
        if ref_type not in SUPPORTED_EVIDENCE_TYPES or not ref_id:
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="unsupported_ref"))
            continue

        item: dict | None = None
        status_reason: str | None = None
        safe_item: dict[str, Any] | None = None
        filter_fn: Callable[[list[dict], dict[str, Any], str | None], list[dict]] | None = None

        if ref_type == "note":
            numeric_id = int(ref_id)
            item = _db.get_coaching_note(numeric_id, team_id=team_id)
            if item is None:
                status_reason = "cross_team_scope" if _exists_unscoped(ref_type, numeric_id) else "not_found"
            filter_fn = _visibility.filter_notes_for_user
            safe_builder = _safe_note
        elif ref_type == "clip":
            numeric_id = int(ref_id)
            item = _db.get_coaching_clip(numeric_id, team_id=team_id)
            if item is None:
                status_reason = "cross_team_scope" if _exists_unscoped(ref_type, numeric_id) else "not_found"
            filter_fn = _visibility.filter_clips_for_user
            safe_builder = _safe_clip
        elif ref_type == "playlist":
            numeric_id = int(ref_id)
            item = _db.get_coaching_playlist(numeric_id, team_id=team_id)
            if item is None:
                status_reason = "cross_team_scope" if _exists_unscoped(ref_type, numeric_id) else "not_found"
            filter_fn = _visibility.filter_playlists_for_user
            safe_builder = _safe_playlist
        elif ref_type == "goal":
            numeric_id = int(ref_id)
            item = _db.get_player_goal(numeric_id, team_id=team_id)
            if item is None:
                status_reason = "cross_team_scope" if _exists_unscoped(ref_type, numeric_id) else "not_found"
            filter_fn = _visibility.filter_goals_for_user
            safe_builder = _safe_goal
        elif ref_type == "match_summary":
            numeric_id = int(ref_id)
            item = _db.get_coaching_match_summary(numeric_id, team_id=team_id)
            if item is None:
                status_reason = "cross_team_scope" if _exists_unscoped(ref_type, numeric_id) else "not_found"
            filter_fn = _visibility.filter_match_summaries_for_user
            safe_builder = _safe_summary
        elif ref_type in {"player", "development_profile"}:
            item = _db.get_player(ref_id, team_id=team_id)
            if item is None:
                # Determine whether it exists elsewhere without exposing content.
                status_reason = "cross_team_scope" if _db.player_exists(ref_id) else "not_found"
            filter_fn = None
            safe_builder = _safe_development_profile if ref_type == "development_profile" else _safe_player
        elif ref_type == "review":
            numeric_id = int(ref_id)
            review = _db.get_coaching_review_for_ai_context(numeric_id, team_id)
            if review is None:
                status_reason = "not_found"
            else:
                source_item = _review_scope_item(review, team_id)
                if source_item is None:
                    status_reason = "cross_team_scope"
                elif source_item.get("visibility") == "private":
                    status_reason = "private_source_excluded"
                else:
                    # Apply the source item's draft visibility and player scope to
                    # review metadata before including the compact review row.
                    item = {
                        **review,
                        "visibility": source_item.get("visibility"),
                        "player_id": source_item.get("player_id"),
                        "player_ids": source_item.get("player_ids", []),
                    }
            filter_fn = None
            safe_builder = _safe_review
        elif ref_type == "engagement":
            if target_players:
                _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="target_player_scope_required"))
                continue
            item = _engagement.build_coach_engagement_dashboard(team_id=team_id)
            safe_item = _safe_engagement(item, ref_id)
            items.append(safe_item)
            audit["included"].append(_included_ref(ref_type, ref_id))
            continue
        else:
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="unsupported_ref"))
            continue

        if status_reason is None and ref_type not in {"player", "development_profile", "review"}:
            item, status_reason = _team_visible_item(
                item=item,
                team_id=team_id,
                actor_user=actor_user,
                filter_fn=filter_fn,  # type: ignore[arg-type]
            )

        if status_reason == "cross_team_scope":
            audit["excluded_by_cross_team_scope"].append(_safe_ref(ref_type, ref_id, reason="cross_team_scope"))
            continue
        if status_reason == "private_source_excluded":
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="private_source_excluded"))
            continue
        if status_reason == "visibility_denied":
            audit["excluded_by_visibility"].append(_safe_ref(ref_type, ref_id, reason="visibility_denied"))
            continue
        if status_reason == "not_found" or item is None:
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="not_found"))
            continue

        if ref_type == "note" and item.get("visibility") == "private":
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="private_source_excluded"))
            continue

        if not _source_visibility_allowed(item, never_draft_visibilities):
            audit["excluded_by_visibility"].append(_safe_ref(ref_type, ref_id, reason="visibility_excluded"))
            continue

        if not _player_intersects(item, target_players):
            _add_policy_exclusion(audit, _safe_ref(ref_type, ref_id, reason="unlinked_player"))
            continue

        safe_item = safe_builder(item)
        items.append(safe_item)
        audit["included"].append(_included_ref(ref_type, ref_id))

    return {
        "context": {
            "team_id": team_id,
            "draft_target": draft_target,
            "target_visibility": target_visibility,
            "items": items,
        },
        "audit": audit,
    }
