// Global-admin teams surface (Phase C of UI/UX hardening).
//
// Renders the /admin/teams two-pane shell: left list of tenants, right
// detail panel with Overview / Seasons / Memberships sub-tabs.
//
// Backed by /api/admin/teams* (introduced by platform-hardening PR 1.4).
// All endpoints require global_admin; the SPA gates entry via the
// existing Admin > Teams sidebar item which only renders when isAdmin()
// returns true.

const ADMIN_TEAM_DETAIL_TABS = ['overview', 'seasons', 'memberships'];

const ADMIN_TEAM_ROLE_LABELS = {
    team_admin: 'Team admin',
    coach: 'Coach',
    assistant_coach: 'Assistant coach',
    player: 'Player',
    guardian: 'Guardian',
};

const ADMIN_TEAM_ROLE_ORDER = ['team_admin', 'coach', 'assistant_coach', 'player', 'guardian'];

export const adminTeamsMixin = {
    _adminTeams: null,
    _adminTeamsLoadInFlight: false,
    _adminTeamsFilter: '',
    _adminActiveTeamId: null,
    _adminTeamDetailTab: 'overview',
    _adminTeamSeasons: {},        // team_id -> seasons[]
    _adminTeamMemberships: {},    // team_id -> memberships[]
    _adminTeamUsersCache: null,    // cached /api/users for the grant modal

    async loadAdminTeams(force = false) {
        const listEl = document.getElementById('admin-teams-list');
        if (!listEl) return;
        if (this._adminTeamsLoadInFlight && !force) return;
        this._adminTeamsLoadInFlight = true;
        if (force || !this._adminTeams) {
            listEl.innerHTML = '<div class="session-empty">Loading teams…</div>';
        }
        try {
            const resp = await this.authFetch('/api/admin/teams', { headers: this.getAuthHeaders() });
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || `teams_load_failed:${resp.status}`);
            }
            this._adminTeams = await resp.json();
            this.renderAdminTeamsList();
            // If a team was previously selected and still exists, re-render its detail.
            if (this._adminActiveTeamId && this._adminTeams.find((t) => t.id === this._adminActiveTeamId)) {
                this.renderAdminTeamDetail(this._adminActiveTeamId);
            }
        } catch (err) {
            listEl.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load teams.')}</div>`;
        } finally {
            this._adminTeamsLoadInFlight = false;
        }
    },

    renderAdminTeamsList() {
        const listEl = document.getElementById('admin-teams-list');
        if (!listEl) return;
        const filter = (this._adminTeamsFilter || '').toLowerCase();
        const teams = (this._adminTeams || []).filter((t) => {
            if (!filter) return true;
            return (t.name || '').toLowerCase().includes(filter) || (t.slug || '').toLowerCase().includes(filter);
        });
        if (!teams.length) {
            listEl.innerHTML = `<div class="session-empty">${filter ? 'No teams match that filter.' : 'No teams yet. Create your first team to get started.'}</div>`;
            return;
        }
        listEl.innerHTML = teams.map((t) => this.adminTeamListRowHtml(t)).join('');
    },

    adminTeamListRowHtml(team) {
        const isActive = team.id === this._adminActiveTeamId;
        const created = this.formatRelativeDate?.(team.created_at) || '';
        return `
            <button type="button" class="admin-teams-list-item ${isActive ? 'is-active' : ''}"
                data-team-id="${this.esc(team.id)}"
                onclick="app.selectAdminTeam('${this.esc(team.id)}')">
                <span class="admin-teams-list-name">${this.esc(team.name || 'Unnamed team')}</span>
                <span class="admin-teams-list-slug">/${this.esc(team.slug || team.id)}</span>
                ${created ? `<span class="admin-teams-list-meta">Created ${this.esc(created)}</span>` : ''}
            </button>
        `;
    },

    handleAdminTeamSearch(event) {
        this._adminTeamsFilter = (event.target.value || '').trim();
        this.renderAdminTeamsList();
    },

    selectAdminTeam(teamId, { tab = null } = {}) {
        this._adminActiveTeamId = teamId;
        if (tab && ADMIN_TEAM_DETAIL_TABS.includes(tab)) this._adminTeamDetailTab = tab;
        this.renderAdminTeamsList();
        this.renderAdminTeamDetail(teamId);
    },

    async renderAdminTeamDetail(teamId) {
        const detailEl = document.getElementById('admin-teams-detail');
        const emptyEl = document.getElementById('admin-teams-detail-empty');
        if (!detailEl || !emptyEl) return;
        const team = (this._adminTeams || []).find((t) => t.id === teamId);
        if (!team) {
            emptyEl.hidden = false;
            detailEl.hidden = true;
            return;
        }
        emptyEl.hidden = true;
        detailEl.hidden = false;
        detailEl.innerHTML = this.adminTeamDetailShellHtml(team);
        this.setAdminTeamDetailTab(this._adminTeamDetailTab || 'overview', { silent: true });
        // Lazy-load season + membership lists on first hit
        if (!this._adminTeamSeasons[teamId]) this.loadAdminTeamSeasons(teamId);
        if (!this._adminTeamMemberships[teamId]) this.loadAdminTeamMemberships(teamId);
    },

    adminTeamDetailShellHtml(team) {
        return `
            <header class="admin-teams-detail-head">
                <div class="admin-teams-detail-text">
                    <span class="section-kicker">Team</span>
                    <h3>${this.esc(team.name || 'Unnamed team')}</h3>
                    <p class="admin-card-sub">
                        /${this.esc(team.slug || team.id)} ·
                        ${this.esc(team.game_format || 'full')} ·
                        ID <code>${this.esc(team.id)}</code>
                    </p>
                </div>
                <div class="admin-teams-detail-actions">
                    <button type="button" class="btn-head" onclick="app.openAdminTeamRenameModal('${this.esc(team.id)}')">Edit</button>
                </div>
            </header>
            <nav class="account-tabs" role="tablist" aria-label="Team detail sections">
                <button type="button" class="account-tab" role="tab" data-admin-team-tab="overview" onclick="app.setAdminTeamDetailTab('overview')">Overview</button>
                <button type="button" class="account-tab" role="tab" data-admin-team-tab="seasons" onclick="app.setAdminTeamDetailTab('seasons')">Seasons</button>
                <button type="button" class="account-tab" role="tab" data-admin-team-tab="memberships" onclick="app.setAdminTeamDetailTab('memberships')">Memberships</button>
            </nav>
            <div class="admin-teams-detail-body">
                <div class="account-tab-panel" data-admin-team-panel="overview" role="tabpanel">
                    ${this.adminTeamOverviewHtml(team)}
                </div>
                <div class="account-tab-panel" data-admin-team-panel="seasons" role="tabpanel" hidden>
                    <div class="admin-panel-head admin-teams-subhead">
                        <p class="admin-card-sub">Seasons on this team. Add a new season to anchor scoped matches and memberships.</p>
                        <div class="admin-panel-head-actions">
                            <button type="button" class="btn-head" onclick="app.loadAdminTeamSeasons('${this.esc(team.id)}', true)">↻ Refresh</button>
                            <button type="button" class="btn-primary" onclick="app.openAdminSeasonCreateModal('${this.esc(team.id)}')">+ New season</button>
                        </div>
                    </div>
                    <div id="admin-teams-seasons-list" class="admin-teams-sub-list">
                        <div class="session-empty">Loading seasons…</div>
                    </div>
                </div>
                <div class="account-tab-panel" data-admin-team-panel="memberships" role="tabpanel" hidden>
                    <div class="admin-panel-head admin-teams-subhead">
                        <p class="admin-card-sub">Cross-tenant membership audit. Global admins can override last-admin protection if needed.</p>
                        <div class="admin-panel-head-actions">
                            <button type="button" class="btn-head" onclick="app.loadAdminTeamMemberships('${this.esc(team.id)}', true)">↻ Refresh</button>
                            <button type="button" class="btn-primary" onclick="app.openAdminMembershipGrantModal('${this.esc(team.id)}')">+ Grant membership</button>
                        </div>
                    </div>
                    <div id="admin-teams-memberships-list" class="admin-teams-sub-list">
                        <div class="session-empty">Loading memberships…</div>
                    </div>
                </div>
            </div>
        `;
    },

    adminTeamOverviewHtml(team) {
        const seasonsCount = (this._adminTeamSeasons[team.id] || []).length;
        const membershipsCount = (this._adminTeamMemberships[team.id] || []).length;
        const created = this.formatRelativeDate?.(team.created_at) || '—';
        return `
            <div class="admin-teams-overview-grid">
                <div class="team-stat-card">
                    <span class="section-kicker">Seasons</span>
                    <span class="team-stat-value">${seasonsCount}</span>
                </div>
                <div class="team-stat-card">
                    <span class="section-kicker">Memberships</span>
                    <span class="team-stat-value">${membershipsCount}</span>
                </div>
                <div class="team-stat-card">
                    <span class="section-kicker">Default format</span>
                    <span class="team-stat-value team-stat-text">${this.esc(team.game_format || 'full')}</span>
                </div>
                <div class="team-stat-card">
                    <span class="section-kicker">Created</span>
                    <span class="team-stat-value team-stat-text">${this.esc(created)}</span>
                </div>
            </div>
        `;
    },

    setAdminTeamDetailTab(tab, { silent = false } = {}) {
        if (!ADMIN_TEAM_DETAIL_TABS.includes(tab)) return;
        this._adminTeamDetailTab = tab;
        document.querySelectorAll('[data-admin-team-tab]').forEach((el) => {
            const isActive = el.dataset.adminTeamTab === tab;
            el.classList.toggle('is-active', isActive);
            el.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        document.querySelectorAll('[data-admin-team-panel]').forEach((el) => {
            el.hidden = el.dataset.adminTeamPanel !== tab;
        });
        if (!silent) {
            const panel = document.querySelector(`[data-admin-team-panel="${tab}"]`);
            const focusable = panel?.querySelector('button, input, select, textarea');
            focusable?.focus({ preventScroll: true });
        }
    },

    async loadAdminTeamSeasons(teamId, force = false) {
        const el = document.getElementById('admin-teams-seasons-list');
        try {
            const resp = await this.authFetch(
                `/api/admin/teams/${encodeURIComponent(teamId)}/seasons`,
                { headers: this.getAuthHeaders() },
            );
            if (!resp.ok) throw new Error(`seasons_load_failed:${resp.status}`);
            const seasons = await resp.json();
            this._adminTeamSeasons[teamId] = seasons;
            if (el && this._adminActiveTeamId === teamId) {
                el.innerHTML = this.adminTeamSeasonsHtml(seasons);
            }
            // Overview KPI tile depends on this count.
            if (this._adminTeamDetailTab === 'overview' && this._adminActiveTeamId === teamId) {
                this.refreshAdminTeamOverviewTiles(teamId);
            }
        } catch (err) {
            if (el && this._adminActiveTeamId === teamId) {
                el.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load seasons.')}</div>`;
            }
        }
    },

    adminTeamSeasonsHtml(seasons) {
        if (!seasons || !seasons.length) {
            return '<div class="session-empty">No seasons yet. Add one above so coaches can scope work to it.</div>';
        }
        const rows = seasons.map((s) => `
            <li class="admin-teams-sub-row">
                <div class="admin-teams-sub-meta">
                    <strong>${this.esc(s.name || 'Unnamed season')}</strong>
                    <span class="admin-card-sub">
                        ${s.starts_on ? this.esc(s.starts_on) : 'No start'} → ${s.ends_on ? this.esc(s.ends_on) : 'open-ended'}
                    </span>
                </div>
                <div class="admin-teams-sub-actions">
                    <code class="admin-mono-id">${this.esc(s.id)}</code>
                </div>
            </li>
        `).join('');
        return `<ul class="admin-teams-sub-list-items" role="list">${rows}</ul>`;
    },

    async loadAdminTeamMemberships(teamId, force = false) {
        const el = document.getElementById('admin-teams-memberships-list');
        try {
            const resp = await this.authFetch(
                `/api/admin/teams/${encodeURIComponent(teamId)}/memberships`,
                { headers: this.getAuthHeaders() },
            );
            if (!resp.ok) throw new Error(`memberships_load_failed:${resp.status}`);
            const memberships = await resp.json();
            this._adminTeamMemberships[teamId] = memberships;
            if (el && this._adminActiveTeamId === teamId) {
                el.innerHTML = this.adminTeamMembershipsHtml(teamId, memberships);
            }
            if (this._adminTeamDetailTab === 'overview' && this._adminActiveTeamId === teamId) {
                this.refreshAdminTeamOverviewTiles(teamId);
            }
        } catch (err) {
            if (el && this._adminActiveTeamId === teamId) {
                el.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load memberships.')}</div>`;
            }
        }
    },

    adminTeamMembershipsHtml(teamId, memberships) {
        if (!memberships || !memberships.length) {
            return '<div class="session-empty">No memberships yet. Grant your first member above.</div>';
        }
        const sorted = [...memberships].sort((a, b) => {
            const ar = ADMIN_TEAM_ROLE_ORDER.indexOf(a.role); const br = ADMIN_TEAM_ROLE_ORDER.indexOf(b.role);
            if (ar !== br) return ar - br;
            return (a.username || '').localeCompare(b.username || '');
        });
        const rows = sorted.map((m) => `
            <li class="admin-teams-sub-row">
                <div class="admin-teams-sub-meta">
                    <strong>${this.esc(m.display_name || m.username || 'Unnamed')}</strong>
                    <span class="admin-card-sub">
                        @${this.esc(m.username || '')} ·
                        <span class="team-pill" data-role="${this.esc(m.role)}">${this.esc(ADMIN_TEAM_ROLE_LABELS[m.role] || m.role)}</span>
                    </span>
                </div>
                <div class="admin-teams-sub-actions">
                    <button type="button" class="mini-action-btn mini-action-danger"
                        onclick="app.revokeAdminTeamMembership('${this.esc(teamId)}', ${m.id}, '${this.esc(m.display_name || m.username || '')}')">Revoke</button>
                </div>
            </li>
        `).join('');
        return `<ul class="admin-teams-sub-list-items" role="list">${rows}</ul>`;
    },

    refreshAdminTeamOverviewTiles(teamId) {
        const grid = document.querySelector('[data-admin-team-panel="overview"] .admin-teams-overview-grid');
        if (!grid) return;
        const team = (this._adminTeams || []).find((t) => t.id === teamId);
        if (team) grid.outerHTML = this.adminTeamOverviewHtml(team).trim();
    },

    // ---- Create / rename team ----

    async openAdminTeamCreateModal() {
        const template = document.getElementById('admin-team-create-form-template');
        if (!template) return;
        const body = template.content.cloneNode(true).firstElementChild;
        let root = body;
        // Auto-fill slug from name as the user types.
        const wireSlugSync = (formRoot) => {
            const nameEl = formRoot.querySelector('#admin-team-create-name');
            const slugEl = formRoot.querySelector('#admin-team-create-slug');
            let userTouchedSlug = false;
            slugEl?.addEventListener('input', () => { userTouchedSlug = true; });
            nameEl?.addEventListener('input', () => {
                if (userTouchedSlug) return;
                const v = (nameEl.value || '').toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
                if (slugEl) slugEl.value = v;
            });
        };
        this.formModal?.({
            title: 'Create a new team',
            body,
            onMount: (formRoot) => {
                root = formRoot.querySelector('#admin-team-create-form') || formRoot;
                wireSlugSync(root);
            },
            onSubmit: async (close) => {
                const banner = root.querySelector('#admin-team-create-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const data = new FormData(root.tagName === 'FORM' ? root : root.querySelector('form'));
                const name = (data.get('name') || '').toString().trim();
                const slug = (data.get('slug') || '').toString().trim();
                const game_format = (data.get('game_format') || 'full').toString();
                if (!name || !slug) { setBanner('error', 'Both name and slug are required.'); return; }
                try {
                    const resp = await this.authFetch('/api/admin/teams', {
                        method: 'POST',
                        headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, slug, game_format }),
                    });
                    const body2 = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        const msg = resp.status === 409 ? 'A team with that slug already exists.' : (body2.detail || 'Could not create team.');
                        setBanner('error', msg);
                        return;
                    }
                    this.loadAdminTeams(true);
                    // Land on the new team's detail panel.
                    if (body2.id) {
                        this._adminActiveTeamId = body2.id;
                    }
                    if (typeof close === 'function') close({ ok: true });
                } catch (err) {
                    setBanner('error', 'Network error while creating team.');
                }
            },
            confirmLabel: 'Create team',
        });
    },

    async openAdminTeamRenameModal(teamId) {
        const team = (this._adminTeams || []).find((t) => t.id === teamId);
        if (!team) return;
        const body = document.createElement('form');
        body.className = 'account-form';
        body.noValidate = true;
        body.innerHTML = `
            <div class="form-group">
                <label for="admin-team-rename-name">Team name</label>
                <input type="text" id="admin-team-rename-name" name="name" required maxlength="200" autocomplete="off" value="${this.esc(team.name || '')}">
                <p class="form-help">This changes the display name only. The team slug stays the same.</p>
            </div>
            <div id="admin-team-rename-banner" class="account-banner" hidden></div>
        `;
        let root = body;
        await this.formModal?.({
            title: 'Rename team',
            body,
            confirmLabel: 'Save name',
            onMount: (modalRoot) => {
                root = modalRoot.querySelector('form.account-form') || body;
                root.querySelector('#admin-team-rename-name')?.select();
            },
            onSubmit: async (close) => {
                const banner = root.querySelector('#admin-team-rename-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const trimmed = (root.querySelector('#admin-team-rename-name')?.value || '').trim();
                if (!trimmed) { setBanner('error', 'Team name is required.'); return; }
                if (trimmed === team.name) { close({ ok: true, unchanged: true }); return; }
                try {
                    const resp = await this.authFetch(`/api/admin/teams/${encodeURIComponent(teamId)}`, {
                        method: 'PATCH',
                        headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: trimmed }),
                    });
                    const result = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        setBanner('error', result.detail || 'Could not rename team.');
                        return;
                    }
                    this.loadAdminTeams(true);
                    close({ ok: true });
                } catch (err) {
                    setBanner('error', 'Network error while renaming team.');
                }
            },
        });
    },

    // ---- Create season ----

    openAdminSeasonCreateModal(teamId) {
        const template = document.getElementById('admin-season-create-form-template');
        if (!template) return;
        const body = template.content.cloneNode(true).firstElementChild;
        let root = body;
        this.formModal?.({
            title: 'Create a new season',
            body,
            onMount: (formRoot) => {
                root = formRoot.querySelector('#admin-season-create-form') || formRoot;
            },
            onSubmit: async (close) => {
                const form = root.tagName === 'FORM' ? root : root.querySelector('form');
                const banner = root.querySelector('#admin-season-create-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const data = new FormData(form);
                const name = (data.get('name') || '').toString().trim();
                const starts_on = (data.get('starts_on') || '').toString();
                const ends_on = (data.get('ends_on') || '').toString();
                if (!name) { setBanner('error', 'Season name is required.'); return; }
                if (starts_on && ends_on && starts_on > ends_on) {
                    setBanner('error', 'End date must be on or after the start date.');
                    return;
                }
                try {
                    const resp = await this.authFetch(`/api/admin/teams/${encodeURIComponent(teamId)}/seasons`, {
                        method: 'POST',
                        headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, starts_on, ends_on }),
                    });
                    const body2 = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        setBanner('error', body2.detail || 'Could not create season.');
                        return;
                    }
                    this.loadAdminTeamSeasons(teamId, true);
                    if (typeof close === 'function') close({ ok: true });
                } catch (err) {
                    setBanner('error', 'Network error while creating season.');
                }
            },
            confirmLabel: 'Create season',
        });
    },

    // ---- Grant membership (global admin) ----

    async openAdminMembershipGrantModal(teamId) {
        const template = document.getElementById('admin-membership-grant-form-template');
        if (!template) return;
        const body = template.content.cloneNode(true).firstElementChild;
        let root = body;
        // Load /api/users (admin-only) into a select. Cache to avoid repeated hits.
        const ensureUsers = async () => {
            if (this._adminTeamUsersCache) return this._adminTeamUsersCache;
            try {
                const resp = await this.authFetch('/api/users', { headers: this.getAuthHeaders() });
                if (resp.ok) {
                    this._adminTeamUsersCache = await resp.json();
                } else {
                    this._adminTeamUsersCache = [];
                }
            } catch { this._adminTeamUsersCache = []; }
            return this._adminTeamUsersCache;
        };
        const renderUserOptions = (formRoot, filter = '') => {
            const select = formRoot.querySelector('#admin-membership-grant-user');
            if (!select) return;
            const users = (this._adminTeamUsersCache || []).filter((u) => {
                if (!filter) return true;
                const f = filter.toLowerCase();
                return (u.username || '').toLowerCase().includes(f) || (u.display_name || '').toLowerCase().includes(f);
            });
            select.innerHTML = '';
            if (!users.length) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.disabled = true;
                opt.textContent = filter ? 'No users match' : 'No users available';
                select.appendChild(opt);
                return;
            }
            users.forEach((u) => {
                const opt = document.createElement('option');
                opt.value = u.id;
                opt.textContent = `${u.username || u.id}${u.display_name ? ` — ${u.display_name}` : ''}`;
                select.appendChild(opt);
            });
        };
        this.formModal?.({
            title: 'Grant team membership',
            body,
            onMount: async (formRoot) => {
                root = formRoot.querySelector('#admin-membership-grant-form') || formRoot;
                await ensureUsers();
                renderUserOptions(root, '');
                const search = root.querySelector('#admin-membership-grant-user-search');
                search?.addEventListener('input', (e) => renderUserOptions(root, e.target.value || ''));
            },
            onSubmit: async (close) => {
                const form = root.tagName === 'FORM' ? root : root.querySelector('form');
                const banner = root.querySelector('#admin-membership-grant-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const data = new FormData(form);
                const user_id = (data.get('user_id') || '').toString().trim();
                const role = (data.get('role') || '').toString();
                if (!user_id) { setBanner('error', 'Pick a user to grant.'); return; }
                if (!role) { setBanner('error', 'Pick a role.'); return; }
                try {
                    const resp = await this.authFetch(`/api/admin/teams/${encodeURIComponent(teamId)}/memberships`, {
                        method: 'POST',
                        headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id, role }),
                    });
                    const body2 = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        const msg = resp.status === 409 ? 'That user already has a membership on this team.' : (body2.detail || 'Could not grant membership.');
                        setBanner('error', msg);
                        return;
                    }
                    this.loadAdminTeamMemberships(teamId, true);
                    if (typeof close === 'function') close({ ok: true });
                } catch (err) {
                    setBanner('error', 'Network error while granting membership.');
                }
            },
            confirmLabel: 'Grant membership',
        });
    },

    async revokeAdminTeamMembership(teamId, membershipId, label) {
        const ok = await this.confirmAction?.({
            title: 'Revoke membership?',
            message: `${label || 'This member'} will lose access to ${this._adminActiveTeamId === teamId ? 'this team' : 'the team'}. The membership can be re-granted later.`,
            confirmLabel: 'Revoke',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(
                `/api/admin/teams/${encodeURIComponent(teamId)}/memberships/${encodeURIComponent(membershipId)}`,
                { method: 'DELETE', headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                this.notifyModal?.({ title: 'Could not revoke', message: detail.detail || 'Unexpected error.' });
                return;
            }
            this.loadAdminTeamMemberships(teamId, true);
        } catch (err) {
            this.notifyModal?.({ title: 'Network error', message: 'Could not revoke membership.' });
        }
    },
};
