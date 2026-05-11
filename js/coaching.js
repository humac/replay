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

    /** Phase 4c (issue #100): single source of truth for the Save
     *  Clip button's enabled/disabled state. Reads `_coachReview`,
     *  the video element, and the metadata flag and applies them to
     *  the picker-bar button. Called from `loadCoachReviewVideo` on
     *  the metadata flip, from `tearDownCoachReview` on the unmount,
     *  and from `setCoachTab('review')` so a coach who returns to
     *  the Review tab without re-loading sees the correct state.
     *  Pure DOM toggling — no hidden side effects on note saves or
     *  the rest of the picker bar. */
    _refreshCoachReviewSaveClipState() {
        const btn = document.getElementById('coach-review-save-clip');
        if (!btn) return;
        const review = this._coachReview;
        const video = document.getElementById(this._coachVideoId);
        const ready = !!review?.metadataReady
            && !!video
            && Number.isFinite(video.duration)
            && video.duration > 0;
        btn.disabled = !ready;
        btn.title = ready
            ? 'Save a clip of the current moment'
            : 'Pick a match and wait for the video to load before saving a clip';
        // `aria-disabled` mirrors `disabled` for AT clarity; some
        // screen readers announce only one of the two.
        btn.setAttribute('aria-disabled', ready ? 'false' : 'true');
    },

    // TODO(PR 5.2 cross-domain): openCoachClipModal, handleCoachDeleteClip,
    // and previewCoachClip moved to js/coaching/clips.js.

    // ===== Review sub-tab =====

    // ===== Match summaries sub-tab (Phase 8) =====
    // Methods extracted to js/coaching/match-summaries.js (coachingMatchSummariesMixin).

    renderCoachReviewPicker() {
        const matchSel = document.getElementById('coach-review-match');
        if (!matchSel) return;
        const opts = ['<option value="">Select a match…</option>'].concat(
            this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`)
        ).join('');
        matchSel.innerHTML = opts;
    },

    async renderCoachReview() {
        this.renderCoachReviewPicker();
        const toolbar = document.getElementById('coach-review-toolbar');
        if (toolbar) toolbar.innerHTML = this.renderCoachTelestratorToolbar();
        if (!this._teamSettings) {
            try { await this.loadCoachTeamSettings(); } catch { /* keep composer usable when settings cannot load */ }
        }
        this.renderCoachReviewForm();
        // Phase 4c (issue #100): apply the Save-Clip enabled state to
        // the picker bar AS SOON as it's rendered, so a coach who
        // arrives without a video selected sees the disabled state
        // rather than an inviting blue button that errors on click.
        this._refreshCoachReviewSaveClipState();

        // Phase 6d-1 — apply the requested source mode (default: video).
        // A pending intent flowing in from a list page (e.g. Roster's
        // "Add observation" button) is honoured here; otherwise we
        // re-apply the last-active mode so a coach who switched modes
        // and navigated away returns to the same surface.
        const requested = this._coachReviewRequestedSource;
        const desired = requested || this._coachReviewSource || 'video';
        this._coachReviewRequestedSource = null;
        this._applyCoachReviewSource(desired);

        const pending = this._coachReviewPending || this._coachReview;
        if (pending?.matchId) {
            const matchSel = document.getElementById('coach-review-match');
            const slotSel = document.getElementById('coach-review-slot');
            if (matchSel) matchSel.value = pending.matchId;
            if (slotSel) slotSel.value = pending.slot || 'full';
            await this.loadCoachReviewVideo(pending.matchId, pending.slot || 'full', pending.seekTo || 0, pending.drawing || null);
            this._coachReviewPending = null;
        } else if (this._coachReviewSource === 'video') {
            const empty = document.getElementById('coach-review-empty');
            if (empty) empty.style.display = 'flex';
            await this.renderCoachReviewNotes(null);
        }
    },

    // ===== Phase 6d-1 — list-page creation routing =====
    //
    // Coach > Notes / Clips / Roster are management surfaces. Their
    // creation buttons route into Coach Review with an intent that
    // selects the right source mode (and any preselection).

    routeNewNote() {
        this._coachReviewIntent = { mode: 'video', intent: 'note' };
        this._coachReviewRequestedSource = 'video';
        this.setCoachTab('review');
    },

    /** Routed from Coach > Clips "+ New clip". Lands the coach in Video
     *  mode so they can scrub to the moment they want, then the existing
     *  Save Clip action opens the clip composer. If a video is already
     *  loaded in Review (from a prior session) we open the clip composer
     *  immediately so the click maps straight to the action. */
    routeNewClip() {
        this._coachReviewIntent = { mode: 'video', intent: 'clip' };
        this._coachReviewRequestedSource = 'video';
        this.setCoachTab('review');
        // If the Review tab already has a match loaded with metadata
        // ready, jump straight into the clip composer — the routing
        // intent is satisfied without another click.
        const review = this._coachReview;
        if (review?.matchId && review.metadataReady) {
            this.openClipComposerFromReview();
        }
    },

    /** Routed from Coach > Notes "+ New observation" and Coach > Roster
     *  "Add observation". `playerId` (optional) preselects that player
     *  in the side panel and defaults visibility to "player". */
    routeNewObservation({ playerId = null } = {}) {
        this._coachReviewIntent = { mode: 'tactical_board', intent: 'observation', playerId };
        this._coachReviewRequestedSource = 'tactical_board';
        this.setCoachTab('review');
    },

    // TODO(PR-FE 12a): Phase 6d-1 source-toggle, tactical-board
    // canvas mounter, TB observation save, focus mode + drawer,
    // and Coach Review keyboard shortcuts moved to
    // js/coaching/review.js.

    tearDownCoachReview() {
        this._stopFeedbackHeartbeat();
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            video.pause();
            video.removeAttribute('src');
            video.load();
        }
        this.deactivateCoachCanvas();
        this.clearCoachDrawing();
        this._coachReview = null;
        // Phase 6d-1 — tear down the tactical board controller so a
        // re-entry into Review starts from a clean state.
        this._unmountCoachReviewBoard();
        // Phase 6d-1 — clear the body source-mode mirror so other
        // surfaces don't accidentally inherit it. The data-attribute
        // is recreated next time the user enters Coach Review.
        delete document.body.dataset.coachReviewSource;
        // Phase 4c (issue #100): the Save-Clip button reads
        // `_coachReview.metadataReady`; with the session cleared the
        // refresh helper picks the disabled state, which is the
        // correct UX for "no match loaded".
        this._refreshCoachReviewSaveClipState();
        // Sprint 2: reset the top-bar time readout so it doesn't show a
        // stale clock when the user reopens Review later.
        const timeEl = document.getElementById('coach-review-time');
        if (timeEl) timeEl.textContent = '--:--';
        // Sprint 4: same invariant for the form's Save-at-MM:SS button.
        const saveFormBtn = document.getElementById('coach-review-save-form');
        if (saveFormBtn) saveFormBtn.textContent = 'Save at --:--';
        // Sprint 5: drop active timeline-chip selection so it doesn't carry
        // over into a different match's notes on next entry.
        this._coachActiveNoteId = null;
        // Phase 2: drop the active-template tracker so a coach who applied
        // a template, navigated away, and comes back doesn't trip the
        // overwrite-protection logic on a fresh, visually-empty composer.
        // Without this reset, _refreshCoachTemplateButtons() would render
        // the Clear button enabled (because canClear = !!selected ||
        // !!active), and the next applyCoachTemplate() would compare the
        // freshly-seeded defaults (category='shape', tone='correction')
        // against the stale previous template's values, treating those
        // defaults as "manually edited" and prompting "Replace your edits?"
        // when nothing was actually edited.
        this._coachReviewActiveTemplateId = null;
        // Sprint 6: defense-in-depth — if focus mode somehow survived a
        // different code path (e.g. external API call to tearDownCoachReview),
        // make sure the listener + body class are cleaned up.
        this.exitCoachFocusMode();
        // Sprint 7: defense-in-depth — if a caller invokes tearDownCoachReview
        // without going through setCoachTab() (which already toggles install/
        // uninstall in lockstep), make sure the global keydown listener is
        // also removed. Safe to call when no handler is installed.
        this.uninstallCoachReviewShortcuts();
    },

    _renderCoachReviewTime(video) {
        const el = document.getElementById('coach-review-time');
        const formBtn = document.getElementById('coach-review-save-form');
        const t = Number(video?.currentTime || 0);
        let display = '--:--';
        if (Number.isFinite(t) && t >= 0) {
            const hh = Math.floor(t / 3600);
            const mm = Math.floor((t % 3600) / 60);
            const ss = Math.floor(t % 60);
            const pad = (n) => String(n).padStart(2, '0');
            display = hh > 0 ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
        }
        if (el) el.textContent = display;
        // Sprint 4: the form's Save button now reads `Save at MM:SS` so the
        // coach can see the exact timestamp the note will land on without
        // glancing up at the top bar.
        if (formBtn) formBtn.textContent = `Save at ${display}`;
    },

    handleCoachReviewMatchChange() {
        const matchId = document.getElementById('coach-review-match')?.value;
        const slot = document.getElementById('coach-review-slot')?.value || 'full';
        // Sprint 5: clear any selected timeline chip when switching matches.
        this._coachActiveNoteId = null;
        // Phase 2: a template applied for the previous match no longer
        // describes the new match's moment. Reset the tracker AND the
        // selector + buttons so the composer starts fresh.
        this._resetCoachReviewTemplateState();
        if (!matchId) { this.tearDownCoachReview(); this.renderCoachReviewNotes(null); return; }
        this.loadCoachReviewVideo(matchId, slot, 0, null);
    },

    handleCoachReviewSlotChange() {
        const matchId = document.getElementById('coach-review-match')?.value;
        const slot = document.getElementById('coach-review-slot')?.value || 'full';
        // Sprint 5: clear active chip when slot changes (the active note may
        // belong to a different slot of the same match).
        this._coachActiveNoteId = null;
        // Phase 2: same reasoning as match-change — different slot = new
        // moment, so the previously-applied template is no longer relevant.
        this._resetCoachReviewTemplateState();
        if (!matchId) return;
        this.loadCoachReviewVideo(matchId, slot, 0, null);
    },

    async loadCoachReviewVideo(matchId, slot, seekTo = 0, drawing = null) {
        const video = document.getElementById(this._coachVideoId);
        const empty = document.getElementById('coach-review-empty');
        if (!video) return;
        if (empty) empty.style.display = 'none';
        // Phase 4c (issue #100): start every fresh load with
        // `metadataReady = false` so the Save-Clip button reflects
        // the loading state (no `currentTime` / `duration` yet).
        // The `loadedmetadata` listener flips it true once the
        // browser knows the video's dimensions + duration.
        this._coachReview = { matchId, slot, metadataReady: false };
        this._refreshCoachReviewSaveClipState();

        const { hlsUrl, mp4Url } = this.getStreamUrls(matchId, slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            if (seekTo > 0) video.currentTime = seekTo;
            this.setupCoachCanvas();
            if (drawing) this.renderCoachDrawing(drawing);
            // Phase 4c (issue #100): metadata is now available.
            // `_coachReview` may have been replaced by a different
            // match load while we were waiting — only flip the flag
            // if the active session is still ours.
            if (this._coachReview && this._coachReview.matchId === matchId && this._coachReview.slot === slot) {
                this._coachReview.metadataReady = true;
                this._refreshCoachReviewSaveClipState();
            }
        };
        video.addEventListener('loadedmetadata', onLoaded);

        // Sprint 2: drive the compact top-bar time readout from the video's
        // timeupdate event. Bound once per video element; subsequent
        // loadCoachReviewVideo calls re-use the same listener.
        if (!video._coachReviewTimeBound) {
            video.addEventListener('timeupdate', () => this._renderCoachReviewTime(video));
            video.addEventListener('seeked', () => this._renderCoachReviewTime(video));
            video.addEventListener('loadedmetadata', () => this._renderCoachReviewTime(video));
            video._coachReviewTimeBound = true;
        }
        this._renderCoachReviewTime(video);
        // Keep the VOD session warm: the streams registry reaps idle sessions
        // after 15 s and admin "kill" only propagates to active heartbeaters.
        this._startFeedbackHeartbeat(matchId, slot, video);

        const url = this._coachUrl('review', matchId, slot);
        this.pushHistoryState({ view: 'coach', tab: 'review', matchId, slot }, { replace: true, url });

        await this.renderCoachReviewNotes(matchId);
    },

    async renderCoachReviewNotes(matchId) {
        // Sprint 5: render notes for the current match as a horizontal
        // chip rail under the video instead of stacked button rows in the
        // right inspector. Each chip shows MM:SS · jersey/team indicator
        // · category dot · short title; clicking still goes through
        // seekCoachReviewNote so the existing seek + drawing-restore flow
        // is unchanged. The rail itself horizontally scrolls (themed
        // scrollbar in styles.css) so a match with 30+ notes doesn't
        // stretch the page vertically.
        const container = document.getElementById('coach-review-notes');
        if (!container) return;
        if (!matchId) {
            container.setAttribute('aria-label', 'Notes timeline (no match selected)');
            container.innerHTML = '<div class="coach-timeline-empty">Select a match to see its notes.</div>';
            return;
        }
        // Sprint 5: keep the rail's aria-label in sync with the active
        // match so screen readers announce which match's notes the user
        // is navigating, instead of the static "Notes for this match".
        const matchName = this.matchLabel(matchId);
        container.setAttribute('aria-label', `Notes for ${matchName}`);
        const allNotes = this._coachBundle?.notes || [];
        const notes = allNotes
            .filter((n) => n.match_id === matchId)
            // Sort by timestamp so the rail reads left-to-right in match order.
            .slice()
            .sort((a, b) => Number(a.timestamp_seconds || 0) - Number(b.timestamp_seconds || 0));
        if (!notes.length) {
            container.innerHTML = '<div class="coach-timeline-empty">No notes for this match yet — save your first one above.</div>';
            return;
        }
        const playersById = new Map();
        (this._coachBundle?.players || []).forEach((p) => playersById.set(String(p.id), p));
        const categoryLabel = Object.fromEntries(NOTE_CATEGORIES);
        container.innerHTML = notes.map((n) => {
            const ids = (n.player_ids || []).map(String);
            let playerIndicator = '';
            let playerAria = '';
            if (ids.length === 1) {
                const p = playersById.get(ids[0]);
                if (p?.jersey_number) {
                    playerIndicator = `#${this.esc(p.jersey_number)}`;
                    playerAria = `, player ${p.jersey_number}`;
                } else if (p?.display_name) {
                    playerIndicator = this.esc(p.display_name.split(' ')[0]);
                    playerAria = `, player ${p.display_name}`;
                }
            } else if (ids.length > 1) {
                playerIndicator = `+${ids.length}`;
                playerAria = `, ${ids.length} players`;
            } else {
                playerIndicator = 'Team';
                playerAria = ', team-wide';
            }
            const cat = String(n.category || 'other');
            const catTitle = this.esc(categoryLabel[cat] || cat);
            const active = this._coachActiveNoteId === Number(n.id);
            const ts = this.esc(this.formatClock(n.timestamp_seconds));
            const ariaLabel = `Jump to ${ts}${playerAria}, ${catTitle}: ${this.esc(n.title)}`;
            return `
                <button type="button"
                        class="coach-timeline-chip coach-timeline-chip--with-thumb ${active ? 'is-active' : ''}"
                        data-coach-note-id="${n.id}"
                        data-coach-category="${this.esc(cat)}"
                        title="${ariaLabel}"
                        aria-label="${ariaLabel}"
                        aria-pressed="${active ? 'true' : 'false'}"
                        onclick="app.seekCoachReviewNote(${n.id})">
                    ${this._coachNoteThumbHtml(n, { size: 'chip' })}
                    <span class="coach-timeline-chip-meta">
                        <span class="coach-timeline-chip-time">${ts}</span>
                        <span class="coach-timeline-chip-player">${playerIndicator}</span>
                        <span class="coach-timeline-chip-cat" aria-hidden="true" data-cat="${this.esc(cat)}"></span>
                        <span class="coach-timeline-chip-title">${this.esc(n.title)}</span>
                    </span>
                </button>
            `;
        }).join('');
        // Phase 3b: kick off thumbnail loads for every chip in one
        // pass. Each chip's tile is independent; failures are silent.
        this.mountCoachNoteThumbnailsIn(container);
    },

    seekCoachReviewNote(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        // Sprint 5: track which note is currently focused so the timeline
        // chip can render an active state. _setActiveCoachReviewNote handles
        // both the in-place class swap (no full re-render) and the
        // scroll-into-view nudge so the active chip is visible after a
        // long-rail seek.
        this._setActiveCoachReviewNote(Number(note.id));
        const review = this._coachReview;
        if (!review || review.matchId !== note.match_id || review.slot !== note.slot) {
            this.loadCoachReviewVideo(note.match_id, note.slot, Math.max(0, Number(note.timestamp_seconds || 0)), note.drawing || null);
            const matchSel = document.getElementById('coach-review-match');
            const slotSel = document.getElementById('coach-review-slot');
            if (matchSel) matchSel.value = note.match_id;
            if (slotSel) slotSel.value = note.slot;
            return;
        }
        const video = document.getElementById(this._coachVideoId);
        if (video) video.currentTime = Math.max(0, Number(note.timestamp_seconds || 0));
        this.renderCoachDrawing(note.drawing || {});
    },

    _setActiveCoachReviewNote(noteId) {
        this._coachActiveNoteId = noteId;
        const chips = document.querySelectorAll('#coach-review-notes .coach-timeline-chip');
        let activeChip = null;
        chips.forEach((chip) => {
            const active = Number(chip.dataset.coachNoteId) === noteId;
            chip.classList.toggle('is-active', active);
            chip.setAttribute('aria-pressed', active ? 'true' : 'false');
            if (active) activeChip = chip;
        });
        if (activeChip) {
            activeChip.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
        }
    },

    renderCoachReviewForm() {
        // Sprint 4: fast compact composer. Default state shows the four
        // fields a coach actually fills in every time — title, players,
        // category, and a Save-at-MM:SS primary button. PR 1b adds the
        // tone chip group (positive / correction / question / team /
        // goal — Phase 1 of the coaching analysis roadmap) right above
        // the Save button so the coach picks the tone with one tap.
        // Visibility, tags, the long-form body, and the new structured
        // coaching-point fields (`what_happened`, `why_it_matters`,
        // `what_to_do_next`, `player_summary`, `coach_private_note`)
        // collapse behind the existing <details class="coach-review-
        // advanced"> disclosure so the default state stays compact.
        // All existing element IDs are preserved. The payload shape
        // gains six fields (`note_type` + the five structured fields)
        // — `saveReviewNote()` sends them on EVERY save, using empty
        // strings when the coach left them blank, so a coach who
        // clears a previously-set field gets the empty string
        // persisted instead of the old value round-tripping silently.
        // The backend `CreateCoachingNoteRequest` already treats every
        // new field as optional with a safe default (`note_type` →
        // `'correction'`, all strings → `''`), so legacy clients that
        // don't send them keep working unchanged.
        const container = document.getElementById('coach-review-form');
        if (!container) return;
        const players = this._coachBundle?.players || [];
        // Phase 2: template selector. Static registry is grouped by
        // soccer area (Build-up, Defending, …) so the <optgroup> labels
        // double as a coach-friendly index. Picking a template only
        // arms it; the coach must press "Apply" to actually populate
        // fields. That preserves Option A overwrite-protection: a coach
        // who has typed something in a target field gets a confirm
        // prompt before the apply replaces their text.
        const templateOptionsHtml = COACH_TEMPLATE_GROUPS.map((group) => {
            const items = COACH_TEMPLATES.filter((t) => t.group === group);
            return `<optgroup label="${this.esc(group)}">${items.map((t) => `<option value="${this.esc(t.id)}">${this.esc(t.label)}</option>`).join('')}</optgroup>`;
        }).join('');
        container.innerHTML = `
            <div class="coach-review-template" role="group" aria-label="Coaching templates">
                <label class="coach-review-template-label" for="coach-review-template">Template</label>
                <select id="coach-review-template" aria-label="Coaching template">
                    <option value="">None — start from scratch</option>
                    ${templateOptionsHtml}
                </select>
                <button type="button" id="coach-review-template-apply" class="mini-action-btn" onclick="app.applyCoachTemplate()" disabled aria-disabled="true">Apply</button>
                <button type="button" id="coach-review-template-clear" class="mini-action-btn" onclick="app.clearCoachTemplate()" disabled aria-disabled="true" title="Clear the selected template (does not erase fields)">Clear</button>
            </div>
            <input type="text" id="coach-review-title" maxlength="160" placeholder="Title (e.g. Back line spacing)" aria-label="Note title">
            <div id="coach-review-players" class="coach-check-list compact" role="listbox" aria-label="Linked players">${this.coachCheckListHtml(players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet')}</div>
            <select id="coach-review-category" aria-label="Category">
                ${NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
            </select>
            <div id="coach-review-tone" class="coach-review-tone" role="radiogroup" aria-label="Note tone">
                ${NOTE_TYPES.map(([v, l, glyph]) => `
                    <button type="button" class="coach-review-tone-btn${v === DEFAULT_NOTE_TYPE ? ' is-active' : ''}" role="radio" aria-checked="${v === DEFAULT_NOTE_TYPE}" tabindex="${v === DEFAULT_NOTE_TYPE ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}" onclick="app.setCoachReviewNoteType('${v}')">
                        <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                        <span class="coach-review-tone-label">${this.esc(l)}</span>
                    </button>
                `).join('')}
            </div>
            ${this.renderCoachAIDraftPanel()}
            <button type="button" id="coach-review-save-form" class="btn-primary" onclick="app.saveReviewNote()">Save at --:--</button>
            <details class="coach-review-advanced">
                <summary>More details</summary>
                <div class="coach-review-advanced-body">
                    <label class="coach-review-field-label">
                        <span>Visibility</span>
                        <select id="coach-review-visibility" aria-label="Visibility" onchange="app.refreshCoachAIDraftControls()">
                            ${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                        </select>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Player summary <small>(visible to player/family)</small></span>
                        <textarea id="coach-review-player-summary" rows="2" maxlength="2000" placeholder="Short, age-appropriate version they'll read."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What happened</span>
                        <textarea id="coach-review-what-happened" rows="2" maxlength="2000" placeholder="The observation."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Why it matters</span>
                        <textarea id="coach-review-why-it-matters" rows="2" maxlength="2000" placeholder="The coaching context."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What to do next</span>
                        <textarea id="coach-review-what-to-do-next" rows="2" maxlength="2000" placeholder="The actionable next step."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Coach context (private)</span>
                        <textarea id="coach-review-coach-private-note" rows="2" maxlength="4000" placeholder="Internal — never sent to players or families."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Long notes</span>
                        <textarea id="coach-review-body" rows="3" maxlength="4000" placeholder="Anything that doesn't fit the structured fields above."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Tags</span>
                        <input type="text" id="coach-review-tags" maxlength="300" placeholder="tags,comma,separated">
                    </label>
                </div>
            </details>
        `;
        // Seed the tone group's dataset.value so it matches the visually
        // active default chip BEFORE the coach clicks anything. The
        // `saveReviewNote()` fallback handles `undefined` defensively
        // (`?.dataset.value || DEFAULT_NOTE_TYPE`), but seeding here
        // keeps the dataset structurally consistent with the Notes-tab
        // modal path (which seeds in openCoachNoteModal()) and avoids
        // landmines for any future reader that drops the fallback.
        const toneEl = document.getElementById('coach-review-tone');
        if (toneEl) {
            toneEl.dataset.value = DEFAULT_NOTE_TYPE;
            // Phase 4d (issue #77): wire WAI-ARIA-style keyboard
            // navigation. `_setupToneRadiogroup` is idempotent per-group
            // — a second `renderCoachReviewForm` call on the same DOM
            // re-applies the roving tabindex but doesn't double-bind
            // the keydown listener. Click selection still flows through
            // the inline `onclick="app.setCoachReviewNoteType(...)"`
            // attrs in the rendered markup; the keyboard path here
            // simply funnels through the same `_syncToneRadiogroup`.
            this._setupToneRadiogroup(toneEl);
        }
        // Phase 2: enable the Apply button only when a template is
        // selected. Listening on `change` here (vs. inline onchange in
        // the markup) keeps the selector markup simple — and the
        // listener is recreated every time `renderCoachReviewForm()`
        // re-runs because we replace `container.innerHTML`.
        const tplSelect = document.getElementById('coach-review-template');
        if (tplSelect) {
            tplSelect.addEventListener('change', () => this._refreshCoachTemplateButtons());
        }
        this._refreshCoachTemplateButtons();
        // Stamp the current timestamp onto the new Save button immediately.
        const v = document.getElementById(this._coachVideoId);
        if (v) this._renderCoachReviewTime(v);
    },

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

    /** Click handler for the tone-chip group. Toggles `is-active` /
     *  `aria-checked` so the chip layer behaves like a real radio
     *  group, and stashes the value on the container's dataset so
     *  `saveReviewNote()` can read it without a redundant DOM scan.
     *  Mouse / touch / inline `onclick` handlers all flow through
     *  here. The keyboard path also calls this — see
     *  `_setupToneRadiogroup` below. */
    setCoachReviewNoteType(value) {
        const group = document.getElementById('coach-review-tone');
        if (!group) return;
        this._syncToneRadiogroup(group, value);
    },

    // ===== Phase 4d (issue #77) — tone radiogroup keyboard a11y =====
    //
    // Two surfaces render a tone radiogroup with the same markup:
    //   1. Coach Review composer (`#coach-review-tone`)
    //   2. Notes-tab Edit modal (`[data-field="note_type"]` inside
    //      the cloned `coach-note-form-template`)
    //
    // The helpers below implement WAI-ARIA-style keyboard behavior
    // ONCE for both:
    //   - roving `tabindex` (only the active chip is in the tab order)
    //   - ArrowRight / ArrowDown → next; ArrowLeft / ArrowUp → previous
    //   - Home → first; End → last
    //   - Space / Enter → select the focused chip
    //   - selection changes flip `is-active`, `aria-checked`,
    //     `tabindex`, and the group's `dataset.value`
    //   - keyboard cycling inside the group does NOT scrub the
    //     Coach Review video (preserved via `_coachShortcutShouldSkip`)
    //
    // Mouse / touch / existing inline `onclick="app.setCoachReviewNoteType(...)"`
    // wiring is unchanged — both paths converge on
    // `_syncToneRadiogroup(group, value)`.

    /** Apply the roving-tabindex / aria-checked / is-active state for
     *  the requested value across all chips in the group. Does NOT
     *  move focus — callers that want to focus the new active chip
     *  pass `{ focusActive: true }`. Validates `value` against the
     *  static `NOTE_TYPES` whitelist; unknown values are ignored
     *  (keeps the dataset consistent with the backend enum). */
    _syncToneRadiogroup(group, value, { focusActive = false } = {}) {
        if (!group) return;
        if (!NOTE_TYPES.some(([v]) => v === value)) return;
        group.dataset.value = value;
        let activeBtn = null;
        group.querySelectorAll('.coach-review-tone-btn').forEach((btn) => {
            const active = btn.dataset.noteType === value;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-checked', active ? 'true' : 'false');
            // Roving tabindex: only the active chip stays in the tab
            // order. A keyboard user who Tabs into the group lands on
            // the current selection; arrow keys move WITHIN the group
            // without leaving it.
            btn.setAttribute('tabindex', active ? '0' : '-1');
            if (active) activeBtn = btn;
        });
        if (focusActive && activeBtn) {
            try { activeBtn.focus(); } catch { /* ignore */ }
        }
    },

    /** Wire keyboard handling on a tone radiogroup container. Idempotent
     *  per-group via a `data-tone-wired` marker so repeated calls
     *  (e.g. `renderCoachReviewForm` re-runs after an input change) do
     *  not stack listeners. Pass `onChange(value)` to be notified when
     *  the user picks a new tone — the helper itself only updates the
     *  DOM state via `_syncToneRadiogroup`; the caller decides what to
     *  do with the value (Coach Review composer ignores it; the
     *  Notes-tab modal stores it and reads on submit, but the dataset
     *  is the authoritative source).
     *
     *  Click handling already works via the inline `onclick=` attrs
     *  (Coach Review) or the per-button click listener (modal). The
     *  helper only ADDS keyboard handling — does not interfere with
     *  the existing click path. */
    _setupToneRadiogroup(group, onChange = null) {
        if (!group) return;
        // Idempotency guard: a second call against the same group is a
        // no-op except for re-applying the roving tabindex (caller may
        // have re-rendered chips inside).
        const initialValue = group.dataset.value
            || group.querySelector('.coach-review-tone-btn.is-active')?.dataset.noteType
            || DEFAULT_NOTE_TYPE;
        this._syncToneRadiogroup(group, initialValue);
        if (group.dataset.toneWired === '1') return;
        group.dataset.toneWired = '1';

        const select = (newValue, focusActive = true) => {
            this._syncToneRadiogroup(group, newValue, { focusActive });
            if (typeof onChange === 'function') onChange(newValue);
        };

        group.addEventListener('keydown', (event) => {
            const target = event.target;
            if (!target || !target.classList?.contains('coach-review-tone-btn')) return;
            const buttons = Array.from(group.querySelectorAll('.coach-review-tone-btn'))
                .filter((b) => !b.disabled && b.offsetParent !== null);
            if (!buttons.length) return;
            const currentIdx = buttons.indexOf(target);
            let nextIdx = currentIdx;
            switch (event.key) {
                case 'ArrowRight':
                case 'ArrowDown':
                    nextIdx = (currentIdx + 1) % buttons.length;
                    break;
                case 'ArrowLeft':
                case 'ArrowUp':
                    nextIdx = (currentIdx - 1 + buttons.length) % buttons.length;
                    break;
                case 'Home':
                    nextIdx = 0;
                    break;
                case 'End':
                    nextIdx = buttons.length - 1;
                    break;
                case ' ':
                case 'Enter':
                    // Space / Enter on a chip selects it. Most of the
                    // time the chip is already active (Tab landed on it
                    // via roving tabindex), so this is a no-op — but a
                    // user who Arrow-moved without selecting still
                    // benefits from explicit confirm.
                    event.preventDefault();
                    select(target.dataset.noteType, true);
                    return;
                default:
                    return;
            }
            event.preventDefault();
            // `_coachShortcutShouldSkip` already prevents the Coach
            // Review keydown handler from firing while focus is inside
            // the group (the `closest('[role="radiogroup"]')` test
            // handles both surfaces). Stop propagation here as a
            // belt-and-braces guard so any future keydown handler at a
            // higher scope also doesn't see these arrow events.
            event.stopPropagation();
            const next = buttons[nextIdx];
            select(next.dataset.noteType, true);
        });
    },

    // ===== Phase 2 — coaching templates =====

    /** Sync the Apply / Clear button enabled-state with the selector.
     *  Apply is enabled when a non-empty template id is selected.
     *  Clear is enabled when there is something to clear (selector has
     *  a value, OR a template was applied previously and is still
     *  tracked in `_coachReviewActiveTemplateId`). */
    _refreshCoachTemplateButtons() {
        const select = document.getElementById('coach-review-template');
        const apply = document.getElementById('coach-review-template-apply');
        const clear = document.getElementById('coach-review-template-clear');
        const selected = select?.value || '';
        const active = this._coachReviewActiveTemplateId || '';
        if (apply) {
            const canApply = !!selected;
            apply.disabled = !canApply;
            apply.setAttribute('aria-disabled', canApply ? 'false' : 'true');
        }
        if (clear) {
            const canClear = !!selected || !!active;
            clear.disabled = !canClear;
            clear.setAttribute('aria-disabled', canClear ? 'false' : 'true');
        }
    },

    /** Phase 2 — apply the currently-selected template to the
     *  composer. Per the spec's Option A: only fill empty fields.
     *  When at least one **text** field has content the coach typed
     *  themselves (i.e. content that does NOT match the previously-
     *  applied template's value for that field), ask for confirmation
     *  before overwriting. Drawing payload, timestamp, players,
     *  visibility, and `coach_private_note` are never touched.
     *
     *  Why text fields only: the category and tone start with a
     *  default option selected by the browser; treating those defaults
     *  as "edited" would prompt on a never-touched composer. We only
     *  count category/tone as edited when their value differs from BOTH
     *  the literal default AND the previous template (if any).
     *
     *  `requestedId` (optional) lets the caller force a specific
     *  template id; otherwise the currently-selected option wins. */
    async applyCoachTemplate(requestedId = null) {
        const select = document.getElementById('coach-review-template');
        const id = requestedId || select?.value || '';
        const tpl = findCoachTemplate(id);
        if (!tpl) return;

        const currentValues = this._readCoachReviewTemplateFields();
        const previousTplId = this._coachReviewActiveTemplateId;
        const previousTpl = findCoachTemplate(previousTplId);

        // Decide which fields would be overwritten. A field counts as
        // "manually edited" only if BOTH:
        //   1. it has content the coach can see (non-empty)
        //   2. that content was not what the previous template wrote
        // For category/tone we additionally require the value to differ
        // from the default — so a never-touched composer never prompts.
        const manuallyEdited = [];
        for (const [field, current] of Object.entries(currentValues)) {
            if (!current) continue;
            // Category and tone defaults: 'shape' is the first option
            // in NOTE_CATEGORIES; 'correction' is DEFAULT_NOTE_TYPE.
            // Treat those as untouched on a fresh composer.
            if (!previousTpl) {
                if (field === 'category' && current === 'shape') continue;
                if (field === 'note_type' && current === DEFAULT_NOTE_TYPE) continue;
            }
            let prev = previousTpl ? (previousTpl[field] ?? '') : '';
            if (field === 'tags' && Array.isArray(prev)) prev = prev.join(', ');
            if (current === prev) continue;
            manuallyEdited.push(field);
        }

        if (manuallyEdited.length) {
            const confirmed = await this.confirmAction({
                title: 'Replace your edits?',
                message: `The template "${tpl.label}" will overwrite ${manuallyEdited.length} field${manuallyEdited.length === 1 ? '' : 's'} you have already edited. Continue?`,
                confirmLabel: 'Replace',
                cancelLabel: 'Keep my edits',
                danger: false,
            });
            if (!confirmed) return;
        }

        this._writeCoachReviewTemplateFields(tpl);
        this._coachReviewActiveTemplateId = tpl.id;
        this._refreshCoachTemplateButtons();
    },

    /** Phase 2 — clear the template selector and forget the active
     *  template. Does NOT erase fields the coach has populated; that
     *  would be a surprise. To erase fields, the coach can switch the
     *  selector to "None — start from scratch" and re-pick a template. */
    clearCoachTemplate() {
        this._resetCoachReviewTemplateState();
    },

    /** Phase 2 — internal helper used by clearCoachTemplate(),
     *  handleCoachReviewMatchChange(), and handleCoachReviewSlotChange()
     *  to keep the visible UI and the JS tracker in lockstep. Resets
     *  the selector to "None — start from scratch", forgets the active
     *  template id, and drives Apply / Clear back to disabled. Like
     *  clearCoachTemplate, this never erases populated form fields —
     *  only the template state is reset. Safe to call when the
     *  composer is not currently mounted (the document.getElementById
     *  call returns null and the only side-effect is the JS field
     *  reset, which is what we want). */
    _resetCoachReviewTemplateState() {
        const select = document.getElementById('coach-review-template');
        if (select) select.value = '';
        this._coachReviewActiveTemplateId = null;
        this._refreshCoachTemplateButtons();
    },

    /** Read the current value of every field the templates can write,
     *  so `applyCoachTemplate()` can detect manual edits. Returns the
     *  raw values (default-vs-edited logic lives in the caller, which
     *  has full context about whether a previous template was applied). */
    _readCoachReviewTemplateFields() {
        const titleEl = document.getElementById('coach-review-title');
        const categoryEl = document.getElementById('coach-review-category');
        const toneEl = document.getElementById('coach-review-tone');
        const playerSummaryEl = document.getElementById('coach-review-player-summary');
        const whatHappenedEl = document.getElementById('coach-review-what-happened');
        const whyMattersEl = document.getElementById('coach-review-why-it-matters');
        const whatToDoNextEl = document.getElementById('coach-review-what-to-do-next');
        const tagsEl = document.getElementById('coach-review-tags');
        return {
            title:           (titleEl?.value || '').trim(),
            category:        (categoryEl?.value || ''),
            note_type:       (toneEl?.dataset.value || ''),
            player_summary:  (playerSummaryEl?.value || '').trim(),
            what_happened:   (whatHappenedEl?.value || '').trim(),
            why_it_matters:  (whyMattersEl?.value || '').trim(),
            what_to_do_next: (whatToDoNextEl?.value || '').trim(),
            tags:            (tagsEl?.value || '').trim(),
        };
    },

    /** Write a template's fields into the composer. Re-uses the
     *  existing `setCoachReviewNoteType()` so the tone chip group's
     *  dataset + aria stays consistent with manual selection. */
    _writeCoachReviewTemplateFields(tpl) {
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value || '';
        };
        set('coach-review-title', tpl.title);
        set('coach-review-player-summary', tpl.player_summary);
        set('coach-review-what-happened', tpl.what_happened);
        set('coach-review-why-it-matters', tpl.why_it_matters);
        set('coach-review-what-to-do-next', tpl.what_to_do_next);
        set('coach-review-tags', (tpl.tags || []).join(', '));
        // Category is a <select>; only set if the option exists.
        const categoryEl = document.getElementById('coach-review-category');
        if (categoryEl && tpl.category && Array.from(categoryEl.options).some((o) => o.value === tpl.category)) {
            categoryEl.value = tpl.category;
        }
        // Note type drives the tone chip group via its existing helper.
        if (tpl.note_type) this.setCoachReviewNoteType(tpl.note_type);
        // Open the More-details disclosure so the coach can see the
        // structured fields the template just populated. If the coach
        // closes it manually that choice persists across re-applies.
        const advanced = document.querySelector('.coach-review-advanced');
        if (advanced && !advanced.open) advanced.open = true;
    },

    async openNoteInReview(noteId) {
        const note = (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this._coachReviewPending = {
            matchId: note.match_id, slot: note.slot,
            seekTo: Math.max(0, Number(note.timestamp_seconds || 0)),
            drawing: note.drawing || null,
        };
        this.setCoachTab('review');
    },

    async saveReviewNote() {
        const review = this._coachReview;
        if (!review?.matchId) { this.showError('Pick a match in the Review tab first.'); return; }
        const video = document.getElementById(this._coachVideoId);
        const title = document.getElementById('coach-review-title')?.value.trim();
        if (!title) { this.showError('Add a title for the coaching note.'); return; }
        // Tone chip group — the active button stores its value on the
        // container's dataset (set by setCoachReviewNoteType). Falls
        // back to the default (`correction`) so a coach who never
        // touched the chips keeps the legacy implied behaviour.
        const noteType = document.getElementById('coach-review-tone')?.dataset.value || DEFAULT_NOTE_TYPE;
        const payload = {
            match_id: review.matchId,
            slot: review.slot || 'full',
            timestamp_seconds: video?.currentTime || 0,
            title,
            body: document.getElementById('coach-review-body')?.value.trim() || '',
            category: document.getElementById('coach-review-category')?.value || 'other',
            visibility: document.getElementById('coach-review-visibility')?.value || 'private',
            player_ids: Array.from(document.querySelectorAll('#coach-review-players .coach-check-option.is-selected')).map((b) => b.dataset.value),
            tags: (document.getElementById('coach-review-tags')?.value || '').split(',').map((s) => s.trim()).filter(Boolean),
            drawing: this._coachDrawing || {},
            // Phase 1 structured-note fields (PR 1a backend / PR 1b UI).
            // All optional with safe defaults at the backend; we send
            // them every time so a coach who clears them gets the
            // empty string persisted (rather than the previous value
            // round-tripping unchanged).
            note_type: noteType,
            what_happened: document.getElementById('coach-review-what-happened')?.value.trim() || '',
            why_it_matters: document.getElementById('coach-review-why-it-matters')?.value.trim() || '',
            what_to_do_next: document.getElementById('coach-review-what-to-do-next')?.value.trim() || '',
            player_summary: document.getElementById('coach-review-player-summary')?.value.trim() || '',
            coach_private_note: document.getElementById('coach-review-coach-private-note')?.value.trim() || '',
        };
        try {
            await this.createCoachNote(payload);
            this.showSuccess('Coaching note saved.');
            // Sprint 4: only clear fields the coach is unlikely to repeat
            // verbatim. Category, visibility, tone, and selected players
            // stay sticky so a coach reviewing one player can save
            // several notes in a row without re-tagging. Title, body,
            // tags, AND the per-moment structured fields are cleared
            // because each describes the specific moment.
            const PER_MOMENT_FIELDS = [
                'coach-review-title',
                'coach-review-body',
                'coach-review-tags',
                'coach-review-what-happened',
                'coach-review-why-it-matters',
                'coach-review-what-to-do-next',
                'coach-review-player-summary',
                'coach-review-coach-private-note',
            ];
            PER_MOMENT_FIELDS.forEach((id) => {
                const el = document.getElementById(id); if (el) el.value = '';
            });
            // Phase 2: reset the template selector so a fresh save starts
            // from "None — start from scratch". The active-template
            // tracker is cleared too so the next apply does not think
            // the just-cleared fields are "template-written".
            const tplSelect = document.getElementById('coach-review-template');
            if (tplSelect) tplSelect.value = '';
            this._coachReviewActiveTemplateId = null;
            this._refreshCoachTemplateButtons?.();
            this.clearCoachDrawing();
            this._coachBundle = await this.loadCoachBundle();
            await this.renderCoachReviewNotes(review.matchId);
        } catch (err) { this.showError(err.message); }
    },

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
