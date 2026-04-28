# Replay Agent Guide

This repository is a small FastAPI + vanilla JS application for uploading, processing, and replaying soccer match videos.

## Stack

- Backend: `server.py` (route registration + entrypoint) with modular services
- Frontend: `index.html`, `script.js` (ES module entry point), `js/` (module mixins), `styles.css`
- Storage: SQLite in `replay.db` plus filesystem media files
- Media pipeline: `media.py` wrapping `ffmpeg` and `ffprobe`
- Testing: `pytest` + `pytest-asyncio` + `httpx` (see `tests/`)
- CI: GitHub Actions (`.github/workflows/ci.yml`)
- Runtime: direct Python or Docker Compose
- Docs: `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`

## Key Files

- `server.py`: API routes, SPA serving, async lock wrappers, entrypoint
- `db.py`: SQLite connection pool, schema migrations, match CRUD helpers
- `auth.py`: multi-user authentication, token management, password hashing (scrypt), role-based access, login rate limiting, origin validation
- `settings.py`: app settings persistence, rendering helpers, `TUNING_KNOBS` schema (typed validation + range clamps for performance/upload/encoder knobs), env-fallback-on-first-load, `settings_audit` write helper, typed read helpers (`get_int`/`get_float`/`get_bool`/`get_str`/`get_hls_variant_presets`)
- `uploads.py`: upload session lifecycle (create, chunk, complete, cleanup)
- `media.py`: ffmpeg/ffprobe probing, transcoding (QSV / NVENC / VAAPI / CPU, auto-selected via `select_hwaccel()` — overridable via the `replay_hwaccel` admin setting or the legacy `REPLAY_HWACCEL` env var) with real-time progress tracking, resilient QSV→VAAPI→CPU fallback chain, HLS variant generation (capped at 2 simultaneous variants via `_hls_semaphore`), thumbnail extraction; `get_all_transcode_progress()` returns all active jobs; `get_gpu_health()` returns session-lifetime GPU encode counters (per-method + aggregate `succeeded`/`failed`); `_transcode_history` ring buffer feeds the Performance Tuning panel with realtime-factor data; `cancel_active_transcodes()` terminates in-flight ffmpegs on shutdown
- `live.py`: MediaMTX bridge — HLS reverse proxy, RTMP-publish auth webhook validation, control-API status query
- `streams.py`: in-memory active streaming-connection registry, client-IP resolver (honors `CF-Connecting-IP`/`X-Forwarded-For` when `TRUSTED_PROXY=cloudflare`; returns peer address otherwise), optional offline GeoLite2 lookup, admin kill/blocklist support, and a 600-entry `_throughput_samples` ring buffer fed by `sweeper_task` (1 Hz during a 60-s capture window via `start_capture_window()`, otherwise the sweeper interval)
- `models.py`: Pydantic v2 request models for login, match CRUD, upload sessions, user management, live auth webhook, and admin stream unblock
- `log.py`: structured JSON logging (configurable via `LOG_FORMAT` env var)
- `script.js`: ES module entry point — state, init, navigation, event binding, mixin assembly
- `js/utils.js`: pure utility functions (esc, formatDate, statusLabel, etc.)
- `js/api.js`: auth, data loading, settings, transcode polling; `authFetch(url, opts)` wraps `fetch` and handles 401 (clears session, shows login modal, throws) — use it for all authenticated requests instead of repeating the 401 boilerplate
- `js/player.js`: AirPlay, Chromecast, HLS playback, position/speed memory, keyboard shortcuts, match navigation
- `js/uploads.js`: chunked upload sessions, resume logic
- `js/views.js`: public view rendering — season view, game view, score reveal, team stats; `updateTranscodeBadges()` for targeted badge-only updates during transcode polling (avoids full grid re-render)
- `js/admin-views.js`: admin view renderers and action methods extracted from views.js — settings form, users list, match form (create/edit/delete), admin diagnostics renderers (consumed by `js/admin.js`), Performance Tuning panel (`renderPerformanceTuning`, `refreshPerformanceTuning`, `startPerformanceTuningPolling`/`stopPerformanceTuningPolling`, `copyPerformanceSnapshot`/`downloadPerformanceSnapshot`, capture-window starter), and Tuning Knobs settings card (`renderTuningKnobsCard`, `applyTuningPreset`, `collectTuningKnobs`)
- `js/live.js`: Watch Live view (HLS.js player + status polling), AirPlay/Chromecast hand-off for the live feed, and admin live config card
- `js/admin.js`: unified `/admin/*` dashboard mixin — sub-routing, sidebar, status strip polling, role gating, overview KPI tiles
- `js/ui.js`: toast notifications (success/error/info) and button loading state helpers
- `index.html`: single-page app shell (loads `script.js` as `type="module"`)
- `styles.css`: full UI styling
- `tests/`: pytest test suite (auth, matches, uploads, settings, users, admin, live)
- `docker-compose.yml`: local container runtime — defines `replay` and the `mediamtx` sidecar
- `mediamtx.yml`: MediaMTX config (RTMP ingest, LL-HLS output, external auth webhook)
- `Caddyfile`: reverse proxy that serves VOD HLS `.ts/.m4s/.mp4` segments + variant playlists directly from `/data` via `sendfile()` and proxies all other routes to the replay app on `:8090`. Drops Python out of the segment-serving hot path so 10 GbE LAN delivery is achievable.
- `.env.example`: deployment configuration template

