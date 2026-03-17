const app = {
    MAX_VIDEO_SIZE_BYTES: 12 * 1024 * 1024 * 1024,
    UPLOAD_TIMEOUT_MS: 4 * 60 * 60 * 1000,
    CHUNK_RETRY_COUNT: 3,
    UPLOAD_SESSION_STORAGE_KEY: 'replay_upload_sessions_v1',
    matches: [],
    activeMatchId: null,
    activeSlot: null,
    castSession: null,
    hlsPlayer: null,
    airplayAvailable: false,
    airplayActive: false,
    castAvailable: false,
    castSupportedBrowser: false,
    castSdkReady: false,
    castSecureContextAllowed: false,
    _castInitialized: false,
    _playRequestToken: 0,
    _pollTimer: null,
    authToken: null,
    diagnostics: null,

    async init() {
        await this.checkAuth();
        await this.loadMatches();
        this.bindEvents();
        this.renderSeasonView();
        this.initializeHistory();
        this.initAirPlay();
        this.initCast();
        this.checkTranscodePolling();
    },

    initializeHistory() {
        const current = window.history.state;
        if (!current || !current.view) {
            window.history.replaceState({ view: 'season' }, '', window.location.href);
            return;
        }
        this.restoreHistoryState(current, { scrollTop: false });
    },

    pushHistoryState(state, { replace = false } = {}) {
        if (replace) {
            window.history.replaceState(state, '', window.location.href);
            return;
        }
        window.history.pushState(state, '', window.location.href);
    },

    restoreHistoryState(state, { scrollTop = false } = {}) {
        if (!state?.view) {
            this.showSeasonView({ pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'game' && state.matchId) {
            this.openMatch(state.matchId, { pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'add-match') {
            if (!this.authToken) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            if (state.mode === 'edit' && state.matchId) {
                this.editMatch(state.matchId, { pushHistory: false, scrollTop });
                return;
            }
            this.cancelEdit();
            this.openAddMatchView({ pushHistory: false, scrollTop });
            return;
        }

        this.showSeasonView({ pushHistory: false, scrollTop });
    },

    activateView(viewId, navView = null) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const activeView = document.getElementById(viewId);
        if (activeView) activeView.classList.add('active');

        document.querySelectorAll('.nav-links a').forEach(l => l.classList.remove('active'));
        if (navView) {
            const navLink = document.querySelector(`.nav-links a[data-view="${navView}"]`);
            if (navLink) navLink.classList.add('active');
        }
    },

    teardownGameView() {
        this.activeMatchId = null;
        this.activeSlot = null;
        this.destroyHlsPlayer();
        const videoEl = document.getElementById('game-video');
        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
        }
        const overlay = document.getElementById('cast-overlay');
        if (overlay && !this.castSession) {
            overlay.style.display = 'none';
        }
        this.updateRemotePlaybackNote();
    },

    showSeasonView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('season-view', 'season');
        this.renderSeasonView();
        if (pushHistory) {
            this.pushHistoryState({ view: 'season' }, { replace: replaceHistory });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    openAddMatchView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('add-match-view', 'add-match');
        if (this.authToken) this.refreshAdminDiagnostics();
        if (pushHistory) {
            this.pushHistoryState({ view: 'add-match', mode: 'create' }, { replace: replaceHistory });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    goHome() {
        this.cancelEdit();
        this.showSeasonView({ replaceHistory: true });
    },

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async loadMatches() {
        try {
            const resp = await fetch('/api/matches');
            this.matches = await resp.json();
        } catch (e) {
            console.error('Failed to load matches', e);
            this.matches = [];
        }
    },

    // ------------------------------------------------------------------
    // Video status helpers
    // ------------------------------------------------------------------

    slotStatus(m, slot) {
        const vs = m.video_status || {};
        if (vs[slot]) return vs[slot];
        // Backward compat: file present but no status field
        if (m.videos?.[slot]) return 'ready';
        return 'none';
    },

    anyTranscoding() {
        return this.matches.some(m => {
            const vs = m.video_status || {};
            return Object.values(vs).some(s => s === 'transcoding');
        });
    },

    matchTranscoding(m) {
        const vs = m.video_status || {};
        return Object.values(vs).some(s => s === 'transcoding');
    },

    // ------------------------------------------------------------------
    // Transcode polling
    // ------------------------------------------------------------------

    checkTranscodePolling() {
        if (this.anyTranscoding()) {
            this.startTranscodePolling();
        }
    },

    startTranscodePolling() {
        if (this._pollTimer) return;
        this._pollTimer = setInterval(async () => {
            await this.loadMatches();
            this.renderSeasonView();

            // Refresh active game view if open
            if (this.activeMatchId) {
                const match = this.matches.find(m => m.id === this.activeMatchId);
                if (match) this.refreshGameView(match);
            }

            if (!this.anyTranscoding()) {
                clearInterval(this._pollTimer);
                this._pollTimer = null;
            }
        }, 5000);
    },

    stopTranscodePolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    },

    // ------------------------------------------------------------------
    // Auth
    // ------------------------------------------------------------------

    getAuthHeaders() {
        const headers = {};
        if (this.authToken) {
            headers['Authorization'] = 'Bearer ' + this.authToken;
        }
        return headers;
    },

    async checkAuth() {
        const token = sessionStorage.getItem('replay_admin_token');
        if (!token) {
            this.setLoggedOut();
            return;
        }
        try {
            const resp = await fetch('/api/auth/check', {
                headers: { 'Authorization': 'Bearer ' + token },
            });
            const data = await resp.json();
            if (data.authenticated) {
                this.authToken = token;
                this.setLoggedIn();
            } else {
                sessionStorage.removeItem('replay_admin_token');
                this.setLoggedOut();
            }
        } catch {
            this.setLoggedOut();
        }
    },

    setLoggedIn() {
        document.getElementById('nav-add-match').style.display = '';
        document.getElementById('nav-login-btn').style.display = 'none';
        document.getElementById('nav-logout-btn').style.display = '';
        this.setAdminPanelVisibility(true);
        this.refreshAdminDiagnostics();
    },

    setLoggedOut() {
        this.authToken = null;
        document.getElementById('nav-add-match').style.display = 'none';
        document.getElementById('nav-login-btn').style.display = '';
        document.getElementById('nav-logout-btn').style.display = 'none';
        this.setAdminPanelVisibility(false);
        // If on add-match view, switch to season view
        if (document.getElementById('add-match-view')?.classList.contains('active')) {
            this.cancelEdit();
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
        }
    },

    showLoginModal() {
        document.getElementById('login-modal').style.display = 'flex';
        document.getElementById('login-error').style.display = 'none';
        document.getElementById('login-username').value = '';
        document.getElementById('login-password').value = '';
        document.getElementById('login-username').focus();
    },

    hideLoginModal() {
        document.getElementById('login-modal').style.display = 'none';
    },

    async handleLogin(e) {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');

        try {
            const resp = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            if (!resp.ok) {
                errorEl.textContent = 'Invalid username or password';
                errorEl.style.display = 'block';
                return;
            }
            const data = await resp.json();
            this.authToken = data.token;
            sessionStorage.setItem('replay_admin_token', data.token);
            this.setLoggedIn();
            this.hideLoginModal();
            this.renderSeasonView();
        } catch {
            errorEl.textContent = 'Login failed. Please try again.';
            errorEl.style.display = 'block';
        }
    },

    async logout() {
        try {
            await fetch('/api/logout', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
        } catch { /* ignore */ }
        sessionStorage.removeItem('replay_admin_token');
        this.setLoggedOut();
        this.renderSeasonView();
    },

    // ------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------

    bindEvents() {
        window.addEventListener('popstate', (event) => {
            this.restoreHistoryState(event.state, { scrollTop: false });
        });

        // Nav links
        document.querySelectorAll('.nav-links a').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const view = e.target.dataset.view;
                if (view === 'season') {
                    this.cancelEdit();
                    this.showSeasonView();
                } else if (view === 'add-match') {
                    this.cancelEdit();
                    this.openAddMatchView();
                }
            });
        });

        // Add match form
        document.getElementById('add-match-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFormSubmit();
        });

        document.getElementById('refresh-diagnostics-btn')?.addEventListener('click', () => {
            this.refreshAdminDiagnostics();
        });
        document.getElementById('backfill-hls-btn')?.addEventListener('click', () => {
            this.backfillExistingHls();
        });
        document.getElementById('cleanup-uploads-btn')?.addEventListener('click', () => {
            this.cleanupStaleUploads();
        });

        // File input labels
        ['f-home-logo', 'f-away-logo', 'f-video-full', 'f-video-first', 'f-video-second'].forEach(id => {
            const input = document.getElementById(id);
            const label = document.getElementById(id + '-label');
            if (input && label) {
                input.addEventListener('change', () => {
                    label.textContent = input.files[0] ? input.files[0].name : 'No file chosen';
                    this.updatePendingUploadState(id, input.files[0] || null);
                });
            }
        });
    },

    // ------------------------------------------------------------------
    // Form
    // ------------------------------------------------------------------

    setAdminPanelVisibility(visible) {
        const panel = document.getElementById('admin-ops-card');
        if (!panel) return;
        panel.style.display = visible ? 'block' : 'none';
        if (!visible) {
            const diagnosticsGrid = document.getElementById('diagnostics-grid');
            const serverList = document.getElementById('upload-sessions-list');
            const localList = document.getElementById('local-upload-sessions-list');
            if (diagnosticsGrid) diagnosticsGrid.innerHTML = '';
            if (serverList) serverList.innerHTML = '';
            if (localList) localList.innerHTML = '';
        }
    },

    async refreshAdminDiagnostics() {
        if (!this.authToken) return;

        const diagnosticsGrid = document.getElementById('diagnostics-grid');
        const serverList = document.getElementById('upload-sessions-list');
        const localList = document.getElementById('local-upload-sessions-list');
        if (diagnosticsGrid) diagnosticsGrid.innerHTML = '<div class="diagnostic-card"><span class="diagnostic-label">Loading</span><strong class="diagnostic-value">Updating...</strong></div>';
        if (serverList) serverList.innerHTML = '<div class="session-empty">Loading upload sessions...</div>';
        if (localList) localList.innerHTML = '<div class="session-empty">Checking resumable uploads...</div>';

        try {
            const resp = await fetch('/api/admin/diagnostics', {
                headers: this.getAuthHeaders(),
            });
            if (resp.status === 401) {
                this.setLoggedOut();
                sessionStorage.removeItem('replay_admin_token');
                this.showLoginModal();
                return;
            }
            if (!resp.ok) throw new Error('Failed to load diagnostics');
            this.diagnostics = await resp.json();
            this.renderAdminDiagnostics();
        } catch (error) {
            if (diagnosticsGrid) diagnosticsGrid.innerHTML = `<div class="session-empty">${this.esc(error.message)}</div>`;
            if (serverList) serverList.innerHTML = '<div class="session-empty">Diagnostics unavailable.</div>';
            if (localList) localList.innerHTML = this.renderLocalResumeSessions();
        }
    },

    renderAdminDiagnostics() {
        const diagnosticsGrid = document.getElementById('diagnostics-grid');
        const serverList = document.getElementById('upload-sessions-list');
        const localList = document.getElementById('local-upload-sessions-list');
        if (!this.diagnostics || !diagnosticsGrid || !serverList || !localList) return;

        const { counts, disk, upload_limits, upload_sessions, hls } = this.diagnostics;
        diagnosticsGrid.innerHTML = `
            <div class="diagnostic-card">
                <span class="diagnostic-label">Free Disk</span>
                <strong class="diagnostic-value">${this.formatBytes(disk.free_bytes)}</strong>
                <span class="diagnostic-note">Need at least ${this.formatBytes(disk.min_free_bytes)} minimum</span>
            </div>
            <div class="diagnostic-card ${disk.enough_space ? '' : 'danger'}">
                <span class="diagnostic-label">Upload Headroom</span>
                <strong class="diagnostic-value">${disk.enough_space ? 'Ready' : 'Low'}</strong>
                <span class="diagnostic-note">${disk.enough_space ? 'Disk can accept new chunk sessions.' : 'Large uploads may be rejected.'}</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">Matches</span>
                <strong class="diagnostic-value">${counts.matches}</strong>
                <span class="diagnostic-note">${counts.ready_slots} ready slots, ${counts.transcoding_slots} processing</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">HLS Backfill</span>
                <strong class="diagnostic-value">${counts.hls_missing_slots}</strong>
                <span class="diagnostic-note">${hls.backfill_running ? 'Backfill is running now.' : 'Ready MP4 slots still missing HLS assets.'}</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">Chunk Size</span>
                <strong class="diagnostic-value">${this.formatBytes(upload_limits.chunk_size_bytes)}</strong>
                <span class="diagnostic-note">Session timeout after ${this.formatDuration(upload_limits.stale_upload_session_seconds)}</span>
            </div>
        `;

        if (!upload_sessions.length) {
            serverList.innerHTML = '<div class="session-empty">No recent upload sessions.</div>';
        } else {
            serverList.innerHTML = upload_sessions.map((session) => `
                <div class="session-item">
                    <div class="session-main">
                        <div class="session-title-row">
                            <strong>${this.esc(session.match_id)}</strong>
                            <span class="status-pill ${this.statusClass(session.status)}">${this.statusLabel(session.status)}</span>
                        </div>
                        <div class="session-meta">${this.slotLabel(session.slot)} • ${this.formatBytes(session.uploaded_bytes)} / ${this.formatBytes(session.size_bytes)} • ${session.progress_pct}%</div>
                        <div class="session-meta">Idle ${this.formatAge(session.idle_seconds)}${session.stale ? ' • stale' : ''}</div>
                    </div>
                    <div class="session-actions">
                        ${session.status === 'active' ? `<button type="button" class="mini-action-btn" onclick="app.cancelUploadSession('${this.esc(session.session_id)}')">Cancel</button>` : ''}
                    </div>
                </div>
            `).join('');
        }

        localList.innerHTML = this.renderLocalResumeSessions();
    },

    renderLocalResumeSessions() {
        const entries = Object.entries(this.getSavedUploadSessions());
        if (!entries.length) {
            return '<div class="session-empty">No resumable uploads saved in this browser.</div>';
        }

        return entries.map(([key, session]) => `
            <div class="session-item">
                <div class="session-main">
                    <div class="session-title-row">
                        <strong>${this.esc(session.file_name || session.match_id)}</strong>
                        <span class="status-pill resume">Resume</span>
                    </div>
                    <div class="session-meta">${this.esc(session.match_id)} • ${this.slotLabel(session.slot)} • ${this.formatBytes(session.size_bytes || 0)}</div>
                    <div class="session-meta">Re-open this match form, select the same file, and submit again.</div>
                </div>
                <div class="session-actions">
                    <button type="button" class="mini-action-btn" onclick="app.clearLocalResumeSession(decodeURIComponent('${encodeURIComponent(key)}'))">Clear</button>
                </div>
            </div>
        `).join('');
    },

    async cleanupStaleUploads() {
        if (!this.authToken) return;
        try {
            const resp = await fetch('/api/uploads/sessions/cleanup', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to cleanup upload sessions');
            const data = await resp.json();
            alert(`Cleaned ${data.count} stale upload session${data.count === 1 ? '' : 's'}.`);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            alert('Error: ' + error.message);
        }
    },

    async backfillExistingHls() {
        if (!this.authToken) return;
        try {
            const resp = await fetch('/api/admin/backfill-hls', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to backfill HLS assets');
            const data = await resp.json();
            if (data.reason === 'already-running') {
                alert('HLS backfill is already running.');
            } else {
                alert(`Backfill checked ${data.processed} ready slot${data.processed === 1 ? '' : 's'} and generated ${data.generated} HLS ladder${data.generated === 1 ? '' : 's'}.`);
            }
            await this.refreshAdminDiagnostics();
        } catch (error) {
            alert('Error: ' + error.message);
        }
    },

    async cancelUploadSession(sessionId) {
        if (!confirm('Cancel this upload session and remove its partial file?')) return;
        try {
            const resp = await fetch(`/api/uploads/sessions/${sessionId}`, {
                method: 'DELETE',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to cancel upload session');
            this.clearLocalResumeSessionBySessionId(sessionId);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            alert('Error: ' + error.message);
        }
    },

    clearLocalResumeSession(key) {
        this.clearSavedUploadSession(key);
        if (this.authToken) this.renderAdminDiagnostics();
    },

    clearLocalResumeSessionBySessionId(sessionId) {
        const sessions = this.getSavedUploadSessions();
        Object.entries(sessions).forEach(([key, value]) => {
            if (value.session_id === sessionId) {
                delete sessions[key];
            }
        });
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    toggleFormatFields() {
        const format = document.querySelector('input[name="format"]:checked').value;
        document.getElementById('video-full-group').style.display = format === 'full' ? 'block' : 'none';
        document.getElementById('video-halves-group').style.display = format === 'two_halves' ? 'block' : 'none';
    },

    updatePendingUploadState(inputId, file) {
        const stateEl = document.getElementById(inputId + '-state');
        if (!stateEl) return;

        if (file) {
            stateEl.textContent = `Selected for upload: ${file.name}`;
            stateEl.className = 'uploaded-state pending';
            return;
        }

        if (!document.getElementById('edit-match-id').value) {
            if (inputId.includes('logo')) {
                stateEl.textContent = 'No logo uploaded yet.';
            } else {
                stateEl.textContent = 'No video uploaded yet.';
            }
            stateEl.className = 'uploaded-state';
        }
    },

    renderEditAssetStates(match) {
        const assetStates = [
            {
                elementId: 'f-home-logo-state',
                present: !!match.home_logo,
                readyText: `Current logo uploaded: ${match.home_logo}`,
                emptyText: 'No home logo uploaded yet.',
            },
            {
                elementId: 'f-away-logo-state',
                present: !!match.away_logo,
                readyText: `Current logo uploaded: ${match.away_logo}`,
                emptyText: 'No away logo uploaded yet.',
            },
            {
                elementId: 'f-video-full-state',
                present: !!match.videos?.full,
                readyText: this.describeVideoState(match, 'full', 'Full match video'),
                emptyText: 'No full match video uploaded yet.',
            },
            {
                elementId: 'f-video-first-state',
                present: !!match.videos?.first_half,
                readyText: this.describeVideoState(match, 'first_half', '1st half video'),
                emptyText: 'No 1st half video uploaded yet.',
            },
            {
                elementId: 'f-video-second-state',
                present: !!match.videos?.second_half,
                readyText: this.describeVideoState(match, 'second_half', '2nd half video'),
                emptyText: 'No 2nd half video uploaded yet.',
            },
        ];

        assetStates.forEach(({ elementId, present, readyText, emptyText }) => {
            const el = document.getElementById(elementId);
            if (!el) return;
            el.textContent = present ? readyText : emptyText;
            el.className = `uploaded-state ${present ? 'ready' : ''}`.trim();
        });
    },

    describeVideoState(match, slot, label) {
        const status = this.slotStatus(match, slot);
        if (status === 'transcoding') return `${label} uploaded and processing.`;
        if (status === 'ready') return `${label} uploaded and ready to play.`;
        if (status === 'error') return `${label} upload exists but processing failed.`;
        return `${label} uploaded.`;
    },

    async handleFormSubmit() {
        const editId = document.getElementById('edit-match-id').value;
        const submitBtn = document.getElementById('submit-btn');
        const format = document.querySelector('input[name="format"]:checked').value;
        const fullFile = document.getElementById('f-video-full')?.files?.[0];
        const firstFile = document.getElementById('f-video-first')?.files?.[0];
        const secondFile = document.getElementById('f-video-second')?.files?.[0];
        let createdNewMatch = false;

        const matchData = {
            home_team: document.getElementById('f-home-team').value.trim(),
            away_team: document.getElementById('f-away-team').value.trim(),
            date: document.getElementById('f-date').value,
            time: document.getElementById('f-time').value,
            location: document.getElementById('f-location').value.trim(),
            score_home: document.getElementById('f-score-home').value ? parseInt(document.getElementById('f-score-home').value) : null,
            score_away: document.getElementById('f-score-away').value ? parseInt(document.getElementById('f-score-away').value) : null,
            format,
        };

        submitBtn.disabled = true;
        submitBtn.textContent = editId ? 'Updating...' : 'Creating...';

        try {
            if (!editId && format === 'full' && !fullFile) {
                throw new Error('Please choose a full-match video file before creating the match.');
            }

            if (!editId && format === 'two_halves' && !firstFile && !secondFile) {
                throw new Error('Please choose at least one half video before creating the match.');
            }

            const filesToValidate = [];
            if (format === 'full' && fullFile) filesToValidate.push(fullFile);
            if (format === 'two_halves' && firstFile) filesToValidate.push(firstFile);
            if (format === 'two_halves' && secondFile) filesToValidate.push(secondFile);
            for (const f of filesToValidate) {
                if (f.size > this.MAX_VIDEO_SIZE_BYTES) {
                    throw new Error(`File ${f.name} exceeds ${Math.round(this.MAX_VIDEO_SIZE_BYTES / (1024 * 1024 * 1024))}GB upload limit.`);
                }
            }

            let match;
            if (editId) {
                const resp = await fetch(`/api/matches/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                    body: JSON.stringify(matchData),
                });
                if (resp.status === 401) {
                    this.setLoggedOut();
                    sessionStorage.removeItem('replay_admin_token');
                    this.showLoginModal();
                    throw new Error('Session expired. Please log in again.');
                }
                match = await resp.json();
            } else {
                const resp = await fetch('/api/matches', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                    body: JSON.stringify(matchData),
                });
                if (resp.status === 401) {
                    this.setLoggedOut();
                    sessionStorage.removeItem('replay_admin_token');
                    this.showLoginModal();
                    throw new Error('Session expired. Please log in again.');
                }
                if (!resp.ok) {
                    const err = await resp.json();
                    throw new Error(err.detail || 'Failed to create match');
                }
                match = await resp.json();
                createdNewMatch = true;
                document.getElementById('edit-match-id').value = match.id;
                document.getElementById('form-heading').textContent = 'Edit Match';
                document.getElementById('submit-btn').textContent = 'Update Match';
                document.getElementById('cancel-edit-btn').style.display = 'inline-block';
            }

            // Upload logos
            await this.uploadFileIfSelected('f-home-logo', match.id, 'logo', 'home');
            await this.uploadFileIfSelected('f-away-logo', match.id, 'logo', 'away');

            // Upload videos (server saves raw file and returns quickly;
            // transcoding runs in the background)
            if (format === 'full') {
                await this.uploadVideoIfSelected('f-video-full', match.id, 'full');
            } else {
                await this.uploadVideoIfSelected('f-video-first', match.id, 'first_half');
                await this.uploadVideoIfSelected('f-video-second', match.id, 'second_half');
            }

            await this.loadMatches();
            this.renderSeasonView();
            this.cancelEdit();
            document.getElementById('add-match-form').reset();
            this.resetFileLabels();
            this.showSeasonView({ replaceHistory: true });

            // Start polling for transcoding progress
            this.checkTranscodePolling();

        } catch (e) {
            if (document.getElementById('edit-match-id').value) {
                await this.loadMatches();
                this.renderSeasonView();
            }
            const resumeHint = createdNewMatch
                ? '\n\nThe match record was created. Re-submit this form to resume any incomplete upload for the same selected file.'
                : '';
            alert('Error: ' + e.message + resumeHint);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = editId ? 'Update Match' : 'Create Match';
            if (document.getElementById('edit-match-id').value) {
                submitBtn.textContent = 'Update Match';
            }
        }
    },

    async uploadFileIfSelected(inputId, matchId, type, param) {
        const input = document.getElementById(inputId);
        if (!input || !input.files[0]) return;

        const form = new FormData();
        form.append('file', input.files[0]);

        const url = type === 'logo'
            ? `/api/matches/${matchId}/upload-logo?team=${param}`
            : `/api/matches/${matchId}/upload-video?slot=${param}`;

        const resp = await fetch(url, { method: 'POST', body: form, headers: this.getAuthHeaders() });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `Upload failed for ${inputId}`);
        }
    },

    async uploadVideoIfSelected(inputId, matchId, slot) {
        const input = document.getElementById(inputId);
        if (!input || !input.files[0]) return;

        const file = input.files[0];
        const uploadKey = this.getUploadSessionKey(matchId, slot, file);

        // Determine correct progress element IDs
        let progressKey;
        if (slot === 'full') progressKey = 'full';
        else if (slot === 'first_half') progressKey = 'first';
        else progressKey = 'second';

        const pEl = document.getElementById('progress-' + progressKey);
        const fEl = document.getElementById('progress-fill-' + progressKey);
        const tEl = document.getElementById('progress-text-' + progressKey);

        if (pEl) pEl.style.display = 'flex';
        if (fEl) {
            fEl.classList.add('indeterminate');
            fEl.style.width = '35%';
        }
        if (tEl) tEl.textContent = 'Uploading...';

        let session = this.getSavedUploadSession(uploadKey);
        if (session?.session_id) {
            const existing = await this.fetchUploadSession(session.session_id);
            if (existing && existing.status === 'active' && existing.match_id === matchId && existing.slot === slot && existing.size_bytes === file.size) {
                session = existing;
            } else {
                this.clearSavedUploadSession(uploadKey);
                session = null;
            }
        }

        if (!session) {
            const sessionResp = await fetch(`/api/matches/${matchId}/upload-video/session?slot=${slot}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify({ filename: file.name, size_bytes: file.size }),
            });
            if (!sessionResp.ok) {
                const err = await sessionResp.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to start upload session');
            }
            session = await sessionResp.json();
            this.saveUploadSession(uploadKey, {
                session_id: session.session_id,
                match_id: matchId,
                slot,
                size_bytes: file.size,
                file_name: file.name,
                updated_at: Date.now(),
            });
        }

        const { session_id, chunk_size, total_chunks } = session;
        let nextIndex = session.next_index || 0;
        let uploadedBytes = Math.min(file.size, nextIndex * chunk_size);

        if (fEl) fEl.classList.remove('indeterminate');
        if (fEl) fEl.style.width = `${Math.round((uploadedBytes / file.size) * 100)}%`;
        if (tEl) {
            if (nextIndex > 0) {
                tEl.textContent = `Resuming at chunk ${nextIndex + 1}/${total_chunks}`;
            } else {
                tEl.textContent = '0%';
            }
        }

        if (nextIndex >= total_chunks) {
            await this.completeUploadSession(session_id, uploadKey, fEl, tEl);
            return;
        }

        for (let index = nextIndex; index < total_chunks; index++) {
            const start = index * chunk_size;
            const end = Math.min(file.size, start + chunk_size);
            const chunk = file.slice(start, end);

            let lastErr = null;
            for (let attempt = 1; attempt <= this.CHUNK_RETRY_COUNT; attempt++) {
                try {
                    const chunkResp = await fetch(`/api/uploads/sessions/${session_id}/chunk?index=${index}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/octet-stream', ...this.getAuthHeaders() },
                        body: chunk,
                    });

                    if (!chunkResp.ok) {
                        const err = await chunkResp.json().catch(() => ({}));
                        throw new Error(err.detail || `Chunk ${index + 1} failed`);
                    }

                    uploadedBytes = end;
                    nextIndex = index + 1;
                    this.saveUploadSession(uploadKey, {
                        session_id,
                        match_id: matchId,
                        slot,
                        size_bytes: file.size,
                        file_name: file.name,
                        updated_at: Date.now(),
                    });
                    if (fEl && tEl) {
                        const pct = Math.round((uploadedBytes / file.size) * 100);
                        fEl.style.width = pct + '%';
                        tEl.textContent = `${pct}% (${index + 1}/${total_chunks} chunks)`;
                    }
                    lastErr = null;
                    break;
                } catch (err) {
                    lastErr = err;
                    if (tEl) tEl.textContent = `Retrying chunk ${index + 1}/${total_chunks} (${attempt}/${this.CHUNK_RETRY_COUNT})...`;
                    if (attempt < this.CHUNK_RETRY_COUNT) {
                        await new Promise((r) => setTimeout(r, 600 * attempt));
                    }
                }
            }

            if (lastErr) {
                throw lastErr;
            }
        }

        await this.completeUploadSession(session_id, uploadKey, fEl, tEl);
    },

    async completeUploadSession(sessionId, uploadKey, fEl, tEl) {
        const completeResp = await fetch(`/api/uploads/sessions/${sessionId}/complete`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
        });
        if (!completeResp.ok) {
            const err = await completeResp.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to complete upload session');
        }

        if (fEl) fEl.style.width = '100%';
        if (tEl) tEl.textContent = 'Uploaded - processing';
        this.clearSavedUploadSession(uploadKey);
    },

    getUploadSessionKey(matchId, slot, file) {
        return [matchId, slot, file.name, file.size, file.lastModified].join('::');
    },

    getSavedUploadSessions() {
        try {
            return JSON.parse(localStorage.getItem(this.UPLOAD_SESSION_STORAGE_KEY) || '{}');
        } catch {
            return {};
        }
    },

    getSavedUploadSession(key) {
        const sessions = this.getSavedUploadSessions();
        return sessions[key] || null;
    },

    saveUploadSession(key, sessionData) {
        const sessions = this.getSavedUploadSessions();
        sessions[key] = sessionData;
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    clearSavedUploadSession(key) {
        const sessions = this.getSavedUploadSessions();
        if (!sessions[key]) return;
        delete sessions[key];
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    async fetchUploadSession(sessionId) {
        try {
            const resp = await fetch(`/api/uploads/sessions/${sessionId}`, {
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) return null;
            return await resp.json();
        } catch {
            return null;
        }
    },

    resetFileLabels() {
        ['f-home-logo', 'f-away-logo', 'f-video-full', 'f-video-first', 'f-video-second'].forEach(id => {
            const label = document.getElementById(id + '-label');
            if (label) label.textContent = 'No file chosen';
            const input = document.getElementById(id);
            if (input) input.value = '';
        });
        ['full', 'first', 'second'].forEach(key => {
            const pEl = document.getElementById('progress-' + key);
            const fEl = document.getElementById('progress-fill-' + key);
            if (pEl) pEl.style.display = 'none';
            if (fEl) fEl.style.width = '0%';
        });
        ['f-home-logo-state', 'f-away-logo-state', 'f-video-full-state', 'f-video-first-state', 'f-video-second-state'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.className = 'uploaded-state';
        });
        document.getElementById('f-home-logo-state').textContent = 'No logo uploaded yet.';
        document.getElementById('f-away-logo-state').textContent = 'No logo uploaded yet.';
        document.getElementById('f-video-full-state').textContent = 'No video uploaded yet.';
        document.getElementById('f-video-first-state').textContent = 'No video uploaded yet.';
        document.getElementById('f-video-second-state').textContent = 'No video uploaded yet.';
    },

    // ------------------------------------------------------------------
    // Edit / Delete
    // ------------------------------------------------------------------

    editMatch(matchId, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        const match = this.matches.find(m => m.id === matchId);
        if (!match) return;

        this.activateView('add-match-view', 'add-match');
        if (this.authToken) this.refreshAdminDiagnostics();

        // Populate form
        document.getElementById('edit-match-id').value = match.id;
        document.getElementById('f-home-team').value = match.home_team || '';
        document.getElementById('f-away-team').value = match.away_team || '';
        document.getElementById('f-date').value = match.date || '';
        document.getElementById('f-time').value = match.time || '';
        document.getElementById('f-location').value = match.location || '';
        document.getElementById('f-score-home').value = match.score_home != null ? match.score_home : '';
        document.getElementById('f-score-away').value = match.score_away != null ? match.score_away : '';

        const formatRadio = document.querySelector(`input[name="format"][value="${match.format || 'full'}"]`);
        if (formatRadio) formatRadio.checked = true;
        this.toggleFormatFields();
        this.resetFileLabels();
        this.renderEditAssetStates(match);

        document.getElementById('form-heading').textContent = 'Edit Match';
        document.getElementById('submit-btn').textContent = 'Update Match';
        document.getElementById('cancel-edit-btn').style.display = 'inline-block';

        if (pushHistory) {
            this.pushHistoryState({ view: 'add-match', mode: 'edit', matchId }, { replace: replaceHistory });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    cancelEdit() {
        document.getElementById('edit-match-id').value = '';
        document.getElementById('add-match-form').reset();
        document.getElementById('form-heading').textContent = 'Add New Match';
        document.getElementById('submit-btn').textContent = 'Create Match';
        document.getElementById('cancel-edit-btn').style.display = 'none';
        this.resetFileLabels();
    },

    async deleteMatch(matchId) {
        if (!confirm('Delete this match and all its videos?')) return;

        try {
            const resp = await fetch(`/api/matches/${matchId}`, { method: 'DELETE', headers: this.getAuthHeaders() });
            if (resp.status === 401) {
                this.setLoggedOut();
                sessionStorage.removeItem('replay_admin_token');
                this.showLoginModal();
                throw new Error('Session expired. Please log in again.');
            }
            if (!resp.ok) throw new Error('Failed to delete');
            await this.loadMatches();
            this.renderSeasonView();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    },

    // ------------------------------------------------------------------
    // Season View
    // ------------------------------------------------------------------

    renderSeasonView() {
        const grid = document.getElementById('matches-grid');
        if (!grid) return;

        document.getElementById('stat-played').textContent = this.matches.length;
        document.getElementById('stat-ready').textContent = this.matches.filter((match) => this.readySlotsCount(match) > 0).length;
        document.getElementById('stat-processing').textContent = this.matches.filter((match) => this.matchTranscoding(match)).length;

        grid.innerHTML = '';
        if (this.matches.length === 0) {
            grid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 2rem;">No matches yet. Click "Add Match" to get started.</p>';
            return;
        }

        // Sort by date descending
        const sorted = [...this.matches].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

        sorted.forEach(m => {
            const card = document.createElement('div');
            card.className = 'match-card';
            card.onclick = () => this.openMatch(m.id);

            const homeLogo = m.home_logo
                ? `<img src="/api/matches/${m.id}/logo/home" class="card-team-logo" alt="${this.esc(m.home_team)}">`
                : `<div class="card-team-initial">${this.esc((m.home_team || '?')[0])}</div>`;
            const awayLogo = m.away_logo
                ? `<img src="/api/matches/${m.id}/logo/away" class="card-team-logo" alt="${this.esc(m.away_team)}">`
                : `<div class="card-team-initial">${this.esc((m.away_team || '?')[0])}</div>`;

            const homeScore = m.score_home != null ? m.score_home : '';
            const awayScore = m.score_away != null ? m.score_away : '';

            const dateStr = this.formatDate(m.date);
            const timeStr = m.time ? ` \u00b7 ${m.time}` : '';

            const formatLabel = m.format === 'two_halves' ? '2 HALVES' : 'FULL MATCH';
            const isTranscoding = this.matchTranscoding(m);
            const readySlots = this.readySlotsCount(m);
            const totalSlots = m.format === 'two_halves' ? 2 : 1;
            const availabilityLabel = `${readySlots}/${totalSlots} READY`;

            card.innerHTML = `
                <div class="card-bg"></div>
                <div class="card-topline">
                    <span class="card-topline-label">${availabilityLabel}</span>
                    ${m.date ? `<span class="card-topline-date">${this.esc(dateStr)}</span>` : ''}
                </div>
                <div class="card-matchup">
                    <div class="card-team-col">
                        ${homeLogo}
                        <span class="team-side-label">Home</span>
                        <div class="team-name-score-row">
                            <span class="card-team-name">${this.esc(m.home_team)}</span>
                            ${homeScore !== '' ? `<span class="card-team-score">${homeScore}</span>` : '<span class="card-team-score empty">-</span>'}
                        </div>
                    </div>
                    <div class="card-vs-col">
                        <span class="card-vs">VS</span>
                    </div>
                    <div class="card-team-col">
                        ${awayLogo}
                        <span class="team-side-label">Away</span>
                        <div class="team-name-score-row">
                            <span class="card-team-name">${this.esc(m.away_team)}</span>
                            ${awayScore !== '' ? `<span class="card-team-score">${awayScore}</span>` : '<span class="card-team-score empty">-</span>'}
                        </div>
                    </div>
                </div>
                <div class="match-date">${this.esc(dateStr)}${timeStr}</div>
                ${m.location ? `<div class="match-location">${this.esc(m.location)}</div>` : ''}
                <div class="match-meta">
                    ${isTranscoding ? '<span class="badge processing">PROCESSING</span>' : ''}
                    <span class="badge mode">${formatLabel}</span>
                    <span class="badge">${availabilityLabel}</span>
                </div>
                <div class="hover-reveal">VIEW MATCH <span>&rarr;</span></div>
                ${this.authToken ? `
                <button class="match-card-edit-btn" onclick="app.triggerEdit(event, '${m.id}')" title="Edit">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="match-card-delete-btn" onclick="app.triggerDelete(event, '${m.id}')" title="Delete">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
                ` : ''}
            `;
            grid.appendChild(card);
        });
    },

    triggerEdit(event, matchId) {
        event.stopPropagation();
        this.editMatch(matchId);
    },

    triggerDelete(event, matchId) {
        event.stopPropagation();
        this.deleteMatch(matchId);
    },

    // ------------------------------------------------------------------
    // Game View
    // ------------------------------------------------------------------

    openMatch(matchId, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        const match = this.matches.find(m => m.id === matchId);
        if (!match) return;

        this.activeMatchId = matchId;

        // Date
        document.getElementById('active-game-date').textContent =
            this.formatDate(match.date) + (match.time ? ` \u00b7 ${match.time}` : '');

        // Location
        document.getElementById('active-game-loc').textContent = match.location || '-';
        document.getElementById('game-title').textContent = `${match.home_team} vs ${match.away_team}`;
        this.renderGameStatus(match);

        // Matchup layout
        const matchupEl = document.getElementById('game-matchup');
        const homeLogo = match.home_logo
            ? `<img src="/api/matches/${match.id}/logo/home" class="game-logo-large">`
            : `<div class="game-logo-initial-large">${this.esc((match.home_team || '?')[0])}</div>`;
        const awayLogo = match.away_logo
            ? `<img src="/api/matches/${match.id}/logo/away" class="game-logo-large">`
            : `<div class="game-logo-initial-large">${this.esc((match.away_team || '?')[0])}</div>`;
        const homeScore = match.score_home != null ? match.score_home : '';
        const awayScore = match.score_away != null ? match.score_away : '';
        matchupEl.innerHTML = `
            <div class="game-team-col">
                ${homeLogo}
                <span class="team-side-label game-side-label">Home</span>
                <div class="team-name-score-row game-team-name-score-row">
                    <span class="game-team-name">${this.esc(match.home_team)}</span>
                    ${homeScore !== '' ? `<span class="game-team-score">${homeScore}</span>` : '<span class="game-team-score empty">-</span>'}
                </div>
            </div>
            <div class="game-vs-col">VS</div>
            <div class="game-team-col">
                ${awayLogo}
                <span class="team-side-label game-side-label">Away</span>
                <div class="team-name-score-row game-team-name-score-row">
                    <span class="game-team-name">${this.esc(match.away_team)}</span>
                    ${awayScore !== '' ? `<span class="game-team-score">${awayScore}</span>` : '<span class="game-team-score empty">-</span>'}
                </div>
            </div>
        `;

        this.activateView('game-view');
        if (pushHistory) {
            this.pushHistoryState({ view: 'game', matchId }, { replace: replaceHistory });
        }

        this.setupVideoSlots(match);
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    setupVideoSlots(match) {
        const segSelector = document.getElementById('segment-selector');
        segSelector.innerHTML = '';

        if (match.format === 'two_halves') {
            segSelector.style.display = 'flex';
            const readySlots = [];

            ['first_half', 'second_half'].forEach(slot => {
                const status = this.slotStatus(match, slot);
                const btn = document.createElement('button');
                btn.className = 'segment-btn';
                btn.dataset.slot = slot;

                if (status === 'ready') {
                    btn.textContent = slot === 'first_half' ? '1st Half' : '2nd Half';
                    btn.onclick = () => this.playSlot(match.id, slot);
                    readySlots.push(slot);
                } else if (status === 'transcoding') {
                    btn.textContent = (slot === 'first_half' ? '1st Half' : '2nd Half') + ' (processing)';
                    btn.disabled = true;
                    btn.style.opacity = '0.5';
                } else {
                    return; // skip slots with no video
                }
                segSelector.appendChild(btn);
            });

            if (readySlots.length > 0) {
                this.playSlot(match.id, readySlots[0]);
            } else if (this.matchTranscoding(match)) {
                this.showProcessingState();
            } else {
                this.showNoVideoState();
            }
        } else {
            segSelector.style.display = 'none';
            const status = this.slotStatus(match, 'full');
            if (status === 'ready') {
                this.playSlot(match.id, 'full');
            } else if (status === 'transcoding') {
                this.showProcessingState();
            } else {
                this.showNoVideoState();
            }
        }
    },

    refreshGameView(match) {
        // Called by polling — update slots without resetting the whole view
        // Only refresh if we're on the game view for this match
        if (!document.getElementById('game-view').classList.contains('active')) return;
        this.renderGameStatus(match);

        // If the active slot just became ready, try playing it
        if (this.activeSlot) {
            const status = this.slotStatus(match, this.activeSlot);
            if (status === 'ready') return; // already playing
        }

        // Check if any new slots became ready
        this.setupVideoSlots(match);
    },

    showProcessingState() {
        this.activeSlot = null;
        this.destroyHlsPlayer();
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');

        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            videoEl.classList.remove('active');
            videoEl.style.display = 'none';
            videoEl.onerror = null;
            videoEl.onloadeddata = null;
        }

        if (placeholder) {
            placeholder.style.display = 'flex';
            const label = placeholder.querySelector('.player-label');
            if (label) label.textContent = 'VIDEO IS BEING PROCESSED';
        }
    },

    showNoVideoState() {
        this.activeSlot = null;
        this.destroyHlsPlayer();
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');

        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            videoEl.classList.remove('active');
            videoEl.style.display = 'none';
            videoEl.onerror = null;
            videoEl.onloadeddata = null;
        }

        if (placeholder) {
            placeholder.style.display = 'flex';
            const label = placeholder.querySelector('.player-label');
            if (label) label.textContent = 'VIDEO NOT AVAILABLE';
        }
    },

    playSlot(matchId, slot) {
        this.activeSlot = slot;
        const playRequestToken = ++this._playRequestToken;
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');
        const { hlsUrl, mp4Url } = this.getStreamUrls(matchId, slot);

        this.destroyHlsPlayer();

        // Update segment button active state
        document.querySelectorAll('.segment-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.slot === slot);
        });

        videoEl.preload = 'auto';
        videoEl.onerror = null;
        videoEl.onloadeddata = () => {
            if (playRequestToken !== this._playRequestToken) return;
            placeholder.style.display = 'none';
            videoEl.style.display = 'block';
            videoEl.classList.add('active');
        };
        this.loadPlaybackSource(videoEl, hlsUrl, mp4Url, playRequestToken);

        // If casting, load on remote
        if (this.castSession) {
            this.castMedia(mp4Url);
        }

        this.updateRemotePlaybackNote();
    },

    closeGame() {
        this.showSeasonView({ replaceHistory: true });
    },

    renderGameStatus(match) {
        const pills = document.getElementById('game-status-pills');
        const slotList = document.getElementById('game-slot-status-list');
        if (!pills || !slotList) return;

        const formatLabel = match.format === 'two_halves' ? 'Two Halves' : 'Full Match';
        const readySlots = this.readySlotsCount(match);
        const totalSlots = match.format === 'two_halves' ? 2 : 1;
        pills.innerHTML = `
            <span class="status-pill neutral">${this.esc(formatLabel)}</span>
            <span class="status-pill ${this.matchTranscoding(match) ? 'processing' : 'ready'}">${readySlots}/${totalSlots} Ready</span>
        `;

        const slots = match.format === 'two_halves'
            ? [['first_half', '1st Half'], ['second_half', '2nd Half']]
            : [['full', 'Full Match']];
        slotList.innerHTML = slots.map(([slot, label]) => {
            const status = this.slotStatus(match, slot);
            return `
                <div class="slot-status-row">
                    <span class="slot-status-label">${label}</span>
                    <span class="status-pill ${this.statusClass(status)}">${this.statusLabel(status)}</span>
                </div>
            `;
        }).join('');
    },

    // ------------------------------------------------------------------
    // Remote Playback
    // ------------------------------------------------------------------

    initAirPlay() {
        const videoEl = document.getElementById('game-video');
        const airplayBtn = document.getElementById('airplay-btn');
        if (!videoEl || !airplayBtn) return;

        videoEl.disableRemotePlayback = false;

        const refreshAvailability = (available) => {
            this.airplayAvailable = available;
            airplayBtn.style.display = available ? 'flex' : 'none';
            this.updateRemotePlaybackNote();
        };

        if (typeof videoEl.webkitShowPlaybackTargetPicker === 'function') {
            refreshAvailability(true);
            videoEl.addEventListener('webkitplaybacktargetavailabilitychanged', (event) => {
                refreshAvailability(event.availability === 'available');
            });
            videoEl.addEventListener('webkitcurrentplaybacktargetiswirelesschanged', () => {
                this.airplayActive = !!videoEl.webkitCurrentPlaybackTargetIsWireless;
                airplayBtn.classList.toggle('casting', this.airplayActive);
                this.updateRemotePlaybackNote();
            });
            return;
        }

        if (videoEl.remote && typeof videoEl.remote.watchAvailability === 'function') {
            videoEl.remote.watchAvailability((available) => {
                refreshAvailability(!!available);
            }).catch(() => {
                refreshAvailability(false);
            });
        }
    },

    initCast() {
        const castBtn = document.getElementById('cast-btn');
        this.castSupportedBrowser = this.isCastSupportedBrowser();
        this.castSecureContextAllowed = this.isCastSecureContextAllowed();
        if (castBtn) {
            castBtn.style.display = this.castSupportedBrowser ? 'flex' : 'none';
            castBtn.classList.toggle('remote-playback-btn-disabled', this.castSupportedBrowser);
        }

        const bootstrap = window.__replayCastBootstrap;
        if (bootstrap && Array.isArray(bootstrap.listeners)) {
            bootstrap.listeners.push((isAvailable) => {
                this.setupCastFramework(isAvailable);
            });
        }

        if (typeof bootstrap?.available === 'boolean') {
            this.setupCastFramework(bootstrap.available);
            return;
        }

        if (window.cast?.framework && window.chrome?.cast) {
            this.setupCastFramework(true);
        } else {
            this.retryCastFrameworkDetection();
            this.updateRemotePlaybackNote();
        }
    },

    isCastSupportedBrowser() {
        const ua = navigator.userAgent || '';
        return /(Chrome|Chromium|CriOS|Edg)\//.test(ua) && !/OPR\//.test(ua);
    },

    isCastSecureContextAllowed() {
        if (window.isSecureContext) return true;
        const hostname = window.location.hostname || '';
        return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
    },

    retryCastFrameworkDetection() {
        if (!this.castSupportedBrowser) return;
        window.setTimeout(() => {
            if (window.cast?.framework && window.chrome?.cast) {
                this.setupCastFramework(true);
                return;
            }
            this.updateRemotePlaybackNote();
        }, 1500);
    },

    setupCastFramework(isAvailable) {
        this.castAvailable = !!isAvailable;
        this.castSdkReady = !!isAvailable && !!window.cast?.framework && !!window.chrome?.cast;

        const castBtn = document.getElementById('cast-btn');
        if (!isAvailable || !window.cast?.framework || !window.chrome?.cast) {
            if (castBtn && this.castSupportedBrowser) {
                castBtn.style.display = 'flex';
                castBtn.classList.add('remote-playback-btn-disabled');
            }
            this.updateRemotePlaybackNote();
            return;
        }

        if (castBtn) {
            castBtn.style.display = 'flex';
            castBtn.classList.remove('remote-playback-btn-disabled');
        }

        if (this._castInitialized) {
            this.updateRemotePlaybackNote();
            return;
        }

        const castContext = cast.framework.CastContext.getInstance();
        castContext.setOptions({
            receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
            autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
        });

        castContext.addEventListener(
            cast.framework.CastContextEventType.SESSION_STATE_CHANGED,
            (event) => {
                if (event.sessionState === cast.framework.SessionState.SESSION_STARTED ||
                    event.sessionState === cast.framework.SessionState.SESSION_RESUMED) {
                    this.onCastConnected();
                } else if (event.sessionState === cast.framework.SessionState.SESSION_ENDED) {
                    this.onCastDisconnected();
                }
            }
        );

        this._castInitialized = true;
        this.updateRemotePlaybackNote();
    },

    toggleCast() {
        if (!this.castSupportedBrowser || !this.castSecureContextAllowed || !window.cast?.framework) {
            this.updateRemotePlaybackNote();
            return;
        }

        if (this.castSession) {
            cast.framework.CastContext.getInstance().endCurrentSession(true);
        } else {
            cast.framework.CastContext.getInstance().requestSession().catch(() => {
                this.updateRemotePlaybackNote();
            });
        }
    },

    async toggleAirPlay() {
        const videoEl = document.getElementById('game-video');
        if (!videoEl) return;

        if (typeof videoEl.webkitShowPlaybackTargetPicker === 'function') {
            videoEl.webkitShowPlaybackTargetPicker();
            return;
        }

        if (videoEl.remote && typeof videoEl.remote.prompt === 'function') {
            try {
                await videoEl.remote.prompt();
            } catch {
                // Ignore user-cancelled prompt
            }
        }
    },

    onCastConnected() {
        this.castSession = cast.framework.CastContext.getInstance().getCurrentSession();
        const castBtn = document.getElementById('cast-btn');
        if (castBtn) castBtn.classList.add('casting');

        const overlay = document.getElementById('cast-overlay');
        const deviceName = document.getElementById('cast-device-name');
        if (overlay) overlay.style.display = 'flex';
        if (deviceName) {
            const name = this.castSession.getCastDevice().friendlyName || 'TV';
            deviceName.textContent = `Casting to ${name}`;
        }

        const videoEl = document.getElementById('game-video');
        if (videoEl) videoEl.pause();

        if (this.activeMatchId && this.activeSlot) {
            const src = `${window.location.origin}/api/matches/${this.activeMatchId}/video/${this.activeSlot}`;
            this.castMedia(src);
        }

        this.updateRemotePlaybackNote();
    },

    onCastDisconnected() {
        this.castSession = null;
        const castBtn = document.getElementById('cast-btn');
        if (castBtn) castBtn.classList.remove('casting');

        const overlay = document.getElementById('cast-overlay');
        if (overlay) overlay.style.display = 'none';
        this.updateRemotePlaybackNote();
    },

    castMedia(url) {
        if (!this.castSession) return;

        const match = this.matches.find((item) => item.id === this.activeMatchId);
        const videoEl = document.getElementById('game-video');
        const absoluteUrl = url.startsWith('http') ? url : window.location.origin + url;
        const mediaInfo = new chrome.cast.media.MediaInfo(absoluteUrl, 'video/mp4');
        mediaInfo.streamType = chrome.cast.media.StreamType.BUFFERED;
        if (match) {
            const metadata = new chrome.cast.media.GenericMediaMetadata();
            metadata.title = `${match.home_team} vs ${match.away_team}`;
            metadata.subtitle = this.slotLabel(this.activeSlot || 'full');
            if (match.home_logo) {
                metadata.images = [
                    { url: `${window.location.origin}/api/matches/${match.id}/logo/home` },
                ];
            }
            mediaInfo.metadata = metadata;
        }
        const request = new chrome.cast.media.LoadRequest(mediaInfo);
        request.currentTime = videoEl?.currentTime || 0;
        request.autoplay = true;

        this.castSession.loadMedia(request).then(
            () => console.log('Cast media loaded'),
            (err) => console.error('Cast load error', err)
        );
    },

    updateRemotePlaybackNote() {
        const note = document.getElementById('remote-playback-note');
        if (!note) return;

        if (this.castSession) {
            note.textContent = 'Chromecast connected. Playback is being sent to the selected TV.';
            return;
        }

        if (this.airplayActive) {
            note.textContent = 'AirPlay is active. Playback is being sent to the selected Apple TV or AirPlay 2 display.';
            return;
        }

        if (this.airplayAvailable) {
            note.textContent = this.castAvailable
                ? 'Adaptive HLS playback is active when supported. Use AirPlay or Cast to send playback to a TV.'
                : 'Adaptive HLS playback is active when supported. AirPlay is available on supported Safari or WebKit devices.';
            return;
        }

        if (this.castAvailable) {
            note.textContent = 'Adaptive HLS playback is active when supported. Cast is available in Chrome when a Chromecast device is on the same network.';
            return;
        }

        if (this.castSupportedBrowser && !this.castSecureContextAllowed) {
            note.textContent = 'Cast is unavailable because this page is not loaded from HTTPS or localhost.';
            return;
        }

        if (this.castSupportedBrowser && !this.castSdkReady) {
            note.textContent = 'Cast is available in Chrome or Edge when this page is opened over HTTPS or localhost.';
            return;
        }

        note.textContent = 'Adaptive HLS playback is used when available, with direct MP4 fallback for simple playback and casting.';
    },

    getStreamUrls(matchId, slot) {
        return {
            hlsUrl: `/api/matches/${matchId}/hls/${slot}/master.m3u8`,
            mp4Url: `/api/matches/${matchId}/video/${slot}`,
        };
    },

    loadPlaybackSource(videoEl, hlsUrl, mp4Url, playRequestToken) {
        const useMp4Fallback = () => {
            if (playRequestToken !== this._playRequestToken) return;
            this.destroyHlsPlayer();
            if (videoEl._nativeHlsFallbackHandler) {
                videoEl.removeEventListener('error', videoEl._nativeHlsFallbackHandler);
                videoEl._nativeHlsFallbackHandler = null;
            }
            videoEl.onerror = () => this.showNoVideoState();
            videoEl.src = mp4Url;
            videoEl.load();
        };

        if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
            if (videoEl._nativeHlsFallbackHandler) {
                videoEl.removeEventListener('error', videoEl._nativeHlsFallbackHandler);
            }
            videoEl._nativeHlsFallbackHandler = useMp4Fallback;
            videoEl.addEventListener('error', useMp4Fallback, { once: true });
            videoEl.src = hlsUrl;
            videoEl.load();
            return;
        }

        if (window.Hls && window.Hls.isSupported()) {
            const hls = new window.Hls({
                enableWorker: true,
                backBufferLength: 90,
                maxBufferLength: 60,
                maxMaxBufferLength: 120,
            });
            this.hlsPlayer = hls;
            hls.attachMedia(videoEl);
            hls.on(window.Hls.Events.MEDIA_ATTACHED, () => {
                if (playRequestToken !== this._playRequestToken) return;
                hls.loadSource(hlsUrl);
            });
            hls.on(window.Hls.Events.ERROR, (_, data) => {
                if (!data?.fatal) return;
                useMp4Fallback();
            });
            return;
        }

        useMp4Fallback();
    },

    destroyHlsPlayer() {
        if (!this.hlsPlayer) return;
        this.hlsPlayer.destroy();
        this.hlsPlayer = null;
    },

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    },

    formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
        } catch {
            return dateStr;
        }
    },

    readySlotsCount(match) {
        const slots = match.format === 'two_halves' ? ['first_half', 'second_half'] : ['full'];
        return slots.filter((slot) => this.slotStatus(match, slot) === 'ready').length;
    },

    statusLabel(status) {
        if (status === 'ready') return 'Ready';
        if (status === 'transcoding') return 'Processing';
        if (status === 'completed') return 'Completed';
        if (status === 'cancelled') return 'Cancelled';
        if (status === 'replaced') return 'Replaced';
        return 'Waiting';
    },

    statusClass(status) {
        if (status === 'ready' || status === 'completed') return 'ready';
        if (status === 'transcoding') return 'processing';
        if (status === 'cancelled' || status === 'error' || status === 'replaced') return 'danger';
        return 'neutral';
    },

    slotLabel(slot) {
        if (slot === 'first_half') return '1st Half';
        if (slot === 'second_half') return '2nd Half';
        return 'Full Match';
    },

    formatBytes(bytes) {
        const value = Number(bytes || 0);
        if (value < 1024) return `${value} B`;
        const units = ['KB', 'MB', 'GB', 'TB'];
        let size = value;
        let unitIndex = -1;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex += 1;
        }
        return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
    },

    formatDuration(seconds) {
        const total = Number(seconds || 0);
        if (total >= 3600) return `${Math.round(total / 3600)}h`;
        if (total >= 60) return `${Math.round(total / 60)}m`;
        return `${Math.round(total)}s`;
    },

    formatAge(seconds) {
        const total = Number(seconds || 0);
        if (total >= 3600) return `${Math.round(total / 3600)}h ago`;
        if (total >= 60) return `${Math.round(total / 60)}m ago`;
        return `${Math.round(total)}s ago`;
    },
};

document.addEventListener('DOMContentLoaded', () => app.init());
