# Replay Agent Guide

This repository is a small FastAPI + vanilla JS application for uploading, processing, and replaying soccer match videos.

## Stack

- Backend: `server.py` (route registration + entrypoint) with modular services
- Frontend: `index.html`, `script.js`, `styles.css`
- Storage: SQLite in `replay.db` plus filesystem media files
- Media pipeline: `media.py` wrapping `ffmpeg` and `ffprobe`
- Testing: `pytest` + `pytest-asyncio` + `httpx` (see `tests/`)
- CI: GitHub Actions (`.github/workflows/ci.yml`)
- Runtime: direct Python or Docker Compose

## Key Files

- `server.py`: API routes, SPA serving, async lock wrappers, entrypoint
- `db.py`: SQLite connection pool, schema migrations, match CRUD helpers
- `auth.py`: token management, login rate limiting, origin validation
- `settings.py`: app settings persistence, rendering helpers
- `uploads.py`: upload session lifecycle (create, chunk, complete, cleanup)
- `media.py`: ffmpeg/ffprobe probing, transcoding (GPU/CPU), HLS variant generation
- `models.py`: Pydantic v2 request models for login, match CRUD, and upload sessions
- `log.py`: structured JSON logging (configurable via `LOG_FORMAT` env var)
- `script.js`: SPA state, uploads, playback, Cast/AirPlay, URL-based history navigation
- `index.html`: single-page app shell
- `styles.css`: full UI styling
- `tests/`: pytest test suite (auth, matches, uploads, settings)
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
- For SPA navigation, prefer the shared history helpers in `script.js`. Match URLs use slug-based paths (`/match/{slug}`).
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
- When adding or modifying API endpoints, add or update Pydantic models in `models.py` and add corresponding tests in `tests/`.
- Login is rate-limited (5 attempts/60s per IP). Token cleanup sweeps run automatically.
- Backend logic is organized into focused modules (`db.py`, `auth.py`, `settings.py`, `uploads.py`, `media.py`). Keep `server.py` as the route registration layer; add business logic to the appropriate module.
- The `MATCHES_LOCK` is an `asyncio.Lock` — all callers that hold it must be async.
