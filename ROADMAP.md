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
GitHub Actions (`.github/workflows/ci.yml`): compile check for all top-level Python modules (`server.py`, `media.py`, `models.py`, `db.py`, `auth.py`, `settings.py`, `uploads.py`, `log.py`, `live.py`, `streams.py`) + `pytest tests/ -v --cov --cov-report=term-missing --cov-fail-under=60` on push/PR to `main`. `.coveragerc` scopes coverage to application code (excludes `tests/`).

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
15 tests in `tests/test_live.py`: auth webhook accepts/rejects (correct key, wrong key, non-publish action, wrong protocol), internal-secret enforcement and fail-closed missing-secret behavior, status endpoint shape and disabled-state, HLS proxy 502/404 paths, admin config + rotate flows, and a regression check that the stream key never leaks via `/api/settings`.

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

---

## Milestone 7 — Streaming connection visibility ✅ COMPLETE

**Goal:** give admins real-time visibility into who is watching what, the ability to disconnect a stream, and Cloudflare-aware client IP capture so login rate limiting and access logs reflect the real source IP.

- **Stream registry (`streams.py`)** — in-memory `StreamRegistry` tracks active live HLS proxy, VOD HLS, and VOD MP4 range sessions. HLS-style sessions are keyed by `(ip, ua, kind, match_id, slot)` with a 15s idle TTL; long-lived MP4 range requests register one session per request and unregister on iterator close.
- **Cloudflare-aware IP** — `streams.client_ip(request)` reads `CF-Connecting-IP` first, then `True-Client-IP`, then the leftmost `X-Forwarded-For` hop, before falling back to `request.client.host`. Login rate limiting (`auth.py`) uses the same helper.
- **Offline GeoIP** — optional `geoip2` lookup against `app_assets/GeoLite2-City.mmdb`. Returns city/country/country_code; fails open when the DB is missing.
- **Kill switch** — `POST /api/admin/streams/{id}/kill` cancels the in-flight iterator and adds a 5-minute blocklist entry keyed by `(ip, kind, match_id, slot)`. The next HLS segment poll or MP4 range request from that viewer for that resource returns 403. `DELETE /api/admin/streams/blocks` clears a block early.
- **Admin endpoints** — `GET /api/admin/streams` returns `{active, blocks}`. Wired into the existing admin diagnostics card in `index.html` + `js/views.js` with a kill button per row.
- **Background sweeper** — runs every 5s in the FastAPI `lifespan` task, dropping idle HLS sessions and expired blocks.

---

## Milestone 8 — Unified Admin Dashboard ✅ COMPLETE

**Goal:** consolidate the legacy "Add Match" and "Settings" pages into a single `/admin/*` dashboard with sub-routes, role-filtered sidebar navigation, a persistent control-room status strip, and a clearer information hierarchy for operators.

- **Single `#admin-view` shell** (`index.html`) replaces the separate `#add-match-view` and `#settings-view` sections. Layout is a CSS grid: sticky left sidebar + content area. On mobile the sidebar collapses into a horizontal scrollable tab strip.
- **Slug deep links** — `/admin`, `/admin/overview`, `/admin/matches`, `/admin/live`, `/admin/streams`, `/admin/users`, `/admin/settings`, `/admin/system`. `script.js` history routing recognizes both new (`view: 'admin'`) and legacy (`view: 'add-match'` / `'settings'`) state shapes for back/forward continuity.
- **Sub-pages**: Overview (KPI grid + quick actions), Matches (Add/Edit form + transcoding queue, uploader+ accessible), Live (RTMP ingest config + stream-key reveal/copy/rotate + MediaMTX diagnose), Streams (active sessions + blocks with kill switch), Users (role management), Settings (branding + nav/replay labels + downloads toggle), System (diagnostics grid + ops buttons).
- **Status strip** — `js/admin.js:refreshAdminStatusStrip()` polls `/api/admin/diagnostics` + `/api/admin/streams` every 10s while the dashboard is active, surfacing disk, live state, viewer count, encoding count, failed-slot count, and active blocks. Tabular numerals + colored state dots. Tears down on view exit.
- **Role gating (defense in depth)** — sidebar items are filtered client-side; `resolveAdminSection()` redirects non-admins to `matches`; server still enforces `_auth.require_role(request, "admin")` on all `/api/admin/*` endpoints.
- **Settings consolidation** — dropped `nav_add_match_label` and `nav_settings_label` (keys removed from `settings.py` defaults and `js/api.js`). Replaced with a single `nav_admin_label` (default "Admin"). Top nav now exposes one role-aware "Admin" link.
- **New module: `js/admin.js`** — admin shell mixin (sidebar render, section show/hide, status-strip polling, overview KPI tiles, role filter). Existing renderers in `views.js` and `live.js` are reused unchanged; only DOM container layout moved.
- **Aesthetic** — extends the existing dark/Oswald/blue-accent system: status strip with monospace tabular numerals + glowing state dots, sidebar with accent radial-glow halo on the active item, control-room kicker labels (`◉`, `⚡`, `⚙`) in Overview quick-action tiles. No new font imports; all new styles consume existing CSS variables.

---

## Milestone 9 — Replay-First Score De-emphasis ✅ COMPLETE

**Goal:** the site is a replay library, not a results page. Stop spotlighting losses on every visit while keeping scores accessible for anyone who actually wants them.

- **Match cards** — scores are hidden by default behind a small "Reveal score" chip in `.match-detail-row`. Each card flips independently; state lives in an in-memory `_revealedScores` Set, intentionally not persisted, so a refresh hides everything again. Cards with no score recorded render no chip and no numerals.
- **Game (match detail) page** — same hide-by-default behavior. Matchup header renders a muted dash placeholder; a centered "Reveal final score" chip lives in a new `#game-score-reveal` row between matchup and meta. Reveal state is shared with the season grid (one Set), so revealing on cards carries through to the detail page in the same session.
- **Team performance panel** — reframed around what was *played*: Matches Played, Goals Scored, Clean Sheets, Replays Available (count of main-team matches with at least one ready slot). The legacy Record / Points / Goal Diff metrics survive behind a "Show record" toggle so users who want them aren't blocked.
- **Score data is unchanged** — `/api/matches`, the DB schema, and admin entry forms still capture and return scores; this is purely a presentation rework. New helpers `app.revealMatchScore`, `app.isMatchScoreRevealed`, `app.toggleSeasonRecord`, and `app.countAvailableReplays` handle the per-session state and effort-metric counting.
- **Aesthetic** — quiet by default. Reveal chip is an Oswald uppercase 32-px pill (40-px large variant for the game page), eye SVG icon, accent border on hover. Hidden scores use `var(--text-muted)` at 0.45 opacity. Neutral team-stat tiles drop the colored radial accents from the four primary metrics; accents return on the collapsed record strip as left-edge bars.

---

## Sprint — Code Review Hardening ✅ COMPLETE (2026-04-27)

**Goal:** address the five open next-sprint items from the post-M9 code review.

