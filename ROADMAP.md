# Replay — Enhancement Roadmap

Improvement plan for the Replay match video platform, organized as sequential milestones.

> This document supersedes `docs/copilot_roadmap.md`, which has been removed.

---

## Code Review Summary

The codebase is a well-structured single-file FastAPI backend (`server.py`, 1768 lines) with a no-build-step vanilla JS SPA (`script.js`, ~2600 lines). Core functionality — chunked uploads, GPU/CPU transcoding, HLS streaming, Cast/AirPlay — is solid. The milestones below represent the highest-impact improvements in recommended execution order.

---

## Milestone 1 — Safety Net ✅ COMPLETE

**Goal:** close security gaps and add test coverage so the rest of the roadmap can ship safely.

### Security

**1.1 Rate-limit login endpoint** ✅
Per-IP rate limiting: 5 attempts per 60-second window, returns HTTP 429. Stale IP entries are garbage-collected during token sweeps.

**1.2 Token cleanup on accumulation** ✅
`_sweep_expired_tokens()` runs from `_require_auth()` every 60 seconds, bulk-removing expired tokens. Token cap of 100 enforced at login; oldest evicted when cap is reached.

**1.3 Input validation on match updates** ✅
Pydantic models (`models.py`) enforce type constraints, string length limits, enum values for `format`, and regex patterns for `date` (YYYY-MM-DD) and `time` (HH:MM). `UpdateMatchRequest` uses `extra="forbid"` to reject unknown fields.

**1.4 CSRF / Origin validation** ✅
Optional `ALLOWED_ORIGINS` env var (comma-separated hostnames). When set, the login endpoint validates the `Origin` header. Bearer-token auth on all other mutating endpoints already prevents CSRF.

**1.5 Disk space check before transcoding** ✅
`_transcode_video()` checks free disk space before starting ffmpeg. On insufficient space, sets video status to `"error"` and logs the issue instead of starting a doomed transcode.

### Testing & CI

**1.6 Add test suite** ✅
37 tests across 4 files: `test_auth.py` (login, rate limit, token lifecycle), `test_matches.py` (CRUD, validation), `test_uploads.py` (session lifecycle), `test_settings.py` (settings CRUD). Uses `tmp_path` fixtures for isolation.

**1.7 Add CI workflow** ✅
GitHub Actions (`.github/workflows/ci.yml`): compile check for `server.py`, `media.py`, `models.py` + `pytest tests/ -v` on push/PR to `main`.

**1.8 Add request/response models (Pydantic)** ✅
`models.py` contains `LoginRequest`, `CreateMatchRequest`, `UpdateMatchRequest`, `CreateUploadSessionRequest`. Wired into `server.py` endpoints; FastAPI auto-returns 422 for validation failures.

### Exit criteria — all met

- ✅ Login brute-force is throttled
- ✅ Core routes have automated test coverage (37 tests)
- ✅ CI passes on clean checkout
- ✅ Invalid payloads fail predictably (Pydantic 422 responses)

---

## Milestone 2 — Performance & Backend Structure ✅ COMPLETE

**Goal:** fix performance issues in hot paths and make `server.py` easier to change.

### Performance

**2.1 Reduce redundant DB reads in hot paths** ✅
Streaming endpoints (`stream_video`, `download_video`, `stream_hls_master`) use `_get_match_by_id()` — a single-row `SELECT * FROM matches WHERE id = ?` — instead of loading all matches.

**2.2 Connection pooling for SQLite** ✅
Thread-local cached connections via `db.connect()`. Each thread reuses its connection across calls; connections are validated before reuse and recreated if stale.

**2.3 Replace threading.Lock with asyncio.Lock** ✅
`MATCHES_LOCK` is now `asyncio.Lock()`. All callers that hold it are async, preventing event-loop blocking during write operations.

**2.4 HLS variant generation parallelism** ✅
`build_hls_assets` in `media.py` now runs all variant ffmpeg processes concurrently via `asyncio.gather()`, cutting HLS generation time to ~1/N for N variants.

