"""Unit tests for Pydantic request validators in models.py.

These run without the FastAPI app — they exercise the validators directly.
The endpoint-level happy paths are already covered by test_matches.py /
test_users.py / test_uploads.py; this file locks in the field-level rules
so a regex tweak or a stripped validator surfaces immediately.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import (
    CreateMatchRequest,
    CreateUploadSessionRequest,
    CreateUserRequest,
    LoginRequest,
    StartCaptureRequest,
    UnblockStreamRequest,
    UpdateMatchRequest,
    UpdateUserRequest,
)


# ---------------------------------------------------------------------------
# LoginRequest
# ---------------------------------------------------------------------------

def test_login_request_requires_non_empty_fields():
    with pytest.raises(ValidationError):
        LoginRequest(username="", password="x")
    with pytest.raises(ValidationError):
        LoginRequest(username="x", password="")


# ---------------------------------------------------------------------------
# CreateMatchRequest
# ---------------------------------------------------------------------------

def test_create_match_strips_team_whitespace():
    m = CreateMatchRequest(home_team="  A  ", away_team="\tB\n")
    assert m.home_team == "A"
    assert m.away_team == "B"


def test_create_match_accepts_iso_date():
    m = CreateMatchRequest(home_team="A", away_team="B", date="2026-04-30")
    assert m.date == "2026-04-30"


def test_create_match_rejects_bad_date_format():
    with pytest.raises(ValidationError):
        CreateMatchRequest(home_team="A", away_team="B", date="04/30/2026")


def test_create_match_accepts_hh_mm_time():
    m = CreateMatchRequest(home_team="A", away_team="B", time="15:30")
    assert m.time == "15:30"


def test_create_match_rejects_non_hh_mm_time():
    with pytest.raises(ValidationError):
        CreateMatchRequest(home_team="A", away_team="B", time="3:30 PM")


def test_create_match_format_must_be_full_or_two_halves():
    with pytest.raises(ValidationError):
        CreateMatchRequest(home_team="A", away_team="B", format="quarters")


def test_create_match_empty_date_is_allowed():
    m = CreateMatchRequest(home_team="A", away_team="B", date="")
    assert m.date == ""


# ---------------------------------------------------------------------------
# UpdateMatchRequest — same validators, but None is allowed and extra=forbid
# ---------------------------------------------------------------------------

def test_update_match_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        UpdateMatchRequest(home_team="A", surprise="bad")


def test_update_match_none_passes_validators():
    # All fields default to None and that should not raise.
    UpdateMatchRequest()


def test_update_match_invalid_date_still_raises():
    with pytest.raises(ValidationError):
        UpdateMatchRequest(date="not-a-date")


def test_update_match_invalid_time_still_raises():
    with pytest.raises(ValidationError):
        UpdateMatchRequest(time="bogus")


# ---------------------------------------------------------------------------
# CreateUploadSessionRequest
# ---------------------------------------------------------------------------

def test_upload_session_requires_positive_size():
    with pytest.raises(ValidationError):
        CreateUploadSessionRequest(size_bytes=0)
    with pytest.raises(ValidationError):
        CreateUploadSessionRequest(size_bytes=-1)


def test_upload_session_rejects_non_hex_hash():
    with pytest.raises(ValidationError):
        CreateUploadSessionRequest(size_bytes=1, first_chunk_hash="zzz")


def test_upload_session_rejects_short_hash():
    with pytest.raises(ValidationError):
        CreateUploadSessionRequest(size_bytes=1, first_chunk_hash="a" * 63)


def test_upload_session_accepts_valid_sha256():
    h = "a" * 64
    m = CreateUploadSessionRequest(size_bytes=10, first_chunk_hash=h)
    assert m.first_chunk_hash == h


def test_upload_session_hash_optional():
    m = CreateUploadSessionRequest(size_bytes=10)
    assert m.first_chunk_hash is None


# ---------------------------------------------------------------------------
# CreateUserRequest
# ---------------------------------------------------------------------------

def test_create_user_username_charset():
    # Allowed: letters, digits, underscore, dot, hyphen
    CreateUserRequest(username="abc.DEF_123-x", password="password1", role="viewer")


def test_create_user_username_rejects_special_chars():
    with pytest.raises(ValidationError):
        CreateUserRequest(username="bad name", password="password1", role="viewer")
    with pytest.raises(ValidationError):
        CreateUserRequest(username="bob@host", password="password1", role="viewer")


def test_create_user_role_must_be_known():
    with pytest.raises(ValidationError):
        CreateUserRequest(username="alice", password="password1", role="superuser")


def test_create_user_password_min_length():
    with pytest.raises(ValidationError):
        CreateUserRequest(username="alice", password="short", role="viewer")


# ---------------------------------------------------------------------------
# UpdateUserRequest
# ---------------------------------------------------------------------------

def test_update_user_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        UpdateUserRequest(role="viewer", username="cant-rename")


def test_update_user_role_validator_runs():
    with pytest.raises(ValidationError):
        UpdateUserRequest(role="not-a-role")


def test_update_user_role_none_is_allowed():
    UpdateUserRequest()  # all None


# ---------------------------------------------------------------------------
# UnblockStreamRequest / StartCaptureRequest
# ---------------------------------------------------------------------------

def test_unblock_stream_kind_is_constrained():
    with pytest.raises(ValidationError):
        UnblockStreamRequest(ip="1.2.3.4", kind="something-else")
    UnblockStreamRequest(ip="1.2.3.4", kind="vod-hls")


def test_start_capture_seconds_bounded():
    with pytest.raises(ValidationError):
        StartCaptureRequest(seconds=4.0)
    with pytest.raises(ValidationError):
        StartCaptureRequest(seconds=601.0)
    StartCaptureRequest(seconds=5.0)
    StartCaptureRequest(seconds=600.0)
