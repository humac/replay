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
from typing import AsyncIterator

import httpx

import log as _log

logger = _log.setup("replay")

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


async def check_publisher_active(stream_key: str) -> dict:
    """Return ``{"active": bool, "ready": bool, ...}`` for the live path.

    ``ready`` is true once MediaMTX has segments available for HLS playback;
    ``active`` is true while a publisher (the camera) is connected.
    """
    url = f"{MEDIAMTX_API_URL}/v3/paths/get/{stream_path(stream_key)}"
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as c:
            resp = await c.get(url)
    except httpx.HTTPError as exc:
        logger.warning("MediaMTX status query failed: %s", exc)
        return {"active": False, "ready": False, "reachable": False}

    if resp.status_code == 404:
        return {"active": False, "ready": False, "reachable": True}
    if resp.status_code != 200:
        logger.warning("MediaMTX returned %s for %s", resp.status_code, url)
        return {"active": False, "ready": False, "reachable": True}

    data = resp.json()
    return {
        "active": bool(data.get("ready") or data.get("source")),
        "ready": bool(data.get("ready")),
        "reachable": True,
        "tracks": data.get("tracks") or [],
        "bytes_received": data.get("bytesReceived"),
        "ready_time": data.get("readyTime"),
    }


def validate_publish_auth(payload: dict, stream_key: str) -> bool:
    """Decide whether MediaMTX should accept an incoming publish.

    Reads/api/etc. are excluded server-side via ``authHTTPExclude``, so the
    only action this needs to handle is ``publish``.  The path must exactly
    match ``live/<stream-key>``; protocol must be RTMP.
    """
    if not stream_key:
        return False
    action = (payload.get("action") or "").lower()
    if action != "publish":
        # Defense in depth — exclusions are configured in mediamtx.yml but if
        # someone strips them we still want to deny non-publish actions here.
        return False
    protocol = (payload.get("protocol") or "").lower()
    if protocol not in {"rtmp", "rtmps"}:
        return False
    path = (payload.get("path") or "").strip("/")
    return path == expected_publish_path(stream_key)


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