**2.5 Startup backfill priority management** ✅
`backfill_hls_for_existing_videos` now takes a configurable startup delay (default 5s) and an inter-item delay (default 1s) so new uploads get priority on the transcode semaphore.

### Backend modularization

**2.6 Extract media pipeline to separate module** ✅
Already extracted to `media.py` (~345 lines): probing, transcoding (GPU/CPU fallback), HLS variant generation, and backfill logic.

**2.7 Extract service modules** ✅
`server.py` reduced from ~1800 to ~1150 lines. Extracted modules:

- `db.py` (327 lines): connection pool, migrations, match CRUD helpers
- `auth.py` (109 lines): token management, rate limiting, origin validation
- `settings.py` (151 lines): app settings persistence, rendering helpers
- `uploads.py` (128 lines): upload session lifecycle

**2.8 Structured logging** ✅
`log.py` provides a `JSONFormatter` emitting one JSON object per log line. Controlled via `LOG_FORMAT` (json/text) and `LOG_LEVEL` env vars. All modules use `log.setup("replay")`.

**2.9 Database migration mechanism** ✅
`db.py` contains a versioned migration system (`_MIGRATIONS` list, `schema_version` table). Each migration function is applied once; version is tracked and committed.

### M2 exit criteria — all met

- ✅ Streaming endpoints no longer load all matches per request
- ✅ `server.py` is substantially smaller with logic in focused modules (1800 → 1150 lines)
- ✅ Schema changes go through versioned migrations

---

## Milestone 3 — UX & Frontend Structure ✅ COMPLETE

**Goal:** make the frontend easier to extend and improve the day-to-day user experience.

### Frontend modularization

**3.1 Split `script.js` into logical modules** ✅
Split the monolithic `script.js` (~2300 lines) into 6 ES modules using a mixin pattern — no build step. `script.js` (284 lines) is now the entry point that imports and assembles mixins from `js/utils.js`, `js/api.js`, `js/player.js`, `js/uploads.js`, and `js/views.js`. Inline `onclick` handlers preserved via `window.app`.

**3.2 Centralize UI feedback** ✅
Added `js/ui.js` with a toast notification system (success/error/info) and `btnLoading()` helper for button loading states. All 10 `alert()` calls replaced with non-blocking toasts. Animated slide-in/out with dismiss buttons, styled to match the dark theme.

### User experience

**3.3 Transcode progress reporting** ✅
`media.py` now probes video duration before transcoding and uses `ffmpeg -progress pipe:1` to parse `out_time_us` in real time. Progress (percentage + stage label) is stored in a module-level dict and exposed via `GET /api/matches/{id}/transcode-progress/{slot}`. The frontend polls this during transcoding and displays percentage on match cards ("PROCESSING 42%"), game status pills, and segment buttons.

**3.4 Match search and pagination** ✅
Added client-side instant search filtering in the season view — search bar filters matches by team name, location, or date as you type. Server-side `search_matches()` in `db.py` supports `?q=&page=&limit=` query params on `GET /api/matches` for future use; existing no-param calls return the full list (backward-compatible).

**3.5 Thumbnail generation** ✅
During transcoding, a JPEG thumbnail is extracted at 10% of video duration (scaled to max 640px width) and saved as `thumb.jpg` in the match directory. The first slot to complete generates the thumbnail; subsequent slots skip if one exists. Thumbnails are served via `GET /api/matches/{id}/thumbnail` and displayed as a subtle background image on match cards. Match data includes `has_thumbnail` computed at load time.

**3.6 Playback quality-of-life** ✅

- **Resume playback**: position saved to localStorage every 3s, restored on re-open (skipped if near start/end or video finished)
- **Speed memory**: playback rate persisted in localStorage, applied automatically on next video load
- **Keyboard shortcuts**: Space/K (play/pause), J/Left (back 10s), L/Right (forward 10s), Shift+Left/Right (30s), F (fullscreen), M (mute), < > (speed), 0/Home/End (seek)
- **Match navigation**: prev/next buttons in game view header, based on date-sorted match order