## Common Commands

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for testing
python server.py
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py && python3 -m py_compile live.py && python3 -m py_compile streams.py
pytest tests/ -v
docker compose up --build
```

Open the app at `http://localhost:8090` by default.

## Environment

Important settings live in `.env.example` and can be copied to `.env.local`.

Most relevant variables:

- `ADMIN_USER`
- `ADMIN_PASS`
- `REPLAY_PORT`
- `REPLAY_DATA_DIR`
- `MAX_UPLOAD_SIZE_BYTES` *(legacy — first-boot fallback only; live value is the `max_upload_size_bytes` setting in the admin Settings page)*
- `UPLOAD_CHUNK_SIZE_BYTES` *(legacy — see `upload_chunk_size_bytes` setting)*
- `TRANSCODE_CONCURRENCY` *(legacy — first-boot fallback. Live value is `transcode_concurrency`; resized in-process via `ResizableSemaphore.resize()` on save. `_hls_semaphore` in `media.py` still caps HLS variant ffmpegs at 2 independently.)*
- `VIDEO_STREAM_CHUNK_BYTES` *(legacy — see `video_stream_chunk_bytes` setting)*
- `HLS_SEGMENT_DURATION` *(legacy — see `hls_segment_duration` setting; new transcodes only)*
- `REPLAY_HWACCEL` *(legacy — see `replay_hwaccel` setting; values: auto/qsv/vaapi/nvenc/cpu)*
- `ALLOWED_ORIGINS` — optional comma-separated hostnames for login origin validation
- `LOG_FORMAT` — `json` (default) or `text` for human-readable logs
- `LOG_LEVEL` — `INFO` (default), `DEBUG`, `WARNING`, etc.
- `MEDIAMTX_HLS_URL` — internal address of the MediaMTX sidecar's HLS port (default `http://mediamtx:8888`)
- `MEDIAMTX_API_URL` — internal address of the MediaMTX control API (default `http://mediamtx:9997`)
- `TRUSTED_PROXY` — `cloudflare` (default) or `none`; controls whether `client_ip()` in `streams.py` honors `CF-Connecting-IP`/`X-Forwarded-For`. Set to `none` for bare deployments not behind Cloudflare.
- `LIVE_AUTH_SECRET` — shared secret MediaMTX sends in `X-Internal-Secret` when calling `/api/live/auth`. Configure the same value in `mediamtx.yml`'s `authHTTPHeaders`. If unset, the endpoint is open to all network callers (only safe when firewalled).
- `LIVE_STALE_SEGMENT_AGE_SECONDS` — stream flips to offline when no new HLS segment has been cut for this many seconds (default 90)

## Project Constraints

- Keep the app as a no-build-step SPA.
- Preserve the existing FastAPI + vanilla JS architecture unless a task explicitly calls for larger rework.
- Prefer minimal, focused edits.
- Do not commit secrets or local-only files such as `.env.local`.
- Large uploads, resumable chunking, HLS playback, Cast, and AirPlay are already implemented; avoid regressing those flows.
- Request validation is handled by Pydantic models in `models.py`; add new models there rather than inline validation in `server.py`.

## Validation

After backend changes, run:

```bash
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py
pytest tests/ -v
```

After frontend changes, sanity-check:

- season view rendering
- match detail navigation (URL slug deep-linking: `/match/{slug}`, `/match/{slug}/first-half`)
- upload form behavior
- replay playback
- Cast/AirPlay controls if relevant

## Editing Guidance

