# Code Review — 2026-04-27

Findings from a full-project security / correctness / quality pass after Milestones 8 (Admin Dashboard) and 9 (Score De-emphasis) shipped. Tick boxes as items are addressed.

**Verdict:** ~~Request changes~~ C1–C7 all fixed 2026-04-27 — Critical items resolved. Major items next.

**Overall:** Solid foundation with thoughtful operational details (orphan sweepers, range-request cancellation, structured logger plumbing). Three classes of issue need attention: stored XSS in attribute contexts because `esc()` doesn't escape quotes, read-modify-write races around match writes, and default `admin`/`admin` credentials in production. Plus a sprawl of fire-and-forget `asyncio.create_task` calls that swallow exceptions.

---

## Critical (must fix)

- [x] **C1. Stored XSS via `User-Agent` in admin Streams panel** — `js/views.js:473`
  - Issue: `title="${this.esc(s.user_agent)}"` — `esc()` only escapes `< > &`, not `" '`. Anonymous viewer can break out with `User-Agent: " onmouseover="..."` and exfiltrate the admin token from sessionStorage.
  - Fix: broaden `esc()` in `js/utils.js:5` to cover `"` and `'`. Promote `escapeHtml` from `js/ui.js:68` (which already does it) to the shared util.

- [x] **C2. XSS via attacker-controlled IP in unblock button** — `js/views.js:433`
  - Issue: `onclick='app.unblockStream(${JSON.stringify(b)})'` — `JSON.stringify` escapes `"` but not `'`. With a non-Cloudflare deployment, an attacker can spoof their IP via `X-Forwarded-For` to break out of the single-quoted attribute.
  - Fix: stop interpolating JSON into HTML. Attach data via `data-*` attributes; assign click handler in JS after row creation.

- [x] **C3. Default `admin`/`admin` credentials** — `auth.py:33–34`
  - Issue: `ADMIN_USER`/`ADMIN_PASS` fall back to `"admin"`/`"admin"` when env-unset.
  - Fix: refuse to start when `ADMIN_PASS` is unset, OR auto-generate on first boot and print to stdout. Update `.env.example`.

- [x] **C4. `delete_match` releases `MATCHES_LOCK` between existence check and `rmtree`** — `server.py:1146–1159`
  - Issue: Lock is taken, released, `shutil.rmtree(videos/{id}/)` runs unlocked, then lock re-acquired for the row delete. Concurrent upload landing between releases gets nuked.
  - Fix: delete DB row inside a single locked block first, then `rmtree` afterward (no further request can find the match by id).

- [x] **C5. Concurrent `/retry`, `/regenerate-hls`, `/regenerate-thumbnail` are unlocked** — `server.py:924–1028`
  - Issue: Two admins clicking Retry both pass the `status=='error'` check, both rename `slot.mp4 → slot_raw.mp4`, two `_transcode_video` tasks race writing to the same destination. `TRANSCODE_SEMAPHORE` is acquired *inside* `transcode_video`, so it doesn't gate task spawning.
  - Fix: compare-and-swap slot status to `"transcoding"` inside `MATCHES_LOCK`; only proceed if prior was `"error"`. Rename inside the lock.

- [x] **C6. Race in `complete_upload_session` allows double transcode spawn** — `server.py:1342–1381`
  - Issue: Two concurrent POSTs to `/complete` both pass `status=='active'` check, both spawn `_transcode_video`.
  - Fix: `UPDATE upload_sessions SET status='completed' WHERE id=? AND status='active'` and check `cursor.rowcount == 1` before spawning.

- [x] **C7. HLS backfill partial-failure leaves silently-incomplete ladder** — `media.py:build_hls_assets` (~line 374)
  - Issue: `asyncio.gather(*variants)` partial success writes a master.m3u8 listing only the successful variants. `_ready_slots_missing_hls` checks only `master.is_file()` — exists, so backfill skips it. Slot permanently lacks 1080p with no signal.
  - Fix: (a) `master.m3u8.tmp` + `os.replace` for atomic publish; (b) `_ready_slots_missing_hls` calls `verify_slot_assets` and treats `hls_complete=False` as needs-backfill; (c) treat any variant failure as full failure.

---

## Major (should fix)

- [x] **M1. `esc()` doesn't escape quotes — pattern across many sites** — `js/views.js:140, 396, 397, 476, 606, 607, 654, 1177, 1180`
  - Today protected by server-side validation (username regex, slot enum, server-generated UUIDs); every new field that misses validation becomes XSS.
  - Fix: unify `esc()` covering `< > & " '`. (Same root cause as C1; this captures the rest of the surface.)

- [ ] **M2. Login rate limit trusts spoofable headers when not behind Cloudflare** — `auth.py:107–119`
  - `client_ip()` honors `CF-Connecting-IP` / `X-Forwarded-For` unconditionally. A bare deployment lets an attacker rotate the header to bypass the 5/min cap.
  - Fix: explicit `TRUSTED_PROXY` env (`cloudflare`/`none`); only honor headers when peer is in an allowlisted CIDR.

