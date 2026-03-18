# Replay Agent Guide

This repository is a small FastAPI + vanilla JS application for uploading, processing, and replaying soccer match videos.

## Stack

- Backend: `server.py` using FastAPI
- Frontend: `index.html`, `script.js`, `styles.css`
- Storage: SQLite in `replay.db` plus filesystem media files
- Media pipeline: `ffmpeg` and `ffprobe`
- Runtime: direct Python or Docker Compose

## Key Files

- `server.py`: API, auth, uploads, HLS generation, static file serving
- `media.py`: ffmpeg/ffprobe probing, transcoding (GPU/CPU), HLS variant generation
- `script.js`: SPA state, uploads, playback, Cast/AirPlay, browser history navigation
- `index.html`: single-page app shell
- `styles.css`: full UI styling
- `docker-compose.yml`: local container runtime
- `.env.example`: deployment configuration template

## Common Commands

```bash
pip install -r requirements.txt
python server.py
python3 -m py_compile server.py && python3 -m py_compile media.py
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

## Project Constraints

- Keep the app as a no-build-step SPA.
- Preserve the existing FastAPI + vanilla JS architecture unless a task explicitly calls for larger rework.
- Prefer minimal, focused edits.
- Do not commit secrets or local-only files such as `.env.local`.
- Large uploads, resumable chunking, HLS playback, Cast, and AirPlay are already implemented; avoid regressing those flows.

## Validation

After backend changes, run:

```bash
python3 -m py_compile server.py
```

After frontend changes, sanity-check:

- season view rendering
- match detail navigation
- upload form behavior
- replay playback
- Cast/AirPlay controls if relevant

## Editing Guidance

- Keep API shapes stable unless the task requires a breaking change.
- Reuse existing helper functions instead of duplicating upload, playback, or view-toggle logic.
- For SPA navigation, prefer the shared history helpers in `script.js`.
- For caching behavior, be careful with `index.html`, `/static/*`, and Cloudflare-facing asset URLs.
