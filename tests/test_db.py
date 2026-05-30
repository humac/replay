"""Direct tests for the SQLite layer in db.py.

The existing test suite goes through HTTP routes, which exercises db.py
indirectly. These tests target the module's API directly so a regression
in migrations or activity-event serialization fails fast and points at
the right module.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import db as _db


@pytest.fixture()
def fresh_db(tmp_path: Path):
    """Initialize a brand-new sqlite db rooted at tmp_path and tear it down."""
    data_dir = tmp_path / "data"
    db_file = data_dir / "replay.db"
    assets_dir = data_dir / "app_assets"
    _db.close_thread_connection()
    _db.init(data_dir, db_file, assets_dir)
    yield _db
    _db.close_thread_connection()


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "matches",
    "upload_sessions",
    "settings",
    "users",
    "video_errors",
    "settings_audit",
    "activity_events",
    "schema_version",
    "background_jobs",
}


def test_migrations_create_all_expected_tables(fresh_db):
    with fresh_db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in rows}
    assert EXPECTED_TABLES.issubset(names), names


def test_schema_version_pinned_to_latest(fresh_db):
    with fresh_db.connect() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    # The schema was squashed into a single 1-based migration; versions are
    # 1-based so the latest stored version equals the migration count.
    assert version == len(fresh_db._MIGRATIONS)
    assert version == 1


def test_matches_table_has_slug_and_updated_at_columns(fresh_db):
    """Migrations v1 (slug) and v5 (updated_at) must be applied on a fresh db."""
    with fresh_db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)").fetchall()}
    assert "slug" in cols
    assert "updated_at" in cols


def test_upload_sessions_has_first_chunk_hash_column(fresh_db):
    """Migration v4 added first_chunk_hash for upload fingerprinting."""
    with fresh_db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(upload_sessions)").fetchall()}
    assert "first_chunk_hash" in cols


def test_re_running_migrations_is_idempotent(fresh_db, tmp_path):
    """Re-initializing the same db should not error or duplicate version rows."""
    fresh_db.close_thread_connection()
    fresh_db.init(tmp_path / "data", tmp_path / "data" / "replay.db", tmp_path / "data" / "app_assets")
    with fresh_db.connect() as conn:
        rows = conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()
    assert rows["c"] == 1


def test_migrations_fail_closed_on_legacy_higher_version(fresh_db, tmp_path):
    """A DB at a HIGHER schema_version than the squashed target must refuse
    to run rather than silently downgrade user_version and leave dead tables
    from the pre-squash v0..v26 chain in place. Regression for PR #193 review."""
    import sqlite3
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (26)")
        conn.execute("PRAGMA user_version = 26")
        conn.commit()
    fresh_db.close_thread_connection()
    with pytest.raises(RuntimeError, match="schema_version=26"):
        fresh_db.init(tmp_path, db_path, tmp_path / "assets")


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def test_generate_slug_basic(fresh_db):
    assert fresh_db.generate_slug("Home FC", "Away United", "2026-04-30") == "home-fc-vs-away-united-2026-04-30"


def test_generate_slug_strips_punctuation(fresh_db):
    slug = fresh_db.generate_slug("FC Köln!", "AC/DC FC", "")
    # Non-ASCII collapses to a hyphen and gets stripped at the boundary.
    assert all(c.isalnum() or c == "-" for c in slug)
    assert "fc" in slug


def test_ensure_unique_slug_appends_counter(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("a", slug="duel-2026"))
        fresh_db.upsert_match(conn, _make_match("b", slug="duel-2026-2"))
        unique = fresh_db.ensure_unique_slug(conn, "duel-2026")
        assert unique == "duel-2026-3"


def test_ensure_unique_slug_excludes_self(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("self", slug="dup"))
        # Same slug, but excluded → returns the original.
        assert fresh_db.ensure_unique_slug(conn, "dup", exclude_id="self") == "dup"


