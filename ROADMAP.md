# Replay — Enhancement Roadmap

Code review and prioritized improvement plan for the Replay match video platform.

---

## Code Review Summary

The codebase is a well-structured single-file FastAPI backend (`server.py`, 1768 lines) with a no-build-step vanilla JS SPA (`script.js`, ~2600 lines). Core functionality — chunked uploads, GPU/CPU transcoding, HLS streaming, Cast/AirPlay — is solid. The areas below represent the highest-impact improvements organized by priority tier.

---

## Tier 1 — Security & Reliability (High Priority)

### 1.1 Rate-limit login endpoint
**File:** `server.py:1077-1087`
The `/api/login` endpoint has no rate limiting. An attacker can brute-force credentials without throttling. Add per-IP rate limiting (e.g. 5 attempts per minute) or exponential backoff after failed attempts.

### 1.2 Token cleanup on accumulation
**File:** `server.py:390`
`_active_tokens` is an in-memory dict that only removes tokens on explicit logout or individual TTL expiry check. Tokens are never garbage-collected in bulk — a long-running server accumulates stale entries. Add a periodic sweep or cap the dict size.

### 1.3 Input validation on match updates
**File:** `server.py:1201-1218`
`PUT /api/matches/{match_id}` blindly accepts any value for updatable fields (including `score_home`, `score_away`). Non-integer scores or excessively long strings are persisted without validation. Add type checking and length limits.

### 1.4 CSRF / Origin validation
No CSRF protection exists. Since auth is Bearer-token based (not cookie-based), this is partially mitigated, but the login endpoint itself could benefit from origin validation to prevent credential harvesting from rogue pages.

### 1.5 Disk space check before transcoding
**File:** `server.py:857-933`
`_transcode_video` does not verify free disk space before starting ffmpeg. Transcoding a large file to multiple HLS variants can consume 3-5x the source size. The disk check in `_ensure_disk_space` only runs at upload session creation time — by the time transcoding starts, disk may be full.

---

## Tier 2 — Performance & Scalability (Medium-High Priority)

### 2.1 Reduce redundant DB reads in hot paths
**Files:** `server.py:1519-1542`, `server.py:1584-1608`
`stream_video`, `stream_hls_master`, and `download_video` all call `_load_matches()` which reads and deserializes every match from SQLite on every request. For video streaming, this is called per range request. Replace with a single-match lookup: `SELECT * FROM matches WHERE id = ?`.

### 2.2 Connection pooling for SQLite
**File:** `server.py` (`_db_connect`)
Each database operation opens and closes a fresh SQLite connection. While SQLite handles this reasonably well with WAL mode, a simple connection pool or cached connection per-thread would reduce overhead on high-traffic deployments.

### 2.3 Avoid synchronous threading lock in async context
**File:** `server.py:50`
`MATCHES_LOCK = Lock()` is a threading lock used inside async endpoint handlers. This blocks the event loop while held. Replace with `asyncio.Lock()` or restructure to keep the lock hold time minimal. The current pattern risks starving other coroutines during heavy write operations.

### 2.4 HLS variant generation parallelism
**File:** `server.py:779-814`
HLS variants (1080p, 720p, 480p) are generated sequentially within `_build_hls_assets`. These are independent ffmpeg processes and could run concurrently (respecting the transcode semaphore). This would cut HLS generation time to ~1/3 for multi-variant content.

### 2.5 Startup backfill blocks readiness
**File:** `server.py:1579-1581`
`startup_backfill_hls` fires on server start and may transcode many videos. While it runs as a background task, it competes for the transcode semaphore, potentially delaying new uploads. Consider adding a startup delay or lower-priority queue for backfill work.

---

## Tier 3 — User Experience Improvements (Medium Priority)

### 3.1 Transcode progress reporting
Currently the frontend polls match status and sees only `transcoding` or `ready`. There is no progress percentage. ffmpeg outputs frame progress to stderr — capture and expose it (e.g. via an SSE endpoint or a progress field on the match) so users see estimated completion.

