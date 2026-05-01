// Auth, data loading, and settings data methods.

export const apiMixin = {
    getAuthHeaders() {
        const headers = {};
        if (this.authToken) {
            headers['Authorization'] = 'Bearer ' + this.authToken;
        }
        return headers;
    },

    async authFetch(url, opts = {}) {
        const resp = await fetch(url, opts);
        if (resp.status === 401) {
            this.setLoggedOut();
            sessionStorage.removeItem('replay_admin_token');
            this.showLoginModal();
            throw new Error('Session expired. Please log in again.');
        }
        return resp;
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
                this.userRoles = data.roles || [this.userRole];
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
        return this.hasRole('admin');
    },

    hasRole(role) {
        const roles = this.userRoles || (this.userRole ? String(this.userRole).split(',') : []);
        if (roles.includes('admin')) return true;
        return roles.includes(role);
    },

    canCoach() {
        return this.hasRole('coach');
    },

    canEdit() {
        return this.hasRole('uploader');
    },

    setLoggedIn() {
        const navAdmin = document.getElementById('nav-admin');
        if (navAdmin) navAdmin.style.display = this.canEdit() ? '' : 'none';
        const navCoach = document.getElementById('nav-coach');
        if (navCoach) navCoach.style.display = this.canCoach() ? '' : 'none';
        const navFeedback = document.getElementById('nav-feedback');
        if (navFeedback) navFeedback.style.display = '';
        document.getElementById('nav-login-btn').style.display = 'none';
        document.getElementById('nav-logout-btn').style.display = '';
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn && this.activeMatchId) gameEditBtn.style.display = this.canEdit() ? 'inline-flex' : 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn && this.activeMatchId) regenThumbBtn.style.display = this.isAdmin() ? 'inline-flex' : 'none';
        this.setAdminPanelVisibility(this.isAdmin());
        this.renderCoachingPanel?.();
        if (this.isAdmin()) this.refreshAdminDiagnostics();
    },

    setLoggedOut() {
        this.authToken = null;
        this.userRole = null;
        this.userRoles = [];
        this.userName = null;
        const navAdmin = document.getElementById('nav-admin');
        if (navAdmin) navAdmin.style.display = 'none';
        const navCoach = document.getElementById('nav-coach');
        if (navCoach) navCoach.style.display = 'none';
        const navFeedback = document.getElementById('nav-feedback');
        if (navFeedback) navFeedback.style.display = 'none';
        document.getElementById('nav-login-btn').style.display = '';
        document.getElementById('nav-logout-btn').style.display = 'none';
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn) gameEditBtn.style.display = 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn) regenThumbBtn.style.display = 'none';
        this.setAdminPanelVisibility(false);
        this.stopAdminStatusPolling?.();
        if (document.getElementById('admin-view')?.classList.contains('active')) {
            this.cancelEdit();
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
        }
        if (document.getElementById('coach-view')?.classList.contains('active') ||
            document.getElementById('feedback-view')?.classList.contains('active')) {
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
            this.userRoles = data.roles || [this.userRole];
            this.userName = data.username || '';
            sessionStorage.setItem('replay_admin_token', data.token);
            this.setLoggedIn();
            this.hideLoginModal();
            this.renderSeasonView();
            this.renderCoachingPanel?.();
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
        const hadData = this.matches.length > 0;
        try {
            const resp = await fetch('/api/matches');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            this.matches = await resp.json();
            this._matchLoadErrorShown = false;
        } catch (e) {
            console.error('Failed to load matches', e);
            if (hadData && !this._matchLoadErrorShown) {
                this._matchLoadErrorShown = true;
                this.showInfo("Couldn't refresh matches — showing last known data.");
            }
        }
    },

    getDefaultAppSettings() {
        return {
            app_name: 'Replay',
            nav_matches_label: 'Matches',
            nav_admin_label: 'Admin',
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
            this.updateTranscodeBadges();

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
        try {
            const resp = await fetch('/api/transcode-progress');
            this.transcodeProgress = resp.ok ? await resp.json() : this.transcodeProgress;
        } catch {
            // keep previous progress on transient network error
        }
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

    // ===== COACHING =====
    async loadCoachBundle(matchId = null) {
        const suffix = matchId ? `?match_id=${encodeURIComponent(matchId)}` : '';
        const [playersResp, notesResp, playlistsResp, users] = await Promise.all([
            this.authFetch('/api/coach/players', { headers: this.getAuthHeaders() }),
            this.authFetch(`/api/coach/notes${suffix}`, { headers: this.getAuthHeaders() }),
            this.authFetch('/api/coach/playlists', { headers: this.getAuthHeaders() }),
            this.authFetch('/api/coach/users', { headers: this.getAuthHeaders() }),
        ]);
        if (!playersResp.ok || !notesResp.ok || !playlistsResp.ok || !users.ok) {
            throw new Error('Failed to load coaching workspace');
        }
        return {
            players: (await playersResp.json()).players || [],
            notes: (await notesResp.json()).notes || [],
            playlists: (await playlistsResp.json()).playlists || [],
            users: (await users.json()).users || [],
        };
    },

    async createCoachPlayer(data) {
        const resp = await this.authFetch('/api/coach/players', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to create player');
        return resp.json();
    },

    async linkCoachPlayer(data) {
        const resp = await this.authFetch('/api/coach/player-links', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to link account');
        return resp.json();
    },

    async unlinkCoachPlayer(linkId) {
        const resp = await this.authFetch(`/api/coach/player-links/${linkId}`, {
            method: 'DELETE',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error('Failed to remove roster link');
        return resp.json();
    },

    async createCoachNote(data) {
        const resp = await this.authFetch('/api/coach/notes', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save coaching note');
        return resp.json();
    },

    async updateCoachNote(noteId, data) {
        const resp = await this.authFetch(`/api/coach/notes/${noteId}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to update coaching note');
        return resp.json();
    },

    async deleteCoachNote(noteId) {
        const resp = await this.authFetch(`/api/coach/notes/${noteId}`, {
            method: 'DELETE',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error('Failed to delete coaching note');
        return resp.json();
    },

    async createCoachPlaylist(data) {
        const resp = await this.authFetch('/api/coach/playlists', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save playlist');
        return resp.json();
    },

    async loadMyFeedback() {
        const resp = await this.authFetch('/api/my-feedback', { headers: this.getAuthHeaders() });
        if (!resp.ok) throw new Error('Failed to load feedback');
        return resp.json();
    },

    async markFeedbackReviewed(data) {
        const resp = await this.authFetch('/api/my-feedback/review', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to mark reviewed');
        return resp.json();
    },
};
