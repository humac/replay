# Replay Agent Guide

This repository is a small FastAPI + vanilla JS application for uploading, processing, and replaying soccer match videos, plus live streaming. Replay is a single-team VOD + live-streaming platform: a flat, global match library (no teams/seasons/multi-tenant scope), admin-managed user accounts, and an in-process transcode queue.

## Stack

- Backend: `server.py` (FastAPI app wiring + entrypoint) with focused routers under `routers/` and shared services under `services/`
- Frontend: `index.html`, `script.js` (ES module entry point), `js/` (module mixins), `styles.css`
- Storage: SQLite in `replay.db` (the only supported backend) plus filesystem media files. The schema is a single squashed migration (`_migrate_v1` in `db.py`) pinned at `PRAGMA user_version = 1`; the tables are `activity_events`, `background_jobs`, `matches`, `schema_version`, `settings`, `settings_audit`, `upload_sessions`, `user_sessions`, `users`, `video_errors`.
- Media pipeline: `media.py` wrapping `ffmpeg` and `ffprobe`
- Testing: `pytest` + `pytest-asyncio` + `httpx` (see `tests/`)
- CI: GitHub Actions (`.github/workflows/ci.yml`)
- Runtime: direct Python or Docker Compose
- Docs: `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/user-guide.md`, `docs/admin-guide.md`

## Key Files

