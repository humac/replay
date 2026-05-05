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

## Coaching Analysis Phase 3a — Per-coaching-note thumbnails (backend) ✅ COMPLETE (2026-05-04)

Backend foundation for Phase 3 (per-note thumbnails for visual scanability of Coach Notes / playlists / My Feedback). This PR ships generation + secure serving only; the UI integration that wires thumbnails into the Coach Notes list, the Coach Review timeline rail, the playlist builder/preview, and My Feedback ships in **Phase 3b**. **No DB schema migration; no API payload changes; no playback/drawing changes.**

- **Path helper** (`media.py`): `coach_note_thumbnail_path(videos_dir, match_id, note_id)` returns `<videos>/<match_id>/coach_thumbs/<note_id>.jpg`. Single-sourced so the convention can't drift; the serving endpoint and the generator both call this helper.
- **Generator** (`media.py`): `generate_thumbnail_at_timestamp(src, dest, *, timestamp_s)` extracts a JPEG still at an absolute timestamp via the existing `run_ffmpeg` helper. Best-effort: clamps negative timestamps to 0, clamps timestamps past `duration` to `duration - 1`, returns `False` (not raises) on missing source / ffmpeg crash, and logs a warning so the failure is observable without blocking the parent task.
- **Generation hooks** (`server.py`): `POST /api/coach/notes` and `PATCH /api/coach/notes/{id}` (only when `match_id` / `slot` / `timestamp_seconds` change) both schedule `_spawn_coach_note_thumbnail(note)` via the existing `_spawn_task` helper. The note save returns to the client immediately; the ffmpeg call runs in the background. A failure in the generator never blocks the note response — locked in by the `test_thumbnail_create_does_not_break_when_generator_raises` test.
- **Note delete cleanup** (`server.py`): `DELETE /api/coach/notes/{id}` now `unlink(missing_ok=True)`s the per-note thumbnail file too, so a deleted note doesn't leave an orphan JPEG behind. OS errors are logged, not raised.
- **Serving endpoint** (`server.py`): `GET /api/coach/notes/{note_id}/thumbnail` requires any signed-in user (`_auth.require_auth`), then enforces visibility via the new `_can_view_coach_note(user, note)` helper which **reuses the existing `_filter_notes_for_user`** so the visibility ladder (private / team / unlisted / player) cannot drift between this endpoint and `/api/my-feedback`. Returns `image/jpeg` with `Cache-Control: public, max-age=300, must-revalidate` + `X-Content-Type-Options: nosniff`. Unknown notes, notes the user can't see, AND missing files all return the same `404` so a viewer cannot probe the existence of private notes via the thumbnail endpoint.
- **Manual regenerate endpoint** (`server.py`): `POST /api/coach/notes/{note_id}/thumbnail/regenerate` is gated to coach/admin via `_require_coach`. Synchronous on purpose — returns `{ok: true, generated: bool}` so the UI can distinguish "regen ran and produced a file" from "regen ran but the source MP4 is still missing" (e.g. note created before the match's video finished transcoding).
- **Playlist privacy boundary**: the standalone thumbnail endpoint deliberately does NOT honour the playlist-grants-access rule for private items. A viewer who can play a private note inside a visible playlist (per the existing rule) cannot fetch that private note's standalone thumbnail. This matches the existing `/api/my-feedback/notes` behaviour, which only surfaces private notes via `playlists[].items[]`. A future Phase 3b can add a `?playlist_id=X` query parameter that accepts the playlist context if the playlist UI needs in-rail thumbnails for private items; this PR scopes that out explicitly.
- **Tests** (`tests/test_coaching.py`, +13 new): `test_thumbnail_404_when_file_missing`, `test_thumbnail_404_for_unknown_note`, `test_thumbnail_requires_auth`, `test_thumbnail_admin_and_coach_can_access_team_note`, `test_thumbnail_team_visible_note_reachable_by_signed_in_viewer`, `test_thumbnail_player_visible_only_to_linked_family`, `test_thumbnail_private_note_never_leaks_to_viewer`, `test_thumbnail_for_playlist_private_item_blocked_via_standalone_endpoint`, `test_thumbnail_create_does_not_break_when_generator_raises`, `test_thumbnail_regenerate_requires_coach`, `test_thumbnail_regenerate_handles_unknown_note`, `test_thumbnail_regenerate_returns_ok_false_when_source_missing`, `test_thumbnail_path_convention`. Uses a `monkeypatch`-installed stub for `generate_thumbnail_at_timestamp` so tests don't depend on real ffmpeg — the stub writes a tiny `\xff\xd8\xff\xd9` JPEG payload synchronously so the file-existence check succeeds.
- **Validation**: `python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py log.py live.py streams.py` clean; `node --check js/coaching.js js/api.js js/player.js script.js` clean; `pytest tests/test_coaching.py -v` 23/23 passed (was 10, +13 new); `pytest tests/` 285 passed (was 272, +13 new).

Phase 3a is intentionally a backend-only PR. The Phase 3b follow-up will: (a) render thumbnails in the Coach Notes list and Coach Review timeline rail, (b) add thumbnails to the Coach Playlist builder + Preview, (c) render thumbnails in My Feedback notes + playlists, and (d) add a back-fill admin trigger for matches whose notes pre-date this PR.

---

## Coaching Analysis Phase 2 — Coach Review templates ✅ COMPLETE (2026-05-04)

Reduce coach typing and make structured coaching notes more consistent. Adds a static template registry and a template selector inside the Coach Review note composer. **No backend changes; no new endpoints; no schema migrations.**

- **`js/coaching-templates.js`** — new module exporting `COACH_TEMPLATES` (14 templates), `COACH_TEMPLATE_GROUPS` (7 ordered groups), and `findCoachTemplate(id)`. Each template prefills `title`, `category`, `note_type`, `player_summary`, `what_happened`, `why_it_matters`, `what_to_do_next`, and `tags`. Templates **never** populate `coach_private_note` — that field stays empty unless the coach types into it.
- **Templates shipped** (grouped by soccer area):
  - **Build-up**: Scanning before receiving · Body shape when receiving · First touch direction · Passing decision · Movement after pass
  - **Shape**: Width and depth
  - **Defending**: Defensive recovery · Pressing trigger · Delay/contain in 1v1 defending · Tracking runner
  - **Goalkeeper**: Goalkeeper distribution
  - **Set piece**: Set-piece marking
  - **Transition**: Transition reaction
  - **Finishing**: Finishing choice
- **Coach Review composer** (`renderCoachReviewForm` in `js/coaching.js`) — new "Template" row above the title input with a `<select>` (grouped by `<optgroup>`), an "Apply" button, and a "Clear" button. Apply is disabled until a template is selected; Clear resets the selector + active-template tracking without erasing field content.
- **Overwrite-protection (Option A from the spec)** — `applyCoachTemplate(id)` only prompts when the coach has TYPED content the previous template (if any) did not write. Default `<select>` values (category=`shape`, tone=`correction`) on a fresh composer are treated as untouched, so the first apply onto an empty composer never asks. Switching templates after applying one is silent (the existing values came from a template, not the coach). Switching templates after a manual edit shows the existing `confirmAction` modal with "Replace" / "Keep my edits" buttons.
- **Save flow unchanged** — `saveReviewNote()` still sends the same Phase 1 payload shape; the per-moment field-clearing block now also resets the template selector + the active-template tracker so the next moment starts from "None — start from scratch."
- **Privacy** — Templates write nothing to `coach_private_note`. The visibility ladder, role gating, drawing payload, timestamp, player selection, and tone-chip behavior are unchanged. Saving a note opens the focused-modal playback path the same way it did before; My Feedback rendering is untouched.
- **Accessibility** — Selector has `aria-label`; Apply / Clear buttons toggle `aria-disabled`. The Sprint 7 keyboard-shortcut guard (`_coachShortcutShouldSkip`) already skips `<select>` elements, so ArrowLeft / ArrowRight inside the template dropdown does NOT scrub the video. New CSS includes both dark and light overrides plus `(pointer: coarse)` 44 px tap targets for touch.
- **Light-mode contrast (Issue #80 guardrail)** — The new selector adopts the same light-mode pattern as `[data-theme="light"] .coach-review-picker select`: white background, dark border, dark chevron. Verified text-on-bg contrast ≥ 4.5:1 in light theme.
- **Validation**: `node --check js/coaching.js script.js js/api.js js/player.js js/coaching-templates.js` clean; `pytest tests/test_coaching.py` 10/10 passed; `pytest tests/` 272/272 passed (no new tests — Phase 2 is UI-only and the backend API is unchanged).
- **Live verified** as `coach1` at 1440 + 390 px (dark + light): selector lists 14 templates in 7 groups; Apply on empty composer fills 8 fields without a confirm dialog; manual edit → switch template → Apply shows the confirm dialog and the cancel button preserves the edit; Clear resets selector + active-template state without erasing fields; ArrowLeft inside the selector does not scrub the video.

Phase 2 explicitly does not implement Phase 3 (thumbnails), clips, player profiles, goals, analytics, AI, or computer vision. It also does not extend the Notes-tab Edit modal — Coach Review is the single template authoring surface for this PR. A future phase may move templates from the static frontend registry to a DB-backed customisable set.

---

## Coaching Analysis — PR 1c follow-up: focused player opens paused at the freeze ✅ COMPLETE (2026-05-04)

Playback-behavior follow-up to PR 1c (#79). Pure UX change inside the focused feedback player modal — no rendering changes, no payload changes, no new endpoints.

Standalone-note path (`_loadFeedbackVideoForNote` in `js/coaching.js`)
- The note opens **paused** at the freeze timestamp with the saved drawing visible over the video frame, instead of auto-playing past it. The drawing is a freeze-frame coaching overlay; the player should study it before pressing Play.
- Canvas listeners are bound BEFORE the video paints (was after `loadedmetadata`), so the canvas bitmap dimensions catch up to the wrapper as soon as the layout settles. Fixes a regression where a real video + saved drawing combination still rendered a blank canvas because `setupCoachCanvas`'s ResizeObserver attached after the resize event had already fired.
- Drawing visibility now follows the playhead via a persistent `play` / `pause` / `seeked` listener trio: the drawing reappears whenever the player scrubs back to (or pauses at) the freeze timestamp and disappears whenever they press Play. The cached drawing payload lives on `_feedbackPlayer.noteDrawing` for the entire modal lifetime; `_coachDrawing` (which gets nulled on Play to hide the canvas) is no longer the source of truth.

Playlist path (`openCoachingPlaylistItem` + `startPlaylistMonitor`)
- Each playlist item also opens **paused** at the freeze timestamp with telestration visible — same UX as the standalone note. The previous `pre-roll → freeze → post-roll` auto-play loop made the telestration feel fleeting; pre-roll is now intentionally skipped (the freeze IS the moment; pressing Play reveals the post-roll context).
- `frozeCurrentItem` starts true because we're already at the freeze position; `startPlaylistMonitor`'s only remaining job is to advance to the next item once the post-roll window completes.

New helpers (`js/coaching.js`)
- `_renderFeedbackTelestration()` — paint the cached drawing on the current modal session. Idempotent; safe to call any number of times.
- `_clearFeedbackTelestration()` — hide the canvas without destroying the cached payload, so the modal can re-show it on scrub-back.

Privacy + role gating unchanged. Backend untouched. `coach_private_note` is still server-scrubbed and never templated client-side.

Validation: `node --check js/coaching.js script.js` clean; `pytest tests/test_coaching.py` 10/10 passed; `pytest tests/` 272/272 passed; live verified at 1440 px as `family1` — modal opens with v1 freehand stroke painted on the canvas overlay above the paused video at timestamp 0:05; pressing Play clears the drawing and starts playback; scrubbing back restores it.

---

## Coaching Analysis — PR 1c: My Feedback renders structured fields ✅ COMPLETE (2026-05-04)

Final Phase 1 slice on top of [PR 1a / #75](https://github.com/humac/replay/pull/75) (backend) and [PR 1b / #76](https://github.com/humac/replay/pull/76) (Coach surface). Player/family-facing rendering layer for the structured note fields. **No backend changes; no new endpoints; no new payload fields.**

- **Notes card grid** (`renderFeedbackNotes` in `js/coaching.js`) renders each note as a self-contained card in a responsive grid (4 cols ≥1920 / 3 ≥1440 / 2 ≥1024 / 1 ≤720). Each card carries the accent-tinted **tone pill** (Positive / Correction / Question / Team concept / Individual goal), title, match · timestamp · slot meta, a 2-line clamped `player_summary` (falling back to `body` for legacy pre-Phase-1 notes), and a `▶ Watch` / `Mark reviewed` action row. Cards are designed for scanning — the full structured stack lives in the Watch modal.
- **Playlists card grid** (`renderFeedbackPlaylists`) mirrors the same shape: "REVIEW SESSION" kicker, title, clip count, description, and a `▶ Play session` / `Mark reviewed` action row.
- **Focused Watch modal** (single-note mode) writes the full composition into `[data-field="body"]` via `_renderFeedbackBody`: tone pill + `player_summary` (or `body` fallback) + structured `<dl>` of What happened / Why it matters / What to do next + a collapsed `<details>` "Coach context" disclosure for the long-form `body` when distinct from `player_summary`. The template's `<p data-field="body">` was promoted to a `<div>` (`index.html`) so the `<dl>` + `<details>` markup stays valid.
- **Playlist player rail** (`renderPlaylistSessionRail`) surfaces the per-item tone pill + `player_summary` under "Review Session" so a player watching a session sees the same context they'd see on the standalone note.
- **`coach_private_note` is never rendered.** The server already strips it (`_filter_notes_for_user` + `_strip_private_fields` + the `items_source` scrub for playlist items), but the client renderers also do not template it anywhere — defense-in-depth.
- **New helpers in `js/coaching.js`** (private, prefixed with `_`):
  - `_feedbackNoteSummary(note)` → `{ primary, secondary }` (`player_summary` first, `body` fallback, both shown when distinct)
  - `_feedbackTonePillHtml(noteType)` → accent-tinted pill markup
  - `_feedbackStructuredHtml(note)` → `<dl>` with only the non-empty fields
  - `_renderFeedbackBody(target, note)` → modal-body composition shared by note + playlist surfaces
- **`FEEDBACK_NOTE_TYPE_LABELS`** — player-friendly tone labels (longer than the dense Coach Review chip labels: "Team concept" instead of "Team", "Individual goal" instead of "Goal"). Mirrors the backend `_VALID_NOTE_TYPES` set — keep in sync.
- **Visibility ladder preserved**: `private` → coach/admin only; `team` → any signed-in viewer; `player` → only users linked via `player_user_links`; playlist-item access still flows through visible playlists only.
- **Tests** (`tests/test_coaching.py`):
  - `test_legacy_body_visible_when_player_summary_blank` — a team-visible note with only `body` (no Phase 1 fields) reaches the viewer with `body` populated, `player_summary=""`, and `note_type='correction'` (defaults). Guards the UI's body-fallback path against any future filter that strips `body` alongside private fields.
- **Styling** (`styles.css`) — new `.feedback-tone-pill` block (5 tones × dark + light = 10 themed accents), `.feedback-structured` `<dl>` for the modal body, `.feedback-card-grid` + `.feedback-card-*` rules for the responsive list cards, 44 px tap targets at `pointer:coarse`.
- **Validation**: `node --check js/coaching.js script.js js/api.js` clean; `pytest tests/test_coaching.py` 10/10 passed; `pytest tests/` 272 passed (was 271, +1 new).

Phase 1 of `docs/coaching-analysis-feature-roadmap.md` is now complete: backend (PR 1a / #75) → Coach UI (PR 1b / #76) → player UI (this PR). Playback-behavior follow-ups (paused freeze-frame, telestration scrub-back, pre-roll skip) ship in a separate PR — they touch playback semantics, not rendering.

---

## Coaching Analysis — PR 1b: Coach Review composer + Notes modal surface structured fields ✅ COMPLETE (2026-05-04)

Phase 1 UI layer on top of [PR 1a](docs/coaching-analysis-feature-roadmap.md). Coach Review's note composer now exposes the structured fields the backend already accepts; the Notes-tab edit modal mirrors them so editing parity is preserved. **No backend changes** — every payload field PR 1b sends is already validated by `CreateCoachingNoteRequest` (PR 1a).

- **Tone chip group above Save** (`#coach-review-tone`) — five compact `radiogroup` chips: Positive (`+`) · Correction (`↺`) · Question (`?`) · Team (`⌬`) · Goal (`★`). Mirrors the backend `_VALID_NOTE_TYPES` set; default is `correction` (matches the column default). `setCoachReviewNoteType()` toggles `is-active` + `aria-checked` and stashes the value on the container's dataset so `saveReviewNote()` can read it without a redundant DOM scan.
- **Structured fields inside the existing `<details class="coach-review-advanced">` disclosure** — Player summary (visible-to-player hint), What happened, Why it matters, What to do next, Coach context (private), Long notes, Tags. The default state is unchanged (title → players → category → tone → Save) so the composer stays compact for the common case.
- **`saveReviewNote()`** now sends `note_type` + the 5 structured fields on every save (empty strings when blank). Sticky-on-success: tone chip + category + visibility + selected players persist between saves; per-moment fields (title, body, tags, all 5 structured fields) clear so the composer is ready for the next note.
- **Notes-tab `Edit` modal** (`<template id="coach-note-form-template">` + `openCoachNoteModal()`) extended with the same tone group + structured fields. A note saved via Coach Review can be re-opened in the Notes modal with full round-trip parity.
- **Styling** (`styles.css`) — new `.coach-review-tone` + `.coach-review-tone-btn` + `.coach-review-tone-glyph` block (themed for both dark + light, `pointer:coarse` bumps to 44 px tap targets). New `<small>` hint inside `.coach-review-field-label > span` for the "(visible to player/family)" tag.
- **Validation**: `node --check js/coaching.js script.js` clean; `pytest tests/` 271 passed (no test changes — PR 1a's backend tests already cover create + update + privacy round-trip, and the new UI fields go through that same path).
- **Live verified** as `coach1` at 1440 px: tone chip click flips `aria-checked`; saved note returns `note_type=positive` + all 5 structured fields persisted; Notes-tab Edit modal pre-fills the saved note's tone + fields correctly.

Next: PR 1c — My Feedback rendering shows `player_summary` first (falling back to `body`), groups notes by tone, and never displays `coach_private_note` to viewers (already enforced server-side by PR 1a + the playlist-items follow-up).

---

## Coaching Analysis — PR 1a: Structured-note backend (Phase 1) ✅ COMPLETE (2026-05-03)

First slice of the [coaching-analysis-feature-roadmap.md](docs/coaching-analysis-feature-roadmap.md) Phase 1. **Backend only** — UI + My Feedback rendering ship in PR 1b / PR 1c.

- **Schema migration `_migrate_v9`** (`db.py`) adds six optional columns to `coaching_notes`: `note_type` (enum: `positive` / `correction` / `question` / `team_concept` / `individual_goal`, default `correction`), `what_happened`, `why_it_matters`, `what_to_do_next`, `player_summary`, `coach_private_note`. Each ships with a safe default so every existing pre-v9 note round-trips unchanged. Adds `idx_coaching_notes_note_type`. Defensive `_row_to_note` reads via `_opt(key, default)` so older snapshots / mocks without the new keys still hydrate without `KeyError`.
- **Pydantic validation** (`models.py`) — `CreateCoachingNoteRequest` and `UpdateCoachingNoteRequest` extended with all six fields. New `_VALID_NOTE_TYPES` set; `validate_note_type` field validator raises 422 for unknown values. `strip_text` validator extended to cover the four new long-text fields.
- **Privacy invariant** (`server.py`): `_filter_notes_for_user` now passes every viewer-visible note through a new `_strip_private_fields()` helper that scrubs `coach_private_note` to an empty string. Coach / admin call sites are unchanged (the helper is only invoked on the viewer branch). **Two-path scrub**: `/api/my-feedback` ALSO embeds full note objects under `playlists[].items[]` via `_playlists_with_items`, so `my_feedback` builds a `_strip_private_fields`-applied `items_source` for the viewer branch (`is_privileged ? all_notes : [_strip_private_fields(n) for n in all_notes]`) before passing it to the playlist hydration. This was caught by the original PR #73 code review (after the original merge + revert) — the leak via the playlist-items path is now closed.
- **Tests** (`tests/test_coaching.py`):
  - `test_structured_note_round_trip` — legacy payload (no Phase 1 fields) lands with safe defaults; full structured payload round-trips through create + PATCH; invalid `note_type` returns 422.
  - `test_coach_private_note_never_leaks_to_viewer` — a team-visible note + a team-visible playlist that includes the same note. Asserts `coach_private_note` is empty in BOTH `payload["notes"][]` AND `payload["playlists"][].items[]`. Verified to fail without the `items_source` scrub (i.e. the test catches the bug).
- **Validation**: `python3 -m py_compile` clean across all backend modules; `pytest tests/` 271 passed (was 269 pre-PR).

Next: PR 1b (Coach UI for note tone + structured fields, hidden behind the existing "More details" disclosure) and PR 1c (My Feedback rendering shows `player_summary` first, falling back to `body`).

---

## Coach > Roster redesign ✅ COMPLETE (2026-05-03)

**Goal:** turn the Roster sub-tab into a dashboard-style cockpit (header + KPI tiles + search/filter + roster table + sticky Quick Add panel) inspired by the spec screenshot, while preserving the existing backend payload shapes.

- **Header** with kicker (`TEAM MANAGEMENT`), title, sub, and `Link Account` / `Add Player` buttons. Add Player jumps focus to the Quick Add panel; Link Account opens a cloned `<template id="coach-link-modal-template">` modal mounted via `app.formModal()`.
- **KPI grid** of four tiles computed from the existing `_coachBundle`: Active Players, Linked Accounts (+N this week if `link.created_at` is present), Without Family Link, Avg. Notes / Player. Any KPI that can't be calculated falls back to `—` instead of crashing.
- **Search + filter rail** — `_coachRosterSearch` + `_coachRosterFilter` state in `js/coaching.js`; filtering happens via a fresh array and never mutates `_coachBundle`. Search matches name, jersey, notes, and any linked username / display name. Filter chips use `role="tab"` + `aria-selected` + `aria-pressed` patterns.
- **Roster table** with columns `# / Player / Linked Accounts / Status / Actions`. Jersey shown as a small accent-tinted pill in the `#` column; Status as an active-green / muted-gray pill. Linked accounts render as removable accent chips that call the existing `handleCoachUnlink()`. Action column has compact icon buttons for Link / Edit (UI-only placeholder, disabled) / Delete.
- **Right-side Quick Add Player panel** — sticky on desktop, stacks below the table on tablet / mobile. Fields: Display Name, Jersey Number, Position (UI-only — value is stashed in the existing `notes` field, no backend migration), Link Family / Self Account (uses an existing user select). The new `+ Add to Roster` CTA flows through the same `handleCoachAddPlayer()` payload shape (`display_name`, `jersey_number`, `active`, `notes`).
- **No backend changes.** `CreatePlayerRequest` payload shape unchanged. The "position" field is handled UI-side and persisted via the existing `notes` column so the same payload contract holds.
- **Validation**: `node --check script.js js/coaching.js js/api.js` clean; `pytest tests/` 269 passed; live verified at 1920 / 1440 / 1024 / 768 / 390 px — search filters correctly, filter chips toggle, Link Account modal opens with all 3 selects populated, no horizontal overflow.
- **Screenshots**: `docs/screenshots/roster-redesign-after/` — roster at 5 widths plus modal / search / filter states.

---

## Every-view Fills the Universal Page Shell ✅ COMPLETE (2026-05-03)

**Goal:** the previous unification (below) widened `#app-container` to 2200 px but each view still capped its inner content (Coach 1440, Feedback 980, Admin 1320), leaving large dead bands on either side at 1920 px on every surface except Coach Review. This pass removes those inner caps so each view actually fills the shell.

- **Coach inner caps removed** — `.coach-page-head`, `.coach-grid`, `.coach-subnav`, `.coach-tab-panel` no longer cap; form rows now stretch with the shell. The two-column `.coach-grid` keeps `repeat(2, minmax(0, 1fr))` so the Roster two-card layout still works.
- **Feedback inner caps removed** — `.feedback-content`, `.feedback-linked-strip`, `.feedback-subnav`, `.feedback-tab-panel` (all were 980 px). My Feedback now fills the shell to match Coach.
- **Admin inner cap removed** — `#admin-view` is no longer capped at 1320 px. A small horizontal pad (`0.75rem`) preserves a visible gutter between the sticky sidebar / status strip and the outer `#app-container` edge so the dense control panel still has breathing room.
- **`is-review-mode` width override** in `styles.css` (the `@media (min-width: 1024px) { .coach-page-head, .coach-subnav, .coach-tab-panel { max-width: 100% } }` block) removed — it became a no-op once the inner caps it lifted were gone.
- **AGENTS.md** rewritten under Editing Guidance: "One width for the whole site. Every view fills the shell end-to-end. Don't add per-view outer OR inner max-width caps."
- **Public season + match pages** unchanged — they already used grid `auto-fill` / flex, so they fill naturally.
- **Validation**: `node --check` clean, `pytest tests/` 269 passed; measured at 1920 px — every surface reports container `12 → 1908` with active-view content `32 → 1888`. No body overflow at 1920 / 1440 / 1024 / 768 / 390 px.
- **Screenshots**: `docs/screenshots/site-width-after/` — refreshed.

---

## Site-wide Outer Shell Unification + Coach Tab Inner Caps ✅ COMPLETE (2026-05-03) — *superseded same day by the entry above*

**Goal:** make every view (public season, public match, coach all 4 tabs, my feedback, admin) share one outer page-shell width, so navigating between them never jumps the page edges.

- **Global page-shell width** (`styles.css` `#app-container` ~L179) — promoted the Review-mode `min(100% - 1.5rem, 2200px)` policy to the universal default. Padding dropped from `3rem` to `1.25rem` so content actually reaches the new edges. The previous Review-only override (`body:has(#coach-view.is-review-mode)` block ~L6628) is dropped — it became a no-op once global matched it.
- **Coach inner caps** lifted from `1180px` to `1440px` on `.coach-page-head`, `.coach-grid`, `.coach-subnav`, `.coach-tab-panel`. *(Removed entirely the same day — see entry above.)*
- **Admin shell** kept its dedicated `1320px` inner cap (`#admin-view`). *(Removed the same day — see entry above; admin instead uses a small horizontal pad for sidebar gutter.)*
- **Mobile padding** unchanged — `@media (max-width: 768px)` still sets `1.5rem`, `(max-width: 480px)` still sets `1.1rem`. The new `1.25rem` global only fires above the existing breakpoints.
- **Validation**: `node --check` clean, `pytest tests/` 265 passed; live verified at 1920 / 1440 / 1024 / 390 px across season / public match / coach (all 4 tabs) / my feedback / admin — no body overflow at any width, edges align tab-to-tab and view-to-view.
- **Screenshots**: `docs/screenshots/site-width-after/` — 7 surfaces × 4 widths = 28 PNGs.

---

## Coach Section Alignment Pass ✅ COMPLETE (2026-05-03)

**Goal:** make Roster / Notes / Playlists feel as compact and scannable as the new Coach Review cockpit, without redesigning Review again or touching backend schemas, My Feedback, or public match playback.

- **CSS-only density pass** scoped to `#coach-view:not(.is-review-mode)`: tighter `.options-card` padding (`0.95rem 1.1rem` desktop), heading sizes brought down to `1.05rem`, `.coach-row` padding reduced to `0.6rem 0`, list `gap` removed in favour of row borders, form rows compacted, primary CTAs / row actions snapped to a `30 px` minimum on `pointer:fine` desktop and a `44 px` minimum on `pointer:coarse`. Review's existing tighter shell rules win because they're on `.is-review-mode` (no double-override).
- **Mobile fallback** — at `pointer:coarse` / ≤ 899 px the row flips to vertical stacking so `coach-row-actions` get full-width touch targets while desktop keeps the horizontal `name | actions` layout.
- **Dominant action elevation** — `js/coaching.js` adds `mini-action-btn-primary` to "Open in Review" (Notes) and "Preview" (Playlists) so the eye lands on the play action first. Reuses the existing modifier (already used by My Feedback) — no new design tier.
- **Playlists row metadata** now shows `assigned-players` count when present, alongside the existing `note-count · visibility · pre/post-roll`.
- **Coach-scoped layout vars** at `#coach-view`: `--coach-shell-gap`, `--coach-card-padding`, `--coach-row-padding-y`, `--coach-compact-control-height`, `--coach-row-gap`. Future Coach work can tune density in one place.
- **Empty state** — `.session-empty` inside Coach gets a dashed-border "card" treatment that reads as part of the list rather than as raw text.
- **Validation**: `node --check script.js js/coaching.js js/api.js` clean; `pytest tests/` 265 passed; manual regression at 1440 / 1024 / 390 confirmed Roster add/delete/link, Notes Open-in-Review deep link, Playlist Preview focused-modal, and all Edit modals still work; Review tab unchanged.
- **Screenshots**: `docs/screenshots/coach-alignment-after/` — 12 PNGs (4 tabs × 3 widths).

---

## Coach Review UX Cockpit — Sprint 0 (audit) ✅ COMPLETE (2026-05-02)

**Goal:** establish a measured before-state for [`docs/coach-review-ui-ux-implementation-plan.md`](docs/coach-review-ui-ux-implementation-plan.md). Audit only — no source code changed (PR #56).

- **`.agent-skills/`** — portable, repo-local skill pack (8 skills + README) so any coding agent loads the redesign guardrails, search recipes, and QA gates before editing. Travels with the repo.
- **`tests/e2e/`** — Playwright scaffold scoped under its own `package.json` (no root build step). Includes a reproducible Sprint 0 baseline-capture spec.
- **`docs/coach-review-sprint-0-baseline-audit.md`** — full report with measured dimensions (chrome above video 498 px at 1440, video 65% of grid), selector / method inventory, gap analysis vs. Sprint 1–9 target, and a Sprint 1 starting recipe.
- **`docs/screenshots/sprint-0-baseline/`** — 16 PNGs capturing Coach Review at 1920 / 1440 / 1024 / 768 / 390 px plus adjacent surfaces (Roster / Notes / Playlists / Feedback / public season) at 1440 px for regression reference.

---

## Coach Review UX Cockpit — Sprint 1 + Sprint 2 ✅ COMPLETE (2026-05-02)

**Goal:** turn `/coach?tab=review` into a video-first cockpit (Sprint 1) and replace the form-row picker with a compact match/slot/time/save-note bar (Sprint 2). PR #57.

- **`is-review-mode` class** (`js/coaching.js setCoachTab`): toggled on `#coach-view` when the Review sub-tab is active. All overrides scoped to that class — Roster / Notes / Playlists keep their existing density.
- **Video-first grid** (`styles.css`): `.coach-review-grid` becomes `minmax(0, 1fr) 340px` above 1024 px (single column below). `#app-container`'s 1600 px width cap and 3 rem padding relaxed to `min(100% - 1.5rem, 2200px)` / 1.25 rem **only in Review mode**, so a 1920 px monitor uses the full width. Other surfaces unchanged. *(Superseded 2026-05-03 by the site-wide shell unification — that policy is now the global default and the Review-only override has been removed.)*
- **Inspector height matched to video player** (`js/coaching.js _syncCoachReviewSideHeight`): right-side inspector's `max-height` is JS-synced to the video wrapper's actual rendered height. Wired to window resize, ResizeObserver on `.coach-review-wrapper`, and Review-tab activation via `requestAnimationFrame`. Single themed scrollbar inside the inspector slot — no more nested scrollbars.
- **ResizeObserver on `.coach-review-wrapper`** (`js/coaching.js setupCoachCanvas`): keeps the drawing canvas aligned even when the inspector resizes the wrapper without a window resize event (the gap flagged in the Sprint 0 audit).
- **Compact picker bar** (`index.html`, `styles.css`): `.coach-review-picker` refactored from a `.form-row` block (118 px) into a horizontal toolbar (47 px) with `role="toolbar"`: Match | Slot | Time | Save Note. New `#coach-review-time` readout updates from `timeupdate` / `seeked` / `loadedmetadata`, formatted MM:SS or H:MM:SS with `tabular-nums`. New `#coach-review-save-top` calls the existing `app.saveReviewNote()`. Below 720 px the bar wraps cleanly.
- **Themed selects** (`styles.css`): scoped `.coach-review-picker select` rules so the picker selects don't fall back to native browser chrome when removed from `.form-group` (caught in review).
- **Inspector polish**: redundant `<h4>` section headers visually hidden in Review mode (still in DOM for AT). Player checklist's hardcoded `max-height: 150px` removed so chips ride the outer scroll instead of stacking a second scrollbar inside the form.
- **Dev-only static-asset import rewriter** (`server.py`): opt-in `REPLAY_DEV` env var rewrites `import './js/foo.js'` to `?v=<mtime_ns>` on serve so a soft refresh after editing any mixin reliably picks up the change. Production unaffected — without `REPLAY_DEV=1` the response is byte-for-byte the source. Two unit tests cover the rewriter and its path-traversal guard.
- **Measured deltas vs Sprint 0 baseline (1440 px):** video % of grid 65 → 74 (+9 pts); side panel 373 → 340 px; chrome above video 498 → 344 px (-154); picker 118 → 47 px (-71). At 1920 px video width 743 → 1466 px (+97%).
- **Validation**: `pytest tests/ -v --cov` 265/265 pass, coverage 65.03%. Playwright `sprint-1-after.spec.js` 11/11, `sprint-2-after.spec.js` 7/7.

Sprints 3–9 (icon-first telestrator toolbar, fast note composer, timeline rail, focus mode, keyboard shortcuts, responsive/a11y polish, QA + docs) tracked in [`docs/coach-review-ui-ux-implementation-plan.md`](docs/coach-review-ui-ux-implementation-plan.md).

---

## Coach Review UX Cockpit — Sprint 9 ✅ COMPLETE (2026-05-02)

**Goal:** lock in the UX changes and document the new Coach Review workflow. Per the plan's coding-agent prompt: "Perform the final QA pass for the Coach Review cockpit redesign. Run node syntax checks for touched JS, py_compile if Python changed, and pytest with emphasis on tests/test_coaching.py. Manually verify the full Coach Review workflow… Update the design documentation with the new layout decisions and add a concise before/after summary for the PR."

- **Static checks**: `node --check` × 4 source files green; `python3 -m py_compile` × 10 backend files green.
- **Tests**: `pytest tests/ -v --cov` → 265/265 pass, coverage 65.03 % (CI gate 60).
- **Playwright e2e**: all 8 sprint specs green (72/72 tests). The shared `_login.js` helper from PR3 keeps the suite stable across the auth.py 5-per-IP login rate limit.
- **Manual regression** — verified in browser as `coach1` (and `family1` for `/feedback` privacy): all 14 acceptance items in the plan's Sprint 9 checklist pass. Specifically: match selector loads video, slot switches, drawing canvas toggles, all 9 telestrator tools work, formation overlay accepts 3–16 anchors with collinear rejection, note save with timestamp + drawing succeeds, saved note appears in the timeline rail, click-to-seek + drawing restore work, Coach > Playlists > Preview opens the focused modal (not /match/{slug}), My Feedback unchanged + private notes do not leak, public /match/{slug} unchanged, mobile (390 px) usable, focus mode + Esc work cleanly.
- **Design report**: new `docs/design/coach-review-cockpit-report.md` consolidates all 9 sprints' design decisions, measured deltas (Sprint 0 → PR4), architecture (state machine, key files, critical-path implementation notes), acceptance evidence, and a screenshot tour pointing to all 8 capture directories.
- **Constraints respected** (full audit in the design report): no frontend build step; no backend / schema / API changes; `CreateCoachingNoteRequest` payload byte-for-byte identical; drawing schemas v1, v2, formation untouched; no native browser chrome anywhere; element IDs preserved; focus mode session-local (no localStorage).

---

## Coach Review UX Cockpit — Sprint 8 ✅ COMPLETE (2026-05-02)

**Goal:** lock in the denser desktop UI's accessibility while keeping tablet/mobile comfortable. Per the plan's coding-agent prompt: "Polish the Coach Review responsive and accessibility behavior. Use pointer-aware CSS so compact desktop controls do not make touch devices hard to use. Verify keyboard focus, aria labels, aria-pressed state on tool buttons, and visible focus rings. Test mobile, tablet, laptop, desktop, and wide monitor layouts. Confirm the drawing canvas stays aligned with the video after resizing and mode changes. Do not change backend behavior."

- **Pointer-coarse min-height (44 px)** added to every Coach Review picker bar button (`Save`, `Focus`, `Tools`, `Shortcuts`), the picker selects, the Sprint 5 timeline chips, and the Sprint 7 shortcuts-help close button. The Sprint 3 telestrator toolbar already had this; Sprint 8 extends the same rule to all post-Sprint-3 controls. Single `@media (pointer: coarse), (max-width: 899px)` block at the end of the Coach Review CSS section.
- **Visible `:focus-visible` rings** added/strengthened on `.coach-shortcuts-help button`, `.coach-review-picker-save`, `.coach-timeline-chip` so keyboard users see focus consistently across both themes. Existing tool-button rings preserved.
- **`tests/e2e/sprint-8-after.spec.js`** (NEW): 9 tests across 5 viewport widths (390 / 768 / 1024 / 1440 / 1920) covering ARIA-completeness audit (every tool button + swatch + chip has `aria-label` / `title` / `aria-pressed`), no-horizontal-page-overflow check, iPad Mini emulation tap-target verification (≥44 px on every primary control), canvas-vs-video alignment after viewport resize AND focus-mode toggle (canvas dims track video within ±2 px), and keyboard tab order through the cockpit reaches all primary controls (match → slot → save → focus → ...).
- **Dynamic aria-label** on `#coach-review-notes` (the timeline rail) implemented in PR3 review fixes — Sprint 8 verifies it stays in sync (`Notes for {matchName}` → screen readers announce the actual match name).

---

## Coach Review UX Cockpit — Sprint 7 ✅ COMPLETE (2026-05-02)

**Goal:** make the cockpit fast for power users via keyboard shortcuts. Per the plan's coding-agent prompt: "Add keyboard shortcuts scoped to Coach > Review only. Implement play/pause, small seek, larger seek, save note, tool selection, and Escape to exit focus mode or cancel drawing. Do not intercept keys while typing in inputs, textareas, selects, or contenteditable elements. Reuse existing video and drawing state methods in js/coaching.js where possible. Add a compact shortcuts help affordance in the Review UI. Make sure listeners are installed only while Review is active and cleaned up when leaving."

- **Scoped install/uninstall** (`js/coaching.js` `installCoachReviewShortcuts` / `uninstallCoachReviewShortcuts`): `setCoachTab('review')` installs the keydown listener; any other sub-tab uninstalls it. Other surfaces (Roster, Notes, Playlists, Feedback, public match, admin) are unaffected.
- **Shortcut map** (per the plan):
  - `Space` / `K` — play / pause
  - `←` / `→` — back / forward 1 s
  - `Shift+←` / `Shift+→` — back / forward 10 s
  - `J` / `L` — back / forward 5 s
  - `S` — save note (calls existing `saveReviewNote()`)
  - `A` `F` `Z` `C` `T` `D` — Arrow / Freehand / Zone / Circle / Label / Spotlight tool
  - `Esc` — exit focus mode (when in focus) or cancel formation draft
  - `?` — toggle the shortcuts help popover
- **Skip-typing guard** (`_coachShortcutShouldSkip`): no shortcut fires while focus is in `<input>`, `<textarea>`, `<select>`, or `[contenteditable]`. Modifier keys (Cmd, Ctrl, Alt) are also passed through so OS / browser shortcuts work.
- **Help popover** (`#coach-shortcuts-help` in `index.html`, `.coach-shortcuts-help` in `styles.css`): themed dialog above the cockpit. Toggled by the picker bar's `?` button or the `?` keyboard shortcut. Lists every shortcut with `<kbd>` tags. Light + dark mode variants.
- **Picker bar `Shortcuts` button** (`#coach-review-shortcuts-toggle`): icon-first variant alongside the Sprint 6 `Focus` and `Tools` buttons. Always visible, `aria-controls="coach-shortcuts-help"`.
- **Coexistence with Sprint 6 Escape handler**: the Sprint 6 focus-mode handler runs in the **capture phase** so it wins when focus mode is active. Sprint 7's bubble-phase Escape handles the formation-draft-cancel case when focus mode is OFF. No conflict; verified.
- **`tests/e2e/sprint-7-after.spec.js`** (NEW): 9 tests covering install/uninstall lifecycle (handler installs on Review, uninstalls on Roster, re-installs on return), tool-letter switches, typing-in-input doesn't trigger shortcuts, Space play/pause, Arrow / J / L seek by exact documented amounts, S triggers saveReviewNote, ? toggles help popover, Escape cancels formation draft when focus mode is off, picker bar Shortcuts button opens help. All 9 pass.

---

## Coach Review UX Cockpit — Sprint 6 ✅ COMPLETE (2026-05-02)

**Goal:** give coaches a Wide / Focus mode that prioritises the video and drawing canvas by collapsing the right inspector and reducing page chrome. Per the plan's coding-agent prompt: "Add a Wide Review or Focus Mode to Coach > Review. This mode should prioritize the video/telestrator canvas by collapsing or minimizing the right inspector panel and reducing page chrome. Add a toggle in the compact review control bar and allow Escape to exit. Preserve access to drawing tools and note saving, either through a compact floating toolbar, icon rail, or slide-over inspector. Keep this state session-local and do not affect public playback or My Feedback."

- **Focus toggle in the picker bar** (`index.html` + `styles.css`): a new icon-first `Focus` button (`#coach-review-focus-toggle`) sits at the right of the Sprint 2 top bar, visible at all times. `aria-pressed` mirrors the active state. Companion `Tools` button (`#coach-review-focus-inspector-toggle`) appears only in focus mode and opens the slide-over drawer.
- **State machine** (`js/coaching.js`):
  - `_coachFocusMode` (boolean, session-local — no persistence)
  - `_coachFocusInspectorOpen` (drawer state)
  - `_coachFocusEscapeHandler` (the active keydown listener so it can be removed cleanly)
- **Class-based layout switch** (`#coach-view.is-focus-mode`):
  - `.coach-page-head` and `.coach-subnav` hidden (chrome reduced)
  - `.coach-review-grid` collapses to a single full-width column
  - `.coach-review-side` hidden by default; mounts as a `position: fixed` slide-over (380 px, themed border + shadow) when `is-focus-drawer-open` is also set
  - `.coach-focus-backdrop` element created in `openCoachFocusInspector` so click-outside-to-close works (pseudo-elements can't fire click events)
- **Escape behavior** (capturing keydown handler, bound only while focus mode is on): drawer-open → close drawer; drawer-closed → exit focus mode. The handler is removed in `exitCoachFocusMode` so an Escape press elsewhere in the app is unaffected.
- **Lifecycle resets**: `setCoachTab('roster' | 'notes' | 'playlists')` calls `exitCoachFocusMode()` so focus mode never leaks into other Coach sub-tabs. `tearDownCoachReview()` is also belt-and-suspenders defensive. State does NOT persist across page reloads (no localStorage).
- **Canvas + inspector height re-sync**: both `enterCoachFocusMode` and `exitCoachFocusMode` re-run `_resizeCoachCanvas` and `_syncCoachReviewSideHeight` via `requestAnimationFrame` so the drawing canvas stays aligned with the resized video wrapper across the layout switch.
- **Measured deltas at 1440 px**: video wrapper width grows from **1462 → 1824 px (+362, +25 %)** when entering focus mode. Page-head, subnav, and inspector all collapse to zero pixels.
- **`tests/e2e/_login.js`** (shared helper): extracted the per-spec inline `login` / `gotoAndSettle` / `pickMatchWithMostNotes` helpers into a single module with retry-on-429 backoff. The auth.py rate limit (5 logins per IP per window) used to flake when 5 spec files ran back-to-back; the shared cache + retry chain kills that flake. All 6 spec files now `import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js'`.
- **`tests/e2e/sprint-6-after.spec.js`**: 11 tests covering toggle existence, chrome hiding + video expansion, drawer slide-over + backdrop, Escape behavior (drawer-then-exit two-press semantics), leaving Review auto-exits, click-backdrop-to-close, no localStorage persistence, and 3-width screenshot capture. All 11 pass; sprint-1 / 2 / 3 / 4 / 5 specs remain 43/43 green (54/54 total).

---

## Coach Review UX Cockpit — Sprint 5 ✅ COMPLETE (2026-05-02)

**Goal:** replace the bulky stacked notes list with a compact horizontal timeline rail so coaches can scan and jump between moments without losing the inspector to a long list of notes. Per the plan's coding-agent prompt: "Create a compact current-match notes timeline rail for Coach Review. The rail should sit under the video or directly below the review grid and render timestamp chips instead of large note rows. Each chip should show the clock time, short title, category, and player indicator if available. Clicking a chip must reuse existing seekCoachReviewNote behavior: seek to timestamp and render the saved drawing. Use horizontal scrolling for many notes. Keep accessibility and keyboard focus states."

- **`#coach-review-notes` relocated out of `.coach-review-side`** (`index.html`): the container now lives as the third child of `.coach-review-grid` with `grid-column: 1 / -1` so it spans both video and inspector columns. Existing element ID and `renderCoachReviewNotes(matchId)` entry point preserved so all callers keep working.
- **`renderCoachReviewNotes` rewritten** (`js/coaching.js`): emits horizontally-scrollable `.coach-timeline-chip` buttons instead of stacked `.coach-note-jump` rows. Each chip shows `MM:SS · player indicator · category dot · short title` with `aria-label` formatted as "Jump to MM:SS, player X, Category: Title". Notes are now sorted by timestamp so the rail reads left-to-right in match order.
- **Player indicator logic**: single linked player → `#7` (jersey number) or first-name fallback; multiple players → `+N`; no players → `Team`. The `aria-label` includes a human-readable player phrase ("player 7", "team-wide", "3 players") so screen readers don't read the bare `+3`.
- **Category dot color hints** (`styles.css`): each `.coach-timeline-chip-cat[data-cat="X"]` gets a 8 px circle in a category-specific color (sky for shape, orange for pressing, purple for transition, green for build-up, etc.). Decorative — the category name lives in the `aria-label` for AT users.
- **Active-chip state** (`js/coaching.js _setActiveCoachReviewNote`): `seekCoachReviewNote` now calls `_setActiveCoachReviewNote(noteId)` which toggles `is-active` + `aria-pressed` on the matching chip and uses `scrollIntoView({ inline: 'center' })` to nudge a far-right chip back into view. Cleared on match/slot change and on tear-down so a stale active chip never carries over.
- **Empty state** (`.coach-timeline-empty`): coach-friendly placeholder ("No notes for this match yet — save your first one above.") in a dashed border so the rail still has visual presence when empty.
- **Themed scrollbar** on the rail (`scrollbar-width: thin` + `::-webkit-scrollbar` rules) — never expose native chrome inside styled UI. Light-mode variant included.
- **Measured deltas vs. Sprint 4 (1440 px desktop)**: stacked notes list (height grew with note count, ~120 px for 5 notes, ~270 px for 10) → **single 50 px horizontal rail** that doesn't grow vertically regardless of note count. Frees the inspector slot entirely for the telestrator + composer.
- **`tests/e2e/sprint-5-after.spec.js`**: 9 tests covering layout assertions (rail not in inspector, spans full grid width, lives below video AND below inspector), chip composition (time + player + category + title + ARIA), click → active state + scroll-into-view, slot-change clears active state, empty-state rendering, and 4-width screenshot capture. All 9 pass; sprint-1 / 2 / 3 / 4 specs remain 35/35 green (no regressions).
- **No backend changes**, no payload schema changes, no role-gating changes.

---

## Coach Review UX Cockpit — Sprint 4 ✅ COMPLETE (2026-05-02)

**Goal:** let coaches save useful notes quickly without filling out a full form every time. Compact composer (title + player chips + category + Save at MM:SS) with visibility / body / tags collapsed behind a "More details" disclosure.

- **Compact default composer** (`js/coaching.js renderCoachReviewForm`): five visible fields by default — title input, player chip strip, category select, Save-at-MM:SS button, "More details" disclosure. The plan's UX target sequence preserved.
- **Live timestamp on the Save button** (`js/coaching.js _renderCoachReviewTime`): the form's Save button now reads `Save at MM:SS` and updates from the same `timeupdate` listener that drives the top-bar readout. Coaches can see the exact timestamp the note will land on without glancing up.
- **`<details>` disclosure for advanced fields** (`styles.css .coach-review-advanced`): visibility, long-form notes (`coach-review-body`), and tags collapse into a `<details>` element. Default: closed. Native browser triangle hidden in both Firefox and WebKit; replaced with a CSS chevron that rotates on open. CSS gates the body via `.coach-review-advanced[open] > .coach-review-advanced-body { display: grid }` so the browser's default `display:none` for closed `<details>` children is preserved (without the gate, my own `display: grid` rule overrode it and the advanced fields rendered while collapsed — caught in browser verify).
- **Sticky reset behavior** (`js/coaching.js saveReviewNote`): only title, body, and tags clear after save. Category, visibility, and selected players stay sticky so a coach reviewing one player can save several notes in a row without re-tagging. Per the plan: "category/type may remain sticky for fast repeated note creation; selected players should optionally remain sticky while reviewing one player."
- **No backend changes**. Per the plan task 3 ("If not, do not add backend changes in this sprint"): the existing `category` enum is sufficient; an additional `note_type` field would require a `models.py` + DB migration. Deferred.
- **All existing element IDs preserved** (`#coach-review-title`, `#coach-review-body`, `#coach-review-category`, `#coach-review-visibility`, `#coach-review-players`, `#coach-review-tags`) so `saveReviewNote()` and the existing `CreateCoachingNoteRequest` payload chain need no changes. The new form button (`#coach-review-save-form`) calls the same `app.saveReviewNote()` handler as the top-bar Save Note button.
- **`tests/e2e/sprint-4-after.spec.js`**: 8 tests covering collapsed-state assertions, expanded-state assertions, Save-at-MM:SS timestamp tracking, save-handler binding, and 4-width screenshot capture. All 8 pass; sprint-1/2/3 specs remain 27/27 green (no regressions).

---

## Coach Review UX Cockpit — Sprint 3 ✅ COMPLETE (2026-05-02)

**Goal:** shrink the telestrator controls so they do not crowd the video canvas. Icon-first desktop toolbar with pointer-aware sizing — compact at `pointer: fine`, ≥44 px tap target at `pointer: coarse`.

- **Icon-first tool buttons** (`js/coaching.js renderCoachTelestratorToolbar`): nine drawing tools (`select`, `freehand`, `arrow`, `circle`, `zone`, `label`, `spotlight`, `dim`, `formation`) now render as inline-SVG icon buttons. No font dependency; the SVG `<path>` data is embedded in the render template alongside its tool id, label, and tooltip. Each button uses `currentColor` so the icon picks up the button's foreground in both themes. `data-coach-tool` values, the `setCoachDrawingTool()` handler, and the drawing payload are unchanged.
- **Grouped toolbar sections** (`role="toolbar"` + `role="group"` per section): drawing tools in a 5-column grid; color swatches + width slider in a wrap row; canvas actions (Canvas On/Off, Undo, Delete, Clear) in their own row. Clear keeps a text label and is given a soft destructive variant (`.btn-danger-soft`) — per the plan: "Keep text labels for destructive actions like Clear if needed."
- **Accessibility**: every icon button carries `title`, `aria-label`, and `aria-pressed`. `setCoachDrawingTool`, `setCoachDrawingColor`, and `updateCoachCanvasToggleLabel` now keep `aria-pressed` in sync with the visual `.active` class, so screen readers announce toggle changes without re-rendering. Color swatches expose human-readable names (`Color: Sky blue`, `Color: Orange`, …). Width slider has `aria-label="Stroke width"`.
- **Pointer-aware sizing** (`styles.css .coach-tool-btn`): default state is touch-first with `min-height: 44px` and visible icon + label. `@media (pointer: fine) and (min-width: 900px)` collapses each button to a 34 × 34 px square with the text label visually hidden via the standard sr-only clip. `@media (pointer: coarse)` and narrow viewports keep the larger target.
- **Visible focus** (`:focus-visible`): every tool button has an accent-colored 2 px box-shadow ring on keyboard focus.
- **Measured deltas vs. Sprint 2 baseline (1440 px desktop):**
  - Tool button size: text rectangles (~32 × 84 px each) → **34 × 34 px** square icons (-58% width per button)
  - Tool grid height: ~136 px → **74 px** (-62 px)
  - Total telestrator section: ~277 px → **232 px** (-45 px)
- **Pointer-coarse verification**: Playwright iPad Mini emulation profile yields 46 px tool buttons (above the 44 px minimum).
- **`tests/e2e/sprint-3-after.spec.js`**: 9 tests covering 5-width capture, ARIA assertions, dynamic `aria-pressed` sync, color swatch state, canvas-toggle text + `aria-pressed`, and the iPad Mini tap-target check. All 9 pass; sprint-1-after / sprint-2-after specs remain 18/18 green (no regressions).

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

The original C1–C7 outline (coach workspace, roster + player-user links, timestamped notes, drawing overlays, review playlists, My Feedback, assignment/review tracking, access rules, test plan) is now **shipped** — see the completed entries above:

- `Coaching Platform MVP ✅ COMPLETE (2026-05-01)` — C1, C2, C3, C6, C7, access rules, test plan
- `Telestrator + Review Playlist Playback ✅ COMPLETE (2026-05-01)` — C4 + C5 with versioned drawing objects, pre/post-roll playback
- `Coaching Telestrator — Multi-Player Formation Overlay (Phase 1) ✅ COMPLETE (2026-05-02)` — formation tool extension to C4

**Forward-looking coaching work** has moved into two dedicated planning docs (kept separate from this roadmap so each can iterate without churning the milestone log):

- [`docs/coaching-analysis-feature-roadmap.md`](docs/coaching-analysis-feature-roadmap.md) — feature backlog (Phases 1–11): structured note quality, review templates, per-note thumbnails, first-class clip builder, player development profiles, action items, match summaries, engagement dashboards, analytics, AI-assisted workflow, CV-assisted clip discovery.
- [`docs/coach-review-ui-ux-implementation-plan.md`](docs/coach-review-ui-ux-implementation-plan.md) — Coach > Review UX cockpit redesign in 10 sprints (S0–S9): video-first layout, compact match/slot bar, icon-first telestrator toolbar, fast note composer, timeline rail, focus mode, keyboard shortcuts, responsive/a11y polish, QA + docs.

The Telestrator follow-on phases (connectors, animated keyframes v3 schema, server-side player tracking) remain in [Coaching Telestrator — Future Phases](#coaching-telestrator--future-phases-designed-not-shipped) above because they extend a shipped object schema rather than the broader feature/UX backlog.