**3.7 Multi-user support** ✅
Three roles: **admin** (full access + user management + settings), **uploader** (create/edit matches + upload), **viewer** (read-only). The env-var admin (`ADMIN_USER`/`ADMIN_PASS`) always works as superadmin. DB-stored users managed via admin UI in Settings. Password hashing uses `hashlib.scrypt` (no extra dependency). Login returns role, UI adapts visibility per role. 14 new tests cover CRUD, role enforcement, and disabled users.

### M3 exit criteria — all met

- ✅ Major frontend features are separated by responsibility (6 ES modules)
- ✅ Upload and playback failures are surfaced clearly (toast notifications)
- ✅ Finding a past match is materially easier (search + thumbnails)
- ✅ Multi-user support with role-based access (51 tests)

---

## Milestone 4 — Media Hardening & Ops ✅ COMPLETE

**Goal:** make the media pipeline recoverable, expand admin diagnostics, and harden for production.

### Media pipeline hardening

**4.1 Formalize processing state machine** ✅
Kept existing `none/transcoding/ready/error` states (adding uploading/queued would require too many changes for marginal benefit). Added `video_errors` table (migration v3) to persist failure reasons with error codes: `disk_full`, `probe_failed`, `all_methods_failed`, `unexpected_error`. Errors are logged automatically during transcode failures and exposed via `GET /api/admin/matches/{id}/errors`.

**4.2 Retry and recovery actions** ✅

- **Retry failed transcode**: `POST /api/admin/matches/{id}/slots/{slot}/retry` — checks for raw upload or MP4, resets to "transcoding" and kicks off background task
- **Regenerate HLS**: `POST /api/admin/matches/{id}/slots/{slot}/regenerate-hls` — rebuilds HLS from existing MP4 without re-transcoding
- **Verify asset integrity**: `GET /api/admin/matches/{id}/verify` — per-slot report of MP4 existence/size, HLS completeness, missing variants
- **Clean orphaned files**: Enhanced `POST /api/uploads/sessions/cleanup` now also removes orphaned `raw_*.tmp` files and expired completed sessions (>7 days)

**4.3 Expand admin diagnostics** ✅
Enriched `GET /api/admin/diagnostics` with: `failed_slots` (count + details), `active_jobs` (with progress/stage/elapsed), `recent_errors` (last 10 from DB), `disk_usage_by_match` (top 5). Admin panel UI shows active transcode jobs with progress bars, failed slots with Retry/Verify buttons, and recent error history.

### Feature enhancements (deferred to M5)

**4.4 Video clipping / highlights**
Allow admins to mark time ranges within a match video as "highlights" or "clips." Generate sub-clips on the backend and display them alongside the full match.

**4.5 Match tagging and categories**
Add tags/categories to matches (e.g. "Tournament," "League," "Friendly") with filtering in the season view. This extends the existing Home/Away filter system.

**4.6 Bulk operations**
Support bulk delete, bulk re-transcode, and bulk HLS backfill from the admin panel. Currently these must be done one match at a time.

**4.7 Webhook / notification support**
Send a webhook or push notification when a transcode completes. Useful for automated workflows or alerting admins that a video is ready for review.

**4.8 S3 / object storage backend**
Replace filesystem storage with an optional S3-compatible backend for deployments where local disk is limited or where CDN integration is desired. The current `VIDEOS_DIR` abstraction makes this a moderate-effort change.

### Operational readiness

**4.9 Database backup and export** ✅
`POST /api/admin/export-database` returns the SQLite file as a downloadable attachment with timestamped filename. Export button added to admin panel.

**4.10 Deployment documentation** ✅
Created `docs/DEPLOYMENT.md` (Docker/bare-metal setup, env vars reference, reverse proxy, storage layout, backup, resource requirements) and `docs/TROUBLESHOOTING.md` (transcode failures, upload issues, HLS playback, GPU setup, database recovery).

### M4 exit criteria — all met

