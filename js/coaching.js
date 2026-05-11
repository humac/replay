// Coaching workspace: roster, notes, playlists, in-/coach Review video player + telestrator,
// player-facing /feedback view with a focused feedback-player modal. The in-match side panel
// is intentionally absent — Coach > Review is the single authoring surface.

import { COACH_TEMPLATES, COACH_TEMPLATE_GROUPS, findCoachTemplate } from './coaching-templates.js';
import { VALID_FEEDBACK_TABS } from './coaching/feedback.js';

export const NOTE_CATEGORIES = [
    ['shape', 'Shape'], ['pressing', 'Pressing'], ['transition', 'Transition'],
    ['set_piece', 'Set piece'], ['build_up', 'Build-up'], ['finishing', 'Finishing'],
    ['defending', 'Defending'], ['goalkeeper', 'Goalkeeper'], ['effort', 'Effort'],
    ['decision', 'Decision'], ['other', 'Other'],
];

export const VISIBILITY_OPTIONS = [
    ['private', 'Private'], ['team', 'Team-visible'],
    ['player', 'Player/family'], ['unlisted', 'Unlisted link'],
];

// Phase 1 structured-note tone (PR 1b). Mirrors the backend
// `_VALID_NOTE_TYPES` set in models.py — keep in sync. The default
// `correction` matches the column default in `coaching_notes` so
// existing UIs that don't send `note_type` keep behaving the same.
export const NOTE_TYPES = [
    ['positive',        'Positive',        '+'],
    ['correction',      'Correction',      '↺'],
    ['question',        'Question',        '?'],
    ['team_concept',    'Team',            '⌬'],
    ['individual_goal', 'Goal',            '★'],
];
export const DEFAULT_NOTE_TYPE = 'correction';

// TODO(PR-FE 10): FEEDBACK_NOTE_TYPE_LABELS moved to js/coaching/feedback.js.

const VALID_COACH_TABS = ['roster', 'notes', 'playlists', 'clips', 'summaries', 'engagement', 'settings', 'review'];
// TODO(PR-FE 10): VALID_FEEDBACK_TABS moved to js/coaching/feedback.js; imported above.

export const GOAL_STATUS_OPTIONS = [
    ['open', 'Open'], ['in_progress', 'In progress'], ['needs_follow_up', 'Needs follow-up'],
    ['achieved', 'Achieved'], ['archived', 'Archived'],
];
export const ACTIVE_GOAL_STATUSES = new Set(['open', 'in_progress', 'needs_follow_up']);
export const GOAL_CONTEXT_OPTIONS = [
    ['next_match', 'Next match'], ['next_training', 'Next training'], ['season_goal', 'Season goal'], ['other', 'Other'],
];
export const GOAL_STATUS_LABELS = Object.fromEntries(GOAL_STATUS_OPTIONS);
export const GOAL_CONTEXT_LABELS = Object.fromEntries(GOAL_CONTEXT_OPTIONS);
export const GOAL_VISIBILITY_OPTIONS = [
    ['player', 'Player/family'], ['coach', 'Coach/admin only'],
];
export const GOAL_PRIORITY_OPTIONS = [
    ['low', 'Low'], ['medium', 'Medium'], ['high', 'High'],
];
export const GOAL_VISIBILITY_LABELS = Object.fromEntries(GOAL_VISIBILITY_OPTIONS);
export const GOAL_PRIORITY_LABELS = Object.fromEntries(GOAL_PRIORITY_OPTIONS);

// Phase 4b: pre/post-roll defaults for the Coach Review "Save Clip"
// affordance. Match the existing playlist defaults so a coach who's
// used to playlist sessions sees the same windowing behavior on
// freshly-saved clips. Both can be overridden in the clip modal.
export const COACH_CLIP_DEFAULT_PRE_ROLL = 5;
export const COACH_CLIP_DEFAULT_POST_ROLL = 8;
// Phase 4a backend MVP cap (enforced by `models._MAX_CLIP_DURATION_SECONDS`).
// We mirror it client-side so the modal's Save button can short-circuit
// before the request hits the server.
export const COACH_CLIP_MAX_DURATION_SECONDS = 120;

const AI_DRAFT_TARGETS = [
    ['player_summary', 'Player summary', 'coach-review-player-summary'],
    ['what_happened', 'What happened', 'coach-review-what-happened'],
    ['why_it_matters', 'Why it matters', 'coach-review-why-it-matters'],
    ['what_to_do_next', 'What to do next', 'coach-review-what-to-do-next'],
];
const AI_DRAFT_TARGET_LABELS = Object.fromEntries(AI_DRAFT_TARGETS.map(([value, label]) => [value, label]));

