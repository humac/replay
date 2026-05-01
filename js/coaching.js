// Coaching workspace, roster links, timestamped notes, drawing overlays, and feedback.

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
        const linkPlayerEl = document.getElementById('coach-link-player');
        if (linkPlayerEl) linkPlayerEl.innerHTML = playerOptions || '<option value="">No players yet</option>';
        this.renderCoachCheckList('coach-note-players', bundle.players.map((p) => ({
            value: p.id,
            label: this.playerLabel(p),
        })), 'No players yet');
        this.renderCoachCheckList('coach-playlist-players', bundle.players.map((p) => ({
            value: p.id,
            label: this.playerLabel(p),
        })), 'No players yet');

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

        this.renderCoachCheckList('coach-playlist-notes', bundle.notes.map((n) => ({
            value: n.id,
            label: this.noteLabel(n),
        })), 'No notes yet');
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

    renderCoachCheckList(id, items, emptyLabel) {
        const el = document.getElementById(id);
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
                    <span>${p.note_ids?.length || 0} notes · ${this.esc(p.visibility)} · ${Number(p.pre_roll_seconds ?? 5)}s pre / ${Number(p.post_roll_seconds ?? 8)}s post</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn" onclick="app.startCoachPlaylist(${p.id})">Play</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachPlaylistEditor(${p.id})">Edit</button>
                </div>
            </article>
        `).join('');
    },

    selectedValues(id) {
        const el = document.getElementById(id);
        if (!el) return [];
        const themedOptions = el.querySelectorAll?.('.coach-check-option.is-selected');
        if (themedOptions?.length) {
            return Array.from(themedOptions).map((opt) => opt.dataset.value).filter(Boolean);
        }
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
                pre_roll_seconds: Number(document.getElementById('coach-playlist-pre-roll')?.value || 5),
                post_roll_seconds: Number(document.getElementById('coach-playlist-post-roll')?.value || 8),
            });
            this.showSuccess('Review playlist created.');
            await this.renderCoachWorkspace();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async openCoachPlaylistEditor(playlistId) {
        const playlist = (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        const body = document.createElement('div');
        body.className = 'coach-mini-form';
        body.innerHTML = `
            <label>Title<input type="text" id="playlist-edit-title" maxlength="160" value="${this.esc(playlist.title)}"></label>
            <label>Pre-roll Seconds<input type="number" id="playlist-edit-pre" min="0" max="60" step="1" value="${Number(playlist.pre_roll_seconds ?? 5)}"></label>
            <label>Post-roll Seconds<input type="number" id="playlist-edit-post" min="0" max="120" step="1" value="${Number(playlist.post_roll_seconds ?? 8)}"></label>
        `;
        const values = await this.formModal({
            title: 'Edit Playlist',
            kicker: 'Review session',
            body,
            confirmLabel: 'Save playlist',
            onSubmit: async (close) => {
                close({
                    title: document.getElementById('playlist-edit-title')?.value.trim(),
                    pre_roll_seconds: Number(document.getElementById('playlist-edit-pre')?.value || 5),
                    post_roll_seconds: Number(document.getElementById('playlist-edit-post')?.value || 8),
                });
            },
        });
        if (!values) return;
        try {
            await this.updateCoachPlaylist(playlist.id, values);
            this.showSuccess('Playlist updated.');
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
        const playerChecklist = this.coachCheckListHtml(players.map((p) => ({
            value: p.id,
            label: this.playerLabel(p),
        })), 'No players yet');
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
                <div id="coach-panel-players" class="coach-check-list compact" role="listbox" aria-label="Linked players">${playerChecklist}</div>
                <input type="text" id="coach-panel-tags" placeholder="tags,comma,separated">
                ${this.renderCoachTelestratorToolbar()}
                <button type="button" class="mini-action-btn" onclick="app.saveCoachPanelNote()">Save at current time</button>
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
        this.activateCoachCanvas();
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

    renderCoachTelestratorToolbar() {
        const tools = [
            ['select', 'Select'],
            ['freehand', 'Line'],
            ['arrow', 'Arrow'],
            ['circle', 'Circle'],
            ['zone', 'Zone'],
            ['label', 'Label'],
            ['spotlight', 'Spot'],
            ['dim', 'Dim'],
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
        canvas.addEventListener('pointerup', (event) => this.coachDrawEnd(event));
        canvas.addEventListener('pointerleave', (event) => this.coachDrawEnd(event));
        canvas._coachBound = true;
        resize();
    },

    activateCoachCanvas() {
        this.setupCoachCanvas();
        const canvas = document.getElementById('coach-drawing-canvas');
        if (!canvas) return;
        this._coachDrawingActive = true;
        canvas.style.display = 'block';
        canvas.style.pointerEvents = 'auto';
        this.updateCoachCanvasToggleLabel();
    },

    deactivateCoachCanvas() {
        const canvas = document.getElementById('coach-drawing-canvas');
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
        this._coachDrawingTool = tool;
        document.querySelectorAll('[data-coach-tool]').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.coachTool === tool);
        });
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
        const drawing = this.ensureCoachDrawing();
        const point = this.coachDrawPoint(event);
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
        const canvas = document.getElementById('coach-drawing-canvas');
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
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    renderCoachDrawing(drawing) {
        this._coachDrawing = this.normalizeCoachDrawing(drawing);
        this._coachSelectedObjectIndex = null;
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
                            <div class="coach-row-actions">
                                <button type="button" class="mini-action-btn" onclick="app.startFeedbackPlaylist(${p.id})">Play</button>
                                <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">Mark reviewed</button>
                            </div>
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

    playlistItems(playlist) {
        if (Array.isArray(playlist?.items) && playlist.items.length) return playlist.items;
        const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
        const byId = new Map(notes.map((note) => [Number(note.id), note]));
        return (playlist?.note_ids || []).map((id) => byId.get(Number(id))).filter(Boolean);
    },

    startCoachPlaylist(playlistId) {
        const playlist = (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (playlist) this.startCoachingPlaylistSession(playlist);
    },

    startFeedbackPlaylist(playlistId) {
        const playlist = (this._feedbackData?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (playlist) this.startCoachingPlaylistSession(playlist);
    },

    startCoachingPlaylistSession(playlist) {
        const items = this.playlistItems(playlist);
        if (!items.length) {
            this.showError('This playlist has no playable notes.');
            return;
        }
        this.stopCoachingPlaylistSession({ keepView: true });
        this._coachPlaylistSession = {
            playlist,
            items,
            index: 0,
            frozeCurrentItem: false,
            paused: false,
            opening: false,
        };
        this.openCoachingPlaylistItem(0);
    },

    openCoachingPlaylistItem(index) {
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
        this.openMatch(item.match_id, { initialSlot: item.slot, pushHistory: false, scrollTop: false });
        window.setTimeout(() => {
            if (this._coachPlaylistSession !== session) return;
            const video = document.getElementById('game-video');
            if (!video) return;
            const start = Math.max(0, Number(item.timestamp_seconds || 0) - Number(session.playlist.pre_roll_seconds ?? 5));
            video.currentTime = start;
            video.play().catch(() => {});
            session.opening = false;
            this.startPlaylistMonitor();
        }, 700);
    },

    startPlaylistMonitor() {
        this.stopPlaylistMonitor();
        this._coachPlaylistMonitor = window.setInterval(() => {
            const session = this._coachPlaylistSession;
            const video = document.getElementById('game-video');
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
        let rail = document.getElementById('coach-playlist-session');
        const wrapper = document.querySelector('.player-wrapper');
        const session = this._coachPlaylistSession;
        if (!wrapper || !session) {
            if (rail) rail.remove();
            return;
        }
        if (!rail) {
            rail = document.createElement('div');
            rail.id = 'coach-playlist-session';
            rail.className = 'coach-playlist-session';
            wrapper.appendChild(rail);
        }
        const item = session.items[session.index];
        rail.innerHTML = `
            <div>
                <span>Review Session</span>
                <strong>${this.esc(session.playlist.title)}</strong>
                <small>${session.index + 1} of ${session.items.length} · ${this.esc(item.title)} · ${this.esc(item.category || 'note')}</small>
            </div>
            <div class="coach-playlist-controls">
                <button type="button" class="mini-action-btn" onclick="app.previousCoachingPlaylistItem()">Prev</button>
                <button type="button" class="mini-action-btn" onclick="app.toggleCoachingPlaylistPause()">${session.paused ? 'Resume' : 'Pause'}</button>
                <button type="button" class="mini-action-btn" onclick="app.restartCoachingPlaylistItem()">Restart</button>
                <button type="button" class="mini-action-btn" onclick="app.nextCoachingPlaylistItem()">Next</button>
                <button type="button" class="mini-action-btn" onclick="app.stopCoachingPlaylistSession()">Exit</button>
            </div>
        `;
    },

    toggleCoachingPlaylistPause() {
        const session = this._coachPlaylistSession;
        const video = document.getElementById('game-video');
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
        const rail = document.getElementById('coach-playlist-session');
        if (rail) rail.remove();
        const video = document.getElementById('game-video');
        if (video) video.pause();
        if (session) this.showSuccess('Playlist finished.');
    },

    stopCoachingPlaylistSession({ keepView = false } = {}) {
        this.stopPlaylistMonitor();
        this._coachPlaylistSession = null;
        const rail = document.getElementById('coach-playlist-session');
        if (rail) rail.remove();
        if (!keepView) {
            const video = document.getElementById('game-video');
            if (video) video.pause();
        }
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
