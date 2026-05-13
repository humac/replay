// Admin > Users 360 drawer + CRUD modals.
//
// Powers the single People pivot: a global admin clicks an Admin > Users
// row body and sees the user's profile, every team membership across the
// platform, and every linked player they're connected to — without
// bouncing between /admin/users, /admin/teams (memberships tab), and
// Coach > Roster. Reuses existing /api/users CRUD; the only new endpoint
// is GET /api/users/{id} which returns memberships + linked_players in
// one shot (routers/admin.py).

export const adminUserDetailMixin = {
    /** Open the per-user 360 drawer (read view + inline actions). */
    async openAdminUserDetail(userId) {
        const body = document.createElement('div');
        body.className = 'admin-user-detail';
        body.innerHTML = '<div class="session-empty">Loading user…</div>';
        let detail = null;
        const refresh = async () => {
            try {
                detail = await this.getUserDetail(userId);
            } catch (err) {
                body.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load user.')}</div>`;
                return;
            }
            body.innerHTML = this._renderAdminUserDetail(detail);
        };
        await refresh();
        await this.formModal({
            title: 'User details',
            body,
            confirmLabel: 'Close',
            cancelLabel: 'Done',
            size: 'wide',
            onSubmit: (close) => close({ ok: true }),
        });
    },

    _renderAdminUserDetail(detail) {
        const u = detail.user || {};
        const memberships = detail.memberships || [];
        const linked = detail.linked_players || [];
        const globalAdminPill = String(u.role || '').split(',').map((p) => p.trim()).includes('admin')
            ? '<span class="badge ready">Global admin</span>' : '';
        const enabledPill = u.enabled
            ? '<span class="badge ready">Active</span>'
            : '<span class="badge error">Disabled</span>';
        const rolePill = `<span class="badge">${this.esc(String(u.role || 'viewer').replace(',', ' + '))}</span>`;

        const profile = `
            <section class="admin-user-section">
                <header class="admin-user-section-head">
                    <h3>Profile</h3>
                    <button type="button" class="btn-head" onclick="app.openAdminUserEdit('${this.esc(u.id)}')">Edit profile</button>
                </header>
                <dl class="admin-user-profile">
                    <dt>Display name</dt><dd>${this.esc(u.display_name || '—')}</dd>
                    <dt>Username</dt><dd>@${this.esc(u.username)}</dd>
                    <dt>Roles</dt><dd>${rolePill} ${globalAdminPill}</dd>
                    <dt>Status</dt><dd>${enabledPill}</dd>
                    <dt>Created</dt><dd>${this.esc(u.created_at || '—')}</dd>
                    <dt>Last active team</dt><dd>${this.esc(u.last_team_id || '—')}</dd>
                </dl>
            </section>`;

        const membershipRows = memberships.length
            ? memberships.map((m) => `
                <li class="admin-user-membership-row">
                    <span class="admin-user-membership-team">
                        <strong>${this.esc(m.team_name || m.team_id)}</strong>
                        <span class="admin-card-sub">/${this.esc(m.team_slug || '')}</span>
                    </span>
                    <span class="team-pill" data-role="${this.esc(m.role)}">${this.esc((m.role || '').replace(/_/g, ' '))}</span>
                </li>
            `).join('')
            : '<li class="session-empty">No team memberships. Grant one in Admin &gt; Teams.</li>';
        const membershipsSection = `
            <section class="admin-user-section">
                <header class="admin-user-section-head">
                    <h3>Team memberships <span class="admin-card-sub">(${memberships.length})</span></h3>
                    <a class="btn-head" href="/admin/teams">Manage in Admin &gt; Teams</a>
                </header>
                <ul class="admin-user-membership-list" role="list">${membershipRows}</ul>
            </section>`;

        const linkedRows = linked.length
            ? linked.map((l) => {
                const jersey = l.jersey_number ? `<span class="admin-user-link-jersey">#${this.esc(l.jersey_number)}</span>` : '';
                return `
                    <li class="admin-user-link-row">
                        <span class="admin-user-link-player">
                            ${jersey}
                            <strong>${this.esc(l.player_name)}</strong>
                        </span>
                        <span class="admin-user-link-team admin-card-sub">${this.esc(l.team_name || l.team_id || '')}</span>
                        ${this.relationshipPillHtml(l.relationship)}
                    </li>`;
            }).join('')
            : '<li class="session-empty">No linked players. Link this user from Coach &gt; Roster.</li>';
        const linkedSection = `
            <section class="admin-user-section">
                <header class="admin-user-section-head">
                    <h3>Linked players <span class="admin-card-sub">(${linked.length})</span></h3>
                </header>
                <ul class="admin-user-link-list" role="list">${linkedRows}</ul>
            </section>`;

        return profile + membershipsSection + linkedSection;
    },

    /** Modal — create a new user (replaces the inline Settings form). */
    async openAdminUserCreate() {
        const body = document.createElement('form');
        body.className = 'account-form admin-user-form';
        body.noValidate = true;
        body.innerHTML = `
            <div class="form-group">
                <label for="adm-uc-username">Username</label>
                <input type="text" id="adm-uc-username" name="username" required maxlength="50" autocomplete="off">
                <p class="form-help">Letters, digits, underscore, dot, or hyphen. 2–50 characters.</p>
            </div>
            <div class="form-group">
                <label for="adm-uc-display">Display name</label>
                <input type="text" id="adm-uc-display" name="display_name" maxlength="100" autocomplete="off">
            </div>
            <div class="form-group">
                <label for="adm-uc-password">Password</label>
                <input type="password" id="adm-uc-password" name="password" required minlength="8" maxlength="200" autocomplete="new-password">
                <p class="form-help">At least 8 characters.</p>
            </div>
            <fieldset class="form-group admin-user-role-fieldset">
                <legend>Platform roles</legend>
                <p class="form-help">Team-scoped access is granted separately via team memberships.</p>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="admin"> <span>Global admin</span></label>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="uploader"> <span>Uploader</span></label>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="viewer" checked> <span>Viewer</span></label>
            </fieldset>
            <div id="adm-uc-banner" class="account-banner" hidden></div>
        `;
        let root = body;
        await this.formModal({
            title: 'Create user',
            body,
            confirmLabel: 'Create user',
            onMount: (modalRoot) => { root = modalRoot.querySelector('form') || body; },
            onSubmit: async (close) => {
                const banner = root.querySelector('#adm-uc-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const username = (root.querySelector('#adm-uc-username').value || '').trim();
                const display_name = (root.querySelector('#adm-uc-display').value || '').trim();
                const password = root.querySelector('#adm-uc-password').value || '';
                const roles = Array.from(root.querySelectorAll('input[name="role"]:checked')).map((el) => el.value);
                if (!username) { setBanner('error', 'Username is required.'); return; }
                if (password.length < 8) { setBanner('error', 'Password must be at least 8 characters.'); return; }
                const role = roles.length ? roles.join(',') : 'viewer';
                try {
                    await this.createUser({ username, password, role, display_name });
                    await this.renderUsersList();
                    if (typeof close === 'function') close({ ok: true });
                } catch (err) {
                    setBanner('error', err.message || 'Could not create user.');
                }
            },
        });
    },

    /** Modal — edit an existing user (display name, roles, enabled, optional password reset). */
    async openAdminUserEdit(userId) {
        let detail;
        try { detail = await this.getUserDetail(userId); }
        catch (err) { this.showError(err.message); return; }
        const u = detail.user || {};
        const roles = String(u.role || '').split(',').map((p) => p.trim()).filter(Boolean);
        const body = document.createElement('form');
        body.className = 'account-form admin-user-form';
        body.noValidate = true;
        body.innerHTML = `
            <div class="form-group">
                <label>Username</label>
                <input type="text" value="${this.esc(u.username)}" disabled>
                <p class="form-help">Username is the identity key — it can't be changed.</p>
            </div>
            <div class="form-group">
                <label for="adm-ue-display">Display name</label>
                <input type="text" id="adm-ue-display" name="display_name" maxlength="100" value="${this.esc(u.display_name || '')}">
            </div>
            <fieldset class="form-group admin-user-role-fieldset">
                <legend>Platform roles</legend>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="admin" ${roles.includes('admin') ? 'checked' : ''}> <span>Global admin</span></label>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="uploader" ${roles.includes('uploader') ? 'checked' : ''}> <span>Uploader</span></label>
                <label class="admin-user-role-option"><input type="checkbox" name="role" value="viewer" ${roles.includes('viewer') ? 'checked' : ''}> <span>Viewer</span></label>
            </fieldset>
            <div class="form-group">
                <label class="admin-user-toggle">
                    <input type="checkbox" id="adm-ue-enabled" ${u.enabled ? 'checked' : ''}>
                    <span>Account active</span>
                </label>
            </div>
            <div class="form-group">
                <label for="adm-ue-password">Reset password (optional)</label>
                <input type="password" id="adm-ue-password" autocomplete="new-password" minlength="8" maxlength="200" placeholder="Leave blank to keep current password">
                <p class="form-help">If filled, sets a new password and signs the user out of other sessions next time.</p>
            </div>
            <div id="adm-ue-banner" class="account-banner" hidden></div>
        `;
        let root = body;
        await this.formModal({
            title: `Edit ${u.username}`,
            body,
            confirmLabel: 'Save changes',
            onMount: (modalRoot) => { root = modalRoot.querySelector('form') || body; },
            onSubmit: async (close) => {
                const banner = root.querySelector('#adm-ue-banner');
                const setBanner = (kind, msg) => {
                    if (!banner) return;
                    banner.dataset.kind = kind;
                    banner.textContent = msg;
                    banner.hidden = false;
                };
                const display_name = (root.querySelector('#adm-ue-display').value || '').trim();
                const newRoles = Array.from(root.querySelectorAll('input[name="role"]:checked')).map((el) => el.value);
                const enabled = !!root.querySelector('#adm-ue-enabled').checked;
                const password = (root.querySelector('#adm-ue-password').value || '').trim();
                if (!newRoles.length) { setBanner('error', 'Pick at least one platform role.'); return; }
                if (password && password.length < 8) { setBanner('error', 'Password must be at least 8 characters.'); return; }
                const patch = { display_name, role: newRoles.join(','), enabled };
                if (password) patch.password = password;
                try {
                    await this.updateUser(u.id, patch);
                    await this.renderUsersList();
                    if (typeof close === 'function') close({ ok: true });
                } catch (err) {
                    const msg = String(err.message || '');
                    if (msg === 'last_admin') {
                        setBanner('error', 'This is the only enabled global admin. Promote another user before demoting or disabling this account.');
                    } else {
                        setBanner('error', msg || 'Could not save changes.');
                    }
                }
            },
        });
    },

    /** Delete user — surfaces last_admin guard from the backend. */
    async handleAdminUserDelete(userId, username) {
        const ok = await this.confirmAction({
            title: 'Delete user',
            message: `Delete user "${username}"? This cannot be undone. Their team memberships and player links will also be removed.`,
            confirmLabel: 'Delete user',
            danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteUser(userId);
            this.showSuccess(`User "${username}" deleted.`);
            await this.renderUsersList();
        } catch (err) {
            const msg = String(err.message || '');
            if (msg === 'last_admin') {
                this.notifyModal?.({
                    title: 'Cannot delete the last admin',
                    message: 'This is the only enabled global admin account. Promote another user to global admin before deleting this one.',
                });
            } else {
                this.showError(msg || 'Could not delete user.');
            }
        }
    },
};
