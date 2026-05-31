# Changelog

All notable changes to Replay are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

First stable release. Replay is a single-team match video platform: VOD upload
+ transcode + multi-variant HLS playback, plus live RTMP → LL-HLS streaming, an
admin console, and admin-managed user accounts.

### Features

- **VOD library** — chunked, resumable uploads (MP4 / MKV) → ffmpeg transcode →
  multi-variant HLS ladder, with a direct MP4 fallback for download and
  casting. Single-video or two-half matches. HLS backfill for already-uploaded
  MP4s.
- **Live streaming** — RTMP ingest through a MediaMTX sidecar, repackaged to
  LL-HLS and reverse-proxied so viewers watch same-origin at `/live` with
  sub-5s latency.
- **Playback** — dark-themed SPA player with AirPlay 2 and Chromecast support,
  spoiler-safe score reveal, and per-match download/cast controls.
- **Admin console** — `/admin/{overview,matches,live,performance,users,settings}`:
  match library management, per-slot upload recovery (verify / re-transcode /
  regenerate HLS / regenerate thumbnail), live stream config, performance
  tuning knobs, user management, branding, and an operational activity feed.
- **Accounts** — admin-managed users with three roles (`admin` / `uploader` /
  `viewer`); durable hashed bearer sessions, revoked on logout.

### Stack

- FastAPI + SQLite backend; no-build vanilla-JS SPA frontend.
- Caddy as the single public entry point; MediaMTX sidecar for live ingest.
- In-process durable transcode queue.
- SQLite schema created on first startup at `PRAGMA user_version = 1`. SQLite is
  the only supported backend. A database from an older multi-team build is
  migrated to the v1 schema in place on startup (matches/users/sessions/settings
  preserved; coaching/team/account tables dropped).

### Not in scope

Replay is intentionally focused. The following are out of scope and not planned
(see `ROADMAP.md` → Scope boundaries): coaching / player-feedback features,
multi-tenancy (teams / seasons-as-tenants / memberships / invites), account
self-service (signup / profile self-edit / password reset / email
verification), and alternate database backends.

[1.0.0]: https://github.com/humac/replay/releases/tag/v1.0.0