export const coachingMixin = {
    _coachBundle: null,
    _coachDrawing: null,
    _coachDrawingActive: false,
    _coachDrawingTool: 'freehand',
    _coachDrawingColor: '#38bdf8',
    _coachDrawingWidth: 3,
    _coachSelectedObjectIndex: null,
    _coachCurrentObject: null,
    _coachDragState: null,
    // TODO(PR-FE 11): _coachPlaylistSession / _coachPlaylistMonitor /
    // _coachPlaylistFreezeTimer state declarations moved to
    // js/coaching/feedback-player.js.
    _coachTab: 'roster',
    _feedbackTab: 'playlists',
    _coachReview: null,
    _coachCanvasId: 'coach-drawing-canvas',
    _coachVideoId: 'coach-review-video',
    // Phase 6d-1 — Coach Review source mode state. `_coachReviewSource`
    // tracks which authoring surface (video / tactical_board) is on
    // screen; `_coachReviewRequestedSource` is a one-shot intent set by
    // routing entry points (e.g. Roster's "Add observation" button) so
    // the next renderCoachReview() call applies the right mode.
    // `_coachReviewIntent` carries player-id / mode hints from the
    // routing call. `_coachReviewBoardCtrl` is the controller returned
    // by mountTacticalBoardReviewCanvas; null when not in board mode.
    _coachReviewSource: 'video',
    _coachReviewRequestedSource: null,
    _coachReviewIntent: null,
    _coachReviewBoardCtrl: null,
    _feedbackPlayer: null,
    // Phase 4b: end-of-window watcher for clip playback. Holds a
    // reference to the timeupdate listener + the fallback interval
    // so `cleanup()` in `openFeedbackPlayer` can detach them on close.
    // Null when the focused player isn't in clip mode.
    _clipMonitor: null,
    // Multi-player formation overlay (Phase 1) — see ROADMAP "Coaching Telestrator".
    // Draft holds the in-progress anchors while the coach is clicking; gets
    // committed to a single drawing object on Done.
    _coachFormationDraft: null,
    _coachFormationMode: 'quick', // 'quick' | 'linked'

    // Sprint 5: id of the timeline-rail chip currently flagged as the
    // active note (highlighted blue, aria-pressed=true). Cleared on
    // match/slot change and tab teardown.
    _coachActiveNoteId: null,

    // Phase 2: id of the coaching template most recently applied to the
    // composer. Used by `applyCoachTemplate()` so a coach who picks a
    // different template can swap fields without an extra confirm prompt
    // (since the existing values came from a template, not from the
    // coach typing). Cleared on save (per-moment) and on Clear template.
    _coachReviewActiveTemplateId: null,

    // Roster redesign — search query + status filter live here so the
    // table can re-render without mutating `_coachBundle`.
    _coachRosterSearch: '',
    _coachRosterFilter: 'all', // 'all' | 'active' | 'inactive'

    // Sprint 6: Wide / Focus mode. Session-local — never persisted; resets
    // on tab leave or page reload. The keydown listener is bound only when
    // focus mode is on, so an Escape press elsewhere in the app is unaffected.
    _coachFocusMode: false,
    _coachFocusEscapeHandler: null,
    _coachFocusInspectorOpen: false,
    _teamSettings: null,

    // Sprint 7: Coach Review keyboard shortcut handler. Bound only while
    // Review is the active sub-tab; uninstalled on tab change / teardown.
    _coachShortcutsHandler: null,

    // ===== top-level view entry points =====

    async showCoachView({ pushHistory = true, replaceHistory = false, scrollTop = true, tab = null, matchId = null, slot = null } = {}) {
        if (!this.canCoach()) {
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('coach-view', 'coach');
        const targetTab = VALID_COACH_TABS.includes(tab) ? tab : (this._coachTab || 'roster');
        if (matchId) this._coachReviewPending = { matchId, slot: slot || 'full' };
        if (pushHistory) {
            const url = this._coachUrl(targetTab, matchId, slot);
            this.pushHistoryState({ view: 'coach', tab: targetTab }, { replace: replaceHistory, url });
        }
        await this.renderCoachWorkspace();
        this.setCoachTab(targetTab, { pushHistory: false });
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async showFeedbackView({ pushHistory = true, replaceHistory = false, scrollTop = true, tab = null } = {}) {
        if (!this.authToken) {
            this.showLoginModal();
            return;
        }
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();
        this.activateView('feedback-view', 'feedback');
        const targetTab = VALID_FEEDBACK_TABS.includes(tab) ? tab : (this._feedbackTab || 'playlists');
        if (pushHistory) {
            const url = `/feedback?tab=${targetTab}`;
            this.pushHistoryState({ view: 'feedback', tab: targetTab }, { replace: replaceHistory, url });
        }
        await this.renderMyFeedback();
        this.setFeedbackTab(targetTab, { pushHistory: false });
        if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    _coachUrl(tab, matchId, slot) {
        const params = new URLSearchParams();
        if (tab && tab !== 'roster') params.set('tab', tab);
        if (matchId) params.set('match', String(matchId));
        if (slot) params.set('slot', slot);
        const qs = params.toString();
        return qs ? `/coach?${qs}` : '/coach';
    },

    // ===== sub-tab routers =====

    setCoachTab(name, { pushHistory = true } = {}) {
        if (!VALID_COACH_TABS.includes(name)) name = 'roster';
        this._coachTab = name;
        document.querySelectorAll('[data-coach-tab]').forEach((btn) => {
            const active = btn.dataset.coachTab === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        VALID_COACH_TABS.forEach((tab) => {
            const panel = document.getElementById(`coach-tab-${tab}`);
            if (panel) panel.hidden = tab !== name;
        });
        // Sprint 1: drive a video-first layout when Review is the active sub-tab.
        // Scoping the class to #coach-view keeps Roster/Notes/Playlists untouched.
        const coachView = document.getElementById('coach-view');
        if (coachView) coachView.classList.toggle('is-review-mode', name === 'review');
        // Sprint 6: exit focus mode when leaving Review so it doesn't leak
        // into Roster/Notes/Playlists. Idempotent — no-op if not in focus.
        if (name !== 'review') this.exitCoachFocusMode();
        // Sprint 7: install / tear down Coach-Review-scoped keyboard
        // shortcuts. Listener is bound only while Review is active so the
        // shortcuts (Space, J/L, S, A/F/Z/C/T/D, …) don't intercept keys
        // on Roster / Notes / Playlists / Feedback / public match.
        if (name === 'review') this.installCoachReviewShortcuts();
        else this.uninstallCoachReviewShortcuts();
        // Sprint 2 polish: install a window-resize listener that keeps the
        // inspector height matched to the video wrapper. Bound once globally;
        // _syncCoachReviewSideHeight no-ops when the Review tab isn't active.
        if (!this._coachReviewSideSyncBound) {
            window.addEventListener('resize', () => {
                const v = document.getElementById(this._coachVideoId);
                if (v) this._syncCoachReviewSideHeight(v);
            });
            this._coachReviewSideSyncBound = true;
        }
        if (name === 'review') {
            // Run once after the panel becomes visible so the heights match
            // even before any video loads.
            requestAnimationFrame(() => {
                const v = document.getElementById(this._coachVideoId);
                if (v) this._syncCoachReviewSideHeight(v);
            });
        }
        if (pushHistory) {
            const params = new URLSearchParams(window.location.search);
            if (name === 'roster') params.delete('tab');
            else params.set('tab', name);
            const qs = params.toString();
            const url = qs ? `/coach?${qs}` : '/coach';
            this.pushHistoryState({ view: 'coach', tab: name }, { replace: true, url });
        }
        if (name === 'roster') this.renderCoachRoster();
        if (name === 'notes') this.renderCoachNotes();
        if (name === 'playlists') this.renderCoachPlaylists();
        if (name === 'clips') this.renderCoachClips();
        if (name === 'summaries') this.renderCoachMatchSummaries();
        if (name === 'engagement') this.renderCoachEngagement();
        if (name === 'settings') this.renderCoachTeamSettings();
        if (name === 'review') this.renderCoachReview();
        else this.tearDownCoachReview();
    },

    // TODO(PR-FE 10): setFeedbackTab moved to js/coaching/feedback.js.

    // ===== Team settings =====

    async loadCoachTeamSettings() {
        const resp = await this.authFetch('/api/coach/team/settings', { headers: this.getAuthHeaders() });
        if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}));
            throw new Error(detail.detail || 'Could not load team settings.');
        }
        this._teamSettings = await resp.json();
        return this._teamSettings;
    },

    async renderCoachTeamSettings() {
        const el = document.getElementById('coach-team-settings-content');
        if (!el) return;
        el.innerHTML = '<div class="session-empty">Loading team settings…</div>';
        try {
            const payload = await this.loadCoachTeamSettings();
            const settings = payload.settings || {};
            const canEdit = !!payload.can_edit;
            const teamName = payload.team?.name || payload.team_id || 'Active team';
            el.innerHTML = this.teamSettingsHtml(settings, { canEdit, teamName });
            this.syncTeamSettingsControls(settings, canEdit);
        } catch (error) {
            el.innerHTML = `<div class="session-empty">${this.esc(error.message || 'Could not load team settings.')}</div>`;
        }
    },

    teamSettingsHtml(settings, { canEdit, teamName }) {
        const disabled = canEdit ? '' : 'disabled';
        const readonly = canEdit ? '' : '<span class="status-pill waiting">Read only</span>';
        return `
            <div class="team-settings-shell">
                <div class="team-settings-intro">
                    <div>
                        <span class="section-kicker">Active team</span>
                        <h3>${this.esc(teamName)} settings</h3>
                        <p>Team admins control AI drafting governance and coaching defaults. Coaches can review these settings before using templates and feedback tools.</p>
                    </div>
                    ${readonly}
                </div>

                <div class="team-settings-grid">
                    <section class="team-settings-card" aria-labelledby="team-settings-ai-title">
                        <div class="team-settings-card-head">
                            <span class="section-kicker">AI governance</span>
                            <h4 id="team-settings-ai-title">Drafting controls</h4>
                        </div>
                        ${this.teamSettingsToggleHtml('ai.drafting_enabled', 'Enable AI drafting', 'Allow draft generation for approved targets only.', !!settings['ai.drafting_enabled'], disabled)}
                        ${this.teamSettingsChoiceGroupHtml('ai.tone', 'Draft tone', [
                            ['direct', 'Direct'], ['encouraging', 'Encouraging'], ['technical', 'Technical']
                        ], settings['ai.tone'] || 'direct', disabled)}
                        ${this.teamSettingsMultiHtml('ai.never_draft_for_visibilities', 'Never draft or include context for', [
                            ['private', 'Private'], ['player', 'Player/family']
                        ], settings['ai.never_draft_for_visibilities'] || [], disabled)}
                        ${this.teamSettingsMultiHtml('ai.allowed_draft_targets', 'Allowed draft targets', [
                            ['player_summary', 'Player summary'], ['what_happened', 'What happened'], ['why_it_matters', 'Why it matters'],
                            ['what_to_do_next', 'What to do next'], ['clip_title', 'Clip title'], ['clip_description', 'Clip description'],
                            ['goal_description', 'Goal description'], ['goal_success_criteria', 'Goal success criteria'],
                            ['summary_team_positives', 'Summary positives'], ['summary_team_improvements', 'Summary improvements'], ['summary_training_focus', 'Training focus']
                        ], settings['ai.allowed_draft_targets'] || [], disabled)}
                    </section>

                    <section class="team-settings-card" aria-labelledby="team-settings-defaults-title">
                        <div class="team-settings-card-head">
                            <span class="section-kicker">Defaults</span>
                            <h4 id="team-settings-defaults-title">Coach workspace defaults</h4>
                        </div>
                        ${this.teamSettingsChoiceGroupHtml('notes.default_visibility', 'New note visibility', VISIBILITY_OPTIONS, settings['notes.default_visibility'] || 'private', disabled)}
                        ${this.teamSettingsChoiceGroupHtml('summaries.default_visibility', 'Match summary visibility', VISIBILITY_OPTIONS, settings['summaries.default_visibility'] || 'private', disabled)}
                        ${this.teamSettingsChoiceGroupHtml('goals.default_visibility', 'Goal visibility', GOAL_VISIBILITY_OPTIONS, settings['goals.default_visibility'] || 'player', disabled)}
                    </section>
                </div>

                <div class="team-settings-actions">
                    <p id="team-settings-status" class="team-settings-status">${canEdit ? 'Changes save to the active team.' : 'Ask a team admin to change governance settings.'}</p>
                    <button type="button" class="btn-primary" id="team-settings-save-btn" onclick="app.saveCoachTeamSettings()" ${disabled}>Save team settings</button>
                </div>
            </div>
        `;
    },

    teamSettingsToggleHtml(key, label, help, selected, disabled) {
        return `
            <div class="team-settings-field">
                <span class="team-settings-label">${this.esc(label)}</span>
                <button type="button" class="team-settings-switch ${selected ? 'is-on' : ''}" data-setting-key="${this.esc(key)}" data-setting-kind="bool" aria-pressed="${selected ? 'true' : 'false'}" onclick="app.toggleTeamSettingsBool(this)" ${disabled}>
                    <span>${selected ? 'Enabled' : 'Disabled'}</span>
                </button>
                <p>${this.esc(help)}</p>
            </div>
        `;
    },

    teamSettingsChoiceGroupHtml(key, label, options, selected, disabled) {
        return `
            <div class="team-settings-field">
                <span class="team-settings-label">${this.esc(label)}</span>
                <div class="team-settings-choice-row" data-setting-key="${this.esc(key)}" data-setting-kind="single">
                    ${options.map(([value, optionLabel]) => `
                        <button type="button" class="coach-check-option team-settings-chip ${value === selected ? 'is-selected' : ''}" data-value="${this.esc(value)}" aria-pressed="${value === selected ? 'true' : 'false'}" onclick="app.selectTeamSettingsSingle(this)" ${disabled}>
                            <span class="coach-check-box" aria-hidden="true"></span>
                            <span class="coach-check-label">${this.esc(optionLabel)}</span>
                        </button>
                    `).join('')}
                </div>
            </div>
        `;
    },

    teamSettingsMultiHtml(key, label, options, selectedValues, disabled) {
        const selected = new Set(selectedValues || []);
        return `
            <div class="team-settings-field">
                <span class="team-settings-label">${this.esc(label)}</span>
                <div class="team-settings-choice-row wrap" data-setting-key="${this.esc(key)}" data-setting-kind="multi">
                    ${options.map(([value, optionLabel]) => `
                        <button type="button" class="coach-check-option team-settings-chip ${selected.has(value) ? 'is-selected' : ''}" data-value="${this.esc(value)}" aria-pressed="${selected.has(value) ? 'true' : 'false'}" onclick="app.toggleCoachCheck(this)" ${disabled}>
                            <span class="coach-check-box" aria-hidden="true"></span>
                            <span class="coach-check-label">${this.esc(optionLabel)}</span>
                        </button>
                    `).join('')}
                </div>
            </div>
        `;
    },

    syncTeamSettingsControls(settings, canEdit) {
        document.querySelectorAll('#coach-team-settings-content [data-setting-key]').forEach((el) => {
            if ('disabled' in el) el.disabled = !canEdit;
        });
    },

    toggleTeamSettingsBool(btn) {
        if (!btn || btn.disabled) return;
        const next = btn.getAttribute('aria-pressed') !== 'true';
        btn.classList.toggle('is-on', next);
        btn.setAttribute('aria-pressed', next ? 'true' : 'false');
        const label = btn.querySelector('span');
        if (label) label.textContent = next ? 'Enabled' : 'Disabled';
    },

    selectTeamSettingsSingle(btn) {
        if (!btn || btn.disabled) return;
        const row = btn.closest('[data-setting-kind="single"]');
        if (!row) return;
        row.querySelectorAll('.team-settings-chip').forEach((item) => {
            const active = item === btn;
            item.classList.toggle('is-selected', active);
            item.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    },

    collectTeamSettingsPayload() {
        const root = document.getElementById('coach-team-settings-content');
        const settings = {};
        if (!root) return settings;
        root.querySelectorAll('[data-setting-key]').forEach((el) => {
            const key = el.dataset.settingKey;
            const kind = el.dataset.settingKind;
            if (!key) return;
            if (kind === 'bool') {
                settings[key] = el.getAttribute('aria-pressed') === 'true';
            } else if (kind === 'single') {
                const selected = el.querySelector('.team-settings-chip.is-selected');
                if (selected) settings[key] = selected.dataset.value;
            } else if (kind === 'multi') {
                settings[key] = Array.from(el.querySelectorAll('.team-settings-chip.is-selected')).map((item) => item.dataset.value);
            }
        });
        return settings;
    },

    async saveCoachTeamSettings() {
        const btn = document.getElementById('team-settings-save-btn');
        const status = document.getElementById('team-settings-status');
        if (!btn || btn.disabled) return;
        const done = this.btnLoading ? this.btnLoading(btn, 'Saving…') : null;
        if (status) status.textContent = 'Saving team settings…';
        try {
            const resp = await this.authFetch('/api/coach/team/settings', {
                method: 'PATCH',
                headers: { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: this.collectTeamSettingsPayload() }),
            });
            const payload = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const detail = payload.detail;
                const message = detail?.errors?.map((err) => `${err.key}: ${err.detail}`).join('; ') || detail || 'Could not save team settings.';
                throw new Error(message);
            }
            this._teamSettings = payload;
            this.showSuccess?.('Team settings saved.');
            if (status) status.textContent = 'Saved.';
            await this.renderCoachTeamSettings();
        } catch (error) {
            if (status) status.textContent = error.message || 'Could not save team settings.';
            this.showError?.(error.message || 'Could not save team settings.');
        } finally {
            if (done) done();
        }
    },

    // ===== Coach workspace data load =====

    async renderCoachWorkspace() {
        const roster = document.getElementById('coach-roster-list');
        const notes = document.getElementById('coach-notes-list');
        if (roster) roster.innerHTML = '<div class="session-empty">Loading roster...</div>';
        if (notes) notes.innerHTML = '<div class="session-empty">Loading notes...</div>';
        try {
            this._coachBundle = await this.loadCoachBundle();
            this.renderCoachRoster();
            this.renderCoachLinkSelectors();
            this.renderCoachNotes();
            this.renderCoachPlaylists();
            this.renderCoachClips();
            this.renderCoachMatchSummaries();
            this.renderCoachEngagementFilters();
            this.renderCoachReviewPicker();
        } catch (err) {
            this.showError(err.message || 'Could not load coaching workspace.');
        }
    },

    renderCoachLinkSelectors() {
        // Roster redesign: the standalone Player/User/Relationship form is
        // gone — those selects now live inside the cloned link-modal body
        // (populated by openCoachLinkModal()) and inside the Quick Add
        // panel's optional "Link Family / Self Account" select. We only
        // need to populate the Quick Add user select here; the modal's
        // selects are filled when the modal opens.
        const bundle = this._coachBundle || { players: [], users: [] };
        const userEl = document.getElementById('coach-link-user-quickadd');
        if (userEl) {
            const opts = bundle.users.map((u) => (
                `<option value="${this.esc(u.id)}">${this.esc(u.display_name || u.username)} (@${this.esc(u.username)})</option>`
            )).join('');
            userEl.innerHTML = `<option value="">— none —</option>${opts}`;
        }
    },

    _coachLinkSelectorOptionsHtml() {
        // Reused by the link modal so both the standalone modal and any
        // future inline link UI build their selects from the same data.
        const bundle = this._coachBundle || { players: [], users: [] };
        const playerOptions = bundle.players.map((p) => (
            `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`
        )).join('') || '<option value="">No players yet</option>';
        const userOptions = bundle.users.map((u) => (
            `<option value="${this.esc(u.id)}">${this.esc(u.display_name || u.username)} (@${this.esc(u.username)})</option>`
        )).join('') || '<option value="">Create a user first</option>';
        return { playerOptions, userOptions };
    },

    coachCheckListHtml(items, emptyLabel = 'Nothing available') {
        if (!items.length) {
            return `<div class="coach-check-empty">${this.esc(emptyLabel)}</div>`;
        }
        return items.map((item) => `
            <button type="button" class="coach-check-option" data-value="${this.esc(item.value)}" aria-pressed="false" onclick="app.toggleCoachCheck(this)">
                <span class="coach-check-box" aria-hidden="true"></span>
                <span class="coach-check-label">${this.esc(item.label)}</span>
            </button>
        `).join('');
    },

    renderCoachCheckList(target, items, emptyLabel) {
        const el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return;
        el.innerHTML = this.coachCheckListHtml(items, emptyLabel);
    },

    toggleCoachCheck(btn) {
        const selected = !btn.classList.contains('is-selected');
        btn.classList.toggle('is-selected', selected);
        btn.setAttribute('aria-pressed', selected ? 'true' : 'false');
    },

    playerLabel(player) {
        const number = player.jersey_number ? `#${player.jersey_number} ` : '';
        return `${number}${player.display_name}`;
    },

    noteLabel(note) {
        const match = this.matches.find((m) => m.id === note.match_id);
        const matchup = match ? `${match.home_team} vs ${match.away_team}` : note.match_id;
        return `${this.formatClock(note.timestamp_seconds)} · ${matchup} · ${note.title}`;
    },

    formatClock(seconds) {
        const total = Math.max(0, Math.floor(Number(seconds || 0)));
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return `${mins}:${String(secs).padStart(2, '0')}`;
    },

    matchLabel(matchId) {
        const m = this.matches.find((x) => x.id === matchId);
        return m ? `${m.home_team} vs ${m.away_team} · ${this.formatDate(m.date)}` : String(matchId);
    },

    // ===== Notes sub-tab =====

    // TODO(PR 5.2 cross-domain): _coachNoteThumbHtml,
    // handleRegenCoachThumb, and _refreshCoachNoteThumbnailSurfaces
    // moved to js/coaching/thumbnails.js.

    // TODO(PR 5.2 cross-domain): openCoachObservationModal moved to
    // js/coaching/observations.js.

    // TODO(PR 5.2 cross-domain): Coach > Playlists tab methods
    // (renderCoachPlaylists, _coachPlaylistThumbStripHtml,
    // openCoachPlaylistModal, handleCoachDeletePlaylist,
    // previewCoachPlaylist) moved to js/coaching/playlists.js.

    // ===== Clips sub-tab (Phase 4b — first-class coaching clips UI) =====
    //
    // Backend (PR #95 / Phase 4a):
    //   - GET    /api/coach/clips
    //   - GET    /api/coach/clips/{id}
    //   - POST   /api/coach/clips
    //   - PATCH  /api/coach/clips/{id}
    //   - DELETE /api/coach/clips/{id}
    //   - /api/my-feedback now includes clips[]
    //
    // The Coach > Clips tab renders the coach's full clip library.
    // The Coach > Review tab gets a Save-clip button that opens the
    // same composer modal pre-filled with [currentTime − pre-roll,
    // currentTime + post-roll]. Visibility / category / players reuse
    // the existing note-form selectors for vocabulary parity.
    //
    // Clips don't have their own thumbnail in Phase 4b. When a clip
    // has `source_note_id`, we reuse that note's thumbnail (loaded
    // through the existing visibility-checked
    // `loadCoachNoteThumbnail`) as a visual preview — no new
    // thumbnail backend, no auth weakening.

    // TODO(PR 5.2 cross-domain): renderCoachClips moved to js/coaching/clips.js.

    // TODO(PR 5.2 cross-domain): _coachClipThumbHtml and
    // _coLocatedNoteId moved to js/coaching/thumbnails.js.

    // TODO(PR-FE 10): _clipDurationLabel moved to js/coaching/feedback.js.

    // TODO(PR 5.2 cross-domain): openClipComposerFromReview and
    // _deriveClipSourceNoteId moved to js/coaching/clips.js.

    // TODO(PR-FE 12b): _refreshCoachReviewSaveClipState moved to
    // js/coaching/review.js.

    // TODO(PR 5.2 cross-domain): openCoachClipModal, handleCoachDeleteClip,
    // and previewCoachClip moved to js/coaching/clips.js.

    // ===== Review sub-tab =====

    // ===== Match summaries sub-tab (Phase 8) =====
    // Methods extracted to js/coaching/match-summaries.js (coachingMatchSummariesMixin).

    // TODO(PR-FE 12b): renderCoachReviewPicker, renderCoachReview,
    // routeNewNote, routeNewClip, and routeNewObservation moved to
    // js/coaching/review.js.

    // TODO(PR-FE 12a): Phase 6d-1 source-toggle, tactical-board
    // canvas mounter, TB observation save, focus mode + drawer,
    // and Coach Review keyboard shortcuts moved to
    // js/coaching/review.js.

    renderCoachAIDraftPanel() {
        // UX-only: these client-side ai.drafting_enabled / allowed_draft_targets / visibility checks
        // are for UX hygiene (avoiding visible-but-non-functional buttons). routers/coach_ai.py is the
        // authoritative gate — server enforcement is the actual access control.
        const settings = this._teamSettings?.settings || {};
        const enabled = !!settings['ai.drafting_enabled'];
        const allowedTargets = this._coachAIAllowedDraftTargets(settings);
        const blockedVisibilities = settings['ai.never_draft_for_visibilities'] || [];
        const status = enabled
            ? (allowedTargets.length
                ? 'Generate a bounded draft from selected, team-scoped evidence. Nothing is saved until you insert and save.'
                : 'AI drafting is enabled, but no note fields are allowed for drafting in Team settings.')
            : 'AI drafting is disabled for this team. Enable it in Team settings to generate drafts.';
        const disabled = enabled && allowedTargets.length ? '' : 'disabled aria-disabled="true"';
        return `
            <section id="coach-ai-draft-panel" class="coach-ai-draft-panel ${enabled ? 'is-enabled' : 'is-disabled'}" aria-labelledby="coach-ai-draft-title" data-blocked-visibilities="${this.esc(blockedVisibilities.join(','))}">
                <div class="coach-ai-draft-head">
                    <div>
                        <span class="section-kicker">AI assist</span>
                        <h5 id="coach-ai-draft-title">AI drafting</h5>
                    </div>
                    <span class="status-pill ${enabled ? 'ready' : 'waiting'}">${enabled ? 'Opt-in' : 'Disabled'}</span>
                </div>
                <p id="coach-ai-draft-status" class="coach-ai-draft-status">${this.esc(status)}</p>
                <label class="coach-review-field-label" for="coach-ai-draft-target">
                    <span>Draft target</span>
                    <select id="coach-ai-draft-target" ${disabled} onchange="app.refreshCoachAIDraftControls()">
                        ${(enabled ? allowedTargets : AI_DRAFT_TARGETS).map(([value, label]) => `<option value="${this.esc(value)}">${this.esc(label)}</option>`).join('')}
                    </select>
                </label>
                <label class="coach-review-field-label" for="coach-ai-draft-instruction">
                    <span>Coach instruction <small>(not stored)</small></span>
                    <textarea id="coach-ai-draft-instruction" rows="2" maxlength="4000" placeholder="Optional: emphasize confidence, one concise sentence, U12 tone…" ${disabled}></textarea>
                </label>
                <div class="coach-ai-draft-actions">
                    <button type="button" id="coach-ai-draft-generate" class="mini-action-btn" onclick="app.generateCoachAIDraft()" ${disabled}>Generate draft</button>
                    <button type="button" id="coach-ai-draft-insert" class="mini-action-btn" onclick="app.insertCoachAIDraft()" disabled aria-disabled="true">Insert</button>
                </div>
                <textarea id="coach-ai-draft-output" class="coach-ai-draft-output" rows="3" readonly placeholder="Draft appears here for review before insertion."></textarea>
            </section>
        `;
    },

    _coachAIAllowedDraftTargets(settings = this._teamSettings?.settings || {}) {
        const allowed = new Set(settings['ai.allowed_draft_targets'] || []);
        return AI_DRAFT_TARGETS.filter(([value]) => allowed.has(value));
    },

    _coachAIDraftTargetConfig(value = null) {
        const selected = value || document.getElementById('coach-ai-draft-target')?.value || AI_DRAFT_TARGETS[0][0];
        const row = AI_DRAFT_TARGETS.find(([target]) => target === selected) || AI_DRAFT_TARGETS[0];
        return { target: row[0], label: row[1], fieldId: row[2] };
    },

    _coachAIDraftVisibility() {
        return document.getElementById('coach-review-visibility')?.value || this._teamSettings?.settings?.['notes.default_visibility'] || 'private';
    },

    _coachAIDraftSelectedPlayerIds() {
        return Array.from(document.querySelectorAll('#coach-review-players .coach-check-option.is-selected'))
            .map((item) => item.dataset.value)
            .filter(Boolean);
    },

    refreshCoachAIDraftControls() {
        const status = document.getElementById('coach-ai-draft-status');
        const generateBtn = document.getElementById('coach-ai-draft-generate');
        if (!generateBtn) return;
        const settings = this._teamSettings?.settings || {};
        const visibility = this._coachAIDraftVisibility();
        const blocked = new Set(settings['ai.never_draft_for_visibilities'] || []);
        const enabled = !!settings['ai.drafting_enabled'];
        const hasAllowedTarget = this._coachAIAllowedDraftTargets(settings).length > 0;
        const blockedByVisibility = blocked.has(visibility);
        generateBtn.disabled = !enabled || !hasAllowedTarget || blockedByVisibility;
        generateBtn.setAttribute('aria-disabled', generateBtn.disabled ? 'true' : 'false');
        if (status) {
            status.textContent = !hasAllowedTarget && enabled
                ? 'AI drafting is enabled, but no note fields are allowed for drafting in Team settings.'
                : (blockedByVisibility
                    ? `Drafting is blocked for ${visibility} visibility by team policy. Choose a permitted visibility before generating.`
                    : (enabled ? 'Ready. Drafts are review-only until inserted and saved.' : 'AI drafting is disabled for this team.'));
        }
    },

    async generateCoachAIDraft() {
        const btn = document.getElementById('coach-ai-draft-generate');
        const output = document.getElementById('coach-ai-draft-output');
        const insertBtn = document.getElementById('coach-ai-draft-insert');
        const status = document.getElementById('coach-ai-draft-status');
        if (!btn || btn.disabled) return;
        this.refreshCoachAIDraftControls();
        if (btn.disabled) return;
        const done = this.btnLoading ? this.btnLoading(btn, 'Drafting…') : null;
        if (status) status.textContent = 'Generating draft from scoped evidence…';
        if (insertBtn) { insertBtn.disabled = true; insertBtn.setAttribute('aria-disabled', 'true'); }
        try {
            const config = this._coachAIDraftTargetConfig();
            const review = this._coachReview || {};
            const evidenceRefs = [];
            if (review.matchId) evidenceRefs.push({ type: 'match', id: review.matchId });
            const payload = await this.draftCoachAI({
                draft_target: config.target,
                target_resource_type: 'player',
                target_resource_id: this._coachAIDraftSelectedPlayerIds()[0] || null,
                target_visibility: this._coachAIDraftVisibility(),
                target_player_ids: this._coachAIDraftSelectedPlayerIds(),
                evidence_refs: evidenceRefs,
                coach_prompt: document.getElementById('coach-ai-draft-instruction')?.value || '',
            });
            if (output) output.value = payload.text || '';
            if (insertBtn) {
                const hasDraft = !!(payload.text || '').trim();
                insertBtn.disabled = !hasDraft;
                insertBtn.setAttribute('aria-disabled', hasDraft ? 'false' : 'true');
            }
            if (status) status.textContent = `Draft ready for ${AI_DRAFT_TARGET_LABELS[config.target] || config.target}. Review before inserting.`;
        } catch (error) {
            if (output) output.value = '';
            if (status) status.textContent = error.message || 'AI drafting failed.';
            this.showError?.(error.message || 'AI drafting failed.');
        } finally {
            if (done) done();
        }
    },

    insertCoachAIDraft() {
        const output = document.getElementById('coach-ai-draft-output');
        const text = (output?.value || '').trim();
        if (!text) return;
        const config = this._coachAIDraftTargetConfig();
        const target = document.getElementById(config.fieldId);
        if (!target) {
            this.showError?.('Open More details before inserting this draft.');
            return;
        }
        target.value = text;
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.focus?.();
        const status = document.getElementById('coach-ai-draft-status');
        if (status) status.textContent = `Inserted into ${AI_DRAFT_TARGET_LABELS[config.target] || config.target}. Save the note to persist it.`;
    },

    // TODO(PR-FE 12b): setCoachReviewNoteType, _syncToneRadiogroup,
    // _setupToneRadiogroup, _refreshCoachTemplateButtons,
    // applyCoachTemplate, clearCoachTemplate,
    // _resetCoachReviewTemplateState, _readCoachReviewTemplateFields,
    // _writeCoachReviewTemplateFields, openNoteInReview, and
    // saveReviewNote moved to js/coaching/review.js.


    // TODO(PR-FE 12a): telestrator toolbar, canvas painter, drawing
    // primitives, and formation overlay moved to
    // js/coaching/review.js.

    // ===== /feedback view =====

    // TODO(PR-FE 10): renderMyFeedback, renderFeedbackLinkedStrip,
    // _feedbackNoteSummary, _feedbackTonePillHtml,
    // _feedbackStructuredHtml, renderFeedbackPlaylists,
    // _resolveFeedbackPlaylistCover, and renderFeedbackNotes moved to
    // js/coaching/feedback.js.

    // TODO(PR-FE 11): openFeedbackNote, openFeedbackPlaylist,
    // openFeedbackClip, _resolveLinkedPlayerChips,
    // _detailStructuredHtml, _detailVideoMetaHtml,
    // _detailObservationMetaHtml, _observationMetaText,
    // _renderUnifiedFeedbackBody, _categoryLabel,
    // openFeedbackPlayer, _loadFeedbackVideoForClip,
    // _stopClipMonitor, _loadFeedbackVideoForNote,
    // _renderFeedbackTelestration, _clearFeedbackTelestration,
    // _startFeedbackHeartbeat, _stopFeedbackHeartbeat,
    // playlistItems, startCoachingPlaylistSession,
    // openCoachingPlaylistItem, startPlaylistMonitor,
    // stopPlaylistMonitor, renderPlaylistSessionRail,
    // toggleCoachingPlaylistPause, restartCoachingPlaylistItem,
    // nextCoachingPlaylistItem, previousCoachingPlaylistItem,
    // finishCoachingPlaylistSession, stopFeedbackPlaylistSession,
    // stopCoachingPlaylistSession, and updateCoachThisMatchLink moved
    // to js/coaching/feedback-player.js.


    // TODO(PR-FE 10): markFeedbackItemReviewed and
    // renderFeedbackMatchSummaries moved to js/coaching/feedback.js.

};
