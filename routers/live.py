"""Live streaming domain routes: MediaMTX HLS proxy, publish auth webhook,
admin live config + key rotation, and the active-streams admin surface.

PR-BE 3/N — mechanical extraction from server.py. Handler bodies, decorator
paths, and the ``methods=[...]`` list on the HLS proxy ``api_route`` are
verbatim copies. Late imports from ``server`` break the circular import that
would otherwise occur because server.py imports this module to register the
router.

The root-level ``live.py`` service module (HLS proxy logic for the MediaMTX
sidecar) and ``streams.py`` registry are untouched; this file is the HTTP
layer only.
"""
from __future__ import annotations

import base64
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

import auth as _auth
import live as _live
import streams as _streams
from models import LiveAuthRequest, UnblockStreamRequest

router = APIRouter()


@router.get("/api/live/status")
async def live_status():
    """Public — does the camera have an active publish session?"""
    from server import _load_settings, _stream_key
    settings = await _load_settings()
    if settings.get("live_enabled", "1") != "1":
        return {"enabled": False, "active": False, "ready": False}
    key = await _stream_key()
    info = await _live.check_publisher_active(key)
    return {
        "enabled": True,
        "active": info["active"],
        "ready": info["ready"],
        "reachable": info.get("reachable", False),
    }


@router.api_route("/api/live/hls/{asset_path:path}", methods=["GET", "HEAD", "OPTIONS"])
async def live_hls_proxy(asset_path: str, request: Request):
    """Reverse-proxy MediaMTX's LL-HLS playlist + segments to the browser.

    Accepts HEAD so AVPlayer / AirPlay receivers can probe the URL before
    starting playback (a GET-only route returns 405 and the receiver
    silently aborts after the user enters the AirPlay PIN).  Accepts
    OPTIONS so cross-origin clients (Chromecast Default Media Receiver,
    browser fetch) can preflight.
    """
    from server import _load_settings, _stream_key, logger
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, If-Range, If-Modified-Since, If-None-Match",
                "Access-Control-Max-Age": "86400",
            },
        )

    settings = await _load_settings()
    if settings.get("live_enabled", "1") != "1":
        raise HTTPException(404, "Live streaming is disabled")
    if not asset_path:
        raise HTTPException(400, "Missing HLS asset path")

    ip = _streams.client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    if _streams.registry.is_blocked(ip, "live", None, None):
        return Response(status_code=403, content="Stream killed by admin")

    try:
        key = await _stream_key()
        status_code, headers, body = await _live.proxy_hls(
            asset_path,
            key,
            method=request.method,
            request_headers=dict(request.headers),
            query_string=request.url.query,
        )
    except ValueError:
        raise HTTPException(400, "Invalid HLS asset path")
    except Exception as exc:
        logger.warning("Live HLS proxy error for %s: %s", asset_path, exc)
        raise HTTPException(502, "Upstream live stream unavailable")

    if request.method.upper() == "HEAD":
        return StreamingResponse(body, status_code=status_code, headers=headers)

    session = _streams.registry.touch("live", None, None, ip, user_agent)
    wrapped = _streams.wrap_iter(body, session)
    return StreamingResponse(wrapped, status_code=status_code, headers=headers)


@router.post("/api/live/auth")
async def live_auth_webhook(body: LiveAuthRequest, request: Request):
    """Webhook MediaMTX calls to authorise an RTMP publish.

    Reads/api/etc. are excluded in mediamtx.yml so this only ever sees
    publish attempts.  Allow if the path matches the configured stream key.
    """
    from server import (
        LIVE_AUTH_ALLOW_INSECURE,
        LIVE_AUTH_SECRET,
        _LIVE_AUTH_RATE_LIMIT,
        _LIVE_AUTH_RATE_WINDOW,
        _live_auth_attempts,
        _stream_key,
        logger,
    )
    ip = _streams.client_ip(request)
    now = time.time()
    attempts = _live_auth_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LIVE_AUTH_RATE_WINDOW]
    if not attempts:
        _live_auth_attempts.pop(ip, None)
    if len(attempts) >= _LIVE_AUTH_RATE_LIMIT:
        raise HTTPException(429, "Too many requests")
    attempts.append(now)
    _live_auth_attempts[ip] = attempts

    if LIVE_AUTH_SECRET:
        # MediaMTX 1.18 dropped support for authHTTPHeaders, so we accept
        # the shared secret either as the X-Internal-Secret header (for
        # callers that can set headers) or as the password half of HTTP
        # Basic Auth in the URL (which is what MediaMTX uses now —
        # authHTTPAddress: http://_:<secret>@replay:8091/api/live/auth).
        provided = request.headers.get("x-internal-secret") or ""
        if not provided:
            auth_header = request.headers.get("authorization") or ""
            if auth_header.lower().startswith("basic "):
                try:
                    decoded = base64.b64decode(auth_header.split(None, 1)[1]).decode("utf-8", "replace")
                    _, _, provided = decoded.partition(":")
                except Exception:
                    provided = ""
        if not secrets.compare_digest(provided, LIVE_AUTH_SECRET):
            raise HTTPException(401, "Unauthorized")
    elif LIVE_AUTH_ALLOW_INSECURE:
        if not hasattr(live_auth_webhook, "_warned"):
            live_auth_webhook._warned = True
            logger.warning("LIVE_AUTH_SECRET is not set; insecure live auth is enabled via LIVE_AUTH_ALLOW_INSECURE=1")
    else:
        raise HTTPException(503, "Live auth misconfigured: set LIVE_AUTH_SECRET")

    key = await _stream_key()
    payload = body.model_dump()
    allowed, reason = _live.validate_publish_auth(payload, key)
    if not allowed:
        _live.record_rejection(payload, reason)
        logger.info(
            "Live auth rejected (%s): action=%s path=%s protocol=%s ip=%s",
            reason, body.action, body.path, body.protocol, body.ip,
            extra={"reason": reason, "action": body.action, "path": body.path,
                   "protocol": body.protocol, "ip": body.ip},
        )
        raise HTTPException(401, "Invalid stream key")
    logger.info(
        "Live auth accepted: ip=%s protocol=%s", body.ip, body.protocol,
        extra={"ip": body.ip, "protocol": body.protocol},
    )
    return {"ok": True}


