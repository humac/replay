"""Active streaming connection registry, client-IP resolution, and GeoIP.

Wired into the live HLS proxy and VOD endpoints in ``server.py`` / ``live.py``.
Exposes a small admin-facing API used by ``/api/admin/streams`` to list and
kill connections.

Everything here is in-memory only — the registry empties on process restart.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from fastapi import Request

import log as _log

logger = _log.setup("replay")

# ---------------------------------------------------------------------------
# Client IP resolution
# ---------------------------------------------------------------------------

# TRUSTED_PROXY controls whether IP-spoofable headers are honoured.
# "cloudflare" (default): trust CF-Connecting-IP / True-Client-IP / X-Forwarded-For.
# "none": ignore proxy headers and use the ASGI peer address directly.
# A bare deployment without Cloudflare must set TRUSTED_PROXY=none, otherwise
# an attacker can rotate X-Forwarded-For to bypass per-IP rate limits.
TRUSTED_PROXY = os.environ.get("TRUSTED_PROXY", "cloudflare").strip().lower()

_IP_HEADERS = ("cf-connecting-ip", "true-client-ip")


def client_ip(request: Request) -> str:
    """Resolve the client's real IP for a request."""
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY != "cloudflare":
        return peer
    headers = request.headers
    for name in _IP_HEADERS:
        val = headers.get(name)
        if val:
            return val.strip()
    fwd = headers.get("x-forwarded-for")
    if fwd:
        # First entry is the original client; subsequent entries are proxy hops.
        first = fwd.split(",", 1)[0].strip()
        if first:
            return first
    return peer


# ---------------------------------------------------------------------------
# GeoIP (offline MaxMind GeoLite2-City)
# ---------------------------------------------------------------------------

_GEO_DB_PATH = Path(
    os.environ.get(
        "GEOIP_DB_PATH",
        str(Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay")) / "app_assets" / "GeoLite2-City.mmdb"),
    )
)
_geo_reader = None
_geo_open_attempted = False


def _open_geo_reader():
    global _geo_reader, _geo_open_attempted
    if _geo_open_attempted:
        return _geo_reader
    _geo_open_attempted = True
    if not _GEO_DB_PATH.is_file():
        return None
    try:
        import geoip2.database  # type: ignore
        _geo_reader = geoip2.database.Reader(str(_GEO_DB_PATH))
        logger.info("GeoIP database loaded from %s", _GEO_DB_PATH)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("Failed to open GeoIP database at %s: %s", _GEO_DB_PATH, exc)
        _geo_reader = None
    return _geo_reader


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


@functools.lru_cache(maxsize=4096)
def geo_lookup(ip: str) -> dict | None:
    """Return ``{city, country, country_code}`` for an IP, or ``None``.

    Cached per-IP. Returns ``None`` when the GeoLite2 DB is missing, the IP is
    private/unknown, or the lookup fails — never raises.
    """
    if not ip or ip == "unknown" or _is_private(ip):
        return None
    reader = _open_geo_reader()
    if reader is None:
        return None
    try:
        resp = reader.city(ip)
    except Exception:
        return None
    return {
        "city": (resp.city.name or "") if resp.city else "",
        "country": (resp.country.name or "") if resp.country else "",
        "country_code": (resp.country.iso_code or "") if resp.country else "",
    }


# ---------------------------------------------------------------------------
# Stream registry
# ---------------------------------------------------------------------------

# Idle timeout for HLS sessions (each segment fetch refreshes last_activity;
# after this many seconds without a new fetch we drop the session from the
# active list). Picked just above the worst-case live segment duration plus
# a bit of slack.
HLS_IDLE_SECONDS = 15

# How long a kill-block stays in effect — long enough to keep the next few
# segment polls / playlist refreshes from re-attaching, short enough that
# admins don't have to remember to clear it.
DEFAULT_BLOCK_TTL = 300


@dataclass
class StreamSession:
    id: str
    kind: str  # "live" | "vod-hls" | "vod-mp4"
    match_id: str | None
    slot: str | None
    ip: str
    user_agent: str
    geo: dict | None
    started_at: float
    last_activity: float
    bytes_sent: int = 0
    cancel: asyncio.Event = field(default_factory=asyncio.Event)

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "id": self.id,
            "kind": self.kind,
            "match_id": self.match_id,
            "slot": self.slot,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "geo": self.geo,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "duration_seconds": round(now - self.started_at, 1),
            "idle_seconds": round(now - self.last_activity, 1),
            "bytes_sent": self.bytes_sent,
        }