- **M4 — Background task tracking** (`server.py`): added module-level `_background_tasks` set and `_spawn_task()` helper. Every `create_task` for transcodes and startup backfills now goes through `_spawn_task`, which auto-discards on completion and logs any unhandled exception via `logger.error`.
- **M5 — Graceful shutdown** (`server.py`, `media.py`): `lifespan` `finally` block now calls `_media.cancel_active_transcodes()` (terminates in-flight ffmpeg subprocesses and awaits their exit) and then cancels + gathers all remaining background tasks. Added `_active_procs` set in `media.py` and `cancel_active_transcodes()` function; `run_ffmpeg` registers/deregisters each subprocess via `try/finally`.
- **M7 — Match deletion cascade** (`server.py`): `delete_match` now DELETEs orphaned `upload_sessions` and `video_errors` rows inside the same `MATCHES_LOCK` block before `rmtree`.
- **M8 — Upload fingerprinting** (`db.py`, `models.py`, `uploads.py`, `server.py`, `js/uploads.js`): added `first_chunk_hash` column (migration v4). Client computes SHA-256 of the first 64 KB before calling the session bind endpoint; server stores it and uses it as an additional match key in `find_active_session`. Chunk 0 upload also verifies the hash as defense-in-depth, rejecting any attempt to interleave a different file into an existing session.
- **M13 — Audit logging** (`server.py`): all nine destructive admin endpoints now emit `logger.info("admin.action", extra={action, actor, target_id, ...})` structured log events: `delete_user`, `update_user`, `delete_match`, `unblock_stream`, `backfill_hls`, `retry_transcode`, `regenerate_hls`, `regenerate_thumbnail`, `export_database`.
- **M9 — Diagnostics disk-walk cache** (`server.py`): `_cached_disk_usage_by_match()` memoizes the `VIDEOS_DIR` rglob + `stat` walk for 60 s. The walk is dispatched via `asyncio.to_thread` so cache misses don't block the event loop. Previously the System tab (polled every 10 s) issued 120 k+ `stat` syscalls per refresh on a 100-match library.
- **M10 — Bulk transcode-progress endpoint** (`server.py`, `js/api.js`): new `GET /api/transcode-progress` returns all active jobs in one request. `fetchTranscodeProgress()` in `api.js` replaced N per-slot fetches (one per transcoding slot every 5 s) with a single fetch. Added `get_all_transcode_progress()` helper in `media.py`.
- **M11 — HLS variant concurrency cap** (`media.py`): `_hls_semaphore = asyncio.Semaphore(2)` gates entry into `_generate_variant`. With `TRANSCODE_CONCURRENCY=2` and 3 HLS variants per transcode, the previous code could run 6+ concurrent ffmpegs on a 2-core host; the semaphore caps variant processes at 2 at a time.

---

## Sprint — Security Hardening ✅ COMPLETE (2026-04-27)

**Goal:** address M2, M3, M6, and M16 from the post-M9 code review — proxy trust, live auth endpoint security, unbounded match list, and DOM churn from transcode polling.