- ✅ Failed processing can be retried from the UI (retry button + API endpoint)
- ✅ Media state is diagnosable without inspecting files manually (error history, asset verification, enriched diagnostics)
- ✅ Maintenance tasks are documented (deployment + troubleshooting guides)

---

## Milestone 5 — Live Streaming ✅ COMPLETE

**Goal:** let users watch the current match in real time without waiting for upload + transcode.

**5.1 RTMP ingest via MediaMTX sidecar** ✅
Added `mediamtx` service to `docker-compose.yml`. Accepts RTMP push at port 1935, exposes LL-HLS internally on port 8888, exposes a control API on 9997 (internal only). Configured via `mediamtx.yml` with external HTTP auth — every publish hits `/api/live/auth` so the stream key can be rotated without restarting the sidecar.

**5.2 Live stream key management** ✅
Stream key is generated lazily on first read (24 chars of url-safe entropy) and persisted in the `settings` table under the new private key `live_stream_key`. The key is never included in the public `/api/settings` payload (private-key denylist in `settings.public_payload`). Admin endpoints: `GET /api/admin/live/config` (view), `POST /api/admin/live/rotate-key` (rotate).

**5.3 Backend bridge to MediaMTX** ✅
New `live.py` module with three responsibilities: validate publish auth webhook payloads, query the MediaMTX control API for publisher status, and reverse-proxy LL-HLS playlists/segments back to the browser via async streaming. Browsers only ever see the replay origin — MediaMTX's 8888/9997 ports stay on the internal compose network. Status check includes a stale-publisher override: if MediaMTX still reports `path.ready=true` but the HLS playlist's last `EXT-X-PROGRAM-DATE-TIME` is older than `LIVE_STALE_SEGMENT_AGE_SECONDS` (default 90s), the stream is reported offline. Covers cameras (XbotGo Falcon iOS app) that stop recording but leave the RTMP socket open with audio-only data flowing — MediaMTX keeps the path "ready" but stops cutting playable segments. HLS proxy sets per-asset `Cache-Control` (1s on playlists, 60s `immutable` on segments, `no-store` on errors) so a CDN in front of Replay can dedupe segment fetches across many concurrent viewers.

**5.4 Watch Live SPA tab** ✅
Deep-link route `/live` and live view section. New `js/live.js` mixin polls `/api/live/status` every 4s, attaches HLS.js (or native HLS for Safari) to `/api/live/hls/index.m3u8` when a publisher is active, shows an offline placeholder otherwise. Tear-down is wired into all view transitions so leaving the page stops polling and destroys the player. Player attach prefers HLS.js whenever it's supported — Chrome/Firefox/Edge return `"maybe"` from `canPlayType('application/vnd.apple.mpegurl')` but can't actually play HLS natively, so native playback is reserved for Safari/iOS where HLS.js is unsupported. Entry to the live view is via the `season-live-cta` button on the Matches page (state-aware: shows "Live Now / Watch the Match" when active, "Live Stream / Watch Live" when offline). The dedicated nav tab was removed once the season-page CTA proved sufficient.

**5.5 Admin live settings card** ✅
Settings view gains a "Live Streaming" card (admin-only): toggle live on/off, set the public-facing RTMP URL shown to camera operators, customise the offline message and nav label, view/copy the RTMP endpoint and stream key (masked by default), and rotate the key with one click.

**5.6 Test coverage** ✅
13 new tests in `tests/test_live.py`: auth webhook accepts/rejects (correct key, wrong key, non-publish action, wrong protocol), status endpoint shape and disabled-state, HLS proxy 502/404 paths, admin config + rotate flows, and a regression check that the stream key never leaks via `/api/settings`.

