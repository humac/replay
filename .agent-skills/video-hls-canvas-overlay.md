# Video, HLS, and canvas overlay

## Purpose

Keep the Coach Review drawing canvas perfectly aligned over the `<video>` element through
HLS startup, seeks, freeze-frame paints, layout changes, focus-mode toggles, and viewport
resizes. The canvas IS the telestration surface — alignment drift = misplaced arrows on
players.

## When to use it

- Any sprint that changes the Review video element, its wrapper, the surrounding grid, or
  the inspector's overflow behavior (Sprints 1, 2, 5, 6, 8).
- Any change to `loadCoachReviewVideo`, `setupCoachCanvas`, `_resizeCoachCanvas`,
  `paintCoachCanvas`, or `renderCoachDrawing`.
- Adding a new playback surface (don't add one — the modal in `feedback-player-template`
  already exists for the player path).

## Key repo files

- `js/player.js`
  - `getStreamUrls(matchId, slot)` (~line 299) — returns `{ hlsUrl, mp4Url }`.
  - `loadPlaybackSource(video, hlsUrl, mp4Url, token)` — handles HLS.js, native HLS, MP4
    fallback, and `_playRequestToken` cancellation.
  - HLS.js init (~lines 320–340) and event wiring.
- `js/coaching.js`
  - `loadCoachReviewVideo(matchId, slot, seekTo, drawing)` (~line 574) — entry point.
  - `setupCoachCanvas` / `_resizeCoachCanvas` / `paintCoachCanvas` (~lines 733–790).
  - `renderCoachDrawing(drawing)` — applies a saved drawing to the current canvas state.
  - `normalizeCoachDrawing(drawing)` — v1→v2 migration in-memory.
  - `teardownCoachCanvasListeners(canvasId)` — removes `window.resize` listener for disposable
    canvases (the modal one).
- `index.html` — `<video id="coach-review-video">` inside `.player-wrapper.coach-review-wrapper`
  and `<canvas id="coach-drawing-canvas">` overlay.

## How it works today

```
loadCoachReviewVideo(matchId, slot, seekTo, drawing)
   ├─ getStreamUrls() → { hlsUrl, mp4Url }
   ├─ loadPlaybackSource(video, hlsUrl, mp4Url, token)
   ├─ video.addEventListener('loadedmetadata', repaint)   (one-shot)
   ├─ if (seekTo) video.currentTime = seekTo
   └─ if (drawing) renderCoachDrawing(drawing)

setupCoachCanvas()
   ├─ window.addEventListener('resize', resize)
   ├─ video.addEventListener('loadedmetadata', resize)
   ├─ canvas pointer{down,move,up,leave} → coachDraw{Start,Move,End}
   └─ initial resize() call

_resizeCoachCanvas(canvas, video)
   ├─ rect = video.getBoundingClientRect()
   ├─ canvas.width  = round(rect.width)
   ├─ canvas.height = round(rect.height)
   └─ paintCoachCanvas()
```

The bitmap dimensions of the canvas track the displayed pixel size of the video. Drawing
objects (v2) are stored in **normalized 0..1 coordinates** so they survive resize.

## Assumptions about playback

- HLS.js when `window.Hls` is loaded and the browser doesn't natively support HLS.
- Native HLS via `<video src="…m3u8">` on Safari / iOS.
- MP4 fallback via `mp4Url` if HLS init throws.
- Reverse-proxy serves segments directly under `/api/matches/{id}/hls/{slot}/...` — see
  `Caddyfile` and `CLAUDE.md`.
- VOD playback heartbeat: `js/player.js` posts to `/api/matches/{id}/heartbeat?slot=…` every
  10 s while the **public** match player is active. Coach Review uses the same `<video>`
  element pattern but does **not** need the heartbeat (the coach is authenticated as
  coach/admin and the registry treats them as staff). Don't add a heartbeat to the Review
  video.

## Required event coverage

Every layout / lifecycle change must keep these wired:

| Event | What must happen |
|---|---|
| `loadedmetadata` | Resize canvas to current video bounding rect; repaint last drawing. |
| `seeked` | Repaint drawing — drawings are freeze-frame overlays; clearing them is a bug. |
| `timeupdate` | (Sprint 2) update the current-time readout in the top bar. |
| `play` / `pause` | (Sprint 7) update keyboard-shortcut visual state. |
| `error` | Surface a friendly empty-state in `#coach-review-empty`; do not silently fail. |
| window `resize` | Re-run `_resizeCoachCanvas`. |
| **wrapper resize** | (Sprint 1+) `ResizeObserver` on `.coach-review-wrapper` — see below. |