- Keep API shapes stable unless the task requires a breaking change.
- Reuse existing helper functions instead of duplicating upload, playback, or view-toggle logic.
- Frontend JS is split into ES modules under `js/` using a mixin pattern. Each module exports a plain object; `script.js` merges them into `window.app`. Add new methods to the appropriate mixin, not to `script.js` directly.
- For SPA navigation, prefer the shared history helpers in `script.js`. Match URLs use slug-based paths (`/match/{slug}`). The unified admin dashboard uses `/admin/{section}` deep links (`overview`, `matches`, `live`, `streams`, `users`, `settings`, `system`); routing + role gating live in `js/admin.js`. Legacy `view: 'add-match'` and `view: 'settings'` history states are still recognized in `restoreHistoryState()` and forwarded into the dashboard so back/forward keeps working across deploys.
- Match scores are intentionally hidden by default on cards and the game header — the site is a replay library, not a results page. Reveal state lives in `app._revealedScores` (per-session Set, not persisted). When adding new surfaces that show a score, call `app.isMatchScoreRevealed(matchId)` to gate the numerals and emit a `.score-reveal-chip` (or `.score-reveal-chip-large` on the game page) that calls `app.revealMatchScore(matchId, event)`.
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
- When adding or modifying API endpoints, add or update Pydantic models in `models.py` and add corresponding tests in `tests/`.
- Login is rate-limited (5 attempts/60s per IP). Token cleanup sweeps run automatically. On startup, `lifespan` also calls `_uploads.cleanup_stale_sessions()` to cancel any upload sessions that were left `'active'` across a restart.
- Three user roles: `admin` (full access), `uploader` (match CRUD + uploads), `viewer` (read-only). Use `_auth.require_role(request, "admin", "uploader")` for role checks. The env-var admin (`ADMIN_USER`/`ADMIN_PASS`) is always a superadmin and is checked before the DB user table — it bypasses the DB `enabled` flag entirely. Do not reuse `ADMIN_USER` as a DB account name.
- Backend logic is organized into focused modules (`db.py`, `auth.py`, `settings.py`, `uploads.py`, `media.py`). Keep `server.py` as the route registration layer; add business logic to the appropriate module.
- The `MATCHES_LOCK` is an `asyncio.Lock` — all callers that hold it must be async.
- For UI feedback, use the toast system in `js/ui.js` (`showSuccess`, `showError`, `showInfo`) instead of `alert()`. Use `btnLoading()` for button loading states.
- Playback state (position, speed) is persisted in localStorage by `js/player.js`. Keyboard shortcuts are YouTube-style and registered globally in `initKeyboardShortcuts()`. Thumbnails are auto-generated during transcoding and backfilled at startup for existing videos.
- Video errors are persisted in the `video_errors` table. When setting status to `"error"`, pass `error_info={"error_code": ..., "reason": ..., "details": ...}` to `_set_video_status()`.
- Admin recovery endpoints: retry transcode (`POST .../retry`), regenerate HLS (`POST .../regenerate-hls`), verify assets (`GET .../verify`), export DB (`POST /api/admin/export-database`).
- Live streaming (RTMP ingest → LL-HLS) is provided by a `mediamtx` sidecar in compose. Stream-key auth runs through `POST /api/live/auth` (called by MediaMTX); browsers always reach LL-HLS via the proxy at `/api/live/hls/*` so they only ever talk to the replay origin. The stream key is private (never returned by `/api/settings`) and is rotated via `POST /api/admin/live/rotate-key`.
- AirPlay and Chromecast for the Watch Live feed live alongside the replay-player implementation. `js/live.js::initLiveRemotePlayback` binds the `live-video` element + `airplay-btn-live` / `cast-btn-live` buttons; `js/player.js::onCastConnected` and `setupCastFramework` are view-aware and route the live HLS URL (`application/x-mpegURL` + `streamType=LIVE`) when the live view is active.
- Active streaming connections (live HLS proxy + VOD HLS + VOD MP4) are tracked in `streams.py`'s in-memory `StreamRegistry`. Admin endpoints `GET /api/admin/streams`, `POST /api/admin/streams/{id}/kill`, and `DELETE /api/admin/streams/blocks` power the "Active Streaming Connections" card in admin diagnostics. Killing a stream cancels its iterator and adds a 5-minute `(ip, kind, match_id, slot)` blocklist entry. Block TTL uses `time.monotonic()` (not wall clock) so NTP jumps cannot permanently strand an entry; `list_blocks()` converts back to wall-clock epoch for the API response. Use `streams.client_ip(request)` to resolve client IPs everywhere — behavior is gated by `TRUSTED_PROXY`: `"cloudflare"` (default) honors `CF-Connecting-IP` / `True-Client-IP` / `X-Forwarded-For`; `"none"` always returns the direct peer address.
- The Performance Tuning admin panel (under `/admin/system`) is powered by `GET /api/admin/performance`, which aggregates host signals (psutil), throughput rollups from `streams._throughput_samples`, transcode realtime factors from `media._transcode_history`, GPU stats counters, and active sessions. Refreshes every 5 s while the system view is active. `POST /api/admin/performance/capture` flips the sweeper to 1 Hz sampling for 60 s. The panel includes copy-to-clipboard and download-as-JSON buttons that bundle the latest payload for sharing with a coding agent. Also under `/admin/settings`: `renderTuningKnobsCard()` renders the typed editor for the `TUNING_KNOBS` schema with three one-click presets (Conservative / Balanced 10 GbE / Live-first); changes are recorded in the `settings_audit` table and `transcode_concurrency` resizes the in-process semaphore live.
- **After every code change**, update the relevant markdown files (`ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`) to reflect what changed — new files, completed roadmap items, new conventions, updated guidance. Keep these files as the living source of truth.
