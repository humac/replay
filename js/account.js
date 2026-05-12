// Account self-service mixin (Phase A of UI/UX hardening).
//
// Owns the `/me` shell: Profile · Password · Email · Sessions sub-tabs.
// Backed by the existing /api/me (GET) + /api/me/profile (PATCH) + /api/me/password
// (POST) + /api/me/email-verification/{request,confirm} endpoints introduced
// by platform-hardening Phase 9.1 / 9.2.

const VALID_ACCOUNT_TABS = ['profile', 'password', 'email', 'sessions'];

const COMMON_TIMEZONES = [
    'UTC',
    'America/Los_Angeles', 'America/Denver', 'America/Chicago',
    'America/New_York', 'America/Toronto', 'America/Sao_Paulo',
    'Europe/London', 'Europe/Madrid', 'Europe/Paris', 'Europe/Berlin',
    'Europe/Athens', 'Africa/Cairo', 'Africa/Johannesburg',
    'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Tokyo',
    'Australia/Sydney', 'Pacific/Auckland',
];

export const accountMixin = {
    _accountTab: 'profile',
    _accountProfile: null,
    _accountSaveInFlight: false,

    showAccountView({ pushHistory = true, replaceHistory = false, scrollTop = true, tab = null } = {}) {
        if (!this.authToken) {
            this.showLoginModal?.();
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.activateView('account-view');
        this.populateAccountTimezoneOptions();
        const target = VALID_ACCOUNT_TABS.includes(tab) ? tab : this._accountTab || 'profile';
        this.setAccountTab(target, { silent: true });
        this.loadAccountProfile();
        if (pushHistory) {
            this.pushHistoryState({ view: 'account', tab: target }, { replace: replaceHistory, url: '/me' });
        }
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    setAccountTab(tab, { silent = false } = {}) {
        if (!VALID_ACCOUNT_TABS.includes(tab)) return;
        this._accountTab = tab;
        document.querySelectorAll('.account-tab').forEach((el) => {
            const isActive = el.dataset.accountTab === tab;
            el.classList.toggle('is-active', isActive);
            el.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        document.querySelectorAll('.account-tab-panel').forEach((el) => {
            const isActive = el.dataset.accountPanel === tab;
            el.hidden = !isActive;
        });
        // Refocus first focusable element in the newly active panel for keyboard
        // users. Skipped on the initial silent load to avoid jumping the page.
        if (!silent) {
            const panel = document.querySelector(`[data-account-panel="${tab}"]`);
            const focusable = panel?.querySelector('input, select, button, textarea');
            focusable?.focus({ preventScroll: true });
        }
    },

    populateAccountTimezoneOptions() {
        const sel = document.getElementById('account-profile-timezone');
        if (!sel || sel.options.length > 1) return;
        let browserTz = '';
        try { browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { /* ignore */ }
        const set = new Set(COMMON_TIMEZONES);
        if (browserTz) set.add(browserTz);
        const tz = Array.from(set).sort();
        tz.forEach((zone) => {
            const opt = document.createElement('option');
            opt.value = zone;
            opt.textContent = zone;
            sel.appendChild(opt);
        });
    },

    async loadAccountProfile() {
        this.clearAccountBanner('profile');
        try {
            const resp = await this.authFetch('/api/me', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error(`me_load_failed:${resp.status}`);
            const me = await resp.json();
            this._accountProfile = me.profile || {};
            this.applyAccountProfileToForm(this._accountProfile);
            this.applyAccountEmailState(this._accountProfile);
        } catch (err) {
            this.showAccountBanner('profile', 'error', 'Could not load your profile. Try again in a moment.');
        }
    },

    applyAccountProfileToForm(profile) {
        const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
        setVal('account-profile-first-name', profile.first_name);
        setVal('account-profile-last-name', profile.last_name);
        setVal('account-profile-email', profile.email);
        setVal('account-profile-phone', profile.phone);

        const tz = document.getElementById('account-profile-timezone');
        if (tz) {
            const target = profile.timezone || '';
            const exists = Array.from(tz.options).some((o) => o.value === target);
            if (!exists && target) {
                const opt = document.createElement('option');
                opt.value = target;
                opt.textContent = target;
                tz.appendChild(opt);
            }
            tz.value = target;
        }
        const locale = document.getElementById('account-profile-locale');
        if (locale) {
            const target = profile.locale || '';
            const exists = Array.from(locale.options).some((o) => o.value === target);
            if (!exists && target) {
                const opt = document.createElement('option');
                opt.value = target;
                opt.textContent = target;
                locale.appendChild(opt);
            }
            locale.value = target;
        }
        const contact = profile.preferred_contact_method || 'none';
        document.querySelectorAll('input[name="preferred_contact_method"]').forEach((r) => {
            r.checked = r.value === contact;
        });
    },

    applyAccountEmailState(profile) {
        const pill = document.getElementById('account-profile-email-pill');
        const emailCurrent = document.getElementById('account-email-current');
        const emailStatus = document.getElementById('account-email-status');
        const verifyBtn = document.getElementById('account-email-verify-btn');
        const verified = !!profile.email_verified_at;
        const email = profile.email || '';

        if (pill) {
            if (!email) {
                pill.hidden = true;
            } else if (verified) {
                pill.hidden = false;
                pill.textContent = 'Verified';
                pill.dataset.state = 'verified';
            } else {
                pill.hidden = false;
                pill.textContent = 'Unverified';
                pill.dataset.state = 'unverified';
            }
        }
        if (emailCurrent) emailCurrent.textContent = email || 'No email on file';
        if (emailStatus) {
            if (!email) {
                emailStatus.textContent = 'Add an email on the Profile tab to enable verification.';
            } else if (verified) {
                emailStatus.textContent = `Verified on ${this.formatDateOnly(profile.email_verified_at)}.`;
            } else {
                emailStatus.textContent = 'Email is on file but not yet verified. Send a verification email to confirm ownership.';
            }
        }
        if (verifyBtn) verifyBtn.disabled = !email || verified;
    },

    formatDateOnly(iso) {
        if (!iso) return 'unknown date';
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return iso;
            return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        } catch { return iso; }
    },

    async handleAccountProfileSubmit(event) {
        event.preventDefault();
        if (this._accountSaveInFlight) return;
        const form = event.currentTarget;
        const data = new FormData(form);
        const payload = {};
        ['first_name', 'last_name', 'email', 'phone', 'timezone', 'locale'].forEach((k) => {
            const v = (data.get(k) || '').toString().trim();
            payload[k] = v || null;
        });
        const contact = (data.get('preferred_contact_method') || 'none').toString();
        payload.preferred_contact_method = contact;

        const saveBtn = document.getElementById('account-profile-save');
        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
        this._accountSaveInFlight = true;
        this.clearAccountBanner('profile');
        try {
            const resp = await this.authFetch('/api/me/profile', {
                method: 'PATCH',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const message = resp.status === 409
                    ? 'That email is already in use by another account.'
                    : (body.detail || 'Could not save your profile.');
                this.showAccountBanner('profile', 'error', message);
                return;
            }
            this._accountProfile = body.profile || this._accountProfile;
            this.applyAccountProfileToForm(this._accountProfile);
            this.applyAccountEmailState(this._accountProfile);
            this.showAccountBanner('profile', 'success', 'Profile saved.');
        } catch (err) {
            this.showAccountBanner('profile', 'error', 'Network error while saving your profile.');
        } finally {
            this._accountSaveInFlight = false;
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save profile'; }
        }
    },

    async handleAccountPasswordSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const current = (data.get('current_password') || '').toString();
        const next = (data.get('new_password') || '').toString();
        const confirm = (data.get('confirm_password') || '').toString();
        this.clearAccountBanner('password');
        if (next.length < 8) {
            this.showAccountBanner('password', 'error', 'New password must be at least 8 characters.');
            return;
        }
        if (next !== confirm) {
            this.showAccountBanner('password', 'error', 'The two new-password fields do not match.');
            return;
        }
        try {
            const resp = await this.authFetch('/api/me/password', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password: current, new_password: next }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const message = resp.status === 400
                    ? 'Current password is incorrect.'
                    : (body.detail || 'Could not change your password.');
                this.showAccountBanner('password', 'error', message);
                return;
            }
            form.reset();
            this.showAccountBanner('password', 'success', 'Password updated. Other sessions have been signed out.');
        } catch (err) {
            this.showAccountBanner('password', 'error', 'Network error while changing your password.');
        }
    },

    async requestAccountEmailVerification() {
        const btn = document.getElementById('account-email-verify-btn');
        this.clearAccountBanner('email');
        if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
        try {
            const resp = await this.authFetch('/api/me/email-verification/request', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const message = resp.status === 400
                    ? 'Add an email on the Profile tab before requesting verification.'
                    : (body.detail || 'Could not request verification.');
                this.showAccountBanner('email', 'error', message);
                return;
            }
            this.showAccountBanner('email', 'success', 'Verification email sent. Paste the token below to confirm.');
            const dev = document.getElementById('account-email-dev-token');
            const devVal = document.getElementById('account-email-dev-token-value');
            if (body.verification_token && dev && devVal) {
                dev.hidden = false;
                devVal.textContent = body.verification_token;
            } else if (dev) {
                dev.hidden = true;
            }
        } catch (err) {
            this.showAccountBanner('email', 'error', 'Network error while requesting verification.');
        } finally {
            if (btn) { btn.textContent = 'Send verification email'; btn.disabled = false; }
            // Disabled state recalculated on next profile load.
            if (this._accountProfile) this.applyAccountEmailState(this._accountProfile);
        }
    },

    async handleAccountEmailConfirmSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const token = (data.get('token') || '').toString().trim();
        this.clearAccountBanner('email');
        if (token.length < 16) {
            this.showAccountBanner('email', 'error', 'Verification token must be at least 16 characters.');
            return;
        }
        try {
            const resp = await this.authFetch('/api/me/email-verification/confirm', {
                method: 'POST',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ token }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                this.showAccountBanner('email', 'error', body.detail || 'That verification token is invalid or expired.');
                return;
            }
            form.reset();
            const dev = document.getElementById('account-email-dev-token');
            if (dev) dev.hidden = true;
            this.showAccountBanner('email', 'success', 'Email verified. Thank you for confirming.');
            this.loadAccountProfile();
        } catch (err) {
            this.showAccountBanner('email', 'error', 'Network error while confirming the token.');
        }
    },

    showAccountBanner(panel, kind, message) {
        const el = document.getElementById(`account-${panel}-banner`);
        if (!el) return;
        el.dataset.kind = kind;
        el.textContent = message;
        el.hidden = false;
    },
    clearAccountBanner(panel) {
        const el = document.getElementById(`account-${panel}-banner`);
        if (!el) return;
        el.hidden = true;
        el.textContent = '';
        delete el.dataset.kind;
    },

    // ---- Password reset request modal (Phase A.4 login-modal footer) ----
    openPasswordResetRequestModal() {
        this.hideLoginModal?.();
        const modal = document.getElementById('password-reset-request-modal');
        if (!modal) return;
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        const usernameInput = document.getElementById('password-reset-username');
        const navUsername = document.getElementById('login-username')?.value;
        if (usernameInput) {
            usernameInput.value = navUsername || '';
            setTimeout(() => usernameInput.focus(), 50);
        }
        this.hideSimpleBanner('password-reset-request-banner');
        const dev = document.getElementById('password-reset-request-dev-token');
        if (dev) dev.hidden = true;
    },
    closePasswordResetRequestModal() {
        const modal = document.getElementById('password-reset-request-modal');
        if (!modal) return;
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
        const form = document.getElementById('password-reset-request-form');
        if (form) form.reset();
    },
    async handlePasswordResetRequestSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const username = (data.get('username') || '').toString().trim();
        this.hideSimpleBanner('password-reset-request-banner');
        if (!username) {
            this.showSimpleBanner('password-reset-request-banner', 'error', 'Username is required.');
            return;
        }
        try {
            const resp = await fetch('/api/auth/password-reset/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username }),
            });
            const body = await resp.json().catch(() => ({}));
            // Backend response is intentionally generic regardless of whether
            // the username exists, to avoid enumeration. We mirror that here.
            this.showSimpleBanner(
                'password-reset-request-banner',
                'success',
                'If an account exists for that username, reset instructions are on the way. The reset link goes to the email on file.'
            );
            const dev = document.getElementById('password-reset-request-dev-token');
            const devVal = document.getElementById('password-reset-request-dev-token-value');
            if (body.reset_token && dev && devVal) {
                dev.hidden = false;
                devVal.textContent = body.reset_token;
            }
        } catch (err) {
            this.showSimpleBanner('password-reset-request-banner', 'error', 'Network error. Try again in a moment.');
        }
    },

    // ---- Email verification landing (/verify-email) ----
    async handleVerifyEmailLandingSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const token = (data.get('token') || '').toString().trim();
        this.hideSimpleBanner('verify-email-banner');
        if (token.length < 16) {
            this.showSimpleBanner('verify-email-banner', 'error', 'Verification token must be at least 16 characters.');
            return;
        }
        try {
            const resp = await fetch('/api/me/email-verification/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                this.showSimpleBanner('verify-email-banner', 'error', body.detail || 'That verification token is invalid or expired.');
                return;
            }
            form.reset();
            this.showSimpleBanner('verify-email-banner', 'success', 'Email verified. You can close this page or open your profile.');
        } catch (err) {
            this.showSimpleBanner('verify-email-banner', 'error', 'Network error while confirming the token.');
        }
    },

    // ---- Password reset confirmation landing (/reset-password) ----
    async handleResetPasswordLandingSubmit(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const token = (data.get('token') || '').toString().trim();
        const next = (data.get('new_password') || '').toString();
        const confirm = (data.get('confirm_password') || '').toString();
        this.hideSimpleBanner('reset-password-banner');
        if (token.length < 16) {
            this.showSimpleBanner('reset-password-banner', 'error', 'Reset token must be at least 16 characters.');
            return;
        }
        if (next.length < 8) {
            this.showSimpleBanner('reset-password-banner', 'error', 'New password must be at least 8 characters.');
            return;
        }
        if (next !== confirm) {
            this.showSimpleBanner('reset-password-banner', 'error', 'The two new-password fields do not match.');
            return;
        }
        try {
            const resp = await fetch('/api/auth/password-reset/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token, new_password: next }),
            });
            const body = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                this.showSimpleBanner('reset-password-banner', 'error', body.detail || 'That reset token is invalid or expired.');
                return;
            }
            form.reset();
            this.showSimpleBanner('reset-password-banner', 'success', 'Password reset. Sign in with your new password.');
            // Show login modal after a short delay so the user sees the success.
            setTimeout(() => this.showLoginModal?.(), 1200);
        } catch (err) {
            this.showSimpleBanner('reset-password-banner', 'error', 'Network error while resetting your password.');
        }
    },

    // ---- Generic banner helpers used by landings + reset modal ----
    showSimpleBanner(id, kind, message) {
        const el = document.getElementById(id);
        if (!el) return;
        el.dataset.kind = kind;
        el.textContent = message;
        el.hidden = false;
    },
    hideSimpleBanner(id) {
        const el = document.getElementById(id);
        if (!el) return;
        el.hidden = true;
        el.textContent = '';
        delete el.dataset.kind;
    },

    // Auto-populate the token field when navigating to /verify-email?token=…
    // or /reset-password?token=…. Called by showShellView after activation.
    populateLandingTokenFromQuery() {
        try {
            const params = new URLSearchParams(window.location.search);
            const token = (params.get('token') || '').trim();
            if (!token) return;
            const path = window.location.pathname;
            if (path === '/verify-email') {
                const input = document.getElementById('verify-email-token-input');
                if (input && !input.value) input.value = token;
            } else if (path === '/reset-password') {
                const input = document.getElementById('reset-password-token');
                if (input && !input.value) input.value = token;
            }
        } catch { /* ignore */ }
    },
};
