# Phase 6d-1 — Unified Coach Review: Source Modes & Creation Routing

Screenshots captured via Playwright against a local dev server seeded with `docs/_seed/seed.py`.
Accounts used: `coach1` / `Replay!Demo123` (coach role), `family1` / `Replay!Demo123` (viewer role).

---

## Coach Review — mode toggle

| File | What it shows |
|------|---------------|
| `01-video-mode-dark.png` | Coach > Review, dark theme, **Video mode active**. The Video / Tactical Board pill toggle is visible below the sub-tab bar; Video is the active (highlighted) button. The picker bar (Match / Slot / Time / Save Note / Save Clip / Focus / Shortcuts), video area, and the note-composer right panel are all visible. |
| `02-tactical-board-mode-dark.png` | Coach > Review, dark theme, **Tactical Board mode active**. The Tactical Board button in the pill toggle is highlighted. The video area and picker bar are hidden; the observation fields and Save Observation button render in the right panel. The pitch board editor is below the fold at 900 px viewport height. |
| `12-video-mode-regression-check.png` | Coach > Review, dark theme — navigated to TB mode first, then switched back to **Video mode**. Confirms all video controls (picker bar, video area, telestrator, Save Note, Save Clip) are fully restored with no regression. |

---

## Coach > Notes — creation routing buttons

| File | What it shows |
|------|---------------|
| `03-notes-routing-buttons-dark.png` | Coach > Notes tab, dark theme. The header shows the **management-only list** of existing coaching notes (with "Open in Review", Edit, Delete actions per row), and the two creation-routing buttons top-right: **+ New observation** and **+ New note**. Neither opens an inline form — both route into Coach Review. |
| `11-notes-tab-dark.png` | Coach > Notes tab, dark theme — a second capture confirming the same layout with note rows visible (context pills, match/event metadata, thumbnails). |

---

## Creation routing round-trips

| File | What it shows |
|------|---------------|
| `04-new-note-routed-review-video.png` | Coach > Review after clicking **+ New note** from the Notes tab. Video mode is active: picker bar, video area, note-composer panel with template selector and player list are all present. |
| `05-new-obs-routed-review-board.png` | Coach > Review after clicking **+ New observation** from the Notes tab. Tactical Board mode is active: the picker bar/video area are hidden; the observation panel (observation-specific fields, Save Observation button) is visible in the right rail. |
| `06-new-clip-routed-review-video.png` | Coach > Review after clicking **+ New clip** from the Clips tab. Video mode is active with Save Note and Save Clip CTAs in the picker bar, identical to `04`. |

---

## Coach > Clips tab

| File | What it shows |
|------|---------------|
| `10-clips-tab-dark.png` | Coach > Clips tab, dark theme. The **management-only clip list** with existing clip rows (Preview, Edit, Delete actions per row) and a **+ New clip** button that routes into Coach Review rather than opening an inline form. |

---

## Coach > Roster tab

| File | What it shows |
|------|---------------|
| `07-roster-tab.png` | Coach > Roster tab, dark theme. KPI tile grid (Active players, Linked accounts, Without link, Avg notes/player), search + filter bar, and the player table with jersey badges, status pills, linked-account chips, and per-row action buttons including the "Add observation" clipboard icon. |
| `08-roster-add-obs-routed-board.png` | Coach > Review after clicking **"Add observation"** on a roster player row. Tactical Board mode is active with that player's checkbox pre-checked in the players list (visible in the right observation panel). |

---

## Observation form

| File | What it shows |
|------|---------------|
| `09-obs-form-filled.png` | Coach > Review, Tactical Board mode, observation fields fully filled: Event title ("Tuesday training — pressing shape"), Date (2026-05-07), Type (Practice), Observation title ("Compact block out of possession"), category (Shape), visibility (Private), linked players (Maya Chen, Liam O'Connor, Theo Bauer checked), tone chip (Correction selected), Player summary text. The **Save Observation** button is visible at the bottom of the right panel. |

---

## Light theme

| File | What it shows |
|------|---------------|
| `13-tactical-board-light-mode.png` | Coach > Review, **Tactical Board mode**, light theme. The mode toggle shows "Tactical Board" highlighted in teal/blue. The observation right panel renders with correctly themed inputs and background. |
| `14-video-mode-light-mode.png` | Coach > Review, **Video mode**, light theme. Picker bar, video area, telestrator toolbar and note-composer panel all render in light theme. |
| `15-notes-routing-light-mode.png` | Coach > Notes tab, light theme. The **+ New observation** and **+ New note** routing buttons are visible and correctly themed. |

---

## Viewer surface — privacy check

| File | What it shows |
|------|---------------|
| `16-viewer-my-feedback-notes.png` | My Feedback > Notes, logged in as `family1` (viewer). Note cards render with tone pills, player summary text, and Watch buttons. `coach_private_note` content is absent — it is scrubbed server-side by `_strip_private_fields()` and is not present in the viewer DOM. |

---

## Mobile (390 × 844 px)

| File | What it shows |
|------|---------------|
| `17-mobile-video-mode.png` | Coach > Review at 390 px wide, **Video mode**. The sub-tab row (Roster · Notes · Playlists · Clips · Review) is visible. The Video / Tactical Board pill toggle stacks cleanly. Picker bar controls (Match, Slot, Time, Save Note, Save Clip, Focus, Shortcuts) are each full-width with no horizontal overflow. |
| `18-mobile-tactical-board.png` | Coach > Review at 390 px wide, **Tactical Board mode**. The Tactical Board button in the pill is highlighted. Video controls are hidden. The mobile layout has no overflow. |
| `19-mobile-notes-routing.png` | Coach > Notes at 390 px wide. The note list header shows **+ New observation** and **+ New note** routing buttons, both accessible and readable at narrow width. |
