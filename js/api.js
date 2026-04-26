// Auth, data loading, and settings data methods.

export const apiMixin = {
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
                this.userRole = data.role || 'viewer';
                this.userName = data.username || '';
                this.setLoggedIn();
            } else {
                sessionStorage.removeItem('replay_admin_token');
                this.setLoggedOut();
            }
        } catch {
            this.setLoggedOut();
        }
    },

    isAdmin() {
        return this.userRole === 'admin';
    },

    canEdit() {
        return this.userRole === 'admin' || this.userRole === 'uploader';
    },

    setLoggedIn() {
        document.getElementById('nav-add-match').style.display = this.canEdit() ? '' : 'none';
        document.getElementById('nav-settings').style.display = this.isAdmin() ? '' : 'none';
        document.getElementById('nav-login-btn').style.display = 'none';
        document.getElementById('nav-logout-btn').style.display = '';
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn && this.activeMatchId) gameEditBtn.style.display = this.canEdit() ? 'inline-flex' : 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn && this.activeMatchId) regenThumbBtn.style.display = this.isAdmin() ? 'inline-flex' : 'none';
        this.setAdminPanelVisibility(this.isAdmin());
        if (this.isAdmin()) this.refreshAdminDiagnostics();
    },

    setLoggedOut() {
        this.authToken = null;
        this.userRole = null;
        this.userName = null;
        document.getElementById('nav-add-match').style.display = 'none';
        document.getElementById('nav-settings').style.display = 'none';
        document.getElementById('nav-login-btn').style.display = '';
        document.getElementById('nav-logout-btn').style.display = 'none';
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn) gameEditBtn.style.display = 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn) regenThumbBtn.style.display = 'none';
        this.setAdminPanelVisibility(false);
        if (document.getElementById('add-match-view')?.classList.contains('active') || document.getElementById('settings-view')?.classList.contains('active')) {
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
            this.userRole = data.role || 'viewer';
            this.userName = data.username || '';
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

    async loadMatches() {
        try {
            const resp = await fetch('/api/matches');
            this.matches = await resp.json();
        } catch (e) {
            console.error('Failed to load matches', e);
            this.matches = [];
        }
    },

    getDefaultAppSettings() {
        return {
            app_name: 'Replay',
            nav_matches_label: 'Matches',
            nav_add_match_label: 'Add Match',
            nav_settings_label: 'Settings',
            season_title: 'U12 GIRLS STEEL',
            season_intro: 'Missed a game? You can find all our match replays right here! (Subject to my attendance and the battery life of my camera.)',
            main_team_name: 'OSU Steel',
            filter_all_label: 'All Matches',
            filter_home_label: 'Home',
            filter_away_label: 'Away',
            stat_matches_label: 'Matches',
            stat_ready_label: 'Ready',
            stat_processing_label: 'Processing',
            game_back_label: 'Back to Matches',
            game_replay_label: 'Match Replay',
            game_video_status_label: 'Video Status',
            download_label: 'Download',
            downloads_enabled: '1',
            live_enabled: '1',
            live_offline_message: 'No live stream right now. Check back at kick-off.',
            live_rtmp_public_url: '',
            app_logo_filename: '',
            favicon_filename: '',
        };
    },

    getAppSettings() {
        return this.appSettings || this.getDefaultAppSettings();
    },

    async loadAppSettings(force = false) {
        if (!force && window.__APP_SETTINGS__) {
            this.setAppSettingsPayload(window.__APP_SETTINGS__);
            return;
        }
        try {
            const resp = await fetch('/api/settings');
            if (!resp.ok) throw new Error('Failed to load settings');
            const payload = await resp.json();
            this.setAppSettingsPayload(payload);
        } catch (error) {
            console.error('Failed to load app settings', error);
            this.setAppSettingsPayload({ settings: this.getDefaultAppSettings(), assets: {} });
        }
    },

    setAppSettingsPayload(payload) {
        const defaults = this.getDefaultAppSettings();
        this.appSettings = { ...defaults, ...(payload?.settings || {}) };
        this.appAssets = {
            logo_url: payload?.assets?.logo_url || '/static/logo.png',
            favicon_url: payload?.assets?.favicon_url || '/static/logo.png',
        };
    },

    mainTeamNameNormalized() {
        return (this.getAppSettings().main_team_name || '').trim().toLowerCase();
    },

    matchFilterCategory(match) {
        const mainTeamName = this.mainTeamNameNormalized();
        if (!mainTeamName) return 'all';
        const home = (match.home_team || '').trim().toLowerCase();
        const away = (match.away_team || '').trim().toLowerCase();
        if (home === mainTeamName) return 'home';
        if (away === mainTeamName) return 'away';
        return 'other';
    },

    filteredMatches() {
        let results = this.matches;

        if (this.mainTeamNameNormalized() && this.activeFilter !== 'all') {
            results = results.filter((match) => this.matchFilterCategory(match) === this.activeFilter);
        }

        const q = (this.searchQuery || '').trim().toLowerCase();
        if (q) {
            results = results.filter((match) =>
                (match.home_team || '').toLowerCase().includes(q) ||
                (match.away_team || '').toLowerCase().includes(q) ||
                (match.location || '').toLowerCase().includes(q) ||
                (match.date || '').includes(q)
            );
        }

        return results;
    },

    checkTranscodePolling() {
        if (this.anyTranscoding()) {
            this.startTranscodePolling();
        }
    },

    startTranscodePolling() {
        if (this._pollTimer) return;
        this._pollTimer = setInterval(async () => {
            await this.loadMatches();
            await this.fetchTranscodeProgress();
            this.renderSeasonView();

            if (this.activeMatchId) {
                const match = this.matches.find(m => m.id === this.activeMatchId);
                if (match) this.refreshGameView(match);
            }

            if (!this.anyTranscoding()) {
                this.transcodeProgress = {};
                clearInterval(this._pollTimer);
                this._pollTimer = null;
            }
        }, 5000);
    },

    async fetchTranscodeProgress() {
        const progress = {};
        const fetches = [];
        for (const match of this.matches) {
            const vs = match.video_status || {};
            for (const [slot, status] of Object.entries(vs)) {
                if (status === 'transcoding') {
                    fetches.push(
                        fetch(`/api/matches/${match.id}/transcode-progress/${slot}`)
                            .then(r => r.ok ? r.json() : null)
                            .then(data => { if (data?.active) progress[`${match.id}/${slot}`] = data; })
                            .catch(() => {})
                    );
                }
            }
        }
        await Promise.all(fetches);
        this.transcodeProgress = progress;
    },

    getSlotProgress(matchId, slot) {
        return (this.transcodeProgress || {})[`${matchId}/${slot}`] || null;
    },

    stopTranscodePolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    },

    // ===== USER MANAGEMENT =====
    async loadUsers() {
        try {
            const resp = await fetch('/api/users', { headers: this.getAuthHeaders() });
            if (!resp.ok) return [];
            return await resp.json();
        } catch { return []; }
    },

    async createUser(data) {
        const resp = await fetch('/api/users', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create user');
        }
        return resp.json();
    },

    async updateUser(userId, data) {
        const resp = await fetch(`/api/users/${userId}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to update user');
        }
        return resp.json();
    },

    async deleteUser(userId) {
        const resp = await fetch(`/api/users/${userId}`, {
            method: 'DELETE',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error('Failed to delete user');
        return resp.json();
    },
};
