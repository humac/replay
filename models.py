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


def validate_tactical_board_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Phase 6a — `tactical_board_json` is JSON-compatible metadata
    that the Phase 6c tactical board editor will read and write. The
    backend doesn't enforce a board schema yet (the editor will firm it
    up); we just guard against obviously malformed input:

    - None / missing → stored as NULL.
    - Non-dict (list, string, number) → 422. The board surface is an
      object with `pitch_kind` + tokens / shapes / labels.
    - Oversized blob (> ~100 KB) → 422 so a corrupted client can't
      stuff arbitrarily large payloads into the row.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("tactical_board_json must be an object")
    if not value:
        # Empty dict is allowed but normalized to None so the row
        # mapper distinguishes "explicit empty" the same as "unset".
        return None
    if len(json.dumps(value, separators=(",", ":"))) > _MAX_TACTICAL_BOARD_JSON_BYTES:
        raise ValueError("tactical_board_json payload is too large")
    return value


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
    title: Optional[str] = Field(None, min_length=1, max_length=160)
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


class MarkCoachingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: Optional[int] = None
    playlist_id: Optional[int] = None
    reflection: str = Field("", max_length=1000)

    @field_validator("reflection")
    @classmethod
    def strip_reflection(cls, v: str) -> str:
        return v.strip()


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