**5.7 AirPlay & Chromecast on the live feed** ✅
Watch Live now exposes the same AirPlay + Chromecast buttons as the replay player. AirPlay binds `webkitShowPlaybackTargetPicker` / `RemotePlayback.prompt()` to the `live-video` element so iOS / Safari users can hand the LL-HLS feed to an Apple TV or AirPlay 2 display. Chromecast reuses the global `CastContext` from `js/player.js`; `setupCastFramework` and `onCastConnected` are now view-aware — when the live view is active, casting loads `/api/live/hls/index.m3u8` with `streamType=LIVE` and `application/x-mpegURL`, pauses local audio so the TV doesn't echo, and shows the live cast overlay. `onCastDisconnected` resumes muted local playback if the user is still on the live view. New methods live in `js/live.js` (`initLiveRemotePlayback`, `toggleLiveAirPlay`, `toggleLiveCast`, `castLiveStream`, `resumeLiveAfterCast`); `applyLiveStatus` automatically casts the feed if a session is already up when the publisher comes online.

**5.7.1 Make live AirPlay + Chromecast actually work end-to-end** ✅
The 5.7 wiring shipped the buttons but the underlying transport had three blockers. Fixed all three:
- **Safari macOS AirPlay:** `attachLivePlayer` now branches on Safari (UA + `MacIntel`/touch heuristic for iPadOS) and uses native HLS (`video.src = LIVE_HLS_URL`) instead of hls.js. Hls.js plays via MediaSource, and Safari does not surface AirPlay for MSE-backed video — the picker / `webkitplaybacktargetavailabilitychanged` events only fire for direct HLS sources.
- **iOS post-PIN failure:** the HLS proxy was GET-only, so the AirPlay receiver's HEAD probe returned 405 and the session aborted silently after the user entered the passcode. `live_hls_proxy` now accepts `GET`, `HEAD`, and `OPTIONS`, and `proxy_hls` forwards the method to MediaMTX. It also forwards `Range`, `If-Range`, `If-Modified-Since`, and `If-None-Match` from the inbound request so AVPlayer's ranged segment fetches return `206 Partial Content` instead of a full body (Apple TV refuses HLS playback when a ranged request gets a 200).
- **Chromecast logo-only:** the proxy stripped MediaMTX's CORS headers without setting its own. The Chromecast Default Media Receiver fetches HLS from its own iframe origin and requires `Access-Control-Allow-Origin: *`. `proxy_hls` now adds `Access-Control-Allow-Origin: *`, `Allow-Methods`, `Allow-Headers`, `Expose-Headers: Content-Length, Content-Range, Accept-Ranges, Date`, and `Accept-Ranges: bytes` on every response. Stylesheet cache-busted to `v=20260426c`.

### M5 exit criteria — all met

- ✅ Camera operators get a stable RTMP URL + rotatable stream key
- ✅ Viewers can watch live without authenticating
- ✅ Stream key is never exposed in public payloads
- ✅ Live and replay flows share zero state — leaving Watch Live releases the player

---

## Milestone 6 — Multi-host GPU support ✅ COMPLETE

**Goal:** run the same `ghcr.io/humac/replay:latest` image on both NVIDIA and Intel-iGPU hosts.

**6.1 Hardware-accelerated transcode dispatcher** ✅
`media.py` now picks NVENC or VAAPI per-job via `select_hwaccel()` (auto-detects `/dev/dri/renderD128`; overridable via `REPLAY_HWACCEL=auto|nvenc|vaapi|cpu`). VAAPI command line uses `-hwaccel vaapi -hwaccel_output_format vaapi` with a `format=nv12|vaapi,hwupload` filter so it works whether decode lands on the GPU or falls back to software. CPU fallback path is unchanged.

**6.2 VAAPI userspace in the image** ✅
Dockerfile installs `intel-media-va-driver` (iHD, Gen9+) and `i965-va-driver` alongside `libva-drm2 libva2 vainfo`. Same image transcodes on either GPU; NVIDIA hosts ignore the Intel drivers. `vainfo` available inside the container for diagnostics.

