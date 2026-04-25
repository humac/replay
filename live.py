"""Live stream — MediaMTX bridge.

Wraps the small surface we expose to the rest of the app:

- ``check_publisher_active`` — ask the MediaMTX control API whether the
  configured stream path currently has an RTMP publisher.
- ``proxy_hls`` — reverse-proxy a request from the browser to MediaMTX's
  internal LL-HLS endpoint so the player never talks to MediaMTX directly.
- ``validate_publish_auth`` — the server-side check the MediaMTX
  ``authHTTPAddress`` webhook calls before accepting a publish.

The stream-key value lives in the settings table (private — not exposed via
``/api/settings``).  All MediaMTX URLs are configurable via env vars so the
test suite can point at fake endpoints.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import AsyncIterator

import httpx

import log as _log

logger = _log.setup("replay")

# Ring buffer of recent rejected publish attempts.  Sized small on purpose —
# we only want enough to debug "why is my camera being refused?" without
# turning the process into a security log.
_REJECTION_HISTORY_SIZE = 20
_recent_rejections: deque[dict] = deque(maxlen=_REJECTION_HISTORY_SIZE)

MEDIAMTX_HLS_URL = os.environ.get("MEDIAMTX_HLS_URL", "http://mediamtx:8888")
MEDIAMTX_API_URL = os.environ.get("MEDIAMTX_API_URL", "http://mediamtx:9997")

# Single configurable stream path. The full RTMP path is "live/<stream-key>".
STREAM_PATH_PREFIX = "live"

# Short timeouts — MediaMTX is on the same compose network so anything slow
# means it's down.
_STATUS_TIMEOUT = httpx.Timeout(3.0, connect=2.0)
_PROXY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def stream_path(stream_key: str) -> str:
    """The MediaMTX path name for the configured stream key."""
    return f"{STREAM_PATH_PREFIX}/{stream_key}"


def expected_publish_path(stream_key: str) -> str:
    """The full path string MediaMTX sends in the auth webhook on publish."""
    return stream_path(stream_key)


async def _list_paths() -> tuple[bool, list[dict]]:
    """Query MediaMTX for the full path list.

    We use ``/v3/paths/list`` rather than ``/v3/paths/get/<path>`` because
    the latter logs ``ERR [API] path not found`` every time we poll while
    no publisher is active — quickly drowning out useful log lines.
    Returns ``(reachable, items)``.
    """
    url = f"{MEDIAMTX_API_URL}/v3/paths/list"
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as c:
            resp = await c.get(url)
    except httpx.HTTPError as exc:
        logger.warning("MediaMTX path list query failed: %s", exc)
        return False, []
    if resp.status_code != 200:
        logger.warning("MediaMTX returned %s for %s", resp.status_code, url)
        return True, []
    items = resp.json().get("items") or []
    return True, items


async def _list_rtmp_conns() -> list[dict]:
    """Return the active RTMP connections MediaMTX is tracking, or [] on error."""
    url = f"{MEDIAMTX_API_URL}/v3/rtmpconns/list"
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as c:
            resp = await c.get(url)
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    return resp.json().get("items") or []


async def check_publisher_active(stream_key: str) -> dict:
    """Return ``{"active": bool, "ready": bool, ...}`` for the live path.

    ``ready`` is true once MediaMTX has segments available for HLS playback;
    ``active`` is true while a publisher (the camera) is connected.
    """
    reachable, items = await _list_paths()
    if not reachable:
        return {"active": False, "ready": False, "reachable": False}

    target = stream_path(stream_key)
    match = next((p for p in items if (p.get("name") or "") == target), None)
    if match is None:
        return {"active": False, "ready": False, "reachable": True}

    return {
        "active": bool(match.get("ready") or match.get("source")),
        "ready": bool(match.get("ready")),
        "reachable": True,
        "tracks": match.get("tracks") or [],
        "bytes_received": match.get("bytesReceived"),
        "ready_time": match.get("readyTime"),
    }


def validate_publish_auth(payload: dict, stream_key: str) -> tuple[bool, str]:
    """Decide whether MediaMTX should accept an incoming publish.

    Returns ``(allowed, reason)``.  Reads/api/etc. are excluded server-side
    via ``authHTTPExclude``, so the only action this needs to handle is
    ``publish``.  The path must exactly match ``live/<stream-key>``;
    protocol must be RTMP.
    """
    if not stream_key:
        return False, "no stream key configured"
    action = (payload.get("action") or "").lower()
    if action != "publish":
        return False, f"action {action!r} not allowed (only publish)"
    protocol = (payload.get("protocol") or "").lower()
    if protocol not in {"rtmp", "rtmps"}:
        return False, f"protocol {protocol!r} not allowed (only rtmp/rtmps)"
    path = (payload.get("path") or "").strip("/")
    if path != expected_publish_path(stream_key):
        return False, "stream key did not match"
    return True, "ok"


def record_rejection(payload: dict, reason: str) -> None:
    """Append a rejection to the ring buffer for the diagnostics endpoint."""
    _recent_rejections.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ip": payload.get("ip") or "",
        "action": payload.get("action") or "",
        "protocol": payload.get("protocol") or "",
        "path": payload.get("path") or "",
        "reason": reason,
    })


def recent_rejections() -> list[dict]:
    """Newest-first copy of the rejection ring buffer."""
    return list(reversed(_recent_rejections))


def clear_rejections() -> None:
    """Reset the ring buffer — used by tests to keep them isolated."""
    _recent_rejections.clear()


async def get_diagnostics(stream_key: str) -> dict:
    """Combined snapshot for the admin diagnostics view.

    Surfaces three things admins normally have to grep MediaMTX logs for:

    - reachability of the MediaMTX control API
    - the configured live path (publisher, ready, bytes received)
    - any other paths or RTMP connections currently open (even ones that
      haven't completed the publish handshake — the canonical "TCP socket
      is open but no RTMP frames flowing" case)
    - the most recent publish-auth rejections, with the reason MediaMTX
      was told to deny
    """
    reachable, items = await _list_paths()
    target_name = stream_path(stream_key) if stream_key else ""
    target = next((p for p in items if (p.get("name") or "") == target_name), None)
    rtmp_conns = await _list_rtmp_conns() if reachable else []

    return {
        "reachable": reachable,
        "stream_path": target_name,
        "publisher": _publisher_summary(target),
        "paths": [_path_summary(p) for p in items],
        "rtmp_connections": [_rtmp_conn_summary(c) for c in rtmp_conns],
        "recent_rejections": recent_rejections(),
    }


def _publisher_summary(item: dict | None) -> dict | None:
    if not item:
        return None
    return {
        "name": item.get("name"),
        "ready": bool(item.get("ready")),
        "source": item.get("source"),
        "tracks": item.get("tracks") or [],
        "bytes_received": item.get("bytesReceived"),
        "ready_time": item.get("readyTime"),
    }


def _path_summary(item: dict) -> dict:
    return {
        "name": item.get("name"),
        "ready": bool(item.get("ready")),
        "source_type": (item.get("source") or {}).get("type") if isinstance(item.get("source"), dict) else None,
        "bytes_received": item.get("bytesReceived"),
    }


def _rtmp_conn_summary(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "remote_addr": item.get("remoteAddr"),
        "state": item.get("state"),
        "path": item.get("path") or "",
        "bytes_received": item.get("bytesReceived"),
        "bytes_sent": item.get("bytesSent"),
        "created": item.get("created"),
    }


async def proxy_hls(asset_path: str, stream_key: str) -> tuple[int, dict, AsyncIterator[bytes]]:
    """Stream a MediaMTX HLS asset back through the replay origin.

    Returns ``(status_code, headers, body_iterator)``.  The caller wraps the
    iterator in a ``StreamingResponse`` so the client gets the bytes as soon
    as MediaMTX produces them.

    ``asset_path`` is the path component the player asked for, e.g.
    ``index.m3u8`` or ``segment_42.ts``.  We map it onto MediaMTX's
    ``/live/<stream-key>/<asset_path>`` URL.
    """
    if ".." in asset_path or asset_path.startswith("/"):
        raise ValueError("invalid hls asset path")

    url = f"{MEDIAMTX_HLS_URL}/{stream_path(stream_key)}/{asset_path}"
    client = httpx.AsyncClient(timeout=_PROXY_TIMEOUT)

    try:
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("MediaMTX HLS proxy failed for %s: %s", url, exc)
        raise

    # Forward only the headers a player cares about — drop hop-by-hop and
    # MediaMTX's internal CORS values (we set our own).
    drop = {
        "transfer-encoding",
        "connection",
        "content-encoding",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
    }
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in drop}
    headers.setdefault("Cache-Control", "no-store")

    async def _iter() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return resp.status_code, headers, _iter()
