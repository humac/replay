# Phase 6b — Coach observation composer screenshots

Captured against the live dev server at `http://localhost:8090` using Playwright.
The page is seeded with a synthetic `_coachBundle` (3 sample players + a small mix
of video and observation notes) so the screenshots showcase the new UI states
without depending on user-specific seed data. No real backend writes — these are
DOM-only renders of production code paths.

| File | Surface | What it shows |
| --- | --- | --- |
| `01-roster.png` | Coach > Roster (dark) | Roster table with the new clipboard-icon "Add observation" action on every row, alongside the existing chart / link / edit / trash icons. |
| `02-composer-from-roster.png` | Observation composer (dark) | New observation modal opened from a Roster row. Player is preselected (#7 Sample Player); visibility defaults to **Player/Family**. Helper paragraph at the top explains the surface. |
| `03-notes-list.png` | Coach > Notes (dark) | Notes list rendering both Video and Observation rows. Per-row context pill differentiates them; observation rows show event metadata (`Practice observation · Tuesday practice — scanning · 2026-05-05`) instead of `matchLabel · timestamp · slot`, render the clipboard placeholder tile, and suppress "Open in Review" + "Regenerate thumbnail". |
| `04-edit-observation.png` | Edit observation modal (dark) | Editing an existing observation note. Event title / event date / event type round-trip; structured fields (player summary, what happened, why it matters, what to do next) all populated from the seeded note. |
| `05-composer-from-notes.png` | Observation composer (dark) | New observation opened from Coach > Notes "+ New observation" button. No player preselected; visibility defaults to **Team-visible**. |
| `01-roster-light.png` | Coach > Roster (light) | Light-mode parity for the Roster surface. |
| `02-composer-from-roster-light.png` | Observation composer (light) | Light-mode composer with player preselected. |
| `03-notes-list-light.png` | Coach > Notes (light) | Light-mode notes list with mixed contexts. |
| `04-edit-observation-light.png` | Edit modal (light) | Light-mode edit. |
| `05-composer-from-notes-light.png` | Composer (light) | Light-mode "+ New observation" entry. |
| `06-composer-mobile-390.png` | Composer @ 390 px (dark) | Mobile width — event metadata row collapses to a single column, form remains usable. |
| `07-notes-list-mobile-390.png` | Notes list @ 390 px (dark) | Mobile width — observation rows still show context pill + event metadata cleanly. |

## What these screenshots prove

- **Two entry points wire correctly.** Roster's clipboard icon and Notes' "+ New observation" button both open the same template; the only behavioural difference is `playerId` preselection + `visibility` default (player vs team).
- **Observation composer reuses every structured field** but swaps match/slot/time for event metadata; helper text is unmistakable.
- **Coach > Notes never shows `null` / `undefined` / `0:00`** for observation rows. Per-context meta line + clipboard placeholder ensure the row is readable.
- **Edit support round-trips event_title / event_date / event_type** without losing the note's structured fields.
- **Light + dark themes** both render with sufficient contrast — context pills, helper paragraph, and clipboard placeholder tile all carry theme-aware overrides in `styles.css`.
- **Mobile @ 390 px** drops the event metadata grid to a single column so the date input stays usable.

## How to regenerate

The Playwright capture script lives at `/tmp/capture_phase6b.py` (regenerate from
the project history if needed). It seeds `_coachBundle` via `page.evaluate` and
calls the existing renderers (`app.renderCoachRoster()`, `app.renderCoachNotes()`,
`app.openCoachObservationModal(...)`) so the screenshots reflect production code,
not mocked markup. Run with the dev server up:

```bash
python3 -m playwright install chromium  # once
python3 /tmp/capture_phase6b.py
```
