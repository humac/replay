# Replay

A standalone match viewer and video archive for soccer (or any sport). Upload match recordings, add team details and logos, and replay them in a clean, modern dark-themed web UI.

## Features

- **Manual match creation** — add home/away teams, logos, date, time, location, and score
- **Video upload** — supports MP4 and MKV files (MKV is automatically remuxed to MP4 via ffmpeg)
- **Resumable large uploads** — chunked upload sessions with browser-side resume support for interrupted transfers
- **Single or two-half matches** — upload one video for a full match, or separate videos for each half with a segment selector
- **Adaptive streaming** — each processed upload is packaged into an HLS ladder for smoother playback under varying bandwidth
- **Direct MP4 fallback** — the processed MP4 remains available for simple playback, range seeking, and casting
- **HLS backfill for existing uploads** — already processed MP4 files can generate HLS assets later without re-uploading
- **AirPlay 2** — explicit AirPlay picker button on supported Safari/WebKit devices for Apple TV and AirPlay 2 displays
- **Chromecast** — Google Cast SDK integration with a dedicated cast button, metadata, and remote playback resume support
- **System settings** — admin-only branding and label controls for app name, season copy, logo, favicon, filters, and download availability
- **Home/Away filters** — configurable main-team matching powers `All`, `Home`, and `Away` filtering on the main page
- **Public downloads** — optional direct MP4 download buttons for ready games with normal browser resume support for large files
- **Dark theme** — polished dark UI with Oswald/Manrope typography, smooth animations, and a noise overlay
- **Edit & delete** — update match details or remove matches (and their videos) from the UI
- **Admin diagnostics** — inspect upload sessions, cleanup stale partial uploads, and check disk headroom

## Screenshot

After adding a match, the season view displays cards with team logos, score, date, and format badge. Clicking a card opens the video player with match details in a sidebar.

## Quick Start

### Prerequisites

- Python 3.11+
- ffmpeg (for MKV remux support)

### Install & Run

```bash
pip install -r requirements.txt
python server.py
```

Open [http://localhost:8090](http://localhost:8090) in your browser.

### Run with Docker

Build and run with Docker Compose:

```bash
docker compose up --build
```

Then open [http://localhost:8090](http://localhost:8090).

Copy the example environment file before first run if you want to override defaults:

```bash
cp .env.example .env.local
```

Data persists in a named Docker volume (`replay_data`) mounted at `/data` in the container.

Build/run with plain Docker:

```bash
docker build -t replay .
docker run --rm -p 8090:8090 -v replay_data:/data replay
```

### Configuration

| Environment Variable | Default | Description |
| -------------------- | ------- | ----------- |
| `REPLAY_DATA_DIR` | `/tank/replay` | Directory for match metadata and uploaded videos |
| `REPLAY_PORT` | `8090` | Server port |
| `MAX_UPLOAD_SIZE_BYTES` | `12884901888` | Max allowed upload size |
| `UPLOAD_CHUNK_SIZE_BYTES` | `16777216` | Chunk size for resumable uploads |
| `TRANSCODE_CONCURRENCY` | `2` | Max concurrent ffmpeg jobs |
| `VIDEO_STREAM_CHUNK_BYTES` | `1048576` | Chunk size used for HTTP range streaming |
| `HLS_SEGMENT_DURATION` | `6` | Segment duration for generated HLS variants |
| `MIN_FREE_DISK_BYTES` | `21474836480` | Minimum free disk threshold before accepting new uploads |
| `UPLOAD_DISK_HEADROOM_MULTIPLIER` | `2.2` | Required free-space multiplier for new uploads |
| `STALE_UPLOAD_SESSION_SECONDS` | `21600` | Idle upload session age before cleanup |

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

## API

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| `/` | GET | Serve the web app |
| `/api/matches` | GET | List all matches |
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

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn
- **Frontend**: Vanilla HTML/CSS/JS (no build step)
- **Fonts**: Oswald + Manrope (Google Fonts)
- **Cast**: Google Cast SDK (Chromecast), AirPlay 2 via Safari/WebKit remote playback APIs
- **Storage**: SQLite + filesystem

## License

MIT
