# Phase 6e — Unified Viewer Review Modal

Screenshots demonstrating the **unified viewer review modal** on the
`/feedback` (My Feedback) surface. A player or family viewer can click
any visible note, observation, tactical-board observation, or clip
card and the SAME modal opens for all four — the focused-feedback
player. Cards stay compact (no inline summary, no inline tactical
board, no inline action buttons); the detail layout lives inside the
playback modal so the reading experience is identical across review
types.

## Behaviour

- **Cards** = compact preview only: thumbnail + tone pill + title +
  meta (match · timestamp for video, event type · date for
  observations, match · clip window for clips). Clicking the card body
  opens the unified modal. No inline boards, no inline summary lines,
  no per-card action buttons.
- **Modal** = focused feedback player (`#feedback-player-template`):
  - Video notes / clips → `<video>` plays HLS with the existing
    telestrator overlay.
  - Observation notes → the `<video>` is hidden and the read-only
    tactical board renders in the same slot (when present).
  - The `[data-field="body"]` slot below the visual carries one shared
    structured-field layout for every review type (context pill +
    category + linked players + Summary + What happened / Why / Next
    + Additional detail + tags).
- **Mark reviewed** lives in the modal action row for notes
  (clips have no review backend yet, so the confirm button is hidden
  and Close is the only action).
- **Player Development** rows route into the same modal, so a viewer
  reading the development profile gets the identical reading layout.

## How to reproduce

1. Seed the docs data dir (idempotent):

    ```bash
    set -a && source .env.local && set +a
    rm -rf /tmp/replay-docs-data
    REPLAY_DATA_DIR=/tmp/replay-docs-data python3 docs/_seed/seed.py
    ```

   Or use the user's existing dev DB at `~/replay-data/replay.db`. Both
   seed paths produce a `family1` viewer linked to roster #7 (Alex Park)
   with at least one visible video note, one tactical-board
   observation, and one clip.

2. Start the dev server on port 8090 (or use the Claude Code preview
   server):

    ```bash
    set -a && source .env.local && set +a && python3 server.py
    ```

3. From the repo root, run the capture:

    ```bash
    cd tests/e2e && npm run capture-phase-6e
    ```

   The spec runs serially (`workers=1`) to avoid the per-IP login rate
   limit. It logs in as the seeded `family1` (password
   `Replay!Demo123`).

## Captures

| Filename | Surface | Account / role | What it proves |
|---|---|---|---|
| `01-notes-tab-compact-cards.png` | `/feedback?tab=notes` | `family1` viewer | Notes tab renders compact cards uniformly across video / observation / tactical-board contexts. No inline boards, no inline summary, no per-card action buttons. |
| `02-video-note-unified-modal.png` | Unified review modal — video note | `family1` viewer | The focused-feedback player IS the detail surface. Video on top with telestration; structured fields (context pill / linked player / Summary / Additional detail) below in one shared layout. |
| `04-tactical-board-observation-unified-modal.png` | Unified review modal — tactical-board observation | `family1` viewer | Same modal — the tactical board renders where the video would be. Same structured-field layout below. Modal title reflects observation context ("Practice observation"). |
| `05-clips-tab-compact-cards.png` | `/feedback?tab=clips` | `family1` viewer | Clip cards mirror the note-card density: thumb + clip pill + title + meta. No inline description, no per-card buttons. |
| `06-clip-unified-modal.png` | Unified review modal — clip | `family1` viewer | Clip detail = same focused player + same structured-field layout below. Mark reviewed is hidden because clips have no review backend; Close is the only action. |
| `07-development-tab-recent-items.png` | `/feedback?tab=development` | `family1` viewer | Development profile recent rows route into the SAME unified modal, so the reading experience matches the Notes / Clips tabs. |
| `08-mobile-390-observation-unified-modal.png` | Unified review modal at 390 px | `family1` viewer | Modal collapses cleanly on mobile. Board stays full-width above the fields. |
| `09-light-mode-video-note-unified-modal.png` | Unified review modal — light theme | `family1` viewer | Same modal under `[data-theme="light"]`. |

> The "observation note (no board)" capture (test 03 in the spec) is
> conditional: it skips cleanly when the seeded DB only has tactical-
> board observations on the player-visible tier. To produce it, reseed
> against `/tmp/replay-docs-data` (which adds the text-only
> *Tuesday practice — 1v1 defending* observation) and re-run the
> capture.

## Seeded data assumptions

- `family1` is linked to roster #7 (Alex Park).
- At least one player-visible video note (e.g. *Player #7 — defensive recovery*).
- At least one player-visible tactical-board observation (e.g. *Tactical sketch for Alex* / *Smoke — visible observation*).
- At least one team-visible coaching clip from a Riverside FC match.
- The seed scripts at `docs/_seed/seed.py` carry `coach_private_note`
  canary text for the privacy assertion.

## Privacy invariants exercised

- Capture spec test 10 parses the raw `/api/my-feedback` JSON response
  AND every unified modal HTML and asserts the `coach_private_note`
  canary text never appears.
- All visibility filtering remains server-side
  (`_filter_notes_for_user` / `_filter_clips_for_user`). No
  client-side authorization logic was added in Phase 6e.
- `tactical_board_json` follows the parent note's visibility — when a
  board reaches the unified modal the parent note is visible.
