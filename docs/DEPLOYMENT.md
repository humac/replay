# Deployment Guide

## Quick Start (Docker Compose — GPU)

```bash
cp .env.example .env.local   # edit ADMIN_PASS, NVIDIA_VISIBLE_DEVICES
docker compose up --build -d
```

The app is accessible at `http://localhost:8090`.

## Docker Compose (CPU-only)

Remove the `deploy.resources.reservations` block and NVIDIA environment
variables from `docker-compose.yml`.  Transcoding falls back to `libx264`
automatically when GPU is unavailable.

## Bare-metal

```bash
pip install -r requirements.txt
cp .env.example .env.local    # edit as needed
source .env.local              # or export vars manually
python server.py
```

Requires Python 3.10+ and `ffmpeg`/`ffprobe` on PATH.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USER` | `admin` | Env-var superadmin username |
| `ADMIN_PASS` | (none) | Env-var superadmin password |
| `REPLAY_PORT` | `8090` | HTTP listen port |
| `REPLAY_DATA_DIR` | `/tank/replay` | Root data directory (DB + videos) |
| `MAX_UPLOAD_SIZE_BYTES` | 12 GB | Max upload file size |
| `UPLOAD_CHUNK_SIZE_BYTES` | 16 MB | Chunked upload piece size |
| `TRANSCODE_CONCURRENCY` | `2` | Max simultaneous transcode jobs |
| `VIDEO_STREAM_CHUNK_BYTES` | 1 MB | Video streaming chunk size |
| `HLS_SEGMENT_DURATION` | `6` | HLS segment length in seconds |
| `MIN_FREE_DISK_BYTES` | 20 GB | Minimum free disk to accept uploads |
| `UPLOAD_DISK_HEADROOM_MULTIPLIER` | `2.2` | Upload size × this = required free space |
| `STALE_UPLOAD_SESSION_SECONDS` | 6 hours | Idle upload session timeout |
| `ALLOWED_ORIGINS` | (empty) | Comma-separated hostnames for login origin check |
| `LOG_FORMAT` | `json` | `json` or `text` |
| `LOG_LEVEL` | `INFO` | Python log level |

## Reverse Proxy (Nginx / Caddy)

Replay serves its own static assets; place a reverse proxy in front for TLS
and caching.  Important headers to pass through:

```
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

Set `client_max_body_size` to match `MAX_UPLOAD_SIZE_BYTES` (or larger) if
using non-chunked uploads.  Chunked uploads send small pieces so this is
usually not an issue.

## CDN / Live-Stream Scale-Out

The HLS proxy at `/api/live/hls/*` sets `Cache-Control` per asset type:

| Path | `Cache-Control` |
|------|-----------------|
| `*.m3u8` | `public, max-age=1, must-revalidate` |
| `*.ts`, `*.mp4`, `*.m4s` | `public, max-age=60, immutable` |
| Errors (4xx/5xx) | `no-store` |

Segments are content-addressed (filenames embed a session prefix + sequence
number and are never reused), so a CDN edge can dedupe them safely. With a
CDN in front of Replay, N concurrent viewers cost ~1 origin pull per segment
instead of N — the practical scale-out lever for live streaming.

Recommended Cloudflare setup:

1. Add the Replay hostname to Cloudflare; proxy traffic (orange cloud).
2. Page Rule on `your-host/api/live/hls/*` → "Cache Level: Cache Everything",
   "Edge Cache TTL: respect existing headers".
3. Leave the rest of the site on the default rules — only HLS benefits from
   edge caching; everything else is dynamic or already covered by the
   per-asset headers Replay sets.

Tune `LIVE_STALE_SEGMENT_AGE_SECONDS` (default 90) if your camera disconnect
behavior needs faster offline detection. A smaller value flips `/api/live/status`
to `active=false` sooner after the camera stops sending video keyframes.

## Cloudflare Dynamic DNS

If your Replay host runs on a residential connection without a static IP,
the `cloudflare-ddns` sidecar in `docker-compose.yml` keeps both A records
pointing at the current public IP. Uses `favonia/cloudflare-ddns` —
config is entirely env-var driven, no JSON file.

One-time setup:

1. Cloudflare dashboard → My Profile → API Tokens → **Create Token**.
   Use the "Edit zone DNS" template, scope it to the relevant zone
   (e.g. `jvhlabs.com`). Copy the token — you won't see it again.

2. Add the token to `.env.local` (gitignored, alongside the existing
   `replay` env values):

   ```
   CLOUDFLARE_API_TOKEN=your-token-here
   ```

3. Adjust the `DOMAINS` and `PROXIED` env vars in `docker-compose.yml` to
   match your hosts. Default keeps `f2014steel.jvhlabs.com` proxied
   (orange cloud, for HTTPS+CDN) and `f2014steel-live.jvhlabs.com`
   DNS-only (gray cloud, required for RTMP). The `PROXIED=is(...)`
   syntax matches a specific domain; everything else stays not-proxied.

4. Start the sidecar:

   ```bash
   docker compose up -d cloudflare-ddns
   docker compose logs -f cloudflare-ddns
   ```

   On boot you should see lines like
   `Updating A (f2014steel.jvhlabs.com) to <ip>` or
   `Set A (f2014steel.jvhlabs.com) to <ip>`. Subsequent polls (every 5
   minutes) only log when the IP actually changes.

If the IP changes, propagation to viewers depends on the Cloudflare
record's TTL — visible in the Cloudflare dashboard. Default is "Auto"
(60s when proxied). Set explicitly via `TTL` env var if you need
something specific.

## Storage

Data lives under `REPLAY_DATA_DIR`:

```
<REPLAY_DATA_DIR>/
├── replay.db          # SQLite database
├── app_assets/        # Uploaded logos, favicons
└── videos/
    └── <match-id>/
        ├── full.mp4
        ├── first_half.mp4
        ├── second_half.mp4
        ├── thumb.jpg
        └── hls/
            └── <slot>/
                ├── master.m3u8
                └── <variant>/
                    ├── index.m3u8
                    └── segment_*.ts
```

In Docker Compose the default config uses a named volume `replay_data`
mounted at `/data`.

## Backup

Use the admin panel **Export Database** button or call:

```bash
curl -X POST http://localhost:8090/api/admin/export-database \
  -H "Authorization: Bearer <token>" \
  -o replay-backup.db
```

This downloads a copy of `replay.db`.  Video files must be backed up
separately (e.g., `rsync` or volume snapshot).

## Resource Requirements

- **Disk:** 2–3× the raw video size (raw upload + MP4 + HLS segments)
- **CPU:** 2+ cores recommended for concurrent transcoding
- **GPU (optional):** NVIDIA with NVENC support for faster transcoding
- **RAM:** 512 MB minimum; ffmpeg uses additional memory during transcoding
