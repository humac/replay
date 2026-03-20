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


class CreateUploadSessionRequest(BaseModel):
    filename: str = Field("video.mp4", min_length=1, max_length=500)
    size_bytes: int = Field(..., gt=0)
