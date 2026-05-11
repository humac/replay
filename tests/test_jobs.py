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


def _team_admin_headers(user_id: str, username: str, role: str = "team_admin") -> dict:
    import auth as _auth

    token = _auth.create_token(user_id, role, username)
    return {"Authorization": f"Bearer {token}"}


def _create_member(team_id: str, *, username: str = "job-coach", role: str = "team_admin") -> tuple[str, dict]:
    import db as _db

    user = _db.create_user(username, "hash", role, username.title())
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user["id"], role, _iso()),
        )
        conn.commit()
    return user["id"], _team_admin_headers(user["id"], username, role)


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

    team_id = _db.get_default_team()["id"]
    first = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=team_id, idempotency_key="draft:n1")
    second = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=team_id, idempotency_key="draft:n1")
    third = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=team_id)

    with _db.connect() as conn:
        assert _row_count(conn, kind="ai_draft", idempotency_key="draft:n1") == 1
        assert _row_count(conn, kind="ai_draft") == 2
    assert first == second
    assert third != first


def test_enqueue_idempotency_is_team_scoped(client):
    import db as _db
    from services import jobs

    default_team = _db.get_default_team()["id"]
    with _db.connect() as conn:
        conn.execute(
            "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES ('jobs-team-b', 'Jobs Team B', 'jobs-team-b', '9v9', ?)",
            (_iso(),),
        )
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES ('jobs-team-b-season', 'jobs-team-b', 'Default', '', '', ?)",
            (_iso(),),
        )
        conn.commit()

    first = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id=default_team, idempotency_key="draft:n1")
    second = jobs.enqueue("ai_draft", {"note_id": "n1"}, team_id="jobs-team-b", idempotency_key="draft:n1")

    assert first != second
    assert jobs.get(first)["team_id"] == default_team
    assert jobs.get(second)["team_id"] == "jobs-team-b"

@pytest.mark.asyncio
async def test_lease_claims_due_job_and_excludes_second_worker(client):
    import db as _db
    from services import jobs

    team_id = _db.get_default_team()["id"]
    job_id = jobs.enqueue("transcode", {"match_id": "m1", "slot": "full"}, team_id=team_id)

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
    import db as _db
    from services import jobs

    team_id = _db.get_default_team()["id"]
    jobs.enqueue("thumbnail", {"match_id": "m1"}, team_id=team_id)
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
    import db as _db
    from services import jobs

    team_id = _db.get_default_team()["id"]
    job_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=team_id)
    assert jobs.lease(["transcode"], "worker-a") is not None

    assert jobs.complete(job_id, "worker-b", {"ok": True}) == 0
    row = jobs.get(job_id)
    assert row["status"] == "running"
    assert row["locked_by"] == "worker-a"


@pytest.mark.asyncio
async def test_expired_lease_holder_cannot_mutate_terminal_state(client):
    import db as _db
    from services import jobs

    team_id = _db.get_default_team()["id"]
    complete_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=team_id)
    fail_id = jobs.enqueue("transcode", {"match_id": "m2"}, team_id=team_id)
    heartbeat_id = jobs.enqueue("transcode", {"match_id": "m3"}, team_id=team_id)
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
    import db as _db
    from services import jobs

    team_id = _db.get_default_team()["id"]
    job_id = jobs.enqueue("transcode", {"match_id": "m1"}, team_id=team_id)
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

    team_id = _db.get_default_team()["id"]
    requeue_id = jobs.enqueue("ai_draft", {"n": 1}, team_id=team_id, max_attempts=3)
    fail_id = jobs.enqueue("ai_draft", {"n": 2}, team_id=team_id, max_attempts=3)
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