**6.3 Intel compose variant** ✅
`docker-compose-intel.yml` passes through `/dev/dri` and the render node, takes `VIDEO_GID` / `RENDER_GID` from `.env.local` (render's GID is distro-specific), and inlines the MediaMTX config via Compose `configs:` so Komodo only ships one file.

**6.4 Orphaned-transcode sweep at startup** ✅
`_sweep_orphaned_transcodes()` runs in the lifespan startup hook and flips any slot still in `transcoding` state to `error` with `error_code=transcode_orphaned_at_startup`. Transcode jobs are in-process asyncio tasks and cannot survive a container restart, so any `transcoding` row at boot is by definition stale. Reset slots show up in the existing admin "Failed Slots" list and can be retried via the existing UI button — no manual SQL needed after a restart kills a transcode mid-flight.

**6.5 VAAPI-accelerated HLS variant generation** ✅
`build_hls_assets()` now uses `scale_vaapi` + `h264_vaapi -low_power 1` when `select_hwaccel()` picks VAAPI. The bottleneck on Intel hosts wasn't the main MP4 transcode (often a no-op remux) — it was the three parallel libx264 encodes for the 1080p / 720p / 480p variants. With GPU-side resize and encode, encoder CPU usage drops to near zero and wall-clock for HLS generation drops 4-8× on low-power iGPUs. Each variant falls back to libx264 independently if the VAAPI path fails, so a transient driver issue can degrade gracefully instead of failing the whole match.

**6.6 Retry no longer deletes its own source** ✅
The admin retry endpoint promotes the final `<slot>.mp4` to `<slot>_raw.mp4` before kicking off `transcode_video` when no raw upload is on disk. Previously, `transcode_video` did `dest.unlink(missing_ok=True)` against the same path it was about to read from, causing every encoder branch to fail with "No such file or directory" and silently destroying the only copy of the video.

**6.7 Admin Diagnostics moved to Settings view** ✅
The diagnostics panel (disk headroom, active jobs, failed slots, recent errors, upload sessions, cleanup controls) used to sit at the bottom of the Add Match form, which made it visually cluttered for editors and awkward to find when no match was being created. It now lives in the Settings view (admin-only by nav-link visibility); refresh fires on Settings open instead of Add Match open.

**6.8 On-demand thumbnail regeneration** ✅
New `POST /api/admin/matches/{id}/regenerate-thumbnail[?slot=<full|first_half|second_half>]` endpoint and a "Regen Thumb" button on the game view (admin-only). Without `slot=`, falls back to the same priority order as the startup backfill task (full > first_half > second_half). Useful when the slot that finished first isn't the one the admin wants representing the match. The thumbnail endpoint also gained `Cache-Control: no-cache, must-revalidate` + an mtime-based ETag so regenerated thumbs are visible immediately, and the UI cache-busts in-DOM `<img>` tags after a regeneration so admins don't need to hard-refresh.

**6.9 Mobile season-header dead space fix** ✅
On phones the season header stacked the team badge, title/intro block and Watch Live CTA in a column, but `.season-info` carried a desktop-oriented `flex: 1 1 320px`. In a column flex container that 320px basis becomes the minimum *height*, so the intro block padded itself out to ~320px tall and pushed the Watch Live button hundreds of pixels below the description. Added a `@media (max-width: 720px)` override that resets `.season-info` to `flex: 0 1 auto` so the block hugs its content and the CTA sits directly under the intro paragraph. Stylesheet cache-busted to `v=20260426a`.

---

## Dependencies

- **M1 before M2:** tests and CI must exist before major refactors.
- **M2 before M4:** backend modularization before pipeline hardening.
- **M1 before M3:** validation models and test coverage before frontend expansion.

---

## Quick Wins (can ship independently)

| Item | Effort | Impact | Status |
| ---- | ------ | ------ | ------ |
| Single-match DB lookup for streaming endpoints | ~30 min | High — reduces per-request DB load | ✅ Done (M2) |
| Token garbage collection sweep | ~20 min | Medium — prevents memory leak | ✅ Done (M1) |
| Login rate limiting | ~45 min | High — closes brute-force vector | ✅ Done (M1) |
| Pydantic models for match CRUD | ~1 hr | Medium — better validation + docs | ✅ Done (M1) |
| Disk space check before transcode | ~20 min | Medium — prevents failed transcodes | ✅ Done (M1) |
