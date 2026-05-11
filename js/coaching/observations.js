// Coaching observations domain mixin (PR-FE 6/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.

import { NOTE_TYPES, DEFAULT_NOTE_TYPE } from '../coaching.js';

export const coachingObservationsMixin = {
    /** Phase 6b — observation note composer.
     *
     *  Opens a text-only note editor. Reuses every structured field
     *  from the video-note modal but swaps the match/slot/time row
     *  for `event_title` / `event_date` / `event_type` and drops the
     *  hard "title required" check — observation notes can be saved
     *  with just `event_title` + structured fields when no overall
     *  title makes sense (Phase 6b #113).
     *
     *  Two entry points:
     *    Coach > Roster icon button → `openCoachObservationModal(null,
     *      { playerId })` preselects the player and defaults
     *      visibility to "player".
     *    Coach > Notes "+ New observation" → `openCoachObservationModal()`
     *      with no preselection; visibility defaults to "team".
     *
     *  Edit path: `openCoachObservationModal(noteId)` reuses the same
     *  modal so a coach can iterate on an existing observation.
     *  `openCoachNoteModal` dispatches to this when called with an
     *  observation note id so the video-shaped modal isn't forced on
     *  a text-only row.
     */
    async openCoachObservationModal(noteId = null, { playerId = null } = {}) {
        const note = noteId
            ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId))
            : null;
        if (noteId && !note) {
            this.showError('Observation note not found.');
            return;
        }
        const tpl = document.getElementById('coach-observation-form-template');
        if (!tpl) { this.showError('Observation form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Event metadata.
        body.querySelector('[data-field="event_title"]').value = note?.event_title || '';
        body.querySelector('[data-field="event_date"]').value = note?.event_date || '';
        const eventTypeSel = body.querySelector('[data-field="event_type"]');
        eventTypeSel.value = note?.event_type || '';

        // Shared structured-note fields.
        body.querySelector('[data-field="title"]').value = note?.title || '';
        body.querySelector('[data-field="category"]').value = note?.category || 'other';
        // Visibility default — preselected-player flow leans toward
        // "player" (the coach is writing FOR that player); the Notes-
        // tab "+ New observation" flow has no player context so
        // default to "team".
        const defaultVisibility = note?.visibility
            || (playerId ? 'player' : 'team');
        body.querySelector('[data-field="visibility"]').value = defaultVisibility;
        body.querySelector('[data-field="body"]').value = note?.body || '';
        body.querySelector('[data-field="tags"]').value = (note?.tags || []).join(',');

        // Tone radiogroup — same chip set + a11y wiring as the video
        // note modal so keyboard navigation feels consistent.
        const initialNoteType = note?.note_type || DEFAULT_NOTE_TYPE;
        const toneBox = body.querySelector('[data-field="note_type"]');
        toneBox.dataset.value = initialNoteType;
        toneBox.innerHTML = NOTE_TYPES.map(([v, l, glyph]) => `
            <button type="button" class="coach-review-tone-btn${v === initialNoteType ? ' is-active' : ''}" role="radio" aria-checked="${v === initialNoteType}" tabindex="${v === initialNoteType ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}">
                <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                <span class="coach-review-tone-label">${this.esc(l)}</span>
            </button>
        `).join('');
        toneBox.addEventListener('click', (event) => {
            const btn = event.target.closest('.coach-review-tone-btn');
            if (!btn || !toneBox.contains(btn)) return;
            this._syncToneRadiogroup(toneBox, btn.dataset.noteType);
        });
        this._setupToneRadiogroup(toneBox);

        body.querySelector('[data-field="player_summary"]').value = note?.player_summary || '';
        body.querySelector('[data-field="what_happened"]').value = note?.what_happened || '';
        body.querySelector('[data-field="why_it_matters"]').value = note?.why_it_matters || '';
        body.querySelector('[data-field="what_to_do_next"]').value = note?.what_to_do_next || '';
        body.querySelector('[data-field="coach_private_note"]').value = note?.coach_private_note || '';

        // Players: render the same checklist as the video note modal.
        // Preselect via three sources, in priority order:
        //   1. existing note's player_ids (edit path)
        //   2. explicit playerId arg (Roster entry point)
        //   3. nothing (Notes-tab "New observation" entry point)
        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        const preselected = new Set();
        if (note?.player_ids?.length) {
            note.player_ids.forEach((id) => preselected.add(String(id)));
        } else if (playerId) {
            preselected.add(String(playerId));
        }
        if (preselected.size) {
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (preselected.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        // Phase 6c — tactical board section. The composer carries the
        // current board JSON in a closure variable; the inline editor
        // mounted into [data-field="tactical_board_section"] reads /
        // writes through getBoard / setBoard. On submit we send the
        // latest value so the editor's saved scene round-trips on
        // create AND on edit (and a removed board sends `null` so the
        // backend clears the column).
        let currentBoard = (note?.tactical_board_json && typeof note.tactical_board_json === 'object')
            ? note.tactical_board_json
            : null;
        const boardContainer = body.querySelector('[data-field="tactical_board_section"]');
        if (boardContainer) {
            this.mountTacticalBoardSection(boardContainer, {
                initialBoard: currentBoard,
                getBoard: () => currentBoard,
                setBoard: (next) => { currentBoard = next; },
            });
        }

        const result = await this.formModal({
            title: note ? 'Edit Observation' : 'New Observation',
            kicker: 'Coach observation',
            body,
            confirmLabel: note ? 'Save changes' : 'Save observation',
            // Phase 6c — `wide-board` is a scoped wider variant for
            // the observation composer that hosts the tactical board
            // editor. The shared `wide` size stays 720 px so Player
            // Development + focused Feedback player don't get widened.
            size: 'wide-board',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                const eventTitleVal = root.querySelector('[data-field="event_title"]').value.trim();
                const playerSummaryVal = root.querySelector('[data-field="player_summary"]').value.trim();
                const whatHappenedVal = root.querySelector('[data-field="what_happened"]').value.trim();
                const whyMattersVal = root.querySelector('[data-field="why_it_matters"]').value.trim();
                const whatToDoVal = root.querySelector('[data-field="what_to_do_next"]').value.trim();
                const bodyVal = root.querySelector('[data-field="body"]').value.trim();
                const hasBoardNow = this.tacticalBoardHasContent(currentBoard);
                // Mirror the backend's meaningful-content rule so the
                // coach gets a clear inline message instead of a 422.
                const meaningful = titleVal || eventTitleVal || playerSummaryVal
                    || whatHappenedVal || whyMattersVal || whatToDoVal || bodyVal
                    || hasBoardNow;
                if (!meaningful) {
                    this.showError('Observation needs at least a title, event title, or some content.');
                    return;
                }
                close({
                    note_context: 'observation',
                    title: titleVal,
                    event_title: eventTitleVal,
                    event_date: root.querySelector('[data-field="event_date"]').value || '',
                    event_type: root.querySelector('[data-field="event_type"]').value || '',
                    body: bodyVal,
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'team',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    tags: (root.querySelector('[data-field="tags"]').value || '').split(',').map((s) => s.trim()).filter(Boolean),
                    note_type: root.querySelector('[data-field="note_type"]').dataset.value || DEFAULT_NOTE_TYPE,
                    player_summary: playerSummaryVal,
                    what_happened: whatHappenedVal,
                    why_it_matters: whyMattersVal,
                    what_to_do_next: whatToDoVal,
                    coach_private_note: root.querySelector('[data-field="coach_private_note"]').value.trim(),
                    tactical_board_json: currentBoard,
                });
            },
        });
        if (!result) return;
        try {
            if (note) {
                // Edit path. `UpdateCoachingNoteRequest` is `extra="forbid"`
                // so we send only fields that exist on it. `note_context`
                // stays so a future flip back to video can be initiated
                // explicitly elsewhere; for now Phase 6b only supports
                // editing observations as observations.
                await this.updateCoachNote(note.id, result);
            } else {
                await this.createCoachNote(result);
            }
            this.showSuccess(note ? 'Observation updated.' : 'Observation saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },
};
