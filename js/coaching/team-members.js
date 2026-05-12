// Team admin members + invites mixin (Phase B of UI/UX hardening).
//
// Admin > People: Members list, Pending Invites list, and the "Invite member"
// composer modal. Coach > Settings links here for people administration.
// Backed by /api/team/memberships* and /api/team/invites* introduced by
// platform-hardening Phase 9.3.
//
// Capability gate: a team admin (membership role `team_admin`) or
// global admin can write; coaches/assistant coaches see read-only summaries.

const TEAM_ROLE_LABELS = {
    team_admin: 'Team admin',
    coach: 'Coach',
    assistant_coach: 'Assistant coach',
    player: 'Player',
    guardian: 'Guardian',
};
const TEAM_ROLE_ORDER = ['team_admin', 'coach', 'assistant_coach', 'player', 'guardian'];

export const coachingTeamMembersMixin = {
    _teamMembers: null,
    _teamInvites: null,
    _teamMembersLoadInFlight: false,
    _teamInvitesLoadInFlight: false,
    _teamInviteModalOpen: false,

    activeTeamIdForMembership() {
        // Reuse the scope mixin's activeScope so both lists stay in sync
        // with the nav scope switcher.
        return this.activeScope?.team?.id || null;
    },

    canManageTeamMembers() {
        // Backend enforces team_admin / global_admin; client uses scope cap.
        const caps = new Set(this.activeScope?.capabilities || []);
        return caps.has('membership:manage') || caps.has('global_admin');
    },

    async loadCoachTeamMembers(force = false) {
        const teamId = this.activeTeamIdForMembership();
        const el = document.getElementById('coach-team-members-content');
        if (!el) return;
        if (!teamId) {
            el.innerHTML = '<div class="session-empty">Pick a team from the scope switcher to manage members.</div>';
            return;
        }
        if (!this.canManageTeamMembers()) {
            el.innerHTML = this.teamMembersReadOnlyHtml();
            return;
        }
        if (this._teamMembersLoadInFlight && !force) return;
        this._teamMembersLoadInFlight = true;
        if (force || !this._teamMembers) {
            el.innerHTML = '<div class="session-empty">Loading members…</div>';
        }
        try {
            const resp = await this.authFetch(
                `/api/team/memberships?team_id=${encodeURIComponent(teamId)}`,
                { headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || `members_load_failed:${resp.status}`);
            }
            this._teamMembers = await resp.json();
            el.innerHTML = this.teamMembersListHtml(this._teamMembers);
        } catch (err) {
            el.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load members.')}</div>`;
        } finally {
            this._teamMembersLoadInFlight = false;
        }
    },

    async loadCoachTeamInvites(force = false) {
        const teamId = this.activeTeamIdForMembership();
        const el = document.getElementById('coach-team-invites-content');
        if (!el) return;
        if (!teamId) {
            el.innerHTML = '<div class="session-empty">Pick a team from the scope switcher to see pending invites.</div>';
            return;
        }
        if (!this.canManageTeamMembers()) {
            el.innerHTML = '<div class="session-empty">Only team admins can view pending invites.</div>';
            return;
        }
        if (this._teamInvitesLoadInFlight && !force) return;
        this._teamInvitesLoadInFlight = true;
        if (force || !this._teamInvites) {
            el.innerHTML = '<div class="session-empty">Loading invites…</div>';
        }
        try {
            const resp = await this.authFetch(
                `/api/team/invites?team_id=${encodeURIComponent(teamId)}`,
                { headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || `invites_load_failed:${resp.status}`);
            }
            this._teamInvites = await resp.json();
            this.renderTeamInviteSurfaces();
        } catch (err) {
            el.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load invites.')}</div>`;
        } finally {
            this._teamInvitesLoadInFlight = false;
        }
    },

    teamMembersReadOnlyHtml() {
        return `
            <div class="session-empty">
                <p>Members are managed by a team admin. You can see the active roster on the <a href="#" onclick="event.preventDefault(); app.setCoachTab('roster')">Roster tab</a>.</p>
            </div>
        `;
    },

    teamMembersListHtml(members) {
        if (!members || !members.length) {
            return '<div class="session-empty">No team memberships yet. Invite your first coach above.</div>';
        }
        // Sort by role precedence then username for a stable, scannable list.
        const sorted = [...members].sort((a, b) => {
            const ar = TEAM_ROLE_ORDER.indexOf(a.role); const br = TEAM_ROLE_ORDER.indexOf(b.role);
            if (ar !== br) return ar - br;
            return (a.username || '').localeCompare(b.username || '');
        });
        const rows = sorted.map((m) => this.teamMemberRowHtml(m)).join('');
        return `<ul class="team-member-list" role="list">${rows}</ul>`;
    },

    teamMemberRowHtml(member) {
        const display = member.display_name || member.username || 'Unnamed';
        const initials = this.computeInitials(display);
        const role = TEAM_ROLE_LABELS[member.role] || member.role;
        const username = member.username ? `@${this.esc(member.username)}` : '';
        return `
            <li class="team-member-row" data-membership-id="${this.esc(String(member.id || ''))}" data-role="${this.esc(member.role)}">
                <div class="team-member-avatar" aria-hidden="true">${this.esc(initials)}</div>
                <div class="team-member-text">
                    <div class="team-member-name">${this.esc(display)}</div>
                    <div class="team-member-meta">
                        <span class="team-member-handle">${username}</span>
                        <span class="team-pill" data-role="${this.esc(member.role)}">${this.esc(role)}</span>
                    </div>
                </div>
                <div class="team-member-actions">
                    <button type="button" class="mini-action-btn" data-action="change-role"
                        onclick="app.openCoachTeamMemberRolePopover('${this.esc(String(member.id || ''))}')">Change role</button>
                    <button type="button" class="mini-action-btn mini-action-danger" data-action="revoke"
                        onclick="app.revokeCoachTeamMember('${this.esc(String(member.id || ''))}', '${this.esc(display)}')">Remove</button>
                </div>
            </li>
        `;
    },

    teamInvitesListHtml(invites) {
        if (!invites || !invites.length) {
            return '<div class="session-empty">No pending invites.</div>';
        }
        const rows = invites.map((iv) => this.teamInviteRowHtml(iv)).join('');
        return `<ul class="team-invite-list" role="list">${rows}</ul>`;
    },

    teamInviteRowHtml(invite) {
        const status = (invite.status || 'pending').toLowerCase();
        const email = invite.email || '(no email)';
        const role = TEAM_ROLE_LABELS[invite.role] || invite.role;
        const expires = this.formatInviteExpiry(invite);
        const isPending = status === 'pending';
        const delivery = this.inviteDeliveryLabel(invite);
        const devUrl = invite.invite_token ? `${window.location.origin}/invite/${invite.invite_token}` : '';
        const inviteIdArg = this.jsInlineArg(invite.id || '');
        const emailArg = this.jsInlineArg(email);
        const devUrlArg = this.jsInlineArg(devUrl);
        return `
            <li class="team-invite-row" data-invite-id="${this.esc(String(invite.id || ''))}">
                <div class="team-invite-meta">
                    <div class="team-invite-email">${this.esc(email)}</div>
                    <div class="team-invite-sub">
                        <span class="team-pill" data-role="${this.esc(invite.role)}">${this.esc(role)}</span>
                        <span class="team-pill" data-state="${this.esc(status)}">${this.esc(status)}</span>
                        ${delivery ? `<span class="team-pill" data-state="${this.esc(delivery.state)}">${this.esc(delivery.label)}</span>` : ''}
                        <span class="team-invite-expiry">${this.esc(expires)}</span>
                    </div>
                </div>
                <div class="team-invite-actions">
                    ${isPending ? `<button type="button" class="mini-action-btn" onclick="app.resendCoachTeamInvite(${inviteIdArg}, ${emailArg})">Resend</button>` : ''}
                    ${isPending && devUrl ? `<button type="button" class="mini-action-btn" onclick="app.copyToClipboard?.(${devUrlArg})">Copy link</button>` : ''}
                    ${isPending ? `<button type="button" class="mini-action-btn mini-action-danger" onclick="app.revokeCoachTeamInvite(${inviteIdArg}, ${emailArg})">Revoke</button>` : ''}
                </div>
            </li>
        `;
    },

    jsInlineArg(value) {
        return this.esc(JSON.stringify(String(value ?? '')));
    },

    inviteDeliveryLabel(invite) {
        const status = (invite.last_delivery_status || '').toLowerCase();
        if (!status) return null;
        if (status === 'sent') return { state: 'accepted', label: 'Email sent' };
        if (status === 'disabled') return { state: 'pending', label: 'Email off' };
        if (status === 'not_configured') return { state: 'pending', label: 'Email not configured' };
        if (status === 'failed') return { state: 'revoked', label: 'Send failed' };
        return { state: status, label: status.replace(/_/g, ' ') };
    },

    renderTeamInviteSurfaces() {
        ['coach-team-invites-content', 'admin-people-invites-content'].forEach((id) => {
            const target = document.getElementById(id);
            if (target) target.innerHTML = this.teamInvitesListHtml(this._teamInvites || []);
        });
    },

    renderTeamMemberSurfaces() {
        ['coach-team-members-content', 'admin-people-members-content'].forEach((id) => {
            const target = document.getElementById(id);
            if (target) target.innerHTML = this.teamMembersListHtml(this._teamMembers || []);
        });
    },

    formatInviteExpiry(invite) {
        const status = (invite.status || 'pending').toLowerCase();
        if (status === 'accepted') return `Accepted ${this.formatRelativeDate(invite.accepted_at)}`;
        if (status === 'revoked') return `Revoked ${this.formatRelativeDate(invite.revoked_at)}`;
        if (status === 'expired') return 'Expired';
        // Pending — show expiry countdown.
        if (invite.expires_at) {
            const d = this.parseServerDate(invite.expires_at);
            if (!Number.isNaN(d.getTime())) {
                const now = Date.now();
                const ms = d.getTime() - now;
                if (ms <= 0) return 'Expired';
                const days = Math.floor(ms / 86400000);
                if (days >= 1) return `Expires in ${days} day${days === 1 ? '' : 's'}`;
                const hours = Math.max(1, Math.floor(ms / 3600000));
                return `Expires in ${hours} hour${hours === 1 ? '' : 's'}`;
            }
        }
        return 'Pending';
    },

    formatRelativeDate(iso) {
        if (!iso) return '';
        try {
            const d = this.parseServerDate(iso);
            if (Number.isNaN(d.getTime())) return iso;
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        } catch { return iso; }
    },

    parseServerDate(value) {
        if (typeof value === 'number') return new Date(value * 1000);
        if (typeof value === 'string' && /^\d+(\.\d+)?$/.test(value)) return new Date(Number(value) * 1000);
        return new Date(value);
    },

    computeInitials(name) {
        const cleaned = (name || '').trim();
        if (!cleaned) return '?';
        const parts = cleaned.split(/\s+/);
        if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    },

    async openCoachTeamMemberRolePopover(membershipId) {
        // Lightweight role change via prompt + confirmAction. A richer
        // popover with a segmented control can land in a polish pass.
        const member = (this._teamMembers || []).find((m) => String(m.id) === String(membershipId));
        if (!member) return;
        if (!this.canManageTeamMembers()) return;
        const teamId = this.activeTeamIdForMembership();
        if (!teamId) return;

        // For now: revoke + re-grant under a new role. Saves backend round-trips
        // until a dedicated PATCH endpoint exists. Confirm before destructive.
        const choices = TEAM_ROLE_ORDER.map((r) => ({ value: r, label: TEAM_ROLE_LABELS[r] }))
            .filter((c) => c.value !== member.role);
        const choice = await this.promptChoice?.({
            title: 'Pick a new role',
            message: `New role for ${member.display_name || member.username}`,
            options: choices,
            initialValue: choices[0]?.value || '',
            confirmLabel: 'Save role',
        });
        if (!choice) return;
        try {
            // Revoke current membership.
            const revokeResp = await this.authFetch(
                `/api/team/memberships/${encodeURIComponent(member.id)}?team_id=${encodeURIComponent(teamId)}`,
                { method: 'DELETE', headers: this.getAuthHeaders() },
            );
            if (!revokeResp.ok && revokeResp.status !== 404) {
                const detail = await revokeResp.json().catch(() => ({}));
                throw new Error(detail.detail || 'Could not change role.');
            }
            // Grant under new role.
            const grantResp = await this.authFetch('/api/team/memberships', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ team_id: teamId, user_id: member.user_id, role: choice }),
            });
            if (!grantResp.ok) {
                const detail = await grantResp.json().catch(() => ({}));
                throw new Error(detail.detail || 'Could not grant the new role.');
            }
            this.notifyModal?.({
                title: 'Role updated',
                message: `${member.display_name || member.username} is now ${TEAM_ROLE_LABELS[choice] || choice}.`,
            });
            this.loadCoachTeamMembers(true);
        } catch (err) {
            this.notifyModal?.({ title: 'Could not update role', message: err.message || 'Unexpected error.' });
        }
    },

    async revokeCoachTeamMember(membershipId, label) {
        if (!this.canManageTeamMembers()) return;
        const teamId = this.activeTeamIdForMembership();
        if (!teamId || !membershipId) return;
        const ok = await this.confirmAction?.({
            title: 'Remove member?',
            message: `${label || 'This member'} will lose access to coaching tools for this team. They can be re-added later.`,
            confirmLabel: 'Remove',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(
                `/api/team/memberships/${encodeURIComponent(membershipId)}?team_id=${encodeURIComponent(teamId)}`,
                { method: 'DELETE', headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                if (resp.status === 409) {
                    this.notifyModal?.({ title: 'Cannot remove last admin', message: detail.detail || 'A team must keep at least one team admin.' });
                    return;
                }
                throw new Error(detail.detail || 'Could not remove member.');
            }
            this.loadCoachTeamMembers(true);
        } catch (err) {
            this.notifyModal?.({ title: 'Could not remove member', message: err.message || 'Unexpected error.' });
        }
    },

    async revokeCoachTeamInvite(inviteId, label) {
        if (!this.canManageTeamMembers()) return;
        const teamId = this.activeTeamIdForMembership();
        if (!teamId || !inviteId) return;
        const ok = await this.confirmAction?.({
            title: 'Revoke invite?',
            message: `The invite to ${label || 'this address'} will no longer be redeemable.`,
            confirmLabel: 'Revoke',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(
                `/api/team/invites/${encodeURIComponent(inviteId)}/revoke?team_id=${encodeURIComponent(teamId)}`,
                { method: 'POST', headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || 'Could not revoke invite.');
            }
            this.loadCoachTeamInvites(true);
            if (document.getElementById('admin-people-invites-content')) this.loadAdminPeople(true);
        } catch (err) {
            this.notifyModal?.({ title: 'Could not revoke invite', message: err.message || 'Unexpected error.' });
        }
    },

    async resendCoachTeamInvite(inviteId, label) {
        if (!this.canManageTeamMembers()) return;
        const teamId = this.activeTeamIdForMembership();
        if (!teamId || !inviteId) return;
        try {
            const resp = await this.authFetch(
                `/api/team/invites/${encodeURIComponent(inviteId)}/resend?team_id=${encodeURIComponent(teamId)}`,
                { method: 'POST', headers: this.getAuthHeaders() },
            );
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(body.detail || 'Could not resend invite.');
            this._teamInvites = (this._teamInvites || []).map((iv) => String(iv.id) === String(inviteId) ? body : iv);
            this.renderTeamInviteSurfaces();
            const extra = body.invite_token ? ' Dev mode: the refreshed invite link is available in the row.' : '';
            this.notifyModal?.({ title: 'Invite resent', message: `Invite sent to ${label || body.email || 'the invitee'}.${extra}` });
        } catch (err) {
            this.notifyModal?.({ title: 'Could not resend invite', message: err.message || 'Unexpected error.' });
        }
    },

    async loadAdminPeople(force = false) {
        const note = document.getElementById('admin-people-scope-note');
        const membersEl = document.getElementById('admin-people-members-content');
        const invitesEl = document.getElementById('admin-people-invites-content');
        const teamId = this.activeTeamIdForMembership();
        const teamName = this.activeScope?.team?.name || 'active team';
        if (note) note.textContent = teamId ? `Managing ${teamName}. Use the team switcher in the top bar to change scope.` : 'Pick a team from the scope switcher to manage people.';
        if (!membersEl || !invitesEl) return;
        if (!teamId) {
            membersEl.innerHTML = '<div class="session-empty">Pick a team from the scope switcher to manage members.</div>';
            invitesEl.innerHTML = '<div class="session-empty">Pick a team from the scope switcher to see invites.</div>';
            return;
        }
        if (!this.canManageTeamMembers()) {
            membersEl.innerHTML = this.teamMembersReadOnlyHtml();
            invitesEl.innerHTML = '<div class="session-empty">Only team admins can view pending invites.</div>';
            return;
        }
        membersEl.innerHTML = '<div class="session-empty">Loading members…</div>';
        invitesEl.innerHTML = '<div class="session-empty">Loading invites…</div>';
        try {
            const [membersResp, invitesResp] = await Promise.all([
                this.authFetch(`/api/team/memberships?team_id=${encodeURIComponent(teamId)}`, { headers: this.getAuthHeaders() }),
                this.authFetch(`/api/team/invites?team_id=${encodeURIComponent(teamId)}`, { headers: this.getAuthHeaders() }),
            ]);
            if (!membersResp.ok || !invitesResp.ok) throw new Error('Could not load team people.');
            this._teamMembers = await membersResp.json();
            this._teamInvites = await invitesResp.json();
            this.renderTeamMemberSurfaces();
            this.renderTeamInviteSurfaces();
        } catch (err) {
            membersEl.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load team members.')}</div>`;
            invitesEl.innerHTML = '<div class="session-empty">Invites unavailable.</div>';
        }
    },

    renderAdminPeople() {
        this.loadAdminPeople(true);
    },

    // ---- Invite composer ----

    async openCoachTeamInviteModal() {
        if (!this.canManageTeamMembers()) {
            this.notifyModal?.({ title: 'Permission required', message: 'Only team admins can send invites.' });
            return;
        }
        const teamId = this.activeTeamIdForMembership();
        if (!teamId) {
            this.notifyModal?.({ title: 'No active team', message: 'Select a team from the scope switcher first.' });
            return;
        }
        const template = document.getElementById('coach-team-invite-form-template');
        if (!template) return;
        const body = template.content.cloneNode(true).firstElementChild;
        // Render the modal via the existing formModal primitive so we get
        // accessible close/Esc/backdrop handling for free.
        let mountedRoot = null;
        this.formModal?.({
            title: 'Invite to this team',
            body,
            onMount: async (root) => {
                // The 'root' here is the body element passed in. Some
                // formModal implementations pass the modal card root; either
                // way `root.querySelector(...)` still finds our form fields
                // because the cloned template element is wrapped inside it.
                mountedRoot = root.matches('.coach-team-invite-form') ? root : (root.querySelector('.coach-team-invite-form') || root);
                this._teamInviteRootEl = mountedRoot;
                this._teamInviteModalOpen = true;
                const roleInputs = mountedRoot.querySelectorAll('input[name="role"]');
                const playersGroup = mountedRoot.querySelector('#coach-team-invite-players-group');
                const playersSelect = mountedRoot.querySelector('#coach-team-invite-players');
                await this.populateCoachTeamInvitePlayersOptions(playersSelect);
                const syncRole = () => {
                    const role = mountedRoot.querySelector('input[name="role"]:checked')?.value;
                    const needsPlayer = role === 'player' || role === 'guardian';
                    if (playersGroup) playersGroup.hidden = !needsPlayer;
                };
                roleInputs.forEach((r) => r.addEventListener('change', syncRole));
                syncRole();
            },
            onSubmit: async (close) => {
                // close is provided by openAppModal. A successful submit
                // closes the modal; a failed submit leaves it open with the
                // error banner visible.
                await this.handleCoachTeamInviteSubmit(mountedRoot || body, close);
            },
            confirmLabel: 'Send invite',
        });
    },

    async populateCoachTeamInvitePlayersOptions(selectEl) {
        if (!selectEl) return;
        // Reuse the coach bundle if already loaded; otherwise refresh.
        if (!this._coachBundle) {
            try { await this.loadCoachBundle?.(); } catch { /* ignore */ }
        }
        const players = this._coachBundle?.players || [];
        selectEl.innerHTML = '';
        if (!players.length) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'No players on this team yet';
            opt.disabled = true;
            selectEl.appendChild(opt);
            selectEl.disabled = true;
            return;
        }
        selectEl.disabled = false;
        players.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name || p.id;
            selectEl.appendChild(opt);
        });
    },

    async handleCoachTeamInviteSubmit(root, close) {
        const banner = root.querySelector('#coach-team-invite-banner');
        const dev = root.querySelector('#coach-team-invite-dev-token');
        const devVal = root.querySelector('#coach-team-invite-dev-token-value');
        const submitBtn = root.querySelector('#coach-team-invite-submit-btn');
        const setBanner = (kind, msg) => {
            if (!banner) return;
            banner.dataset.kind = kind;
            banner.textContent = msg;
            banner.hidden = false;
        };
        const hideBanner = () => { if (banner) { banner.hidden = true; delete banner.dataset.kind; } };
        hideBanner();
        const teamId = this.activeTeamIdForMembership();
        if (!teamId) {
            setBanner('error', 'No active team. Pick one from the scope switcher.');
            return;
        }
        const email = (root.querySelector('#coach-team-invite-email')?.value || '').trim();
        const role = (root.querySelector('input[name="role"]:checked')?.value || '').trim();
        if (!email || email.length < 3) { setBanner('error', 'A valid email is required.'); return; }
        if (!role) { setBanner('error', 'Pick a role for the invitee.'); return; }
        const playersSelect = root.querySelector('#coach-team-invite-players');
        const playerIds = playersSelect && !playersSelect.disabled
            ? Array.from(playersSelect.selectedOptions).map((o) => o.value).filter(Boolean)
            : [];

        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Sending…'; }
        try {
            const resp = await this.authFetch('/api/team/invites', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ team_id: teamId, email, role, player_ids: playerIds }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                setBanner('error', body.detail || 'Could not send invite.');
                return;
            }
            // Success. Refresh the pending invites list so the new entry
            // appears, then either close the modal or surface the dev URL
            // and let the user dismiss.
            this.loadCoachTeamInvites(true);
            if (body.invite_token && dev && devVal) {
                const url = `${window.location.origin}/invite/${body.invite_token}`;
                dev.hidden = false;
                devVal.textContent = url;
                setBanner('success', `Invite sent to ${email}. Share the link below in dev mode.`);
                // Reset email + uncheck player selections; keep modal open so
                // the operator can grab the dev URL.
                const emailInput = root.querySelector('#coach-team-invite-email');
                if (emailInput) emailInput.value = '';
                if (playersSelect && !playersSelect.disabled) {
                    Array.from(playersSelect.options).forEach((o) => { o.selected = false; });
                }
            } else {
                // Production-like response: close on success.
                if (typeof close === 'function') close({ ok: true, email });
            }
        } catch (err) {
            setBanner('error', 'Network error while sending invite.');
        } finally {
            if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Send invite'; }
        }
    },

    // ---- Invite acceptance landing (Phase B.3) ----

    async handleInviteAcceptLandingMount() {
        // Called when the SPA activates /invite/{token}. The route handler
        // already activated the view; we just hydrate the card from the
        // token in the URL.
        const path = window.location.pathname;
        const m = path.match(/^\/invite\/(.+)$/);
        const token = m && m[1] ? decodeURIComponent(m[1]) : '';
        const el = document.getElementById('invite-shell-sub');
        if (!token) {
            if (el) el.textContent = 'No invite token found in the URL.';
            return;
        }
        // For Phase B.3 v1 we don't preview the invite (no token-lookup
        // endpoint that doesn't accept the invite). We render a generic
        // accept-or-create form. The backend rejects with a clear message
        // if the token is invalid/expired.
        this.renderInviteAcceptCard(token);
    },

    renderInviteAcceptCard(token) {
        const body = document.querySelector('#invite-view .onboarding-shell-body');
        if (!body) return;
        if (this.authToken) {
            body.innerHTML = `
                <div class="account-placeholder invite-accept">
                    <div class="account-placeholder-glyph" aria-hidden="true">✉</div>
                    <h2>Accept this invite</h2>
                    <p>You&rsquo;re signed in as <strong>${this.esc(this.userName || 'unknown')}</strong>. Accepting will link this team to your account.</p>
                    <div id="invite-accept-banner" class="account-banner" hidden></div>
                    <div class="account-form-actions">
                        <button type="button" class="btn-primary" onclick="app.acceptInvite('${this.esc(token)}')">Accept invite</button>
                        <button type="button" class="btn-secondary" onclick="app.logout()">Sign in as someone else</button>
                    </div>
                </div>
            `;
        } else {
            body.innerHTML = `
                <div class="invite-accept-shell">
                    <p>You can accept this invite by creating a new account or by signing in if you already have one.</p>
                    <form id="invite-accept-form" class="account-form" onsubmit="app.handleInviteAcceptSubmit(event, '${this.esc(token)}')" novalidate>
                        <div class="form-group">
                            <label for="invite-accept-username">Choose a username</label>
                            <input type="text" id="invite-accept-username" name="username" required minlength="1" maxlength="100" autocomplete="username">
                        </div>
                        <div class="form-group">
                            <label for="invite-accept-display-name">Display name</label>
                            <input type="text" id="invite-accept-display-name" name="display_name" maxlength="200" autocomplete="name">
                        </div>
                        <div class="form-group">
                            <label for="invite-accept-password">Choose a password</label>
                            <input type="password" id="invite-accept-password" name="password" required minlength="8" maxlength="200" autocomplete="new-password">
                            <p class="form-help">At least 8 characters.</p>
                        </div>
                        <div id="invite-accept-banner" class="account-banner" hidden></div>
                        <div class="account-form-actions">
                            <button type="submit" class="btn-primary">Create account &amp; accept</button>
                            <button type="button" class="btn-secondary" onclick="app.showLoginModal()">Sign in instead</button>
                        </div>
                    </form>
                </div>
            `;
        }
    },

    async acceptInvite(token) {
        const banner = document.getElementById('invite-accept-banner');
        const setBanner = (kind, msg) => {
            if (!banner) return;
            banner.dataset.kind = kind;
            banner.textContent = msg;
            banner.hidden = false;
        };
        try {
            const resp = await this.authFetch('/api/team/invites/accept', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ token }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                setBanner('error', body.detail || 'That invite is invalid or expired.');
                return;
            }
            setBanner('success', 'Invite accepted. Taking you to your team…');
            await this.loadMeScope?.();
            setTimeout(() => {
                this.routeAfterInviteAcceptance(body.membership?.role);
            }, 800);
        } catch (err) {
            setBanner('error', 'Network error. Try again in a moment.');
        }
    },

    async handleInviteAcceptSubmit(event, token) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const username = (data.get('username') || '').toString().trim();
        const display_name = (data.get('display_name') || '').toString().trim();
        const password = (data.get('password') || '').toString();
        const banner = document.getElementById('invite-accept-banner');
        const setBanner = (kind, msg) => {
            if (!banner) return;
            banner.dataset.kind = kind;
            banner.textContent = msg;
            banner.hidden = false;
        };
        if (!username || password.length < 8) {
            setBanner('error', 'Pick a username and password (at least 8 characters).');
            return;
        }
        try {
            const resp = await fetch('/api/team/invites/accept', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token, username, password, display_name: display_name || undefined }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                setBanner('error', body.detail || 'Could not accept the invite.');
                return;
            }
            setBanner('success', 'Account created. Signing you in…');
            try {
                await this.loginWith(username, password);
            } catch {
                setBanner('error', 'Account created, but automatic sign-in failed. Please sign in with your new account.');
                this.showLoginModal?.();
                return;
            }
            setTimeout(() => {
                this.routeAfterInviteAcceptance(body.membership?.role);
            }, 800);
        } catch (err) {
            setBanner('error', 'Network error while creating your account.');
        }
    },

    routeAfterInviteAcceptance(role) {
        const normalized = (role || '').toLowerCase();
        if (normalized === 'guardian' || normalized === 'player') {
            this.showFeedbackView?.({ replaceHistory: true });
            return;
        }
        if (normalized === 'team_admin' && this.canAccessAdminConsole?.()) {
            this.showAdminView?.('people', { replaceHistory: true });
            return;
        }
        if (this.canCoach?.()) {
            this.showCoachView?.({ replaceHistory: true });
            return;
        }
        if (this.canAccessAdminConsole?.()) {
            this.showAdminView?.(undefined, { replaceHistory: true });
            return;
        }
        this.showSeasonView?.({ replaceHistory: true });
    },
};
