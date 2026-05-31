# Troubleshooting Guide

## Transcode Failures

### "All transcode methods failed"

The video could not be processed by remux, GPU, or CPU pipelines.

**Diagnose:**
1. Check the admin panel → Recent Errors section for the error details
2. Or call `GET /api/admin/matches/{id}/errors` for the full error history
3. The `details` field contains ffmpeg stderr output from each attempt

**Common causes:**
- Corrupt or truncated upload file
- Unsupported codec (very rare — ffmpeg handles most formats)
- Insufficient disk space during processing

**Recovery:**
- Click **Retry** in the admin panel, or `POST /api/admin/matches/{id}/slots/{slot}/retry`
- If the source file was deleted, re-upload the video

### "Insufficient disk space"

Error code: `disk_full`.  The server checks free disk before transcoding
and refuses to start if space is below `MIN_FREE_DISK_BYTES`.

**Fix:**
- Free disk space (delete old matches, clean orphaned files via admin panel)
- Increase `MIN_FREE_DISK_BYTES` if the threshold is too aggressive
- Retry the failed transcode after freeing space

### "Could not determine video codecs"

Error code: `probe_failed`.  ffprobe could not read the uploaded file.

**Fix:**
- The uploaded file is likely corrupt or not a valid video container
- Re-upload the original file

## Upload Issues

### Upload session times out

Sessions expire after `STALE_UPLOAD_SESSION_SECONDS` (default: 6 hours)
of inactivity.  The browser auto-resumes if the session is still active.

**Fix:**
- Increase `STALE_UPLOAD_SESSION_SECONDS` for very slow connections
- Ensure the browser tab stays open during upload
- The upload resumes automatically on page reload if the session is still active

### "Insufficient free disk space for upload"

The server requires `size × UPLOAD_DISK_HEADROOM_MULTIPLIER` free bytes.

**Fix:**
- Free disk space or increase the data volume
- Lower `UPLOAD_DISK_HEADROOM_MULTIPLIER` (not recommended below 1.5)

### Orphaned raw files

If an upload session is cancelled or times out, partial raw files may remain
on disk.  Use the admin panel **Cleanup Stale Uploads** button or call
`POST /api/uploads/sessions/cleanup`.  This also removes orphaned raw files
that don't belong to any active session.

## HLS Playback

### "HLS playlist not found"

The video is ready (MP4 exists) but HLS segments haven't been generated.

**Fix:**
- Click **Backfill Existing HLS** in the admin panel
- Or regenerate for a specific slot: `POST /api/admin/matches/{id}/slots/{slot}/regenerate-hls`

### Missing HLS variants

Use **Verify Assets** in the admin panel to check which variants are
missing, then regenerate HLS for that slot.

### Playback stutters or fails on Cast/AirPlay

- Ensure HLS assets are fully generated (verify via admin panel)
- Check that the reverse proxy allows large responses and long connections
- Cast devices require network access to the server URL

## Database Issues

### Export / backup

Use the admin panel **Export Database** button.  This downloads a copy of
the SQLite database file.

### Migration errors on startup

Schema migrations run automatically.  If a migration fails, the server
logs the error and may not start.  Check logs for the specific migration
version that failed.

**Fix:**
- Back up `replay.db` before attempting fixes
- If the database is corrupt, restore from a backup
- Migration state is tracked in the `schema_version` table

### Upgrading from an older (pre-v1) database

When the app finds a database from an older build (its `user_version` is
higher than 1), it migrates it to the v1 schema **in place on startup** — you
should see `Folded legacy database down to schema v1` in the logs. All
matches, users, sessions, settings, and uploads are preserved; the old
team/season columns and coaching/account tables are dropped. No manual step is
needed, but back up `replay.db` before upgrading as a precaution. See
[Deployment → Upgrading an older database](DEPLOYMENT.md#upgrading-an-older-database).

If the fold-down itself errors (e.g. a corrupt source database), the server
logs the failure and does not start. Restore `replay.db` from your backup and
investigate, or — if the data is disposable — start from a fresh
`REPLAY_DATA_DIR`.

## GPU Transcoding

### GPU transcode fails, CPU fallback works

This is normal behavior — the server automatically falls back to CPU
`libx264` when GPU encoding fails (NVENC unavailable, driver mismatch, etc.).

**To use GPU consistently:**
- Ensure the NVIDIA Container Toolkit is installed
- Set `NVIDIA_VISIBLE_DEVICES` and `NVIDIA_DRIVER_CAPABILITIES` in `.env.local`
- Verify GPU access: `docker exec replay nvidia-smi`

### CPU-only deployment

Remove NVIDIA settings from `docker-compose.yml` and `.env.local`.
Transcoding uses `libx264` with `-preset medium -crf 23` — slower but
works everywhere.

## UI / Frontend

### "Reveal Score" chip looks oversized on mobile

The match card and game-detail page expose a "Reveal Score" chip when
a match has a final score that is still hidden. On narrow viewports,
the chip can balloon into a circular blob if it stretches to the full
row width and its label wraps to two lines.

The fix lives in `styles.css` under the `@media (max-width: 520px)`
block near `.score-reveal-chip`. Both `.score-reveal-chip` and
`.score-reveal-chip-large` are sized to content (`flex-basis: auto`,
`align-self: center`), padded to match `.match-detail-pill`
(`padding: 0.38rem 0.72rem`), and pinned to a single line
(`white-space: nowrap`). The game-page button label is also kept
short ("Reveal score" rather than "Reveal final score") in
`js/views.js` so it doesn't run out of room — the longer phrasing
is preserved in the `aria-label` for accessibility.

If the chip ever drifts back to looking out-of-proportion on mobile,
check that:

- The `@media (max-width: 520px)` rule still targets both class
  variants (`.score-reveal-chip, .score-reveal-chip-large`).
- No newer rule reintroduces `flex-basis: 100%` or removes
  `white-space: nowrap`.
- The button label in `js/views.js` is still the short form.
