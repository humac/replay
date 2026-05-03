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
import re
import time
from collections import deque
from datetime import datetime, timezone
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

# How long without a new HLS segment before we treat the publisher as stale,
# even if MediaMTX still reports path.ready=true. Cameras (e.g. the XbotGo
# Falcon iOS app) can stop sending video keyframes while leaving the RTMP
# socket open with audio-only flowing — MediaMTX keeps the path "ready" but
# stops cutting new segments, so the playlist's last EXT-X-PROGRAM-DATE-TIME
# falls progressively further behind wall clock. The threshold needs to be
# larger than the worst-case real-streaming inter-segment gap on a slow
# uplink (observed up to ~60s on a 4G XbotGo Falcon).
STALE_SEGMENT_AGE_SECONDS = float(
    os.environ.get("LIVE_STALE_SEGMENT_AGE_SECONDS", "90")
)

_PDT_RE = re.compile(r"#EXT-X-PROGRAM-DATE-TIME:([^\r\n]+)")


def _first_variant_url(master_playlist: str, base_url: str) -> str | None:
    """Extract the first variant URL from a master HLS playlist.

    Master playlists are line-oriented: each ``#EXT-X-STREAM-INF`` tag is
    followed by exactly one URL line (relative or absolute). We don't need
    to pick the "best" variant — there's only ever one for the live stream
    — so we just return the first URL line we find.
    """
    found_inf = False
    for raw_line in master_playlist.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF"):
            found_inf = True
            continue
        if found_inf and not line.startswith("#"):
            if line.startswith("http://") or line.startswith("https://"):
                return line
            return f"{base_url}/{line}"
    return None


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


async def _last_segment_age(stream_key: str) -> float | None:
    """Seconds since the most recent EXT-X-PROGRAM-DATE-TIME in the live
    playlist, or ``None`` when the playlist can't be fetched or has no
    PDT entries (e.g. before the first segment cut).

    MediaMTX serves a two-level playlist regardless of `hlsVariant`:
    ``index.m3u8`` is a master playlist that points at a variant playlist
    like ``main_stream.m3u8?session=<uuid>``. The PDT entries live on the
    variant, so we fetch the master, parse out the first variant URL,
    then fetch that.
    """
    if not stream_key:
        return None
    base = f"{MEDIAMTX_HLS_URL}/{stream_path(stream_key)}"
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as c:
            master = await c.get(f"{base}/index.m3u8")
            if master.status_code != 200:
                return None
            variant_url = _first_variant_url(master.text, base)
            if not variant_url:
                return None
            resp = await c.get(variant_url)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    pdts = _PDT_RE.findall(resp.text)
    if not pdts:
        return None
    last = pdts[-1].strip()
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


async def check_publisher_active(stream_key: str) -> dict:
    """Return ``{"active": bool, "ready": bool, ...}`` for the live path.

    ``ready`` is true once MediaMTX has segments available for HLS playback;
    ``active`` is true while a publisher (the camera) is connected.

    Includes a stale-publisher override: if MediaMTX still reports the path
    as ready but no new HLS segment has been cut for STALE_SEGMENT_AGE_SECONDS,
    we treat the stream as offline. This covers the case where a camera (e.g.
    XbotGo Falcon) stops recording but leaves the RTMP socket open with
    audio-only data flowing — MediaMTX keeps the path "ready" but stops
    producing playable video segments.

    Order of operations:
      1. Hit ``/v3/paths/list`` first. If the target path isn't there, return
         immediately — there's no point fetching the HLS playlist for a path
         that doesn't exist on MediaMTX.
      2. Only when the path exists AND is ready, fan out the segment-age
         check. Skipping the playlist GET when the camera is offline cuts
         /api/live/status latency from ~2s (httpx waiting for a 404 on a
         path MediaMTX has never created) to ~30ms.
    """
    reachable, items = await _list_paths()
    if not reachable:
        return {"active": False, "ready": False, "reachable": False}

    target = stream_path(stream_key)
    match = next((p for p in items if (p.get("name") or "") == target), None)
    if match is None:
        return {"active": False, "ready": False, "reachable": True}

    # Only ask for segment age once we know MediaMTX has a path — otherwise
    # the HLS playlist GET will hang/404 while no publisher is connected.
    age = (
        await _last_segment_age(stream_key)
        if match.get("ready")
        else None
    )

    result = {
        "active": bool(match.get("ready") or match.get("source")),
        "ready": bool(match.get("ready")),
        "reachable": True,
        "tracks": match.get("tracks") or [],
        "bytes_received": match.get("bytesReceived"),
        "ready_time": match.get("readyTime"),
        "last_segment_age_seconds": age,
    }
    if age is not None and age > STALE_SEGMENT_AGE_SECONDS and (
        result["ready"] or result["active"]
    ):
        logger.info(
            "Live publisher marked stale: last segment %.1fs ago (threshold %.0fs).",
            age, STALE_SEGMENT_AGE_SECONDS,
            extra={"last_segment_age_s": round(age, 1), "threshold_s": STALE_SEGMENT_AGE_SECONDS},
        )
        result["active"] = False
        result["ready"] = False
    return result


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


