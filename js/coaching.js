// Coaching workspace, roster links, timestamped notes, drawing overlays, and feedback.

export const coachingMixin = {
    _coachBundle: null,
    _coachDrawing: null,
    _coachDrawingActive: false,

    async showCoachView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        if (!this.canCoach()) {
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('coach-view', 'coach');
        if (pushHistory) this.pushHistoryState({ view: 'coach' }, { replace: replaceHistory, url: '/coach' });
        await this.renderCoachWorkspace();
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async showFeedbackView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        if (!this.authToken) {
            this.showLoginModal();
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('feedback-view', 'feedback');
        if (pushHistory) this.pushHistoryState({ view: 'feedback' }, { replace: replaceHistory, url: '/feedback' });
        await this.renderMyFeedback();
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async renderCoachWorkspace() {
        const roster = document.getElementById('coach-roster-list');
        const notes = document.getElementById('coach-notes-list');
        if (roster) roster.innerHTML = '<div class="session-empty">Loading roster...</div>';
        if (notes) notes.innerHTML = '<div class="session-empty">Loading notes...</div>';
        try {
            this._coachBundle = await this.loadCoachBundle();
            this.renderCoachRoster();
            this.renderCoachSelectors();
            this.renderCoachNotes();
            this.renderCoachPlaylists();
        } catch (err) {
            this.showError(err.message || 'Could not load coaching workspace.');
        }
    },

    renderCoachSelectors() {
        const bundle = this._coachBundle || { players: [], users: [], notes: [] };
        const playerOptions = bundle.players.map((p) => (
            `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`
        )).join('');
        ['coach-link-player', 'coach-note-players', 'coach-playlist-players'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = playerOptions || '<option value="">No players yet</option>';
        });

        const userOptions = bundle.users.map((u) => (
            `<option value="${this.esc(u.id)}">${this.esc(u.display_name || u.username)} (@${this.esc(u.username)})</option>`
        )).join('');
        const userEl = document.getElementById('coach-link-user');
        if (userEl) userEl.innerHTML = userOptions || '<option value="">Create a user first</option>';

        const matchOptions = this.matches.map((m) => (
            `<option value="${this.esc(m.id)}">${this.esc(m.home_team)} vs ${this.esc(m.away_team)} · ${this.esc(this.formatDate(m.date))}</option>`
        )).join('');
        const matchEl = document.getElementById('coach-note-match');
        if (matchEl) matchEl.innerHTML = matchOptions || '<option value="">No matches yet</option>';

        const noteOptions = bundle.notes.map((n) => (
            `<option value="${n.id}">${this.esc(this.noteLabel(n))}</option>`
        )).join('');
        const playlistNotes = document.getElementById('coach-playlist-notes');
        if (playlistNotes) playlistNotes.innerHTML = noteOptions || '<option value="">No notes yet</option>';
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

    renderCoachNotes() {
        const container = document.getElementById('coach-notes-list');
        if (!container) return;
        const notes = this._coachBundle?.notes || [];
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes yet.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(n.title)}</strong>
                    <span>${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${this.esc(n.category)} · ${this.esc(n.visibility)}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn" onclick="app.openCoachNote(${n.id})">Open</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                </div>
            </article>
        `).join('');
    },

    renderCoachPlaylists() {
        const container = document.getElementById('coach-playlists-list');
        if (!container) return;
        const playlists = this._coachBundle?.playlists || [];
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists yet.</div>';
            return;
        }
        container.innerHTML = playlists.map((p) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(p.title)}</strong>
                    <span>${p.note_ids?.length || 0} notes · ${this.esc(p.visibility)}</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
            </article>
        `).join('');
    },

    selectedValues(id) {
        const el = document.getElementById(id);
        if (!el) return [];
        return Array.from(el.selectedOptions || []).map((opt) => opt.value).filter(Boolean);
    },

    async handleCoachAddPlayer() {
        const display_name = document.getElementById('coach-player-name')?.value.trim();
        const jersey_number = document.getElementById('coach-player-number')?.value.trim() || '';
        if (!display_name) {
            this.showError('Player name is required.');
            return;
        }
        try {
            await this.createCoachPlayer({ display_name, jersey_number, active: true });
            document.getElementById('coach-player-name').value = '';
            document.getElementById('coach-player-number').value = '';
            this.showSuccess('Player added.');
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleCoachDeletePlayer(playerId) {
        const ok = await this.confirmAction({
            title: 'Delete player',
            message: 'Delete this roster player and remove their feedback links?',
            confirmLabel: 'Delete player',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(`/api/coach/players/${playerId}`, {
                method: 'DELETE',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to delete player');
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleCoachLinkAccount() {
        const player_id = document.getElementById('coach-link-player')?.value;
        const user_id = document.getElementById('coach-link-user')?.value;
        const relationship = document.getElementById('coach-link-relationship')?.value || 'family';
        if (!player_id || !user_id) {
            this.showError('Pick a player and a user account.');
            return;
        }
        try {
            await this.linkCoachPlayer({ player_id, user_id, relationship });
            this.showSuccess('Account linked.');
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleCoachUnlink(linkId) {
        try {
            await this.unlinkCoachPlayer(linkId);
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    coachNotePayloadFromForm(prefix = 'coach-note') {
        return {
            match_id: document.getElementById(`${prefix}-match`)?.value,
            slot: document.getElementById(`${prefix}-slot`)?.value || 'full',
            timestamp_seconds: Number(document.getElementById(`${prefix}-time`)?.value || 0),
            title: document.getElementById(`${prefix}-title`)?.value.trim(),
            body: document.getElementById(`${prefix}-body`)?.value.trim() || '',
            category: document.getElementById(`${prefix}-category`)?.value || 'other',
            visibility: document.getElementById(`${prefix}-visibility`)?.value || 'private',
            player_ids: this.selectedValues(`${prefix}-players`),
            tags: (document.getElementById(`${prefix}-tags`)?.value || '').split(',').map((s) => s.trim()).filter(Boolean),
            drawing: this._coachDrawing || {},
        };
    },

    async handleCoachCreateNote(payload = null) {
        const body = payload || this.coachNotePayloadFromForm();
        if (!body.match_id || !body.title) {
            this.showError('Match and note title are required.');
            return;
        }
        try {
            await this.createCoachNote(body);
            this.showSuccess('Coaching note saved.');
            ['coach-note-title', 'coach-note-body', 'coach-note-tags'].forEach((id) => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            this.clearCoachDrawing();
            if (document.getElementById('coach-view')?.classList.contains('active')) await this.renderCoachWorkspace();
            if (this.activeMatchId) await this.renderCoachingPanel();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleCoachDeleteNote(noteId) {
        const ok = await this.confirmAction({
            title: 'Delete note',
            message: 'Delete this coaching note?',
            confirmLabel: 'Delete note',
            danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachNote(noteId);
            await this.renderCoachWorkspace();
            if (this.activeMatchId) await this.renderCoachingPanel();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleCoachCreatePlaylist() {
        const title = document.getElementById('coach-playlist-title')?.value.trim();
        if (!title) {
            this.showError('Playlist title is required.');
            return;
        }
        try {
            await this.createCoachPlaylist({
                title,
                description: document.getElementById('coach-playlist-description')?.value.trim() || '',
                visibility: document.getElementById('coach-playlist-visibility')?.value || 'private',
                note_ids: this.selectedValues('coach-playlist-notes').map((v) => Number(v)),
                player_ids: this.selectedValues('coach-playlist-players'),
            });
            this.showSuccess('Review playlist created.');
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async openCoachNote(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this.openMatch(note.match_id, { initialSlot: note.slot });
        window.setTimeout(() => {
            const video = document.getElementById('game-video');
            if (video) video.currentTime = Math.max(0, Number(note.timestamp_seconds || 0));
            this.renderCoachDrawing(note.drawing || {});
        }, 700);
    },

    async renderCoachingPanel() {
        const panel = document.getElementById('coach-match-panel');
        if (!panel) return;
        if (!this.canCoach() || !this.activeMatchId) {
            panel.style.display = 'none';
            return;
        }
        panel.style.display = 'block';
        let bundle = this._coachBundle;
        try {
            bundle = await this.loadCoachBundle(this.activeMatchId);
            this._coachBundle = { ...(this._coachBundle || {}), ...bundle };
        } catch {
            bundle = { players: [], notes: [] };
        }
        const players = bundle.players || [];
        const notes = bundle.notes || [];
        const playerOptions = players.map((p) => `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`).join('');
        panel.innerHTML = `
            <h3>Coach Notes</h3>
            <div class="coach-mini-form">
                <input type="text" id="coach-panel-title" placeholder="Teaching point">
                <textarea id="coach-panel-body" rows="3" placeholder="What should players notice?"></textarea>
                <div class="coach-panel-grid">
                    <select id="coach-panel-category">
                        <option value="shape">Shape</option><option value="pressing">Pressing</option>
                        <option value="transition">Transition</option><option value="decision">Decision</option>
                        <option value="defending">Defending</option><option value="finishing">Finishing</option>
                        <option value="other">Other</option>
                    </select>
                    <select id="coach-panel-visibility">
                        <option value="private">Private</option>
                        <option value="team">Team</option>
                        <option value="player">Player/family</option>
                    </select>
                </div>
                <select id="coach-panel-players" multiple size="3">${playerOptions}</select>
                <input type="text" id="coach-panel-tags" placeholder="tags,comma,separated">
                <div class="coach-draw-actions">
                    <button type="button" class="mini-action-btn" onclick="app.toggleCoachDrawing()">Draw</button>
                    <button type="button" class="mini-action-btn" onclick="app.clearCoachDrawing()">Clear drawing</button>
                    <button type="button" class="mini-action-btn" onclick="app.saveCoachPanelNote()">Save at current time</button>
                </div>
            </div>
            <div class="coach-panel-notes">
                ${notes.length ? notes.map((n) => `
                    <button type="button" class="coach-note-jump" onclick="app.seekCoachNote(${n.id})">
                        <span>${this.esc(this.formatClock(n.timestamp_seconds))}</span>
                        <strong>${this.esc(n.title)}</strong>
                    </button>
                `).join('') : '<div class="session-empty">No notes for this match yet.</div>'}
            </div>
        `;
        this.setupCoachCanvas();
    },

    async saveCoachPanelNote() {
        const video = document.getElementById('game-video');
        const title = document.getElementById('coach-panel-title')?.value.trim();
        if (!title) {
            this.showError('Add a title for the coaching note.');
            return;
        }
        const payload = {
            match_id: this.activeMatchId,
            slot: this.activeSlot || 'full',
            timestamp_seconds: video?.currentTime || 0,
            title,
            body: document.getElementById('coach-panel-body')?.value.trim() || '',
            category: document.getElementById('coach-panel-category')?.value || 'other',
            visibility: document.getElementById('coach-panel-visibility')?.value || 'private',
            player_ids: this.selectedValues('coach-panel-players'),
            tags: (document.getElementById('coach-panel-tags')?.value || '').split(',').map((s) => s.trim()).filter(Boolean),
            drawing: this._coachDrawing || {},
        };
        await this.handleCoachCreateNote(payload);
    },

    seekCoachNote(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        if (this.activeSlot !== note.slot) this.playSlot(note.match_id, note.slot);
        window.setTimeout(() => {
            const video = document.getElementById('game-video');
            if (video) video.currentTime = Math.max(0, Number(note.timestamp_seconds || 0));
            this.renderCoachDrawing(note.drawing || {});
        }, 300);
    },

    setupCoachCanvas() {
        const canvas = document.getElementById('coach-drawing-canvas');
        const video = document.getElementById('game-video');
        if (!canvas || !video || canvas._coachBound) return;
        const resize = () => {
            const rect = video.getBoundingClientRect();
            canvas.width = Math.max(1, Math.round(rect.width));
            canvas.height = Math.max(1, Math.round(rect.height));
            this.paintCoachCanvas();
        };
        window.addEventListener('resize', resize);
        video.addEventListener('loadedmetadata', resize);
        canvas.addEventListener('pointerdown', (event) => this.coachDrawStart(event));
        canvas.addEventListener('pointermove', (event) => this.coachDrawMove(event));
        canvas.addEventListener('pointerup', () => this.coachDrawEnd());
        canvas.addEventListener('pointerleave', () => this.coachDrawEnd());
        canvas._coachBound = true;
        resize();
    },

    toggleCoachDrawing() {
        const canvas = document.getElementById('coach-drawing-canvas');
        if (!canvas) return;
        this._coachDrawingActive = !this._coachDrawingActive;
        canvas.style.display = this._coachDrawingActive ? 'block' : 'none';
        canvas.style.pointerEvents = this._coachDrawingActive ? 'auto' : 'none';
        this.setupCoachCanvas();
    },

    coachDrawPoint(event) {
        const canvas = document.getElementById('coach-drawing-canvas');
        const rect = canvas.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) / Math.max(1, rect.width),
            y: (event.clientY - rect.top) / Math.max(1, rect.height),
        };
    },

    coachDrawStart(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        if (!this._coachDrawing) this._coachDrawing = { version: 1, strokes: [] };
        const stroke = { color: '#38bdf8', width: 3, points: [this.coachDrawPoint(event)] };
        this._coachDrawing.strokes.push(stroke);
        this._coachCurrentStroke = stroke;
        this.paintCoachCanvas();
    },

    coachDrawMove(event) {
        if (!this._coachDrawingActive || !this._coachCurrentStroke) return;
        event.preventDefault();
        this._coachCurrentStroke.points.push(this.coachDrawPoint(event));
        this.paintCoachCanvas();
    },

    coachDrawEnd() {
        this._coachCurrentStroke = null;
    },

    paintCoachCanvas() {
        const canvas = document.getElementById('coach-drawing-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const strokes = this._coachDrawing?.strokes || [];
        strokes.forEach((stroke) => {
            ctx.strokeStyle = stroke.color || '#38bdf8';
            ctx.lineWidth = stroke.width || 3;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.beginPath();
            (stroke.points || []).forEach((pt, idx) => {
                const x = pt.x * canvas.width;
                const y = pt.y * canvas.height;
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
        });
    },

    clearCoachDrawing() {
        this._coachDrawing = null;
        this._coachDrawingActive = false;
        const canvas = document.getElementById('coach-drawing-canvas');
        if (canvas) canvas.style.display = 'none';
        if (canvas) canvas.style.pointerEvents = 'none';
        this.paintCoachCanvas();
    },

    renderCoachDrawing(drawing) {
        this._coachDrawing = drawing && drawing.strokes ? drawing : null;
        const canvas = document.getElementById('coach-drawing-canvas');
        if (canvas) canvas.style.display = this._coachDrawing ? 'block' : (this._coachDrawingActive ? 'block' : 'none');
        if (canvas) canvas.style.pointerEvents = this._coachDrawingActive ? 'auto' : 'none';
        this.setupCoachCanvas();
        const video = document.getElementById('game-video');
        if (canvas && video) {
            const rect = video.getBoundingClientRect();
            canvas.width = Math.max(1, Math.round(rect.width));
            canvas.height = Math.max(1, Math.round(rect.height));
        }
        this.paintCoachCanvas();
    },

    async renderMyFeedback() {
        const container = document.getElementById('feedback-content');
        if (!container) return;
        container.innerHTML = '<div class="options-card"><div class="session-empty">Loading feedback...</div></div>';
        try {
            const data = await this.loadMyFeedback();
            const reviewedNotes = new Set((data.reviews || []).filter((r) => r.note_id).map((r) => Number(r.note_id)));
            const reviewedPlaylists = new Set((data.reviews || []).filter((r) => r.playlist_id).map((r) => Number(r.playlist_id)));
            container.innerHTML = `
                <div class="options-card">
                    <div class="admin-card-head"><h3>Linked Players</h3><span class="admin-card-kicker">${(data.players || []).length}</span></div>
                    ${(data.players || []).length ? data.players.map((p) => `<span class="coach-link-pill">${this.esc(this.playerLabel(p))}</span>`).join('') : '<div class="session-empty">No roster player is linked to this account yet.</div>'}
                </div>
                <div class="options-card mt-4">
                    <div class="admin-card-head"><h3>Review Playlists</h3><span class="admin-card-kicker">${(data.playlists || []).length}</span></div>
                    ${(data.playlists || []).length ? data.playlists.map((p) => `
                        <article class="coach-row">
                            <div><strong>${this.esc(p.title)}</strong><span>${p.note_ids?.length || 0} notes · ${reviewedPlaylists.has(Number(p.id)) ? 'Reviewed' : 'New'}</span><p>${this.esc(p.description || '')}</p></div>
                            <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">Mark reviewed</button>
                        </article>
                    `).join('') : '<div class="session-empty">No playlists have been shared with you yet.</div>'}
                </div>
                <div class="options-card mt-4">
                    <div class="admin-card-head"><h3>Coaching Notes</h3><span class="admin-card-kicker">${(data.notes || []).length}</span></div>
                    ${(data.notes || []).length ? data.notes.map((n) => `
                        <article class="coach-row">
                            <div><strong>${this.esc(n.title)}</strong><span>${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${reviewedNotes.has(Number(n.id)) ? 'Reviewed' : 'New'}</span><p>${this.esc(n.body || '')}</p></div>
                            <div class="coach-row-actions">
                                <button type="button" class="mini-action-btn" onclick="app.openFeedbackNote(${n.id})">Watch</button>
                                <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ note_id: ${n.id} })">Reviewed</button>
                            </div>
                        </article>
                    `).join('') : '<div class="session-empty">No coaching notes have been shared with you yet.</div>'}
                </div>
            `;
            this._feedbackData = data;
        } catch (err) {
            container.innerHTML = '<div class="options-card"><div class="session-empty">Could not load feedback.</div></div>';
            this.showError(err.message);
        }
    },

    openFeedbackNote(noteId) {
        const note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this.openMatch(note.match_id, { initialSlot: note.slot });
        window.setTimeout(() => {
            const video = document.getElementById('game-video');
            if (video) video.currentTime = Number(note.timestamp_seconds || 0);
            this.renderCoachDrawing(note.drawing || {});
        }, 700);
    },

    async markFeedbackItemReviewed(data) {
        try {
            await this.markFeedbackReviewed(data);
            this.showSuccess('Marked reviewed.');
            await this.renderMyFeedback();
        } catch (err) {
            this.showError(err.message);
        }
    },
};
