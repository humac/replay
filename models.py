"""Pydantic request models for the Replay API."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class UpdateActiveScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(..., min_length=1, max_length=200)
    season_id: str = Field(..., min_length=1, max_length=200)

    @field_validator("team_id", "season_id")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("scope selector is required")
        return cleaned


class PatchMeProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Optional[str] = Field(None, max_length=320)
    first_name: Optional[str] = Field(None, max_length=120)
    last_name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=64)
    timezone: Optional[str] = Field(None, max_length=120)
    locale: Optional[str] = Field(None, max_length=32)
    preferred_contact_method: Optional[Literal["email", "phone", "none"]] = None

    @field_validator("email", "first_name", "last_name", "phone", "timezone", "locale")
    @classmethod
    def strip_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class EnqueueJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(..., min_length=1, max_length=200)
    kind: Literal["ai_draft", "thumbnail", "transcode"]
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(None, max_length=500)
    scheduled_at: Optional[str] = Field(None, max_length=64)
    max_attempts: int = Field(3, ge=1, le=25)
    payload_version: int = Field(1, ge=1)

    @field_validator("team_id")
    @classmethod
    def strip_required_team_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("team_id is required")
        return cleaned

    @field_validator("idempotency_key", "scheduled_at")
    @classmethod
    def strip_optional_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = v.strip()
        return cleaned or None


class PatchTeamSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: dict[str, Any] = Field(default_factory=dict)


class CoachAIDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: Optional[str] = Field(None, min_length=1, max_length=200)
    season_id: Optional[str] = Field(None, min_length=1, max_length=200)
    draft_target: str = Field(..., min_length=1, max_length=120)
    target_resource_type: str = Field(..., min_length=1, max_length=80)
    target_resource_id: Optional[str | int] = None
    target_visibility: Optional[str] = Field(None, max_length=32)
    proposed_visibility: Optional[str] = Field(None, max_length=32)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    target_player_ids: list[str] = Field(default_factory=list, max_length=50)
    coach_prompt: Optional[str] = Field(None, max_length=10000)

    @field_validator("team_id", "season_id", "draft_target", "target_resource_type", "target_visibility", "proposed_visibility", "coach_prompt")
    @classmethod
    def strip_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None

    @field_validator("target_player_ids")
    @classmethod
    def strip_player_ids(cls, v: list[str]) -> list[str]:
        return [str(item).strip() for item in v if str(item).strip()]


class CreateAdminTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=64)
    game_format: str = Field("full", min_length=1, max_length=32)

    @field_validator("name", "slug", "game_format")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class UpdateAdminTeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    game_format: Optional[str] = Field(None, min_length=1, max_length=32)

    @field_validator("name", "game_format")
    @classmethod
    def strip_optional_whitespace(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class CreateAdminSeasonRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    starts_on: str = Field("", max_length=10)
    ends_on: str = Field("", max_length=10)

    @field_validator("name", "starts_on", "ends_on")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("starts_on", "ends_on")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if v and not _DATE_RE.match(v):
            raise ValueError("date must be empty or YYYY-MM-DD")
        return v


class CreateAdminMembershipRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=200)
    role: str = Field(..., min_length=1, max_length=64)

    @field_validator("user_id", "role")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class CreateMatchRequest(BaseModel):
    home_team: str = Field(..., min_length=1, max_length=200)
    away_team: str = Field(..., min_length=1, max_length=200)
    date: str = Field("", max_length=10)
    time: str = Field("", max_length=5)
    location: str = Field("", max_length=500)
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    format: Literal["full", "two_halves"] = "full"

    @field_validator("home_team", "away_team")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        v = v.strip()
        if v and not _DATE_RE.match(v):
            raise ValueError("date must be empty or YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        v = v.strip()
        if v and not _TIME_RE.match(v):
            raise ValueError("time must be empty or HH:MM")
        return v


class UpdateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_team: Optional[str] = Field(None, min_length=1, max_length=200)
    away_team: Optional[str] = Field(None, min_length=1, max_length=200)
    date: Optional[str] = Field(None, max_length=10)
    time: Optional[str] = Field(None, max_length=5)
    location: Optional[str] = Field(None, max_length=500)
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    format: Optional[Literal["full", "two_halves"]] = None

    @field_validator("home_team", "away_team")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and not _DATE_RE.match(v):
            raise ValueError("date must be empty or YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and not _TIME_RE.match(v):
            raise ValueError("time must be empty or HH:MM")
        return v


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CreateUploadSessionRequest(BaseModel):
    filename: str = Field("video.mp4", min_length=1, max_length=500)
    size_bytes: int = Field(..., gt=0)
    first_chunk_hash: Optional[str] = Field(None, max_length=64)

    @field_validator("first_chunk_hash")
    @classmethod
    def validate_hash(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256_RE.match(v):
            raise ValueError("first_chunk_hash must be a 64-char lowercase hex SHA-256")
        return v


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VALID_ROLES = {"admin", "coach", "uploader", "viewer"}


def _normalize_role_string(value: str) -> str:
    roles = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not roles:
        raise ValueError("role must include at least one role")
    unknown = [role for role in roles if role not in _VALID_ROLES]
    if unknown:
        raise ValueError(f"role must contain only: {', '.join(sorted(_VALID_ROLES))}")
    # Keep a stable order for storage and client comparisons.
    ordered = [role for role in ("admin", "coach", "uploader", "viewer") if role in roles]
    return ",".join(ordered)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=8, max_length=200)
    role: str = Field("viewer")
    display_name: str = Field("", max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not _USERNAME_RE.match(v):
            raise ValueError("username may only contain letters, digits, underscores, dots, and hyphens")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        return _normalize_role_string(v)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: Optional[str] = Field(None, min_length=8, max_length=200)
    role: Optional[str] = None
    display_name: Optional[str] = Field(None, max_length=100)
    enabled: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        return _normalize_role_string(v) if v is not None else v


_VALID_PLAYER_RELATIONSHIPS = {"self", "parent", "guardian", "family"}
_VALID_NOTE_CATEGORIES = {
    "shape", "pressing", "transition", "set_piece", "build_up", "finishing",
    "defending", "goalkeeper", "effort", "decision", "other",
}
_VALID_COACHING_VISIBILITY = {"private", "team", "player", "unlisted"}
_VALID_SLOTS = {"full", "first_half", "second_half"}
# Phase 1 structured-note tone (see docs/coaching-analysis-feature-roadmap.md).
# `correction` is the legacy implied default — every existing pre-v9 note
# round-trips as a correction unless explicitly re-tagged.
_VALID_NOTE_TYPES = {"positive", "correction", "question", "team_concept", "individual_goal"}
# Phase 6a — observation notes. `note_context` discriminates between
# the existing video-anchored notes (the only kind before Phase 6) and
# the new non-video observation notes (practice / game / meeting /
# tactical / other).
_VALID_NOTE_CONTEXTS = {"video", "observation"}
_VALID_EVENT_TYPES = {"practice", "game", "meeting", "tactical", "other"}
# tactical_board_json is opaque-ish JSON metadata. Cap the serialized
# size so a corrupted client cannot stuff multi-megabyte boards into
# the row. The board format will firm up in Phase 6c (tactical board
# editor); the backend just stores whatever shape the editor saves
# alongside a `pitch_kind` discriminator.
_MAX_TACTICAL_BOARD_JSON_BYTES = 100_000
# Phase 6c — tactical board scene schema. The board surface is a
# structured scene (NOT a raster image). The MVP only ships soccer
# full-pitch, but every callsite that special-cases pitch_kind goes
# through `_VALID_PITCH_KINDS` so a future sport (futsal, 7-a-side,
# basketball, hockey) can be added by extending the set + the SVG
# pitch renderer — no schema migration needed.
_VALID_PITCH_KINDS = {"soccer_full"}
_VALID_BOARD_ORIENTATIONS = {"landscape"}
_VALID_BOARD_TOKEN_KINDS = {"player", "ball"}
_VALID_BOARD_SHAPE_KINDS = {"arrow", "line", "zone", "label", "freehand"}
_MAX_BOARD_TOKENS = 40
_MAX_BOARD_SHAPES = 40
_MAX_BOARD_LABEL_LENGTH = 80
# Phase 6d-1 — freehand stroke point cap. Mirrors the JS `MAX_FREEHAND_POINTS`
# in js/tactical-board.js. Higher than a typical drawn stroke needs but
# bounded so a corrupted client cannot stuff thousands of points into a
# single shape.
_MAX_BOARD_FREEHAND_POINTS = 200
# Phase 6d-2 color parity follow-up — closed palette accepted on per-
# shape `color` fields. Mirrors the video telestrator palette in
# `js/coaching.js renderCoachTelestratorToolbar` exactly so a coach who
# learned the video swatches sees identical hex values in tactical mode.
# The legacy `#fde047` (pre-color-controls default) is also accepted so
# old boards saved with a color value round-trip unchanged. Stored
# values are lowercased; a non-string / off-palette / null value is
# treated as ABSENT (the field is dropped from the normalized payload)
# rather than rejected, so a corrupted client cannot 422 a board that
# has a stray field. Adding any kind of permissive parser here would
# allow `javascript:` style strings to leak into `<svg fill="…">`, so
# the closed-set check stays.
_VALID_BOARD_COLORS = {
    "#38bdf8", "#f97316", "#22c55e", "#facc15",
    "#f43f5e", "#ffffff", "#fde047",
}
# Phase 6d-2 thickness parity follow-up — bounded stroke-width range
# mirrors the video telestrator slider (`<input type="range" min="2"
# max="10" value="3">` in `js/coaching.js renderCoachTelestratorToolbar`)
# AND the JS-side BOARD_STROKE_WIDTH_MIN / BOARD_STROKE_WIDTH_MAX in
# `js/tactical-board.js`. Out-of-range / non-numeric values are silently
# dropped (treated as ABSENT) rather than rejected — same defense-in-
# depth pattern as `_normalize_board_color`. The legacy default `3` is
# also accepted for round-trip symmetry.
_BOARD_STROKE_WIDTH_MIN = 2
_BOARD_STROKE_WIDTH_MAX = 10
# Phase 6d-2 — optional game format + formation metadata. Both fields
# are OPTIONAL; old boards saved without them still load and round-trip
# unchanged. The validator stores them only when present so a future
# sport / format can be added without a migration.
_VALID_BOARD_GAME_FORMATS = {"7v7", "9v9", "11v11"}
# Formation labels are coach-facing strings (e.g. "2-3-1", "4-3-3",
# "custom"). We don't enumerate every possible formation here because
# the registry lives in the JS layer (js/tactical-board.js) and a coach
# can save a custom layout with any short label. Capped at 32 chars so
# a corrupted client cannot store a multi-megabyte string.
_MAX_BOARD_FORMATION_LENGTH = 32
# Observation notes still need *some* coaching content, otherwise the
# row carries nothing useful. Any non-empty value in any of these fields
# is enough — same spirit as the structured-fields list (Phase 1) but
# applied at the request boundary so the empty-row case fails with 422
# instead of saving and surfacing as an unreadable empty card later.
_OBSERVATION_CONTENT_FIELDS = (
    "title", "body", "player_summary", "what_happened", "why_it_matters",
    "what_to_do_next", "event_title",
)
_VALID_DRAWING_TYPES = {"freehand", "arrow", "circle", "zone", "label", "spotlight", "dim", "formation"}
_VALID_DRAWING_POINT_KEYS = {"x", "y", "x1", "y1", "x2", "y2", "w", "h", "opacity"}


def _validate_unit_number(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if normalized < 0 or normalized > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return normalized


def _validate_drawing_point(point: Any) -> dict[str, float]:
    if not isinstance(point, dict):
        raise ValueError("drawing points must be objects")
    if "x" not in point or "y" not in point:
        raise ValueError("drawing points require x and y")
    return {
        "x": _validate_unit_number(point["x"], "x"),
        "y": _validate_unit_number(point["y"], "y"),
    }


def validate_drawing_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("drawing must be an object")
    if len(json.dumps(value, separators=(",", ":"))) > 50000:
        raise ValueError("drawing payload is too large")

    version = value.get("version", 1)
    if version == 1:
        strokes = value.get("strokes", [])
        if not isinstance(strokes, list) or len(strokes) > 120:
            raise ValueError("legacy drawing strokes must be a list of 120 or fewer")
        total_points = 0
        for stroke in strokes:
            if not isinstance(stroke, dict):
                raise ValueError("legacy drawing strokes must be objects")
            points = stroke.get("points", [])
            if not isinstance(points, list) or len(points) > 800:
                raise ValueError("legacy drawing strokes must contain 800 or fewer points")
            total_points += len(points)
            if total_points > 4000:
                raise ValueError("drawing has too many points")
            for point in points:
                _validate_drawing_point(point)
        return value

    if version != 2:
        raise ValueError("drawing version must be 1 or 2")

    objects = value.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 120:
        raise ValueError("drawing objects must be a list of 120 or fewer")
    total_points = 0
    for item in objects:
        if not isinstance(item, dict):
            raise ValueError("drawing objects must be objects")
        item_type = str(item.get("type", "")).strip().lower()
        if item_type not in _VALID_DRAWING_TYPES:
            raise ValueError(f"drawing object type must be one of: {', '.join(sorted(_VALID_DRAWING_TYPES))}")
        for key in _VALID_DRAWING_POINT_KEYS.intersection(item):
            _validate_unit_number(item[key], key)
        if item_type == "freehand":
            points = item.get("points", [])
            if not isinstance(points, list) or len(points) > 800:
                raise ValueError("freehand drawing objects require 800 or fewer points")
            total_points += len(points)
            if total_points > 4000:
                raise ValueError("drawing has too many points")
            for point in points:
                _validate_drawing_point(point)
        elif item_type == "arrow":
            for key in ("x1", "y1", "x2", "y2"):
                if key not in item:
                    raise ValueError("arrow drawing objects require x1, y1, x2, and y2")
                _validate_unit_number(item[key], key)
        elif item_type in {"circle", "zone", "spotlight"}:
            for key in ("x", "y", "w", "h"):
                if key not in item:
                    raise ValueError(f"{item_type} drawing objects require x, y, w, and h")
                _validate_unit_number(item[key], key)
        elif item_type == "label":
            for key in ("x", "y"):
                if key not in item:
                    raise ValueError("label drawing objects require x and y")
                _validate_unit_number(item[key], key)
            text = str(item.get("text", "")).strip()
            if not text or len(text) > 40:
                raise ValueError("label drawing text must be 1 to 40 characters")
        elif item_type == "dim" and "opacity" in item:
            _validate_unit_number(item["opacity"], "opacity")
        elif item_type == "formation":
            anchors = item.get("anchors", [])
            if not isinstance(anchors, list) or len(anchors) < 3 or len(anchors) > 16:
                raise ValueError("formation anchors must be a list of 3 to 16 entries")
            for anchor in anchors:
                if not isinstance(anchor, dict):
                    raise ValueError("formation anchor must be an object")
                for key in ("x", "y"):
                    if key not in anchor:
                        raise ValueError("formation anchor requires x and y")
                    _validate_unit_number(anchor[key], key)
                pid = anchor.get("player_id")
                if pid is not None and (not isinstance(pid, str) or len(pid) > 64):
                    raise ValueError("formation anchor player_id must be a short string")
                lab = anchor.get("label")
                if lab is not None and (not isinstance(lab, str) or len(lab) > 8):
                    raise ValueError("formation anchor label must be a short string")
            hull_points = item.get("hull_points", [])
            if not isinstance(hull_points, list) or len(hull_points) < 3 or len(hull_points) > 16:
                raise ValueError("formation hull_points must be a polygon with 3 to 16 entries")
            for point in hull_points:
                _validate_drawing_point(point)
    return value


class CreatePlayerRequest(BaseModel):
    # `notes` is currently overloaded by the Coach > Roster Quick Add UI
    # to also carry the player's Position (e.g. "Forward", "Midfielder")
    # — there is no dedicated `position` column yet. Existing data is
    # safe (the column was never writable from any prior UI), but if a
    # real free-text "notes" field is added later, ship a small
    # migration to extract Position into its own column first.
    # See ROADMAP "Coach > Roster redesign" + AGENTS.md for context.
    display_name: str = Field(..., min_length=1, max_length=120)
    jersey_number: str = Field("", max_length=20)
    active: bool = True
    notes: str = Field("", max_length=1000)

    @field_validator("display_name", "jersey_number", "notes")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class UpdatePlayerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    jersey_number: Optional[str] = Field(None, max_length=20)
    active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("display_name", "jersey_number", "notes")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class CreatePlayerUserLinkRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=80)
    user_id: str = Field(..., min_length=1, max_length=80)
    relationship: str = Field("family")

    @field_validator("relationship")
    @classmethod
    def validate_relationship(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _VALID_PLAYER_RELATIONSHIPS:
            raise ValueError(f"relationship must be one of: {', '.join(sorted(_VALID_PLAYER_RELATIONSHIPS))}")
        return v


def _validate_event_type(v: str) -> str:
    v = v.strip().lower()
    if not v:
        return ""
    if v not in _VALID_EVENT_TYPES:
        raise ValueError(
            f"event_type must be one of: {', '.join(sorted(_VALID_EVENT_TYPES))}"
        )
    return v


def _validate_event_date(v: str) -> str:
    """Phase 6a — accept ISO-date `YYYY-MM-DD` (matches the rest of the
    codebase's date pattern, e.g. `CreateMatchRequest.date`) or empty.
    Anything else is a 422. Kept simple by design; if a future iteration
    needs ISO datetime or timezones this validator gets extended."""
    v = v.strip()
    if not v:
        return ""
    if not _DATE_RE.match(v):
        raise ValueError("event_date must be empty or YYYY-MM-DD")
    return v


def _validate_board_unit(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"tactical_board {field_name} must be a number")
    f = float(value)
    if f < 0 or f > 1:
        raise ValueError(f"tactical_board {field_name} must be between 0 and 1")
    return f


def _validate_board_label(value: Any, field_name: str, *, max_length: int = _MAX_BOARD_LABEL_LENGTH) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"tactical_board {field_name} must be a string")
    s = value.strip()
    if len(s) > max_length:
        raise ValueError(f"tactical_board {field_name} too long (max {max_length})")
    return s


def _validate_board_token(token: Any, index: int) -> dict[str, Any]:
    if not isinstance(token, dict):
        raise ValueError(f"tactical_board tokens[{index}] must be an object")
    kind = token.get("kind")
    if kind not in _VALID_BOARD_TOKEN_KINDS:
        raise ValueError(
            f"tactical_board tokens[{index}].kind must be one of {sorted(_VALID_BOARD_TOKEN_KINDS)}"
        )
    out: dict[str, Any] = {
        "kind": kind,
        "x": _validate_board_unit(token.get("x"), f"tokens[{index}].x"),
        "y": _validate_board_unit(token.get("y"), f"tokens[{index}].y"),
    }
    tid = token.get("id")
    if tid is not None:
        if not isinstance(tid, str) or not tid.strip():
            raise ValueError(f"tactical_board tokens[{index}].id must be a non-empty string")
        if len(tid) > 64:
            raise ValueError(f"tactical_board tokens[{index}].id too long (max 64)")
        out["id"] = tid
    label = token.get("label")
    if label is not None and label != "":
        out["label"] = _validate_board_label(label, f"tokens[{index}].label", max_length=24)
    pid = token.get("player_id")
    if pid is not None:
        if not isinstance(pid, (str, int)) or isinstance(pid, bool):
            raise ValueError(f"tactical_board tokens[{index}].player_id must be a string or integer")
        out["player_id"] = str(pid)[:64]
    return out


def _normalize_board_color(value: Any) -> str | None:
    """Phase 6d-2 color parity follow-up — return the lowercased color
    when it's in the closed palette, else None. None is a defensive
    pass-through (drop the field) rather than a 422 — the validator
    must accept old boards with a stray-but-harmless field. The closed
    set keeps `<svg fill="…">` from receiving e.g. `javascript:` URIs."""
    if value is None or isinstance(value, bool) or not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in _VALID_BOARD_COLORS else None


def _normalize_board_stroke_width(value: Any) -> int | None:
    """Phase 6d-2 thickness parity follow-up — return the rounded int
    when it's inside `[_BOARD_STROKE_WIDTH_MIN, _BOARD_STROKE_WIDTH_MAX]`,
    else None. Same defense-in-depth pattern as `_normalize_board_color`
    — out-of-range / non-numeric / boolean values drop the field rather
    than 422. SVG renderers don't have a code-execution surface here,
    but a runaway value (e.g. `1e308`) could blow up viewer canvases,
    so the bound stays tight."""
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not (_BOARD_STROKE_WIDTH_MIN <= n <= _BOARD_STROKE_WIDTH_MAX):
        return None
    return round(n)


def _validate_board_shape(shape: Any, index: int) -> dict[str, Any]:
    if not isinstance(shape, dict):
        raise ValueError(f"tactical_board shapes[{index}] must be an object")
    kind = shape.get("kind")
    if kind not in _VALID_BOARD_SHAPE_KINDS:
        raise ValueError(
            f"tactical_board shapes[{index}].kind must be one of {sorted(_VALID_BOARD_SHAPE_KINDS)}"
        )
    out: dict[str, Any] = {"kind": kind}
    color = _normalize_board_color(shape.get("color"))
    if color:
        out["color"] = color
    stroke_width = _normalize_board_stroke_width(shape.get("stroke_width"))
    if stroke_width is not None:
        out["stroke_width"] = stroke_width
    sid = shape.get("id")
    if sid is not None:
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError(f"tactical_board shapes[{index}].id must be a non-empty string")
        if len(sid) > 64:
            raise ValueError(f"tactical_board shapes[{index}].id too long (max 64)")
        out["id"] = sid
    if kind in ("arrow", "line"):
        out["x1"] = _validate_board_unit(shape.get("x1"), f"shapes[{index}].x1")
        out["y1"] = _validate_board_unit(shape.get("y1"), f"shapes[{index}].y1")
        out["x2"] = _validate_board_unit(shape.get("x2"), f"shapes[{index}].x2")
        out["y2"] = _validate_board_unit(shape.get("y2"), f"shapes[{index}].y2")
    elif kind == "zone":
        out["x"] = _validate_board_unit(shape.get("x"), f"shapes[{index}].x")
        out["y"] = _validate_board_unit(shape.get("y"), f"shapes[{index}].y")
        w = _validate_board_unit(shape.get("w"), f"shapes[{index}].w")
        h = _validate_board_unit(shape.get("h"), f"shapes[{index}].h")
        if w <= 0 or h <= 0:
            raise ValueError(f"tactical_board shapes[{index}] zone width/height must be > 0")
        if out["x"] + w > 1.0001 or out["y"] + h > 1.0001:
            raise ValueError(f"tactical_board shapes[{index}] zone extends past pitch bounds")
        out["w"] = w
        out["h"] = h
    elif kind == "label":
        out["x"] = _validate_board_unit(shape.get("x"), f"shapes[{index}].x")
        out["y"] = _validate_board_unit(shape.get("y"), f"shapes[{index}].y")
    elif kind == "freehand":
        # Phase 6d-1 — freehand stroke. Stored as a list of points.
        # Single-point and zero-point strokes don't render usefully so
        # we reject them at the boundary; the editor's drag-to-draw
        # short-circuit handles that path client-side too.
        points_raw = shape.get("points", [])
        if not isinstance(points_raw, list):
            raise ValueError(f"tactical_board shapes[{index}] freehand points must be a list")
        if len(points_raw) < 2:
            raise ValueError(f"tactical_board shapes[{index}] freehand requires at least 2 points")
        if len(points_raw) > _MAX_BOARD_FREEHAND_POINTS:
            raise ValueError(
                f"tactical_board shapes[{index}] freehand points exceed max ({_MAX_BOARD_FREEHAND_POINTS})"
            )
        clean_points: list[dict[str, float]] = []
        for p_index, point in enumerate(points_raw):
            if not isinstance(point, dict) or "x" not in point or "y" not in point:
                raise ValueError(
                    f"tactical_board shapes[{index}].points[{p_index}] must have x and y"
                )
            clean_points.append({
                "x": _validate_board_unit(point["x"], f"shapes[{index}].points[{p_index}].x"),
                "y": _validate_board_unit(point["y"], f"shapes[{index}].points[{p_index}].y"),
            })
        out["points"] = clean_points
    text = shape.get("text")
    if text is not None and text != "":
        out["text"] = _validate_board_label(text, f"shapes[{index}].text")
    elif kind == "label":
        # Label shapes need text — otherwise nothing renders.
        raise ValueError(f"tactical_board shapes[{index}] label requires text")
    return out


def validate_tactical_board_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Phase 6c — `tactical_board_json` is a structured soccer-pitch
    scene (NOT a raster image). The MVP only accepts `pitch_kind:
    "soccer_full"` but the validator goes through `_VALID_PITCH_KINDS`
    so future sports can be added without a schema migration.

    Validation behavior:
    - None / missing → stored as NULL.
    - Empty dict → normalized to NULL.
    - Non-dict (list, string, number) → 422.
    - Unknown `pitch_kind` / `orientation` / token-kind / shape-kind → 422.
    - Coordinates outside [0, 1] → 422.
    - Too many tokens / shapes (each capped at 40) → 422.
    - Oversized serialized blob (> ~100 KB) → 422.

    Returns a normalized dict so the on-disk shape is consistent: all
    coordinates float, only known fields preserved per token/shape,
    `version` defaults to 1, `orientation` defaults to 'landscape'.
    Unknown top-level keys are dropped (forward-compat: a future
    client field can land in a later release without crashing on
    older clients reading newer rows).
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("tactical_board_json must be an object")
    if not value:
        return None
    # Cheap raw-input size guard BEFORE per-item validation so a
    # corrupted client cannot force us to walk a multi-megabyte
    # tokens array. Normalization only ever shrinks or near-equals
    # the input (defaults filled, unknown keys dropped, no
    # synthesis of large fields), so the persisted row is bounded
    # too. Keep this BEFORE the structural pass.
    if len(json.dumps(value, separators=(",", ":"))) > _MAX_TACTICAL_BOARD_JSON_BYTES:
        raise ValueError("tactical_board_json payload is too large")

    pitch_kind = value.get("pitch_kind", "soccer_full")
    if pitch_kind not in _VALID_PITCH_KINDS:
        raise ValueError(
            f"tactical_board_json pitch_kind must be one of {sorted(_VALID_PITCH_KINDS)}"
        )
    orientation = value.get("orientation", "landscape") or "landscape"
    if orientation not in _VALID_BOARD_ORIENTATIONS:
        raise ValueError(
            f"tactical_board_json orientation must be one of {sorted(_VALID_BOARD_ORIENTATIONS)}"
        )
    version = value.get("version", 1)
    # Reject booleans explicitly — Python's `isinstance(True, int)`
    # is True and `True == 1`, so without this guard `{"version":
    # true}` would silently normalize to `version: 1`. Mirrors the
    # bool guard in `_validate_board_unit`.
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("tactical_board_json version must be 1")

    # `tokens` / `shapes` may be absent (defaults to []) but if the
    # client sends an explicit non-list value (null, scalar, dict)
    # that's a malformed payload — reject with 422 instead of
    # silently coercing to []. `value.get("tokens", [])` returns
    # the explicit value when present, so a JSON `null` becomes
    # Python `None` and the isinstance check catches it.
    tokens_raw = value["tokens"] if "tokens" in value else []
    if not isinstance(tokens_raw, list):
        raise ValueError("tactical_board_json tokens must be an array")
    if len(tokens_raw) > _MAX_BOARD_TOKENS:
        raise ValueError(f"tactical_board_json tokens exceed max ({_MAX_BOARD_TOKENS})")
    tokens = [_validate_board_token(t, i) for i, t in enumerate(tokens_raw)]

    shapes_raw = value["shapes"] if "shapes" in value else []
    if not isinstance(shapes_raw, list):
        raise ValueError("tactical_board_json shapes must be an array")
    if len(shapes_raw) > _MAX_BOARD_SHAPES:
        raise ValueError(f"tactical_board_json shapes exceed max ({_MAX_BOARD_SHAPES})")
    shapes = [_validate_board_shape(s, i) for i, s in enumerate(shapes_raw)]

    # Phase 6d-2 — optional game_format + formation metadata. Absent =
    # legacy board (do not synthesize). Present-but-null is treated as
    # absent so a client that wants to clear can send null. Unknown
    # game_format rejects on write; formation is a free-form short
    # string that's bounds-checked but not enumerated here.
    out = {
        "version": 1,
        "pitch_kind": pitch_kind,
        "orientation": orientation,
        "tokens": tokens,
        "shapes": shapes,
    }
    if "game_format" in value and value["game_format"] is not None:
        gf = value["game_format"]
        if not isinstance(gf, str):
            raise ValueError("tactical_board_json game_format must be a string")
        if gf not in _VALID_BOARD_GAME_FORMATS:
            raise ValueError(
                f"tactical_board_json game_format must be one of {sorted(_VALID_BOARD_GAME_FORMATS)}"
            )
        out["game_format"] = gf
    if "formation" in value and value["formation"] is not None:
        fm = value["formation"]
        if isinstance(fm, bool) or not isinstance(fm, str):
            raise ValueError("tactical_board_json formation must be a string")
        fm = fm.strip()
        if not fm:
            raise ValueError("tactical_board_json formation cannot be blank")
        if len(fm) > _MAX_BOARD_FORMATION_LENGTH:
            raise ValueError(
                f"tactical_board_json formation exceeds max length ({_MAX_BOARD_FORMATION_LENGTH})"
            )
        out["formation"] = fm
    return out


class CreateCoachingNoteRequest(BaseModel):
    # Phase 6a — `match_id` / `slot` / `timestamp_seconds` are now
    # nullable so observation notes can omit them. Validation is split
    # between field-level rules (each field's individual shape) and a
    # `model_validator(mode="after")` that enforces per-context
    # invariants:
    #   - `note_context == "video"` requires all three.
    #   - `note_context == "observation"` does not require any of them
    #     and additionally requires meaningful coaching content.
    match_id: Optional[str] = Field(None, min_length=1, max_length=120)
    slot: Optional[str] = Field(None)
    timestamp_seconds: Optional[float] = Field(None, ge=0)
    title: str = Field("", max_length=160)
    body: str = Field("", max_length=4000)
    category: str = Field("other")
    visibility: str = Field("private")
    player_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=25)
    drawing: dict[str, Any] = Field(default_factory=dict)
    # Phase 1 structured-note fields. All optional with safe defaults so
    # existing clients (older Coach Review save flow, scripts, tests)
    # keep working with no payload changes. UI-side, the new fields are
    # exposed via templates (Phase 2) and the note composer.
    note_type: str = Field("correction")
    what_happened: str = Field("", max_length=2000)
    why_it_matters: str = Field("", max_length=2000)
    what_to_do_next: str = Field("", max_length=2000)
    player_summary: str = Field("", max_length=2000)
    coach_private_note: str = Field("", max_length=4000)
    # Phase 6a — observation-note fields. All optional. Video notes
    # leave them empty / None.
    note_context: str = Field("video")
    event_title: str = Field("", max_length=200)
    event_date: str = Field("", max_length=10)
    event_type: str = Field("")
    tactical_board_json: Optional[dict[str, Any]] = None

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _VALID_SLOTS:
            raise ValueError("slot must be full, first_half, or second_half")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _VALID_NOTE_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(sorted(_VALID_NOTE_CATEGORIES))}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _VALID_COACHING_VISIBILITY:
            raise ValueError(f"visibility must be one of: {', '.join(sorted(_VALID_COACHING_VISIBILITY))}")
        return v

    @field_validator("note_type")
    @classmethod
    def validate_note_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _VALID_NOTE_TYPES:
            raise ValueError(f"note_type must be one of: {', '.join(sorted(_VALID_NOTE_TYPES))}")
        return v

    @field_validator("note_context")
    @classmethod
    def validate_note_context(cls, v: str) -> str:
        v = v.strip().lower() or "video"
        if v not in _VALID_NOTE_CONTEXTS:
            raise ValueError(
                f"note_context must be one of: {', '.join(sorted(_VALID_NOTE_CONTEXTS))}"
            )
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        return _validate_event_type(v)

    @field_validator("event_date")
    @classmethod
    def validate_event_date(cls, v: str) -> str:
        return _validate_event_date(v)

    @field_validator("title", "body", "what_happened", "why_it_matters",
                     "what_to_do_next", "player_summary", "coach_private_note",
                     "event_title")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str]) -> list[str]:
        seen = set()
        tags = []
        for tag in v:
            clean = str(tag).strip().lower()
            if not clean or clean in seen:
                continue
            if len(clean) > 40:
                raise ValueError("tags must be 40 characters or fewer")
            seen.add(clean)
            tags.append(clean)
        return tags

    @field_validator("drawing")
    @classmethod
    def validate_drawing(cls, v: dict[str, Any]) -> dict[str, Any]:
        return validate_drawing_payload(v)

    @field_validator("tactical_board_json")
    @classmethod
    def validate_tactical_board(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_tactical_board_payload(v)

    @model_validator(mode="after")
    def validate_context_invariants(self):
        # Phase 6a — per-context invariants.
        # The field-level title validator made title an empty-allowed
        # string so observation notes that lean on `event_title` /
        # `player_summary` / structured fields aren't forced to
        # duplicate text into `title`. Re-enforce title presence for
        # video notes here so existing video-note callers behave
        # exactly as before.
        if self.note_context == "video":
            missing = [
                name for name, value in (
                    ("match_id", self.match_id),
                    ("slot", self.slot),
                    ("timestamp_seconds", self.timestamp_seconds),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "video notes require " + ", ".join(missing)
                )
            if not (self.title or "").strip():
                raise ValueError("title must not be empty")
            return self
        # Observation notes — reject obviously empty-content rows.
        # `tactical_board_json` is also accepted as "meaningful content"
        # so a tactical-board-only note (Phase 6c will exercise this)
        # passes without forcing the coach to type a title.
        has_content = self.tactical_board_json is not None or any(
            (getattr(self, name) or "").strip()
            for name in _OBSERVATION_CONTENT_FIELDS
        )
        if not has_content:
            raise ValueError(
                "observation notes require at least one of: "
                + ", ".join(_OBSERVATION_CONTENT_FIELDS)
                + ", or tactical_board_json"
            )
        return self


class UpdateCoachingNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Phase 6a — `match_id` / `slot` / `note_context` are now editable
    # via PATCH so a coach can flip a note between video and
    # observation contexts. The route handler validates the merged
    # state (existing row + this PATCH) so a video note can never end
    # up with `match_id` cleared but `note_context` still 'video'.
    match_id: Optional[str] = Field(None, min_length=1, max_length=120)
    slot: Optional[str] = Field(None)
    timestamp_seconds: Optional[float] = Field(None, ge=0)
    # Phase 6b (#113) — `min_length` removed so observation notes can
    # PATCH `title: ""` to clear it. The route handler revalidates the
    # merged state and still rejects an empty title for video notes
    # (and rejects observation notes that end up with no meaningful
    # content), so this is purely a model-shape relaxation.
    title: Optional[str] = Field(None, max_length=160)
    body: Optional[str] = Field(None, max_length=4000)
    category: Optional[str] = None
    visibility: Optional[str] = None
    player_ids: Optional[list[str]] = Field(None, max_length=50)
    tags: Optional[list[str]] = Field(None, max_length=25)
    drawing: Optional[dict[str, Any]] = None
    # Phase 1 structured-note fields — all optional partial-update.
    note_type: Optional[str] = None
    what_happened: Optional[str] = Field(None, max_length=2000)
    why_it_matters: Optional[str] = Field(None, max_length=2000)
    what_to_do_next: Optional[str] = Field(None, max_length=2000)
    player_summary: Optional[str] = Field(None, max_length=2000)
    coach_private_note: Optional[str] = Field(None, max_length=4000)
    # Phase 6a — observation-note fields. All optional partial-update.
    # `tactical_board_json` accepts an explicit `null` JSON value (or a
    # missing key) so a coach can clear the saved sketch.
    note_context: Optional[str] = None
    event_title: Optional[str] = Field(None, max_length=200)
    event_date: Optional[str] = Field(None, max_length=10)
    event_type: Optional[str] = None
    tactical_board_json: Optional[dict[str, Any]] = None

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _VALID_SLOTS:
            raise ValueError("slot must be full, first_half, or second_half")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_category(v)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_visibility(v)

    @field_validator("note_type")
    @classmethod
    def validate_note_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_note_type(v)

    @field_validator("note_context")
    @classmethod
    def validate_note_context(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_note_context(v)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_event_type(v)

    @field_validator("event_date")
    @classmethod
    def validate_event_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_event_date(v)

    @field_validator("title", "body", "what_happened", "why_it_matters",
                     "what_to_do_next", "player_summary", "coach_private_note",
                     "event_title")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.normalize_tags(v)

    @field_validator("drawing")
    @classmethod
    def validate_drawing(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        return validate_drawing_payload(v)

    @field_validator("tactical_board_json")
    @classmethod
    def validate_tactical_board(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_tactical_board_payload(v)


class CreateCoachingPlaylistRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field("", max_length=1000)
    visibility: str = Field("private")
    player_ids: list[str] = Field(default_factory=list, max_length=50)
    note_ids: list[int] = Field(default_factory=list, max_length=100)
    pre_roll_seconds: float = Field(5.0, ge=0, le=60)
    post_roll_seconds: float = Field(8.0, ge=0, le=120)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        return CreateCoachingNoteRequest.validate_visibility(v)


class UpdateCoachingPlaylistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=1000)
    visibility: Optional[str] = None
    player_ids: Optional[list[str]] = Field(None, max_length=50)
    note_ids: Optional[list[int]] = Field(None, max_length=100)
    pre_roll_seconds: Optional[float] = Field(None, ge=0, le=60)
    post_roll_seconds: Optional[float] = Field(None, ge=0, le=120)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_visibility(v)


class CreateMatchSummaryRequest(BaseModel):
    match_id: str = Field(..., min_length=1, max_length=120)
    visibility: str = Field("private")
    team_positives: str = Field("", max_length=4000)
    team_improvements: str = Field("", max_length=4000)
    training_focus: str = Field("", max_length=2000)
    body: str = Field("", max_length=8000)
    note_ids: list[int] = Field(default_factory=list, max_length=100)
    clip_ids: list[int] = Field(default_factory=list, max_length=100)
    playlist_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        return CreateCoachingNoteRequest.validate_visibility(v)

    @field_validator("team_positives", "team_improvements", "training_focus", "body")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("note_ids", "clip_ids", "playlist_ids")
    @classmethod
    def normalize_ids(cls, v: list[int]) -> list[int]:
        seen = set()
        out = []
        for item in v:
            if item <= 0:
                raise ValueError("linked source ids must be positive")
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @model_validator(mode="after")
    def validate_has_content(self):
        if not any((getattr(self, name) or "").strip() for name in ("team_positives", "team_improvements", "training_focus", "body")):
            raise ValueError("match summary requires at least one text field")
        return self


class UpdateMatchSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Optional[str] = None
    team_positives: Optional[str] = Field(None, max_length=4000)
    team_improvements: Optional[str] = Field(None, max_length=4000)
    training_focus: Optional[str] = Field(None, max_length=2000)
    body: Optional[str] = Field(None, max_length=8000)
    note_ids: Optional[list[int]] = Field(None, max_length=100)
    clip_ids: Optional[list[int]] = Field(None, max_length=100)
    playlist_ids: Optional[list[int]] = Field(None, max_length=100)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_visibility(v)

    @field_validator("team_positives", "team_improvements", "training_focus", "body")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("note_ids", "clip_ids", "playlist_ids")
    @classmethod
    def normalize_ids(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        return CreateMatchSummaryRequest.normalize_ids(v)


class MarkCoachingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: Optional[int] = None
    playlist_id: Optional[int] = None
    reflection: str = Field("", max_length=1000)

    @field_validator("reflection")
    @classmethod
    def strip_reflection(cls, v: str) -> str:
        return v.strip()


_VALID_GOAL_STATUSES = {"open", "in_progress", "needs_follow_up", "achieved", "archived"}
_VALID_GOAL_CONTEXTS = {"next_match", "next_training", "season_goal", "other"}
_VALID_GOAL_VISIBILITIES = {"player", "coach"}
_VALID_GOAL_PRIORITIES = {"low", "medium", "high"}


def _strip_optional_text(v: str | None) -> str | None:
    return v.strip() if isinstance(v, str) else v


class CreatePlayerGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field("", max_length=2000)
    visibility: str = Field("player")
    priority: str = Field("medium")
    target_date: str = Field("", max_length=10)
    success_criteria: str = Field("", max_length=2000)
    coach_private_note: str = Field("", max_length=2000)
    context: str = Field("next_match")
    status: str = Field("open")
    source_note_id: Optional[int] = None
    source_clip_id: Optional[int] = None
    source_playlist_id: Optional[int] = None
    source_playlist_item_note_id: Optional[int] = None
    target_match_id: Optional[str] = Field(default=None, max_length=120)

    @field_validator("title", "description", "player_id", "target_match_id", "success_criteria", "coach_private_note")
    @classmethod
    def strip_goal_text(cls, v: str | None) -> str | None:
        return _strip_optional_text(v)

    @model_validator(mode="after")
    def reject_blank_required_goal_text(self):
        if not self.player_id:
            raise ValueError("player_id is required")
        if not self.title:
            raise ValueError("title is required")
        return self

    @field_validator("status")
    @classmethod
    def validate_goal_status(cls, v: str) -> str:
        if v not in _VALID_GOAL_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_GOAL_STATUSES))}")
        return v

    @field_validator("context")
    @classmethod
    def validate_goal_context(cls, v: str) -> str:
        if v not in _VALID_GOAL_CONTEXTS:
            raise ValueError(f"context must be one of: {', '.join(sorted(_VALID_GOAL_CONTEXTS))}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_goal_visibility(cls, v: str) -> str:
        if v not in _VALID_GOAL_VISIBILITIES:
            raise ValueError(f"visibility must be one of: {', '.join(sorted(_VALID_GOAL_VISIBILITIES))}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_goal_priority(cls, v: str) -> str:
        if v not in _VALID_GOAL_PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(sorted(_VALID_GOAL_PRIORITIES))}")
        return v

    @field_validator("target_date")
    @classmethod
    def validate_goal_target_date(cls, v: str) -> str:
        v = v.strip()
        if v and not _DATE_RE.match(v):
            raise ValueError("target_date must be empty or YYYY-MM-DD")
        return v


class UpdatePlayerGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    visibility: Optional[str] = None
    priority: Optional[str] = None
    target_date: Optional[str] = Field(default=None, max_length=10)
    success_criteria: Optional[str] = Field(default=None, max_length=2000)
    coach_private_note: Optional[str] = Field(default=None, max_length=2000)
    context: Optional[str] = None
    status: Optional[str] = None
    source_note_id: Optional[int] = None
    source_clip_id: Optional[int] = None
    source_playlist_id: Optional[int] = None
    source_playlist_item_note_id: Optional[int] = None
    target_match_id: Optional[str] = Field(default=None, max_length=120)

    @field_validator("title", "description", "target_match_id", "target_date", "success_criteria", "coach_private_note")
    @classmethod
    def strip_goal_text(cls, v: str | None) -> str | None:
        return _strip_optional_text(v)

    @model_validator(mode="after")
    def reject_blank_goal_title(self):
        if self.title is not None and not self.title:
            raise ValueError("title is required")
        return self

    @field_validator("status")
    @classmethod
    def validate_goal_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreatePlayerGoalRequest.validate_goal_status(v)

    @field_validator("context")
    @classmethod
    def validate_goal_context(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreatePlayerGoalRequest.validate_goal_context(v)

    @field_validator("visibility")
    @classmethod
    def validate_goal_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreatePlayerGoalRequest.validate_goal_visibility(v)

    @field_validator("priority")
    @classmethod
    def validate_goal_priority(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreatePlayerGoalRequest.validate_goal_priority(v)

    @field_validator("target_date")
    @classmethod
    def validate_goal_target_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreatePlayerGoalRequest.validate_goal_target_date(v)


class CreatePlayerGoalReflectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reflection: str = Field(..., min_length=1, max_length=1000)

    @field_validator("reflection")
    @classmethod
    def strip_reflection(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reflection is required")
        return v


# ---------------------------------------------------------------------------
# Phase 4a — Coaching clips
#
# Clips reuse the SAME enums as notes (`_VALID_NOTE_CATEGORIES`,
# `_VALID_COACHING_VISIBILITY`, `_VALID_SLOTS`) and the same drawing
# validator, so the coach authoring vocabulary stays consistent across
# notes / playlists / clips. The duration cap matches the roadmap's
# MVP guidance (120 seconds). The clip authoring UI ships in a later
# phase; this PR is backend-only.
# ---------------------------------------------------------------------------

# Roadmap MVP cap (Phase 4a). Generous enough for a full set-piece +
# follow-up sequence, narrow enough that the eventual MP4 export job
# stays bounded. Re-think this when clip export ships.
_MAX_CLIP_DURATION_SECONDS = 120.0


class CreateCoachingClipRequest(BaseModel):
    match_id: str = Field(..., min_length=1, max_length=120)
    slot: str = Field("full")
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field("", max_length=2000)
    category: str = Field("other")
    visibility: str = Field("private")
    player_ids: list[str] = Field(default_factory=list, max_length=50)
    source_note_id: Optional[int] = None
    # Optional drawing snapshot. When the create endpoint is given a
    # `source_note_id` and `drawing` is empty, the server defaults this
    # field from the source note's drawing so the clip is self-
    # contained. See `db.create_coaching_clip` + the create handler in
    # `server.py`.
    drawing: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str) -> str:
        if v not in _VALID_SLOTS:
            raise ValueError("slot must be full, first_half, or second_half")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        return CreateCoachingNoteRequest.validate_category(v)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        return CreateCoachingNoteRequest.validate_visibility(v)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("drawing")
    @classmethod
    def validate_drawing(cls, v: dict[str, Any]) -> dict[str, Any]:
        return validate_drawing_payload(v)

    @model_validator(mode="after")
    def validate_window(self):
        # `end_seconds > start_seconds` is the must-hold invariant.
        # The other constraints (non-negative start, MVP duration cap)
        # live here too so the error messages name the field a coach
        # actually edits in the UI.
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        duration = self.end_seconds - self.start_seconds
        if duration > _MAX_CLIP_DURATION_SECONDS:
            raise ValueError(
                f"clip duration must be {_MAX_CLIP_DURATION_SECONDS:.0f} seconds or less"
            )
        return self


class UpdateCoachingClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: Optional[float] = Field(None, ge=0)
    end_seconds: Optional[float] = Field(None, gt=0)
    title: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = None
    visibility: Optional[str] = None
    player_ids: Optional[list[str]] = Field(None, max_length=50)
    drawing: Optional[dict[str, Any]] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_category(v)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CreateCoachingNoteRequest.validate_visibility(v)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("drawing")
    @classmethod
    def validate_drawing(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        return validate_drawing_payload(v)

    @model_validator(mode="after")
    def validate_window(self):
        # We can only enforce the window invariants when the request
        # provides BOTH endpoints, OR provides one endpoint and the
        # caller has already merged the other in from the existing row.
        # Validation against the existing row happens in the route
        # handler (`server.py`) so it can short-circuit with 404 when
        # the clip itself doesn't exist. Here we just guard the
        # both-fields-supplied case.
        if self.start_seconds is not None and self.end_seconds is not None:
            if self.end_seconds <= self.start_seconds:
                raise ValueError("end_seconds must be greater than start_seconds")
            duration = self.end_seconds - self.start_seconds
            if duration > _MAX_CLIP_DURATION_SECONDS:
                raise ValueError(
                    f"clip duration must be {_MAX_CLIP_DURATION_SECONDS:.0f} seconds or less"
                )
        return self


class LiveAuthRequest(BaseModel):
    """Body MediaMTX POSTs to the auth webhook on publish/read attempts."""
    model_config = ConfigDict(extra="allow")

    user: str = ""
    password: str = ""
    ip: str = ""
    action: str = ""
    path: str = ""
    protocol: str = ""
    id: str = ""
    query: str = ""


class UnblockStreamRequest(BaseModel):
    """Admin: clear a kill-block for a (ip, kind, match_id, slot) tuple."""
    model_config = ConfigDict(extra="forbid")

    ip: str = Field(..., min_length=1, max_length=64)
    kind: Literal["live", "vod-hls", "vod-mp4"]
    match_id: Optional[str] = None
    slot: Optional[str] = None


class StartCaptureRequest(BaseModel):
    """Admin: start a high-frequency throughput capture window for the
    Performance Tuning panel. The streams module clamps the value to
    [5, 600] s, but bound the type/range here so an invalid body fails
    fast with a 422 instead of slipping through to a float() coercion."""
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(60.0, ge=5.0, le=600.0)