async def proxy_hls(
    asset_path: str,
    stream_key: str,
    *,
    method: str = "GET",
    request_headers: dict | None = None,
    query_string: str = "",
) -> tuple[int, dict, AsyncIterator[bytes]]:
    """Stream a MediaMTX HLS asset back through the replay origin.

    Returns ``(status_code, headers, body_iterator)``.  The caller wraps the
    iterator in a ``StreamingResponse`` so the client gets the bytes as soon
    as MediaMTX produces them.

    ``asset_path`` is the path component the player asked for, e.g.
    ``index.m3u8`` or ``segment_42.ts``.  We map it onto MediaMTX's
    ``/live/<stream-key>/<asset_path>`` URL.

    ``method`` is forwarded as-is so HEAD probes from AVPlayer / AirPlay
    receivers reach MediaMTX intact.  ``request_headers`` lets the caller
    forward client headers like ``Range`` so segment fetches return
    ``206 Partial Content`` instead of a full body — Apple TV refuses to
    play HLS when a ranged request is answered with a 200.

    ``query_string`` is forwarded verbatim so MediaMTX's per-stream session
    tokens (``?session=<uuid>``) survive the round-trip. The master
    ``index.m3u8`` references variant playlists like
    ``main_stream.m3u8?session=…`` and MediaMTX 1.18+ returns 404 if the
    session token is missing on the variant fetch.
    """
    if ".." in asset_path or asset_path.startswith("/"):
        raise ValueError("invalid hls asset path")

    url = f"{MEDIAMTX_HLS_URL}/{stream_path(stream_key)}/{asset_path}"
    if query_string:
        url = f"{url}?{query_string}"
    client = httpx.AsyncClient(timeout=_PROXY_TIMEOUT)

    # Pass through only the conditional / range headers that affect the
    # response semantics.  Anything else (Host, Cookie, Authorization,
    # Origin) would either confuse MediaMTX or leak across origins.
    forward_keys = {"range", "if-range", "if-modified-since", "if-none-match"}
    upstream_headers = {
        k: v
        for k, v in (request_headers or {}).items()
        if k.lower() in forward_keys
    }

    # MediaMTX's HLS muxer reliably handles GET but historically returns
    # 404 for HEAD on the same path — which would defeat the whole point
    # of accepting HEAD here (AVPlayer / AirPlay receivers probe with
    # HEAD first and silently abort on 404).  Always issue GET upstream,
    # stream-mode so the body isn't buffered, and discard it locally
    # when the downstream method is HEAD.
    upstream_method = "GET" if method.upper() == "HEAD" else method
    try:
        req = client.build_request(upstream_method, url, headers=upstream_headers)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning(
            "MediaMTX HLS proxy failed for %s: %s", url, exc,
            extra={"url": url, "error": str(exc)},
        )
        raise

    # Forward only the headers a player cares about — drop hop-by-hop and
    # MediaMTX's internal CORS values (we set our own). Also drop MediaMTX's
    # Cache-Control (it sends no-store) so we can substitute our own.
    drop = {
        "transfer-encoding",
        "connection",
        "content-encoding",
        "cache-control",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-expose-headers",
    }
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in drop}

    # Cache-Control by asset type — gives a CDN (Cloudflare, BunnyCDN, etc.)
    # something to dedupe on. Playlists change every segment, so cache them
    # only briefly; segments are content-addressed (filenames embed a
    # session prefix + sequence number) and never get reused, so cache them
    # aggressively. Errors are never cached.
    lower = asset_path.lower()
    if resp.status_code >= 400:
        headers["Cache-Control"] = "no-store"
    elif lower.endswith(".m3u8"):
        headers["Cache-Control"] = "public, max-age=1, must-revalidate"
    elif lower.endswith((".ts", ".mp4", ".m4s")):
        headers["Cache-Control"] = "public, max-age=60, immutable"
    else:
        headers["Cache-Control"] = "no-store"

    # CORS: the Chromecast Default Media Receiver (and any future
    # cross-origin web client) fetches the playlist + segments from its
    # own iframe origin and requires permissive CORS to load HLS.
    # Expose Content-Length / Content-Range so range-aware players can
    # seek correctly.
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Range, If-Range, If-Modified-Since, If-None-Match"
    headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Range, Accept-Ranges, Date"
    headers.setdefault("Accept-Ranges", "bytes")

    async def _iter() -> AsyncIterator[bytes]:
        try:
            if method.upper() == "HEAD":
                # HEAD must not return a body, but we still need to release
                # the upstream connection.
                return
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return resp.status_code, headers, _iter()