### Sprint 1 caveat: ResizeObserver

Once the right inspector is independently scrollable (Sprint 1), the **wrapper** can change
size without `window` resizing — for example, the inspector growing pushes the side column
which shrinks the video column without a window event. Add a `ResizeObserver` on the wrapper
in `setupCoachCanvas`:

```js
const wrapper = video.closest('.coach-review-wrapper');
const ro = new ResizeObserver(() => this._resizeCoachCanvas(canvas, video));
ro.observe(wrapper);
canvas._coachResizeObserver = ro;
```

And tear it down in `teardownCoachCanvasListeners` alongside the existing `window.resize`
removal.

## Constraints

- **Do not burn drawings into MP4.** Drawings are JSON metadata on `coaching_notes`. There
  is no future `clip-export` feature in scope here. If a sprint suggests "render to video",
  stop and confirm.
- **Preserve v1 + v2 + formation rendering.**
  - v1: legacy `{ strokes: [...] }` payloads — render via the v1→v2 in-memory migration in
    `normalizeCoachDrawing`.
  - v2: `{ version: 2, objects: [...] }` with types `freehand|arrow|circle|zone|label|spotlight|dim|formation`.
  - `formation` carries 3–16 anchors in 0..1 coordinates plus a `hull_points` polygon.
    The painter mirrors the spotlight `destination-out` cutout. Backend validates 3–16 in
    `models.py`; frontend rejects collinear anchors before save.
- **Do not destroy the global HLS instance.** Coach Review owns its own `<video>`; the
  public match page owns `app.hlsPlayer`. Tearing the wrong one down breaks the other view.
- **Do not change `getStreamUrls` / `loadPlaybackSource` signatures.** Other callers
  (`/feedback` modal, public match) depend on them.
- **Do not modify the Caddy HLS routing or cache headers.** `Caddyfile` and `live.py` must
  stay aligned (playlists `max-age=60`, segments `immutable`).

## Commands / checks to run

```bash
# Verify the canvas event coverage
rg -n "loadedmetadata|seeked|timeupdate|_resizeCoachCanvas|ResizeObserver" js/

# Find every place a Review-area video element is referenced
rg -n "_coachVideoId|coach-review-video" js/ index.html styles.css

# Check that drawing v1/v2/formation paths exist
rg -n "normalizeCoachDrawing|version:\s*2|hull_points|formation" js/coaching.js

# Verify HLS lifecycle is intact after edits
node --check js/player.js js/coaching.js
```

Manual check after a layout change:

1. Open `/coach?tab=review&match=<id>&slot=full`.
2. Activate the canvas, draw a freehand line over a player.
3. Drag the browser to 1024 / 1440 / 1920 px widths.
4. Open / close the inspector (Sprint 6 focus mode).
5. Seek backward 10 s and forward 10 s.
6. The drawing must remain pixel-aligned in every state.

## Common failure modes

- **Canvas drift after Sprint 1.** Wrapper resizes without `window.resize` firing → canvas
  bitmap stale. Add the `ResizeObserver` described above.
- **Painting before `loadedmetadata`.** `getBoundingClientRect()` returns zeros until the
  video has dimensions. Always paint inside or after the `loadedmetadata` listener.
- **Clearing the drawing on `seeked`.** Drawings are freeze-frame metadata — repaint, don't
  clear.
- **Tearing down the wrong canvas.** The Review canvas is **persistent** (lives in the
  DOM); the modal canvas in `feedback-player-template` is **disposable**. Only the modal
  one should run `teardownCoachCanvasListeners`.
- **Memory leak.** A `ResizeObserver` not stored on the canvas (or not disconnected) keeps
  references alive. Always store a reference and disconnect on teardown.
- **Heartbeat 403 on Review.** Don't add a heartbeat — only the public match player needs
  it. If you copy public-match playback code into a new surface, strip the heartbeat first.

## Done criteria

- After resize from 390 → 1920 px, canvas dimensions match the video rect within 1 px.
- After seeking 10 s back/forward, the saved drawing renders identical pixels.
- After leaving and re-entering the Review tab, no leaked listeners (check
  `getEventListeners(window)` in DevTools — should not grow per visit).
- v1, v2, and formation drawings all render. Loading a v1 record does not raise.
- Public `/match/{slug}` HLS playback unchanged.
