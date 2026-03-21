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
- `settings.py`: app settings persistence, rendering helpers
- `uploads.py`: upload session lifecycle (create, chunk, complete, cleanup)
- `media.py`: ffmpeg/ffprobe probing, transcoding (GPU/CPU) with real-time progress tracking, HLS variant generation, thumbnail extraction
- `models.py`: Pydantic v2 request models for login, match CRUD, upload sessions, and user management
- `log.py`: structured JSON logging (configurable via `LOG_FORMAT` env var)
- `script.js`: ES module entry point — state, init, navigation, event binding, mixin assembly
- `js/utils.js`: pure utility functions (esc, formatDate, statusLabel, etc.)
- `js/api.js`: auth, data loading, settings, transcode polling
- `js/player.js`: AirPlay, Chromecast, HLS playback, position/speed memory, keyboard shortcuts, match navigation
- `js/uploads.js`: chunked upload sessions, resume logic
- `js/views.js`: season view, game view, match form, settings form, admin panel
- `js/ui.js`: toast notifications (success/error/info) and button loading state helpers
- `index.html`: single-page app shell (loads `script.js` as `type="module"`)
- `styles.css`: full UI styling
- `tests/`: pytest test suite (auth, matches, uploads, settings, users, admin)
- `docker-compose.yml`: local container runtime
- `.env.example`: deployment configuration template

## Common Commands

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for testing
python server.py
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py
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
- `MAX_UPLOAD_SIZE_BYTES`
- `UPLOAD_CHUNK_SIZE_BYTES`
- `TRANSCODE_CONCURRENCY`
- `VIDEO_STREAM_CHUNK_BYTES`
- `HLS_SEGMENT_DURATION`
- `ALLOWED_ORIGINS` — optional comma-separated hostnames for login origin validation
- `LOG_FORMAT` — `json` (default) or `text` for human-readable logs
- `LOG_LEVEL` — `INFO` (default), `DEBUG`, `WARNING`, etc.

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
- For SPA navigation, prefer the shared history helpers in `script.js`. Match URLs use slug-based paths (`/match/{slug}`).
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
- When adding or modifying API endpoints, add or update Pydantic models in `models.py` and add corresponding tests in `tests/`.
- Login is rate-limited (5 attempts/60s per IP). Token cleanup sweeps run automatically.
- Three user roles: `admin` (full access), `uploader` (match CRUD + uploads), `viewer` (read-only). Use `_auth.require_role(request, "admin", "uploader")` for role checks. The env-var admin (`ADMIN_USER`/`ADMIN_PASS`) is always a superadmin.
- Backend logic is organized into focused modules (`db.py`, `auth.py`, `settings.py`, `uploads.py`, `media.py`). Keep `server.py` as the route registration layer; add business logic to the appropriate module.
- The `MATCHES_LOCK` is an `asyncio.Lock` — all callers that hold it must be async.
- For UI feedback, use the toast system in `js/ui.js` (`showSuccess`, `showError`, `showInfo`) instead of `alert()`. Use `btnLoading()` for button loading states.
- Playback state (position, speed) is persisted in localStorage by `js/player.js`. Keyboard shortcuts are YouTube-style and registered globally in `initKeyboardShortcuts()`. Thumbnails are auto-generated during transcoding and backfilled at startup for existing videos.
- Video errors are persisted in the `video_errors` table. When setting status to `"error"`, pass `error_info={"error_code": ..., "reason": ..., "details": ...}` to `_set_video_status()`.
- Admin recovery endpoints: retry transcode (`POST .../retry`), regenerate HLS (`POST .../regenerate-hls`), verify assets (`GET .../verify`), export DB (`POST /api/admin/export-database`).
- **After every code change**, update the relevant markdown files (`ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`) to reflect what changed — new files, completed roadmap items, new conventions, updated guidance. Keep these files as the living source of truth.