@pytest.mark.asyncio
async def test_user_job_api_is_team_scoped_and_worker_routes_absent(client, auth_headers, monkeypatch):
    import db as _db
    from services import jobs

    created = await client.post(
        "/api/admin/teams",
        headers=auth_headers,
        json={"name": "Jobs Away", "slug": "jobs-away", "game_format": "9v9"},
    )
    assert created.status_code == 200, created.text
    other_team = created.json()
    default_team = _db.get_default_team()
    _user_id, default_headers = _create_member(default_team["id"], username="jobs-default-coach")
    _viewer_id, viewer_headers = _create_member(default_team["id"], username="jobs-viewer", role="viewer")
    # Internal enqueue (via the service, NOT the user route) is still allowed for
    # ai_draft — the user route is the only thing we lock down. This row stands
    # in for an ai_draft job belonging to a different team.
    other_job_id = jobs.enqueue("ai_draft", {"draft": "secret"}, team_id=other_team["id"])
    # User-route enqueue must use a real (transcode/thumbnail) kind backed by a
    # match the team owns. ai_draft via the user route is rejected at 422 — see
    # test_user_route_rejects_ai_draft_enqueue below.
    transcode_match_id = "job-api-match"
    other_match_id = "job-api-match-other"
    with _db.connect() as conn:
        _db.upsert_match(conn, {"id": transcode_match_id, "slug": transcode_match_id, "home_team": "Home", "away_team": "Away", "team_id": default_team["id"]})
        _db.upsert_match(conn, {"id": other_match_id, "slug": other_match_id, "home_team": "Home", "away_team": "Away", "team_id": other_team["id"]})
        conn.commit()
    transcode_job_id = jobs.enqueue(
        "transcode",
        {"match_id": transcode_match_id, "slot": "full", "src": "/srv/replay/private/raw.mp4", "dest": "/srv/replay/private/out.mp4"},
        team_id=default_team["id"],
    )

    denied_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": other_team["id"], "kind": "transcode", "payload": {"match_id": other_match_id, "slot": "full"}},
    )
    assert denied_create.status_code == 403

    unsupported_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "unknown_job", "payload": {"match_id": transcode_match_id}},
    )
    assert unsupported_create.status_code == 422

    invalid_payload_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "transcode", "payload": ["not", "an", "object"]},
    )
    assert invalid_payload_create.status_code == 422

    invalid_attempts_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "transcode", "payload": {"match_id": transcode_match_id}, "max_attempts": 0},
    )
    assert invalid_attempts_create.status_code == 422

    invalid_schedule_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "transcode", "payload": {"match_id": transcode_match_id}, "scheduled_at": "not-a-date"},
    )
    assert invalid_schedule_create.status_code == 422

    oversized_payload_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "transcode", "payload": {"match_id": transcode_match_id, "slot": "x" * 10001}},
    )
    assert oversized_payload_create.status_code == 422

    allowed_create = await client.post(
        "/api/jobs",
        headers=default_headers,
        json={"team_id": default_team["id"], "kind": "thumbnail", "payload": {"match_id": transcode_match_id}, "idempotency_key": "thumb:x"},
    )
    assert allowed_create.status_code == 200, allowed_create.text
    created_job = allowed_create.json()
    assert created_job["team_id"] == default_team["id"]
    assert created_job["payload"] == {"match_id": transcode_match_id}

    denied_list = await client.get(f"/api/jobs?team_id={other_team['id']}", headers=default_headers)
    assert denied_list.status_code == 403
    allowed_list = await client.get(f"/api/jobs?team_id={default_team['id']}", headers=default_headers)
    assert allowed_list.status_code == 200
    assert [row["id"] for row in allowed_list.json()] == [created_job["id"], transcode_job_id]

    denied_viewer_list = await client.get(f"/api/jobs?team_id={default_team['id']}", headers=viewer_headers)
    assert denied_viewer_list.status_code == 403
    denied_viewer_read = await client.get(f"/api/jobs/{created_job['id']}?team_id={default_team['id']}", headers=viewer_headers)
    assert denied_viewer_read.status_code == 403
    denied_viewer_cancel = await client.post(f"/api/jobs/{created_job['id']}/cancel?team_id={default_team['id']}", headers=viewer_headers)
    assert denied_viewer_cancel.status_code == 403

    transcode_read = await client.get(f"/api/jobs/{transcode_job_id}?team_id={default_team['id']}", headers=default_headers)
    assert transcode_read.status_code == 200
    assert transcode_read.json()["payload"] == {"match_id": transcode_match_id, "slot": "full"}

    running_job_id = jobs.enqueue("transcode", {"match_id": transcode_match_id, "slot": "half2"}, team_id=default_team["id"])
    assert jobs.start(running_job_id, "worker-running") is not None
    running_cancel = await client.post(f"/api/jobs/{running_job_id}/cancel?team_id={default_team['id']}", headers=default_headers)
    assert running_cancel.status_code == 409

    race_job_id = jobs.enqueue("transcode", {"match_id": transcode_match_id, "slot": "half1"}, team_id=default_team["id"])
    monkeypatch.setattr("server._jobs.cancel", lambda job_id, *, team_id: 0)
    raced_cancel = await client.post(f"/api/jobs/{race_job_id}/cancel?team_id={default_team['id']}", headers=default_headers)
    assert raced_cancel.status_code == 409

    masked_read = await client.get(
        f"/api/jobs/{other_job_id}?team_id={default_team['id']}",
        headers=default_headers,
    )
    assert masked_read.status_code == 404
    masked_cancel = await client.post(
        f"/api/jobs/{other_job_id}/cancel?team_id={default_team['id']}",
        headers=default_headers,
    )
    assert masked_cancel.status_code == 404

    for path in [
        "/api/jobs/lease",
        f"/api/jobs/{created_job['id']}/heartbeat",
        f"/api/jobs/{created_job['id']}/complete",
        f"/api/jobs/{created_job['id']}/fail",
    ]:
        resp = await client.post(path, headers=default_headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_route_rejects_ai_draft_enqueue(client):
    """POST /api/jobs with kind=ai_draft must NOT persist any raw payload to
    background_jobs.payload_json. The only AI draft API is POST /api/coach/ai/draft,
    and raw prompts / private source text must never land in the durable jobs
    table where ops / future workers can read them.
    """
    import db as _db

    default_team = _db.get_default_team()
    _user_id, headers = _create_member(default_team["id"], username="jobs-canary-coach")

    canary = "CANARY_RAW_PROMPT_AbC123_xyz789"
    resp = await client.post(
        "/api/jobs",
        headers=headers,
        json={
            "team_id": default_team["id"],
            "kind": "ai_draft",
            "payload": {"prompt": canary, "private_source_text": canary},
            "idempotency_key": f"draft:{canary}",
        },
    )
    assert resp.status_code == 422, resp.text
    body_text = resp.text
    # Server must not echo the canary in its 422 response body.
    assert canary not in body_text

    # And nothing must have landed in background_jobs.payload_json.
    with _db.connect() as conn:
        rows = conn.execute("SELECT payload_json, idempotency_key FROM background_jobs").fetchall()
    for row in rows:
        assert canary not in (row["payload_json"] or "")
        assert canary not in (row["idempotency_key"] or "")