- [ ] **M3. `/api/live/auth` is unauthenticated and unrate-limited** — `server.py:634`
  - 144-bit key is brute-force-infeasible, but the endpoint is public. Could be used for rejection-log spam / mild amplification.
  - Fix: restrict to MediaMTX peer IP (compose service IP) OR require shared-secret header configured in `mediamtx.yml`'s `authHTTPHeaders`.

- [ ] **M4. Background tasks fire-and-forget; exceptions silently dropped** — `server.py:59–62, 965, 1380, 1431`
  - `asyncio.create_task(...)` with no reference, no `add_done_callback`, no awaited cleanup. GC can collect; SIGTERM leaves orphan ffmpegs.
  - Fix: module-level `_background_tasks: set[asyncio.Task]` + `add_done_callback(self.discard)`; `await gather(*pending)` in `lifespan` shutdown.

- [ ] **M5. `lifespan` shutdown cancels only the sweeper** — `server.py:51–67`
  - SIGTERM during a transcode leaves ffmpeg writing a half-MP4. `_sweep_orphaned_transcodes` flips status to `error` on next start but doesn't unlink the partial file.
  - Fix: track child `Process` handles in `media._transcode_progress`; terminate on shutdown; orphan sweep deletes partial dest files.

- [ ] **M6. `/api/matches` is unbounded; SPA always uses no-args branch** — `server.py:1070–1076`, `js/api.js:133–141`
  - Pagination exists in `db.search_matches` but client never invokes it. ~1000 matches × ~1KB = ~1MB JSON every transcode poll tick.
  - Fix: cap no-args path at ~500 most-recent; migrate client to paginated queries with infinite scroll.

- [ ] **M7. Match deletion does not cascade** — `server.py:1143–1160`
  - `upload_sessions` rows orphaned forever; `video_errors` rows orphaned forever; in-flight `_transcode_video` task isn't cancelled.
  - Fix: `DELETE FROM upload_sessions WHERE match_id=?`, `DELETE FROM video_errors WHERE match_id=?`, cancel any tracked task for that match.

- [ ] **M8. Upload session resume can produce a Frankenstein file** — `js/uploads.js:45–75`, `server.py:1188–1248`
  - `find_active_session` matches on `(match_id, slot, size, ext)`. Two browsers picking different files of identical size and extension interleave chunks into one corrupt MP4.
  - Fix: hash first chunk on bind, store on session row; reject mismatched first-chunk hashes.

- [ ] **M9. `/api/admin/diagnostics` walks every video file every call** — `server.py:871–879`
  - 100 matches × 4 HLS variants × ~300 segments = 120k+ `stat()` syscalls per refresh; status strip refreshes every 10s.
  - Fix: memoize for 60s with mtime invalidation, OR compute lazily only when System tab is open.

- [ ] **M10. Transcode progress polled with N+1 fetches** — `js/api.js:259–277`
  - One fetch per active transcode every 5s. Diagnostics already has `active_jobs`.
  - Fix: single `/api/transcode-progress` endpoint returning all active jobs.

- [ ] **M11. HLS variant generation has no concurrency cap** — `media.py:371`
  - `asyncio.gather(*variants)` spawns 3+ ffmpegs per transcode on top of `TRANSCODE_CONCURRENCY=2`. Six concurrent ffmpegs on a 2-core box thrash.
  - Fix: reuse `transcode_semaphore` inside `_generate_variant`, OR add `HLS_CONCURRENCY` capped at 2.

- [ ] **M12. No "GPU permanently broken" signal** — `media.py:531`
  - Each failed GPU attempt logs a warning, but no aggregated counter. Broken VAAPI silently drops every transcode to CPU at 5× elapsed time.
  - Fix: counter pair `gpu_attempts_failed` / `gpu_attempts_succeeded` exposed via `/api/admin/diagnostics`.

- [ ] **M13. Audit log gap on destructive admin actions** — `server.py:809, 1143, 722, 924, 969, 990, 910, 1050, 787`
  - None of `delete_user`, `delete_match`, `unblock_stream`, `retry_transcode`, `regenerate_hls`, `regenerate_thumbnail`, `backfill_hls`, `export_database`, `update_user` log who did what to which target.
  - Fix: `logger.info("admin.action", extra={"action": ..., "actor": user["username"], "target_id": ...})`.

- [ ] **M14. Structured logging plumbing exists but is unused** — `log.py:23` plus call sites across `server.py / media.py / live.py / uploads.py`
  - Only `streams.py` uses `extra={...}`. Everywhere else uses `%s` interpolation, defeating the JSON formatter.
  - Fix: convert high-signal sites (kill, rotate, transcode start/done, upload create/complete, live HLS proxy errors) to `extra=`.

- [ ] **M15. Two admins editing the same match: last-write-wins** — `server.py:1118–1140`
  - `MATCHES_LOCK` only serializes within one process; no version/etag check. With `exclude_unset=True` it's a partial merge — small blast radius, but a deliberate field-clear by admin A can be lost.
  - Fix: `If-Match` ETag with `updated_at`; return 409 on mismatch.

