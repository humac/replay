# Phase 6d-1 — Unified Coach Review: Source Modes & Creation Routing

Screenshots captured via Playwright against a local dev server seeded with `docs/_seed/seed.py`
(accounts: `coach1` / `Replay!Demo123`, `family1` / `Replay!Demo123`).

---

## Mode toggle & Video mode

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `01-video-mode-dark.png` | Baseline state | Coach > Review, dark theme | Mode toggle renders with **Video** button active (sky-blue pill), picker bar + video grid visible, Tactical Board workspace hidden |
| `01-coach-review-video-mode-dark.png` | Video mode alt capture | Coach > Review, dark theme | Duplicate capture confirming picker bar, match/slot selectors, telestrator toolbar, Save Note + Save Clip CTAs all present in Video mode |
| `12-video-mode-regression-check.png` | Regression | Coach > Review, dark theme | After switching modes, switching back to Video shows all original controls unchanged — no regression from TB mode introduction |

---

## Tactical Board mode

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `02-tactical-board-mode-dark.png` | TB mode active | Coach > Review, dark theme | **Tactical Board** toggle button is active (pressed), board workspace is visible, picker bar + video grid are hidden, tone chips + observation fields render in the right rail |
| `13-tactical-board-light-mode.png` | Light theme | Coach > Review, light theme | Same layout readable in light mode — no contrast issues, correct background/border tokens |
| `18-mobile-tactical-board.png` | Mobile | Coach > Review, 390 px wide | Board workspace collapses to single-column, observation fields stack full-width, no horizontal scroll |

---

## Notes tab routing buttons

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `03-notes-routing-buttons-dark.png` | Button layout | Coach > Notes, dark theme | Both `+ New note` and `+ New observation` buttons present in the Notes tab header; Note list is management-only (no inline form) |
| `15-notes-routing-light-mode.png` | Light theme | Coach > Notes, light theme | Same routing buttons readable in light theme |
| `19-mobile-notes-routing.png` | Mobile | Coach > Notes, 390 px wide | Routing buttons stack cleanly at narrow width |

---

## Creation routing round-trips

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `04-new-note-routed-review-video.png` | `+ New note` → Video | Coach > Review after routing | Clicking `+ New note` from Coach > Notes lands in Review with **Video** mode active — mode toggle, picker bar, and video grid all present |
| `05-new-obs-routed-review-board.png` | `+ New observation` → TB | Coach > Review after routing | Clicking `+ New observation` from Coach > Notes lands in Review with **Tactical Board** mode active — board workspace visible, observation fields ready |
| `06-new-clip-routed-review-video.png` | `+ New clip` → Video | Coach > Review after routing | Clicking `+ New clip` from Coach > Clips lands in Review with **Video** mode active |

---

## Roster tab

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `07-roster-tab.png` | Roster list | Coach > Roster, dark theme | Roster table renders with player rows visible |
| `08-roster-no-obs-btns.png` | Roster (headless capture) | Coach > Roster | Intermediate capture during headless QA — confirms Roster renders when bundle players are loaded |
| `08-roster-obs-player-preselected.png` | Player preselect | Coach > Review after Roster routing | When "Add observation" is triggered for a player from the Roster tab, Review opens in Tactical Board mode with that player's checkbox pre-checked in the `cr-obs-players` checklist |

---

## Observation save flow

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `09-obs-form-filled.png` | Filled observation | Coach > Review, TB mode | Observation fields filled (event title, date, type, title, tone, player summary) before clicking Save Observation |
| `10-obs-saved-feedback.png` | Save confirmation | Coach > Review after save | Success toast appears; fields are cleared / reset after save |
| `11-obs-in-notes-list.png` | Note appears | Coach > Notes list | Newly saved observation appears in the Notes list with an "Observation" context pill |

---

## Viewer privacy

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `16-viewer-my-feedback-notes.png` | Viewer surface | My Feedback > Notes, family1 account | `coach_private_note` text is not present in the viewer-facing note body — server scrubs it via `_strip_private_fields()` |

---

## Mobile (390 px)

| File | Role | Surface | What it proves |
|------|------|---------|----------------|
| `17-mobile-video-mode.png` | Video mode | Coach > Review, 390 px | Mode toggle + review controls stack without horizontal overflow |
| `18-mobile-tactical-board.png` | TB mode | Coach > Review, 390 px | Board workspace collapses to single column, fields full-width |
| `19-mobile-notes-routing.png` | Notes routing | Coach > Notes, 390 px | Routing buttons accessible at narrow width |
