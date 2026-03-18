# Replay — Enhancement Roadmap

Improvement plan for the Replay match video platform, organized as sequential milestones.

> This document supersedes `docs/copilot_roadmap.md`, which has been removed.

---

## Code Review Summary

The codebase is a well-structured single-file FastAPI backend (`server.py`, 1768 lines) with a no-build-step vanilla JS SPA (`script.js`, ~2600 lines). Core functionality — chunked uploads, GPU/CPU transcoding, HLS streaming, Cast/AirPlay — is solid. The milestones below represent the highest-impact improvements in recommended execution order.

---

## Milestone 1 — Safety Net

**Goal:** close security gaps and add test coverage so the rest of the roadmap can ship safely.

### Security

**1.1 Rate-limit login endpoint**
**File:** `server.py:1077-1087`
The `/api/login` endpoint has no rate limiting. An attacker can brute-force credentials without throttling. Add per-IP rate limiting (e.g. 5 attempts per minute) or exponential backoff after failed attempts.

**1.2 Token cleanup on accumulation**
**File:** `server.py:390`
`_active_tokens` is an in-memory dict that only removes tokens on explicit logout or individual TTL expiry check. Tokens are never garbage-collected in bulk — a long-running server accumulates stale entries. Add a periodic sweep or cap the dict size.

**1.3 Input validation on match updates**
**File:** `server.py:1201-1218`
`PUT /api/matches/{match_id}` blindly accepts any value for updatable fields (including `score_home`, `score_away`). Non-integer scores or excessively long strings are persisted without validation. Add type checking and length limits.

**1.4 CSRF / Origin validation**
No CSRF protection exists. Since auth is Bearer-token based (not cookie-based), this is partially mitigated, but the login endpoint itself could benefit from origin validation to prevent credential harvesting from rogue pages.

**1.5 Disk space check before transcoding**
**File:** `server.py:857-933`
`_transcode_video` does not verify free disk space before starting ffmpeg. Transcoding a large file to multiple HLS variants can consume 3-5x the source size. The disk check in `_ensure_disk_space` only runs at upload session creation time — by the time transcoding starts, disk may be full.

### Testing & CI

**1.6 Add test suite**
There are no tests. Key areas to cover:
- Auth flow (login, token expiry, invalid credentials)
- Match CRUD operations
- Upload session lifecycle (create, chunk, complete, resume, cancel)
- Range request handling
- HLS playlist generation
- Codec probing and transcode strategy selection

Use temp data-dir fixtures so tests run without touching real data.

**1.7 Add CI workflow**
GitHub Actions workflow to run on every push/PR:
- `python3 -m py_compile server.py`
- Test execution
- Optional Docker build smoke check

**1.8 Add request/response models (Pydantic)**
FastAPI supports Pydantic models for request validation and response serialization, but the app uses raw `request.json()` everywhere. Adding models would provide automatic validation, OpenAPI documentation, and type safety.

### Exit criteria
- Login brute-force is throttled
- Core routes have automated test coverage
- CI passes on clean checkout
- Invalid payloads fail predictably

---

## Milestone 2 — Performance & Backend Structure

**Goal:** fix performance issues in hot paths and make `server.py` easier to change.

### Performance

**2.1 Reduce redundant DB reads in hot paths**
**Files:** `server.py:1519-1542`, `server.py:1584-1608`
`stream_video`, `stream_hls_master`, and `download_video` all call `_load_matches()` which reads and deserializes every match from SQLite on every request. For video streaming, this is called per range request. Replace with a single-match lookup: `SELECT * FROM matches WHERE id = ?`.

**2.2 Connection pooling for SQLite**
**File:** `server.py` (`_db_connect`)
Each database operation opens and closes a fresh SQLite connection. While SQLite handles this reasonably well with WAL mode, a simple connection pool or cached connection per-thread would reduce overhead on high-traffic deployments.

**2.3 Avoid synchronous threading lock in async context**
**File:** `server.py:50`
`MATCHES_LOCK = Lock()` is a threading lock used inside async endpoint handlers. This blocks the event loop while held. Replace with `asyncio.Lock()` or restructure to keep the lock hold time minimal. The current pattern risks starving other coroutines during heavy write operations.

**2.4 HLS variant generation parallelism**
**File:** `server.py:779-814`
HLS variants (1080p, 720p, 480p) are generated sequentially within `_build_hls_assets`. These are independent ffmpeg processes and could run concurrently (respecting the transcode semaphore). This would cut HLS generation time to ~1/3 for multi-variant content.

**2.5 Startup backfill blocks readiness**
**File:** `server.py:1579-1581`
`startup_backfill_hls` fires on server start and may transcode many videos. While it runs as a background task, it competes for the transcode semaphore, potentially delaying new uploads. Consider adding a startup delay or lower-priority queue for backfill work.