- `server.py`: FastAPI app construction + lifespan/startup work, SPA/static serving, shared path helpers, async lock wrappers, and the entrypoint. It mounts the focused routers and keeps shared helpers that routers import lazily to avoid circular imports. `lifespan` runs the durable-jobs stuck-job recovery sweep and cleans up stale upload sessions on startup.
- `db.py`: SQLite connection pool, schema, match CRUD helpers, persisted admin `activity_events` feed helpers, durable `background_jobs` schema, durable hashed `user_sessions` (with `revoke_user_sessions` used on admin password reset), upload-session persistence, settings + `settings_audit`, and `video_errors`. The schema is a **single squashed migration** (`_migrate_v1`) pinned at `PRAGMA user_version = 1`. SQLite is the only backend — `connect()` is SQLite-only.
- `auth.py`: multi-user authentication, token management, durable hashed database-user sessions, password hashing (scrypt), login rate limiting, origin validation. `db.revoke_user_sessions` is used when an admin resets a user's password.
- `models.py`: Pydantic v2 request models for login, match CRUD, upload sessions, user management, live auth webhook, and admin stream unblock.
- `settings.py`: app settings persistence, rendering helpers, static asset version rewriting for `styles.css` and `script.js`, `TUNING_KNOBS` schema (typed validation + range clamps for performance/upload/encoder knobs), env-fallback-on-first-load, `settings_audit` write helper, typed read helpers (`get_int`/`get_float`/`get_bool`/`get_str`/`get_hls_variant_presets`).
- `uploads.py`: upload session lifecycle (create, chunk, complete, cleanup).
- `media.py`: ffmpeg/ffprobe probing, transcoding (QSV / NVENC / VAAPI / CPU, auto-selected via `select_hwaccel()` — overridable via the `replay_hwaccel` admin setting or the legacy `REPLAY_HWACCEL` env var) with real-time progress tracking, resilient QSV→VAAPI→CPU fallback chain, HLS variant generation (capped at 2 simultaneous variants via `_hls_semaphore`), thumbnail extraction; `get_all_transcode_progress()` returns all active jobs; `get_gpu_health()` returns session-lifetime GPU encode counters; `_transcode_history` ring buffer feeds the Performance Tuning panel with realtime-factor data; `cancel_active_transcodes()` terminates in-flight ffmpegs on shutdown. **Path helpers split hot vs. cold storage**: `slot_hls_dir`, `slot_hls_master_path` resolve under `videos_dir` (SSD); `slot_mp4_path`, `slot_raw_path`, `find_slot_raw_path`, `match_originals_dir` resolve under `originals_dir` (cold pool when `REPLAY_ORIGINALS_DIR` is set, else aliased to `videos_dir`).
- `live.py`: MediaMTX bridge — HLS reverse proxy, RTMP-publish auth webhook validation, control-API status query.
- `streams.py`: in-memory active streaming-connection registry, client-IP resolver (honors `CF-Connecting-IP`/`X-Forwarded-For` when `TRUSTED_PROXY=cloudflare`; returns peer address otherwise), optional offline GeoLite2 lookup, admin kill/blocklist support, and a 600-entry `_throughput_samples` ring buffer fed by `sweeper_task` (1 Hz during a 60-s capture window via `start_capture_window()`, otherwise the sweeper interval).
- `log.py`: structured JSON logging (configurable via `LOG_FORMAT` env var).
- `routers/auth.py`: authentication router for login (`POST /api/login`), logout (`POST /api/logout`), and auth-check (`GET /api/auth/check`). Keep auth rate limiting, token hashing, and origin validation in `auth.py`; the router stays a thin HTTP surface.
- `routers/admin.py`: admin user-management router for `/api/users*` (CRUD) plus admin diagnostics helpers, backed by `auth.py`, `db.py`, and `services/activity.py`.
- `routers/admin_ops.py`: operational admin router — `/api/admin/diagnostics`, `/api/admin/performance` (+ capture), `/api/admin/backfill-hls`, `/api/admin/export-database`, `/api/transcode-progress`.
- `routers/matches.py`: match library CRUD/playback/recovery — `/api/matches*` (incl. HLS `/api/matches/{id}/hls/{slot}/...`, `/video/{slot}`, `/thumbnail`, `/logo/{team}`, `/download/{slot}`), admin recovery (`/api/admin/matches/{id}/{retry,regenerate-hls,regenerate-thumbnail,verify,errors}`), and the match heartbeat.
- `routers/uploads.py`: chunked upload session lifecycle (`/api/uploads/sessions*`) and the two `POST /api/matches/{id}/upload-video[/session]` entry points.
- `routers/live.py`: `/api/live/{status,hls/...,auth}` plus `/api/admin/{live/...,streams/...}`.
- `routers/settings.py`: public `/api/settings`, admin `/api/admin/settings` GET/PUT, `/api/admin/settings/asset`, `/api/app-assets/{kind}`. Branding + tuning knobs only.
- `services/activity.py`: best-effort admin activity feed writer and stream activity callback.
- `services/thumbnails.py`: match thumbnail path checks and best-effort generation helpers.
- `services/jobs.py`: durable in-process background-job queue. Owns enqueue/idempotency, internal worker leasing, heartbeats, stale-worker-safe complete/fail, cancel, listing, and stuck-job recovery. Transcodes create `background_jobs` rows while still executing through the existing in-process semaphore/path. There is no user-facing `/api/jobs*` surface.
- `script.js`: ES module entry point — state, init, navigation, event binding, mixin assembly into `window.app`.
- `js/utils.js`: pure utility functions (esc, formatDate, statusLabel, etc.).
- `js/api.js`: auth, data loading, settings, transcode polling; `authFetch(url, opts)` wraps `fetch` and handles 401 (clears session, shows login modal, throws) — use it for all authenticated requests.
- `js/player.js`: AirPlay, Chromecast, HLS playback, position/speed memory, keyboard shortcuts, match navigation.
- `js/uploads.js`: chunked upload sessions, resume logic.
- `js/views.js`: public view rendering — season view (groups matches by their season label string), game view, score reveal, team stats; `updateTranscodeBadges()` for targeted badge-only updates during transcode polling.
- `js/admin-views.js`: admin view renderers and action methods — settings form, users list, match form (create/edit/delete), admin diagnostics renderers (consumed by `js/admin.js`), Performance Tuning panel (`renderPerformanceTuning`, `refreshPerformanceTuning`, polling start/stop, snapshot copy/download, capture-window starter), and Tuning Knobs settings card (`renderTuningKnobsCard`, `applyTuningPreset`, `collectTuningKnobs`).
- `js/admin.js`: unified `/admin/*` dashboard mixin — sub-routing for `/admin/overview`, `/admin/matches`, `/admin/live`, `/admin/performance`, `/admin/users`, and `/admin/settings`; status strip polling, role gating, overview KPI tiles. Legacy `/admin/streams` and `/admin/system` redirect to `/admin/live` and `/admin/performance`.
- `js/live.js`: Watch Live view (HLS.js player + status polling), AirPlay/Chromecast hand-off for the live feed, and admin live config card.
- `js/ui.js`: toast notifications (success/error/info), button loading state helpers, and the modal kernel (`openAppModal` / `app.formModal`).
- `index.html`: single-page app shell (loads `script.js` as `type="module"`).
- `styles.css`: full UI styling. When splitting CSS into a `styles/` directory, preserve link order and add new files to `_STATIC_EXPORT_PATHS` in `server.py` for exported-static deployments and version-tag them in `settings.render_index_html()`.
- `tests/`: pytest test suite (auth, matches, uploads, settings, users, admin, live, streams, media, db, models, server, route inventory). Canonical invocation is `ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q` (`tests/conftest.py` defaults `ADMIN_PASS` to `admin`). pytest-cov is not installed locally; do not pass `--cov`. `tests/fixtures/route-inventory.txt` is the canonical route list checked by `test_route_inventory.py`.
- `tests/e2e/`: a single Playwright VOD smoke spec (`vod-smoke.spec.js`) covering the public surface, the admin console, the matches API, and removed-surface 404s. Scoped with its own `package.json` and `node_modules` so the repo root stays no-build. Run from inside the folder: `cd tests/e2e && PLAYWRIGHT_BASE_URL=... ADMIN_PASS=... npm test`. The shared login helper is `tests/e2e/_login.js`.
- `.agent-skills/`: portable per-repo skill pack (repo navigation, mixin pattern, CSS/accessibility, QA gates, PR checklist). Load `.agent-skills/README.md` first.
- `pytest.ini`: pytest-asyncio mode/scope plus narrow filters for third-party Python 3.14 deprecations.
- `docker-compose.yml`: local container runtime — defines `replay` and the `mediamtx` sidecar.
- `mediamtx.yml`: MediaMTX config (RTMP ingest, LL-HLS output, external auth webhook).
- `Caddyfile`: reverse proxy that serves VOD HLS `.ts/.m4s/.mp4` segments + variant playlists directly from `/data` via `sendfile()` and proxies all other routes to the replay app on `:8091`. Drops Python out of the segment-serving hot path so 10 GbE LAN delivery is achievable.
- `.env.example`: deployment configuration template.

