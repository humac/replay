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
        if (this.activeMatchId) {
            const match = this.matches.find((m) => m.id === this.activeMatchId);
            this.updateCoachThisMatchLink?.(match);
        }
        if (this.isAdmin()) this.refreshAdminDiagnostics();
    },

    setLoggedOut() {
        this.authToken = null;
        this.userRole = null;
        this.userRoles = [];
        this.userName = null;
        // Phase 3b/4e: revoke every cached thumbnail object URL so
        // blobs from the prior session don't outlive their visibility
        // context. The caches are rebuilt lazily on the next mount.
        this.clearCoachNoteThumbnailCache?.();
        this.clearCoachClipThumbnailCache?.();
        // Phase 5b: drop the sticky My Feedback Development player
        // selection so user A's UUID can't seed user B's first render.
        // The in-render guard in `renderFeedbackDevelopment` would also
        // catch a mismatch, but resetting here keeps the cleanup
        // pattern consistent with the coaching state above.
        this._feedbackDevPlayerId = null;
        // Phase 6e: drop the cached per-player development payloads so a
        // viewer detail click can't replay user A's notes for user B.
        this._feedbackDevCache = null;
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
        const coachLink = document.getElementById('coach-this-match-link');
        if (coachLink) coachLink.hidden = true;
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
        } catch {
            errorEl.textContent = 'Login failed. Please try again.';
            errorEl.style.display = 'block';
        }
    },

    async logout() {
        // Phase 3b PR #92 review follow-up: cancel any in-flight
        // coach-note thumbnail fetches BEFORE we POST /api/logout.
        // Otherwise the server-side token revocation lands while our
        // thumbnail fetches are still on the wire, causing each one to
        // come back with a 401 and emit a browser-level DevTools error.
        // The abort short-circuits them cleanly with `AbortError` (which
        // `loadCoachNoteThumbnail` catches silently).
        this.clearCoachNoteThumbnailCache?.();
        this.clearCoachClipThumbnailCache?.();
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
        // Phase 4b: also fetch /api/coach/clips so the new Coach > Clips
        // sub-tab + the Save-clip control in Coach Review can render
        // without an extra network round-trip on every tab switch. The
        // clips endpoint is the same role-gated surface as notes /
        // playlists (PR #95), so this is one more parallel coach-only
        // GET in the same `Promise.all`.
        const [playersResp, notesResp, playlistsResp, clipsResp, goalsResp, users] = await Promise.all([
            this.authFetch('/api/coach/players', { headers: this.getAuthHeaders() }),
            this.authFetch(`/api/coach/notes${suffix}`, { headers: this.getAuthHeaders() }),
            this.authFetch('/api/coach/playlists', { headers: this.getAuthHeaders() }),
            this.authFetch(`/api/coach/clips${suffix}`, { headers: this.getAuthHeaders() }),
            this.authFetch('/api/coach/goals', { headers: this.getAuthHeaders() }),
            this.authFetch('/api/coach/users', { headers: this.getAuthHeaders() }),
        ]);
        if (!playersResp.ok || !notesResp.ok || !playlistsResp.ok || !clipsResp.ok || !goalsResp.ok || !users.ok) {
            throw new Error('Failed to load coaching workspace');
        }
        return {
            players: (await playersResp.json()).players || [],
            notes: (await notesResp.json()).notes || [],
            playlists: (await playlistsResp.json()).playlists || [],
            clips: (await clipsResp.json()).clips || [],
            goals: (await goalsResp.json()).goals || [],
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

    async updateCoachPlayer(playerId, data) {
        const resp = await this.authFetch(`/api/coach/players/${playerId}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to update player');
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

    async updateCoachPlaylist(playlistId, data) {
        const resp = await this.authFetch(`/api/coach/playlists/${playlistId}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to update playlist');
        return resp.json();
    },

    // ===== Phase 4b — Coaching clip CRUD helpers =====
    //
    // Backend endpoints landed in PR #95 (Phase 4a). Helpers here are
    // thin wrappers that mirror the note / playlist patterns: each
    // request goes through `authFetch` so 401s drive the login modal,
    // each error is surfaced via the response body's `detail` so the
    // coach sees the Pydantic validation message (window invariants,
    // duration cap, unknown match/player/source-note IDs, etc.).
    //
    // For My Feedback the viewer reads clips through `/api/my-feedback`
    // (already wired in Phase 4a's `loadMyFeedback`), so there is NO
    // viewer-only clip GET helper here — that endpoint is coach/admin
    // only by design.
    //
    // **Phase 4c (PR #96 review fix-up — issue #97)**: all five
    // helpers now return a normalized shape, consistent with each
    // other AND with the rest of `js/api.js`:
    //   - listCoachClips()    -> Array<clip>      (the `clips` array)
    //   - getCoachClip(id)    -> clip             (single clip object)
    //   - createCoachClip()   -> clip             (the new clip)
    //   - updateCoachClip()   -> clip             (the updated clip)
    //   - deleteCoachClip()   -> { ok: true }     (envelope — no clip body)
    //
    // Backend response shape is unchanged (`{ ok: true, clip: {...} }`
    // / `{ ok: true, clips: [...] }`); the helpers just unwrap the
    // payload field so callers don't have to remember
    // `result.clip.title` vs `result.title`. Existing call sites in
    // `js/coaching.js` discard the return value (just `await`), so
    // unwrapping is safe.

    async listCoachClips(matchId = null) {
        const suffix = matchId ? `?match_id=${encodeURIComponent(matchId)}` : '';
        const resp = await this.authFetch(`/api/coach/clips${suffix}`, {
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to load coaching clips');
        return (await resp.json()).clips || [];
    },

    async getCoachClip(clipId) {
        const resp = await this.authFetch(`/api/coach/clips/${Number(clipId)}`, {
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to load clip');
        return (await resp.json()).clip || null;
    },

    async createCoachClip(data) {
        const resp = await this.authFetch('/api/coach/clips', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save coaching clip');
        return (await resp.json()).clip || null;
    },

    async updateCoachClip(clipId, data) {
        const resp = await this.authFetch(`/api/coach/clips/${Number(clipId)}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to update coaching clip');
        return (await resp.json()).clip || null;
    },

    async deleteCoachClip(clipId) {
        const resp = await this.authFetch(`/api/coach/clips/${Number(clipId)}`, {
            method: 'DELETE',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to delete coaching clip');
        return resp.json();
    },

    async createCoachGoal(data) {
        const resp = await this.authFetch('/api/coach/goals', {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save player goal');
        return (await resp.json()).goal || null;
    },

    async updateCoachGoal(goalId, data) {
        const resp = await this.authFetch(`/api/coach/goals/${Number(goalId)}`, {
            method: 'PATCH',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to update player goal');
        return (await resp.json()).goal || null;
    },

    async deleteCoachGoal(goalId) {
        const resp = await this.authFetch(`/api/coach/goals/${Number(goalId)}`, {
            method: 'DELETE',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to delete player goal');
        return resp.json();
    },

    async createMyGoalReflection(goalId, reflection) {
        const resp = await this.authFetch(`/api/my-feedback/goals/${Number(goalId)}/reflection`, {
            method: 'POST',
            headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ reflection }),
        });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save reflection');
        return (await resp.json()).reflection || null;
    },

    async loadMyFeedback() {
        const resp = await this.authFetch('/api/my-feedback', { headers: this.getAuthHeaders() });
        if (!resp.ok) throw new Error('Failed to load feedback');
        return resp.json();
    },

    // ===== Phase 3b — coach-note thumbnails =====
    //
    // The thumbnail endpoint (`GET /api/coach/notes/{id}/thumbnail`) is
    // visibility-checked per-viewer and authenticated via the same
    // Bearer token used by every other API call. Plain `<img src>` can't
    // attach an Authorization header, and we can't put the token in a
    // query param (auth.py only accepts Authorization), so we fetch the
    // JPEG with `getAuthHeaders()` and convert it to an object URL the
    // browser can render via `<img src>`.
    //
    // **Why raw `fetch` instead of `authFetch`** (Phase 3b PR #92 review
    // follow-up): thumbnails fan out — a Coach Notes list re-render
    // fires one fetch per visible row. Routing every thumbnail through
    // `authFetch` would cause a single expired-token state to spam
    // dozens of `setLoggedOut()` + `showLoginModal()` calls in
    // parallel as each individual thumbnail 401'd. Instead we use raw
    // `fetch` so 401/403/404 all degrade silently to the placeholder
    // (the user's next non-thumbnail action — opening a note, saving,
    // etc. — runs through `authFetch` and surfaces the auth flow
    // properly). When we DO see a 401 we still drop the auth state via
    // a single `setLoggedOut()` call so the next user click doesn't
    // succeed with a stale token; we just don't pop the login modal
    // from a fetch the user didn't trigger.
    //
    // Cache layout: per-note entry of one of three shapes:
    //   - Promise<string|null>     in-flight fetch (dedupes concurrent calls)
    //   - { url: string }          successful — object URL ready to assign
    //   - { url: null }            negative cache (404 / 403 / network) —
    //                              prevents the same broken image from
    //                              re-firing on every re-render
    //
    // Negative cache entries are kept until `clearCoachNoteThumbnailCache()`
    // or `invalidateCoachNoteThumbnail(id)` is called (the latter runs
    // after a successful regenerate) — that's deliberate so the timeline
    // rail doesn't issue 30 requests per second when the user scrolls past
    // a stretch of notes that genuinely have no thumbnail.
    //
    // **Generation counter** (Phase 3b PR #92 review follow-up): every
    // call to `clearCoachNoteThumbnailCache()` bumps `_coachThumbGen`.
    // In-flight `loadCoachNoteThumbnail` fetches capture the generation
    // at start and check it again before committing the resulting
    // object URL to the cache. If the generation moved (because the
    // user logged out mid-fetch), the resolved blob URL is revoked
    // immediately and the cache entry is NOT written — so a logout
    // during pending fetches cannot leave orphan blobs from the prior
    // session alive past the next page reload.

    coachNoteThumbnailUrl(noteId) {
        // Returns the API URL — NOT a usable <img src> (no auth header).
        // Use loadCoachNoteThumbnail() to get a renderable object URL.
        return `/api/coach/notes/${Number(noteId)}/thumbnail`;
    },

    _coachNoteThumbnailCache() {
        if (!this._coachThumbCache) this._coachThumbCache = new Map();
        return this._coachThumbCache;
    },

    _coachThumbGeneration() {
        // Monotonically increasing token bumped on every cache clear.
        // Used by in-flight loads to detect "the cache I started this
        // fetch against is no longer the active one" (logout race).
        if (typeof this._coachThumbGen !== 'number') this._coachThumbGen = 0;
        return this._coachThumbGen;
    },

    _coachThumbAbortController() {
        // One AbortController per generation. `clearCoachNoteThumbnailCache()`
        // calls `.abort()` on the current one and replaces it, so any
        // in-flight thumbnail fetches at logout time are cleanly
        // cancelled rather than running to completion against the
        // now-stale token (which would cause browser-level 401s in the
        // DevTools console).
        if (!this._coachThumbAbort || this._coachThumbAbort._gen !== this._coachThumbGeneration()) {
            const ctrl = new AbortController();
            ctrl._gen = this._coachThumbGeneration();
            this._coachThumbAbort = ctrl;
        }
        return this._coachThumbAbort;
    },

    async loadCoachNoteThumbnail(noteId) {
        // Returns a string object-URL on success, or `null` when the
        // server has no thumbnail / the viewer can't see this note /
        // the network errored. Never throws — callers should treat
        // `null` as "show placeholder" and move on.
        const id = Number(noteId);
        if (!Number.isFinite(id) || id <= 0) return null;
        const cache = this._coachNoteThumbnailCache();
        const cached = cache.get(id);
        if (cached !== undefined) {
            // Promise (in-flight) — await it; or { url } — return the value.
            if (cached && typeof cached.then === 'function') return cached;
            return cached.url;
        }
        // Snapshot the cache generation + abort signal BEFORE we kick
        // off the fetch so we can both (a) detect a clear that lands
        // while we're awaiting, and (b) get cancelled cleanly via
        // signal.abort() when logout happens.
        const startGen = this._coachThumbGeneration();
        const signal = this._coachThumbAbortController().signal;
        const promise = (async () => {
            try {
                const resp = await fetch(this.coachNoteThumbnailUrl(id), {
                    headers: this.getAuthHeaders(),
                    signal,
                });
                // Generation changed mid-fetch (logout / cache clear) —
                // bail without writing to the cache or producing a
                // blob URL. The body is discarded; nothing to revoke.
                if (this._coachThumbGeneration() !== startGen) return null;
                if (!resp.ok) {
                    if (resp.status === 401) {
                        // Token is stale. Don't pop the login modal
                        // from a fetch the user didn't trigger (every
                        // visible row would race), but DO clear local
                        // auth state so the next user-driven authFetch
                        // surfaces the login flow naturally.
                        try { this.setLoggedOut?.(); } catch { /* ignore */ }
                        return null;
                    }
                    // 403 / 404 (not generated yet, no permission to view) is
                    // the common case — degrade silently to placeholder.
                    cache.set(id, { url: null });
                    return null;
                }
                const blob = await resp.blob();
                // Re-check generation: clearCache() may have run while we
                // were reading the blob body. If so, never call
                // createObjectURL — there is nothing to revoke and the
                // viewer this blob was authorized for is gone.
                if (this._coachThumbGeneration() !== startGen) return null;
                const url = URL.createObjectURL(blob);
                // Final guard between `createObjectURL` and `cache.set`:
                // if a clear happened in the same microtask tick, revoke
                // the blob we just created so it doesn't leak.
                if (this._coachThumbGeneration() !== startGen) {
                    try { URL.revokeObjectURL(url); } catch { /* ignore */ }
                    return null;
                }
                cache.set(id, { url });
                return url;
            } catch (err) {
                // AbortError on logout-cancel is expected and silent —
                // no console noise, no negative-cache write (the cache
                // was already cleared by the same call that aborted us).
                if (err?.name === 'AbortError') return null;
                // Network error — negative-cache only if the cache is
                // still the one we started against.
                if (this._coachThumbGeneration() === startGen) {
                    cache.set(id, { url: null });
                }
                return null;
            }
        })();
        cache.set(id, promise);
        return promise;
    },

    /** Mount a thumbnail into an `<img>` element. The element should
     *  start with the placeholder class; on success this method swaps in
     *  the object URL and removes the placeholder marker. On failure or
     *  missing thumbnail the placeholder stays as-is — no broken-image
     *  icon, no error toast.
     *
     *  Idempotent: safe to call repeatedly with the same element (e.g.
     *  on re-render — the cache hit makes it a no-op after the first
     *  successful load). */
    async mountCoachNoteThumbnail(imgEl, noteId) {
        if (!imgEl) return;
        const url = await this.loadCoachNoteThumbnail(noteId);
        if (!url) return; // placeholder already in DOM — leave it.
        // Element may have been removed from the DOM between request
        // and response (e.g. user navigated away). Skip the assignment
        // in that case so we don't pin an orphan.
        if (!imgEl.isConnected) return;
        imgEl.src = url;
        imgEl.dataset.thumbState = 'loaded';
        const wrapper = imgEl.closest('[data-thumb]');
        if (wrapper) wrapper.dataset.thumbState = 'loaded';
    },

    /** Mount thumbnails for every `<img data-coach-note-thumb="<id>">`
     *  inside a container. Used after rendering a list — one call wires
     *  every row. Errors on individual thumbnails are isolated. */
    mountCoachNoteThumbnailsIn(container) {
        if (!container) return;
        const imgs = container.querySelectorAll('img[data-coach-note-thumb]');
        imgs.forEach((img) => {
            const id = Number(img.dataset.coachNoteThumb);
            if (Number.isFinite(id) && id > 0) {
                this.mountCoachNoteThumbnail(img, id);
            }
        });
    },

    /** Drop the cached thumbnail (and its object URL, if any) for one
     *  note. Used after a coach calls regenerate so the next render
     *  refetches the freshly-generated JPEG. */
    invalidateCoachNoteThumbnail(noteId) {
        const id = Number(noteId);
        const cache = this._coachNoteThumbnailCache();
        const entry = cache.get(id);
        if (entry && typeof entry === 'object' && entry.url) {
            try { URL.revokeObjectURL(entry.url); } catch { /* ignore */ }
        }
        cache.delete(id);
    },

    /** Drop every cached thumbnail. Bumps the generation counter so any
     *  in-flight `loadCoachNoteThumbnail` fetches that resolve after this
     *  call discard their results (and revoke any blob URL they created)
     *  instead of re-populating the now-empty cache with orphan entries.
     *
     *  Also `.abort()`s the current generation's AbortController so any
     *  pending HTTP requests are cancelled cleanly — no browser-level
     *  401 console noise from in-flight thumbnail fetches racing logout.
     *
     *  Wired into `setLoggedOut()` so blobs from a prior session don't
     *  outlive their visibility context. */
    clearCoachNoteThumbnailCache() {
        const cache = this._coachNoteThumbnailCache();
        cache.forEach((entry) => {
            if (entry && typeof entry === 'object' && entry.url) {
                try { URL.revokeObjectURL(entry.url); } catch { /* ignore */ }
            }
            // Promise entries don't carry a URL yet — the abort+gen
            // bump below makes their continuation discard whatever they
            // produce. No revocation needed here.
        });
        cache.clear();
        // Cancel any in-flight HTTP requests for the current generation
        // before bumping. The next call to `_coachThumbAbortController()`
        // sees the bumped generation and creates a fresh controller.
        if (this._coachThumbAbort) {
            try { this._coachThumbAbort.abort(); } catch { /* ignore */ }
            this._coachThumbAbort = null;
        }
        this._coachThumbGen = this._coachThumbGeneration() + 1;
    },

    async regenerateCoachNoteThumbnail(noteId) {
        const resp = await this.authFetch(`/api/coach/notes/${Number(noteId)}/thumbnail/regenerate`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error('Failed to regenerate thumbnail');
        // Drop the cached blob (positive or negative) so the next
        // mount call fetches the fresh JPEG.
        this.invalidateCoachNoteThumbnail(noteId);
        return resp.json();
    },

    // -----------------------------------------------------------------
    // Phase 4e — per-coaching-clip thumbnails
    //
    // Mirrors the per-note thumbnail helpers above. Clip thumbnails are
    // served by `GET /api/coach/clips/{id}/thumbnail` which requires a
    // Bearer header, so `<img src="/api/...">` cannot be used directly —
    // we fetch with auth headers, wrap the response in `URL.createObjectURL`,
    // and cache one object URL per clip id. Negative responses (404 / 403
    // / network error) are negative-cached so a long timeline rail of
    // un-thumbnailed clips doesn't re-fire requests every render.
    //
    // Cache lifecycle is shared with the note cache: `setLoggedOut()`
    // calls `clearCoachClipThumbnailCache()` which revokes every
    // outstanding object URL and `.abort()`s any in-flight fetches so
    // blobs from the prior session don't outlive their visibility
    // context.
    // -----------------------------------------------------------------

    coachClipThumbnailUrl(clipId) {
        return `/api/coach/clips/${Number(clipId)}/thumbnail`;
    },

    _coachClipThumbnailCache() {
        if (!this._coachClipThumbCache) this._coachClipThumbCache = new Map();
        return this._coachClipThumbCache;
    },

    _coachClipThumbGeneration() {
        if (typeof this._coachClipThumbGen !== 'number') this._coachClipThumbGen = 0;
        return this._coachClipThumbGen;
    },

    _coachClipThumbAbortController() {
        if (!this._coachClipThumbAbort || this._coachClipThumbAbort._gen !== this._coachClipThumbGeneration()) {
            const ctrl = new AbortController();
            ctrl._gen = this._coachClipThumbGeneration();
            this._coachClipThumbAbort = ctrl;
        }
        return this._coachClipThumbAbort;
    },

    async loadCoachClipThumbnail(clipId) {
        const id = Number(clipId);
        if (!Number.isFinite(id) || id <= 0) return null;
        const cache = this._coachClipThumbnailCache();
        const cached = cache.get(id);
        if (cached !== undefined) {
            if (cached && typeof cached.then === 'function') return cached;
            return cached.url;
        }
        const startGen = this._coachClipThumbGeneration();
        const signal = this._coachClipThumbAbortController().signal;
        const promise = (async () => {
            try {
                const resp = await fetch(this.coachClipThumbnailUrl(id), {
                    headers: this.getAuthHeaders(),
                    signal,
                });
                if (this._coachClipThumbGeneration() !== startGen) return null;
                if (!resp.ok) {
                    if (resp.status === 401) {
                        try { this.setLoggedOut?.(); } catch { /* ignore */ }
                        return null;
                    }
                    cache.set(id, { url: null });
                    return null;
                }
                const blob = await resp.blob();
                if (this._coachClipThumbGeneration() !== startGen) return null;
                const url = URL.createObjectURL(blob);
                if (this._coachClipThumbGeneration() !== startGen) {
                    try { URL.revokeObjectURL(url); } catch { /* ignore */ }
                    return null;
                }
                cache.set(id, { url });
                return url;
            } catch (err) {
                if (err?.name === 'AbortError') return null;
                if (this._coachClipThumbGeneration() === startGen) {
                    cache.set(id, { url: null });
                }
                return null;
            }
        })();
        cache.set(id, promise);
        return promise;
    },

    /** Mount a clip thumbnail into an `<img>`. On miss, optionally fall
     *  back to the source-note (or co-located note) thumbnail provided
     *  by the caller via `data-coach-note-thumb-fallback="<noteId>"` so
     *  pre-Phase-4e clips keep their borrowed thumbnail until a coach
     *  hits Regenerate. The placeholder stays visible if both fail. */
    async mountCoachClipThumbnail(imgEl, clipId, fallbackNoteId = null) {
        if (!imgEl) return;
        const url = await this.loadCoachClipThumbnail(clipId);
        if (url) {
            if (!imgEl.isConnected) return;
            imgEl.src = url;
            imgEl.dataset.thumbState = 'loaded';
            const wrapper = imgEl.closest('[data-thumb]');
            if (wrapper) wrapper.dataset.thumbState = 'loaded';
            return;
        }
        // Fall back to the note thumbnail if the caller provided one.
        // `loadCoachNoteThumbnail` itself returns null on miss, so the
        // placeholder simply stays visible.
        const noteId = Number(fallbackNoteId);
        if (Number.isFinite(noteId) && noteId > 0) {
            const noteUrl = await this.loadCoachNoteThumbnail(noteId);
            if (!noteUrl || !imgEl.isConnected) return;
            imgEl.src = noteUrl;
            imgEl.dataset.thumbState = 'loaded';
            const wrapper = imgEl.closest('[data-thumb]');
            if (wrapper) wrapper.dataset.thumbState = 'loaded';
        }
    },

    /** Mount thumbnails for every `<img data-coach-clip-thumb="<id>">`
     *  inside a container. Honours an optional
     *  `data-coach-note-thumb-fallback="<noteId>"` so clips without a
     *  generated thumbnail can borrow the source / co-located note. */
    mountCoachClipThumbnailsIn(container) {
        if (!container) return;
        const imgs = container.querySelectorAll('img[data-coach-clip-thumb]');
        imgs.forEach((img) => {
            const id = Number(img.dataset.coachClipThumb);
            const fallback = img.dataset.coachNoteThumbFallback;
            if (Number.isFinite(id) && id > 0) {
                this.mountCoachClipThumbnail(img, id, fallback);
            }
        });
    },

    invalidateCoachClipThumbnail(clipId) {
        const id = Number(clipId);
        const cache = this._coachClipThumbnailCache();
        const entry = cache.get(id);
        if (entry && typeof entry === 'object' && entry.url) {
            try { URL.revokeObjectURL(entry.url); } catch { /* ignore */ }
        }
        cache.delete(id);
    },

    clearCoachClipThumbnailCache() {
        const cache = this._coachClipThumbnailCache();
        cache.forEach((entry) => {
            if (entry && typeof entry === 'object' && entry.url) {
                try { URL.revokeObjectURL(entry.url); } catch { /* ignore */ }
            }
        });
        cache.clear();
        if (this._coachClipThumbAbort) {
            try { this._coachClipThumbAbort.abort(); } catch { /* ignore */ }
            this._coachClipThumbAbort = null;
        }
        this._coachClipThumbGen = this._coachClipThumbGeneration() + 1;
    },

    async regenerateCoachClipThumbnail(clipId) {
        const resp = await this.authFetch(`/api/coach/clips/${Number(clipId)}/thumbnail/regenerate`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
        });
        if (!resp.ok) throw new Error('Failed to regenerate clip thumbnail');
        this.invalidateCoachClipThumbnail(clipId);
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

    // ===== Phase 5b — Player development profiles =====
    //
    // Two endpoints share the aggregator (`_build_player_development_profile`
    // in server.py), so the UI gets the same shape regardless of caller
    // role. Privacy is enforced server-side: the viewer endpoint scrubs
    // `coach_private_note` (and excludes private notes/clips/playlists),
    // while the coach endpoint returns the full data set including
    // `linked_accounts`. The UI never re-implements those rules — it
    // simply calls the right endpoint and renders what comes back.
    async getCoachPlayerDevelopment(playerId) {
        const resp = await this.authFetch(
            `/api/coach/players/${encodeURIComponent(playerId)}/development`,
            { headers: this.getAuthHeaders() },
        );
        if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}));
            throw new Error(detail.detail || `Failed to load player profile (${resp.status})`);
        }
        const data = await resp.json();
        return data.profile || null;
    },

    async getMyPlayerDevelopment(playerId) {
        const resp = await this.authFetch(
            `/api/my-feedback/players/${encodeURIComponent(playerId)}/development`,
            { headers: this.getAuthHeaders() },
        );
        if (resp.status === 404) {
            // Per backend contract, unknown / unrelated viewer / unlinked
            // player all collapse to 404 so the viewer can't probe roster
            // ids. Surface a `null` profile so the caller can render a
            // "Profile not available" empty state without throwing.
            return null;
        }
        if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}));
            throw new Error(detail.detail || `Failed to load development profile (${resp.status})`);
        }
        const data = await resp.json();
        return data.profile || null;
    },
};
