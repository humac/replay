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

Most performance/upload knobs that used to live as env vars are now editable
from the admin Settings page (under "Performance Tuning"). The env vars below
are still read on **first boot only** — if no DB row exists yet, the env value
seeds the setting, then the env var is ignored. Edit through the UI thereafter.

**Env-only (boot-time):**

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USER` | `admin` | Env-var superadmin username |
| `ADMIN_PASS` | (none) | Env-var superadmin password |
| `REPLAY_PORT` | `8090` | HTTP listen port |
| `REPLAY_DATA_DIR` | `/tank/replay` | Root data directory (DB + videos) |
| `ALLOWED_ORIGINS` | (empty) | Comma-separated hostnames for login origin check |
| `LOG_FORMAT` | `json` | `json` or `text` |
| `LOG_LEVEL` | `INFO` | Python log level |
| `GEOIP_DB_PATH` | `<REPLAY_DATA_DIR>/app_assets/GeoLite2-City.mmdb` | Path to MaxMind GeoLite2 City DB |
| `MEDIAMTX_HLS_URL` | `http://mediamtx:8888` | Internal LL-HLS address |
| `MEDIAMTX_API_URL` | `http://mediamtx:9997` | Internal control API |
| `TRUSTED_PROXY` | `cloudflare` | `cloudflare` or `none` (see streams.py) |
| `LIVE_AUTH_SECRET` | (empty) | Shared secret MediaMTX sends in `X-Internal-Secret` |

**First-boot fallback (otherwise edited in admin Settings → Performance Tuning):**

| Variable | Maps to setting | Default |
|----------|-----------------|---------|
| `TRANSCODE_CONCURRENCY` | `transcode_concurrency` | `2` |
| `REPLAY_HWACCEL` | `replay_hwaccel` (`auto`/`qsv`/`vaapi`/`nvenc`/`cpu`) | `auto` |
| `HLS_SEGMENT_DURATION` | `hls_segment_duration` | `6` |
| `MAX_UPLOAD_SIZE_BYTES` | `max_upload_size_bytes` | 12 GiB |
| `UPLOAD_CHUNK_SIZE_BYTES` | `upload_chunk_size_bytes` | 16 MiB |
| `VIDEO_STREAM_CHUNK_BYTES` | `video_stream_chunk_bytes` | 1 MiB |
| `MIN_FREE_DISK_BYTES` | `min_free_disk_bytes` | 20 GiB |
| `UPLOAD_DISK_HEADROOM_MULTIPLIER` | `upload_disk_headroom_multiplier` | `2.2` |
| `STALE_UPLOAD_SESSION_SECONDS` | `stale_upload_session_seconds` | 21600 (6 h) |

The admin Settings page also exposes `hls_variant_presets` (the ABR ladder),
`live_hls_variant`, `live_record_enabled`, and `live_transcode_enabled`, which
have no env-var equivalent. Knobs flagged "Restart required" persist
immediately but only take effect on the next process restart (or on the next
new transcode for ladder/segment-duration changes).

**Tuning presets** (one click in the Settings page):

- **Conservative** — current defaults, safe baseline.
- **Balanced 10 GbE** — `transcode_concurrency=4`, `replay_hwaccel=qsv`,
  `hls_segment_duration=4`, larger chunk sizes. Recommended for the
  Terramaster F6-424 Max with Iris Xe + 10 GbE LAN.
- **Live-first** — `replay_hwaccel=qsv`, `live_hls_variant=lowLatency`,
  `live_record_enabled=1`, `live_transcode_enabled=1`. Favors live ingest.

## Reverse Proxy (Caddy — bundled)

A `Caddyfile` and `caddy` compose service ship with the project. Caddy
terminates port 80 and:

- Serves VOD HLS `.ts/.m4s/.mp4` segments and variant playlists **directly
  from the `/data` bind-mount via `sendfile()`** — drops Python out of the
  hot path so 10 GbE LAN delivery is achievable.
- Reverse-proxies everything else (live HLS proxy at `/api/live/hls/*`, MP4
  ranges, all `/api/*` admin endpoints, the SPA shell) to the replay app on
  `:8090`.
