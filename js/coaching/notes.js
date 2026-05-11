// Coaching notes domain mixin (PR-FE 2/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.

import { NOTE_TYPES, DEFAULT_NOTE_TYPE } from '../coaching.js';

export const coachingNotesMixin = {
    // ===== Notes sub-tab =====

    renderCoachNotes() {
        const container = document.getElementById('coach-notes-list');
        if (!container) return;
        const notes = this._coachBundle?.notes || [];
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes yet. Click <strong>+ New note</strong> or <strong>+ New observation</strong> to add the first one.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => {
            const isObservation = (n.note_context || 'video') === 'observation';
            const titleText = (n.title || '').trim() || (isObservation
                ? ((n.event_title || '').trim() || 'Observation note')
                : '(untitled)');
            const contextPill = isObservation
                ? '<span class="coach-row-context-pill" data-context="observation">Observation</span>'
                : '<span class="coach-row-context-pill" data-context="video">Video</span>';
            // Meta line — observation notes show event metadata
            // (event type / event title / event date) instead of
            // match/timestamp/slot, so the row never shows
            // "undefined" / "0:00" / "Full" for fields that don't apply.
            const metaParts = [];
            if (isObservation) {
                if (n.event_type) {
                    const typeLabel = `${n.event_type[0].toUpperCase()}${n.event_type.slice(1)}`;
                    metaParts.push(`${typeLabel} observation`);
                } else {
                    metaParts.push('Observation');
                }
                if (n.event_title && n.event_title !== titleText) metaParts.push(n.event_title);
                if (n.event_date) metaParts.push(n.event_date);
            } else {
                metaParts.push(this.matchLabel(n.match_id));
                metaParts.push(this.formatClock(n.timestamp_seconds));
                metaParts.push(this.slotLabel(n.slot));
            }
            if (n.category) metaParts.push(n.category);
            if (n.visibility) metaParts.push(n.visibility);
            const metaLine = metaParts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
            // Observation notes have no video frame to seek into,
            // so the "Open in Review" + "Regenerate thumbnail"
            // actions are suppressed. Edit + Delete still apply.
            const actions = isObservation
                ? `
                    ${n.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(n.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_note_id: ${Number(n.id)}, title: ${JSON.stringify(titleText).replace(/"/g, '&quot;')}, description: ${JSON.stringify(n.what_to_do_next || n.player_summary || n.body || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(titleText).replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachObservationModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                `
                : `
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openNoteInReview(${n.id})">Open in Review</button>
                    ${n.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(n.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_note_id: ${Number(n.id)}, title: ${JSON.stringify(titleText).replace(/"/g, '&quot;')}, description: ${JSON.stringify(n.what_to_do_next || n.player_summary || n.body || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(titleText).replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn" onclick="app.openCoachNoteModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleRegenCoachThumb(${n.id})" title="Regenerate thumbnail" aria-label="Regenerate thumbnail">↻</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                `;
            // Observation notes get a film-strip placeholder tile so
            // the row stays visually aligned without firing a 404
            // network request — `_coachNoteThumbHtml` is video-only.
            // Phase 6c: when an observation carries a tactical board
            // we render a compact SVG preview tile instead of the
            // clipboard glyph so the coach sees the sketch at-a-glance.
            const hasBoard = isObservation && this.tacticalBoardHasContent(n.tactical_board_json);
            const thumb = isObservation
                ? (hasBoard
                    ? `<div class="coach-thumb coach-thumb--list coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(n.tactical_board_json, { size: 'chip' })}</div>`
                    : '<div class="coach-thumb coach-thumb--list coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
                : this._coachNoteThumbHtml(n, { size: 'list' });
            // Board indicator pill in the header so the row reads
            // "Observation · ⌬ Tactical board" even when the
            // thumbnail tile is visible.
            const boardPill = hasBoard
                ? '<span class="coach-row-board-pill" title="Tactical board attached">⌬ Board</span>'
                : '';
            return `
            <article class="coach-row coach-row-with-thumb" data-note-context="${isObservation ? 'observation' : 'video'}">
                ${thumb}
                <div class="coach-row-body">
                    <div class="coach-row-head">
                        ${contextPill}
                        ${boardPill}
                        <strong>${this.esc(titleText)}</strong>
                    </div>
                    <span>${metaLine}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    ${actions}
                </div>
            </article>
        `;
        }).join('');
        // Phase 3b: kick off a single batch of authenticated thumbnail
        // fetches now that the placeholders are in the DOM. Failures are
        // silent — placeholder stays visible. Observation rows skip
        // this entirely (they use a static placeholder, no
        // `data-coach-note-thumb` attribute).
        this.mountCoachNoteThumbnailsIn(container);
    },

    async openCoachNoteModal(noteId = null) {
        const note = noteId ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId)) : null;
        // Phase 6b — dispatch observation notes to the dedicated
        // observation editor. Editing an observation through the
        // video-shaped modal would force a match select that doesn't
        // belong on a text-only note.
        if (note && (note.note_context || 'video') === 'observation') {
            return this.openCoachObservationModal(noteId);
        }
        const tpl = document.getElementById('coach-note-form-template');
        if (!tpl) { this.showError('Note form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        if (note) matchSel.value = note.match_id;

        const slotSel = body.querySelector('[data-field="slot"]');
        if (note) slotSel.value = note.slot;

        body.querySelector('[data-field="time"]').value = note ? Number(note.timestamp_seconds || 0) : 0;
        body.querySelector('[data-field="title"]').value = note?.title || '';
        body.querySelector('[data-field="category"]').value = note?.category || 'other';
        body.querySelector('[data-field="visibility"]').value = note?.visibility || 'private';
        body.querySelector('[data-field="body"]').value = note?.body || '';
        body.querySelector('[data-field="tags"]').value = (note?.tags || []).join(',');

        // Phase 1 structured-note fields (PR 1b). The Notes-tab modal
        // mirrors the Review composer so editing parity is preserved —
        // a note saved via Coach Review can be re-opened here without
        // losing its structured shape.
        const initialNoteType = note?.note_type || DEFAULT_NOTE_TYPE;
        const toneBox = body.querySelector('[data-field="note_type"]');
        toneBox.dataset.value = initialNoteType;
        // Phase 4d (issue #77): the Notes-tab tone chips need the same
        // WAI-ARIA keyboard behavior as the Coach Review composer. The
        // markup intentionally matches the composer's chip set so the
        // shared `_setupToneRadiogroup` helper can drive it.
        toneBox.innerHTML = NOTE_TYPES.map(([v, l, glyph]) => `
            <button type="button" class="coach-review-tone-btn${v === initialNoteType ? ' is-active' : ''}" role="radio" aria-checked="${v === initialNoteType}" tabindex="${v === initialNoteType ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}">
                <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                <span class="coach-review-tone-label">${this.esc(l)}</span>
            </button>
        `).join('');
        // Wire click + keyboard. Click delegation is added here so the
        // modal's chip clicks update the group state without the
        // composer's inline `onclick="app.setCoachReviewNoteType(...)"`
        // attribute (which would target the WRONG group — the composer's
        // — if the modal is open at the same time).
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

        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        if (note?.player_ids?.length) {
            const sel = new Set(note.player_ids.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const result = await this.formModal({
            title: note ? 'Edit Coaching Note' : 'New Coaching Note',
            kicker: 'Coaching',
            body,
            confirmLabel: note ? 'Save changes' : 'Save note',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Title is required.'); return; }
                const matchVal = root.querySelector('[data-field="match"]').value;
                if (!matchVal) { this.showError('Match is required.'); return; }
                close({
                    match_id: matchVal,
                    slot: root.querySelector('[data-field="slot"]').value || 'full',
                    timestamp_seconds: Number(root.querySelector('[data-field="time"]').value || 0),
                    title: titleVal,
                    body: root.querySelector('[data-field="body"]').value.trim(),
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    tags: (root.querySelector('[data-field="tags"]').value || '').split(',').map((s) => s.trim()).filter(Boolean),
                    drawing: note?.drawing || {},
                    // Phase 1 structured-note fields.
                    note_type: root.querySelector('[data-field="note_type"]').dataset.value || DEFAULT_NOTE_TYPE,
                    player_summary: root.querySelector('[data-field="player_summary"]').value.trim(),
                    what_happened: root.querySelector('[data-field="what_happened"]').value.trim(),
                    why_it_matters: root.querySelector('[data-field="why_it_matters"]').value.trim(),
                    what_to_do_next: root.querySelector('[data-field="what_to_do_next"]').value.trim(),
                    coach_private_note: root.querySelector('[data-field="coach_private_note"]').value.trim(),
                });
            },
        });
        if (!result) return;
        try {
            if (note) {
                // Phase 4d (incidental fix needed for #77 manual QA):
                // `UpdateCoachingNoteRequest` is `extra="forbid"` and
                // does NOT accept `match_id` or `slot` (rebinding a
                // saved note to a different match/slot would silently
                // invalidate timestamps and drawings, so the backend
                // rejects them outright). The composer modal renders
                // those selects on edit anyway so the coach can see
                // the note's anchor; we just strip them before PATCH
                // so the request matches the server's allow-list. Same
                // pattern as the clip composer's PATCH path
                // (openCoachClipModal). Without this strip, EVERY note
                // edit (incl. the keyboard-driven note_type changes
                // this PR enables) returns 422 and the coach's edits
                // silently disappear.
                const patchBody = { ...result };
                delete patchBody.match_id;
                delete patchBody.slot;
                await this.updateCoachNote(note.id, patchBody);
            } else {
                await this.createCoachNote(result);
            }
            this.showSuccess(note ? 'Note updated.' : 'Note saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteNote(noteId) {
        const ok = await this.confirmAction({
            title: 'Delete note', message: 'Delete this coaching note?',
            confirmLabel: 'Delete note', danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachNote(noteId);
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },
};