## Common Commands

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for testing
python server.py
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py && python3 -m py_compile live.py && python3 -m py_compile streams.py
ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q
docker compose up --build
```

Open the app at `http://localhost:8091` by default.

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
- `MAX_ACTIVE_TOKENS` — hard cap on concurrent in-memory sessions (default 1000)
- `LOG_FORMAT` — `json` (default) or `text` for human-readable logs
- `LOG_LEVEL` — `INFO` (default), `DEBUG`, `WARNING`, etc.
- `MEDIAMTX_HLS_URL` — internal address of the MediaMTX sidecar's HLS port (default `http://mediamtx:8888`)
- `MEDIAMTX_API_URL` — internal address of the MediaMTX control API (default `http://mediamtx:9997`)
- `TRUSTED_PROXY` — `cloudflare` (default) or `none`; controls whether `client_ip()` in `streams.py` honors `CF-Connecting-IP`/`X-Forwarded-For`. Set to `none` for bare deployments not behind Cloudflare.
- `LIVE_AUTH_SECRET` — shared secret MediaMTX sends to `/api/live/auth`. MediaMTX 1.18 dropped `authHTTPHeaders`, so the secret travels as the password half of HTTP Basic Auth in `authHTTPAddress` itself: `http://_:***@replay:8091/api/live/auth`. The replay handler accepts the secret from either the `Authorization: Basic …` header (current MediaMTX) or the legacy `X-Internal-Secret:` header. If unset, the endpoint returns 503 by default; set `LIVE_AUTH_ALLOW_INSECURE=1` only for local/dev firewalled scenarios.
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
ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q
```

After frontend changes, sanity-check:

- align new UI with the existing Replay design language
- avoid raw/browser-default controls; visible controls must be themed in dark and light modes
- season view rendering
- match detail navigation (URL slug deep-linking: `/match/{slug}`, `/match/{slug}/first-half`)
- upload form behavior
- replay playback
- Cast/AirPlay controls if relevant

## Editing Guidance

- Keep API shapes stable unless the task requires a breaking change.
- Reuse existing helper functions instead of duplicating upload, playback, or view-toggle logic.
- Frontend JS is split into ES modules under `js/` using a mixin pattern. Each module exports a plain object; `script.js` merges them into `window.app`. Add new methods to the appropriate mixin, not to `script.js` directly.
- For SPA navigation, prefer the shared history helpers in `script.js`. Match URLs use slug-based paths (`/match/{slug}`, `/match/{slug}/{slot}`). The unified admin dashboard uses `/admin/{section}` deep links (`overview`, `matches`, `live`, `performance`, `users`, `settings`); routing + role gating live in `js/admin.js`. Legacy URLs `/admin/streams` and `/admin/system` are redirected via `LEGACY_SECTION_REDIRECTS` to `/admin/live` and `/admin/performance`.
- Three admin button tiers (`styles.css`): `.btn-primary / .btn-secondary / .btn-danger` for form submits + primary CTAs (Save, Cancel, Add Match); `.btn-head` for every section-head action button (Refresh, capture, copy, preset buttons, the Live Console's Copy / Reveal / Rotate / Diagnose); `.mini-action-btn` for row-level actions in tables and accordions. Don't reach for `.btn-secondary` for section-head actions — `.btn-head` is the consistent quiet tier for that role.
- Visible controls must be themed in both dark and light modes. Avoid raw browser chrome: no native multi-select boxes, unstyled range sliders, number spinners, default checkboxes/radios, file inputs, horizontal overflow bars, or unthemed scrollbars. If a native control must remain for accessibility or platform behavior, skin the closed/control state and avoid visible overflow that exposes browser scroll UI.
- **One width for the whole site.** `#app-container` is `max-width: min(100% - 1.5rem, 2200px)` with `1.25rem` padding above the existing mobile breakpoints. Every view — public season, public match, admin — fills the shell end-to-end so navigating between them never jumps the page edges. **Don't add per-view outer OR inner max-width caps** unless a specific component genuinely needs a narrower readable measure (e.g. a long prose article, the focused playback modal). Components that use a grid (`.matches-grid`, the admin tile rows) handle responsive column counts via `auto-fill / auto-fit minmax(...)`.
- The Matches tab is a **library**, not a form. `renderMatchLibraryTable()` in `js/admin-views.js` renders the table of recorded matches with format, per-slot status pills, and an expandable diagnostics row containing every per-slot recovery action (Verify, Regen HLS, Re-transcode, Force Re-transcode, Logs, Regenerate Thumbnail). Add Match / Edit Match open a modal mounted from the `<template id="match-form-template">` in `index.html` — the modal reuses the original form input ids (`f-home-team`, `f-video-full`, …) so existing handlers (`handleFormSubmit`, `toggleFormatFields`, `uploadFileIfSelected`, `uploadVideoIfSelected`, `editMatch`, `renderEditAssetStates`) work unchanged. The modal kernel is `openAppModal({ kind: 'form', body, onSubmit })` in `js/ui.js`, exposed as `app.formModal({ … })`.
- Match scores are intentionally hidden by default on cards and the game header — the site is a replay library, not a results page. Reveal state lives in `app._revealedScores` (per-session Set, not persisted). When adding new surfaces that show a score, call `app.isMatchScoreRevealed(matchId)` to gate the numerals and emit a `.score-reveal-chip` that calls `app.revealMatchScore(matchId, event)`.
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
- When adding or modifying API endpoints, add or update Pydantic models in `models.py` and add corresponding tests in `tests/`.
- When testing `/api/live/auth`, configure `server.LIVE_AUTH_SECRET` and send the secret either as the `X-Internal-Secret` header or as HTTP Basic Auth (any username, password = secret). Both paths are accepted.
- Login is rate-limited (5 attempts/60s per IP). Token cleanup sweeps run automatically. On startup, `lifespan` also calls `_uploads.cleanup_stale_sessions()` to cancel any upload sessions that were left `'active'` across a restart.
- Role capabilities: `admin` (full access and inherits every capability), `uploader` (match CRUD + uploads), and `viewer` (read-only, signed-in). DB user `role` can be a comma-separated capability string such as `uploader,admin`; use `_auth.require_role(...)` and `_auth.has_role(...)` rather than comparing `user["role"]` directly. The env-var admin (`ADMIN_USER`/`ADMIN_PASS`) is always a superadmin and is checked before the DB user table — it bypasses the DB `enabled` flag entirely. Do not reuse `ADMIN_USER` as a DB account name. User accounts are admin-managed: there is no public signup, self-service password reset, or email verification.
- Backend logic is organized into focused routers (`routers/`) and services (`services/`). Keep `server.py` as the app-wiring/route-registration layer; add domain behavior to the appropriate router or service module.
- The `MATCHES_LOCK` is an `asyncio.Lock` — all callers that hold it must be async.
- For UI feedback, use the toast system in `js/ui.js` (`showSuccess`, `showError`, `showInfo`) instead of `alert()`. Use `btnLoading()` for button loading states.
- Playback state (position, speed) is persisted in localStorage by `js/player.js`. Keyboard shortcuts are YouTube-style and registered globally in `initKeyboardShortcuts()`. Thumbnails are auto-generated during transcoding and backfilled at startup for existing videos.
- Video errors are persisted in the `video_errors` table. When setting status to `"error"`, pass `error_info={"error_code": ..., "reason": ..., "details": ...}` to `_set_video_status()`.
- Admin overview "Recent Activity" is backed by persisted `activity_events` (`_db.log_activity_event()` / `_db.get_activity_events()`), not by `video_errors`. Log logical events only: upload/transcode/HLS/admin/user/settings/live-or-VOD-HLS stream session transitions. Do not log HLS segment polls, VOD heartbeat noise, or per-range MP4 requests.
- Admin recovery endpoints: retry transcode (`POST .../retry`), regenerate HLS (`POST .../regenerate-hls`), verify assets (`GET .../verify`), export DB (`POST /api/admin/export-database`).
- Live streaming (RTMP ingest → LL-HLS) is provided by a `mediamtx` sidecar in compose. Stream-key auth runs through `POST /api/live/auth` (called by MediaMTX); browsers always reach LL-HLS via the proxy at `/api/live/hls/*` so they only ever talk to the replay origin. The stream key is private (never returned by `/api/settings`) and is rotated via `POST /api/admin/live/rotate-key`.
- AirPlay and Chromecast for the Watch Live feed live alongside the replay-player implementation. `js/live.js::initLiveRemotePlayback` binds the `live-video` element + `airplay-btn-live` / `cast-btn-live` buttons; `js/player.js::onCastConnected` and `setupCastFramework` are view-aware and route the live HLS URL (`application/x-mpegURL` + `streamType=LIVE`) when the live view is active.
- Active streaming connections (live HLS proxy + VOD HLS + VOD MP4) are tracked in `streams.py`'s in-memory `StreamRegistry`. Admin endpoints `GET /api/admin/streams`, `POST /api/admin/streams/{id}/kill`, and `DELETE /api/admin/streams/blocks` power the "Active Streaming Connections" card in admin diagnostics. Killing a stream cancels its iterator and adds a 5-minute `(ip, kind, match_id, slot)` blocklist entry. Block TTL uses `time.monotonic()` (not wall clock) so NTP jumps cannot permanently strand an entry. Use `streams.client_ip(request)` to resolve client IPs everywhere — behavior is gated by `TRUSTED_PROXY`.
- The Performance Tuning admin panel (under `/admin/performance`) is powered by `GET /api/admin/performance`, which aggregates host signals (psutil), throughput rollups from `streams._throughput_samples`, transcode realtime factors from `media._transcode_history`, GPU stats counters, and active sessions. Refreshes every 5 s while the performance view is active. `POST /api/admin/performance/capture` flips the sweeper to 1 Hz sampling for 60 s. The tuning knobs (`renderTuningKnobsCard()` — typed editor for the `TUNING_KNOBS` schema with three one-click presets Conservative / Balanced 10 GbE / Live-first) are colocated on the same page. Changes are recorded in the `settings_audit` table and `transcode_concurrency` resizes the in-process semaphore live. Tuning saves through `handleTuningSubmit()` (tuning-only PUT body); never route the tuning Save button through `handleSettingsSubmit()` — that handler reads live-form inputs which can be uninitialized HTML defaults from the Performance section, silently disabling live streaming.
- **After every code change**, update the relevant markdown files (`ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`) to reflect what changed — new files, completed roadmap items, new conventions, updated guidance. Keep these files as the living source of truth.