- Mirrors the cache policy the replay app uses for HLS: playlists
  `public, max-age=60, must-revalidate`, segments
  `public, max-age=31536000, immutable`.

The bind-mount is read-only inside the Caddy container.

For TLS / WAN, run Caddy behind Cloudflare Tunnel (existing setup) or
front it with a TLS terminator. Don't enable Caddy's automatic HTTPS in
homelab unless you've fronted DNS-01 with your provider.

If you prefer Nginx, important headers to pass through:

```
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

Set `client_max_body_size` to match `max_upload_size_bytes` (or larger) if
using non-chunked uploads.  Chunked uploads send small pieces so this is
usually not an issue.

### Client IP behind Cloudflare / proxies

`streams.client_ip()` resolves the real client IP by checking, in order:

1. `CF-Connecting-IP` (Cloudflare CDN and Cloudflare Tunnel)
2. `True-Client-IP` (Cloudflare Enterprise / Akamai)
3. The leftmost hop in `X-Forwarded-For`
4. The ASGI peer address (`request.client.host`)

This is used by both the admin "Active streaming connections" panel and the
login rate-limiter, so make sure your reverse proxy forwards at least one of
these headers when Replay is not on the public-facing edge.

## Admin: Active streaming connections (GeoIP)

The admin diagnostics panel ("Active streaming connections") shows currently
connected viewers — live HLS, VOD HLS, and VOD MP4 — with their IP, optional
city/country, User-Agent, duration, and bytes sent. A "Kill" button cancels
the in-flight transfer and adds a 5-minute block keyed by
`(ip, kind, match_id, slot)` so the next segment poll or range request from
that viewer is rejected.

City/country comes from a MaxMind GeoLite2-City database. It's optional —
the panel works without it (the location column shows `—`). To enable:

1. Create a free MaxMind account and download `GeoLite2-City.mmdb`
   (https://www.maxmind.com/en/geolite2/signup).
2. Drop the file at `<REPLAY_DATA_DIR>/app_assets/GeoLite2-City.mmdb` (or
   point `GEOIP_DB_PATH` at it).
3. Restart Replay.

Lookups are LRU-cached (4096 entries) and never block on the network — the
DB is read-only and bundled with the deployment.

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
the `cloudflare-ddns` sidecar in `docker-compose.yml` keeps the RTMP A
record pointing at the current public IP. Uses `favonia/cloudflare-ddns`
— config is entirely env-var driven, no JSON file.

This sidecar **only manages the RTMP host** (`f2014steel-live.jvhlabs.com`
in the default config). The HTTPS host (`f2014steel.jvhlabs.com`) is
expected to flow through a Cloudflare Tunnel (`cloudflared`), so its A
record points at Cloudflare's tunnel infrastructure rather than the home
IP — no DDNS needed there. Cloudflare Tunnel can't carry RTMP, so the
camera connects directly to the home IP via the live host, which is why
that one record needs DDNS.

One-time setup:

1. Cloudflare dashboard → My Profile → API Tokens → **Create Token**.
   Use the "Edit zone DNS" template, scope it to the relevant zone
   (e.g. `jvhlabs.com`). Copy the token — you won't see it again.

2. Add the token to `.env.local` (gitignored, alongside the existing
   `replay` env values):

   ```
   CLOUDFLARE_API_TOKEN=your-token-here
   ```

3. Adjust the `DOMAINS` env var in `docker-compose.yml` to match the
   subdomain you're using for RTMP. The default is
   `f2014steel-live.jvhlabs.com`. Multiple subdomains can be
   comma-separated.

4. Start the sidecar:

   ```bash
   docker compose up -d cloudflare-ddns
   docker compose logs -f cloudflare-ddns
   ```

   On boot you should see a line like
   `Set A (f2014steel-live.jvhlabs.com) to <ip>`. Subsequent polls
   (every 5 minutes) only log when the IP actually changes.

If the IP changes, propagation to the camera depends on the Cloudflare
record's TTL. Default is "Auto" (300s for DNS-only records). Lower it in
the dashboard if your ISP cycles IPs frequently and you need faster
recovery.

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