### Backend modularization

**2.6 Extract media pipeline to separate module**
**File:** `server.py:683-933`
The transcoding, probing, and HLS generation logic (~250 lines) is self-contained and could be extracted to a `media.py` module. This improves testability and keeps `server.py` focused on HTTP concerns.

**2.7 Extract service modules**
Beyond media, extract standalone modules for:
- Auth (token management, login logic)
- DB access (connection helpers, query wrappers)
- Upload session management
- Settings persistence

Keep `server.py` as the entrypoint and route registration layer.

**2.8 Structured logging**
**File:** `server.py:27-28`
The app uses basic `logging.basicConfig` with string interpolation. Switching to structured logging (JSON format) would improve log parsing in production and make it easier to search/filter by match_id, slot, session_id, etc.

**2.9 Database migration mechanism**
Startup schema creation is ad hoc SQL. Introduce a lightweight migration/versioning mechanism so schema changes are tracked and repeatable.

### Exit criteria
- Streaming endpoints no longer load all matches per request
- `server.py` is substantially smaller with logic in focused modules
- Schema changes go through versioned migrations

---

## Milestone 3 — UX & Frontend Structure

**Goal:** make the frontend easier to extend and improve the day-to-day user experience.

### Frontend modularization

**3.1 Split `script.js` into logical modules**
**File:** `script.js` (~2600 lines)
The entire frontend is a single file with functions in a flat namespace. Split into modules (e.g. API client, player, uploads, season view, settings) loaded via `<script>` tags or lightweight ES modules — still no build step.

**3.2 Centralize UI feedback**
Consistent loading states, success/error banners, and clearer processing/retry messaging across all views.

### User experience

**3.3 Transcode progress reporting**
Currently the frontend polls match status and sees only `transcoding` or `ready`. There is no progress percentage. ffmpeg outputs frame progress to stderr — capture and expose it (e.g. via an SSE endpoint or a progress field on the match) so users see estimated completion.

**3.4 Match search and pagination**
**File:** `server.py:1163-1165`
`GET /api/matches` returns all matches with no pagination or filtering. As the match count grows, this becomes slow and wastes bandwidth. Add `?page=&limit=` query params and optional `?q=` text search across team names.

**3.5 Thumbnail generation**
Generate a thumbnail image (e.g. frame at 10% duration) during transcoding for each match. Display these on match cards in the season view instead of relying solely on team logos.

**3.6 Playback quality-of-life**
- Remember playback position
- Remember speed preference
- Keyboard shortcuts for common actions
- Next/previous match navigation

**3.7 Multi-user support**
The app currently supports a single admin account. For team use, consider adding:
- Read-only user accounts for players/parents
- Role-based access (admin vs. uploader vs. viewer)
- Per-match access control for private/public content

### Exit criteria
- Major frontend features are separated by responsibility
- Upload and playback failures are surfaced clearly
- Finding a past match is materially easier

---

## Milestone 4 — Media Hardening, Features & Ops

**Goal:** make the media pipeline recoverable, add advanced features, and harden for production.

### Media pipeline hardening

**4.1 Formalize processing state machine**
Define explicit states: created → uploading → uploaded → queued → processing → ready / failed. Persist failure reasons so admins can diagnose without inspecting files.

**4.2 Retry and recovery actions**
- Retry failed transcode from the UI or API
- Regenerate HLS for an existing MP4
- Clean orphaned partial uploads
- Verify asset integrity per match

**4.3 Expand admin diagnostics**
Surface active jobs, stale sessions, failed items, missing HLS assets, and disk usage summaries in the admin panel.

### Feature enhancements

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

**4.9 Database backup and export**
Add an admin endpoint to export the SQLite database and match metadata as a downloadable archive. Useful for migration, disaster recovery, or switching to a different storage backend.

**4.10 Deployment documentation**
- CPU-only vs GPU deployment paths
- Upgrade/migration guide
- Troubleshooting guide for uploads/transcodes/HLS
- Backup and restore procedures

### Exit criteria
- Failed processing can be retried from the UI
- Media state is diagnosable without inspecting files manually
- Maintenance tasks are documented

---

## Dependencies

- **M1 before M2:** tests and CI must exist before major refactors.
- **M2 before M4:** backend modularization before pipeline hardening.
- **M1 before M3:** validation models and test coverage before frontend expansion.

---

## Quick Wins (can ship independently)

| Item | Effort | Impact |
|------|--------|--------|
| Single-match DB lookup for streaming endpoints | ~30 min | High — reduces per-request DB load |
| Token garbage collection sweep | ~20 min | Medium — prevents memory leak |
| Login rate limiting | ~45 min | High — closes brute-force vector |
| Pydantic models for match CRUD | ~1 hr | Medium — better validation + docs |
| Disk space check before transcode | ~20 min | Medium — prevents failed transcodes |
