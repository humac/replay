# Discovery Notes (internal)

> Working document used to drive the user-guide and admin-guide deliverables. Not part of the published docs.

## App at a glance

**Replay** is a self-hosted soccer match video archive and live-stream viewer. Users browse a season grid, open a match, and play recorded full matches or first/second-half slots; admins upload new matches, transcode them to HLS, and (optionally) broadcast a live RTMP feed that viewers consume as LL-HLS.

## Stack

- Backend: Python 3.11 + FastAPI on `:8091`, plain SQLite via `db.py` (no ORM)
- Frontend: vanilla HTML/CSS/JS, no build step. SPA shell at `index.html`, ES-module mixins under `js/` assembled by `script.js`
- Media: ffmpeg/ffprobe via `media.py` (HLS variants + thumbnails)
- Live: MediaMTX sidecar (RTMP → LL-HLS) — only available when running the docker-compose stack
- Reverse proxy in production: Caddy serves VOD HLS segments directly via sendfile; everything else proxies to the FastAPI app

## Roles

| Role | Source | Permissions |
|---|---|---|
| Anonymous | — | View season grid, watch a match, watch live |
| Viewer | DB user with `role='viewer'` | Login only; effectively read-only (no admin nav) |
| Uploader | DB user with `role='uploader'` | Create/edit/delete matches, upload videos. Restricted to `/admin/matches` |
| Admin | DB user with `role='admin'` | Full access to `/admin/{overview,matches,live,performance,users,settings}` |
| Env-var superadmin | `ADMIN_USER` / `ADMIN_PASS` env vars | Bypasses the DB user table; always grants `admin`. Cannot be disabled from the UI. |

## Page surface

Public: `/`, `/match/{slug}`, `/match/{slug}/{slot}`, `/live`

Admin: `/admin/overview`, `/admin/matches`, `/admin/live`, `/admin/performance`, `/admin/users`, `/admin/settings`

Legacy redirects: `/admin/streams` → `/admin/live`, `/admin/system` → `/admin/performance`.

## Documentation strategy

- **Seed**: direct SQLite via `db.py` and `auth.hash_password` — faster than HTTP, no auth handshake, no resumable-upload complexity. Idempotent (clear matches + seeded users, then re-insert). Hard-fails if it detects existing matches with non-empty `videos_json` to avoid clobbering a real archive.
- **Data dir**: isolated `/tmp/replay-docs-data` so the user's real `~/replay-data` is never touched.
- **Logos**: 12 placeholder SVGs (colored circle with two-letter initials), copied into each match's video dir as `home_logo.svg` / `away_logo.svg`.
- **Screenshots**: headless Playwright via the `agent-browser` skill, viewport 1440×900 (mobile shot at 390×844).
- **Live coverage**: offline-state only. The admin guide explains the docker-compose path for full live setup but doesn't screenshot it.

## Out of scope for these guides

- Resumable upload internals (described in prose only — we don't seed real video files)
- Live RTMP ingest (no MediaMTX bring-up)
- Transcoding (no real videos seeded)
- Document/permission sharing (the app has none)
- Developer-facing API documentation (separate concern from functional docs)

## Feature inventory → guide mapping

| Feature | User guide | Admin guide | Coach guide |
|---|---|---|---|
| Browse season grid + filter | ✓ | — | — |
| Open match / play video / score reveal | ✓ | — | — |
| Watch live | ✓ | partial (offline state + setup) | — |
| Login | ✓ (viewer) | ✓ (admin) | ✓ (coach) |
| Mobile experience | ✓ | — | ✓ (`/feedback` mobile) |
| Add / edit / delete match | — | ✓ | — |
| Upload video (described, not walked) | — | ✓ | — |
| Live config + key rotation | — | ✓ | — |
| Performance tuning + diagnostics | — | ✓ | — |
| User management | — | ✓ | cross-link only |
| Branding / labels / settings | — | ✓ | — |
| Backups / DB export | — | ✓ | — |
| Coach roster + family links | — | ✓ (data model) | ✓ (UI walkthrough) |
| Coaching notes (CRUD, visibility) | partial (player view) | ✓ (data model) | ✓ |
| Telestrator (8 tools) | — | summary | ✓ |
| Multi-player formation overlay | — | summary | ✓ (its own subsection) |
| Review tab + deep-link from match page | — | — | ✓ |
| Review playlists (authoring) | — | summary | ✓ |
| `/feedback` (player & family viewing) | ✓ (overview) | summary | ✓ (deep dive) |
| Focused feedback player modal | — | — | ✓ |

## Known limitations called out in the guides

- Live page renders an "offline" message under bare `python server.py` (no MediaMTX).
- Score reveal is per-session — refreshing the page hides scores again.
- The env-var superadmin cannot be deleted from the UI (by design; it's the recovery account).
- Coaching seed inserts notes directly into SQLite, so screenshots of notes-with-drawings render correctly even though `seed.py` does not seed real video files — the focused player modal shows the layout but the underlying `<video>` element is empty.
