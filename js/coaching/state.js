// Active team/season scope state and nav switcher methods.

export const coachingStateMixin = {
    async loadMeScope() {
        if (!this.authToken) {
            this.meScope = null;
            this.activeScope = null;
            this.renderScopeSwitcher();
            return null;
        }
        try {
            const resp = await this.authFetch('/api/me', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load active scope');
            const payload = await resp.json();
            this.meScope = payload;
            this.activeScope = payload.active_scope || null;
            this.renderScopeSwitcher();
            // Re-evaluate nav visibility now that membership data is
            // available — canCoach() consults meScope.memberships so a
            // viewer-role user with a coach/team_admin membership
            // upgrades from "no /coach nav link" to "nav link visible"
            // at this point. setLoggedIn is idempotent (it sets
            // style.display from the current canCoach/canEdit/isAdmin
            // values) so calling it twice during login is safe.
            this.setLoggedIn?.();
            return payload;
        } catch (error) {
            console.error('Failed to load active scope', error);
            this.meScope = null;
            this.activeScope = null;
            this.renderScopeSwitcher();
            return null;
        }
    },

    scopeTeamOptions() {
        return Array.isArray(this.meScope?.teams) ? this.meScope.teams : [];
    },

    scopeSeasonOptions(teamId = null) {
        const selectedTeamId = teamId || this.activeScope?.team?.id || this.meScope?.user?.last_team_id || '';
        const team = this.scopeTeamOptions().find((item) => item.id === selectedTeamId);
        if (team && Array.isArray(team.seasons)) return team.seasons;
        return (Array.isArray(this.meScope?.seasons) ? this.meScope.seasons : [])
            .filter((season) => !selectedTeamId || season.team_id === selectedTeamId);
    },

    activeScopeLabel() {
        if (!this.meScope) return 'Select team';
        const team = this.activeScope?.team;
        const season = this.activeScope?.season;
        if (team?.name && season?.name) return `${team.name} · ${season.name}`;
        if (team?.name) return team.name;
        if (this.meScope.selection_required) return 'Select team';
        const teams = this.scopeTeamOptions();
        return teams.length ? 'Select team' : 'No team scope';
    },

    renderScopeSwitcher() {
        const root = document.getElementById('nav-scope-switcher');
        if (!root) return;
        const trigger = document.getElementById('nav-scope-trigger');
        const panel = document.getElementById('nav-scope-panel');
        const label = document.getElementById('nav-scope-label');
        const teamSelect = document.getElementById('nav-scope-team');
        const seasonSelect = document.getElementById('nav-scope-season');
        const help = document.getElementById('nav-scope-help');
        const teams = this.scopeTeamOptions();
        const seasonCount = teams.reduce((count, team) => count + (Array.isArray(team.seasons) ? team.seasons.length : 0), 0);
        const shouldShow = !!this.authToken && (teams.length > 1 || seasonCount > 1) && (this.canCoach?.() || this.isAdmin?.());
        root.hidden = !shouldShow;
        if (!shouldShow) {
            if (panel) panel.hidden = true;
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
            return;
        }

        const activeTeamId = this.activeScope?.team?.id || this.meScope?.user?.last_team_id || teams[0]?.id || '';
        const seasons = this.scopeSeasonOptions(activeTeamId);
        const activeSeasonId = this.activeScope?.season?.id || this.meScope?.user?.last_season_id || seasons[0]?.id || '';
        if (label) label.textContent = this.activeScopeLabel();
        root.classList.toggle('needs-selection', !!this.meScope?.selection_required || !this.activeScope);
        if (teamSelect) {
            teamSelect.innerHTML = teams.map((team) =>
                `<option value="${this.esc(team.id)}" ${team.id === activeTeamId ? 'selected' : ''}>${this.esc(team.name || team.slug || team.id)}</option>`
            ).join('');
        }
        if (seasonSelect) {
            seasonSelect.innerHTML = seasons.map((season) =>
                `<option value="${this.esc(season.id)}" ${season.id === activeSeasonId ? 'selected' : ''}>${this.esc(season.name || season.id)}</option>`
            ).join('');
            seasonSelect.disabled = seasons.length === 0;
        }
        if (help) {
            help.textContent = this.meScope?.selection_required
                ? 'Pick the team and season to use for coach/admin work.'
                : 'Changes are saved to your account and used by scoped coach/admin APIs.';
        }
        const open = !!this._scopeSwitcherOpen;
        if (panel) panel.hidden = !open;
        if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    },

    toggleScopeSwitcher(force = null) {
        this._scopeSwitcherOpen = force === null ? !this._scopeSwitcherOpen : !!force;
        this.renderScopeSwitcher();
    },

    async handleScopeTeamChange(teamId) {
        const seasons = this.scopeSeasonOptions(teamId);
        const seasonId = seasons[0]?.id || '';
        this.renderScopeSwitcher();
        if (seasonId) await this.saveActiveScope(teamId, seasonId);
    },

    async handleScopeSeasonChange(seasonId) {
        const teamId = document.getElementById('nav-scope-team')?.value || this.activeScope?.team?.id || '';
        if (teamId && seasonId) await this.saveActiveScope(teamId, seasonId);
    },

    async saveActiveScope(teamId, seasonId) {
        if (!teamId || !seasonId) return;
        const help = document.getElementById('nav-scope-help');
        if (help) help.textContent = 'Saving active scope…';
        try {
            const resp = await this.authFetch('/api/me/scope', {
                method: 'PUT',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ team_id: teamId, season_id: seasonId }),
            });
            if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'Failed to save active scope');
            const payload = await resp.json();
            this.meScope = payload;
            this.activeScope = payload.active_scope || null;
            this.clearScopedViewData();
            this.renderScopeSwitcher();
            this.showSuccess?.('Active team and season updated.');
            await this.refreshAfterScopeChange();
        } catch (error) {
            if (help) help.textContent = error.message || 'Could not save that scope.';
            this.showError?.(error.message || 'Could not save active scope.');
            await this.loadMeScope();
        }
    },

    clearScopedViewData() {
        this.matches = [];
        this._matchLoadErrorShown = false;
        this._coachBundle = null;
        this._teamSettings = null;
        this._feedbackData = null;
        this._feedbackDevCache = null;
        const placeholders = [
            ['coach-roster-list', 'Loading roster…'],
            ['coach-notes-list', 'Loading notes…'],
            ['coach-playlists-list', 'Loading playlists…'],
            ['coach-clips-list', 'Loading clips…'],
            ['coach-summaries-list', 'Loading summaries…'],
            ['coach-engagement-dashboard', 'Loading engagement…'],
            ['coach-team-settings-content', 'Loading team settings…'],
            ['feedback-playlists-list', 'Loading playlists…'],
            ['feedback-notes-list', 'Loading notes…'],
            ['feedback-clips-list', 'Loading clips…'],
            ['feedback-summaries-list', 'Loading summaries…'],
            ['feedback-development-content', 'Loading development profile…'],
            ['library-table-wrap', 'Loading match library…'],
        ];
        placeholders.forEach(([id, text]) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `<div class="session-empty">${this.esc(text)}</div>`;
        });
    },

    async refreshAfterScopeChange() {
        await this.loadMatches();
        if (document.getElementById('coach-view')?.classList.contains('active')) {
            await this.showCoachView({ pushHistory: false, scrollTop: false, tab: this.coachActiveTab || null });
            return;
        }
        if (document.getElementById('feedback-view')?.classList.contains('active')) {
            await this.showFeedbackView({ pushHistory: false, scrollTop: false, tab: this.feedbackActiveTab || null });
            return;
        }
        if (document.getElementById('admin-view')?.classList.contains('active')) {
            this.renderAdminSectionContent?.(this._adminSection || this.defaultAdminSection?.() || 'overview');
            this.renderAdminStatusStrip?.();
            this.refreshAdminDiagnostics?.();
            return;
        }
        this.renderSeasonView();
    },

};
