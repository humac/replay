# Phase 4e — Clip-specific thumbnail screenshots

Captured against `http://localhost:8090` with the Phase 4e backend live
and the seeded demo data (`docs/_seed/seed.py`, password
`Replay!Demo123`). The capture script is [`_capture.py`](./_capture.py)
— re-run any time after the demo seed:

```bash
python3 docs/screenshots/phase-4e-clip-thumbnails/_capture.py
```

The "color-bar" imagery in the tiles is the SMPTE test pattern from the
seeded mock first-half MP4 (`docs/_seed/videos/mock_first_half.mp4`) —
in production the tiles show real frames extracted by ffmpeg at each
clip's `start_seconds`.

## Pre-conditions

Before re-running the capture script, four clips need to exist on the
seeded "Riverside FC vs Northgate United" match (the only seeded match
with a playable source MP4) plus one clip on a match WITHOUT a source
video. Easiest path while logged in as `coach1` in the dev console:

```js
const matchId = '<id from /api/matches where home=Riverside, away=Northgate>';
const noSrcMatch = '<id of any other seeded match>';
for (const spec of [
  {match_id: matchId, slot: 'first_half', start: 4,  end: 12, title: 'Phase 4e — clip-specific thumbnail (no source note)', vis: 'team'},
  {match_id: matchId, slot: 'first_half', start: 8,  end: 18, title: 'Phase 4e — clip-specific thumbnail (team)',           vis: 'team'},
  {match_id: matchId, slot: 'first_half', start: 14, end: 24, title: 'Phase 4e — private clip (coach-only)',                vis: 'private'},
  {match_id: noSrcMatch, slot: 'full',    start: 0,  end: 10, title: 'Phase 4e — placeholder demo (no source video)',       vis: 'team'},
]) {
  await fetch('/api/coach/clips', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + app.authToken}, body: JSON.stringify({match_id: spec.match_id, slot: spec.slot, start_seconds: spec.start, end_seconds: spec.end, title: spec.title, description: '', category: 'shape', visibility: spec.vis})});
}
```

## Inventory

| File | Role | What it proves | Thumbnail source |
|---|---|---|---|
| `01-coach-clips-dark.png` | coach1 (coach) | Coach > Clips dark mode — three clips show real frames extracted at their `start_seconds`; the no-source-video clip shows the placeholder. Confirms the new GET endpoint serves the JPEG `_spawn_coach_clip_thumbnail` produced. | clip-specific (3 of 4); placeholder for the no-source clip |
| `02-coach-clips-light.png` | coach1 (coach) | Same surface in `data-theme="light"` mode — themed correctly, no native browser chrome. Same four clips, same thumbnails. | clip-specific (3 of 4); placeholder for the no-source clip |
| `03-my-feedback-clips-desktop.png` | family1 (viewer) | My Feedback > Clips shows ONLY the three TEAM-visible clips — the PRIVATE clip 11 has been correctly filtered out by `_filter_clips_for_user`. Card layout is thumbnail-left, content-right. | clip-specific for clips 9 + 10; placeholder for clip 12 |
| `04-my-feedback-clips-mobile.png` | family1 (viewer) | Same surface at iPhone 14 width (390 × 844). Thumbnail stacks above the card body per the existing 720 px breakpoint. Frame is scrolled to show real clip-specific thumbnails (placeholder card is in #5). | clip-specific |
| `05-placeholder-demo.png` | coach1 (coach) | Coach > Clips with the "Phase 4e — placeholder demo (no source video)" clip in view — the clip's match has no playable MP4, so the GET endpoint returns 404 and `_coachClipThumbHtml` keeps the placeholder tile. Locks in the empty-state visual. | placeholder (intentional — no source video) |

## Demo clip ladder (matches the screenshots)

| id | match | window | source_note_id | visibility | thumbnail behaviour |
|---|---|---|---|---|---|
| 9  | Riverside vs Northgate (1H) | 0:04–0:12 | null | team    | clip JPEG at 4 s — no source note required |
| 10 | Riverside vs Northgate (1H) | 0:08–0:18 | null | team    | clip JPEG at 8 s |
| 11 | Riverside vs Northgate (1H) | 0:14–0:24 | null | private | clip JPEG at 14 s — coach-only; `family1` 404s |
| 12 | Coastal vs Riverside (full) | 0:00–0:10 | null | team    | placeholder always — match has no playable MP4 |

## Network evidence

While the page renders, every visible clip card kicks off one
auth-bearing `GET /api/coach/clips/{id}/thumbnail` via
`mountCoachClipThumbnailsIn`:

```
coach1 view:
  GET /api/coach/clips/9/thumbnail   → 200 image/jpeg   (clip-specific JPEG)
  GET /api/coach/clips/10/thumbnail  → 200 image/jpeg   (clip-specific JPEG)
  GET /api/coach/clips/11/thumbnail  → 200 image/jpeg   (private — coach OK)
  GET /api/coach/clips/12/thumbnail  → 404              (no source video)

family1 view:
  GET /api/coach/clips/9/thumbnail   → 200 image/jpeg
  GET /api/coach/clips/10/thumbnail  → 200 image/jpeg
  GET /api/coach/clips/11/thumbnail  → 404              (private — viewer blocked)
  GET /api/coach/clips/12/thumbnail  → 404              (no source video)
```

The privacy invariant is enforced server-side via `_can_view_coach_clip`
(reuses `_filter_clips_for_user`), so a viewer who can't see a clip
gets the same 404 they'd get for "clip doesn't exist" — they cannot
probe whether private clips exist.

## Manual regenerate

Confirmed end-to-end against the live server:

```
POST /api/coach/clips/9/thumbnail/regenerate (coach1) → 200 {ok: true,  generated: true}
POST /api/coach/clips/9/thumbnail/regenerate (family1) → 403            (viewer blocked)
```

## Regression smoke (post-Phase-4e)

After Phase 4e went live the existing playback paths stayed clean:

- **Clip playback** (`openFeedbackClip(9)`) — modal opens, `feedback-player-video` loads HLS for the source match, `currentTime` snaps to `start_seconds = 4`, `readyState = 4`.
- **Note playback** (`openFeedbackNote(23)`) — modal opens, video loads from `/api/matches/.../video/first_half`, `readyState = 4`.
- **Playlist playback** (`openFeedbackPlaylist(8)`) — "First-half tactical lessons" playlist with two notes; modal opens, first item's video loads, `readyState = 4`.

No new errors in the browser console for any of the three flows.
