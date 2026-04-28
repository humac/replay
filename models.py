"""Pydantic request models for the Replay API."""

from __future__ import annotations

import re
from typing import Literal, Optional

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
_VALID_ROLES = {"admin", "uploader", "viewer"}


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
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(_VALID_ROLES))}")
        return v


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: Optional[str] = Field(None, min_length=8, max_length=200)
    role: Optional[str] = None
    display_name: Optional[str] = Field(None, max_length=100)
    enabled: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(_VALID_ROLES))}")
        return v


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
