// playlists domain mixin for Phase 5.2 modular assembly.
// Extracted from js/coaching.js — Coach > Playlists tab list rendering,
// add/edit composer modal, delete handler, and the coach-side preview
// affordance. Viewer-side playlist player, session controller, session
// rail, and playlist thumbnails remain in js/coaching.js for their
// future domain commits.

export const coachingPlaylistsMixin = {
    // ===== Playlists sub-tab =====

    renderCoachPlaylists() {
        const container = document.getElementById('coach-playlists-list');
        if (!container) return;
        const playlists = this._coachBundle?.playlists || [];
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists yet. Click <strong>+ New playlist</strong> to build one.</div>';
            return;
        }
        // Phase 3b: build a quick lookup from note id → note so we can
        // show a stacked thumbnail strip (first 3 notes of the playlist)
        // on each row. Cheap one-pass map build; the full notes list is
        // already loaded in `_coachBundle`.
        const notesById = new Map();
        (this._coachBundle?.notes || []).forEach((n) => notesById.set(Number(n.id), n));
        container.innerHTML = playlists.map((p) => {
            const noteCount = p.note_ids?.length || 0;
            const playerCount = p.player_ids?.length || 0;
            const meta = [
                `${noteCount} note${noteCount === 1 ? '' : 's'}`,
                this.esc(p.visibility),
                `${Number(p.pre_roll_seconds ?? 5)}s pre / ${Number(p.post_roll_seconds ?? 8)}s post`,
            ];
            if (playerCount) meta.push(`${playerCount} player${playerCount === 1 ? '' : 's'}`);
            return `
            <article class="coach-row coach-row-with-thumb">
                ${this._coachPlaylistThumbStripHtml(p, notesById)}
                <div class="coach-row-body">
                    <strong>${this.esc(p.title)}</strong>
                    <span>${meta.join(' · ')}</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.previewCoachPlaylist(${p.id})">Preview</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachPlaylistModal(${p.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeletePlaylist(${p.id})">Delete</button>
                </div>
            </article>
        `;
        }).join('');
        this.mountCoachNoteThumbnailsIn(container);
    },

    /** Phase 3b — render a stacked thumbnail strip representing the
     *  first few notes in a playlist. Up to 3 tiles; if there are more
     *  items we add a `+N` overflow chip. Uses the same `coach-thumb`
     *  primitive as individual notes so the placeholder/loaded state
     *  behaves identically. */
    _coachPlaylistThumbStripHtml(playlist, notesById) {
        const ids = (playlist?.note_ids || []).slice(0, 3);
        const total = playlist?.note_ids?.length || 0;
        if (!ids.length) {
            return `
                <div class="coach-thumb-strip coach-thumb-strip--empty" aria-hidden="true">
                    <div class="coach-thumb coach-thumb--strip" data-thumb data-thumb-state="placeholder"></div>
                </div>
            `;
        }
        const tiles = ids.map((id) => {
            const note = notesById.get(Number(id));
            if (!note) {
                return `<div class="coach-thumb coach-thumb--strip" data-thumb data-thumb-state="placeholder"></div>`;
            }
            return this._coachNoteThumbHtml(note, { size: 'strip' });
        }).join('');
        const overflow = total > 3
            ? `<span class="coach-thumb-strip-more" aria-label="${total - 3} more clips">+${total - 3}</span>`
            : '';
        return `
            <div class="coach-thumb-strip" aria-hidden="true">
                ${tiles}
                ${overflow}
            </div>
        `;
    },

    async openCoachPlaylistModal(playlistId = null) {
        const playlist = playlistId ? (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId)) : null;
        const tpl = document.getElementById('coach-playlist-form-template');
        if (!tpl) { this.showError('Playlist form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        body.querySelector('[data-field="title"]').value = playlist?.title || '';
        body.querySelector('[data-field="visibility"]').value = playlist?.visibility || 'private';
        body.querySelector('[data-field="preRoll"]').value = Number(playlist?.pre_roll_seconds ?? 5);
        body.querySelector('[data-field="postRoll"]').value = Number(playlist?.post_roll_seconds ?? 8);
        body.querySelector('[data-field="description"]').value = playlist?.description || '';

        const notes = this._coachBundle?.notes || [];
        const notesBox = body.querySelector('[data-field="notes"]');
        this.renderCoachCheckList(notesBox, notes.map((n) => ({ value: n.id, label: this.noteLabel(n) })), 'No notes yet');
        if (playlist?.note_ids?.length) {
            const sel = new Set(playlist.note_ids.map(String));
            notesBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        if (playlist?.player_ids?.length) {
            const sel = new Set(playlist.player_ids.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const result = await this.formModal({
            title: playlist ? 'Edit Review Playlist' : 'New Review Playlist',
            kicker: 'Coaching',
            body,
            confirmLabel: playlist ? 'Save changes' : 'Create playlist',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Playlist title is required.'); return; }
                close({
                    title: titleVal,
                    description: root.querySelector('[data-field="description"]').value.trim(),
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    note_ids: Array.from(root.querySelector('[data-field="notes"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => Number(b.dataset.value)),
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    pre_roll_seconds: Number(root.querySelector('[data-field="preRoll"]').value || 5),
                    post_roll_seconds: Number(root.querySelector('[data-field="postRoll"]').value || 8),
                });
            },
        });
        if (!result) return;
        try {
            if (playlist) await this.updateCoachPlaylist(playlist.id, result);
            else await this.createCoachPlaylist(result);
            this.showSuccess(playlist ? 'Playlist updated.' : 'Playlist created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeletePlaylist(playlistId) {
        const ok = await this.confirmAction({
            title: 'Delete playlist', message: 'Delete this review playlist?',
            confirmLabel: 'Delete playlist', danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(`/api/coach/playlists/${playlistId}`, {
                method: 'DELETE', headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to delete playlist');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    previewCoachPlaylist(playlistId) {
        const playlist = (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'coach' });
    },
};
