// Coaching workspace: roster, notes, playlists, in-/coach Review video player + telestrator,
// player-facing /feedback view with a focused feedback-player modal. The in-match side panel
// is intentionally absent — Coach > Review is the single authoring surface.

const NOTE_CATEGORIES = [
    ['shape', 'Shape'], ['pressing', 'Pressing'], ['transition', 'Transition'],
    ['set_piece', 'Set piece'], ['build_up', 'Build-up'], ['finishing', 'Finishing'],
    ['defending', 'Defending'], ['goalkeeper', 'Goalkeeper'], ['effort', 'Effort'],
    ['decision', 'Decision'], ['other', 'Other'],
];

const VISIBILITY_OPTIONS = [
    ['private', 'Private'], ['team', 'Team-visible'],
    ['player', 'Player/family'], ['unlisted', 'Unlisted link'],
];

const VALID_COACH_TABS = ['roster', 'notes', 'playlists', 'review'];
const VALID_FEEDBACK_TABS = ['playlists', 'notes'];

export const coachingMixin = {
    _coachBundle: null,
    _coachDrawing: null,
    _coachDrawingActive: false,
    _coachDrawingTool: 'freehand',
    _coachDrawingColor: '#38bdf8',
    _coachDrawingWidth: 3,
    _coachSelectedObjectIndex: null,
    _coachCurrentObject: null,
    _coachDragState: null,
    _coachPlaylistSession: null,
    _coachPlaylistMonitor: null,
    _coachPlaylistFreezeTimer: null,
    _coachTab: 'roster',
    _feedbackTab: 'playlists',
    _coachReview: null,
    _coachCanvasId: 'coach-drawing-canvas',
    _coachVideoId: 'coach-review-video',
    _feedbackPlayer: null,
    // Multi-player formation overlay (Phase 1) — see ROADMAP "Coaching Telestrator".
    // Draft holds the in-progress anchors while the coach is clicking; gets
    // committed to a single drawing object on Done.
    _coachFormationDraft: null,
    _coachFormationMode: 'quick', // 'quick' | 'linked'

    // ===== top-level view entry points =====

    async showCoachView({ pushHistory = true, replaceHistory = false, scrollTop = true, tab = null, matchId = null, slot = null } = {}) {
        if (!this.canCoach()) {
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('coach-view', 'coach');
        const targetTab = VALID_COACH_TABS.includes(tab) ? tab : (this._coachTab || 'roster');
        if (matchId) this._coachReviewPending = { matchId, slot: slot || 'full' };
        if (pushHistory) {
            const url = this._coachUrl(targetTab, matchId, slot);
            this.pushHistoryState({ view: 'coach', tab: targetTab }, { replace: replaceHistory, url });
        }
        await this.renderCoachWorkspace();
        this.setCoachTab(targetTab, { pushHistory: false });
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async showFeedbackView({ pushHistory = true, replaceHistory = false, scrollTop = true, tab = null } = {}) {
        if (!this.authToken) {
            this.showLoginModal();
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('feedback-view', 'feedback');
        const targetTab = VALID_FEEDBACK_TABS.includes(tab) ? tab : (this._feedbackTab || 'playlists');
        if (pushHistory) {
            const url = `/feedback?tab=${targetTab}`;
            this.pushHistoryState({ view: 'feedback', tab: targetTab }, { replace: replaceHistory, url });
        }
        await this.renderMyFeedback();
        this.setFeedbackTab(targetTab, { pushHistory: false });
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    _coachUrl(tab, matchId, slot) {
        const params = new URLSearchParams();
        if (tab && tab !== 'roster') params.set('tab', tab);
        if (matchId) params.set('match', String(matchId));
        if (slot) params.set('slot', slot);
        const qs = params.toString();
        return qs ? `/coach?${qs}` : '/coach';
    },

    // ===== sub-tab routers =====

    setCoachTab(name, { pushHistory = true } = {}) {
        if (!VALID_COACH_TABS.includes(name)) name = 'roster';
        this._coachTab = name;
        document.querySelectorAll('[data-coach-tab]').forEach((btn) => {
            const active = btn.dataset.coachTab === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        VALID_COACH_TABS.forEach((tab) => {
            const panel = document.getElementById(`coach-tab-${tab}`);
            if (panel) panel.hidden = tab !== name;
        });
        // Sprint 1: drive a video-first layout when Review is the active sub-tab.
        // Scoping the class to #coach-view keeps Roster/Notes/Playlists untouched.
        const coachView = document.getElementById('coach-view');
        if (coachView) coachView.classList.toggle('is-review-mode', name === 'review');
        if (pushHistory) {
            const params = new URLSearchParams(window.location.search);
            if (name === 'roster') params.delete('tab');
            else params.set('tab', name);
            const qs = params.toString();
            const url = qs ? `/coach?${qs}` : '/coach';
            this.pushHistoryState({ view: 'coach', tab: name }, { replace: true, url });
        }
        if (name === 'roster') this.renderCoachRoster();
        if (name === 'notes') this.renderCoachNotes();
        if (name === 'playlists') this.renderCoachPlaylists();
        if (name === 'review') this.renderCoachReview();
        else this.tearDownCoachReview();
    },

    setFeedbackTab(name, { pushHistory = true } = {}) {
        if (!VALID_FEEDBACK_TABS.includes(name)) name = 'playlists';
        this._feedbackTab = name;
        document.querySelectorAll('[data-feedback-tab]').forEach((btn) => {
            const active = btn.dataset.feedbackTab === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        VALID_FEEDBACK_TABS.forEach((tab) => {
            const panel = document.getElementById(`feedback-tab-${tab}`);
            if (panel) panel.hidden = tab !== name;
        });
        if (pushHistory) {
            const url = `/feedback?tab=${name}`;
            this.pushHistoryState({ view: 'feedback', tab: name }, { replace: true, url });
        }
    },

    // ===== Coach workspace data load =====

    async renderCoachWorkspace() {
        const roster = document.getElementById('coach-roster-list');
        const notes = document.getElementById('coach-notes-list');
        if (roster) roster.innerHTML = '<div class="session-empty">Loading roster...</div>';
        if (notes) notes.innerHTML = '<div class="session-empty">Loading notes...</div>';
        try {
            this._coachBundle = await this.loadCoachBundle();
            this.renderCoachRoster();
            this.renderCoachLinkSelectors();
            this.renderCoachNotes();
            this.renderCoachPlaylists();
            this.renderCoachReviewPicker();
        } catch (err) {
            this.showError(err.message || 'Could not load coaching workspace.');
        }
    },

    renderCoachLinkSelectors() {
        const bundle = this._coachBundle || { players: [], users: [] };
        const playerOptions = bundle.players.map((p) => (
            `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`
        )).join('');
        const linkPlayerEl = document.getElementById('coach-link-player');
        if (linkPlayerEl) linkPlayerEl.innerHTML = playerOptions || '<option value="">No players yet</option>';
        const userOptions = bundle.users.map((u) => (
            `<option value="${this.esc(u.id)}">${this.esc(u.display_name || u.username)} (@${this.esc(u.username)})</option>`
        )).join('');
        const userEl = document.getElementById('coach-link-user');
        if (userEl) userEl.innerHTML = userOptions || '<option value="">Create a user first</option>';
    },

    coachCheckListHtml(items, emptyLabel = 'Nothing available') {
        if (!items.length) {
            return `<div class="coach-check-empty">${this.esc(emptyLabel)}</div>`;
        }
        return items.map((item) => `
            <button type="button" class="coach-check-option" data-value="${this.esc(item.value)}" aria-pressed="false" onclick="app.toggleCoachCheck(this)">
                <span class="coach-check-box" aria-hidden="true"></span>
                <span class="coach-check-label">${this.esc(item.label)}</span>
            </button>
        `).join('');
    },

    renderCoachCheckList(target, items, emptyLabel) {
        const el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return;
        el.innerHTML = this.coachCheckListHtml(items, emptyLabel);
    },

    toggleCoachCheck(btn) {
        const selected = !btn.classList.contains('is-selected');
        btn.classList.toggle('is-selected', selected);
        btn.setAttribute('aria-pressed', selected ? 'true' : 'false');
    },

    playerLabel(player) {
        const number = player.jersey_number ? `#${player.jersey_number} ` : '';
        return `${number}${player.display_name}`;
    },

    noteLabel(note) {
        const match = this.matches.find((m) => m.id === note.match_id);
        const matchup = match ? `${match.home_team} vs ${match.away_team}` : note.match_id;
        return `${this.formatClock(note.timestamp_seconds)} · ${matchup} · ${note.title}`;
    },

    formatClock(seconds) {
        const total = Math.max(0, Math.floor(Number(seconds || 0)));
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return `${mins}:${String(secs).padStart(2, '0')}`;
    },

    matchLabel(matchId) {
        const m = this.matches.find((x) => x.id === matchId);
        return m ? `${m.home_team} vs ${m.away_team} · ${this.formatDate(m.date)}` : String(matchId);
    },

    // ===== Roster sub-tab =====

    renderCoachRoster() {
        const container = document.getElementById('coach-roster-list');
        if (!container) return;
        const players = this._coachBundle?.players || [];
        if (!players.length) {
            container.innerHTML = '<div class="session-empty">No roster players yet.</div>';
            return;
        }
        container.innerHTML = players.map((p) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(this.playerLabel(p))}</strong>
                    <span>${p.active ? 'Active' : 'Inactive'} · ${p.links?.length || 0} linked account${p.links?.length === 1 ? '' : 's'}</span>
                    ${(p.links || []).map((l) => `
                        <button type="button" class="coach-link-pill" onclick="app.handleCoachUnlink(${l.id})">
                            ${this.esc(l.relationship)} · @${this.esc(l.username)} ×
                        </button>
                    `).join('')}
                </div>
                <button type="button" class="mini-action-btn" onclick="app.handleCoachDeletePlayer('${this.esc(p.id)}')">Delete</button>
            </article>
        `).join('');
    },

    async handleCoachAddPlayer() {
        const display_name = document.getElementById('coach-player-name')?.value.trim();
        const jersey_number = document.getElementById('coach-player-number')?.value.trim() || '';
        if (!display_name) { this.showError('Player name is required.'); return; }
        try {
            await this.createCoachPlayer({ display_name, jersey_number, active: true });
            document.getElementById('coach-player-name').value = '';
            document.getElementById('coach-player-number').value = '';
            this.showSuccess('Player added.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeletePlayer(playerId) {
        const ok = await this.confirmAction({
            title: 'Delete player',
            message: 'Delete this roster player and remove their feedback links?',
            confirmLabel: 'Delete player', danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(`/api/coach/players/${playerId}`, {
                method: 'DELETE', headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to delete player');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachLinkAccount() {
        const player_id = document.getElementById('coach-link-player')?.value;
        const user_id = document.getElementById('coach-link-user')?.value;
        const relationship = document.getElementById('coach-link-relationship')?.value || 'family';
        if (!player_id || !user_id) { this.showError('Pick a player and a user account.'); return; }
        try {
            await this.linkCoachPlayer({ player_id, user_id, relationship });
            this.showSuccess('Account linked.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachUnlink(linkId) {
        try {
            await this.unlinkCoachPlayer(linkId);
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    // ===== Notes sub-tab =====

    renderCoachNotes() {
        const container = document.getElementById('coach-notes-list');
        if (!container) return;
        const notes = this._coachBundle?.notes || [];
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes yet. Click <strong>+ New note</strong> to add the first one.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(n.title)}</strong>
                    <span>${this.esc(this.matchLabel(n.match_id))} · ${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${this.esc(n.category)} · ${this.esc(n.visibility)}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn" onclick="app.openNoteInReview(${n.id})">Open in Review</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachNoteModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                </div>
            </article>
        `).join('');
    },

    async openCoachNoteModal(noteId = null) {
        const note = noteId ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId)) : null;
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
                });
            },
        });
        if (!result) return;
        try {
            if (note) await this.updateCoachNote(note.id, result);
            else await this.createCoachNote(result);
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

    // ===== Playlists sub-tab =====

    renderCoachPlaylists() {
        const container = document.getElementById('coach-playlists-list');
        if (!container) return;
        const playlists = this._coachBundle?.playlists || [];
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists yet. Click <strong>+ New playlist</strong> to build one.</div>';
            return;
        }
        container.innerHTML = playlists.map((p) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(p.title)}</strong>
                    <span>${p.note_ids?.length || 0} notes · ${this.esc(p.visibility)} · ${Number(p.pre_roll_seconds ?? 5)}s pre / ${Number(p.post_roll_seconds ?? 8)}s post</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn" onclick="app.previewCoachPlaylist(${p.id})">Preview</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachPlaylistModal(${p.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeletePlaylist(${p.id})">Delete</button>
                </div>
            </article>
        `).join('');
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

    // ===== Review sub-tab =====

    renderCoachReviewPicker() {
        const matchSel = document.getElementById('coach-review-match');
        if (!matchSel) return;
        const opts = ['<option value="">Select a match…</option>'].concat(
            this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`)
        ).join('');
        matchSel.innerHTML = opts;
    },

    async renderCoachReview() {
        this.renderCoachReviewPicker();
        const toolbar = document.getElementById('coach-review-toolbar');
        if (toolbar) toolbar.innerHTML = this.renderCoachTelestratorToolbar();
        this.renderCoachReviewForm();

        const pending = this._coachReviewPending || this._coachReview;
        if (pending?.matchId) {
            const matchSel = document.getElementById('coach-review-match');
            const slotSel = document.getElementById('coach-review-slot');
            if (matchSel) matchSel.value = pending.matchId;
            if (slotSel) slotSel.value = pending.slot || 'full';
            await this.loadCoachReviewVideo(pending.matchId, pending.slot || 'full', pending.seekTo || 0, pending.drawing || null);
            this._coachReviewPending = null;
        } else {
            const empty = document.getElementById('coach-review-empty');
            if (empty) empty.style.display = 'flex';
            await this.renderCoachReviewNotes(null);
        }
    },

    tearDownCoachReview() {
        this._stopFeedbackHeartbeat();
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            video.pause();
            video.removeAttribute('src');
            video.load();
        }
        this.deactivateCoachCanvas();
        this.clearCoachDrawing();
        this._coachReview = null;
    },

    handleCoachReviewMatchChange() {
        const matchId = document.getElementById('coach-review-match')?.value;
        const slot = document.getElementById('coach-review-slot')?.value || 'full';
        if (!matchId) { this.tearDownCoachReview(); this.renderCoachReviewNotes(null); return; }
        this.loadCoachReviewVideo(matchId, slot, 0, null);
    },

    handleCoachReviewSlotChange() {
        const matchId = document.getElementById('coach-review-match')?.value;
        const slot = document.getElementById('coach-review-slot')?.value || 'full';
        if (!matchId) return;
        this.loadCoachReviewVideo(matchId, slot, 0, null);
    },

    async loadCoachReviewVideo(matchId, slot, seekTo = 0, drawing = null) {
        const video = document.getElementById(this._coachVideoId);
        const empty = document.getElementById('coach-review-empty');
        if (!video) return;
        if (empty) empty.style.display = 'none';
        this._coachReview = { matchId, slot };

        const { hlsUrl, mp4Url } = this.getStreamUrls(matchId, slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            if (seekTo > 0) video.currentTime = seekTo;
            this.setupCoachCanvas();
            if (drawing) this.renderCoachDrawing(drawing);
        };
        video.addEventListener('loadedmetadata', onLoaded);
        // Keep the VOD session warm: the streams registry reaps idle sessions
        // after 15 s and admin "kill" only propagates to active heartbeaters.
        this._startFeedbackHeartbeat(matchId, slot, video);

        const url = this._coachUrl('review', matchId, slot);
        this.pushHistoryState({ view: 'coach', tab: 'review', matchId, slot }, { replace: true, url });

        await this.renderCoachReviewNotes(matchId);
    },

    async renderCoachReviewNotes(matchId) {
        const container = document.getElementById('coach-review-notes');
        if (!container) return;
        if (!matchId) { container.innerHTML = '<div class="session-empty">Select a match to see its notes.</div>'; return; }
        const allNotes = this._coachBundle?.notes || [];
        const notes = allNotes.filter((n) => n.match_id === matchId);
        if (!notes.length) { container.innerHTML = '<div class="session-empty">No notes for this match yet.</div>'; return; }
        container.innerHTML = notes.map((n) => `
            <button type="button" class="coach-note-jump" onclick="app.seekCoachReviewNote(${n.id})">
                <span>${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))}</span>
                <strong>${this.esc(n.title)}</strong>
            </button>
        `).join('');
    },

    seekCoachReviewNote(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        const review = this._coachReview;
        if (!review || review.matchId !== note.match_id || review.slot !== note.slot) {
            this.loadCoachReviewVideo(note.match_id, note.slot, Math.max(0, Number(note.timestamp_seconds || 0)), note.drawing || null);
            const matchSel = document.getElementById('coach-review-match');
            const slotSel = document.getElementById('coach-review-slot');
            if (matchSel) matchSel.value = note.match_id;
            if (slotSel) slotSel.value = note.slot;
            return;
        }
        const video = document.getElementById(this._coachVideoId);
        if (video) video.currentTime = Math.max(0, Number(note.timestamp_seconds || 0));
        this.renderCoachDrawing(note.drawing || {});
    },

    renderCoachReviewForm() {
        const container = document.getElementById('coach-review-form');
        if (!container) return;
        const players = this._coachBundle?.players || [];
        container.innerHTML = `
            <input type="text" id="coach-review-title" maxlength="160" placeholder="Title (e.g. Back line spacing)">
            <textarea id="coach-review-body" rows="3" maxlength="4000" placeholder="What should players notice?"></textarea>
            <div class="coach-panel-grid">
                <select id="coach-review-category">
                    ${NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
                <select id="coach-review-visibility">
                    ${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
            </div>
            <div id="coach-review-players" class="coach-check-list compact" role="listbox" aria-label="Linked players">${this.coachCheckListHtml(players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet')}</div>
            <input type="text" id="coach-review-tags" maxlength="300" placeholder="tags,comma,separated">
            <button type="button" class="btn-primary" onclick="app.saveReviewNote()">Save note at current time</button>
        `;
    },

    async openNoteInReview(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this._coachReviewPending = {
            matchId: note.match_id, slot: note.slot,
            seekTo: Math.max(0, Number(note.timestamp_seconds || 0)),
            drawing: note.drawing || null,
        };
        this.setCoachTab('review');
    },

    async saveReviewNote() {
        const review = this._coachReview;
        if (!review?.matchId) { this.showError('Pick a match in the Review tab first.'); return; }
        const video = document.getElementById(this._coachVideoId);
        const title = document.getElementById('coach-review-title')?.value.trim();
        if (!title) { this.showError('Add a title for the coaching note.'); return; }
        const payload = {
            match_id: review.matchId,
            slot: review.slot || 'full',
            timestamp_seconds: video?.currentTime || 0,
            title,
            body: document.getElementById('coach-review-body')?.value.trim() || '',
            category: document.getElementById('coach-review-category')?.value || 'other',
            visibility: document.getElementById('coach-review-visibility')?.value || 'private',
            player_ids: Array.from(document.querySelectorAll('#coach-review-players .coach-check-option.is-selected')).map((b) => b.dataset.value),
            tags: (document.getElementById('coach-review-tags')?.value || '').split(',').map((s) => s.trim()).filter(Boolean),
            drawing: this._coachDrawing || {},
        };
        try {
            await this.createCoachNote(payload);
            this.showSuccess('Coaching note saved.');
            ['coach-review-title', 'coach-review-body', 'coach-review-tags'].forEach((id) => {
                const el = document.getElementById(id); if (el) el.value = '';
            });
            this.clearCoachDrawing();
            this._coachBundle = await this.loadCoachBundle();
            await this.renderCoachReviewNotes(review.matchId);
        } catch (err) { this.showError(err.message); }
    },

    // ===== Telestrator (operates on whichever canvas/video pair is current) =====

    renderCoachTelestratorToolbar() {
        const tools = [
            ['select', 'Select'], ['freehand', 'Line'], ['arrow', 'Arrow'],
            ['circle', 'Circle'], ['zone', 'Zone'], ['label', 'Label'],
            ['spotlight', 'Spot'], ['dim', 'Dim'], ['formation', 'Formation'],
        ];
        const colors = ['#38bdf8', '#f97316', '#22c55e', '#facc15', '#f43f5e', '#ffffff'];
        return `
            <div class="coach-telestrator">
                <div class="coach-tool-grid">
                    ${tools.map(([tool, label]) => `
                        <button type="button" data-coach-tool="${tool}" class="mini-action-btn ${this._coachDrawingTool === tool ? 'active' : ''}" onclick="app.setCoachDrawingTool('${tool}')">${label}</button>
                    `).join('')}
                </div>
                <div class="coach-tool-row">
                    ${colors.map((color) => `
                        <button type="button" data-coach-color="${color}" class="coach-color-swatch ${this._coachDrawingColor === color ? 'active' : ''}" style="--swatch:${color}" title="${color}" onclick="app.setCoachDrawingColor('${color}')"></button>
                    `).join('')}
                    <label class="coach-width-control">Width <input type="range" min="2" max="10" value="${this._coachDrawingWidth}" onchange="app.setCoachDrawingWidth(this.value)"></label>
                </div>
                <input type="text" id="coach-label-text" maxlength="40" placeholder="Label / player number">
                <div id="coach-formation-controls" class="coach-formation-controls" hidden></div>
                <div class="coach-draw-actions">
                    <button type="button" data-coach-canvas-toggle class="mini-action-btn" onclick="app.toggleCoachDrawing()">Canvas ${this._coachDrawingActive ? 'On' : 'Off'}</button>
                    <button type="button" class="mini-action-btn" onclick="app.undoCoachDrawing()">Undo</button>
                    <button type="button" class="mini-action-btn" onclick="app.deleteSelectedCoachObject()">Delete</button>
                    <button type="button" class="mini-action-btn" onclick="app.clearCoachDrawing()">Clear</button>
                </div>
            </div>
        `;
    },

    setupCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        const video = document.getElementById(this._coachVideoId);
        if (!canvas || !video) return;
        if (canvas._coachBound) { this._resizeCoachCanvas(canvas, video); return; }
        const resize = () => this._resizeCoachCanvas(canvas, video);
        window.addEventListener('resize', resize);
        video.addEventListener('loadedmetadata', resize);
        // Sprint 1: the inspector is now independently scrollable, which means the
        // wrapper can change size without window resizing (e.g. inspector grows and
        // pushes the video column narrower). Observe the wrapper directly so the
        // canvas bitmap stays aligned with the rendered video.
        const wrapper = video.closest('.coach-review-wrapper, .feedback-player-wrapper');
        if (wrapper && typeof ResizeObserver === 'function') {
            const ro = new ResizeObserver(resize);
            ro.observe(wrapper);
            canvas._coachResizeObserver = ro;
        }
        canvas.addEventListener('pointerdown', (event) => this.coachDrawStart(event));
        canvas.addEventListener('pointermove', (event) => this.coachDrawMove(event));
        canvas.addEventListener('pointerup', (event) => this.coachDrawEnd(event));
        canvas.addEventListener('pointerleave', (event) => this.coachDrawEnd(event));
        canvas._coachBound = true;
        canvas._coachResize = resize;
        resize();
    },

    _resizeCoachCanvas(canvas, video) {
        const rect = video.getBoundingClientRect();
        canvas.width = Math.max(1, Math.round(rect.width));
        canvas.height = Math.max(1, Math.round(rect.height));
        this.paintCoachCanvas();
    },

    // Detach the global resize listener registered by setupCoachCanvas.
    // The Review tab's canvas is persistent in the DOM, so this is only
    // needed for the feedback player modal whose canvas is removed when
    // the modal closes — without this the closure stays attached to
    // window, leaking the canvas it captured.
    teardownCoachCanvasListeners(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !canvas._coachResize) return;
        window.removeEventListener('resize', canvas._coachResize);
        if (canvas._coachResizeObserver) {
            canvas._coachResizeObserver.disconnect();
            canvas._coachResizeObserver = null;
        }
        canvas._coachResize = null;
        canvas._coachBound = false;
    },

    activateCoachCanvas() {
        this.setupCoachCanvas();
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = true;
        canvas.style.display = 'block';
        canvas.style.pointerEvents = 'auto';
        this.updateCoachCanvasToggleLabel();
    },

    deactivateCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = false;
        canvas.style.display = this._coachDrawing ? 'block' : 'none';
        canvas.style.pointerEvents = 'none';
        this.updateCoachCanvasToggleLabel();
    },

    updateCoachCanvasToggleLabel() {
        document.querySelectorAll('[data-coach-canvas-toggle]').forEach((btn) => {
            btn.textContent = `Canvas ${this._coachDrawingActive ? 'On' : 'Off'}`;
        });
    },

    normalizeCoachDrawing(drawing) {
        if (!drawing) return null;
        if (drawing.version === 2 && Array.isArray(drawing.objects)) return { version: 2, objects: [...drawing.objects] };
        if (Array.isArray(drawing.strokes)) {
            return {
                version: 2,
                objects: drawing.strokes.map((stroke) => ({
                    type: 'freehand',
                    color: stroke.color || '#38bdf8',
                    width: stroke.width || 3,
                    points: stroke.points || [],
                })),
            };
        }
        return null;
    },

    ensureCoachDrawing() {
        if (!this._coachDrawing || this._coachDrawing.version !== 2) {
            this._coachDrawing = this.normalizeCoachDrawing(this._coachDrawing) || { version: 2, objects: [] };
        }
        if (!Array.isArray(this._coachDrawing.objects)) this._coachDrawing.objects = [];
        return this._coachDrawing;
    },

    toggleCoachDrawing() {
        if (this._coachDrawingActive) this.deactivateCoachCanvas();
        else this.activateCoachCanvas();
    },

    setCoachDrawingTool(tool) {
        // Switching away from formation mid-draft discards the in-progress
        // anchors; the user can restart by re-selecting Formation.
        if (this._coachDrawingTool === 'formation' && tool !== 'formation') {
            this._coachFormationDraft = null;
        }
        this._coachDrawingTool = tool;
        document.querySelectorAll('[data-coach-tool]').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.coachTool === tool);
        });
        this._renderFormationControls();
        this.activateCoachCanvas();
        this.paintCoachCanvas();
    },

    setCoachDrawingColor(color) {
        this._coachDrawingColor = color;
        document.querySelectorAll('[data-coach-color]').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.coachColor === color);
        });
    },

    setCoachDrawingWidth(width) {
        this._coachDrawingWidth = Math.max(2, Math.min(10, Number(width || 3)));
    },

    coachDrawPoint(event) {
        const canvas = document.getElementById(this._coachCanvasId);
        const rect = canvas.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) / Math.max(1, rect.width),
            y: (event.clientY - rect.top) / Math.max(1, rect.height),
        };
    },

    coachDrawStart(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const drawing = this.ensureCoachDrawing();
        const point = this.coachDrawPoint(event);
        if (this._coachDrawingTool === 'formation') {
            if (!this._coachFormationDraft) {
                this._coachFormationDraft = {
                    mode: this._coachFormationMode || 'quick',
                    anchors: [],
                    queuedPlayerIds: [],
                };
                this._renderFormationControls();
            }
            const draft = this._coachFormationDraft;
            if (draft.anchors.length >= 16) {
                this.showError?.('A formation can hold at most 16 players.');
                return;
            }
            const anchor = { x: point.x, y: point.y };
            if (draft.mode === 'linked' && draft.queuedPlayerIds.length) {
                const pid = draft.queuedPlayerIds.shift();
                const p = (this._coachBundle?.players || []).find((pl) => String(pl.id) === String(pid));
                if (p) {
                    anchor.player_id = String(p.id);
                    anchor.label = String(p.jersey_number || (p.display_name || '?').slice(0, 1)).toUpperCase().slice(0, 8);
                }
            }
            draft.anchors.push(anchor);
            this._renderFormationDraftPreview();
            return;
        }
        if (this._coachDrawingTool === 'select') {
            const index = this.hitCoachDrawingObject(point);
            this._coachSelectedObjectIndex = index;
            this._coachDragState = index === null ? null : { index, start: point };
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'label') {
            const text = document.getElementById('coach-label-text')?.value.trim() || 'Player';
            drawing.objects.push({ type: 'label', color: this._coachDrawingColor, x: point.x, y: point.y, text });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'dim') {
            drawing.objects.push({ type: 'dim', opacity: 0.45 });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        let object = null;
        if (this._coachDrawingTool === 'freehand') {
            object = { type: 'freehand', color: this._coachDrawingColor, width: this._coachDrawingWidth, points: [point] };
        } else if (this._coachDrawingTool === 'arrow') {
            object = { type: 'arrow', color: this._coachDrawingColor, width: this._coachDrawingWidth, x1: point.x, y1: point.y, x2: point.x, y2: point.y };
        } else if (this._coachDrawingTool === 'spotlight') {
            object = { type: 'spotlight', color: this._coachDrawingColor, width: this._coachDrawingWidth,
                       x: Math.max(0, point.x - 0.08), y: Math.max(0, point.y - 0.08), w: 0.16, h: 0.16 };
        } else if (['circle', 'zone'].includes(this._coachDrawingTool)) {
            object = { type: this._coachDrawingTool, color: this._coachDrawingColor, width: this._coachDrawingWidth, x: point.x, y: point.y, w: 0.001, h: 0.001 };
        }
        if (!object) return;
        drawing.objects.push(object);
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._coachCurrentObject = { object, start: point };
        this.paintCoachCanvas();
    },

    coachDrawMove(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const point = this.coachDrawPoint(event);
        if (this._coachDragState) {
            const object = this._coachDrawing?.objects?.[this._coachDragState.index];
            if (object) {
                const dx = point.x - this._coachDragState.start.x;
                const dy = point.y - this._coachDragState.start.y;
                this.moveCoachDrawingObject(object, dx, dy);
                this._coachDragState.start = point;
            }
            this.paintCoachCanvas();
            return;
        }
        if (!this._coachCurrentObject) return;
        const { object, start } = this._coachCurrentObject;
        if (object.type === 'freehand') {
            object.points.push(point);
        } else if (object.type === 'arrow') {
            object.x2 = point.x;
            object.y2 = point.y;
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            const minSize = object.type === 'spotlight' ? 0.08 : 0.001;
            const w = Math.max(minSize, Math.abs(point.x - start.x));
            const h = Math.max(minSize, Math.abs(point.y - start.y));
            object.x = Math.min(start.x, point.x);
            object.y = Math.min(start.y, point.y);
            object.w = w;
            object.h = h;
        }
        this.paintCoachCanvas();
    },

    coachDrawEnd(event) {
        if (event?.target?.releasePointerCapture && event.pointerId !== undefined) {
            try { event.target.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
        }
        this._coachCurrentObject = null;
        this._coachDragState = null;
    },

    paintCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const drawing = this.normalizeCoachDrawing(this._coachDrawing);
        const objects = drawing?.objects || [];
        objects.forEach((object, index) => {
            this.paintCoachObject(ctx, canvas, object);
            if (index === this._coachSelectedObjectIndex) this.paintCoachSelection(ctx, canvas, object);
        });
    },

    paintCoachObject(ctx, canvas, object) {
        const color = object.color || '#38bdf8';
        const width = object.width || 3;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        if (object.type === 'dim') {
            ctx.fillStyle = `rgba(0, 0, 0, ${object.opacity ?? 0.45})`;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else if (object.type === 'freehand') {
            ctx.beginPath();
            (object.points || []).forEach((pt, idx) => {
                const x = pt.x * canvas.width;
                const y = pt.y * canvas.height;
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
        } else if (object.type === 'arrow') {
            const x1 = object.x1 * canvas.width;
            const y1 = object.y1 * canvas.height;
            const x2 = object.x2 * canvas.width;
            const y2 = object.y2 * canvas.height;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
            const angle = Math.atan2(y2 - y1, x2 - x1);
            const head = 14 + width;
            ctx.beginPath();
            ctx.moveTo(x2, y2);
            ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
            ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
            ctx.closePath();
            ctx.fill();
        } else if (object.type === 'circle' || object.type === 'spotlight') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const w = object.w * canvas.width;
            const h = object.h * canvas.height;
            if (object.type === 'spotlight') {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.48)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                ctx.beginPath();
                ctx.ellipse(x + w / 2, y + h / 2, Math.max(8, w / 2), Math.max(8, h / 2), 0, 0, Math.PI * 2);
                ctx.fill();
                ctx.globalCompositeOperation = 'source-over';
                ctx.strokeStyle = color;
            }
            ctx.beginPath();
            ctx.ellipse(x + w / 2, y + h / 2, Math.max(4, w / 2), Math.max(4, h / 2), 0, 0, Math.PI * 2);
            ctx.stroke();
        } else if (object.type === 'zone') {
            ctx.strokeRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
            ctx.globalAlpha = 0.14;
            ctx.fillRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
        } else if (object.type === 'label') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const text = object.text || 'Player';
            ctx.font = '700 18px system-ui, sans-serif';
            const metrics = ctx.measureText(text);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
            ctx.fillRect(x - 6, y - 22, metrics.width + 12, 28);
            ctx.fillStyle = color;
            ctx.fillText(text, x, y);
        } else if (object.type === 'formation') {
            const anchors = object.anchors || [];
            const hullPts = object.hull_points || [];
            // One dim layer per formation, then cut spotlight holes at every
            // anchor with destination-out (mirrors the existing `spotlight`
            // tool's pattern; stacking dims per-anchor would compound).
            if (anchors.length) {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.42)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                anchors.forEach((a) => {
                    ctx.beginPath();
                    ctx.arc(a.x * canvas.width, a.y * canvas.height, 22, 0, Math.PI * 2);
                    ctx.fill();
                });
                ctx.globalCompositeOperation = 'source-over';
            }
            // Outline + label badge per anchor
            anchors.forEach((a, idx) => {
                const x = a.x * canvas.width, y = a.y * canvas.height;
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(x, y, 22, 0, Math.PI * 2);
                ctx.stroke();
                const label = (a.label && String(a.label)) || String(idx + 1);
                ctx.font = '700 12px system-ui, sans-serif';
                const m = ctx.measureText(label);
                ctx.fillStyle = 'rgba(0, 0, 0, 0.78)';
                ctx.fillRect(x - m.width / 2 - 5, y - 38, m.width + 10, 18);
                ctx.fillStyle = color;
                ctx.fillText(label, x - m.width / 2, y - 25);
            });
            // Convex hull polygon — translucent fill + crisp stroke
            if (hullPts.length >= 3) {
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                hullPts.forEach((p, idx) => {
                    const x = p.x * canvas.width, y = p.y * canvas.height;
                    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.save();
                ctx.globalAlpha = 0.18;
                ctx.fillStyle = color;
                ctx.fill();
                ctx.restore();
                ctx.stroke();
            }
        }
        ctx.restore();
    },

    paintCoachSelection(ctx, canvas, object) {
        const box = this.coachObjectBounds(object);
        if (!box) return;
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeRect(box.x * canvas.width, box.y * canvas.height, box.w * canvas.width, box.h * canvas.height);
        ctx.restore();
    },

    coachObjectBounds(object) {
        if (!object) return null;
        if (object.type === 'arrow') {
            const x = Math.min(object.x1, object.x2);
            const y = Math.min(object.y1, object.y2);
            return { x, y, w: Math.abs(object.x2 - object.x1) || 0.02, h: Math.abs(object.y2 - object.y1) || 0.02 };
        }
        if (['circle', 'zone', 'spotlight'].includes(object.type)) return { x: object.x, y: object.y, w: object.w, h: object.h };
        if (object.type === 'label') return { x: object.x, y: Math.max(0, object.y - 0.08), w: 0.12, h: 0.08 };
        if (object.type === 'freehand') {
            const points = object.points || [];
            if (!points.length) return null;
            const xs = points.map((p) => p.x);
            const ys = points.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.02, Math.max(...xs) - x), h: Math.max(0.02, Math.max(...ys) - y) };
        }
        if (object.type === 'dim') return { x: 0, y: 0, w: 1, h: 1 };
        if (object.type === 'formation') {
            const pts = (object.hull_points || []).concat(object.anchors || []);
            if (!pts.length) return null;
            const xs = pts.map((p) => p.x);
            const ys = pts.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.04, Math.max(...xs) - x), h: Math.max(0.04, Math.max(...ys) - y) };
        }
        return null;
    },

    hitCoachDrawingObject(point) {
        const objects = this._coachDrawing?.objects || [];
        for (let i = objects.length - 1; i >= 0; i -= 1) {
            const box = this.coachObjectBounds(objects[i]);
            if (!box) continue;
            const pad = 0.025;
            if (point.x >= box.x - pad && point.x <= box.x + box.w + pad &&
                point.y >= box.y - pad && point.y <= box.y + box.h + pad) {
                return i;
            }
        }
        return null;
    },

    moveCoachDrawingObject(object, dx, dy) {
        const clamp = (value) => Math.max(0, Math.min(1, value));
        if (object.type === 'freehand') {
            object.points = (object.points || []).map((pt) => ({ x: clamp(pt.x + dx), y: clamp(pt.y + dy) }));
        } else if (object.type === 'arrow') {
            object.x1 = clamp(object.x1 + dx); object.y1 = clamp(object.y1 + dy);
            object.x2 = clamp(object.x2 + dx); object.y2 = clamp(object.y2 + dy);
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'label') {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'formation') {
            (object.anchors || []).forEach((a) => {
                a.x = clamp(a.x + dx);
                a.y = clamp(a.y + dy);
            });
            (object.hull_points || []).forEach((p) => {
                p.x = clamp(p.x + dx);
                p.y = clamp(p.y + dy);
            });
        }
    },

    undoCoachDrawing() {
        const drawing = this.ensureCoachDrawing();
        drawing.objects.pop();
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    deleteSelectedCoachObject() {
        const drawing = this.ensureCoachDrawing();
        if (this._coachSelectedObjectIndex === null || this._coachSelectedObjectIndex === undefined) return;
        drawing.objects.splice(this._coachSelectedObjectIndex, 1);
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    clearCoachDrawing() {
        this._coachDrawing = null;
        this._coachSelectedObjectIndex = null;
        this._coachFormationDraft = null;
        this._renderFormationControls?.();
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    renderCoachDrawing(drawing) {
        this._coachDrawing = this.normalizeCoachDrawing(drawing);
        this._coachSelectedObjectIndex = null;
        const canvas = document.getElementById(this._coachCanvasId);
        if (canvas) canvas.style.display = this._coachDrawing ? 'block' : (this._coachDrawingActive ? 'block' : 'none');
        if (canvas) canvas.style.pointerEvents = this._coachDrawingActive ? 'auto' : 'none';
        this.setupCoachCanvas();
        const video = document.getElementById(this._coachVideoId);
        if (canvas && video) {
            const rect = video.getBoundingClientRect();
            canvas.width = Math.max(1, Math.round(rect.width));
            canvas.height = Math.max(1, Math.round(rect.height));
        }
        this.paintCoachCanvas();
    },

    // ===== Formation overlay (multi-player highlight + convex hull) =====

    setCoachFormationMode(mode) {
        this._coachFormationMode = (mode === 'linked') ? 'linked' : 'quick';
        if (this._coachFormationDraft) {
            this._coachFormationDraft.mode = this._coachFormationMode;
            // Switching mode discards any queued (unconsumed) player selections.
            this._coachFormationDraft.queuedPlayerIds = [];
        }
        this._renderFormationControls();
    },

    queueFormationPlayer(playerId) {
        if (!this._coachFormationDraft) {
            this._coachFormationDraft = { mode: this._coachFormationMode || 'quick', anchors: [], queuedPlayerIds: [] };
        }
        const id = String(playerId);
        const queue = this._coachFormationDraft.queuedPlayerIds;
        const at = queue.indexOf(id);
        if (at >= 0) queue.splice(at, 1); else queue.push(id);
        this._renderFormationControls();
    },

    cancelFormation() {
        this._coachFormationDraft = null;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    finalizeFormation() {
        const draft = this._coachFormationDraft;
        if (!draft || draft.anchors.length < 3) {
            this.showError?.('A formation needs at least 3 anchor points.');
            return;
        }
        const hull = this._computeConvexHull(draft.anchors);
        // Andrew's monotone-chain returns < 3 points only when every anchor
        // is collinear (the algorithm pops collinear interior points and
        // both endpoints). The painter and the backend validator both
        // require a 3+ point polygon, so reject early with a coach-readable
        // message instead of silently saving a hull-less formation.
        if (hull.length < 3) {
            this.showError?.('Formation anchors are collinear — nudge one off the line so the hull has area.');
            return;
        }
        const drawing = this.ensureCoachDrawing();
        drawing.objects.push({
            type: 'formation',
            color: this._coachDrawingColor,
            width: this._coachDrawingWidth,
            anchors: draft.anchors.map((a) => ({ ...a })),
            hull_points: hull,
        });
        this._coachFormationDraft = null;
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    // Andrew's monotone-chain convex hull (counter-clockwise, no duplicates).
    // Inputs and outputs are normalized 0..1 {x, y} points.
    _computeConvexHull(points) {
        if (!Array.isArray(points) || points.length < 3) return points.slice();
        const pts = points.map((p) => ({ x: Number(p.x) || 0, y: Number(p.y) || 0 }))
            .sort((a, b) => (a.x - b.x) || (a.y - b.y));
        const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
        const lower = [];
        for (const p of pts) {
            while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
            lower.push(p);
        }
        const upper = [];
        for (let i = pts.length - 1; i >= 0; i -= 1) {
            const p = pts[i];
            while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
            upper.push(p);
        }
        upper.pop(); lower.pop();
        return lower.concat(upper);
    },

    // Repaint the in-progress draft on top of the existing canvas paint —
    // shows the user where they've clicked before they hit Done.
    _renderFormationDraftPreview() {
        this.paintCoachCanvas();
        const draft = this._coachFormationDraft;
        if (!draft || !draft.anchors.length) return;
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const color = this._coachDrawingColor || '#38bdf8';
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        draft.anchors.forEach((a, idx) => {
            const x = a.x * canvas.width, y = a.y * canvas.height;
            ctx.beginPath();
            ctx.arc(x, y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.font = '700 11px system-ui, sans-serif';
            ctx.fillText(a.label || String(idx + 1), x + 12, y - 6);
        });
        ctx.restore();
        this._renderFormationControls();
    },

    // Render the per-tool controls panel beneath the toolbar. Hidden when
    // any tool other than Formation is active.
    _renderFormationControls() {
        const el = document.getElementById('coach-formation-controls');
        if (!el) return;
        if (this._coachDrawingTool !== 'formation') {
            el.hidden = true;
            el.innerHTML = '';
            return;
        }
        el.hidden = false;
        const draft = this._coachFormationDraft;
        const anchorCount = draft?.anchors?.length || 0;
        const mode = this._coachFormationMode || 'quick';
        const players = this._coachBundle?.players || [];
        const queued = new Set((draft?.queuedPlayerIds || []).map(String));
        const queueOrderFor = (pid) => {
            const list = draft?.queuedPlayerIds || [];
            const at = list.findIndex((q) => String(q) === String(pid));
            return at >= 0 ? at + 1 : null;
        };
        const linkedRoster = mode === 'linked'
            ? `<div class="coach-formation-roster" role="listbox" aria-label="Players to anchor">
                 ${players.length
                    ? players.map((p) => {
                        const order = queueOrderFor(p.id);
                        const sel = queued.has(String(p.id));
                        return `<button type="button" class="coach-check-option ${sel ? 'is-selected' : ''}"
                                    aria-pressed="${sel}" onclick="app.queueFormationPlayer('${this.esc(p.id)}')">
                                    <span class="coach-check-box" aria-hidden="true">${order || ''}</span>
                                    <span class="coach-check-label">${this.esc(this.playerLabel(p))}</span>
                                </button>`;
                    }).join('')
                    : '<div class="coach-check-empty">No roster players yet.</div>'}
               </div>
               <p class="coach-formation-hint">Tap players in the order you want to place them, then click their position on the field.</p>`
            : '<p class="coach-formation-hint">Click each player’s position on the freeze frame, then press Done.</p>';
        el.innerHTML = `
            <div class="coach-formation-head">
                <strong>Formation</strong>
                <div class="coach-formation-modes" role="tablist">
                    <button type="button" role="tab" aria-selected="${mode === 'quick'}"
                        class="mini-action-btn ${mode === 'quick' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('quick')">Quick</button>
                    <button type="button" role="tab" aria-selected="${mode === 'linked'}"
                        class="mini-action-btn ${mode === 'linked' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('linked')">Linked</button>
                </div>
            </div>
            ${linkedRoster}
            <div class="coach-formation-actions">
                <span class="coach-formation-count">${anchorCount} anchor${anchorCount === 1 ? '' : 's'} (min 3, max 16)</span>
                <button type="button" class="mini-action-btn" onclick="app.cancelFormation()" ${draft ? '' : 'disabled'}>Cancel</button>
                <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.finalizeFormation()" ${anchorCount >= 3 ? '' : 'disabled'}>Done</button>
            </div>
        `;
    },

    // ===== /feedback view =====

    async renderMyFeedback() {
        const linkedStrip = document.getElementById('feedback-linked-strip');
        const playlistsList = document.getElementById('feedback-playlists-list');
        const notesList = document.getElementById('feedback-notes-list');
        if (linkedStrip) linkedStrip.innerHTML = '';
        if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (notesList) notesList.innerHTML = '<div class="session-empty">Loading…</div>';
        try {
            const data = await this.loadMyFeedback();
            this._feedbackData = data;
            this.renderFeedbackLinkedStrip(data);
            this.renderFeedbackPlaylists(data);
            this.renderFeedbackNotes(data);
        } catch (err) {
            if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Could not load feedback.</div>';
            if (notesList) notesList.innerHTML = '';
            this.showError(err.message);
        }
    },

    renderFeedbackLinkedStrip(data) {
        const el = document.getElementById('feedback-linked-strip');
        if (!el) return;
        const players = data?.players || [];
        if (!players.length) {
            el.innerHTML = '<span class="feedback-linked-empty">No roster player is linked to your account yet. Ask a coach to link you.</span>';
            return;
        }
        el.innerHTML = `<span class="feedback-linked-label">Linked players:</span>` + players.map((p) => `<span class="feedback-linked-pill">${this.esc(this.playerLabel(p))}</span>`).join('');
    },

    renderFeedbackPlaylists(data) {
        const container = document.getElementById('feedback-playlists-list');
        if (!container) return;
        const playlists = data?.playlists || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.playlist_id).map((r) => Number(r.playlist_id)));
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists have been shared with you yet.</div>';
            return;
        }
        container.innerHTML = playlists.map((p) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(p.title)}</strong>
                    <span>${p.note_ids?.length || 0} clip${p.note_ids?.length === 1 ? '' : 's'} · ${reviewed.has(Number(p.id)) ? 'Reviewed' : 'New'}</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openFeedbackPlaylist(${p.id})">Play</button>
                    <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">Mark reviewed</button>
                </div>
            </article>
        `).join('');
    },

    renderFeedbackNotes(data) {
        const container = document.getElementById('feedback-notes-list');
        if (!container) return;
        const notes = data?.notes || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.note_id).map((r) => Number(r.note_id)));
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes have been shared with you yet.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(n.title)}</strong>
                    <span>${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${reviewed.has(Number(n.id)) ? 'Reviewed' : 'New'}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openFeedbackNote(${n.id})">Watch</button>
                    <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ note_id: ${n.id} })">Reviewed</button>
                </div>
            </article>
        `).join('');
    },

    openFeedbackNote(noteId) {
        const note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    openFeedbackPlaylist(playlistId) {
        const playlist = (this._feedbackData?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'feedback' });
    },

    // ===== Focused feedback / playlist player modal =====

    async openFeedbackPlayer({ mode, note = null, playlist = null, playerSource = 'feedback' }) {
        const tpl = document.getElementById('feedback-player-template');
        if (!tpl) { this.showError('Feedback player template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Snapshot the canvas/video ids the telestrator points at, so we can restore on close.
        const prevCanvasId = this._coachCanvasId;
        const prevVideoId = this._coachVideoId;
        // Rebind the painter to the modal's elements.
        this._coachCanvasId = 'feedback-drawing-canvas';
        this._coachVideoId = 'feedback-player-video';

        const cleanup = () => {
            this._stopFeedbackHeartbeat();
            this.stopFeedbackPlaylistSession();
            this.destroyHlsPlayer();
            this.deactivateCoachCanvas();
            // Modal canvas was cloned fresh from the template and is removed
            // from the DOM when the modal closes. Detach the window-resize
            // listener bound to it so the closure (and the canvas it captured)
            // can be garbage-collected.
            this.teardownCoachCanvasListeners('feedback-drawing-canvas');
            this._coachDrawing = null;
            this._coachCanvasId = prevCanvasId;
            this._coachVideoId = prevVideoId;
            this._feedbackPlayer = null;
        };

        const onMount = () => {
            this._feedbackPlayer = { body, mode, note, playlist, playerSource };
            if (mode === 'note') {
                body.querySelector('[data-field="title"]').textContent = note.title || 'Coaching note';
                body.querySelector('[data-field="subtitle"]').textContent = `${this.matchLabel(note.match_id)} · ${this.formatClock(note.timestamp_seconds)} · ${this.slotLabel(note.slot)}`;
                body.querySelector('[data-field="body"]').textContent = note.body || '';
                this._loadFeedbackVideoForNote(note);
            } else if (mode === 'playlist') {
                body.querySelector('[data-field="title"]').textContent = playlist.title || 'Review playlist';
                body.querySelector('[data-field="subtitle"]').textContent = `${(playlist.note_ids || []).length} clips`;
                body.querySelector('[data-field="body"]').textContent = playlist.description || '';
                this.startCoachingPlaylistSession(playlist, { playerSource });
            }
        };

        await this.formModal({
            title: mode === 'playlist' ? 'Review Session' : 'Coaching Note',
            kicker: 'Feedback',
            body,
            confirmLabel: 'Mark reviewed',
            cancelLabel: 'Close',
            size: 'wide',
            onMount,
            onSubmit: async (close) => {
                try {
                    if (mode === 'note' && note) await this.markFeedbackReviewed({ note_id: note.id });
                    else if (mode === 'playlist' && playlist) await this.markFeedbackReviewed({ playlist_id: playlist.id });
                    this.showSuccess('Marked reviewed.');
                    await this.renderMyFeedback();
                } catch (err) { this.showError(err.message); }
                close(true);
            },
        });
        cleanup();
    },

    async _loadFeedbackVideoForNote(note) {
        const video = document.getElementById('feedback-player-video');
        if (!video) return;
        const { hlsUrl, mp4Url } = this.getStreamUrls(note.match_id, note.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            video.currentTime = Math.max(0, Number(note.timestamp_seconds || 0));
            this.setupCoachCanvas();
            this.renderCoachDrawing(note.drawing || {});
            video.play().catch(() => {});
        };
        video.addEventListener('loadedmetadata', onLoaded);
        this._startFeedbackHeartbeat(note.match_id, note.slot, video);
    },

    _startFeedbackHeartbeat(matchId, slot, videoEl) {
        this._stopFeedbackHeartbeat();
        if (!matchId || !slot) return;
        const url = `/api/matches/${encodeURIComponent(matchId)}/heartbeat?slot=${encodeURIComponent(slot)}`;
        const ping = async ({ skipPausedCheck = false } = {}) => {
            if (!skipPausedCheck && videoEl && (videoEl.paused || videoEl.ended)) return;
            try {
                const resp = await fetch(url, { method: 'POST', credentials: 'same-origin' });
                if (resp.status === 403) {
                    if (videoEl) videoEl.pause();
                    this.showError?.('This stream was disconnected by an administrator.');
                    this._stopFeedbackHeartbeat();
                    this.destroyHlsPlayer();
                }
            } catch { /* transient — try again next tick */ }
        };
        ping({ skipPausedCheck: true });
        this._feedbackHeartbeatTimer = window.setInterval(() => ping(), 10000);
    },

    _stopFeedbackHeartbeat() {
        if (this._feedbackHeartbeatTimer) {
            window.clearInterval(this._feedbackHeartbeatTimer);
            this._feedbackHeartbeatTimer = null;
        }
    },

    // ===== Playlist controller (operates on whichever video the modal exposes) =====

    playlistItems(playlist) {
        if (Array.isArray(playlist?.items) && playlist.items.length) return playlist.items;
        const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
        const byId = new Map(notes.map((note) => [Number(note.id), note]));
        return (playlist?.note_ids || []).map((id) => byId.get(Number(id))).filter(Boolean);
    },

    startCoachingPlaylistSession(playlist, { playerSource = 'feedback' } = {}) {
        const items = this.playlistItems(playlist);
        if (!items.length) {
            this.showError('This playlist has no playable notes.');
            return;
        }
        this.stopFeedbackPlaylistSession();
        this._coachPlaylistSession = {
            playlist, items, index: 0,
            frozeCurrentItem: false, paused: false, opening: false,
            playerSource,
        };
        this.openCoachingPlaylistItem(0);
    },

    async openCoachingPlaylistItem(index) {
        const session = this._coachPlaylistSession;
        if (!session) return;
        if (index < 0 || index >= session.items.length) {
            this.finishCoachingPlaylistSession();
            return;
        }
        const item = session.items[index];
        session.index = index;
        session.frozeCurrentItem = false;
        session.opening = true;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (!video) { session.opening = false; return; }
        const { hlsUrl, mp4Url } = this.getStreamUrls(item.match_id, item.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);
        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            const start = Math.max(0, Number(item.timestamp_seconds || 0) - Number(session.playlist.pre_roll_seconds ?? 5));
            video.currentTime = start;
            video.play().catch(() => {});
            session.opening = false;
            this.startPlaylistMonitor();
            this._startFeedbackHeartbeat(item.match_id, item.slot, video);
        };
        video.addEventListener('loadedmetadata', onLoaded);
    },

    startPlaylistMonitor() {
        this.stopPlaylistMonitor();
        this._coachPlaylistMonitor = window.setInterval(() => {
            const session = this._coachPlaylistSession;
            const video = document.getElementById('feedback-player-video');
            if (!session || !video || session.opening || session.paused) return;
            const item = session.items[session.index];
            const timestamp = Number(item.timestamp_seconds || 0);
            const end = timestamp + Number(session.playlist.post_roll_seconds ?? 8);
            if (!session.frozeCurrentItem && video.currentTime >= timestamp) {
                session.frozeCurrentItem = true;
                video.pause();
                video.currentTime = timestamp;
                this.renderCoachDrawing(item.drawing || {});
                this.renderPlaylistSessionRail();
                this._coachPlaylistFreezeTimer = window.setTimeout(() => {
                    if (this._coachPlaylistSession !== session || session.paused) return;
                    video.play().catch(() => {});
                }, 1500);
                return;
            }
            if (video.currentTime >= end || video.ended) {
                this.openCoachingPlaylistItem(session.index + 1);
            }
        }, 250);
    },

    stopPlaylistMonitor() {
        if (this._coachPlaylistMonitor) {
            window.clearInterval(this._coachPlaylistMonitor);
            this._coachPlaylistMonitor = null;
        }
        if (this._coachPlaylistFreezeTimer) {
            window.clearTimeout(this._coachPlaylistFreezeTimer);
            this._coachPlaylistFreezeTimer = null;
        }
    },

    renderPlaylistSessionRail() {
        const player = this._feedbackPlayer;
        if (!player) return;
        const rail = player.body.querySelector('[data-field="rail"]');
        if (!rail) return;
        const session = this._coachPlaylistSession;
        if (!session) { rail.hidden = true; rail.innerHTML = ''; return; }
        rail.hidden = false;
        const item = session.items[session.index];
        rail.innerHTML = `
            <div class="feedback-rail-info">
                <span>Review Session</span>
                <strong>${this.esc(session.playlist.title)}</strong>
                <small>${session.index + 1} of ${session.items.length} · ${this.esc(item.title)} · ${this.esc(item.category || 'note')}</small>
            </div>
            <div class="feedback-rail-controls">
                <button type="button" class="mini-action-btn" onclick="app.previousCoachingPlaylistItem()">Prev</button>
                <button type="button" class="mini-action-btn" onclick="app.toggleCoachingPlaylistPause()">${session.paused ? 'Resume' : 'Pause'}</button>
                <button type="button" class="mini-action-btn" onclick="app.restartCoachingPlaylistItem()">Restart</button>
                <button type="button" class="mini-action-btn" onclick="app.nextCoachingPlaylistItem()">Next</button>
            </div>
        `;
    },

    toggleCoachingPlaylistPause() {
        const session = this._coachPlaylistSession;
        const video = document.getElementById('feedback-player-video');
        if (!session || !video) return;
        session.paused = !session.paused;
        if (session.paused) video.pause();
        else video.play().catch(() => {});
        this.renderPlaylistSessionRail();
    },

    restartCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index);
    },

    nextCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index + 1);
    },

    previousCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(Math.max(0, session.index - 1));
    },

    finishCoachingPlaylistSession() {
        this.stopPlaylistMonitor();
        const session = this._coachPlaylistSession;
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (video) video.pause();
        if (session) this.showSuccess('Playlist finished.');
    },

    stopFeedbackPlaylistSession() {
        this.stopPlaylistMonitor();
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
    },

    // Backwards-compat shims for any lingering callers (e.g. teardownGameView).
    stopCoachingPlaylistSession() { this.stopFeedbackPlaylistSession(); },

    // ===== Match-page deep link to /coach?tab=review =====

    updateCoachThisMatchLink(match) {
        const link = document.getElementById('coach-this-match-link');
        if (!link) return;
        if (!match || !this.canCoach()) { link.hidden = true; return; }
        const slot = this.activeSlot || 'full';
        link.href = this._coachUrl('review', match.id, slot);
        link.hidden = false;
    },

    async markFeedbackItemReviewed(data) {
        try {
            await this.markFeedbackReviewed(data);
            this.showSuccess('Marked reviewed.');
            await this.renderMyFeedback();
        } catch (err) { this.showError(err.message); }
    },
};