# ---------------------------------------------------------------------------
# Match CRUD at the DB layer
# ---------------------------------------------------------------------------

def _make_match(mid: str, **overrides) -> dict:
    base = {
        "id": mid,
        "home_team": "A",
        "away_team": "B",
        "date": "2026-04-30",
        "time": "15:00",
        "location": "",
        "score_home": None,
        "score_away": None,
        "format": "full",
        "videos": {"full": None, "first_half": None, "second_half": None},
        "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
        "home_logo": None,
        "away_logo": None,
        "created_at": "2026-04-30T00:00:00Z",
        "slug": f"slug-{mid}",
        "updated_at": "2026-04-30T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_upsert_match_is_idempotent(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("m1"))
        fresh_db.upsert_match(conn, _make_match("m1", home_team="Updated"))
        conn.commit()
    out = fresh_db.get_match_by_id("m1")
    assert out is not None
    assert out["home_team"] == "Updated"


def test_get_match_by_id_returns_none_for_missing(fresh_db):
    assert fresh_db.get_match_by_id("nope") is None


def test_search_matches_filters_by_team(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("a", home_team="Steel", away_team="Hotspurs"))
        fresh_db.upsert_match(conn, _make_match("b", home_team="Rovers", away_team="Wanderers"))
        conn.commit()
    matches, total = fresh_db.search_matches(q="steel")
    assert total == 1
    assert matches[0]["id"] == "a"


def test_search_matches_pagination(fresh_db):
    with fresh_db.connect() as conn:
        for i in range(5):
            fresh_db.upsert_match(conn, _make_match(f"m{i}"))
        conn.commit()
    page1, total = fresh_db.search_matches(page=1, limit=2)
    page2, _ = fresh_db.search_matches(page=2, limit=2)
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {m["id"] for m in page1}.isdisjoint({m["id"] for m in page2})


def test_save_matches_unlocked_deletes_removed_records(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("keep"))
        fresh_db.upsert_match(conn, _make_match("drop"))
        conn.commit()
    # Persist only "keep" — "drop" should be removed.
    fresh_db.save_matches_unlocked([_make_match("keep")])
    assert fresh_db.get_match_by_id("keep") is not None
    assert fresh_db.get_match_by_id("drop") is None


def test_backfill_slugs_fills_blank_only(fresh_db):
    with fresh_db.connect() as conn:
        fresh_db.upsert_match(conn, _make_match("with", slug="already-set"))
        fresh_db.upsert_match(conn, _make_match("without", slug=""))
        conn.commit()
    fresh_db.backfill_slugs()
    assert fresh_db.get_match_by_id("with")["slug"] == "already-set"
    assert fresh_db.get_match_by_id("without")["slug"]  # non-empty


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def test_create_and_lookup_user(fresh_db):
    fresh_db.create_user("alice", "hash:abc", "viewer", "Alice")
    out = fresh_db.get_user_by_username("alice")
    assert out is not None
    assert out["role"] == "viewer"
    assert out["display_name"] == "Alice"
    assert out["enabled"] is True


def test_username_lookup_is_case_insensitive(fresh_db):
    fresh_db.create_user("Alice", "h", "viewer")
    assert fresh_db.get_user_by_username("alice") is not None
    assert fresh_db.get_user_by_username("ALICE") is not None


def test_update_user_ignores_unknown_fields(fresh_db):
    user = fresh_db.create_user("bob", "h", "viewer")
    ok = fresh_db.update_user(user["id"], role="admin", random="ignored")
    assert ok is True
    assert fresh_db.get_user_by_id(user["id"])["role"] == "admin"


def test_update_user_returns_false_when_nothing_to_update(fresh_db):
    user = fresh_db.create_user("carol", "h", "viewer")
    assert fresh_db.update_user(user["id"]) is False


def test_delete_user_returns_true_only_on_match(fresh_db):
    user = fresh_db.create_user("dave", "h", "viewer")
    assert fresh_db.delete_user(user["id"]) is True
    assert fresh_db.delete_user(user["id"]) is False


# ---------------------------------------------------------------------------
# Video errors
# ---------------------------------------------------------------------------

def test_log_video_error_persists(fresh_db):
    rid = fresh_db.log_video_error("m1", "full", "disk_full", "No space", "need 10G")
    assert rid > 0
    errs = fresh_db.get_video_errors(match_id="m1")
    assert len(errs) == 1
    assert errs[0]["error_code"] == "disk_full"
    assert fresh_db.count_video_errors() == 1


def test_get_video_errors_filters_by_slot(fresh_db):
    fresh_db.log_video_error("m1", "full", "a", "x")
    fresh_db.log_video_error("m1", "first_half", "b", "y")
    errs = fresh_db.get_video_errors(match_id="m1", slot="first_half")
    assert len(errs) == 1
    assert errs[0]["error_code"] == "b"


# ---------------------------------------------------------------------------
# Activity events
# ---------------------------------------------------------------------------

def test_log_activity_event_serializes_metadata(fresh_db):
    rid = fresh_db.log_activity_event(
        "transcode.succeeded",
        severity="success",
        message="ok",
        match_id="m1",
        slot="full",
        actor="admin",
        metadata={"variants": 3, "hwaccel": "qsv"},
    )
    assert rid > 0
    events = fresh_db.get_activity_events(limit=10)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "transcode.succeeded"
    assert ev["severity"] == "success"
    assert ev["actor"] == "admin"
    assert ev["metadata"] == {"variants": 3, "hwaccel": "qsv"}


def test_get_activity_events_respects_limit(fresh_db):
    for i in range(5):
        fresh_db.log_activity_event(f"evt.{i}")
    events = fresh_db.get_activity_events(limit=3)
    assert len(events) == 3


def test_get_activity_events_orders_newest_first(fresh_db):
    fresh_db.log_activity_event("evt.first")
    time.sleep(1.01)  # created_at has 1-second resolution
    fresh_db.log_activity_event("evt.second")
    events = fresh_db.get_activity_events(limit=10)
    assert events[0]["event_type"] == "evt.second"
    assert events[1]["event_type"] == "evt.first"


def test_get_activity_events_respects_max_age_cutoff(fresh_db):
    # Insert an event then artificially backdate created_at to past the cutoff.
    fresh_db.log_activity_event("evt.recent")
    fresh_db.log_activity_event("evt.old")
    with fresh_db.connect() as conn:
        conn.execute(
            "UPDATE activity_events SET created_at = ? WHERE event_type = ?",
            ("2000-01-01T00:00:00Z", "evt.old"),
        )
        conn.commit()

    events = fresh_db.get_activity_events(limit=10, max_age_hours=24)
    types = {e["event_type"] for e in events}
    assert "evt.recent" in types
    assert "evt.old" not in types


def test_get_activity_events_no_cutoff_includes_all(fresh_db):
    fresh_db.log_activity_event("evt.recent")
    fresh_db.log_activity_event("evt.ancient")
    with fresh_db.connect() as conn:
        conn.execute(
            "UPDATE activity_events SET created_at = ? WHERE event_type = ?",
            ("2000-01-01T00:00:00Z", "evt.ancient"),
        )
        conn.commit()

    events = fresh_db.get_activity_events(limit=10, max_age_hours=None)
    assert {e["event_type"] for e in events} == {"evt.recent", "evt.ancient"}


def test_activity_events_metadata_resilient_to_corrupt_json(fresh_db):
    """If metadata_json is somehow not valid JSON, get_activity_events
    must not crash — it should fall back to an empty dict."""
    fresh_db.log_activity_event("evt.test")
    with fresh_db.connect() as conn:
        conn.execute(
            "UPDATE activity_events SET metadata_json = ? WHERE event_type = ?",
            ("not-json", "evt.test"),
        )
        conn.commit()
    events = fresh_db.get_activity_events(limit=10)
    assert events[0]["metadata"] == {}