def _block_key(ip: str, kind: str, match_id: str | None, slot: str | None) -> tuple:
    return (ip, kind, match_id or "", slot or "")


class StreamRegistry:
    """In-memory active-session registry plus a short-lived blocklist.

    All operations are O(n) on a typical set (dozens of sessions), so we don't
    bother indexing — simplicity wins over scale here.

    Session keying uses (ip, user_agent) as a proxy for viewer identity.  This
    deliberately under-counts viewers behind carrier-grade NAT (CGN): multiple
    subscribers sharing one public IP + the same UA string collapse into a
    single session.  This is a known limitation — documenting, not fixing,
    since there is no reliable viewer-identity signal without auth cookies.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, StreamSession] = {}
        # blocklist: {key_tuple: monotonic expiry} — monotonic so NTP jumps
        # cannot permanently strand a block entry.
        self._blocks: dict[tuple, float] = {}

    # ----- session lifecycle -----

    def _build(
        self,
        kind: str,
        match_id: str | None,
        slot: str | None,
        ip: str,
        user_agent: str,
    ) -> StreamSession:
        now = time.time()
        return StreamSession(
            id=uuid.uuid4().hex,
            kind=kind,
            match_id=match_id,
            slot=slot,
            ip=ip,
            user_agent=user_agent or "",
            geo=geo_lookup(ip),
            started_at=now,
            last_activity=now,
        )

    def touch(
        self,
        kind: str,
        match_id: str | None,
        slot: str | None,
        ip: str,
        user_agent: str,
    ) -> StreamSession:
        """Find-or-create an HLS-style session keyed by (kind, match_id, slot, ip, ua).

        Used for HLS playlist + segment fetches where each request is a brand
        new HTTP connection but the *viewer* is one logical session.
        """
        for s in self._sessions.values():
            if (
                s.kind == kind
                and s.match_id == match_id
                and s.slot == slot
                and s.ip == ip
                and s.user_agent == (user_agent or "")
                and not s.cancel.is_set()
            ):
                s.last_activity = time.time()
                return s
        sess = self._build(kind, match_id, slot, ip, user_agent)
        self._sessions[sess.id] = sess
        logger.info(
            "Stream started",
            extra={
                "session_id": sess.id,
                "ip": sess.ip,
                "match_id": sess.match_id,
                "slot": sess.slot,
            },
        )
        return sess

    def register_long(
        self,
        kind: str,
        match_id: str | None,
        slot: str | None,
        ip: str,
        user_agent: str,
    ) -> StreamSession:
        """Register an always-new long-lived session (e.g. one MP4 range request)."""
        sess = self._build(kind, match_id, slot, ip, user_agent)
        self._sessions[sess.id] = sess
        logger.info(
            "Stream started",
            extra={
                "session_id": sess.id,
                "ip": sess.ip,
                "match_id": sess.match_id,
                "slot": sess.slot,
            },
        )
        return sess

    def unregister(self, session_id: str) -> None:
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            return
        logger.info(
            "Stream ended",
            extra={
                "session_id": sess.id,
                "ip": sess.ip,
                "match_id": sess.match_id,
                "slot": sess.slot,
            },
        )

    def add_bytes(self, session_id: str, n: int) -> None:
        sess = self._sessions.get(session_id)
        if sess is None:
            return
        sess.bytes_sent += n
        sess.last_activity = time.time()

    def kill(self, session_id: str, ttl: int = DEFAULT_BLOCK_TTL) -> bool:
        """Cancel an active session and add its key to the blocklist."""
        sess = self._sessions.get(session_id)
        if sess is None:
            return False
        sess.cancel.set()
        self.block(_block_key(sess.ip, sess.kind, sess.match_id, sess.slot), ttl=ttl)
        logger.info(
            "Stream killed",
            extra={
                "session_id": sess.id,
                "ip": sess.ip,
                "match_id": sess.match_id,
                "slot": sess.slot,
            },
        )
        return True

    def list_active(self) -> list[StreamSession]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> StreamSession | None:
        return self._sessions.get(session_id)

    # ----- blocklist -----

    def block(self, key: tuple, ttl: int = DEFAULT_BLOCK_TTL) -> None:
        self._blocks[key] = time.monotonic() + ttl

    def unblock(self, key: tuple) -> bool:
        return self._blocks.pop(key, None) is not None

    def is_blocked(
        self,
        ip: str,
        kind: str,
        match_id: str | None,
        slot: str | None,
    ) -> bool:
        key = _block_key(ip, kind, match_id, slot)
        expiry = self._blocks.get(key)
        if expiry is None:
            return False
        if expiry <= time.monotonic():
            self._blocks.pop(key, None)
            return False
        return True

    def list_blocks(self) -> list[dict]:
        now_mono = time.monotonic()
        now_wall = time.time()
        out = []
        for (ip, kind, match_id, slot), expiry in list(self._blocks.items()):
            if expiry <= now_mono:
                self._blocks.pop((ip, kind, match_id, slot), None)
                continue
            remaining = expiry - now_mono
            out.append({
                "ip": ip,
                "kind": kind,
                "match_id": match_id or None,
                "slot": slot or None,
                "expires_at": now_wall + remaining,
                "expires_in_seconds": round(remaining, 1),
            })
        return out

    # ----- maintenance -----

    def sweep(self, idle_seconds: float = HLS_IDLE_SECONDS) -> int:
        """Drop idle HLS sessions and expired blocks. Returns count of pruned sessions."""
        now_wall = time.time()
        now_mono = time.monotonic()
        dead: list[str] = []
        for sid, sess in self._sessions.items():
            # MP4 sessions are removed by their handler's try/finally; only
            # touch HLS-style sessions here.
            if sess.kind in ("live", "vod-hls") and now_wall - sess.last_activity > idle_seconds:
                dead.append(sid)
        for sid in dead:
            self.unregister(sid)
        # Prune expired blocks (monotonic expiry, unaffected by NTP jumps)
        expired_keys = [k for k, exp in self._blocks.items() if exp <= now_mono]
        for k in expired_keys:
            self._blocks.pop(k, None)
        return len(dead)

    def reset(self) -> None:
        """Test helper — clear all state."""
        self._sessions.clear()
        self._blocks.clear()


# Module-level singleton.
registry = StreamRegistry()


# ---------------------------------------------------------------------------
# Throughput sampling — used by the Performance Tuning admin panel.
#
# A small ring buffer of {ts, live_bps_in, live_bps_out, vod_bps_out,
# active_sessions} samples. Two cadences:
#   - "slow"  → sampled every `interval_seconds` from sweeper_task (~10 s)
#   - "fast"  → during a 60-s capture window, sampled every 1 s
#
# Capture mode is started by an admin via /api/admin/performance/capture and
# auto-disengages after the configured window.
# ---------------------------------------------------------------------------

from collections import deque as _deque

_throughput_samples: _deque = _deque(maxlen=600)  # 1 hour at 6/min, or 10 min at 60/min
_capture_state = {
    "fast": False,        # True while inside the 1-Hz window
    "expires_mono": 0.0,  # monotonic deadline; sweeper drops back to slow
}
_last_session_bytes: dict[str, int] = {}  # session_id -> last seen total bytes


def _throughput_sample(now_wall: float) -> dict:
    """Compute one sample by diffing per-session byte counters since the
    previous sample. Stored counters are session-lifetime totals, so this is
    a delta-of-deltas pattern rather than a per-interval reset."""
    live_in = 0  # we don't currently track ingress on live publishers here
    live_out_delta = 0
    vod_out_delta = 0
    active_live = 0
    active_vod = 0
    seen_ids: set[str] = set()
    for sess in registry.list_active():
        seen_ids.add(sess.id)
        prev = _last_session_bytes.get(sess.id, 0)
        delta = max(0, sess.bytes_sent - prev)
        _last_session_bytes[sess.id] = sess.bytes_sent
        if sess.kind == "live":
            live_out_delta += delta
            active_live += 1
        else:
            vod_out_delta += delta
            active_vod += 1
    # Drop entries for sessions that vanished so the dict doesn't grow unbounded.
    for sid in list(_last_session_bytes.keys()):
        if sid not in seen_ids:
            _last_session_bytes.pop(sid, None)
    return {
        "ts": now_wall,
        "live_bps_in": live_in,
        "live_bps_out_delta": live_out_delta,
        "vod_bps_out_delta": vod_out_delta,
        "active_live": active_live,
        "active_vod": active_vod,
    }


def get_throughput_samples(limit: int | None = None) -> list[dict]:
    samples = list(_throughput_samples)
    if limit is not None and limit > 0:
        return samples[-limit:]
    return samples


def start_capture_window(seconds: float = 60.0) -> dict:
    _capture_state["fast"] = True
    _capture_state["expires_mono"] = time.monotonic() + max(5.0, min(600.0, seconds))
    return capture_status()


def capture_status() -> dict:
    if _capture_state["fast"] and time.monotonic() >= _capture_state["expires_mono"]:
        _capture_state["fast"] = False
    remaining = max(0.0, _capture_state["expires_mono"] - time.monotonic()) if _capture_state["fast"] else 0.0
    return {
        "fast": _capture_state["fast"],
        "remaining_seconds": round(remaining, 1),
    }


async def wrap_iter(body, session: StreamSession):
    """Wrap an async byte iterator so the registry sees bytes_sent + kills.

    On each chunk: bumps the session's byte counter and last_activity, then
    checks the cancel event so an admin kill stops sending mid-stream. The
    session is *not* unregistered when the iterator drains — HLS playback is
    a sequence of short fetches, so we let the idle sweeper close it out.
    """
    try:
        async for chunk in body:
            if session.cancel.is_set():
                break
            registry.add_bytes(session.id, len(chunk))
            yield chunk
    finally:
        # The upstream iterator's finally handles connection cleanup.
        pass


def wrap_sync_iter(body, session: StreamSession):
    """Sync-generator variant for File-backed range responses.

    FastAPI's StreamingResponse accepts both sync and async iterators; the MP4
    range path uses a sync generator so we mirror the wrapper's shape here.
    """
    try:
        for chunk in body:
            if session.cancel.is_set():
                break
            registry.add_bytes(session.id, len(chunk))
            yield chunk
    finally:
        registry.unregister(session.id)


async def sweeper_task(interval_seconds: float = 5.0) -> None:
    """Background coroutine: prunes idle sessions, expires blocks, and feeds
    the throughput-sampling ring buffer used by the Performance Tuning panel.

    Cadence: every `interval_seconds` normally; during a capture window we
    sample at 1 Hz so the export has higher-resolution data to analyze.
    """
    while True:
        try:
            # capture_status() handles auto-expiry of the fast window.
            cap = capture_status()
            sleep_for = 1.0 if cap["fast"] else interval_seconds
            await asyncio.sleep(sleep_for)
            registry.sweep()
            sample = _throughput_sample(time.time())
            sample["interval_seconds"] = sleep_for
            sample["bps_live_out"] = round(sample["live_bps_out_delta"] * 8 / sleep_for, 1)
            sample["bps_vod_out"] = round(sample["vod_bps_out_delta"] * 8 / sleep_for, 1)
            _throughput_samples.append(sample)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover — keep loop alive on bugs
            logger.warning("Stream sweeper error: %s", exc)


# ---------------------------------------------------------------------------
# Convenience: build the JSON payload for the admin endpoint
# ---------------------------------------------------------------------------

def serialize_active(
    match_label_resolver=None,
) -> list[dict]:
    """Return all active sessions as dicts, optionally enriched with match labels."""
    out = []
    for sess in registry.list_active():
        d = sess.to_dict()
        if match_label_resolver and sess.match_id:
            try:
                d["match_label"] = match_label_resolver(sess.match_id)
            except Exception:
                d["match_label"] = None
        else:
            d["match_label"] = None
        out.append(d)
    # Newest first feels right for an admin "what's happening now" view.
    out.sort(key=lambda x: x["started_at"], reverse=True)
    return out
