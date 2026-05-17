# Phase 5b — Player Development UI screenshots

Screenshots captured against the local dev server (`localhost:8091`) with
the dev seed roster (see `docs/_seed/seed.py`). Coach surface is rendered
via the `View development profile` action on the Coach > Roster table; the
viewer surface is the new `Development` sub-tab in `My Feedback`.

| File | Role | Theme | What it proves |
| --- | --- | --- | --- |
| `01-coach-desktop-dark.png` | coach (admin) | dark | Coach development profile modal renders header, Summary tiles, Themes section (positives/corrections, top categories, top tags), and the labelled "Suggested focus areas from recent notes" section against the roster table backdrop. **Data is the FULL coach payload** — no `coach_private_note` text is shown in the UI but the coach endpoint returns it. |
| `02-coach-desktop-light.png` | coach (admin) | light | Same coach modal in light theme — borders, chip backgrounds, focus-area tinting all readable. Refreshed after the review-fix pass added explicit `[data-theme="light"]` overrides for tone/tag chips, the `.player-dev-jersey` badge, and the `.player-dev-note-next` "what to do next" blocks; coach surface also gained a Recent playlists Preview button (reuses `previewCoachPlaylist`, no new playback code). |
| `03-feedback-desktop-dark.png` | viewer (family1) | dark | My Feedback > Development tab. Linked-player chip selector (#7 Alex, #14 Riley), player header, Summary tiles (no "Themes" — coach-only), Focus areas section, Recent positives card with note thumbnail, empty Recent things to work on / clips, Recent playlists with Play session button. **Data is viewer-filtered** — `coach_private_note` was scrubbed server-side before reaching the client. |
| `03b-feedback-desktop-light.png` | viewer (family1) | light | Same viewer surface in light theme. |
| `04-feedback-mobile-dark.png` | viewer (family1) | dark | 390 × 844 (iPhone 14 Pro width). Tile grid collapses to two columns; header chips, recent positives card, recent playlists row all stay scannable; Play session button is full-width. |
| `05-coach-empty-state.png` | coach (admin) | dark | Coach modal for a player with no coaching activity yet — empty-state collapse renders the friendly "No coaching activity for this player yet." message instead of seven empty section cards. |

The Phase 5a backend endpoints `GET /api/coach/players/{id}/development`
and `GET /api/my-feedback/players/{id}/development` are unchanged in
this phase; the UI just consumes them through the new
`getCoachPlayerDevelopment` / `getMyPlayerDevelopment` helpers in
`js/api.js`.
