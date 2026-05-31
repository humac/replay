# Replay

**v1.0.0** · A standalone, single-team match viewer and video archive for soccer (or any sport). Upload match recordings, add team details and logos, and replay them in a clean, modern dark-themed web UI. VOD playback plus live RTMP/LL-HLS streaming.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Features

- **Manual match creation** — add home/away teams, logos, date, time, location, and score
- **Video upload** — supports MP4 and MKV files (MKV is automatically remuxed to MP4 via ffmpeg)
- **Resumable large uploads** — chunked upload sessions with browser-side resume support for interrupted transfers
- **Single or two-half matches** — upload one video for a full match, or separate videos for each half with a segment selector
- **Adaptive streaming** — each processed upload is packaged into an HLS ladder for smoother playback under varying bandwidth
- **Direct MP4 fallback** — the processed MP4 remains available for simple playback, range seeking, and casting
- **HLS backfill for existing uploads** — already processed MP4 files can generate HLS assets later without re-uploading
- **Watch Live (RTMP ingest → LL-HLS)** — point a camera (e.g. XbotGo Falcon) at the site's RTMP URL with a configurable stream key; viewers watch the live feed at `/live` with sub-5s latency
- **AirPlay 2** — explicit AirPlay picker button on supported Safari/WebKit devices for Apple TV and AirPlay 2 displays
- **Chromecast** — Google Cast SDK integration with a dedicated cast button, metadata, and remote playback resume support
- **Single-team match library** — a flat, global match library grouped by a season label in the public view
- **Admin-managed accounts** — admins create and manage user accounts with three roles (`admin` / `uploader` / `viewer`); sign-in is by username + password
- **Durable sessions** — database-user logins persist hashed bearer sessions; logout revokes them
- **System settings** — admin-only branding and label controls for app name, season copy, logo, favicon, filters, and download availability
- **Home/Away filters** — configurable main-team matching powers `All`, `Home`, and `Away` filtering on the main page
- **Public downloads** — optional direct MP4 download buttons for ready games with normal browser resume support for large files
- **Dark theme** — polished dark UI with Oswald/Manrope typography, smooth animations, and a noise overlay
- **Edit & delete** — update match details or remove matches (and their videos) from the UI
- **Admin diagnostics** — inspect upload sessions, cleanup stale partial uploads, and check disk headroom

## Screenshot

After adding a match, the season view displays cards with team logos, score, date, and format badge. Clicking a card opens the video player with match details in a sidebar.

## Quick Start

### Run locally (Mac, no Docker)

**1. Install prerequisites**

```bash
brew install python@3.11 ffmpeg
```

Verify both are available:

```bash
python3 --version   # 3.11+
ffmpeg -version
ffprobe -version
```

**2. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure environment**

```bash
cp .env.example .env.local
```

Edit `.env.local` — at minimum set:

- `ADMIN_PASS` — required, the server refuses to start without it
- `REPLAY_DATA_DIR` — change from `/data` to a writable local path, e.g. `~/replay-data`
- `REPLAY_HWACCEL=cpu` — disables NVENC/VAAPI GPU detection (not available on Mac)

**4. Create the data directory and start**

```bash
mkdir -p ~/replay-data
source .env.local
python server.py
```