### 3.2 Match search and pagination
**File:** `server.py:1163-1165`
`GET /api/matches` returns all matches with no pagination or filtering. As the match count grows, this becomes slow and wastes bandwidth. Add `?page=&limit=` query params and optional `?q=` text search across team names.

### 3.3 Shareable match URLs
The SPA uses `pushState` for navigation but match URLs are not directly accessible (the server only serves `/`). Add a catch-all route that serves `index.html` for `/match/{id}` paths so users can share direct links to specific matches.

### 3.4 Thumbnail generation
Generate a thumbnail image (e.g. frame at 10% duration) during transcoding for each match. Display these on match cards in the season view instead of relying solely on team logos. This would make the match grid more visually engaging.

### 3.5 Multi-user support
The app currently supports a single admin account. For team use, consider adding:
- Read-only user accounts for players/parents
- Role-based access (admin vs. uploader vs. viewer)
- Per-match access control for private/public content

---

## Tier 4 — Code Quality & Maintainability (Medium Priority)

### 4.1 Extract media pipeline to separate module
**File:** `server.py:683-933`
The transcoding, probing, and HLS generation logic (~250 lines) is self-contained and could be extracted to a `media.py` module. This improves testability and keeps `server.py` focused on HTTP concerns.

### 4.2 Add request/response models (Pydantic)
FastAPI supports Pydantic models for request validation and response serialization, but the app uses raw `request.json()` everywhere. Adding models would provide automatic validation, OpenAPI documentation, and type safety.

### 4.3 Structured logging
**File:** `server.py:27-28`
The app uses basic `logging.basicConfig` with string interpolation. Switching to structured logging (JSON format) would improve log parsing in production and make it easier to search/filter by match_id, slot, session_id, etc.

### 4.4 Test coverage
There are no tests. Key areas to cover:
- Auth flow (login, token expiry, invalid credentials)
- Match CRUD operations
- Upload session lifecycle (create, chunk, complete, resume, cancel)
- Range request handling
- HLS playlist generation
- Codec probing and transcode strategy selection

### 4.5 Frontend modularization
**File:** `script.js` (~2600 lines)
The entire frontend is a single file with functions in a flat namespace. Consider splitting into logical modules (e.g. `player.js`, `upload.js`, `cast.js`, `settings.js`) loaded via `<script>` tags or a lightweight module approach (still no build step, per project constraints).

---

## Tier 5 — Feature Enhancements (Lower Priority)

### 5.1 Video clipping / highlights
Allow admins to mark time ranges within a match video as "highlights" or "clips." Generate sub-clips on the backend and display them alongside the full match in the game view.

### 5.2 Match tagging and categories
Add tags/categories to matches (e.g. "Tournament," "League," "Friendly") with filtering in the season view. This extends the existing Home/Away filter system.

### 5.3 Bulk operations
Support bulk delete, bulk re-transcode, and bulk HLS backfill from the admin panel. Currently these must be done one match at a time.

### 5.4 Webhook / notification support
Send a webhook or push notification when a transcode completes. Useful for automated workflows or alerting admins that a video is ready for review.

### 5.5 S3 / object storage backend
Replace filesystem storage with an optional S3-compatible backend for deployments where local disk is limited or where CDN integration is desired. The current `VIDEOS_DIR` abstraction makes this a moderate-effort change.

### 5.6 Database backup and export
Add an admin endpoint to export the SQLite database and match metadata as a downloadable archive. Useful for migration, disaster recovery, or switching to a different storage backend.

---

## Quick Wins (Can ship independently)

| Item | Effort | Impact |
|------|--------|--------|
| Single-match DB lookup for streaming endpoints | ~30 min | High — reduces per-request DB load |
| Token garbage collection sweep | ~20 min | Medium — prevents memory leak |
| Login rate limiting | ~45 min | High — closes brute-force vector |
| Pydantic models for match CRUD | ~1 hr | Medium — better validation + docs |
| Disk space check before transcode | ~20 min | Medium — prevents failed transcodes |
| Catch-all route for shareable URLs | ~15 min | Medium — better link sharing |