- **M2 — TRUSTED_PROXY gating** (`streams.py`): added `TRUSTED_PROXY` env var (`cloudflare`/`none`, default `cloudflare`). `client_ip()` now short-circuits and returns the direct peer address when `TRUSTED_PROXY != "cloudflare"`, preventing an attacker on a bare deployment from rotating `X-Forwarded-For` / `CF-Connecting-IP` to bypass login rate limiting. Updated `.env.example` with guidance.
- **M3 — `/api/live/auth` shared-secret + rate limit** (`server.py`): added `LIVE_AUTH_SECRET` env var. When set, the MediaMTX auth webhook endpoint requires `X-Internal-Secret: <value>` to match (configured in `mediamtx.yml`'s `authHTTPHeaders`); mismatches return 401. Added per-IP rate limit (30 req/60 s) using the same sliding-window pattern as login. When the secret is unset a one-time startup warning is logged. Updated `.env.example` with setup instructions.
- **M6 — Cap unbounded `/api/matches`** (`server.py`, `db.py`): `load_matches_unlocked()` now accepts an optional `limit` parameter (uses `LIMIT ?` in SQL when set). The no-args SPA branch passes `limit=500`, capping the response payload to 500 most-recent matches and preventing ~1 MB JSON responses on large archives.
- **M16 — Targeted badge updates instead of full grid re-render** (`js/views.js`, `js/api.js`): `renderSeasonView()` now stamps `data-match-id` on each card. New `updateTranscodeBadges()` method uses `querySelectorAll('.match-card[data-match-id]')` to find cards and updates only the `.match-meta` innerHTML for each card whose status changed. The 5 s transcode-poll timer now calls `updateTranscodeBadges()` instead of `renderSeasonView()`, eliminating 30–80 ms DOM thrash per tick and preserving `:hover` state during active transcodes.

---

## Sprint — Minor Hardening ✅ COMPLETE (2026-04-27)

**Goal:** close out m1, m3, m4, m5, m10 from the post-M9 code review — the last five open minor items.

- **m1 — Document env-var admin bypass** (`auth.py`): added a docstring note to `authenticate_user` explaining that the env-var superadmin always takes precedence over the DB `enabled` flag. Operators should avoid reusing the same username as a disabled DB account.
- **m3 — Cap `?status=` list** (`server.py`): `[:8]` slice on the parsed statuses tuple in `list_upload_sessions` prevents pathologically long comma-separated inputs.
- **m4 — Monotonic block TTL** (`streams.py`): switched `block()`, `is_blocked()`, `list_blocks()`, and `sweep()` from `time.time()` to `time.monotonic()` for expiry arithmetic. `list_blocks()` converts back to wall clock for the API response so `expires_at` remains human-readable. NTP backward jumps can no longer permanently strand a block entry.
- **m5 — Document CGN under-counting** (`streams.py`): added a docstring note to `StreamRegistry` explaining that `(ip, ua)` session keying deliberately under-counts viewers behind carrier-grade NAT, and why this isn't worth fixing.
- **m10 — CSS comment** (`styles.css`): added an explanatory comment on `.team-stat-grid-tiles { grid-column: 1 / -1 }` clarifying that it spans the full width of the parent `.team-stats-grid` row.

## Sprint — Frontend Polish ✅ COMPLETE (2026-04-27)

**Goal:** address m7, m8, m9 from the post-M9 code review — consolidated auth error handling, resilient match list refresh, and safe history fallback.

- **m7 — `authFetch` helper** (`js/api.js`): added `authFetch(url, opts)` to `apiMixin`. On a 401 response it clears auth state, removes the session token, shows the login modal, and throws. Replaced 6 identical 401-handling boilerplate blocks across `js/views.js` (uploadSettingsAsset, handleSettingsSubmit, refreshAdminDiagnostics, handleMatchFormSubmit×2, deleteMatch) and 1 in `js/admin.js` (status strip polling). Future callers get the behaviour for free.
- **m8 — Resilient `loadMatches`** (`js/api.js`): network or non-2xx errors no longer blank `this.matches`. If the list was previously populated, it is preserved and a `showInfo` toast surfaces "Couldn't refresh matches — showing last known data." to the user. On the very first load failure (no prior data) the behaviour is unchanged (empty grid, no toast).
- **m9 — `editMatch` history fallback** (`js/views.js`): when `editMatch(matchId)` is called for a match that no longer exists in `this.matches` (e.g. back-navigation after a delete), it now calls `showAdminView('matches', { pushHistory })` instead of silently no-opping. The user lands on the matches list rather than a blank form.

## Sprint — Concurrency Safety + File Split ✅ COMPLETE (2026-04-27)

**Goal:** address M15 (optimistic concurrency on match edits) and M17 (split overloaded views.js) from the post-M9 code review.

- **M15 — ETag/If-Match on match edits** (`db.py`, `server.py`, `js/views.js`, `tests/test_matches.py`): added `updated_at` column to the matches table (`_migrate_v5`). `create_match` and `update_match` stamp the field with millisecond-precision UTC via `_now_ms()`. `PUT /api/matches/{id}` now checks an optional `If-Match` request header — if the token doesn't match the stored `updated_at`, it returns 409 "Match was modified by another user. Reload and try again." Omitting the header is still accepted (backward-compatible). The edit form sends `If-Match` and shows a user-friendly conflict toast on 409. Two tests added: conflict scenario returns 409; missing `If-Match` still returns 200.
- **M17 — Split views.js** (`js/views.js`, `js/admin-views.js`, `script.js`): extracted all admin renderers and action methods (~1040 lines) from `js/views.js` into a new `js/admin-views.js` module exporting `adminViewsMixin`. `js/views.js` is now ~610 lines covering only public-facing views (season, game, score reveal, team stats). `script.js` imports and spreads both mixins. Zero behavior change — all methods remain on `window.app`.

## Sprint — Ops Quality ✅ COMPLETE (2026-04-27)

**Goal:** address M12, M14, m2, and m6 from the post-M9 code review — GPU health visibility, structured logging, stale upload session cleanup on startup, and path containment.

- **M12 — GPU health signal** (`media.py`): added `_gpu_stats` dict tracking `succeeded`/`failed` GPU encode attempts (incremented by `transcode_video` and `_generate_variant` at NVENC/VAAPI decision points). `get_gpu_health()` returns a snapshot; the `/api/admin/diagnostics` response now includes `transcode.gpu` so operators can see at a glance if VAAPI/NVENC is silently falling back to CPU on every job.
- **M14 — Structured logging at high-signal sites** (`media.py`, `server.py`, `live.py`): added `extra={}` kwargs to key log calls — transcode acquire/start/done/failed (media.py), upload session create/complete/start/save (server.py), live auth accept/reject (server.py), MediaMTX HLS proxy failure and stale-publisher detection (live.py). These fields now appear as top-level keys in the JSON log formatter output, enabling log-based alerting.
- **m2 — Cancel stale upload sessions on startup** (`server.py`): `lifespan` now calls `_uploads.cleanup_stale_sessions(STALE_UPLOAD_SESSION_SECONDS)` during startup. Sessions that were `'active'` when the server was killed and have been idle longer than the stale threshold (default 6 h) are marked `'cancelled'` instead of remaining stuck at `'active'` until a client manually cleans them up.
- **m6 — Path containment on thumbnail/logo endpoints** (`server.py`): `serve_thumbnail` and `serve_logo` now call `.resolve()` on the constructed path and verify `VIDEOS_DIR.resolve()` is an ancestor before serving. Prevents path-traversal via a crafted `match_id` in the URL from escaping the videos directory.

## Sprint — VOD + Live Optimization for 10 GbE LAN ✅ COMPLETE (2026-04-28)

**Goal:** maximize concurrent-stream quality and throughput on a Terramaster F6-424 Max (Intel i5-1235U Iris Xe + QuickSync, 32 GB RAM, 10 GbE LAN, 3 Gbps WAN) without breaking the existing GPU/CPU fallback chains. Implemented sections E2 + A + B + F of the corresponding plan.

- **E2 — Settings-driven tuning** (`settings.py`, `db.py`, `server.py`, `js/admin-views.js`, `index.html`, `styles.css`):
  - 13 new keys in the settings table cover every tuning knob that used to be env-var-only: `transcode_concurrency`, `replay_hwaccel`, `hls_segment_duration`, `hls_variant_presets` (JSON ladder), `min_free_disk_bytes`, `upload_disk_headroom_multiplier`, `stale_upload_session_seconds`, `video_stream_chunk_bytes`, `upload_chunk_size_bytes`, `max_upload_size_bytes`, `live_hls_variant`, `live_record_enabled`, `live_transcode_enabled`. Each has a `TUNING_KNOBS` schema entry (kind, range, restart-required flag, label, help text).
  - `normalize_value()` extended with int / float / bool / enum / json coercers and range clamps. Server-side validation returns structured errors keyed per-field.
  - **Env-fallback on first boot:** if the matching `os.environ` value is set and no DB row exists yet, the env value seeds the setting once and is then ignored. Existing deployments don't reset on upgrade.
  - **`ResizableSemaphore`** (`server.py`): wraps `asyncio.Semaphore` with `resize(new_n)` so changing `transcode_concurrency` in the UI takes effect without a restart.
  - `settings_audit` table (`_migrate_v6`): one row per tuning change with `{ts, key, old_value, new_value, actor}`. Surfaced in the admin UI under the Performance Tuning fieldset.
  - **Admin UI**: `renderTuningKnobsCard()` renders a typed input per knob (number, select, checkbox, JSON ladder editor), shows a "Restart required" pill on knobs that don't live-reload, and includes three one-click presets — **Conservative**, **Balanced 10 GbE** (`transcode_concurrency=4`, `replay_hwaccel=qsv`, `hls_segment_duration=4`, larger chunk sizes), **Live-first** (`replay_hwaccel=qsv`, `live_hls_variant=lowLatency`, `live_record_enabled=1`, `live_transcode_enabled=1`).
- **A — Encoder & ABR upgrades** (`media.py`, `settings.py`):
  - **QSV path** (`h264_qsv` with `-preset veryslow -look_ahead 1 -async_depth 4 -global_quality 21`) added to both `transcode_video` and `build_hls_assets`. `select_hwaccel("qsv")` picks QSV first; auto-detection prefers QSV when `/dev/dri/renderD128` exists.
  - **Resilient fallback chain**: QSV → VAAPI → CPU within a single transcode, so a transient QSV failure no longer escalates straight to libx264. Per-method `_gpu_stats` counters (`qsv_succeeded`, `vaapi_failed`, etc.) and aggregate counters both tracked.
  - **1440p tier** added to the default `_DEFAULT_HLS_VARIANT_PRESETS` (9 Mbps video, 192k audio), gated by source height — 1080p uploads still produce 3 renditions, not 4.
  - **Audio bitrate** raised from 128k to 192k for 1080p+ renditions and the full-resolution MP4 transcode (CPU + GPU + remux paths).
- **B — Delivery layer** (`Caddyfile`, `docker-compose.yml`, `docker-compose-intel.yml`, `server.py`):
  - **Caddy reverse proxy** added as a third compose service and made the **single public entry point** for the stack. Host publishes `8090:80` (Caddy listens on `:80` inside the container; `8090` on the host preserves the existing public address so Cloudflare Tunnel rules and `mediamtx → replay:8090` internal calls keep working). The replay app no longer publishes its own port — it sits on the internal compose network only via `expose: "8090"`. Caddy serves VOD HLS `.ts/.m4s/.mp4` segments + variant playlists directly from the `/data` bind-mount (read-only) via `sendfile()`, and reverse-proxies everything else (live HLS proxy, MP4 ranges, all `/api/*`, SPA shell) to `replay:8090`. Drops Python out of the hot path so 10 GbE on segment reads is achievable.
  - **HLS cache headers** in `server.py` aligned with the live proxy's policy (`live.py`): playlists `public, max-age=60, must-revalidate`, segments `public, max-age=31536000, immutable`. Fixes the latent staleness bug where a re-transcode would be served from cache for an hour.
- **F — Performance Tuning admin panel** (`server.py`, `media.py`, `streams.py`, `js/admin-views.js`, `js/admin.js`, `index.html`, `styles.css`, `requirements.txt`):
  - **`GET /api/admin/performance`** aggregates host signals (CPU%, load, memory, swap, NIC bps, Intel iGPU busy via i915 sysfs), throughput rollups (live + VOD bps with 30 s averages), per-pool disk free, recent transcode realtime factors, GPU stats counters, and active streaming sessions — all in one JSON payload.
  - **Ring buffers** populated on the existing `streams.sweeper_task`: `_throughput_samples` (600 entries) and `_transcode_history` in `media.py` (50 entries; appended at remux/GPU/CPU success points with `wall_seconds`/`source_seconds`/`rt_factor`).
  - **60-s capture window**: `POST /api/admin/performance/capture` flips the sweeper to 1 Hz sampling for 60 s and auto-disengages.
  - **Frontend panel** under `/admin/system`: `.diagnostic-card` KPI tiles refreshed every 5 s, plus recent-transcodes and active-sessions lists. Reuses existing styles.
  - **Snapshot export**: copy-to-clipboard + JSON download buttons bundle the latest `/api/admin/performance` payload for sharing with a coding agent.
  - **`psutil` added to `requirements.txt`** for the host-signals helper; gracefully degrades if missing.

## Sprint — Storage Tiering (TrueNAS two-pool layout) ✅ COMPLETE (2026-04-28)

**Goal:** stop the SSD pool filling up with raw uploads + finished MP4s. The hot path (HLS variants + thumbnails) stays on the SSD, while cold assets move to a configurable second volume — typically a dedicated ZFS dataset on the HDD pool.

- **`REPLAY_ORIGINALS_DIR` env var** (`server.py`): when set, points at a separate filesystem for `<match-id>/<slot>.mp4` (finished, transcoded) and `<match-id>/<slot>_raw.{mp4,mkv}` (raw uploads). Defaults to `VIDEOS_DIR` so existing single-volume deployments are unchanged. The directory is mkdir'd at startup so a fresh bind mount inside the container "just works."
- **`media.py` helpers**: `match_originals_dir`, `slot_mp4_path`, `slot_raw_path`, `find_slot_raw_path`. All paths flow through these so future call sites pick up the split for free.
- **Server-side wiring**: chunked upload session creator + legacy single-shot upload + `/retry` (with `?force=true`) + `/regenerate-hls` + `/regenerate-thumbnail` + `/verify` + MP4 stream + MP4 download + delete-match + HLS backfill + thumbnail backfill all read/write through the helpers. Per-match disk-usage walker tallies bytes across both trees so the admin Diagnostics shows the true footprint.
- **`uploads.cleanup_orphaned_raw_files`** walks both `videos_dir` and `originals_dir` (de-duplicated by resolved path) so a stale raw file in either tree gets removed.
- **Compose**: `docker-compose-intel.yml` now sets `REPLAY_ORIGINALS_DIR=/originals/videos` and bind-mounts the recommended HDD path `/mnt/tank/media/replay → /originals`. Disabling tiering = comment out the env var + bind mount.
- **Tests** (`tests/test_uploads.py` + `tests/conftest.py`): two new tests confirm the chunked upload session writes its `raw_path` into `ORIGINALS_DIR` when tiered, and into `VIDEOS_DIR` (alias) when un-tiered. Conftest adds an `ORIGINALS_DIR == VIDEOS_DIR` default so all existing tests keep passing without modification. 132/132 pass.
- **Capacity model** (per the user's actual pool sizing): SSD pool at 197 GiB used / 678 GiB free comfortably holds 130–200 hot matches' HLS + thumbnails (~3.5–5 GB per match across 3 variants). HDD pool at 21 TiB used / 10 TiB free absorbs 2,500+ matches of cold archive. ZFS ARC + the 32 GB host RAM cache the working set transparently for cold reads.

## Sprint — Match Library Consolidation (admin UX) ✅ COMPLETE (2026-04-28)

**Goal:** Stop scattering match-and-video state across Overview, Matches, and System. `/admin/matches` becomes the single library — a table of recorded matches with format and per-slot status — and per-match diagnostics live on the row that owns them. The always-mounted "Add/Edit Match" form moves into a modal so the page name finally matches the page content.

- **Match Library table** (`js/admin-views.js`): `renderMatchLibraryTable()` lists every recorded match with date, matchup, format (Full / Halves), per-slot status pills (1H / 2H / Full), revealed score, and last-updated. Filter bar offers free-text search, status filter (Ready / Encoding / Error / No video), format filter, and sort. The header strip shows live counts (total · encoding · failed) derived from the same `this.matches`.
- **Expanded row diagnostics**: each row toggles open into a `<tr class="match-detail-row">` that renders one card per active slot. Cards expose **Verify** (`/api/admin/matches/{id}/verify`), **Regen HLS** (`POST .../regenerate-hls`), **Re-transcode** / **Force Re-transcode** (`POST .../retry?force=true`), **Retry** (`POST .../retry`), **Logs** (modal sourced from `/api/admin/matches/{id}/errors`), and **Regenerate Thumbnail** (`POST .../regenerate-thumbnail`). Admin gating preserved via `isAdmin()` — uploaders see Verify and Logs only.
- **Add Match modal** (`js/ui.js`, `index.html`, `js/admin-views.js`): `openAppModal` gains a new `kind: 'form'` that mounts caller-provided DOM into the existing `.app-modal-card` shell. Exposed as `app.formModal({ body, onSubmit, … })`. `app.openAddMatchModal()` and `app.openEditMatchModal(matchId)` clone the form from `<template id="match-form-template">` in `index.html` — every original input id (`f-home-team`, `f-video-full`, …) is preserved so existing handlers (`handleFormSubmit`, `toggleFormatFields`, `uploadFileIfSelected`, `uploadVideoIfSelected`, `editMatch`, `renderEditAssetStates`) work unchanged.
- **System page trim** (`index.html`, `js/admin-views.js`, `js/admin.js`): the Failed Slots panel, Active Transcode Jobs panel, and Library Maintenance card are gone from `/admin/system`. Counts still surface as diagnostic tiles ("Failed Slots", "Matches" — ready/processing breakdown) and the global status strip. `renderLibraryMaintenance()` was deleted; the obsolete `renderTranscodingQueuePanel()` / `#matches-queue-list` was removed because its data is now visible per-row.
- **Overview tweaks** (`index.html`, `js/admin.js`): the "Add a match" quick-action tile now opens the modal directly. The "Failed Slots" KPI note points at the new flow ("Open Matches → expand a row to retry").
- **Form submit flow** (`js/admin-views.js`): on success, the handler now refreshes `loadMatches()` and re-renders the library table in place instead of navigating to the public season view, so admins stay on `/admin/matches` after creating a match. `cancelEdit()` is null-safe across detached DOM (modal teardown).
- **CSS additions** (`styles.css`): `.match-library-table` (plus row states `is-error` / `is-encoding` / `is-ready`), `.slot-pill`, `.format-pill`, `.row-menu` / `.row-menu-list`, `.slot-diagnostics-panel` / `.slot-cards-grid` / `.slot-card`, `.app-modal-card.is-form` / `.app-modal-body` / `.modal-form-section`. Mobile breakpoint at 768 px collapses the table into vertical card-style rows. Reuses existing tokens — no new design variables.
- **Validation**: 137/137 pytest pass; all Python modules `py_compile` clean; JS modules parse via `new Function(...)` syntax check.

## Sprint — Admin Re-Layout (Live Console + Performance) ✅ COMPLETE (2026-04-29)

**Goal:** stop forcing operators to bounce between sections during live broadcasts and VOD tuning. Fold the two operator-facing read-only tabs (Streams, System) into the workflow tabs that already need them.

- **Sidebar drops from 7 → 5 sections** (`js/admin.js`): Overview · Matches · Live · Performance · Users · Settings. The standalone `Streams` and `System` entries are gone; legacy URLs redirect via `LEGACY_SECTION_REDIRECTS` (`/admin/streams` → `/admin/live`, `/admin/system` → `/admin/performance`).
- **Live Console** (`/admin/live`, `index.html` + `js/admin-views.js`): two-column cockpit with ingest/key form on the left rail and a read-rail on the right showing live throughput (with a 60-s sparkline), encoder load tile (CPU / iGPU / memory / NIC TX / VOD egress / encoder slots), filtered live viewers list (`kind === 'live'`), and stream blocks. New `startLiveConsolePolling` runs 5 s while the section is active; consumes `/api/admin/streams` + `/api/admin/performance`. ON-AIR pill in the header derives state from `live_enabled` + presence of live sessions.
- **Performance** (`/admin/performance`): rename of the old `/admin/system` page with the tuning knobs co-located on the right (moved out of Settings). Knob change + impact visible without a section switch. Disk + diagnostics rails are now collapsed `<details>` accordions: Recent errors, Upload sessions (server + browser), Recent transcodes, Active streaming sessions, Tuning audit log. Each summary shows a count pill driven by the existing renderers.
- **Matches** library: expanded row gains a "N viewers watching now" pill via `vodViewersForMatch(matchId)`; reads from the cached `this.activeStreams` so cost is zero for collapsed rows.
- **Overview slimmed**: 6 KPI tiles → 4 (Disk · Encoding · Failed · Live), plus a new Recent Activity strip composed from `recent_errors` + `active_jobs` + active stream counts so admins see the last ~8 events without leaving the page.
- **Sparkline helper** (`js/utils.js`): tiny inline-SVG `sparklineSvg(values, opts)` (~25 lines, no chart library). Used today by the Live Console's throughput card; available for any future tile that wants a trend indicator.
- **Light mode input fix** (`styles.css`): `[data-theme="light"] .form-group select` was using `rgba(0, 0, 0, 0.04)` background which read as "disabled grey" in the white page. Changed to `#ffffff` with a visible border to match the other input rules. Same fix applied to the matches library filter bar (`.library-filter-bar input[type="search"]` and `.library-filter-bar select` were using `var(--bg-dark)` which evaluated to the page colour in light mode).
- **CSS additions** (`styles.css`): `.live-console-grid` / `.live-console-rail` / `.live-console-read`, `.live-onair-pill` (with on-air pulse animation), `.live-throughput-row` / `.live-throughput-spark`, `.live-encoder-grid` / `.live-encoder-cell`, `.performance-grid` / `.performance-knobs`, `.diag-accordions` / `.diag-accordion` (open/closed states + count pill), `.activity-strip` / `.activity-event` (tone-bad / tone-good / tone-accent), `.slot-diagnostics-viewers` (VOD viewer pill). All collapse to single column at ≤900 px.
- **Validation**: 137/137 pytest pass; all Python modules `py_compile` clean; JS modules parse via `new Function(...)` syntax check.

## Sprint — Performance Page Redesign + Button Tier Rework ✅ COMPLETE (2026-04-29)

**Goal:** stop the Performance page from drowning the encoder/host metrics under a side-rail tuning column, lighten the diagnostics rails, and sort the button visual hierarchy out across all admin pages.

- **Stacked full-width layout** (`index.html`, `styles.css`): drop the 2-column `.performance-grid` + `.performance-knobs` aside. Encoder & Host card and Tuning Knobs card are now full-width siblings. New `.tuning-knobs-grid` flows knobs into `repeat(auto-fit, minmax(220px, 1fr))` so they fan into 3–4 columns on desktop and stack on mobile.
- **HLS variant ladder hidden behind a `<details>`** (`js/admin-views.js` `renderTuningKnobsCard`): new `FULLWIDTH_KEYS` and `COLLAPSIBLE_KEYS` sets — the ladder editor is the only knob in both today. The wrapper gets `grid-column: 1 / -1` so when expanded it spans the entire tuning row.
- **Three-tier button system** (`styles.css`, `index.html`, `CLAUDE.md`):
  - `.btn-primary / .btn-secondary / .btn-danger` — form submits + primary CTAs (Save, Cancel). Stepped down from `0.55rem 1rem` → `0.45rem 0.85rem`, font `0.82` → `0.78rem`.
  - `.btn-head` (new) — every section-head action button (Refresh, 60-s capture, Copy snapshot, Download, Backfill HLS, Cleanup uploads, Export DB, the three Tuning presets, plus Live's Copy / Reveal / Rotate / Diagnose). `0.32rem 0.7rem`, `0.72rem`, hairline border, transparent background.
  - `.mini-action-btn` — row-level actions in tables / accordions (unchanged).
- **Flat `.diag-row` template** for all five Performance accordions (Recent errors, Upload sessions, Recent transcodes, Active streaming sessions, Tuning audit). One row, hairline bottom border, no nested dark-grey cards. Errors with a `details` blob wrap the row in a `<details>` so mobile / keyboard users can tap-to-expand the full stack trace (previously tooltip-only).
- **`.diagnostic-value`** bumped from `1.5rem` → `1.7rem` so the metric reads as the primary focus when watching a knob change. Tile minmax tightened from `180px` → `140px` so 8 tiles fit on one desktop row.
- **Light-mode parity** for the new container surfaces — `[data-theme="light"]` overrides for `.diag-accordion` and `.tuning-knobs-grid .form-group-details` flip the `rgba(255,255,255,…)` backgrounds to `rgba(0,0,0,…)`. Without these the new panels were invisible against the off-white page.
- **Cross-browser `<details>` marker suppression**: both `summary::-webkit-details-marker` (webkit) AND `summary::marker` (standards-track) are set to `display: none` on `.diag-accordion`, `.form-group-details`, and `.diag-row-details` so Firefox doesn't render the native triangle alongside the custom `▸` chevron.
- **Upload sessions accordion**: restored per-entry Clear button on resumable browser uploads (an earlier collapse-to-summary made it impossible to target a specific stalled entry when multiple existed). Server uploads + browser-resumable uploads now both render as flat `.diag-row` entries with their own action button.
- **Error timestamps preserve the date**: switched from `slice(11, 16)` (HH:MM only) to `slice(0, 16)` (YYYY-MM-DD HH:MM) so multi-day error spans aren't ambiguous.
- **CLAUDE.md updated** with the three-tier button convention and the new Performance layout invariants.
- **Validation**: 141/141 pytest pass; all Python modules `py_compile` clean; JS modules parse cleanly.


- **M3 hardening follow-up (2026-04-30):** `/api/live/auth` now fails closed when `LIVE_AUTH_SECRET` is missing (503) unless `LIVE_AUTH_ALLOW_INSECURE=1` is explicitly set. Added `MAX_ACTIVE_TOKENS` env knob (default 1000) to reduce unexpected token eviction under multi-user load. Live webhook tests now configure `LIVE_AUTH_SECRET` and send `X-Internal-Secret`, with explicit coverage for missing-header rejection and missing-secret misconfiguration.
- **Warning-clean tests (2026-04-30):** `pytest.ini` now sets `asyncio_default_fixture_loop_scope = function` and filters known dependency-owned Python 3.14 deprecations from `pytest_asyncio.plugin` and `fastapi.routing`; `pytest tests/ -q` reports `146 passed` without warning noise.

## Follow-up — Admin Recent Activity Feed ✅ COMPLETE (2026-04-30)

**Goal:** make Overview's "Recent Activity" a real operational feed instead of a stale replay of old transcode errors.

- **`activity_events` table** (`db.py` migration v7): persisted feed with event type, severity, message, match/slot, actor, metadata JSON, and timestamp. Helpers `log_activity_event()` and `get_activity_events()` return a 72-hour recent window for the dashboard.
- **Diagnostics payload** (`server.py`): `/api/admin/diagnostics` now includes `recent_activity` alongside the existing `recent_errors`. The errors table remains the detailed failure history; it no longer drives the overview feed.
- **Event sources** (`server.py`, `streams.py`): logical events are recorded for match create/update/delete, upload start/complete/cancel, transcode start/success/failure, retry/force re-transcode, HLS regeneration start/success/failure, thumbnail regeneration, settings/tuning/asset saves, live key rotation, user changes, database export, live/VOD-HLS stream start/end/kill/unblock, and HLS backfill. Stream logging is session-level only; segment polls, VOD heartbeats, and per-range MP4 requests stay quiet.
- **Overview UI** (`js/admin.js`, `styles.css`): `renderActivityStrip()` renders persisted activity first, then current active uploads/transcodes/streams as "now" rows. The global 10-second admin status poll also refreshes the overview when it is active, so viewer and activity state no longer sits stale. Empty state now says there has been no recent activity in the last 72 hours.
- **Tests** (`tests/test_admin.py`): diagnostics structure now asserts `recent_activity`, with coverage for direct activity persistence and match-create activity logging.

## Follow-up — CI test improvements ✅ COMPLETE (2026-04-30)

**Goal:** broaden test coverage and gate it in CI so future regressions surface before merge.

- **New test modules:**
  - `tests/test_models.py` (26 tests) — direct Pydantic validator coverage for `LoginRequest`, `CreateMatchRequest`, `UpdateMatchRequest` (extra=forbid + date/time regex), `CreateUploadSessionRequest` (size + SHA-256 hash), `CreateUserRequest` (username charset + role enum + min password), `UpdateUserRequest`, `UnblockStreamRequest`, `StartCaptureRequest` (range bounds).
  - `tests/test_db.py` (28 tests) — schema migrations on a fresh DB (every expected table + schema_version pin), idempotent re-init, slug helpers (`generate_slug` / `ensure_unique_slug`), match upsert / search / pagination / save_matches_unlocked deletion semantics, slug backfill, user CRUD (case-insensitive lookup, ignore-unknown-fields update, return-false-when-empty update), `log_video_error` / `get_video_errors`, and full `activity_events` lifecycle (metadata JSON round-trip, limit, ordering, `max_age_hours` cutoff, corrupt-JSON resilience).
  - `tests/test_server.py` (8 tests) — `ResizableSemaphore` direct unit tests: basic acquire/release, async context manager, grow-releases-waiters, shrink-absorbs-releases, resize-noop, floor-at-1, in-flight-holders-finish-after-shrink. The CLAUDE.md live-resize invariant is now enforced.
- **Extended test modules:**
  - `tests/test_media.py` (now 25 tests) — added path helpers (`slot_mp4_path`, `slot_raw_path`, `find_slot_raw_path` mp4-over-mkv preference), `verify_slot_assets` (missing MP4, complete HLS, missing variants, tiered originals_dir), `select_hwaccel` (explicit / auto / fallback), and ffprobe parsers (`probe_codecs`, `probe_video_dimensions`, `probe_duration`) via mocked `asyncio.create_subprocess_exec`. No real ffmpeg/ffprobe binary is required.
  - `tests/test_matches.py` (now 34 tests) — slug-based SPA deep-links (`/match`, `/match/{slug}`, `/match/{slug}/{slot}`) + no-cache headers, logo upload happy path, viewer-cannot-upload, unsupported-extension rejection, invalid-team rejection, logo serving security headers (PNG → `X-Content-Type-Options: nosniff`; SVG → nosniff + `Content-Security-Policy: script-src 'none'` + `Content-Disposition: inline`, the CLAUDE.md stored-XSS hardening invariant), 404 for unknown match / no upload, thumbnail 404 + JPEG-with-ETag happy path.
  - `tests/test_admin.py` (now 32 tests) — retry happy path (state transition + `transcode.retry_requested` event), force-retry warning event, regenerate-HLS 202 + `hls.regenerate_started` event, regenerate-HLS in-flight 409, regenerate-thumbnail 404 / success / invalid-slot, and the live-resize invariant: `PUT /api/admin/settings { transcode_concurrency }` must call `TRANSCODE_SEMAPHORE.resize()` while leaving the limit untouched for unrelated keys.
- **CI workflow** (`.github/workflows/ci.yml`): now runs `pytest tests/ -v --cov --cov-report=term-missing --cov-fail-under=60`. `requirements-dev.txt` adds `pytest-cov`. `.coveragerc` excludes `tests/` so the percentage reflects application code only. Compile check now also verifies `live.py` and `streams.py`. Baseline coverage on this commit: ~64 % (256 tests, ~6 s).
- **Doc sync:** `CLAUDE.md` + `AGENTS.md` validation snippets updated to the cov-gated command. New tests entry in `AGENTS.md` "Common files."

---

## Follow-up — Coaching Platform MVP ✅ COMPLETE (2026-05-01)

**Goal:** implement the first usable coaching layer from the future roadmap: coaches can maintain a roster, link family/player accounts, create timestamped notes with drawing metadata, build review playlists, and publish feedback to the right signed-in viewers.

- **Roles and navigation** (`auth.py`, `models.py`, `script.js`, `js/api.js`, `index.html`): added a `coach` capability and comma-separated combined roles such as `coach,uploader`. Admins inherit every capability. Signed-in coaches see a new `/coach` workspace; signed-in viewers see `/feedback` for "My Feedback."
- **Coaching schema** (`db.py` migration v8): added `players`, `player_user_links`, `coaching_notes`, `coaching_note_players`, `coaching_note_tags`, `coaching_playlists`, `coaching_playlist_items`, `coaching_playlist_players`, and `coaching_reviews`. Drawings are stored as JSON metadata on notes, not burned into video.
- **Coach APIs** (`server.py`, `models.py`): new coach/admin-gated routes under `/api/coach/*` for roster CRUD, linkable-user lookup, player-user links, notes, and playlists. New signed-in route `/api/my-feedback` returns only team-visible feedback plus player-specific feedback for roster players linked to the current user; `/api/my-feedback/review` records lightweight review completion/reflection.
- **Coach workspace UI** (`js/coaching.js`, `index.html`, `styles.css`): `/coach` supports adding roster players, linking players to user accounts, creating timestamped notes, assigning linked players/tags/visibility, listing notes, and creating playlists from note selections.
- **In-player note capture** (`js/coaching.js`, `js/views.js`, `index.html`): coaches watching a match get a Coach Notes panel in the match sidebar. They can save a note at the current video time, link players, choose visibility, and use a canvas overlay to capture freehand drawing metadata. Existing playback controls are not blocked unless drawing mode is active. _Superseded by **Coaching Platform — UX Restructure** (line 562 below): the in-match panel was deleted and the Coach > Review tab is now the single authoring surface._
- **Player/family feedback view** (`js/coaching.js`, `index.html`): `/feedback` shows linked roster players, published review playlists, and visible coaching notes. Users can jump from a note to the match timestamp and mark notes/playlists reviewed.
- **Design note** (`specs/coaching-platform-design.md`): captures the MVP scope, role/privacy model, backend tables, frontend ownership, and validation approach for future coaching work.
- **Tests** (`tests/test_coaching.py`): covers coach role access, viewer denial, roster account links, player-specific feedback visibility, drawing JSON persistence, team-visible notes, and review tracking. Full suite: `260 passed`.

**Remaining coaching follow-ups:** richer drawing tools (arrows, circles, zones, labels, undo stack), playlist auto-play sequencing with pre/post-roll, roster import/export, coach-facing review-completion dashboards, and rendered clip export.

---

## Follow-up — Telestrator + Review Playlist Playback ✅ COMPLETE (2026-05-01)

**Goal:** turn coaching notes and playlists into a usable review-session workflow.

- **Telestrator tools** (`js/coaching.js`, `styles.css`): upgraded the match-page coach drawing canvas from freehand-only strokes to versioned drawing objects: freehand, arrows, circles, zones, labels/player numbers, spotlight, dim overlay, colors, line width, selection/move, delete, undo, and clear. Legacy v1 stroke drawings still render.
- **Drawing validation** (`models.py`, `tests/test_coaching.py`): coaching note drawing payloads now validate supported versions, object types, normalized coordinates, label length, and size/point limits.
- **Playlist playback** (`js/coaching.js`, `js/player.js`): coach workspace and My Feedback playlists now launch a review-session rail, seek each note moment with pre-roll, pause briefly on the annotated freeze frame, resume through post-roll, and auto-advance with previous/next/pause/restart/exit controls.
- **Playlist API hydration and privacy** (`server.py`): playlist responses include ordered `items` with note details. A visible playlist grants access to its item moments inside the playlist session, while standalone note cards still follow note visibility.
- **Playlist controls** (`index.html`, `js/api.js`): playlist creation exposes pre-roll/post-roll fields and coach playlist rows can edit those timings.

**Remaining coaching follow-ups:** richer roster management, coach-facing review completion dashboards, playlist reordering UI beyond multi-select ordering, typed reflections on playlist finish, and rendered clip export.

---

## Follow-up — Telestrator Pointer Capture Fix ✅ COMPLETE (2026-05-01)

**Goal:** make the telestrator usable end-to-end on the match page.

- **Canvas activates on coach panel mount** (`js/coaching.js`): `setupCoachCanvas` now turns on `display:block` + `pointer-events:auto` every time it runs, not only on first bind. Coaches can pause the video and immediately draw — clicks land on the overlay instead of toggling the native `<video controls>` and unpausing.
- **Dim is a click-to-place action, not an auto-fill on select** (`js/coaching.js`): selecting the Dim tool no longer instantly pushes a full-screen dim object. Dim now behaves like Label — click on the canvas to place it.
- **Spotlight has a usable initial size** (`js/coaching.js`): a click without drag seeds a 16% × 16% spotlight centered on the click instead of a pinhole on a half-black canvas. Drag still resizes from the click point, with an 8% minimum to keep the cutout visible mid-drag.
- **Listener binding separated from activation** (`js/coaching.js`): `setupCoachCanvas` only binds pointer/resize listeners (idempotent on `_coachBound`); new `activateCoachCanvas` / `deactivateCoachCanvas` helpers own activation state and keep the toolbar Canvas On/Off label in sync. Fixes a regression where the Canvas Off toggle was a no-op and where the My Feedback playlist viewer flow force-activated the canvas, blocking video controls for non-coach viewers.

---

## Follow-up — Coach Notes Mode Toggle ✅ COMPLETE (2026-05-01) — _SUPERSEDED_

> **Superseded by [Coaching Platform — UX Restructure](#coaching-platform--ux-restructure--complete-2026-05-01) below.** The Coach Notes mode toggle, the in-match coach side panel, and `#coach-mode-bar` / `#coach-mode-toggle` / `renderCoachingPanel` / `toggleCoachMode` were all deleted later the same day in favour of `/coach?tab=review` as the single authoring surface. This entry is kept as a historical record.

**Goal:** let a coach jump straight into note authoring without scrolling past matchup/score/meta/video-status to reach the form.

- **Sidebar restructure** (`index.html`): the match-page sidebar now hosts three siblings — a coach-mode bar (hidden for non-coaches), the existing `.game-details` block, and `#coach-match-panel`. The coach panel is no longer tucked inside `.game-details`.
- **Coach Notes toggle** (`js/coaching.js`, `js/views.js`, `js/api.js`): a "Coach Notes ▾" button at the top of the sidebar appears only when `app.canCoach()`. Clicking it flips `_coachModeOn`, adds `coach-mode-on` to `.sidebar`, and re-renders the coach panel. CSS swaps which sibling is visible — match details when off, coach panel when on. Mode resets to off when the coach navigates to a different match.
- **Canvas activation gated on mode** (`js/coaching.js`): `renderCoachingPanel` only auto-activates the drawing canvas when `_coachModeOn` is true. With mode off, the panel still binds listeners but leaves `pointer-events: none` so the video remains scrubbable. Toggling mode off calls `deactivateCoachCanvas` to immediately release pointer events.
- **Existing telestrator and form unchanged**: the form fields, telestrator toolbar, and notes timeline are all the same — the toggle just decides where in the sidebar they live and when the canvas is active.
- **Mode-off panel hidden by CSS** (`styles.css`): `.sidebar:not(.coach-mode-on) .coach-match-panel { display: none }` ensures the populated panel stays hidden until the toggle is on. Without this rule, a coach opening a match would see both match details and the coach form stacked, defeating the toggle. `setLoggedOut` (`js/api.js`) also resets `_coachModeOn` and re-runs `setupCoachModeToggle` so the bar disappears on logout.
- **Dedicated toggle button class** (`styles.css`, `index.html`): the toggle now uses a dedicated `.coach-mode-toggle` class (mirroring the existing `.team-stats-toggle` pattern) instead of `.btn-head`, since CLAUDE.md scopes `.btn-head` to `.admin-panel-head` action rows. Includes both dark and light theme variants.

---

## Coaching Platform — UX Restructure ✅ COMPLETE (2026-05-01)

**Goal:** turn the cluttered single-page Coach workspace and the player-facing My Feedback view into focused, intent-driven surfaces, and consolidate note authoring into one place.

- **Coach > sub-tabs** (`index.html`, `js/coaching.js`, `styles.css`): `/coach` is now a sub-tabbed shell — **Roster · Notes · Playlists · Review** — selected via `?tab=` query string and routed through `setCoachTab()`. Roster groups roster CRUD with the player/family Account Link form; Notes and Playlists are list-first with `+ New` modals.
- **`<template>`-cloned forms** (`index.html`, `js/coaching.js`): note and playlist forms moved into `<template id="coach-note-form-template">` / `<template id="coach-playlist-form-template">` and are mounted via `app.formModal()`. The same modal handles create + edit, with `data-field="..."` lookups so there are no duplicate IDs in the DOM.
- **Coach > Review tab** (`index.html`, `js/coaching.js`): a new in-Coach video player (`#coach-review-video`) + telestrator (`#coach-drawing-canvas`) lets coaches pick a match + slot, scrub, freeze, draw, and save a note without leaving `/coach`. Reachable three ways — match picker, "Open in Review" on a Notes row, and the new "Coach this match in Review →" deep link from the match page header.
- **Removed in-match coach side panel** (`index.html`, `js/coaching.js`, `js/views.js`, `script.js`, `styles.css`): `renderCoachingPanel`, `renderCoachTelestratorToolbar`, `toggleCoachMode`, `_coachModeOn`, `#coach-match-panel`, `#coach-mode-bar`, `#coach-mode-toggle`, and the `.coach-match-panel` / `.coach-mode-toggle` / `.sidebar.coach-mode-on …` CSS were deleted. The match page is now clean VOD for everyone; the Coach > Review tab is the single authoring surface.
- **My Feedback restructure** (`index.html`, `js/coaching.js`, `styles.css`): `/feedback` gets a sub-tab strip — **Playlists** (default) and **Notes** — selected via `?tab=`. Linked players move to a compact chip strip (`#feedback-linked-strip`).
- **Focused feedback player modal** (`index.html`, `js/coaching.js`): a new `<template id="feedback-player-template">` powers an in-page modal player. Watching a note or playing a playlist now stays inside `/feedback`, loads HLS via the existing `getStreamUrls()`, overlays the drawing on `#feedback-drawing-canvas`, runs `_startFeedbackHeartbeat()` (every 10 s) so admin "kill" still propagates, and tears down cleanly on close. The playlist controller targets the same modal video, so coach playlist *Preview* and player *Play* share one player.
- **Routing** (`script.js`, `js/coaching.js`): `/coach` and `/feedback` now read `?tab=`, `?match=`, and `?slot=` from the URL on load and on popstate, and `setCoachTab` / `setFeedbackTab` push the new query string via `replaceState` so refresh and copy-link work.
- **Validation:** `pytest tests/ -v --cov` → 262 passed, coverage 64%.

---

## Coaching Telestrator — Multi-Player Formation Overlay (Phase 1) ✅ COMPLETE (2026-05-02)

**Goal:** let a coach highlight multiple players at one freeze frame and visualize their formation shape with a single overlay (the [once.sport](https://once.sport/once-telestrator/) "highlight + connect" effect, minus animation).

- **`formation` object type** (`models.py`, `js/coaching.js`): new v2 drawing object — no schema migration. Carries 3–16 anchors (each `{x, y, player_id?, label?}`) plus a `hull_points` array. Validator caps anchors at 16 and `player_id`/`label` lengths.
- **Painter** (`js/coaching.js paintCoachObject`): paints one dim layer per formation, cuts a spotlight hole at every anchor (mirrors the existing `spotlight` `destination-out` pattern), draws each anchor's outline + numbered/jersey badge, and strokes the convex-hull polygon with a translucent fill in the active swatch color.
- **Authoring** (`js/coaching.js`): new **Formation** tool in the telestrator. **Quick mode** (default) drops auto-numbered anchors at every click; **Linked mode** lets the coach pick roster players first (in placement order) and binds each anchor to a `player_id` with the player's jersey number as the label. Done finalizes (computes Andrew's monotone-chain convex hull, pushes one `formation` object). Cancel discards. Switching tools mid-draft also discards.
- **Selection model** (`js/coaching.js`): formations select-as-a-whole and drag as a unit (all anchors + hull points get the same delta). Per-anchor edit deferred to Phase 2.
- **Forward-compat hook**: per-anchor `player_id` is the seed for Phase 3's animated/tracked anchors. Phase 1 ships static-only.
- **Validation**: `pytest tests/test_coaching.py::test_formation_drawing_validation` — round-trip + min-anchor reject. Full suite: 263 passed.

---

## Coaching Telestrator — Future Phases (designed, NOT shipped)

These phases were designed alongside Phase 1 but deferred. Each builds cleanly on the `formation` object without breaking it.

### Phase 2 — Connectors and per-anchor edit
**Goal:** add explicit relationships between formation anchors (passing lanes, marking assignments) and let a coach nudge a single anchor without redrawing the whole formation.

- New optional `connectors: [{from, to, style}]` field on the `formation` object — each pair of integer indices into `anchors`, drawn as a line or arrow with the formation's color.
- Selection model gains "anchor handle" mode: when a `formation` is selected, render small drag handles on each anchor; dragging a handle updates that one `(x, y)` and re-runs the convex-hull computation.
- Authoring: hold Shift while clicking the Connector tool to chain pairs.
- **Effort:** ~1.5 days. **Schema impact:** additive, no migration.
- **Ship if:** coaches start asking for passing-lane diagrams or can't tolerate "redraw the whole formation to fix one player."

### Phase 3 — Animated keyframes (drawing schema v3)
**Goal:** the formation moves through the video. A coach sets the formation at t=0:42, scrubs to t=0:46, drags anchors to new positions; the painter interpolates as the video plays.

- New drawing wrapper version: `version: 3`. Each object that supports motion gains a `keyframes: [{t, anchors: […]}]` field; legacy v2 objects are treated as a single keyframe at `t=0`.
- New `paintCoachCanvas()` mode: when the video is `playing`, register a `requestAnimationFrame` loop that reads `video.currentTime` and re-renders interpolated anchors (linear lerp between the bracketing keyframes). Stop the loop on `pause` / tab change / drawing-canvas-off.
- Backend migration: `models.py` validators handle both v2 and v3 payloads. v2 reads keep working; v2 writes still allowed for static objects. v3 is opt-in per object.
- Authoring UX additions: a timeline scrubber inside the telestrator showing keyframe markers; **"Set start"** and **"Set end"** buttons that capture the current anchor positions at the current video time.
- **Effort:** ~1.5–2 weeks (the schema/migration + interpolation loop are the bulk). **Schema impact:** v3 wrapper, additive object fields, full backwards compatibility.
- **Ship if:** Phase 1 use confirms coaches actually want the play-through effect — manual keyframing is tedious so validate first. The headline once.sport effect.

### Phase 4 — Server-side player tracking
**Goal:** drop manual keyframing. The system detects player positions from the video and a formation auto-follows the chosen players.

- Background worker (FFmpeg + a tracking model — e.g. ByteTrack on top of YOLO-pose, or a hosted service) runs over `<slot>.mp4` after upload and produces a per-frame `tracks.json` (`[{t, players: [{id, x, y, conf}]}]`) stored alongside the video on `VIDEOS_DIR`.
- New `/api/matches/{id}/tracks/{slot}.json` endpoint serves it (cached, immutable like HLS segments).
- Linked-mode anchors gain a `track_id` field that the painter resolves at runtime — `paintCoachCanvas` looks up the player position at `video.currentTime` and uses it, ignoring the static `(x, y)`.
- Admin diagnostics: re-run tracking, view confidence, manually correct mis-IDs.
- **Effort:** very large — pick the model, pick CPU vs. GPU, build the queue, build correction UI. Realistically 2–4 weeks of focused work plus ongoing model maintenance.
- **Schema impact:** additive — Phase 1 anchors keep working; tracked anchors are a new opt-in field.
- **Ship if:** Phase 3 sees heavy use AND the team accepts a hosted tracking service or owns ML ops. The "magic" once.sport demos show.

---

## Future Track — Fan + Family Engagement

**Goal:** evolve Replay from a working match archive into a club match-day hub that helps families, supporters, and players find the right video moments quickly while preserving the current spoiler-safe public viewing model.

**Product assumptions:**

- Public match viewing remains link-accessible by default.
- Score hiding remains the default presentation for replay surfaces.
- Signed-in features are additive; they should not make the existing family/fan flow feel heavier.
- Fan-facing engagement should avoid public youth-player profiles in v1.

### F1 — Fan-first match discovery

- Feature the latest ready match and current live match more prominently on the season page.
- Add upcoming/not-yet-uploaded fixtures so families can see that a game exists before the recording is ready.
- Add match metadata for competition, tags, and optional visibility.
- Add richer filters for date range, opponent, venue, tag, competition, and video availability.
- Move the public SPA toward server-side paginated search instead of relying on the bounded 500-match payload.

### F2 — Shareable moments and public highlights

- Add shareable timestamp links such as `/match/{slug}/first-half?t=12m34s`.
- Add public highlight entries with title, slot, start time, end time, and optional spoiler flag.
- In v1, highlights should be metadata-driven seek links, not generated video files.
- Expose highlights as match-page chips and optional season-page cards.

### F3 — Optional reactions and moderated comments

- Add lightweight reactions on matches and highlights: cheer, great save, great goal, thanks.
- Add match comments behind a settings toggle, disabled by default.
- Require moderation before comments become public.
- Log moderation activity, not every anonymous reaction, into the admin activity feed.

### F4 — Match-day live experience

- Upgrade `/live` into a match-day page with current fixture, kickoff time, venue, and replay-status messaging.
- Let admins bind the live stream to a scheduled match.
- Add an admin-controlled live announcement banner for delays, weather, or stream status.
- After a live match, surface the recording lifecycle: pending upload, processing, ready.

### F5 — Club identity and supporter surfaces

- Add a richer club home header with team/club banner image, sponsor links, social links, and support copy.
- Add configurable public modules such as "About this team", "How to watch live", and "Support the club".
- Add public collections/playlists: Best goals, tournament weekend, full season, coach picks.
- Keep matches and live viewing visible in the first viewport; do not turn Replay into a marketing-only landing page.

### F6 — Returning-family convenience

- Add a client-only "Continue watching" rail using the existing playback-position storage.
- Add "new since your last visit" indicators for anonymous viewers via localStorage.
- Add optional signed-in favorites/watchlist for viewer accounts.
- Consider calendar-export links for upcoming fixtures once fixture rows exist before uploads.

---

## Future Track — Coaching Platform

**Goal:** let coaches turn recorded match video into structured teaching material: timestamped notes, drawing overlays, review playlists, and private player/family feedback.

**Product assumptions:**

- Coaching content starts private.
- Player-specific feedback requires login.
- Public player profile pages are out of scope for v1.
- Families are modeled as normal user accounts linked to roster player records.
- Drawing overlays are stored as metadata only; rendered clip export can come later.
- Public match viewing remains unchanged.

### C1 — Coach workspace and roles

- Add a `coach` capability/role.
- Coaches can create private coaching notes, drawings, review playlists, and player feedback.
- Admins can grant users the access they need across admin, coach, uploader, and viewer workflows.
- Prefer a dedicated `/coach` workspace or a Coach section in the existing admin shell; keep public viewing uncluttered.

### C2 — Roster, player profiles, and family account links

- Add roster records separate from login users.
- A `player` record represents an athlete on the team: display name, jersey number, active flag, and optional internal notes.
- A `user` record remains the login identity.
- Add `player_user_links` so one or more user accounts can access a player's feedback.
- Support common family cases:
  - one parent account linked to one player
  - two parent/guardian accounts linked to the same player
  - one family account linked to multiple siblings
  - older player account linked directly to their own player profile
- Admins/coaches manage roster links manually in v1.
- Do not add public player profile pages in v1.

Suggested data model:

- `players`: `id`, `display_name`, `jersey_number`, `active`, `notes`, `created_at`, `updated_at`
- `player_user_links`: `id`, `player_id`, `user_id`, `relationship`, `created_at`
- Relationship values: `self`, `parent`, `guardian`, `family`

### C3 — Timestamped coaching notes

- Coaches can pause a match and create a note tied to match, slot, and timestamp.
- Notes include title, body, category, tags, visibility, and optional linked players.
- Notes appear as timeline markers and in a side-panel list.
- Clicking a note seeks the video to its timestamp.
- Suggested categories: shape, pressing, transition, set piece, build-up, finishing, defending, goalkeeper, effort, decision.

Suggested data model:

- `coaching_notes`: `id`, `match_id`, `slot`, `timestamp_seconds`, `title`, `body`, `category`, `visibility`, `created_by`, `created_at`, `updated_at`
- `coaching_note_players`: `note_id`, `player_id`
- `coaching_note_tags`: `note_id`, `tag`

### C4 — Drawing overlays and freeze frames

- Coaches can draw arrows, circles, rectangles/zones, player-number labels, and freehand lines on paused video.
- Drawings are stored as JSON overlay metadata, not burned into video.
- Each drawing belongs to a coaching note and re-renders when the note is opened.
- Provide undo, clear, color, and line-width controls.
- Use a canvas or SVG overlay above the existing video player.

### C5 — Review playlists

- Coaches can group notes into playlists such as "First-half pressing" or "Build-up patterns".
- A playlist plays moments in sequence with configurable pre-roll and post-roll.
- Playlists can be private, team-visible, player/family-visible, or unlisted-link visible.
- Coaches can reorder items and add an intro/summary.

Suggested data model:

- `coaching_playlists`
- `coaching_playlist_items`
- `coaching_playlist_players` for player-specific assignments

### C6 — Player and family feedback view

- Signed-in players/families get a **My Feedback** page.
- The page shows only notes and playlists linked to roster players connected to the signed-in user account.
- On match pages, published feedback appears as timeline markers only for authorized users.
- Team-wide published notes can be visible to all signed-in viewers or shared by unlisted link.
- Private coach notes are never visible outside coach/admin users.

### C7 — Assignments and review tracking

- Coaches can assign notes or playlists to players, families, or the whole team.
- Players/families can mark feedback as reviewed.
- Coaches see simple completion status, not invasive watch analytics.
- Add an optional reflection prompt such as "What did you notice?"

### Coaching access rules

- Anonymous users: public matches, public live stream, and public/unlisted fan highlights only.
- Viewer users: normal signed-in viewing plus team-visible coaching playlists.
- Linked family/player users: viewer access plus feedback assigned to linked player records.
- Coach users: create/edit private notes, drawings, playlists, and assignments.
- Admin users: manage users, roster records, player-user links, and all coaching content.

### Coaching test plan

- Backend: migrations, role validation, roster CRUD, player-user link permissions, note/playlist CRUD, drawing JSON validation, visibility enforcement.
- Frontend: coach workspace rendering, note creation, drawing persistence, timeline marker seeking, playlist playback, My Feedback filtering.
- Privacy: anonymous users cannot access private coaching routes; linked users only see feedback for linked players.
- Regression: public VOD, live viewing, score hiding, uploads, admin match library, Cast/AirPlay.
