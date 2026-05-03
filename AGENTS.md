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
- Docs: `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/user-guide.md`, `docs/admin-guide.md`, `docs/coach-guide.md`
- Specs: lightweight design notes for larger features live under `specs/`, including `specs/coaching-platform-design.md`

## Key Files

- `server.py`: API routes, SPA serving, async lock wrappers, entrypoint
- `db.py`: SQLite connection pool, schema migrations, match CRUD helpers, persisted admin `activity_events` feed helpers, and coaching workspace persistence (`players`, player-user links, notes, playlists, reviews)
- `auth.py`: multi-user authentication, token management, password hashing (scrypt), role-based access, login rate limiting, origin validation
- `settings.py`: app settings persistence, rendering helpers, `TUNING_KNOBS` schema (typed validation + range clamps for performance/upload/encoder knobs), env-fallback-on-first-load, `settings_audit` write helper, typed read helpers (`get_int`/`get_float`/`get_bool`/`get_str`/`get_hls_variant_presets`)
- `uploads.py`: upload session lifecycle (create, chunk, complete, cleanup)
- `media.py`: ffmpeg/ffprobe probing, transcoding (QSV / NVENC / VAAPI / CPU, auto-selected via `select_hwaccel()` — overridable via the `replay_hwaccel` admin setting or the legacy `REPLAY_HWACCEL` env var) with real-time progress tracking, resilient QSV→VAAPI→CPU fallback chain, HLS variant generation (capped at 2 simultaneous variants via `_hls_semaphore`), thumbnail extraction; `get_all_transcode_progress()` returns all active jobs; `get_gpu_health()` returns session-lifetime GPU encode counters (per-method + aggregate `succeeded`/`failed`); `_transcode_history` ring buffer feeds the Performance Tuning panel with realtime-factor data; `cancel_active_transcodes()` terminates in-flight ffmpegs on shutdown. **Path helpers split hot vs. cold storage**: `slot_hls_dir`, `slot_hls_master_path` resolve under `videos_dir` (SSD); `slot_mp4_path`, `slot_raw_path`, `find_slot_raw_path`, `match_originals_dir` resolve under `originals_dir` (cold pool when `REPLAY_ORIGINALS_DIR` is set, else aliased to `videos_dir`).
- `live.py`: MediaMTX bridge — HLS reverse proxy, RTMP-publish auth webhook validation, control-API status query
- `streams.py`: in-memory active streaming-connection registry, client-IP resolver (honors `CF-Connecting-IP`/`X-Forwarded-For` when `TRUSTED_PROXY=cloudflare`; returns peer address otherwise), optional offline GeoLite2 lookup, admin kill/blocklist support, and a 600-entry `_throughput_samples` ring buffer fed by `sweeper_task` (1 Hz during a 60-s capture window via `start_capture_window()`, otherwise the sweeper interval)
- `models.py`: Pydantic v2 request models for login, match CRUD, upload sessions, user management, live auth webhook, admin stream unblock, and coaching roster/notes/playlists/feedback
- `log.py`: structured JSON logging (configurable via `LOG_FORMAT` env var)
- `script.js`: ES module entry point — state, init, navigation, event binding, mixin assembly
- `js/utils.js`: pure utility functions (esc, formatDate, statusLabel, etc.)
- `js/api.js`: auth, data loading, settings, transcode polling; `authFetch(url, opts)` wraps `fetch` and handles 401 (clears session, shows login modal, throws) — use it for all authenticated requests instead of repeating the 401 boilerplate
- `js/player.js`: AirPlay, Chromecast, HLS playback, position/speed memory, keyboard shortcuts, match navigation
- `js/uploads.js`: chunked upload sessions, resume logic
- `js/views.js`: public view rendering — season view, game view, score reveal, team stats; `updateTranscodeBadges()` for targeted badge-only updates during transcode polling (avoids full grid re-render)
- `js/admin-views.js`: admin view renderers and action methods extracted from views.js — settings form, users list, match form (create/edit/delete), admin diagnostics renderers (consumed by `js/admin.js`), Performance Tuning panel (`renderPerformanceTuning`, `refreshPerformanceTuning`, `startPerformanceTuningPolling`/`stopPerformanceTuningPolling`, `copyPerformanceSnapshot`/`downloadPerformanceSnapshot`, capture-window starter), and Tuning Knobs settings card (`renderTuningKnobsCard`, `applyTuningPreset`, `collectTuningKnobs`)
- `js/live.js`: Watch Live view (HLS.js player + status polling), AirPlay/Chromecast hand-off for the live feed, and admin live config card
- `js/coaching.js`: coach workspace (`/coach`) and player/family feedback (`/feedback`) mixin — sub-tabbed `/coach` shell (Roster / Notes / Playlists / Review), Coach > Review video player + telestrator (the single note authoring surface, includes the multi-player `formation` overlay tool), `<template>`-cloned note/playlist modals, and the focused feedback player modal that powers `/feedback` watch + playlist sessions without leaving the page. Coach > Review uses the `is-review-mode` class on `#coach-view` to drive a video-first cockpit layout (PR #57); the telestrator toolbar renders 9 inline-SVG icon buttons (`.coach-tool-btn`, PR #58) with `pointer:fine` collapsing to 34 px squares and `pointer:coarse` keeping a 44 px touch target; the note composer hides visibility / body / tags inside a `<details class="coach-review-advanced">` disclosure (PR #58) so the default state shows just title → players → category → Save-at-MM:SS.
- `js/admin.js`: unified `/admin/*` dashboard mixin — sub-routing, sidebar, status strip polling, role gating, overview KPI tiles
- `js/ui.js`: toast notifications (success/error/info) and button loading state helpers
- `index.html`: single-page app shell (loads `script.js` as `type="module"`)
- `styles.css`: full UI styling
- `tests/`: pytest test suite (auth, matches, uploads, settings, users, admin, live, streams, media, db, models, server). `.coveragerc` excludes the test files from coverage; CI gates `--cov-fail-under=60` (current baseline ~64 %).
- `tests/e2e/`: Playwright browser smoke checks (opt-in). Scoped with its own `package.json` and `node_modules` so the repo root stays no-build. Run from inside the folder: `cd tests/e2e && npx playwright test`. Requires the app reachable at `PLAYWRIGHT_BASE_URL` (default `http://localhost:8090`); the seed spec is `.skip()`'d until Sprint 9 of the Coach Review redesign wires real coverage.
- `.agent-skills/`: portable per-repo skill pack (Coach Review redesign guardrails, search recipes, QA gates). Load `.agent-skills/README.md` first.
- `pytest.ini`: pytest-asyncio mode/scope plus narrow filters for third-party Python 3.14 deprecations
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
pytest tests/ -v --cov --cov-report=term-missing
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
- `REPLAY_ORIGINALS_DIR` — cold-storage path for raw uploads (`<slot>_raw.{mp4,mkv}`) + finished transcoded MP4s (`<slot>.mp4`). When unset, defaults to `<REPLAY_DATA_DIR>/videos` (single-volume layout). Set to a separate bind mount on a slower/larger pool to keep the SSD pool free for HLS segments + thumbnails. The path is mkdir'd at startup; existing matches need a manual `mv` after first enabling the split — see `docs/DEPLOYMENT.md` "Storage tiering."
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
- `LIVE_AUTH_SECRET` — shared secret MediaMTX sends in `X-Internal-Secret` when calling `/api/live/auth`. Configure the same value in `mediamtx.yml`'s `authHTTPHeaders`. If unset, the endpoint returns 503 by default; set `LIVE_AUTH_ALLOW_INSECURE=1` only for local/dev firewalled scenarios.
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
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py && python3 -m py_compile live.py && python3 -m py_compile streams.py
pytest tests/ -v --cov --cov-report=term-missing
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
- For SPA navigation, prefer the shared history helpers in `script.js`. Match URLs use slug-based paths (`/match/{slug}`). Coaching deep links are `/coach` with sub-tab `?tab=` (`roster` default, `notes`, `playlists`, `review`) and optional `?match=&slot=` for the Review tab; `/feedback` with sub-tab `?tab=` (`playlists` default, `notes`). The unified admin dashboard uses `/admin/{section}` deep links (`overview`, `matches`, `live`, `performance`, `users`, `settings`); routing + role gating live in `js/admin.js`. Legacy URLs `/admin/streams` and `/admin/system` are redirected via `LEGACY_SECTION_REDIRECTS` to `/admin/live` and `/admin/performance`. Legacy `view: 'add-match'` and `view: 'settings'` history states are still recognized in `restoreHistoryState()` and forwarded into the dashboard so back/forward keeps working across deploys.
- Three admin button tiers (`styles.css`): `.btn-primary / .btn-secondary / .btn-danger` for form submits + primary CTAs (Save, Cancel, Add Match); `.btn-head` for every section-head action button (Refresh, capture, copy, preset buttons, the Live Console's Copy / Reveal / Rotate / Diagnose); `.mini-action-btn` for row-level actions in tables and accordions. Don't reach for `.btn-secondary` for section-head actions — `.btn-head` is the consistent quiet tier for that role. **Modifier classes** (not new tiers) layer on top of these: `.btn-danger-soft` is a translucent-rose accent applied to `.mini-action-btn` for soft destructive actions like Coach Review > Clear (PR #58); both dark and light modes are themed.
- Visible controls must be themed in both dark and light modes. Avoid raw browser chrome: no native multi-select boxes, unstyled range sliders, number spinners, default checkboxes/radios, file inputs, horizontal overflow bars, or unthemed scrollbars. If a native control must remain for accessibility or platform behavior, skin the closed/control state and avoid visible overflow that exposes browser scroll UI.
- The Matches tab is a **library**, not a form. `renderMatchLibraryTable()` in `js/admin-views.js` renders the table of recorded matches with format, per-slot status pills, and an expandable diagnostics row containing every per-slot recovery action (Verify, Regen HLS, Re-transcode, Force Re-transcode, Logs, Regenerate Thumbnail). Per-match diagnostics that previously lived under `/admin/system` (Failed Slots, Active Jobs, Library Maintenance) have been folded into the expanded row. Add Match / Edit Match open a modal mounted from the `<template id="match-form-template">` in `index.html` — the modal reuses the original form input ids (`f-home-team`, `f-video-full`, …) so existing handlers (`handleFormSubmit`, `toggleFormatFields`, `uploadFileIfSelected`, `uploadVideoIfSelected`, `editMatch`, `renderEditAssetStates`) work unchanged. The modal kernel is `openAppModal({ kind: 'form', body, onSubmit })` in `js/ui.js`, exposed as `app.formModal({ … })`.
- Match scores are intentionally hidden by default on cards and the game header — the site is a replay library, not a results page. Reveal state lives in `app._revealedScores` (per-session Set, not persisted). When adding new surfaces that show a score, call `app.isMatchScoreRevealed(matchId)` to gate the numerals and emit a `.score-reveal-chip` (or `.score-reveal-chip-large` on the game page) that calls `app.revealMatchScore(matchId, event)`.
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
- When adding or modifying API endpoints, add or update Pydantic models in `models.py` and add corresponding tests in `tests/`.
- When testing `/api/live/auth`, configure `server.LIVE_AUTH_SECRET` and send `X-Internal-Secret` unless the test is explicitly covering the fail-closed missing-secret path.
- Login is rate-limited (5 attempts/60s per IP). Token cleanup sweeps run automatically. On startup, `lifespan` also calls `_uploads.cleanup_stale_sessions()` to cancel any upload sessions that were left `'active'` across a restart.
- Role capabilities: `admin` (full access and inherits every capability), `coach` (coaching workspace, roster links, notes/playlists), `uploader` (match CRUD + uploads), and `viewer` (read-only plus assigned feedback). DB user `role` can be a comma-separated capability string such as `coach,uploader`; use `_auth.require_role(...)` and `_auth.has_role(...)` rather than comparing `user["role"]` directly. The env-var admin (`ADMIN_USER`/`ADMIN_PASS`) is always a superadmin and is checked before the DB user table — it bypasses the DB `enabled` flag entirely. Do not reuse `ADMIN_USER` as a DB account name.
- Coaching privacy: coach-created notes/playlists start private. Player-specific feedback requires signed-in user accounts linked to roster `players` through `player_user_links`. `/api/my-feedback` must only return team/unlisted feedback plus player-specific feedback for linked players. Public player profile pages are intentionally out of scope.
- Coaching playlist privacy: a visible playlist may include ordered `items` for its note moments even when those notes are private as standalone feedback. Keep standalone note visibility filtering separate from playlist-session item access.
- Coaching drawings are versioned metadata: legacy `version: 1` strokes must keep rendering; `version: 2` objects power telestrator tools. Do not burn drawings into video files.
- Backend logic is organized into focused modules (`db.py`, `auth.py`, `settings.py`, `uploads.py`, `media.py`). Keep `server.py` as the route registration layer; add business logic to the appropriate module.
- The `MATCHES_LOCK` is an `asyncio.Lock` — all callers that hold it must be async.
- For UI feedback, use the toast system in `js/ui.js` (`showSuccess`, `showError`, `showInfo`) instead of `alert()`. Use `btnLoading()` for button loading states.
- Playback state (position, speed) is persisted in localStorage by `js/player.js`. Keyboard shortcuts are YouTube-style and registered globally in `initKeyboardShortcuts()`. Thumbnails are auto-generated during transcoding and backfilled at startup for existing videos.
- Video errors are persisted in the `video_errors` table. When setting status to `"error"`, pass `error_info={"error_code": ..., "reason": ..., "details": ...}` to `_set_video_status()`.
- Admin overview "Recent Activity" is backed by persisted `activity_events` (`_db.log_activity_event()` / `_db.get_activity_events()`), not by `video_errors`. Log logical events only: upload/transcode/HLS/admin/user/settings/live-or-VOD-HLS stream session transitions. Do not log HLS segment polls, VOD heartbeat noise, or per-range MP4 requests.
- Admin recovery endpoints: retry transcode (`POST .../retry`), regenerate HLS (`POST .../regenerate-hls`), verify assets (`GET .../verify`), export DB (`POST /api/admin/export-database`).
- Live streaming (RTMP ingest → LL-HLS) is provided by a `mediamtx` sidecar in compose. Stream-key auth runs through `POST /api/live/auth` (called by MediaMTX); browsers always reach LL-HLS via the proxy at `/api/live/hls/*` so they only ever talk to the replay origin. The stream key is private (never returned by `/api/settings`) and is rotated via `POST /api/admin/live/rotate-key`.
- AirPlay and Chromecast for the Watch Live feed live alongside the replay-player implementation. `js/live.js::initLiveRemotePlayback` binds the `live-video` element + `airplay-btn-live` / `cast-btn-live` buttons; `js/player.js::onCastConnected` and `setupCastFramework` are view-aware and route the live HLS URL (`application/x-mpegURL` + `streamType=LIVE`) when the live view is active.
- Active streaming connections (live HLS proxy + VOD HLS + VOD MP4) are tracked in `streams.py`'s in-memory `StreamRegistry`. Admin endpoints `GET /api/admin/streams`, `POST /api/admin/streams/{id}/kill`, and `DELETE /api/admin/streams/blocks` power the "Active Streaming Connections" card in admin diagnostics. Killing a stream cancels its iterator and adds a 5-minute `(ip, kind, match_id, slot)` blocklist entry. Block TTL uses `time.monotonic()` (not wall clock) so NTP jumps cannot permanently strand an entry; `list_blocks()` converts back to wall-clock epoch for the API response. Use `streams.client_ip(request)` to resolve client IPs everywhere — behavior is gated by `TRUSTED_PROXY`: `"cloudflare"` (default) honors `CF-Connecting-IP` / `True-Client-IP` / `X-Forwarded-For`; `"none"` always returns the direct peer address.
- The Performance Tuning admin panel (under `/admin/performance`, formerly `/admin/system`) is powered by `GET /api/admin/performance`, which aggregates host signals (psutil), throughput rollups from `streams._throughput_samples`, transcode realtime factors from `media._transcode_history`, GPU stats counters, and active sessions. Refreshes every 5 s while the performance view is active. `POST /api/admin/performance/capture` flips the sweeper to 1 Hz sampling for 60 s. The panel includes copy-to-clipboard and download-as-JSON buttons that bundle the latest payload for sharing with a coding agent. The tuning knobs (`renderTuningKnobsCard()` — typed editor for the `TUNING_KNOBS` schema with three one-click presets Conservative / Balanced 10 GbE / Live-first) are colocated on the same page so a knob change and its impact share one view. Changes are recorded in the `settings_audit` table and `transcode_concurrency` resizes the in-process semaphore live. Tuning saves through `handleTuningSubmit()` (tuning-only PUT body); never route the tuning Save button through `handleSettingsSubmit()` — that handler reads live-form inputs which can be uninitialized HTML defaults from the Performance section, silently disabling live streaming.
- **After every code change**, update the relevant markdown files (`ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`) to reflect what changed — new files, completed roadmap items, new conventions, updated guidance. Keep these files as the living source of truth.
