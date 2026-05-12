// Onboarding wizard mixin (Phase D of UI/UX hardening).
//
// Owns the `/welcome` shell — a three-step guided setup for new global
// admins on a freshly-installed tenant. Uses the existing
// /api/admin/teams* endpoints; never persists raw passwords or tokens.
//
// Auto-fires when a freshly-signed-in global admin has zero teams; the
// check + redirect lives in `script.js` after auth-bootstrapping. The
// route itself works for anyone who navigates to /welcome, but skipping
// the wizard is always available.

const WELCOME_STEPS = ['team', 'season', 'invite', 'done'];

export const onboardingMixin = {
    _welcomeStep: 'team',
    _welcomeTeam: null,        // {id, name, slug}
    _welcomeSeason: null,      // {id, name}
    _welcomeInvitesSent: [],   // [{email, role, invite_url?}, …]

    showWelcomeView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        if (!this.authToken) {
            this.showLoginModal?.();
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.activateView('welcome-view');
        this.setWelcomeStep(this._welcomeStep || 'team');
        if (pushHistory) {
            this.pushHistoryState({ view: 'welcome' }, { replace: replaceHistory, url: '/welcome' });
        }
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    setWelcomeStep(step) {
        if (!WELCOME_STEPS.includes(step)) return;
        this._welcomeStep = step;
        document.querySelectorAll('.welcome-step').forEach((el) => {
            const target = el.dataset.welcomeStep;
            const targetIndex = WELCOME_STEPS.indexOf(target);
            const currentIndex = WELCOME_STEPS.indexOf(step);
            el.classList.toggle('is-current', target === step);
            el.classList.toggle('is-done', targetIndex < currentIndex && currentIndex < WELCOME_STEPS.length - 1);
            if (target === step) el.setAttribute('aria-current', 'step');
            else el.removeAttribute('aria-current');
        });
        document.querySelectorAll('.welcome-step-panel').forEach((el) => {
            el.hidden = el.dataset.welcomePanel !== step;
        });
        // Focus the first input of the now-active panel for keyboard users.
        const panel = document.querySelector(`[data-welcome-panel="${step}"]`);
        const focusable = panel?.querySelector('input, select, button');
        focusable?.focus({ preventScroll: true });
    },

    // Should the welcome wizard auto-fire? Caller passes the /api/me payload
    // so we can check `is_global_admin` + zero-teams. Returns true if so.
    shouldRedirectToWelcome(me) {
        if (!me) return false;
        if (!me.is_global_admin) return false;
        const teams = (me.teams || []);
        if (teams.length > 0) return false;
        // Don't redirect if user already explicitly skipped the wizard.
        try {
            if (localStorage.getItem('replay_welcome_skipped') === '1') return false;
        } catch { /* ignore */ }
        return true;
    },

    skipWelcomeFlow() {
        try { localStorage.setItem('replay_welcome_skipped', '1'); } catch { /* ignore */ }
        // Skipping always lands on admin teams (the operator can finish setup
        // manually there). Welcome state is preserved in memory in case they
        // come back via /welcome.
        if (this.isAdmin?.()) {
            this.showAdminView('teams');
        } else {
            this.showSeasonView();
        }
    },

    skipWelcomeStep(step) {
        // Move forward without persisting this step's input.
        if (step === 'season') this.setWelcomeStep('invite');
        else if (step === 'invite') this.finishWelcomeFlow();
    },

    finishWelcomeFlow() {
        try { localStorage.setItem('replay_welcome_skipped', '1'); } catch { /* ignore */ }
        this.setWelcomeStep('done');
        // Customize the done copy with what they actually built.
        const titleEl = document.getElementById('welcome-done-title');
        const subEl = document.getElementById('welcome-done-sub');
        if (titleEl && this._welcomeTeam?.name) {
            titleEl.textContent = `${this._welcomeTeam.name} is ready`;
        }
        if (subEl) {
            const seasonBit = this._welcomeSeason ? ` Your "${this._welcomeSeason.name}" season is set up too.` : '';
            const inviteBit = this._welcomeInvitesSent.length
                ? ` ${this._welcomeInvitesSent.length} invite${this._welcomeInvitesSent.length === 1 ? '' : 's'} on the way.`
                : '';
            subEl.textContent = `Open the admin console to manage teams and seasons, or jump straight into coach tools.${seasonBit}${inviteBit}`;
        }
    },

    // ---- Step 1: create team ----

    async handleWelcomeTeamSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const name = (data.get('name') || '').toString().trim();
        const slug = (data.get('slug') || '').toString().trim();
        const game_format = (data.get('game_format') || 'full').toString();
        this.hideSimpleBanner?.('welcome-team-banner');
        if (!name) { this.showSimpleBanner?.('welcome-team-banner', 'error', 'Team name is required.'); return; }
        if (!slug) { this.showSimpleBanner?.('welcome-team-banner', 'error', 'Slug is required.'); return; }
        try {
            const resp = await this.authFetch('/api/admin/teams', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, slug, game_format }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const msg = resp.status === 409 ? 'A team with that slug already exists. Pick another slug.' : (body.detail || 'Could not create team.');
                this.showSimpleBanner?.('welcome-team-banner', 'error', msg);
                return;
            }
            this._welcomeTeam = { id: body.id, name: body.name, slug: body.slug };
            this.setWelcomeStep('season');
        } catch (err) {
            this.showSimpleBanner?.('welcome-team-banner', 'error', 'Network error while creating team.');
        }
    },

    // ---- Step 2: create season ----

    async handleWelcomeSeasonSubmit(event) {
        event.preventDefault();
        if (!this._welcomeTeam?.id) {
            this.showSimpleBanner?.('welcome-season-banner', 'error', 'Create a team first.');
            this.setWelcomeStep('team');
            return;
        }
        const form = event.currentTarget;
        const data = new FormData(form);
        const name = (data.get('name') || '').toString().trim();
        const starts_on = (data.get('starts_on') || '').toString();
        const ends_on = (data.get('ends_on') || '').toString();
        this.hideSimpleBanner?.('welcome-season-banner');
        if (!name) { this.showSimpleBanner?.('welcome-season-banner', 'error', 'Season name is required.'); return; }
        if (starts_on && ends_on && starts_on > ends_on) {
            this.showSimpleBanner?.('welcome-season-banner', 'error', 'End date must be on or after the start date.');
            return;
        }
        try {
            const resp = await this.authFetch(
                `/api/admin/teams/${encodeURIComponent(this._welcomeTeam.id)}/seasons`,
                {
                    method: 'POST',
                    headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, starts_on, ends_on }),
                },
            );
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                this.showSimpleBanner?.('welcome-season-banner', 'error', body.detail || 'Could not create season.');
                return;
            }
            this._welcomeSeason = { id: body.id, name: body.name };
            this.setWelcomeStep('invite');
        } catch (err) {
            this.showSimpleBanner?.('welcome-season-banner', 'error', 'Network error while creating season.');
        }
    },

    // ---- Step 3: invite coaches ----

    async handleWelcomeInviteSubmit(event) {
        event.preventDefault();
        if (!this._welcomeTeam?.id) {
            this.showSimpleBanner?.('welcome-invite-banner', 'error', 'Create a team first.');
            this.setWelcomeStep('team');
            return;
        }
        const form = event.currentTarget;
        const data = new FormData(form);
        const email = (data.get('email') || '').toString().trim();
        const role = (data.get('role') || '').toString();
        this.hideSimpleBanner?.('welcome-invite-banner');
        if (!email || email.length < 3) {
            this.showSimpleBanner?.('welcome-invite-banner', 'error', 'A valid email is required.');
            return;
        }
        try {
            const resp = await this.authFetch('/api/team/invites', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    team_id: this._welcomeTeam.id,
                    email,
                    role,
                    player_ids: [],
                }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                this.showSimpleBanner?.('welcome-invite-banner', 'error', body.detail || 'Could not send invite.');
                return;
            }
            const invite_url = body.invite_token ? `${window.location.origin}/invite/${body.invite_token}` : null;
            this._welcomeInvitesSent.push({ email, role, invite_url });
            this.renderWelcomeInvitesSent();
            this.showSimpleBanner?.('welcome-invite-banner', 'success', `Invite queued for ${email}. Add another or finish setup.`);
            // Reset just the email so the operator can chain invites; keep role selection sticky.
            const emailEl = document.getElementById('welcome-invite-email');
            if (emailEl) emailEl.value = '';
            emailEl?.focus({ preventScroll: true });
        } catch (err) {
            this.showSimpleBanner?.('welcome-invite-banner', 'error', 'Network error while sending invite.');
        }
    },

    renderWelcomeInvitesSent() {
        const el = document.getElementById('welcome-invites-sent');
        if (!el) return;
        if (!this._welcomeInvitesSent.length) {
            el.innerHTML = '';
            return;
        }
        const rows = this._welcomeInvitesSent.map((inv) => `
            <li class="welcome-invite-row">
                <span class="welcome-invite-email">${this.esc(inv.email)}</span>
                <span class="team-pill" data-role="${this.esc(inv.role)}">${this.esc(inv.role.replace(/_/g, ' '))}</span>
                ${inv.invite_url ? `<button type="button" class="login-link" onclick="app.copyToClipboard?.('${this.esc(inv.invite_url)}')">Copy link</button>` : ''}
            </li>
        `).join('');
        el.innerHTML = `<ul class="welcome-invite-list" role="list">${rows}</ul>`;
    },

    copyToClipboard(text) {
        try {
            navigator.clipboard?.writeText?.(text);
        } catch { /* ignore */ }
    },

    // ---- Auto-redirect hook called by script.js after auth bootstrap ----

    async maybeRedirectToWelcome() {
        if (!this.authToken) return false;
        if (!this.isAdmin?.()) return false;
        try {
            const resp = await this.authFetch('/api/me', { headers: this.getAuthHeaders() });
            if (!resp.ok) return false;
            const me = await resp.json();
            if (!this.shouldRedirectToWelcome(me)) return false;
            this.showWelcomeView({ pushHistory: true, replaceHistory: true, scrollTop: false });
            return true;
        } catch {
            return false;
        }
    },
};
