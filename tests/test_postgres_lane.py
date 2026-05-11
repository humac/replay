from __future__ import annotations

import os
import uuid

import pytest

import db as _db


def test_configured_db_backend_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REPLAY_DB_BACKEND", raising=False)

    assert _db.configured_db_backend() == "sqlite"


def test_configured_db_backend_can_be_selected_explicitly(monkeypatch):
    monkeypatch.setenv("REPLAY_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert _db.configured_db_backend() == "postgres"


def test_database_url_implies_postgres_backend(monkeypatch):
    monkeypatch.delenv("REPLAY_DB_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://replay:secret@localhost:5432/replay")

    assert _db.configured_db_backend() == "postgres"


def test_psycopg_style_database_url_implies_postgres_backend(monkeypatch):
    monkeypatch.delenv("REPLAY_DB_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://replay:secret@localhost:5432/replay")

    assert _db.configured_db_backend() == "postgres"


def test_invalid_db_backend_fails_fast(monkeypatch):
    monkeypatch.setenv("REPLAY_DB_BACKEND", "mysql")

    with pytest.raises(RuntimeError, match="REPLAY_DB_BACKEND"):
        _db.configured_db_backend()


def _postgres_url_or_skip() -> str:
    if os.getenv("REPLAY_RUN_LIVE_POSTGRES_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("live Postgres smoke tests require REPLAY_RUN_LIVE_POSTGRES_TESTS=1")
    if os.getenv("REPLAY_DB_BACKEND", "").strip().lower() != "postgres":
        pytest.skip("live Postgres smoke tests require REPLAY_DB_BACKEND=postgres")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("DATABASE_URL does not point to Postgres")
    return url


def test_live_postgres_tests_require_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("REPLAY_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://replay:secret@localhost:5432/replay")
    monkeypatch.delenv("REPLAY_RUN_LIVE_POSTGRES_TESTS", raising=False)

    with pytest.raises(pytest.skip.Exception, match="REPLAY_RUN_LIVE_POSTGRES_TESTS"):
        _postgres_url_or_skip()


def test_live_postgres_tests_require_postgres_backend(monkeypatch):
    monkeypatch.setenv("REPLAY_RUN_LIVE_POSTGRES_TESTS", "1")
    monkeypatch.setenv("REPLAY_DB_BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "postgresql://replay:secret@localhost:5432/replay")

    with pytest.raises(pytest.skip.Exception, match="REPLAY_DB_BACKEND=postgres"):
        _postgres_url_or_skip()


@pytest.mark.postgres
def test_postgres_lane_can_connect_and_round_trip_rows():
    url = _postgres_url_or_skip()

    with _db.connect_postgres(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            assert cur.fetchone()["ok"] == 1


@pytest.mark.postgres
def test_postgres_lane_has_transactional_behavior():
    url = _postgres_url_or_skip()

    with _db.connect_postgres(url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE replay_pg_txn_smoke (id integer)")
            cur.execute("INSERT INTO replay_pg_txn_smoke (id) VALUES (1)")
            conn.rollback()
            cur.execute("CREATE TEMP TABLE replay_pg_txn_smoke (id integer)")
            cur.execute("SELECT count(*) AS count FROM replay_pg_txn_smoke")
            assert cur.fetchone()["count"] == 0


@pytest.mark.postgres
def test_postgres_lane_supports_jsonb_and_skip_locked():
    url = _postgres_url_or_skip()
    conn1 = _db.connect_postgres(url)
    conn2 = _db.connect_postgres(url)
    table_name = f"replay_pg_lane_smoke_{uuid.uuid4().hex}"
    try:
        with conn1.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE {table_name} (
                    id integer primary key,
                    payload jsonb not null,
                    status text not null
                )
                """
            )
            cur.execute(
                f"INSERT INTO {table_name} (id, payload, status) VALUES (%s, %s::jsonb, %s)",
                (1, '{"kind":"smoke"}', "pending"),
            )
            conn1.commit()

        cur1 = conn1.cursor()
        cur1.execute("BEGIN")
        cur1.execute(
            f"SELECT id FROM {table_name} WHERE status = 'pending' "
            "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        assert cur1.fetchone()["id"] == 1

        cur2 = conn2.cursor()
        cur2.execute("BEGIN")
        cur2.execute(
            f"SELECT id FROM {table_name} WHERE status = 'pending' "
            "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        assert cur2.fetchone() is None
        conn2.rollback()
        conn1.rollback()
    finally:
        with conn1.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn1.commit()
        conn1.close()
        conn2.close()
