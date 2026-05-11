"""Durable jobs queue routes.

PR-BE 11/N — mechanical extraction from server.py.

Routes moved (8 handlers):
    POST /api/jobs                              (team-scoped enqueue)
    GET  /api/jobs                              (team-scoped list)
    POST /api/jobs/lease                        (404 — worker-only, not web)
    POST /api/jobs/{job_id}/heartbeat           (404 — worker-only, not web)
    POST /api/jobs/{job_id}/complete            (404 — worker-only, not web)
    POST /api/jobs/{job_id}/fail                (404 — worker-only, not web)
    GET  /api/jobs/{job_id}                     (team-scoped read)
    POST /api/jobs/{job_id}/cancel              (team-scoped cancel)

Per CLAUDE.md (Phase 6.3): ``services/jobs.py`` is the internal queue
primitive. User-facing ``/api/jobs*`` routes are team-scoped for
enqueue/read/cancel only; the worker lifecycle endpoints (lease,
heartbeat, complete, fail) are intentionally surfaced here as 404s so
they cannot be invoked from browser sessions.

PR-S defense-in-depth invariant preserved: ``POST /api/jobs`` MUST
reject ``kind=ai_draft`` with a 422 (via ``_normalize_job_payload`` and
``_job_write_capability``). Both helpers still live in ``server.py``
alongside ``_serialize_job_for_api`` / ``_normalize_scheduled_at`` /
``_require_job_access`` / ``JOB_KIND_CAPABILITIES``. They are imported
late inside each handler so the rejection happens verbatim and to
break the ``server -> routers.jobs -> server`` import cycle that would
otherwise occur at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
from models import EnqueueJobRequest

router = APIRouter()


@router.post("/api/jobs")
async def enqueue_job(request: Request, body: EnqueueJobRequest):
    from server import (
        _jobs,
        _normalize_job_payload,
        _normalize_scheduled_at,
        _job_write_capability,
        _serialize_job_for_api,
        _tenancy,
    )

    user = _auth.require_auth(request)
    kind = body.kind
    payload = body.payload
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=body.team_id,
        require_role=_job_write_capability(kind),
        allow_global_admin_override=False,
    )
    team_id = str(scope.team["id"])
    payload = _normalize_job_payload(kind, payload, team_id)
    job_id = _jobs.enqueue(
        kind,
        payload,
        team_id=team_id,
        idempotency_key=body.idempotency_key,
        scheduled_at=_normalize_scheduled_at(body.scheduled_at),
        max_attempts=body.max_attempts,
        payload_version=body.payload_version,
    )
    job = _jobs.get(job_id, team_id=team_id)
    return _serialize_job_for_api(job)


@router.get("/api/jobs")
async def list_jobs(request: Request, team_id: str, status: str | None = None, kind: str | None = None, limit: int = 50):
    from server import (
        _jobs,
        _job_write_capability,
        _serialize_job_for_api,
        _tenancy,
    )

    user = _auth.require_auth(request)
    required_capability = _job_write_capability(kind) if kind else "match:write"
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role=required_capability,
        allow_global_admin_override=False,
    )
    rows = _jobs.list_for_team(str(scope.team["id"]), status=status, kind=kind, limit=limit)
    return [_serialize_job_for_api(row) for row in rows]


@router.post("/api/jobs/lease")
async def reject_worker_lease_route():
    raise HTTPException(404, "Not found")


@router.post("/api/jobs/{job_id}/heartbeat")
@router.post("/api/jobs/{job_id}/complete")
@router.post("/api/jobs/{job_id}/fail")
async def reject_worker_lifecycle_route(job_id: int):
    raise HTTPException(404, "Not found")


@router.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: int, team_id: str):
    from server import (
        _jobs,
        _require_job_access,
        _serialize_job_for_api,
        _tenancy,
    )

    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role="team:read",
        allow_global_admin_override=False,
    )
    job = _jobs.get(job_id, team_id=str(scope.team["id"]))
    if job is None:
        raise HTTPException(404, "Job not found")
    _require_job_access(request, user, team_id=str(scope.team["id"]), kind=job["kind"])
    return _serialize_job_for_api(job)


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int, team_id: str):
    from server import (
        _jobs,
        _require_job_access,
        _serialize_job_for_api,
        _tenancy,
    )

    user = _auth.require_auth(request)
    scope = _tenancy.resolve_scope(
        request,
        user,
        team_id=team_id,
        require_role="team:read",
        allow_global_admin_override=False,
    )
    resolved_team_id = str(scope.team["id"])
    job = _jobs.get(job_id, team_id=resolved_team_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    _require_job_access(request, user, team_id=resolved_team_id, kind=job["kind"])
    if job["status"] != "pending":
        raise HTTPException(409, "Only pending jobs can be cancelled")
    if _jobs.cancel(job_id, team_id=resolved_team_id) != 1:
        raise HTTPException(409, "Only pending jobs can be cancelled")
    refreshed = _jobs.get(job_id, team_id=resolved_team_id)
    return _serialize_job_for_api(refreshed)