@router.get("/api/admin/live/diagnostics")
async def admin_live_diagnostics(request: Request):
    """Admin: bundled diagnostics for live ingest troubleshooting."""
    from server import _stream_key
    _auth.require_role(request, "admin")
    key = await _stream_key()
    return await _live.get_diagnostics(key)


@router.get("/api/admin/live/config")
async def admin_live_config(request: Request):
    """Admin: full config including the stream key, plus a ready-to-paste RTMP URL."""
    from server import _load_settings, _stream_key
    _auth.require_role(request, "admin")
    settings = await _load_settings()
    key = await _stream_key()
    return {
        "enabled": settings.get("live_enabled", "1") == "1",
        "stream_key": key,
        "stream_path": _live.stream_path(key),
        "rtmp_public_url": settings.get("live_rtmp_public_url", "") or "",
        "offline_message": settings.get("live_offline_message", ""),
    }


@router.post("/api/admin/live/rotate-key")
async def admin_live_rotate_key(request: Request):
    """Admin: generate a new stream key and invalidate the old one."""
    import settings as _settings
    from server import MATCHES_LOCK, _log_activity, logger
    _auth.require_role(request, "admin")
    async with MATCHES_LOCK:
        new_key = _settings.rotate_stream_key_unlocked()
    actor = _auth.require_auth(request)["username"]
    logger.info("Live stream key rotated by %s", actor)
    _log_activity(
        "live.key_rotated",
        severity="warning",
        message="Live stream key rotated",
        actor=actor,
    )
    return {"ok": True, "stream_key": new_key, "stream_path": _live.stream_path(new_key)}


@router.get("/api/admin/streams")
async def admin_active_streams(request: Request):
    """Admin: list currently-active streaming connections + active kill blocks."""
    from server import _match_label
    _auth.require_role(request, "admin")
    return {
        "active": _streams.serialize_active(match_label_resolver=_match_label),
        "blocks": _streams.registry.list_blocks(),
    }


@router.post("/api/admin/streams/{session_id}/kill")
async def admin_kill_stream(session_id: str, request: Request):
    """Admin: cancel a running stream and short-list the (ip, target) so it can't immediately reconnect."""
    from server import _log_activity, logger
    user = _auth.require_role(request, "admin")
    killed = _streams.registry.kill(session_id)
    if not killed:
        raise HTTPException(404, "Session not found")
    logger.info("admin.action", extra={"action": "kill_stream", "actor": user["username"], "target_id": session_id})
    _log_activity(
        "stream.killed",
        severity="warning",
        message="Stream killed",
        actor=user["username"],
        metadata={"session_id": session_id},
    )
    return {"ok": True, "killed": True}


@router.delete("/api/admin/streams/blocks")
async def admin_unblock_stream(payload: UnblockStreamRequest, request: Request):
    """Admin: clear a kill-block early so the affected viewer can rejoin."""
    from server import _log_activity, logger
    user = _auth.require_role(request, "admin")
    key = (payload.ip, payload.kind, payload.match_id or "", payload.slot or "")
    cleared = _streams.registry.unblock(key)
    logger.info("admin.action", extra={"action": "unblock_stream", "actor": user["username"], "target_ip": payload.ip, "kind": payload.kind})
    if cleared:
        _log_activity(
            "stream.unblocked",
            severity="info",
            message="Stream block cleared",
            match_id=payload.match_id,
            slot=payload.slot,
            actor=user["username"],
            metadata={"ip": payload.ip, "kind": payload.kind},
        )
    return {"ok": True, "cleared": cleared}
