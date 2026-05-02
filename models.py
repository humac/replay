"""Pydantic request models for the Replay API."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
            if not isinstance(hull_points, list) or len(hull_points) > 16:
                raise ValueError("formation hull_points must be a list with at most 16 entries")
            for point in hull_points:
                _validate_drawing_point(point)
    return value


class CreatePlayerRequest(BaseModel):
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


class CreateCoachingNoteRequest(BaseModel):
    match_id: str = Field(..., min_length=1, max_length=120)
    slot: str = Field("full")
    timestamp_seconds: float = Field(..., ge=0)
    title: str = Field(..., min_length=1, max_length=160)
    body: str = Field("", max_length=4000)
    category: str = Field("other")
    visibility: str = Field("private")
    player_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=25)
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

    @field_validator("title", "body")
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


class UpdateCoachingNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_seconds: Optional[float] = Field(None, ge=0)
    title: Optional[str] = Field(None, min_length=1, max_length=160)
    body: Optional[str] = Field(None, max_length=4000)
    category: Optional[str] = None
    visibility: Optional[str] = None
    player_ids: Optional[list[str]] = Field(None, max_length=50)
    tags: Optional[list[str]] = Field(None, max_length=25)
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

    @field_validator("title", "body")
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
