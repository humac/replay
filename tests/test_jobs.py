from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone

import pytest


def _iso(seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _row_count(conn, *, kind: str | None = None, idempotency_key: str | None = None) -> int:
    clauses = []
    params = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if idempotency_key is not None:
        clauses.append("idempotency_key = ?")
        params.append(idempotency_key)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(f"SELECT COUNT(*) AS c FROM background_jobs {where}", params).fetchone()["c"]


# The durable-jobs queue still enqueues with a constant team_id ("default") even
# though the multi-tenant layer is gone; ``services/jobs.py`` treats team_id as an
# opaque partition string with no FK to a teams table.
TEAM_ID = "default"


@pytest.mark.asyncio
async def test_background_jobs_schema_and_indexes_exist(client):
    import db as _db

    with _db.connect() as conn:
        columns = {row["name"]: row["type"].upper() for row in conn.execute("PRAGMA table_info(background_jobs)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(background_jobs)")}

    assert columns["id"] == "INTEGER"
    assert columns["team_id"] == "TEXT"
    assert columns["kind"] == "TEXT"
    assert columns["payload_json"] == "TEXT"
    assert columns["status"] == "TEXT"
    assert "idx_jobs_due" in indexes
    assert "idx_jobs_lease" in indexes
    assert "idx_jobs_team" in indexes
    assert "idx_jobs_idempotency" in indexes


@pytest.mark.asyncio
async def test_enqueue_idempotency_reuses_existing_job(client):
    import db as _db
    from services import jobs

    first = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=TEAM_ID, idempotency_key="draft:n1")
    second = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=TEAM_ID, idempotency_key="draft:n1")
    third = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=TEAM_ID)

    with _db.connect() as conn:
        assert _row_count(conn, kind="ai_draft", idempotency_key="draft:n1") == 1
        assert _row_count(conn, kind="ai_draft") == 2
    assert first == second
    assert third != first


@pytest.mark.asyncio
async def test_lease_claims_due_job_and_excludes_second_worker(client):
    from services import jobs

    job_id = jobs.enqueue("transcode", {"match_id": "m1", "slot": "full"}, team_id=TEAM_ID)

    first = jobs.lease(["transcode"], "worker-a", lease_seconds=90)
    second = jobs.lease(["transcode"], "worker-b")

    assert first is not None
    assert first["id"] == job_id
    assert first["status"] == "running"
    assert first["locked_by"] == "worker-a"
    assert first["attempts"] == 1
    assert second is None


@pytest.mark.asyncio
async def test_concurrent_lease_exclusion_with_two_threads(client):
    from services import jobs

    jobs.enqueue("thumbnail", {"match_id": "m1"}, team_id=TEAM_ID)
    barrier = threading.Barrier(2)
    results = []

    def worker(worker_id: str) -> None:
        import db as thread_db
        from services import jobs as thread_jobs

        thread_db.close_thread_connection()
        barrier.wait()
        results.append(thread_jobs.lease(["thumbnail"], worker_id))
        thread_db.close_thread_connection()

    threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    claimed = [row for row in results if row is not None]
    missed = [row for row in results if row is None]
    assert len(claimed) == 1
    assert len(missed) == 1


@pytest.mark.asyncio
async def test_stale_worker_completion_is_rejected(client):
    from services import jobs

    job_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=TEAM_ID)
    assert jobs.lease(["transcode"], "worker-a") is not None

    assert jobs.complete(job_id, "worker-b", {"ok": True}) == 0
    row = jobs.get(job_id)
    assert row["status"] == "running"
    assert row["locked_by"] == "worker-a"


@pytest.mark.asyncio
async def test_expired_lease_holder_cannot_mutate_terminal_state(client):
    import db as _db
    from services import jobs

    complete_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=TEAM_ID)
    fail_id = jobs.enqueue("transcode", {"match_id": "m2"}, team_id=TEAM_ID)
    heartbeat_id = jobs.enqueue("transcode", {"match_id": "m3"}, team_id=TEAM_ID)
    assert jobs.lease(["transcode"], "worker-complete") is not None
    assert jobs.lease(["transcode"], "worker-fail") is not None
    assert jobs.lease(["transcode"], "worker-heartbeat") is not None
    with _db.connect() as conn:
        conn.execute("UPDATE background_jobs SET locked_until=? WHERE id IN (?, ?, ?)", (_iso(-60), complete_id, fail_id, heartbeat_id))
        conn.commit()

    assert jobs.complete(complete_id, "worker-complete", {"ok": True}) == 0
    assert jobs.fail(fail_id, "worker-fail", "late failure") == 0
    assert jobs.heartbeat(heartbeat_id, "worker-heartbeat", lease_seconds=120) == 0
    assert jobs.get(complete_id)["status"] == "running"
    assert jobs.get(fail_id)["status"] == "running"
    assert jobs.get(heartbeat_id)["status"] == "running"


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_only_for_holder(client):
    from services import jobs

    job_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=TEAM_ID)
    leased = jobs.lease(["transcode"], "worker-a", lease_seconds=30)
    assert leased is not None

    assert jobs.heartbeat(job_id, "worker-b", lease_seconds=120) == 0
    assert jobs.heartbeat(job_id, "worker-a", lease_seconds=120) == 1
    refreshed = jobs.get(job_id)
    assert refreshed["locked_until"] > leased["locked_until"]
    assert refreshed["locked_by"] == "worker-a"


@pytest.mark.asyncio
async def test_recover_stuck_requeues_then_fails_when_attempts_exhausted(client):
    import db as _db
    from services import jobs

    requeue_id = jobs.enqueue("ai_draft", {"n": 1}, team_id=TEAM_ID, max_attempts=3)
    fail_id = jobs.enqueue("ai_draft", {"n": 2}, team_id=TEAM_ID, max_attempts=3)
    with _db.connect() as conn:
        conn.execute(
            "UPDATE background_jobs SET status='running', attempts=1, locked_by='old', locked_until=? WHERE id=?",
            (_iso(-120), requeue_id),
        )
        conn.execute(
            "UPDATE background_jobs SET status='running', attempts=3, locked_by='old', locked_until=? WHERE id=?",
            (_iso(-120), fail_id),
        )
        conn.commit()

    result = jobs.recover_stuck()

    assert result == {"requeued": 1, "failed": 1}
    assert jobs.get(requeue_id)["status"] == "pending"
    failed = jobs.get(fail_id)
    assert failed["status"] == "failed"
    assert failed["error_text"] == "exceeded max_attempts after stuck recovery"


@pytest.mark.asyncio
async def test_job_recovery_loop_runs_recover_until_cancelled(client, monkeypatch):
    import server

    calls = 0

    def fake_recover():
        nonlocal calls
        calls += 1
        return {"requeued": 0, "failed": 0}

    monkeypatch.setattr(server._jobs, "recover_stuck", fake_recover)
    task = asyncio.create_task(server._job_recovery_loop(interval_seconds=0.01))
    await asyncio.sleep(0.025)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 1