Open [http://localhost:8091](http://localhost:8091) and log in with `admin` / your `ADMIN_PASS`.

> **Note:** Live streaming (RTMP → LL-HLS) requires the `mediamtx` sidecar from Docker Compose and is not available in the bare-metal setup. Transcoding falls back to `libx264` automatically when `REPLAY_HWACCEL=cpu`.

### Run with Docker

Build and run with Docker Compose:

```bash
docker compose up --build
```

Then open [http://localhost:8091](http://localhost:8091).

Copy the example environment file before first run if you want to override defaults:

```bash
cp .env.example .env.local
```

Data persists in a named Docker volume (`replay_data`) mounted at `/data` in the container.

Compose also runs a `mediamtx` sidecar that handles the live stream. It exposes RTMP on `1936` (camera-facing) and keeps its HLS/control ports on the internal compose network — viewers always reach the live feed through the same `8091` origin via a reverse proxy.

Replay uses SQLite as its only database backend. The schema is created on first startup at `PRAGMA user_version = 1`; a fresh `REPLAY_DATA_DIR` is all you need. See [DEPLOYMENT.md → Database](docs/DEPLOYMENT.md#database).

Build/run with plain Docker (without the live stream):

```bash
docker build -t replay .
docker run --rm -p 8091:8091 -v replay_data:/data replay
```

### Configuration

| Environment Variable | Default | Description |
| -------------------- | ------- | ----------- |
| `REPLAY_DATA_DIR` | `/tank/replay` | Directory for match metadata and uploaded videos |
| `REPLAY_PORT` | `8091` | Server port |
| `MAX_UPLOAD_SIZE_BYTES` | `12884901888` | Max allowed upload size |
| `UPLOAD_CHUNK_SIZE_BYTES` | `16777216` | Chunk size for resumable uploads |
| `TRANSCODE_CONCURRENCY` | `2` | Max concurrent ffmpeg jobs |
| `VIDEO_STREAM_CHUNK_BYTES` | `1048576` | Chunk size used for HTTP range streaming |
| `HLS_SEGMENT_DURATION` | `6` | Segment duration for generated HLS variants |
| `MIN_FREE_DISK_BYTES` | `21474836480` | Minimum free disk threshold before accepting new uploads |
| `UPLOAD_DISK_HEADROOM_MULTIPLIER` | `2.2` | Required free-space multiplier for new uploads |
| `STALE_UPLOAD_SESSION_SECONDS` | `21600` | Idle upload session age before cleanup |
| `MEDIAMTX_HLS_URL` | `http://mediamtx:8888` | Internal HLS endpoint of the MediaMTX sidecar |
| `MEDIAMTX_API_URL` | `http://mediamtx:9997` | Internal control API of the MediaMTX sidecar |

## System Settings

After logging in as admin, open the `Settings` page from the main navigation to configure:

- app name shown in the main nav and browser title
- season header title and intro copy
- custom app logo and favicon
- main team name used for `All`, `Home`, and `Away` filters
- navigation labels, filter labels, and stats labels
- replay page labels such as the back button and video status heading
- whether public downloads are enabled

These settings are stored in SQLite and applied across the SPA without changing match records.

## Live Streaming

Replay can ingest a live RTMP feed (e.g. from an XbotGo Falcon or any camera/encoder that speaks RTMP) and play it back in the browser at `/live` with sub-5s latency over LL-HLS.

The live pipeline is provided by a `mediamtx` sidecar in `docker-compose.yml`:

- camera pushes RTMP to `rtmp://<your-host>:1936/live/<stream-key>`
- MediaMTX repackages to LL-HLS and exposes it on its internal port `8888`
- the `replay` app reverse-proxies the playlist + segments at `/api/live/hls/*`, so viewers only ever talk to the same `8091` origin
- MediaMTX calls back to `/api/live/auth` on every publish to validate the stream key — rotating the key invalidates any active publisher immediately

### Camera setup

Log in as admin and open **Settings → Live Streaming**:

1. tick **Enable the Watch Live tab** (default on)
2. enter the public-facing RTMP URL you want camera operators to use, e.g. `rtmp://replay.example.com:1936/live`
3. copy the auto-generated **Stream Key** (click *Reveal* to view it)
4. paste the URL + key into your camera/encoder
5. point a viewer at `/live` — the player shows an "Offline" placeholder until the camera goes live, then auto-attaches to the LL-HLS feed

The stream key is private — it is never returned by `/api/settings`. Use **Rotate** to generate a new one whenever you need to revoke access.

There is no recording: live frames are not persisted on disk. Once the match is done, upload the camera's local recording the usual way.

## Downloads

When downloads are enabled in system settings, ready MP4 files expose public download buttons in the replay view.

This implementation is intentionally direct:

- it downloads the processed MP4, not HLS playlists or segments
- it reuses the same range-capable streaming path as playback, so browsers can resume interrupted transfers
- it is suitable for large files such as 8 GB match recordings without buffering the full file in server memory

Data is stored in SQLite (`replay.db`) and video/logo files on disk under the data directory:

```text
$REPLAY_DATA_DIR/
├── replay.db
└── videos/
    └── <match-id>/
        ├── home_logo.png
        ├── away_logo.png
        ├── full.mp4
        ├── hls/
        │   └── full/
        │       ├── master.m3u8
        │       ├── 1080p/
        │       ├── 720p/
        │       └── 480p/
        ├── first_half.mp4
        └── second_half.mp4
```

## Backend Layout

The FastAPI app is intentionally split so `server.py` stays focused on app wiring, lifespan/startup work, shared path helpers, static/SPA serving, and compatibility wrappers. Most request domains live in focused routers with shared policy in services:

- Core routers:
  - `routers/auth.py` — login/logout/auth-check and durable bearer sessions
  - `routers/admin.py` — admin-only `/api/users*` user-management endpoints
  - `routers/settings.py` — admin settings and branding
- Media/operations routers:
  - `routers/matches.py`, `routers/uploads.py`, `routers/live.py`, `routers/admin_ops.py` — match library CRUD/playback/recovery, resumable uploads, live streaming, and diagnostics/export

Shared service map:

- `services/thumbnails.py` — match thumbnail path checks and generation helpers
- `services/activity.py` — persisted admin/activity feed wrappers
- `services/jobs.py` — durable in-process background-job enqueue/list/cancel/worker lifecycle (transcodes create job rows but still execute through the existing in-process transcode path)

Keep new backend behavior in the appropriate router/service module instead of adding more policy logic to `server.py`.

## API

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| `/` | GET | Serve the web app |
| `/api/matches` | GET | List all matches (flat global library) |
| `/api/matches` | POST | Create a new match (JSON body) |
| `/api/matches/{id}` | PUT | Update match metadata |
| `/api/matches/{id}` | DELETE | Delete match and all associated files |
| `/api/matches/{id}/upload-video/session?slot=` | POST | Create or resume a chunked upload session |
| `/api/uploads/sessions/{id}` | GET | Inspect a chunked upload session |
| `/api/uploads/sessions/{id}/chunk?index=` | PUT | Upload one chunk |
| `/api/uploads/sessions/{id}/complete` | POST | Finalize upload and start processing |
| `/api/uploads/sessions/{id}` | DELETE | Cancel an upload session and remove its partial file |
| `/api/uploads/sessions/cleanup` | POST | Cleanup stale upload sessions |
| `/api/admin/diagnostics` | GET | Admin diagnostics for disk space, transcodes, and uploads |
| `/api/admin/backfill-hls` | POST | Generate HLS ladders for existing ready MP4 files missing adaptive assets |
| `/api/matches/{id}/upload-video?slot=` | POST | Upload video (slot: `full`, `first_half`, `second_half`) |
| `/api/matches/{id}/hls/{slot}/master.m3u8` | GET | Serve the HLS master playlist for adaptive playback |
| `/api/matches/{id}/hls/{slot}/{asset}` | GET | Serve HLS variant playlists and transport stream segments |
| `/api/matches/{id}/upload-logo?team=` | POST | Upload team logo (team: `home`, `away`) |
| `/api/matches/{id}/video/{slot}` | GET | Stream video with range request support |
| `/api/matches/{id}/logo/{team}` | GET | Serve team logo image |
| `/api/live/status` | GET | Whether a live stream is currently active |
| `/api/live/hls/{path}` | GET | Same-origin reverse proxy for the LL-HLS playlist + segments |
| `/api/live/auth` | POST | Webhook MediaMTX calls to authorise an RTMP publish |
| `/api/logout` | POST | Revoke the current bearer token/session |
| `/api/admin/live/config` | GET | Admin: view stream key, RTMP path, and live config |
| `/api/admin/live/rotate-key` | POST | Admin: rotate the stream key (invalidates current publisher) |

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn, httpx
- **Frontend**: Vanilla HTML/CSS/JS (no build step), HLS.js for in-browser LL-HLS playback
- **Live ingest**: MediaMTX sidecar (RTMP → LL-HLS) reverse-proxied through FastAPI
- **Fonts**: Oswald + Manrope (Google Fonts)
- **Cast**: Google Cast SDK (Chromecast), AirPlay 2 via Safari/WebKit remote playback APIs
- **Storage**: SQLite + filesystem

## License

MIT