- [ ] **M16. `renderSeasonView` re-renders entire grid on every transcode poll** — `js/views.js:1148–1260`, `js/api.js:244`
  - 5s poll calls `renderSeasonView` unconditionally. With 100+ cards: 30–80ms DOM thrash every tick; nukes `:hover` state.
  - Fix: stop calling `renderSeasonView` from the poller; update only badge/chip elements for matches whose status changed.

- [ ] **M17. `views.js` is now ~1700 lines and conceptually overloaded** — `js/views.js`
  - Season + game + match form + admin diagnostics renderers + score reveal + team stats. Admin renderers conceptually belong with `js/admin.js`.
  - Fix (low priority): split into `js/views.js` (public viewing) and `js/admin-views.js` (renderers consumed by admin shell). Pure file reorg.

---

## Minor (nice to have)

- [ ] **m1.** Env-var admin path checked before DB `enabled=0` — `auth.py:171`. If a deployer rotates `ADMIN_USER` to a name that exists as a *disabled* DB user, the disabled flag is bypassed. Document or guard.
- [ ] **m2.** Stale `upload_sessions` rows after server restart sit at `'active'` for 6h. Fix: on startup, mark active sessions older than chunk-idle threshold as `'cancelled'`.
- [ ] **m3.** `/api/uploads/sessions?status=...` accepts an unbounded comma-separated list — cap at ~8.
- [ ] **m4.** Stream block TTL uses wall-clock time (`time.time()`), not monotonic. NTP backward-jump can permanently strand a block.
- [ ] **m5.** HLS session keying by `(ip, ua)` permanently under-counts viewers behind carrier-grade NAT. Document, don't fix.
- [ ] **m6.** Defense-in-depth: add `.resolve()` containment checks on `serve_thumbnail` (`server.py:1752`) and `serve_logo` (`server.py:1725`).
- [ ] **m7.** 401-handling pattern repeats 6+ times across `views.js`/`live.js`/`admin.js`. Fix: a `fetchJson(url, opts)` helper handling 401/403 in one place.
- [ ] **m8.** `loadMatches` on transient network error sets `this.matches = []`, blanking the UI. Preserve previous list and surface a "couldn't refresh" toast.
- [ ] **m9.** History routing: `editMatch` silently no-ops if a deleted match is restored from history. Fall through to `showAdminView('matches')` if match is gone.
- [ ] **m10.** `team-stats-grid` sub-grid coupling with `grid-column: 1/-1` on inner children is implicit. Add a comment in the CSS block.

---

## Praise (genuinely good patterns worth keeping)

- **Test isolation in `tests/conftest.py`** — per-test monkeypatching of `DATA_DIR`/`DB_FILE`/`VIDEOS_DIR` plus token-list resets. Right way to write reliable tests for a stateful service.
- **`_sweep_orphaned_transcodes` on startup** (`server.py:196–219`) — explicit recovery for the asyncio-task-can't-survive-restart failure mode, with clear `error_code` and admin-visible recovery path.
- **`models.py` `extra="forbid"`** — typos in JSON return 422 instead of silent no-ops.
- **`PRIVATE_SETTING_KEYS = {"live_stream_key"}` plus `test_public_settings_never_exposes_stream_key`** — explicit allow-out filter pinned by a regression test.
- **`_range_file_response` cancellation** (`server.py:1593–1685`) — Range parsing, 416 on malformed, file-size clamping, cancel-event checks inside the iterator, `try/finally` unregister. Easy to get wrong; this is right.
- **HLS proxy header allowlist** (`live.py:322–327`) — only forwards `Range`/`If-Range`/`If-Modified-Since`/`If-None-Match`. Correct way to write a reverse proxy.
- **Comments that explain WHY, not WHAT** — e.g. `server.py:949–956` (`_raw.mp4` rename), `server.py:1085` (match-id timestamp+random suffix).
- **Mixin pattern with zero name collisions** across 8 mixins.
- **Legacy history-state forwarding** (`script.js:140–161`) — `view: 'add-match'` and `view: 'settings'` still resolve to the new dashboard.
- **`tests/test_streams.py`** — gold standard: `client_ip` precedence unit tests + integration tests + role-gating, all in one file.

---

## Open questions

1. **Deployment context** — is this only ever fronted by Cloudflare in production, or are there bare deployments? Decides whether M2/M3 are critical or defense-in-depth.
2. **Match scale** — what's the realistic ceiling for matches per season? <200 forever makes M6 minor; multi-season archives makes it critical.
3. **Multi-admin reality** — is concurrent admin editing actually a thing? Decides priority of M15.
4. **GPU operator visibility** — do you actually monitor logs, or only the admin dashboard? M12 only matters if the latter.

---

## Recommended sequencing

1. **This week:** C1, C2, C3, C4, C5, C6 — exploitable or actively corrupting on a busy day.
2. **Next sprint:** C7, M1, M4, M5, M7, M8, M13.
3. **When convenient:** the rest.
