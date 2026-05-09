// Coaching workspace: roster, notes, playlists, in-/coach Review video player + telestrator,
// player-facing /feedback view with a focused feedback-player modal. The in-match side panel
// is intentionally absent — Coach > Review is the single authoring surface.

import { COACH_TEMPLATES, COACH_TEMPLATE_GROUPS, findCoachTemplate } from './coaching-templates.js';

const NOTE_CATEGORIES = [
    ['shape', 'Shape'], ['pressing', 'Pressing'], ['transition', 'Transition'],
    ['set_piece', 'Set piece'], ['build_up', 'Build-up'], ['finishing', 'Finishing'],
    ['defending', 'Defending'], ['goalkeeper', 'Goalkeeper'], ['effort', 'Effort'],
    ['decision', 'Decision'], ['other', 'Other'],
];

const VISIBILITY_OPTIONS = [
    ['private', 'Private'], ['team', 'Team-visible'],
    ['player', 'Player/family'], ['unlisted', 'Unlisted link'],
];

// Phase 1 structured-note tone (PR 1b). Mirrors the backend
// `_VALID_NOTE_TYPES` set in models.py — keep in sync. The default
// `correction` matches the column default in `coaching_notes` so
// existing UIs that don't send `note_type` keep behaving the same.
const NOTE_TYPES = [
    ['positive',        'Positive',        '+'],
    ['correction',      'Correction',      '↺'],
    ['question',        'Question',        '?'],
    ['team_concept',    'Team',            '⌬'],
    ['individual_goal', 'Goal',            '★'],
];
const DEFAULT_NOTE_TYPE = 'correction';

// PR 1c: My Feedback uses longer, more player-friendly labels for the
// tone (the Coach Review composer's chip labels above are clipped for
// the dense inspector). Same key set as `_VALID_NOTE_TYPES`.
const FEEDBACK_NOTE_TYPE_LABELS = {
    positive:        'Positive',
    correction:      'Correction',
    question:        'Question',
    team_concept:    'Team concept',
    individual_goal: 'Individual goal',
};

const VALID_COACH_TABS = ['roster', 'notes', 'playlists', 'clips', 'summaries', 'review'];
const VALID_FEEDBACK_TABS = ['playlists', 'notes', 'clips', 'summaries', 'development'];

const GOAL_STATUS_OPTIONS = [
    ['open', 'Open'], ['in_progress', 'In progress'], ['needs_follow_up', 'Needs follow-up'],
    ['achieved', 'Achieved'], ['archived', 'Archived'],
];
const ACTIVE_GOAL_STATUSES = new Set(['open', 'in_progress', 'needs_follow_up']);
const GOAL_CONTEXT_OPTIONS = [
    ['next_match', 'Next match'], ['next_training', 'Next training'], ['season_goal', 'Season goal'], ['other', 'Other'],
];
const GOAL_STATUS_LABELS = Object.fromEntries(GOAL_STATUS_OPTIONS);
const GOAL_CONTEXT_LABELS = Object.fromEntries(GOAL_CONTEXT_OPTIONS);
const GOAL_VISIBILITY_OPTIONS = [
    ['player', 'Player/family'], ['coach', 'Coach/admin only'],
];
const GOAL_PRIORITY_OPTIONS = [
    ['low', 'Low'], ['medium', 'Medium'], ['high', 'High'],
];
const GOAL_VISIBILITY_LABELS = Object.fromEntries(GOAL_VISIBILITY_OPTIONS);
const GOAL_PRIORITY_LABELS = Object.fromEntries(GOAL_PRIORITY_OPTIONS);

// Phase 4b: pre/post-roll defaults for the Coach Review "Save Clip"
// affordance. Match the existing playlist defaults so a coach who's
// used to playlist sessions sees the same windowing behavior on
// freshly-saved clips. Both can be overridden in the clip modal.
const COACH_CLIP_DEFAULT_PRE_ROLL = 5;
const COACH_CLIP_DEFAULT_POST_ROLL = 8;
// Phase 4a backend MVP cap (enforced by `models._MAX_CLIP_DURATION_SECONDS`).
// We mirror it client-side so the modal's Save button can short-circuit
// before the request hits the server.
const COACH_CLIP_MAX_DURATION_SECONDS = 120;

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
    _coachPlaylistSession: null,
    _coachPlaylistMonitor: null,
    _coachPlaylistFreezeTimer: null,
    _coachTab: 'roster',
    _feedbackTab: 'playlists',
    // Phase 5b: sticky linked-player selection inside the My Feedback
    // Development sub-tab. Reset by `setLoggedOut()` so it cannot leak
    // across users — the in-render guard in `renderFeedbackDevelopment`
    // is a second line of defense for stale state during a single
    // session (e.g. a coach unlinking a player via the Roster tab).
    _feedbackDevPlayerId: null,
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
        if (name === 'review') this.renderCoachReview();
        else this.tearDownCoachReview();
    },

    setFeedbackTab(name, { pushHistory = true } = {}) {
        if (!VALID_FEEDBACK_TABS.includes(name)) name = 'playlists';
        this._feedbackTab = name;
        document.querySelectorAll('[data-feedback-tab]').forEach((btn) => {
            const active = btn.dataset.feedbackTab === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        VALID_FEEDBACK_TABS.forEach((tab) => {
            const panel = document.getElementById(`feedback-tab-${tab}`);
            if (panel) panel.hidden = tab !== name;
        });
        if (pushHistory) {
            const url = `/feedback?tab=${name}`;
            this.pushHistoryState({ view: 'feedback', tab: name }, { replace: true, url });
        }
        if (name === 'summaries') this.renderFeedbackMatchSummaries(this._feedbackData || {});
        if (name === 'development') this.renderFeedbackDevelopment();
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

    // ===== Roster sub-tab =====

    /** Compute the KPI numbers shown in the four header tiles. All
     *  derived from `_coachBundle` so no extra fetch is needed. Any
     *  metric that can't be calculated falls back to '0' / '—'. */
    _coachRosterKpis() {
        const players = this._coachBundle?.players || [];
        const notes = this._coachBundle?.notes || [];
        const activePlayers = players.filter((p) => p.active);
        const totalLinks = players.reduce((sum, p) => sum + (p.links?.length || 0), 0);
        const linkedThisWeek = (() => {
            const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
            let n = 0;
            for (const p of players) for (const l of (p.links || [])) {
                const t = l.created_at ? Date.parse(l.created_at) : NaN;
                if (Number.isFinite(t) && t >= cutoff) n++;
            }
            return n;
        })();
        const withoutLink = activePlayers.filter((p) => !(p.links?.length)).length;
        const notesPerPlayer = (() => {
            if (!activePlayers.length) return null;
            // Tally how many notes mention each active player. A note can
            // reference multiple players via player_ids; team-level notes
            // (no player_ids) are not attributed to anyone.
            let total = 0;
            const activeIds = new Set(activePlayers.map((p) => String(p.id)));
            for (const n of notes) {
                for (const pid of (n.player_ids || [])) {
                    if (activeIds.has(String(pid))) total++;
                }
            }
            return total / activePlayers.length;
        })();
        return {
            activePlayers: activePlayers.length,
            linkedAccounts: totalLinks,
            linkedAccountsDelta: linkedThisWeek,
            withoutLink,
            notesPerPlayer,
        };
    },

    _renderCoachRosterKpis() {
        const target = document.getElementById('coach-roster-kpis');
        if (!target) return;
        const k = this._coachRosterKpis();
        const fmtAvg = (v) => (v == null) ? '—' : (Math.round(v * 10) / 10).toFixed(1);
        target.innerHTML = `
            <div class="roster-kpi">
                <span class="roster-kpi-label">Active Players</span>
                <strong class="roster-kpi-value">${k.activePlayers}</strong>
            </div>
            <div class="roster-kpi">
                <span class="roster-kpi-label">Linked Accounts</span>
                <strong class="roster-kpi-value">${k.linkedAccounts}</strong>
                ${k.linkedAccountsDelta ? `<span class="roster-kpi-delta">+${k.linkedAccountsDelta} this week</span>` : ''}
            </div>
            <div class="roster-kpi">
                <span class="roster-kpi-label">Without Family Link</span>
                <strong class="roster-kpi-value">${k.withoutLink}</strong>
            </div>
            <div class="roster-kpi">
                <span class="roster-kpi-label">Avg. Notes / Player</span>
                <strong class="roster-kpi-value">${fmtAvg(k.notesPerPlayer)}</strong>
            </div>
        `;
    },

    /** Apply the search query + status filter to the roster, returning
     *  a fresh array. Never mutates `_coachBundle`. */
    _filteredCoachPlayers() {
        const players = this._coachBundle?.players || [];
        const q = (this._coachRosterSearch || '').trim().toLowerCase();
        const filter = this._coachRosterFilter || 'all';
        return players.filter((p) => {
            if (filter === 'active' && !p.active) return false;
            if (filter === 'inactive' && p.active) return false;
            if (!q) return true;
            // Match name, jersey number, notes (used as freeform position
            // / role hint), and any linked username / display name.
            const haystack = [
                p.display_name || '',
                p.jersey_number || '',
                p.notes || '',
                ...(p.links || []).flatMap((l) => [l.username || '', l.display_name || '']),
            ].join(' ').toLowerCase();
            return haystack.includes(q);
        });
    },

    handleCoachRosterSearch(value) {
        this._coachRosterSearch = value || '';
        this.renderCoachRoster();
    },

    setCoachRosterFilter(name) {
        this._coachRosterFilter = name;
        document.querySelectorAll('.roster-filter-btn').forEach((btn) => {
            const active = btn.dataset.rosterFilter === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        this.renderCoachRoster();
    },

    focusCoachQuickAdd() {
        const input = document.getElementById('coach-player-name');
        if (input) { input.focus(); input.select?.(); }
    },

    renderCoachRoster() {
        // KPIs always reflect the full bundle (not the filtered view).
        this._renderCoachRosterKpis();

        const container = document.getElementById('coach-roster-list');
        if (!container) return;
        const players = this._coachBundle?.players || [];
        const filtered = this._filteredCoachPlayers();

        // Empty states — distinguish "no players at all" from "filter
        // matched nothing" so the user knows whether to clear search.
        if (!players.length) {
            container.innerHTML = `
                <tr class="roster-empty-row"><td colspan="5">
                    <div class="session-empty">No roster players yet. Use <strong>Quick Add Player</strong> to add the first one.</div>
                </td></tr>`;
            return;
        }
        if (!filtered.length) {
            container.innerHTML = `
                <tr class="roster-empty-row"><td colspan="5">
                    <div class="session-empty">No players match your search or filter. <button type="button" class="mini-action-btn" onclick="app.handleCoachRosterSearch(''); document.getElementById('coach-roster-search').value=''; app.setCoachRosterFilter('all');">Clear filters</button></div>
                </td></tr>`;
            return;
        }

        container.innerHTML = filtered.map((p) => {
            const links = p.links || [];
            const linkChips = links.length
                ? links.map((l) => `
                    <button type="button" class="roster-link-chip" title="Unlink @${this.esc(l.username)} (${this.esc(l.relationship)})" onclick="app.handleCoachUnlink(${l.id})">
                        <span class="roster-link-rel">${this.esc(l.relationship)}</span>
                        <span class="roster-link-user">@${this.esc(l.username)}</span>
                        <span class="roster-link-x" aria-hidden="true">×</span>
                    </button>
                `).join('')
                : '<span class="roster-no-links">No links</span>';
            const subtitle = (p.notes && p.notes.trim()) ? this.esc(p.notes.trim()) : '';
            const jerseyBadge = p.jersey_number
                ? `<span class="roster-jersey-badge">${this.esc(p.jersey_number)}</span>`
                : '<span class="roster-jersey-badge is-muted">—</span>';
            const statusPill = p.active
                ? '<span class="roster-status-pill is-active"><span class="roster-status-dot" aria-hidden="true"></span>Active</span>'
                : '<span class="roster-status-pill is-inactive"><span class="roster-status-dot" aria-hidden="true"></span>Inactive</span>';
            // Player IDs are UUIDs (strings). `JSON.stringify` produces a
            // value wrapped in double-quotes (e.g. `"abc-123"`), which
            // — interpolated into a double-quoted `onclick=""` HTML
            // attribute — terminates the attribute prematurely and
            // breaks the click handler. HTML-escape the inner double
            // quotes so the attribute value stays intact; the browser
            // un-escapes them before parsing the JS.
            const playerIdJs = JSON.stringify(String(p.id)).replace(/"/g, '&quot;');
            return `
            <tr class="roster-row">
                <td class="roster-cell roster-col-num">${jerseyBadge}</td>
                <td class="roster-cell roster-col-player">
                    <strong class="roster-player-name">${this.esc(p.display_name)}</strong>
                    ${subtitle ? `<span class="roster-player-sub">${subtitle}</span>` : ''}
                </td>
                <td class="roster-cell roster-col-links">${linkChips}</td>
                <td class="roster-cell roster-col-status">${statusPill}</td>
                <td class="roster-cell roster-col-actions">
                    <div class="roster-actions-row">
                        <button type="button" class="mini-action-btn mini-action-btn-icon" title="Add observation note" aria-label="Add observation note" onclick="app.routeNewObservation({ playerId: ${playerIdJs} })">
                            ${this._rosterIcon('observation')}
                        </button>
                        <button type="button" class="mini-action-btn mini-action-btn-icon" title="View development profile" aria-label="View development profile" onclick="app.openCoachPlayerDevelopmentModal(${playerIdJs})">
                            ${this._rosterIcon('chart')}
                        </button>
                        <button type="button" class="mini-action-btn mini-action-btn-icon" title="Create player goal" aria-label="Create player goal" onclick="app.openCoachGoalModal({ playerId: ${playerIdJs} })">
                            ${this._rosterIcon('goal')}
                        </button>
                        <button type="button" class="mini-action-btn mini-action-btn-icon" title="Link a family or player account" aria-label="Link account" onclick="app.openCoachLinkModal(${playerIdJs})">
                            ${this._rosterIcon('link')}
                        </button>
                        <button type="button" class="mini-action-btn mini-action-btn-icon" title="Edit player" aria-label="Edit player" onclick="app.openCoachPlayerEditModal(${playerIdJs})">
                            ${this._rosterIcon('edit')}
                        </button>
                        <button type="button" class="mini-action-btn mini-action-btn-icon is-danger" title="Delete player" aria-label="Delete player" onclick="app.handleCoachDeletePlayer(${playerIdJs})">
                            ${this._rosterIcon('trash')}
                        </button>
                    </div>
                </td>
            </tr>`;
        }).join('');
    },

    /** Inline-SVG icon set for the Roster table action buttons.
     *  Same `stroke="currentColor"` pattern as the Sprint 3 telestrator
     *  toolbar, so the icon inherits the button's text colour and the
     *  dark / light theme handle hover/focus states automatically. */
    _rosterIcon(name) {
        const SVG = (paths) => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths.map((d) => `<path d="${d}"/>`).join('')}</svg>`;
        if (name === 'link') {
            // Two interlocked chain links.
            return SVG([
                'M9 14l-2 2a4 4 0 01-5.7-5.7l3-3a4 4 0 015.7 0',
                'M15 10l2-2a4 4 0 015.7 5.7l-3 3a4 4 0 01-5.7 0',
            ]);
        }
        if (name === 'edit') {
            // Pencil over a square — classic edit glyph.
            return SVG([
                'M4 20h4l10-10-4-4L4 16v4z',
                'M14 6l4 4',
            ]);
        }
        if (name === 'trash') {
            // Trash can with lid + handle + two vertical bars.
            return SVG([
                'M3 6h18',
                'M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2',
                'M6 6l1 14a2 2 0 002 2h6a2 2 0 002-2l1-14',
                'M10 11v6',
                'M14 11v6',
            ]);
        }
        if (name === 'search') {
            // Magnifying glass.
            return SVG([
                'M11 19a8 8 0 100-16 8 8 0 000 16z',
                'M21 21l-4.35-4.35',
            ]);
        }
        if (name === 'chart') {
            // Bar-chart glyph for the "View development profile" action.
            return SVG([
                'M3 3v18h18',
                'M7 14v4',
                'M12 9v9',
                'M17 5v13',
            ]);
        }
        if (name === 'observation') {
            // Phase 6b — clipboard glyph for the "Add observation" action.
            // Clipboard hints "written observation, no video required".
            return SVG([
                'M9 4h6a1 1 0 011 1v2H8V5a1 1 0 011-1z',
                'M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V9a2 2 0 00-2-2h-2',
                'M9 13h6',
                'M9 17h4',
            ]);
        }
        if (name === 'goal') {
            return SVG([
                'M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8L12 17.1 5.9 20.6l1.4-6.8-5.1-4.7 6.9-.8L12 2z',
            ]);
        }
        return '';
    },

    async handleCoachAddPlayer() {
        const display_name = document.getElementById('coach-player-name')?.value.trim();
        const jersey_number = document.getElementById('coach-player-number')?.value.trim() || '';
        // Position is UI-only for now (no backend column). If a coach picks
        // one we stash it in the local `notes` field so the "Player" cell's
        // subtitle can surface it. If the backend grows a real `position`
        // column later we'll switch to that without changing the UI.
        const positionEl = document.getElementById('coach-player-position');
        const position = positionEl?.value || '';
        const linkUserEl = document.getElementById('coach-link-user-quickadd');
        const linkUserId = linkUserEl?.value || '';

        if (!display_name) { this.showError('Player name is required.'); return; }
        try {
            const created = await this.createCoachPlayer({
                display_name,
                jersey_number,
                active: true,
                notes: position || '',
            });
            // Optional: link the chosen user account to the new player.
            if (linkUserId && created?.id) {
                try {
                    await this.linkCoachPlayer({ player_id: created.id, user_id: linkUserId, relationship: 'family' });
                } catch (err) {
                    this.showError(`Player added but link failed: ${err.message}`);
                }
            }
            // Reset the quick-add fields.
            document.getElementById('coach-player-name').value = '';
            document.getElementById('coach-player-number').value = '';
            if (positionEl) positionEl.value = '';
            if (linkUserEl) linkUserEl.value = '';
            this.showSuccess('Player added.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeletePlayer(playerId) {
        const ok = await this.confirmAction({
            title: 'Delete player',
            message: 'Delete this roster player and remove their feedback links?',
            confirmLabel: 'Delete player', danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(`/api/coach/players/${playerId}`, {
                method: 'DELETE', headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to delete player');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    /** Open the standalone Link Account modal. If `prefillPlayerId` is
     *  given (e.g. from the row icon button), the player select starts
     *  on that player. */
    async openCoachLinkModal(prefillPlayerId = null) {
        const tpl = document.getElementById('coach-link-modal-template');
        if (!tpl) { this.showError('Link Account form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);
        const opts = this._coachLinkSelectorOptionsHtml();
        body.querySelector('#coach-link-player').innerHTML = opts.playerOptions;
        body.querySelector('#coach-link-user').innerHTML = opts.userOptions;
        if (prefillPlayerId) {
            const sel = body.querySelector('#coach-link-player');
            if (sel) sel.value = String(prefillPlayerId);
        }
        const result = await this.formModal({
            title: 'Link Account',
            body,
            confirmLabel: 'Link',
            onSubmit: (close) => {
                const player_id = body.querySelector('#coach-link-player').value;
                const user_id = body.querySelector('#coach-link-user').value;
                const relationship = body.querySelector('#coach-link-relationship').value || 'family';
                if (!player_id || !user_id) {
                    this.showError('Pick a player and a user account.');
                    return;
                }
                close({ player_id, user_id, relationship });
            },
        });
        if (!result) return;
        try {
            await this.linkCoachPlayer(result);
            this.showSuccess('Account linked.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    /** Kept for back-compat with any external caller / inline binding —
     *  if a legacy form somewhere posts here, route through the modal. */
    async handleCoachLinkAccount() {
        return this.openCoachLinkModal();
    },

    /** Open the Edit Player modal for the given roster player. Posts to
     *  the existing `PATCH /api/coach/players/{id}` endpoint via
     *  `updateCoachPlayer()`. The "Position" select is UI-only and is
     *  persisted via the existing `notes` column (same pattern as the
     *  Quick Add panel — see CreatePlayerRequest comment in models.py). */
    async openCoachPlayerEditModal(playerId) {
        const player = (this._coachBundle?.players || []).find((p) => String(p.id) === String(playerId));
        if (!player) { this.showError('Player not found.'); return; }
        const tpl = document.getElementById('coach-player-edit-template');
        if (!tpl) { this.showError('Edit Player form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        body.querySelector('[data-field="display_name"]').value = player.display_name || '';
        body.querySelector('[data-field="jersey_number"]').value = player.jersey_number || '';
        body.querySelector('[data-field="active"]').checked = !!player.active;

        // Position is stored in the `notes` column today. If the value
        // matches one of the known position options, pre-select it;
        // otherwise leave the select blank so we don't accidentally
        // truncate a free-text note when the coach saves.
        const positionSel = body.querySelector('[data-field="position"]');
        const knownPositions = Array.from(positionSel.options).map((o) => o.value).filter(Boolean);
        const currentNotes = (player.notes || '').trim();
        if (knownPositions.includes(currentNotes)) {
            positionSel.value = currentNotes;
            positionSel.dataset.original = currentNotes;
        } else {
            positionSel.value = '';
            // Stash whatever was in `notes` so we can preserve it on save.
            positionSel.dataset.preservedNotes = currentNotes;
            positionSel.dataset.original = '';
        }

        const result = await this.formModal({
            title: 'Edit Player',
            body,
            confirmLabel: 'Save changes',
            onSubmit: (close) => {
                const display_name = body.querySelector('[data-field="display_name"]').value.trim();
                const jersey_number = body.querySelector('[data-field="jersey_number"]').value.trim();
                const active = body.querySelector('[data-field="active"]').checked;
                const newPosition = positionSel.value;
                if (!display_name) { this.showError('Display name is required.'); return; }
                // If the original `notes` was a known position, the
                // select-driven value is the source of truth. If it
                // was free-text we left untouched, only overwrite when
                // the coach picked a real position; otherwise preserve
                // the original free-text notes.
                const notes = newPosition || (positionSel.dataset.preservedNotes ?? '');
                close({ display_name, jersey_number, active, notes });
            },
        });
        if (!result) return;
        try {
            await this.updateCoachPlayer(player.id, result);
            this.showSuccess('Player updated.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachUnlink(linkId) {
        try {
            await this.unlinkCoachPlayer(linkId);
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    // ===== Notes sub-tab =====

    renderCoachNotes() {
        const container = document.getElementById('coach-notes-list');
        if (!container) return;
        const notes = this._coachBundle?.notes || [];
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes yet. Click <strong>+ New note</strong> or <strong>+ New observation</strong> to add the first one.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => {
            const isObservation = (n.note_context || 'video') === 'observation';
            const titleText = (n.title || '').trim() || (isObservation
                ? ((n.event_title || '').trim() || 'Observation note')
                : '(untitled)');
            const contextPill = isObservation
                ? '<span class="coach-row-context-pill" data-context="observation">Observation</span>'
                : '<span class="coach-row-context-pill" data-context="video">Video</span>';
            // Meta line — observation notes show event metadata
            // (event type / event title / event date) instead of
            // match/timestamp/slot, so the row never shows
            // "undefined" / "0:00" / "Full" for fields that don't apply.
            const metaParts = [];
            if (isObservation) {
                if (n.event_type) {
                    const typeLabel = `${n.event_type[0].toUpperCase()}${n.event_type.slice(1)}`;
                    metaParts.push(`${typeLabel} observation`);
                } else {
                    metaParts.push('Observation');
                }
                if (n.event_title && n.event_title !== titleText) metaParts.push(n.event_title);
                if (n.event_date) metaParts.push(n.event_date);
            } else {
                metaParts.push(this.matchLabel(n.match_id));
                metaParts.push(this.formatClock(n.timestamp_seconds));
                metaParts.push(this.slotLabel(n.slot));
            }
            if (n.category) metaParts.push(n.category);
            if (n.visibility) metaParts.push(n.visibility);
            const metaLine = metaParts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
            // Observation notes have no video frame to seek into,
            // so the "Open in Review" + "Regenerate thumbnail"
            // actions are suppressed. Edit + Delete still apply.
            const actions = isObservation
                ? `
                    ${n.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(n.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_note_id: ${Number(n.id)}, title: ${JSON.stringify(titleText).replace(/"/g, '&quot;')}, description: ${JSON.stringify(n.what_to_do_next || n.player_summary || n.body || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(titleText).replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachObservationModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                `
                : `
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openNoteInReview(${n.id})">Open in Review</button>
                    ${n.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(n.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_note_id: ${Number(n.id)}, title: ${JSON.stringify(titleText).replace(/"/g, '&quot;')}, description: ${JSON.stringify(n.what_to_do_next || n.player_summary || n.body || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(titleText).replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn" onclick="app.openCoachNoteModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleRegenCoachThumb(${n.id})" title="Regenerate thumbnail" aria-label="Regenerate thumbnail">↻</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                `;
            // Observation notes get a film-strip placeholder tile so
            // the row stays visually aligned without firing a 404
            // network request — `_coachNoteThumbHtml` is video-only.
            // Phase 6c: when an observation carries a tactical board
            // we render a compact SVG preview tile instead of the
            // clipboard glyph so the coach sees the sketch at-a-glance.
            const hasBoard = isObservation && this.tacticalBoardHasContent(n.tactical_board_json);
            const thumb = isObservation
                ? (hasBoard
                    ? `<div class="coach-thumb coach-thumb--list coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(n.tactical_board_json, { size: 'chip' })}</div>`
                    : '<div class="coach-thumb coach-thumb--list coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
                : this._coachNoteThumbHtml(n, { size: 'list' });
            // Board indicator pill in the header so the row reads
            // "Observation · ⌬ Tactical board" even when the
            // thumbnail tile is visible.
            const boardPill = hasBoard
                ? '<span class="coach-row-board-pill" title="Tactical board attached">⌬ Board</span>'
                : '';
            return `
            <article class="coach-row coach-row-with-thumb" data-note-context="${isObservation ? 'observation' : 'video'}">
                ${thumb}
                <div class="coach-row-body">
                    <div class="coach-row-head">
                        ${contextPill}
                        ${boardPill}
                        <strong>${this.esc(titleText)}</strong>
                    </div>
                    <span>${metaLine}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    ${actions}
                </div>
            </article>
        `;
        }).join('');
        // Phase 3b: kick off a single batch of authenticated thumbnail
        // fetches now that the placeholders are in the DOM. Failures are
        // silent — placeholder stays visible. Observation rows skip
        // this entirely (they use a static placeholder, no
        // `data-coach-note-thumb` attribute).
        this.mountCoachNoteThumbnailsIn(container);
    },

    /** Phase 3b — render the thumbnail tile for a coaching note. The
     *  tile starts with a CSS placeholder background; the real JPEG is
     *  swapped in by `mountCoachNoteThumbnailsIn()` after auth-fetch.
     *
     *  Variants:
     *    `list`  — Notes-tab row tile (~120 × 68 px), shows time chip
     *    `chip`  — Coach Review timeline chip (smaller, 56 × 32 px)
     *    `card`  — Feedback card (full-width, 16:9, with time chip)
     *    `rail`  — playlist session rail strip (compact 80 × 45 px)
     *    `strip` — playlist row stacked tiles (very compact, no chip)
     */
    _coachNoteThumbHtml(note, { size = 'list' } = {}) {
        const id = Number(note?.id);
        if (!Number.isFinite(id) || id <= 0) return '';
        const sizeClass = `coach-thumb--${size}`;
        const ts = this.formatClock(note?.timestamp_seconds);
        // Time chip is helpful on the larger variants where it's
        // legible — skip on the timeline chip (which already shows the
        // timestamp on its label) and the rail strip (very small).
        const timeChip = (size === 'list' || size === 'card')
            ? `<span class="coach-thumb-time">${this.esc(ts)}</span>`
            : '';
        // `data-thumb-state="placeholder"` lets CSS pin the empty state
        // until the mount completes; on success the mount sets it to
        // `loaded` and the background-image is hidden.
        return `
            <div class="coach-thumb ${sizeClass}" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                <img class="coach-thumb-img" data-coach-note-thumb="${id}" alt="" loading="lazy" decoding="async">
                ${timeChip}
            </div>
        `;
    },

    /** Phase 3b — coach/admin "Regenerate thumbnail" action exposed on
     *  Coach Notes list rows. Useful when the source video was uploaded
     *  after the note was saved (the original best-effort spawn would
     *  have logged "no source MP4" and returned generated:false). */
    async handleRegenCoachThumb(noteId) {
        try {
            const result = await this.regenerateCoachNoteThumbnail(noteId);
            if (result?.generated) {
                this.showSuccess('Thumbnail regenerated.');
            } else {
                this.showInfo('Could not regenerate — source video may still be processing.');
            }
            // The regenerate call already invalidated the per-note cache
            // entry. Re-mount thumbnail placeholders in every currently
            // visible surface container so the freshly-generated JPEG
            // appears without a full view re-render.
            this._refreshCoachNoteThumbnailSurfaces();
        } catch (err) {
            this.showError(err.message);
        }
    },

    /** Phase 3b PR #92 review follow-up — remount any `<img
     *  data-coach-note-thumb>` placeholders inside the known thumbnail
     *  containers that are currently in the DOM. Each surface that
     *  isn't mounted (because the user is on a different tab) is a
     *  silent no-op via `mountCoachNoteThumbnailsIn`'s null-safe check.
     *
     *  Used after `regenerateCoachNoteThumbnail` so the new JPEG
     *  surfaces wherever it's already on screen. Does NOT trigger any
     *  re-render of the surrounding view, so DOM identities, focus
     *  state, scroll position, and the Coach Review video element are
     *  all preserved. */
    _refreshCoachNoteThumbnailSurfaces() {
        // Containers currently rendered with thumbnail tiles — each owns
        // one of the size variants from `_coachNoteThumbHtml` /
        // `_coachClipThumbHtml`. Despite the historical name, this
        // helper now refreshes BOTH note and clip thumbnail mounts for
        // every visible coaching surface so a regenerate hit on either
        // type lands wherever it's already on screen. The list is
        // intentionally hard-coded rather than discovered because each
        // container has a different lifecycle (e.g. the playlist
        // session rail lives inside a modal that may not be mounted).
        // A no-op `null` check covers each absent surface; the mount
        // helpers themselves are no-ops on a container with zero
        // matching `data-*` placeholders.
        const containerIds = [
            'coach-notes-list',                // Coach > Notes
            'coach-review-notes',              // Coach > Review timeline rail
            'coach-playlists-list',            // Coach > Playlists
            'coach-clips-list',                // Coach > Clips
            'feedback-notes-list',             // My Feedback > Notes
            'feedback-playlists-list',         // My Feedback > Playlists
            'feedback-clips-list',             // My Feedback > Clips
            // Phase 5b — also remount thumbnails inside the viewer
            // Development tab. Re-mounting both note + clip thumbnails
            // so a regenerate hit while Development is open surfaces
            // the new JPEG without forcing a tab re-render.
            'feedback-development-content',    // My Feedback > Development
        ];
        for (const id of containerIds) {
            const el = document.getElementById(id);
            if (el) {
                this.mountCoachNoteThumbnailsIn(el);
                // Clip thumbnails appear in Coach > Clips, My Feedback
                // > Clips, and the Development surfaces alongside notes.
                // The mount helper is itself a no-op for containers
                // without `<img data-coach-clip-thumb>` placeholders, so
                // the cost on notes-only containers is a single
                // `querySelectorAll` returning zero matches.
                this.mountCoachClipThumbnailsIn?.(el);
            }
        }
        // The focused-feedback player modal's session rail is not an
        // id-bound container — it's `[data-field="rail"]` inside a
        // cloned template. Look it up via the active player ref so we
        // don't accidentally pick up an unrelated `[data-field="rail"]`.
        const railEl = this._feedbackPlayer?.body?.querySelector?.('[data-field="rail"]');
        if (railEl) this.mountCoachNoteThumbnailsIn(railEl);
        // Phase 5b — the coach development modal mounts a transient
        // `.player-dev-modal-body` div that's re-created on each open.
        // It's not id-addressable, but we can find the live one by
        // class so a Coach > Notes regenerate refreshes the modal in
        // place when both happen to be open. Only one such body is
        // ever in the DOM at a time (the modal layer enforces this).
        const modalBody = document.querySelector('.player-dev-modal-body');
        if (modalBody) {
            this.mountCoachNoteThumbnailsIn(modalBody);
            this.mountCoachClipThumbnailsIn?.(modalBody);
        }
    },

    async openCoachNoteModal(noteId = null) {
        const note = noteId ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId)) : null;
        // Phase 6b — dispatch observation notes to the dedicated
        // observation editor. Editing an observation through the
        // video-shaped modal would force a match select that doesn't
        // belong on a text-only note.
        if (note && (note.note_context || 'video') === 'observation') {
            return this.openCoachObservationModal(noteId);
        }
        const tpl = document.getElementById('coach-note-form-template');
        if (!tpl) { this.showError('Note form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        if (note) matchSel.value = note.match_id;

        const slotSel = body.querySelector('[data-field="slot"]');
        if (note) slotSel.value = note.slot;

        body.querySelector('[data-field="time"]').value = note ? Number(note.timestamp_seconds || 0) : 0;
        body.querySelector('[data-field="title"]').value = note?.title || '';
        body.querySelector('[data-field="category"]').value = note?.category || 'other';
        body.querySelector('[data-field="visibility"]').value = note?.visibility || 'private';
        body.querySelector('[data-field="body"]').value = note?.body || '';
        body.querySelector('[data-field="tags"]').value = (note?.tags || []).join(',');

        // Phase 1 structured-note fields (PR 1b). The Notes-tab modal
        // mirrors the Review composer so editing parity is preserved —
        // a note saved via Coach Review can be re-opened here without
        // losing its structured shape.
        const initialNoteType = note?.note_type || DEFAULT_NOTE_TYPE;
        const toneBox = body.querySelector('[data-field="note_type"]');
        toneBox.dataset.value = initialNoteType;
        // Phase 4d (issue #77): the Notes-tab tone chips need the same
        // WAI-ARIA keyboard behavior as the Coach Review composer. The
        // markup intentionally matches the composer's chip set so the
        // shared `_setupToneRadiogroup` helper can drive it.
        toneBox.innerHTML = NOTE_TYPES.map(([v, l, glyph]) => `
            <button type="button" class="coach-review-tone-btn${v === initialNoteType ? ' is-active' : ''}" role="radio" aria-checked="${v === initialNoteType}" tabindex="${v === initialNoteType ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}">
                <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                <span class="coach-review-tone-label">${this.esc(l)}</span>
            </button>
        `).join('');
        // Wire click + keyboard. Click delegation is added here so the
        // modal's chip clicks update the group state without the
        // composer's inline `onclick="app.setCoachReviewNoteType(...)"`
        // attribute (which would target the WRONG group — the composer's
        // — if the modal is open at the same time).
        toneBox.addEventListener('click', (event) => {
            const btn = event.target.closest('.coach-review-tone-btn');
            if (!btn || !toneBox.contains(btn)) return;
            this._syncToneRadiogroup(toneBox, btn.dataset.noteType);
        });
        this._setupToneRadiogroup(toneBox);
        body.querySelector('[data-field="player_summary"]').value = note?.player_summary || '';
        body.querySelector('[data-field="what_happened"]').value = note?.what_happened || '';
        body.querySelector('[data-field="why_it_matters"]').value = note?.why_it_matters || '';
        body.querySelector('[data-field="what_to_do_next"]').value = note?.what_to_do_next || '';
        body.querySelector('[data-field="coach_private_note"]').value = note?.coach_private_note || '';

        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        if (note?.player_ids?.length) {
            const sel = new Set(note.player_ids.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const result = await this.formModal({
            title: note ? 'Edit Coaching Note' : 'New Coaching Note',
            kicker: 'Coaching',
            body,
            confirmLabel: note ? 'Save changes' : 'Save note',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Title is required.'); return; }
                const matchVal = root.querySelector('[data-field="match"]').value;
                if (!matchVal) { this.showError('Match is required.'); return; }
                close({
                    match_id: matchVal,
                    slot: root.querySelector('[data-field="slot"]').value || 'full',
                    timestamp_seconds: Number(root.querySelector('[data-field="time"]').value || 0),
                    title: titleVal,
                    body: root.querySelector('[data-field="body"]').value.trim(),
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    tags: (root.querySelector('[data-field="tags"]').value || '').split(',').map((s) => s.trim()).filter(Boolean),
                    drawing: note?.drawing || {},
                    // Phase 1 structured-note fields.
                    note_type: root.querySelector('[data-field="note_type"]').dataset.value || DEFAULT_NOTE_TYPE,
                    player_summary: root.querySelector('[data-field="player_summary"]').value.trim(),
                    what_happened: root.querySelector('[data-field="what_happened"]').value.trim(),
                    why_it_matters: root.querySelector('[data-field="why_it_matters"]').value.trim(),
                    what_to_do_next: root.querySelector('[data-field="what_to_do_next"]').value.trim(),
                    coach_private_note: root.querySelector('[data-field="coach_private_note"]').value.trim(),
                });
            },
        });
        if (!result) return;
        try {
            if (note) {
                // Phase 4d (incidental fix needed for #77 manual QA):
                // `UpdateCoachingNoteRequest` is `extra="forbid"` and
                // does NOT accept `match_id` or `slot` (rebinding a
                // saved note to a different match/slot would silently
                // invalidate timestamps and drawings, so the backend
                // rejects them outright). The composer modal renders
                // those selects on edit anyway so the coach can see
                // the note's anchor; we just strip them before PATCH
                // so the request matches the server's allow-list. Same
                // pattern as the clip composer's PATCH path
                // (openCoachClipModal). Without this strip, EVERY note
                // edit (incl. the keyboard-driven note_type changes
                // this PR enables) returns 422 and the coach's edits
                // silently disappear.
                const patchBody = { ...result };
                delete patchBody.match_id;
                delete patchBody.slot;
                await this.updateCoachNote(note.id, patchBody);
            } else {
                await this.createCoachNote(result);
            }
            this.showSuccess(note ? 'Note updated.' : 'Note saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteNote(noteId) {
        const ok = await this.confirmAction({
            title: 'Delete note', message: 'Delete this coaching note?',
            confirmLabel: 'Delete note', danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachNote(noteId);
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    /** Phase 6b — observation note composer.
     *
     *  Opens a text-only note editor. Reuses every structured field
     *  from the video-note modal but swaps the match/slot/time row
     *  for `event_title` / `event_date` / `event_type` and drops the
     *  hard "title required" check — observation notes can be saved
     *  with just `event_title` + structured fields when no overall
     *  title makes sense (Phase 6b #113).
     *
     *  Two entry points:
     *    Coach > Roster icon button → `openCoachObservationModal(null,
     *      { playerId })` preselects the player and defaults
     *      visibility to "player".
     *    Coach > Notes "+ New observation" → `openCoachObservationModal()`
     *      with no preselection; visibility defaults to "team".
     *
     *  Edit path: `openCoachObservationModal(noteId)` reuses the same
     *  modal so a coach can iterate on an existing observation.
     *  `openCoachNoteModal` dispatches to this when called with an
     *  observation note id so the video-shaped modal isn't forced on
     *  a text-only row.
     */
    async openCoachObservationModal(noteId = null, { playerId = null } = {}) {
        const note = noteId
            ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId))
            : null;
        if (noteId && !note) {
            this.showError('Observation note not found.');
            return;
        }
        const tpl = document.getElementById('coach-observation-form-template');
        if (!tpl) { this.showError('Observation form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Event metadata.
        body.querySelector('[data-field="event_title"]').value = note?.event_title || '';
        body.querySelector('[data-field="event_date"]').value = note?.event_date || '';
        const eventTypeSel = body.querySelector('[data-field="event_type"]');
        eventTypeSel.value = note?.event_type || '';

        // Shared structured-note fields.
        body.querySelector('[data-field="title"]').value = note?.title || '';
        body.querySelector('[data-field="category"]').value = note?.category || 'other';
        // Visibility default — preselected-player flow leans toward
        // "player" (the coach is writing FOR that player); the Notes-
        // tab "+ New observation" flow has no player context so
        // default to "team".
        const defaultVisibility = note?.visibility
            || (playerId ? 'player' : 'team');
        body.querySelector('[data-field="visibility"]').value = defaultVisibility;
        body.querySelector('[data-field="body"]').value = note?.body || '';
        body.querySelector('[data-field="tags"]').value = (note?.tags || []).join(',');

        // Tone radiogroup — same chip set + a11y wiring as the video
        // note modal so keyboard navigation feels consistent.
        const initialNoteType = note?.note_type || DEFAULT_NOTE_TYPE;
        const toneBox = body.querySelector('[data-field="note_type"]');
        toneBox.dataset.value = initialNoteType;
        toneBox.innerHTML = NOTE_TYPES.map(([v, l, glyph]) => `
            <button type="button" class="coach-review-tone-btn${v === initialNoteType ? ' is-active' : ''}" role="radio" aria-checked="${v === initialNoteType}" tabindex="${v === initialNoteType ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}">
                <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                <span class="coach-review-tone-label">${this.esc(l)}</span>
            </button>
        `).join('');
        toneBox.addEventListener('click', (event) => {
            const btn = event.target.closest('.coach-review-tone-btn');
            if (!btn || !toneBox.contains(btn)) return;
            this._syncToneRadiogroup(toneBox, btn.dataset.noteType);
        });
        this._setupToneRadiogroup(toneBox);

        body.querySelector('[data-field="player_summary"]').value = note?.player_summary || '';
        body.querySelector('[data-field="what_happened"]').value = note?.what_happened || '';
        body.querySelector('[data-field="why_it_matters"]').value = note?.why_it_matters || '';
        body.querySelector('[data-field="what_to_do_next"]').value = note?.what_to_do_next || '';
        body.querySelector('[data-field="coach_private_note"]').value = note?.coach_private_note || '';

        // Players: render the same checklist as the video note modal.
        // Preselect via three sources, in priority order:
        //   1. existing note's player_ids (edit path)
        //   2. explicit playerId arg (Roster entry point)
        //   3. nothing (Notes-tab "New observation" entry point)
        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        const preselected = new Set();
        if (note?.player_ids?.length) {
            note.player_ids.forEach((id) => preselected.add(String(id)));
        } else if (playerId) {
            preselected.add(String(playerId));
        }
        if (preselected.size) {
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (preselected.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        // Phase 6c — tactical board section. The composer carries the
        // current board JSON in a closure variable; the inline editor
        // mounted into [data-field="tactical_board_section"] reads /
        // writes through getBoard / setBoard. On submit we send the
        // latest value so the editor's saved scene round-trips on
        // create AND on edit (and a removed board sends `null` so the
        // backend clears the column).
        let currentBoard = (note?.tactical_board_json && typeof note.tactical_board_json === 'object')
            ? note.tactical_board_json
            : null;
        const boardContainer = body.querySelector('[data-field="tactical_board_section"]');
        if (boardContainer) {
            this.mountTacticalBoardSection(boardContainer, {
                initialBoard: currentBoard,
                getBoard: () => currentBoard,
                setBoard: (next) => { currentBoard = next; },
            });
        }

        const result = await this.formModal({
            title: note ? 'Edit Observation' : 'New Observation',
            kicker: 'Coach observation',
            body,
            confirmLabel: note ? 'Save changes' : 'Save observation',
            // Phase 6c — `wide-board` is a scoped wider variant for
            // the observation composer that hosts the tactical board
            // editor. The shared `wide` size stays 720 px so Player
            // Development + focused Feedback player don't get widened.
            size: 'wide-board',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                const eventTitleVal = root.querySelector('[data-field="event_title"]').value.trim();
                const playerSummaryVal = root.querySelector('[data-field="player_summary"]').value.trim();
                const whatHappenedVal = root.querySelector('[data-field="what_happened"]').value.trim();
                const whyMattersVal = root.querySelector('[data-field="why_it_matters"]').value.trim();
                const whatToDoVal = root.querySelector('[data-field="what_to_do_next"]').value.trim();
                const bodyVal = root.querySelector('[data-field="body"]').value.trim();
                const hasBoardNow = this.tacticalBoardHasContent(currentBoard);
                // Mirror the backend's meaningful-content rule so the
                // coach gets a clear inline message instead of a 422.
                const meaningful = titleVal || eventTitleVal || playerSummaryVal
                    || whatHappenedVal || whyMattersVal || whatToDoVal || bodyVal
                    || hasBoardNow;
                if (!meaningful) {
                    this.showError('Observation needs at least a title, event title, or some content.');
                    return;
                }
                close({
                    note_context: 'observation',
                    title: titleVal,
                    event_title: eventTitleVal,
                    event_date: root.querySelector('[data-field="event_date"]').value || '',
                    event_type: root.querySelector('[data-field="event_type"]').value || '',
                    body: bodyVal,
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'team',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    tags: (root.querySelector('[data-field="tags"]').value || '').split(',').map((s) => s.trim()).filter(Boolean),
                    note_type: root.querySelector('[data-field="note_type"]').dataset.value || DEFAULT_NOTE_TYPE,
                    player_summary: playerSummaryVal,
                    what_happened: whatHappenedVal,
                    why_it_matters: whyMattersVal,
                    what_to_do_next: whatToDoVal,
                    coach_private_note: root.querySelector('[data-field="coach_private_note"]').value.trim(),
                    tactical_board_json: currentBoard,
                });
            },
        });
        if (!result) return;
        try {
            if (note) {
                // Edit path. `UpdateCoachingNoteRequest` is `extra="forbid"`
                // so we send only fields that exist on it. `note_context`
                // stays so a future flip back to video can be initiated
                // explicitly elsewhere; for now Phase 6b only supports
                // editing observations as observations.
                await this.updateCoachNote(note.id, result);
            } else {
                await this.createCoachNote(result);
            }
            this.showSuccess(note ? 'Observation updated.' : 'Observation saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    // ===== Playlists sub-tab =====

    renderCoachPlaylists() {
        const container = document.getElementById('coach-playlists-list');
        if (!container) return;
        const playlists = this._coachBundle?.playlists || [];
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists yet. Click <strong>+ New playlist</strong> to build one.</div>';
            return;
        }
        // Phase 3b: build a quick lookup from note id → note so we can
        // show a stacked thumbnail strip (first 3 notes of the playlist)
        // on each row. Cheap one-pass map build; the full notes list is
        // already loaded in `_coachBundle`.
        const notesById = new Map();
        (this._coachBundle?.notes || []).forEach((n) => notesById.set(Number(n.id), n));
        container.innerHTML = playlists.map((p) => {
            const noteCount = p.note_ids?.length || 0;
            const playerCount = p.player_ids?.length || 0;
            const meta = [
                `${noteCount} note${noteCount === 1 ? '' : 's'}`,
                this.esc(p.visibility),
                `${Number(p.pre_roll_seconds ?? 5)}s pre / ${Number(p.post_roll_seconds ?? 8)}s post`,
            ];
            if (playerCount) meta.push(`${playerCount} player${playerCount === 1 ? '' : 's'}`);
            return `
            <article class="coach-row coach-row-with-thumb">
                ${this._coachPlaylistThumbStripHtml(p, notesById)}
                <div class="coach-row-body">
                    <strong>${this.esc(p.title)}</strong>
                    <span>${meta.join(' · ')}</span>
                    ${p.description ? `<p>${this.esc(p.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.previewCoachPlaylist(${p.id})">Preview</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachPlaylistModal(${p.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeletePlaylist(${p.id})">Delete</button>
                </div>
            </article>
        `;
        }).join('');
        this.mountCoachNoteThumbnailsIn(container);
    },

    /** Phase 3b — render a stacked thumbnail strip representing the
     *  first few notes in a playlist. Up to 3 tiles; if there are more
     *  items we add a `+N` overflow chip. Uses the same `coach-thumb`
     *  primitive as individual notes so the placeholder/loaded state
     *  behaves identically. */
    _coachPlaylistThumbStripHtml(playlist, notesById) {
        const ids = (playlist?.note_ids || []).slice(0, 3);
        const total = playlist?.note_ids?.length || 0;
        if (!ids.length) {
            return `
                <div class="coach-thumb-strip coach-thumb-strip--empty" aria-hidden="true">
                    <div class="coach-thumb coach-thumb--strip" data-thumb data-thumb-state="placeholder"></div>
                </div>
            `;
        }
        const tiles = ids.map((id) => {
            const note = notesById.get(Number(id));
            if (!note) {
                return `<div class="coach-thumb coach-thumb--strip" data-thumb data-thumb-state="placeholder"></div>`;
            }
            return this._coachNoteThumbHtml(note, { size: 'strip' });
        }).join('');
        const overflow = total > 3
            ? `<span class="coach-thumb-strip-more" aria-label="${total - 3} more clips">+${total - 3}</span>`
            : '';
        return `
            <div class="coach-thumb-strip" aria-hidden="true">
                ${tiles}
                ${overflow}
            </div>
        `;
    },

    async openCoachPlaylistModal(playlistId = null) {
        const playlist = playlistId ? (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId)) : null;
        const tpl = document.getElementById('coach-playlist-form-template');
        if (!tpl) { this.showError('Playlist form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        body.querySelector('[data-field="title"]').value = playlist?.title || '';
        body.querySelector('[data-field="visibility"]').value = playlist?.visibility || 'private';
        body.querySelector('[data-field="preRoll"]').value = Number(playlist?.pre_roll_seconds ?? 5);
        body.querySelector('[data-field="postRoll"]').value = Number(playlist?.post_roll_seconds ?? 8);
        body.querySelector('[data-field="description"]').value = playlist?.description || '';

        const notes = this._coachBundle?.notes || [];
        const notesBox = body.querySelector('[data-field="notes"]');
        this.renderCoachCheckList(notesBox, notes.map((n) => ({ value: n.id, label: this.noteLabel(n) })), 'No notes yet');
        if (playlist?.note_ids?.length) {
            const sel = new Set(playlist.note_ids.map(String));
            notesBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        if (playlist?.player_ids?.length) {
            const sel = new Set(playlist.player_ids.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        const result = await this.formModal({
            title: playlist ? 'Edit Review Playlist' : 'New Review Playlist',
            kicker: 'Coaching',
            body,
            confirmLabel: playlist ? 'Save changes' : 'Create playlist',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Playlist title is required.'); return; }
                close({
                    title: titleVal,
                    description: root.querySelector('[data-field="description"]').value.trim(),
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    note_ids: Array.from(root.querySelector('[data-field="notes"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => Number(b.dataset.value)),
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                    pre_roll_seconds: Number(root.querySelector('[data-field="preRoll"]').value || 5),
                    post_roll_seconds: Number(root.querySelector('[data-field="postRoll"]').value || 8),
                });
            },
        });
        if (!result) return;
        try {
            if (playlist) await this.updateCoachPlaylist(playlist.id, result);
            else await this.createCoachPlaylist(result);
            this.showSuccess(playlist ? 'Playlist updated.' : 'Playlist created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeletePlaylist(playlistId) {
        const ok = await this.confirmAction({
            title: 'Delete playlist', message: 'Delete this review playlist?',
            confirmLabel: 'Delete playlist', danger: true,
        });
        if (!ok) return;
        try {
            const resp = await this.authFetch(`/api/coach/playlists/${playlistId}`, {
                method: 'DELETE', headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to delete playlist');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    previewCoachPlaylist(playlistId) {
        const playlist = (this._coachBundle?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'coach' });
    },

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

    renderCoachClips() {
        const container = document.getElementById('coach-clips-list');
        if (!container) return;
        const clips = this._coachBundle?.clips || [];
        if (!clips.length) {
            container.innerHTML = '<div class="session-empty">No clips yet. Create one from the <strong>Review</strong> tab via <em>Save clip</em>, or click <strong>+ New clip</strong> above.</div>';
            return;
        }
        // Sort newest-first by updated_at so a coach who just edited
        // a clip's window or player tags sees it bubble to the top.
        const sorted = clips.slice().sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
        container.innerHTML = sorted.map((c) => {
            const playerCount = c.player_ids?.length || 0;
            const meta = [
                this.matchLabel(c.match_id),
                this.slotLabel(c.slot),
                `${this.formatClock(c.start_seconds)}–${this.formatClock(c.end_seconds)}`,
                `${this._clipDurationLabel(c)}`,
                this.esc(c.category),
                this.esc(c.visibility),
            ];
            if (playerCount) meta.push(`${playerCount} player${playerCount === 1 ? '' : 's'}`);
            const sourceBadge = c.source_note_id
                ? '<span class="coach-clip-source-pill" title="Created from a coaching note">From note</span>'
                : '';
            return `
            <article class="coach-row coach-row-with-thumb">
                ${this._coachClipThumbHtml(c)}
                <div class="coach-row-body">
                    <strong>${this.esc(c.title)}</strong>
                    <span>${meta.map((s) => this.esc(s)).join(' · ')} ${sourceBadge}</span>
                    ${c.description ? `<p>${this.esc(c.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.previewCoachClip(${c.id})">Preview</button>
                    ${c.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(c.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_clip_id: ${Number(c.id)}, title: ${JSON.stringify(c.title || 'Clip goal').replace(/"/g, '&quot;')}, description: ${JSON.stringify(c.description || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(c.title || 'Coaching clip').replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn" onclick="app.openCoachClipModal(${c.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteClip(${c.id})">Delete</button>
                </div>
            </article>
            `;
        }).join('');
        // Phase 4e: clip thumbnails first (per-clip JPEGs at start_seconds),
        // with `data-coach-note-thumb-fallback` providing the source-note /
        // co-located note as a render-time fallback for clips that haven't
        // been generated yet. `mountCoachClipThumbnailsIn` runs the chain.
        this.mountCoachClipThumbnailsIn(container);
    },

    /** Render a thumbnail tile for a clip. Phase 4e adds first-class
     *  per-clip thumbnails generated from the source video at
     *  `start_seconds`, served from `GET /api/coach/clips/{id}/thumbnail`
     *  (visibility-checked per-viewer).
     *
     *  Resolution order (single `<img>` element with a fallback hint):
     *    1. clip thumbnail        — `data-coach-clip-thumb="<id>"`
     *    2. source-note thumbnail — `data-coach-note-thumb-fallback="<noteId>"`
     *       used when (1) returns null AND `clip.source_note_id` is set
     *    3. co-located note thumb — same fallback, derived from the
     *       client-side `notes[]` bundle when no explicit linkage exists
     *    4. placeholder           — both above failed; the
     *       `data-thumb-state="placeholder"` tile stays visible
     *
     *  `mountCoachClipThumbnailsIn` runs the chain in `js/api.js`. The
     *  thumbnail GETs each enforce `_can_view_coach_clip` /
     *  `_can_view_coach_note` server-side, so a viewer who can't see a
     *  private note or private clip never sees its thumbnail leak. */
    _coachClipThumbHtml(clip) {
        const clipId = Number(clip?.id);
        if (!Number.isFinite(clipId) || clipId <= 0) {
            return `
                <div class="coach-thumb coach-thumb--list" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                    <span class="coach-thumb-time">${this.esc(this.formatClock(clip?.start_seconds))}</span>
                </div>
            `;
        }
        // Pick the best note fallback: explicit `source_note_id` first,
        // then a co-located note from the user's bundle/feedback notes.
        let fallbackNoteId = Number(clip?.source_note_id);
        if (!Number.isFinite(fallbackNoteId) || fallbackNoteId <= 0) {
            const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
            const co = this._coLocatedNoteId(clip, notes);
            fallbackNoteId = Number.isFinite(co) && co > 0 ? co : 0;
        }
        const fallbackAttr = fallbackNoteId > 0
            ? ` data-coach-note-thumb-fallback="${fallbackNoteId}"`
            : '';
        return `
            <div class="coach-thumb coach-thumb--list" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                <img class="coach-thumb-img" data-coach-clip-thumb="${clipId}"${fallbackAttr} alt="" loading="lazy" decoding="async">
                <span class="coach-thumb-time">${this.esc(this.formatClock(clip?.start_seconds))}</span>
            </div>
        `;
    },

    /** Find a note from `notes` that's most representative of the
     *  clip — same `match_id` / `slot`, `timestamp_seconds` inside
     *  `[start_seconds, end_seconds]`, closest to window midpoint
     *  when several match. Returns the note id or null. Used by
     *  `_coachClipThumbHtml` as a render-time thumbnail fallback for
     *  clips that have no explicit `source_note_id`. */
    _coLocatedNoteId(clip, notes) {
        if (!clip || !Array.isArray(notes) || !notes.length) return null;
        const matchId = clip.match_id;
        const slot = clip.slot || 'full';
        const start = Number(clip.start_seconds);
        const end = Number(clip.end_seconds);
        if (!matchId || !(end > start)) return null;
        const mid = (start + end) / 2;
        let best = null;
        let bestDelta = Infinity;
        for (const n of notes) {
            if (n.match_id !== matchId) continue;
            if ((n.slot || 'full') !== slot) continue;
            const ts = Number(n.timestamp_seconds);
            if (!Number.isFinite(ts)) continue;
            if (ts < start || ts > end) continue;
            const delta = Math.abs(ts - mid);
            if (delta < bestDelta) {
                best = Number(n.id);
                bestDelta = delta;
            }
        }
        return best;
    },

    /** Returns "1:23" style duration for a clip (clamped to ≥ 0). */
    _clipDurationLabel(clip) {
        const dur = Math.max(0, Number(clip?.end_seconds || 0) - Number(clip?.start_seconds || 0));
        const total = Math.round(dur);
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return `${mins}:${String(secs).padStart(2, '0')}`;
    },

    /** Open the clip composer pre-filled from the Coach Review video's
     *  current time. If no video is loaded, surface a friendly error
     *  and bail — the coach has to pick a match first. */
    openClipComposerFromReview() {
        const review = this._coachReview;
        if (!review?.matchId) {
            this.showError('Pick a match in the Review tab before saving a clip.');
            return;
        }
        // Phase 4c (issue #100): metadata must be loaded before we
        // trust `currentTime` / `duration`. The `loadedmetadata`
        // listener in `loadCoachReviewVideo` flips `metadataReady`
        // to true; until then `currentTime` is 0 and pre-fill would
        // silently produce a [0, 8] window with no relation to what
        // the coach was watching. Surface a clear message instead.
        const video = document.getElementById(this._coachVideoId);
        const ready = review.metadataReady && video && Number.isFinite(video.duration) && video.duration > 0;
        if (!ready) {
            this.showError('Wait for the video to load before saving a clip.');
            return;
        }
        const t = Number(video.currentTime || 0);
        const start = Math.max(0, t - COACH_CLIP_DEFAULT_PRE_ROLL);
        const end = Math.max(start + 1, t + COACH_CLIP_DEFAULT_POST_ROLL);
        // Cap at the MVP duration ceiling so the pre-fill always
        // produces a server-acceptable window.
        const capped_end = Math.min(end, start + COACH_CLIP_MAX_DURATION_SECONDS);
        // Also cap end at the video's duration so a clip near the
        // end of the match doesn't suggest a timestamp past EOS.
        const safe_end = Math.min(capped_end, video.duration);
        // Issue #104: clip thumbnails reuse the source note's thumbnail,
        // but the composer never set `source_note_id` so every saved
        // clip rendered as a placeholder tile. Derive a candidate source
        // note here when the coach is clearly working off a moment:
        //   1) prefer the explicitly-active timeline chip (set when the
        //      coach clicks a note in Coach Review),
        //   2) otherwise pick the same-match/same-slot note whose
        //      `timestamp_seconds` falls inside the [start, end] window.
        // The candidate is a hint — the composer renders a "From note
        // #N" pill so the coach can confirm or clear it before saving.
        const sourceNoteId = this._deriveClipSourceNoteId(
            review.matchId, review.slot || 'full', start, safe_end,
        );
        this.openCoachClipModal(null, {
            match_id: review.matchId,
            slot: review.slot || 'full',
            start_seconds: Number(start.toFixed(1)),
            end_seconds: Number(safe_end.toFixed(1)),
            source_note_id: sourceNoteId,
        });
    },

    /** Pick a source note for a new clip when the coach is clearly
     *  working off a specific moment. Returns the note id or null.
     *  Order of preference:
     *    1. The active timeline chip in Coach Review (`_coachActiveNoteId`).
     *    2. A note on the same `match_id`/`slot` whose
     *       `timestamp_seconds` falls inside `[start, end]`. When
     *       multiple notes match, pick the one closest to the window
     *       midpoint (most representative frame).
     *  Returns null when no plausible source note exists — the clip
     *  will then render the placeholder tile, which is the correct
     *  degraded state. */
    _deriveClipSourceNoteId(matchId, slot, start, end) {
        const notes = this._coachBundle?.notes || [];
        if (!matchId || !notes.length) return null;
        // Prefer the explicitly-selected note when it matches the clip's
        // match/slot. A coach who clicked a chip and then "Save Clip"
        // expects that note to drive the clip.
        if (this._coachActiveNoteId) {
            const active = notes.find((n) => Number(n.id) === Number(this._coachActiveNoteId));
            if (active && active.match_id === matchId && (active.slot || 'full') === slot) {
                return Number(active.id);
            }
        }
        // Fall through to the same co-located picker the render-time
        // fallback uses, so the linkage logic has one source of truth.
        return this._coLocatedNoteId({
            match_id: matchId, slot, start_seconds: start, end_seconds: end,
        }, notes);
    },

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

    /** Mount the clip composer modal. `clipId === null` is the create
     *  flow; `seed` is an optional set of pre-filled fields used by
     *  `openClipComposerFromReview`. */
    async openCoachClipModal(clipId = null, seed = null) {
        const clip = clipId ? (this._coachBundle?.clips || []).find((c) => Number(c.id) === Number(clipId)) : null;
        const tpl = document.getElementById('coach-clip-form-template');
        if (!tpl) { this.showError('Clip form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Match select — same option set as the note composer modal.
        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        const initialMatchId = clip?.match_id || seed?.match_id || (this.matches[0]?.id || '');
        matchSel.value = initialMatchId;

        const slotSel = body.querySelector('[data-field="slot"]');
        slotSel.value = clip?.slot || seed?.slot || 'full';

        // PR #96 review fix: on EDIT, disable Match + Slot. The
        // backend's `UpdateCoachingClipRequest` is `extra="forbid"` and
        // the previous PATCH path silently stripped these fields,
        // causing the coach's edits to disappear without explanation.
        // Disabling the controls makes the constraint visible. Both
        // the visual class and `aria-disabled` keep the controls in
        // tab order with focus rings (`disabled` would also block them
        // — that's the right behavior here, since changes are not
        // accepted by the server). On CREATE the controls stay
        // editable as before.
        if (clip) {
            matchSel.disabled = true;
            slotSel.disabled = true;
            // Append a tiny "fixed on edit" hint so the coach knows
            // why these dropdowns are greyed out without having to
            // experiment.
            const matchHint = matchSel.parentElement;
            const slotHint = slotSel.parentElement;
            const fixedNote = document.createElement('span');
            fixedNote.className = 'coach-clip-field-hint';
            fixedNote.textContent = 'Fixed on edit — create a new clip to change.';
            if (matchHint && !matchHint.querySelector('.coach-clip-field-hint')) {
                matchHint.appendChild(fixedNote);
            }
            // The slot dropdown gets its own copy via cloneNode so
            // both fields are equally explanatory; one node would only
            // attach to the first parent.
            if (slotHint && !slotHint.querySelector('.coach-clip-field-hint')) {
                slotHint.appendChild(fixedNote.cloneNode(true));
            }
        }

        body.querySelector('[data-field="title"]').value = clip?.title || '';
        body.querySelector('[data-field="visibility"]').value = clip?.visibility || 'private';
        body.querySelector('[data-field="description"]').value = clip?.description || '';

        // Category select — pull from NOTE_CATEGORIES so the vocabulary
        // is identical to notes / playlists.
        const categorySel = body.querySelector('[data-field="category"]');
        categorySel.innerHTML = NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('');
        categorySel.value = clip?.category || 'other';

        // Window numeric inputs — formatted to one decimal so a coach
        // can type 12.5 without the input rounding to whole seconds.
        const startEl = body.querySelector('[data-field="startSeconds"]');
        const endEl = body.querySelector('[data-field="endSeconds"]');
        startEl.value = Number(clip?.start_seconds ?? seed?.start_seconds ?? 0).toFixed(1);
        endEl.value = Number(clip?.end_seconds ?? seed?.end_seconds ?? 10).toFixed(1);

        // Live duration label — recompute on every input edit so the
        // coach sees instantly when the window violates the cap.
        const durationEl = body.querySelector('[data-field="durationDisplay"]');
        const refreshDuration = () => {
            const start = Number(startEl.value || 0);
            const end = Number(endEl.value || 0);
            const dur = Math.max(0, end - start);
            const mins = Math.floor(dur / 60);
            const secs = Math.round(dur % 60);
            durationEl.textContent = `${mins}:${String(secs).padStart(2, '0')}`;
            durationEl.classList.toggle('coach-clip-duration--invalid',
                dur <= 0 || dur > COACH_CLIP_MAX_DURATION_SECONDS);
        };
        startEl.addEventListener('input', refreshDuration);
        endEl.addEventListener('input', refreshDuration);
        refreshDuration();

        // Player check-list — same primitive as notes / playlists.
        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        const initialPlayerIds = clip?.player_ids || seed?.player_ids || [];
        if (initialPlayerIds.length) {
            const sel = new Set(initialPlayerIds.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        // Source-note pill — show on EDIT when the clip was created
        // from a note, OR on CREATE when `openClipComposerFromReview`
        // pre-derived a candidate source note (issue #104). On edit
        // `source_note_id` is intentionally NOT editable (rebinding
        // would silently swap the saved drawing snapshot — see
        // `db.update_coaching_clip`'s docstring). On create the coach
        // can simply not save with the candidate (the field is hidden
        // on the form; it's a hint, not a control).
        const seedSourceNoteId = Number(seed?.source_note_id) || null;
        const effectiveSourceNoteId = clip?.source_note_id || seedSourceNoteId || null;
        if (effectiveSourceNoteId) {
            const sourceRow = body.querySelector('[data-field="sourceRow"]');
            const sourceLabel = body.querySelector('[data-field="sourceLabel"]');
            sourceRow.hidden = false;
            sourceLabel.textContent = `From note #${effectiveSourceNoteId}`;
        }

        const result = await this.formModal({
            title: clip ? 'Edit Coaching Clip' : 'New Coaching Clip',
            kicker: 'Coaching',
            body,
            confirmLabel: clip ? 'Save changes' : 'Save clip',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Clip title is required.'); return; }
                const matchVal = root.querySelector('[data-field="match"]').value;
                if (!matchVal) { this.showError('Match is required.'); return; }
                const start = Number(root.querySelector('[data-field="startSeconds"]').value || 0);
                const end = Number(root.querySelector('[data-field="endSeconds"]').value || 0);
                if (!(end > start)) { this.showError('End time must be greater than start time.'); return; }
                if ((end - start) > COACH_CLIP_MAX_DURATION_SECONDS) {
                    this.showError(`Clip duration must be ${COACH_CLIP_MAX_DURATION_SECONDS} seconds or less.`);
                    return;
                }
                const out = {
                    match_id: matchVal,
                    slot: root.querySelector('[data-field="slot"]').value || 'full',
                    start_seconds: start,
                    end_seconds: end,
                    title: titleVal,
                    description: root.querySelector('[data-field="description"]').value.trim(),
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                };
                // Issue #104: only include `source_note_id` on CREATE
                // when the seed pre-derived one. On EDIT we never
                // re-emit it (the backend's `UpdateCoachingClipRequest`
                // is `extra="forbid"` and rebinding mid-life would
                // silently swap the captured drawing snapshot).
                if (!clip && seedSourceNoteId) {
                    out.source_note_id = seedSourceNoteId;
                }
                close(out);
            },
        });
        if (!result) return;
        try {
            if (clip) {
                // PATCH only the fields a coach can actually edit on
                // an existing clip. `match_id` and `slot` are NOT in
                // the backend's `UpdateCoachingClipRequest` allowed
                // set, so we filter them out client-side too — server
                // would 422 on `extra="forbid"` otherwise.
                const patchBody = { ...result };
                delete patchBody.match_id;
                delete patchBody.slot;
                await this.updateCoachClip(clip.id, patchBody);
            } else {
                await this.createCoachClip(result);
            }
            this.showSuccess(clip ? 'Clip updated.' : 'Clip created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteClip(clipId) {
        const ok = await this.confirmAction({
            title: 'Delete clip', message: 'Delete this coaching clip?',
            confirmLabel: 'Delete clip', danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachClip(clipId);
            await this.renderCoachWorkspace();
            this.showSuccess('Clip deleted.');
        } catch (err) { this.showError(err.message); }
    },

    /** Coach-side preview opens the focused feedback player in clip
     *  mode. Reuses the same modal + canvas + heartbeat as note /
     *  playlist preview. */
    previewCoachClip(clipId) {
        const clip = (this._coachBundle?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) return;
        this.openFeedbackPlayer({ mode: 'clip', clip, playerSource: 'coach' });
    },

    // ===== Review sub-tab =====

    // ===== Match summaries sub-tab (Phase 8) =====

    _summaryVisibilityLabel(visibility) {
        return (VISIBILITY_OPTIONS.find(([v]) => v === visibility)?.[1]) || visibility || 'Private';
    },

    _summaryLinkedCounts(summary) {
        const bits = [];
        const noteCount = (summary?.note_ids || []).length;
        const clipCount = (summary?.clip_ids || []).length;
        const playlistCount = (summary?.playlist_ids || []).length;
        if (noteCount) bits.push(`${noteCount} note${noteCount === 1 ? '' : 's'}`);
        if (clipCount) bits.push(`${clipCount} clip${clipCount === 1 ? '' : 's'}`);
        if (playlistCount) bits.push(`${playlistCount} playlist${playlistCount === 1 ? '' : 's'}`);
        return bits.join(' · ');
    },

    renderCoachMatchSummaries() {
        const list = document.getElementById('coach-summaries-list');
        if (!list) return;
        const summaries = this._coachBundle?.match_summaries || [];
        if (!summaries.length) {
            list.innerHTML = '<div class="session-empty">No match summaries yet. Add a team-visible recap after a match.</div>';
            return;
        }
        list.innerHTML = summaries.map((s) => {
            const sections = [
                ['Positives', s.team_positives],
                ['Improve', s.team_improvements],
                ['Training focus', s.training_focus],
                ['Coach recap', s.body],
            ].filter(([, value]) => (value || '').trim());
            const linked = this._summaryLinkedCounts(s);
            return `
                <article class="coach-list-item" data-summary-id="${Number(s.id)}">
                    <div class="coach-list-main">
                        <strong>${this.esc(this.matchLabel(s.match_id))}</strong>
                        <span>${this.esc(this._summaryVisibilityLabel(s.visibility))}${linked ? ` · ${this.esc(linked)}` : ''}</span>
                        ${sections.map(([label, value]) => `<p><strong>${this.esc(label)}:</strong> ${this.esc(value)}</p>`).join('')}
                    </div>
                    <div class="coach-list-actions">
                        <button type="button" class="mini-action-btn" onclick="app.openCoachMatchSummaryModal(${Number(s.id)})">Edit</button>
                        <button type="button" class="mini-action-btn danger" onclick="app.handleCoachDeleteMatchSummary(${Number(s.id)})">Delete</button>
                    </div>
                </article>`;
        }).join('');
    },

    _renderSummaryChecklist(box, items, selectedIds, emptyLabel) {
        this.renderCoachCheckList(box, items, emptyLabel);
        const selected = new Set((selectedIds || []).map(String));
        box.querySelectorAll('.coach-check-option').forEach((btn) => {
            if (selected.has(btn.dataset.value)) {
                btn.classList.add('is-selected');
                btn.setAttribute('aria-pressed', 'true');
            }
        });
    },

    async openCoachMatchSummaryModal(summaryId = null) {
        const summary = summaryId ? (this._coachBundle?.match_summaries || []).find((s) => Number(s.id) === Number(summaryId)) : null;
        const body = document.createElement('div');
        body.className = 'coach-link-modal';
        body.innerHTML = `
            <span class="admin-card-kicker">Match Summary</span>
            <h3>${summary ? 'Edit match summary' : 'New match summary'}</h3>
            <p class="admin-card-sub">Team-visible summaries appear in My Feedback. Linked private source notes/clips/playlists are filtered server-side and are never exposed to viewers.</p>
            <div class="form-row">
                <div class="form-group"><label>Match</label><select data-field="match"></select></div>
                <div class="form-group"><label>Visibility</label><select data-field="visibility">${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></div>
            </div>
            <div class="form-group"><label>Team positives</label><textarea data-field="team_positives" rows="3" maxlength="4000" placeholder="What went well as a team?"></textarea></div>
            <div class="form-group"><label>Areas to improve</label><textarea data-field="team_improvements" rows="3" maxlength="4000" placeholder="What should we clean up next match?"></textarea></div>
            <div class="form-group"><label>Training focus</label><textarea data-field="training_focus" rows="2" maxlength="2000" placeholder="Next practice focus"></textarea></div>
            <div class="form-group"><label>Coach recap</label><textarea data-field="body" rows="4" maxlength="8000" placeholder="Optional full recap for the team"></textarea></div>
            <details class="mt-4"><summary>Link notes, clips, and playlists</summary>
                <div class="form-row mt-4">
                    <div class="form-group"><label>Notes</label><div data-field="notes" class="coach-check-list"></div></div>
                    <div class="form-group"><label>Clips</label><div data-field="clips" class="coach-check-list"></div></div>
                    <div class="form-group"><label>Playlists</label><div data-field="playlists" class="coach-check-list"></div></div>
                </div>
            </details>`;
        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        if (summary) {
            matchSel.value = summary.match_id;
            matchSel.disabled = true;
            matchSel.title = 'Match cannot be changed after a summary is created.';
            matchSel.closest('.form-group')?.insertAdjacentHTML('beforeend', '<small class="form-help">Create a new summary to recap a different match.</small>');
        }
        body.querySelector('[data-field="visibility"]').value = summary?.visibility || 'private';
        ['team_positives', 'team_improvements', 'training_focus', 'body'].forEach((field) => {
            body.querySelector(`[data-field="${field}"]`).value = summary?.[field] || '';
        });
        const notes = (this._coachBundle?.notes || []).filter((n) => !summary || n.match_id === summary.match_id || (summary.note_ids || []).includes(n.id));
        const clips = (this._coachBundle?.clips || []).filter((c) => !summary || c.match_id === summary.match_id || (summary.clip_ids || []).includes(c.id));
        const playlists = this._coachBundle?.playlists || [];
        this._renderSummaryChecklist(body.querySelector('[data-field="notes"]'), notes.map((n) => ({ value: n.id, label: this.noteLabel(n) })), summary?.note_ids, 'No notes yet');
        this._renderSummaryChecklist(body.querySelector('[data-field="clips"]'), clips.map((c) => ({ value: c.id, label: `${this.formatClock(c.start_seconds)}-${this.formatClock(c.end_seconds)} · ${c.title}` })), summary?.clip_ids, 'No clips yet');
        this._renderSummaryChecklist(body.querySelector('[data-field="playlists"]'), playlists.map((p) => ({ value: p.id, label: p.title })), summary?.playlist_ids, 'No playlists yet');

        const result = await this.formModal({
            title: summary ? 'Edit Match Summary' : 'New Match Summary',
            kicker: 'Coaching',
            body,
            confirmLabel: summary ? 'Save changes' : 'Save summary',
            onSubmit: (close) => {
                const textFields = ['team_positives', 'team_improvements', 'training_focus', 'body'];
                const data = Object.fromEntries(textFields.map((f) => [f, body.querySelector(`[data-field="${f}"]`).value.trim()]));
                if (!Object.values(data).some(Boolean)) { this.showError('Add at least one summary field.'); return; }
                const matchId = body.querySelector('[data-field="match"]').value;
                if (!matchId) { this.showError('Match is required.'); return; }
                const selected = (field) => Array.from(body.querySelector(`[data-field="${field}"]`).querySelectorAll('.coach-check-option.is-selected')).map((b) => Number(b.dataset.value));
                close({
                    match_id: matchId,
                    visibility: body.querySelector('[data-field="visibility"]').value || 'private',
                    ...data,
                    note_ids: selected('notes'),
                    clip_ids: selected('clips'),
                    playlist_ids: selected('playlists'),
                });
            },
        });
        if (!result) return;
        try {
            if (summary) {
                const patchBody = { ...result };
                delete patchBody.match_id;
                await this.updateCoachMatchSummary(summary.id, patchBody);
            } else {
                await this.createCoachMatchSummary(result);
            }
            this.showSuccess(summary ? 'Match summary updated.' : 'Match summary saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteMatchSummary(summaryId) {
        const ok = await this.confirmAction({
            title: 'Delete match summary',
            message: 'Delete this match-level coaching summary?',
            confirmLabel: 'Delete summary',
            danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachMatchSummary(summaryId);
            this.showSuccess('Match summary deleted.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

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

    // ===== Phase 6d-1 — Coach Review source modes =====
    //
    // The Review tab is the single creation workspace for video notes,
    // video clips, and tactical-board observations. The source toggle
    // swaps the picker bar's controls, the main canvas, and the side
    // panel without unmounting the shared shell.

    /** Phase 6d-1 — keyboard handler for the source-toggle tablist.
     *  Implements the WAI-ARIA tablist pattern: ArrowLeft / ArrowRight
     *  (and ArrowUp / ArrowDown for vertical-list parity) move focus
     *  to the next / previous tab AND activate it (this is an
     *  "automatic activation" tablist — switching modes has no save-
     *  destroying side effect, so activating on focus matches the
     *  click affordance). Home / End jump to first / last. Does NOT
     *  intercept other keys; the inline `onclick` keeps mouse / touch
     *  / Enter / Space activation working unchanged. */
    handleCoachReviewSourceKeydown(event) {
        const target = event.target;
        if (!target?.dataset?.coachReviewSource) return;
        const tablist = target.closest('[role="tablist"]');
        if (!tablist) return;
        const tabs = Array.from(tablist.querySelectorAll('[data-coach-review-source]'));
        if (tabs.length < 2) return;
        const currentIdx = tabs.indexOf(target);
        let nextIdx = currentIdx;
        switch (event.key) {
            case 'ArrowRight':
            case 'ArrowDown':
                nextIdx = (currentIdx + 1) % tabs.length;
                break;
            case 'ArrowLeft':
            case 'ArrowUp':
                nextIdx = (currentIdx - 1 + tabs.length) % tabs.length;
                break;
            case 'Home':
                nextIdx = 0;
                break;
            case 'End':
                nextIdx = tabs.length - 1;
                break;
            default:
                return;
        }
        event.preventDefault();
        const next = tabs[nextIdx];
        if (!next) return;
        // Activate the new mode (which also updates roving tabindex
        // via _applyCoachReviewSource), then move focus to the now-
        // active tab.
        this.setCoachReviewSource(next.dataset.coachReviewSource);
        try { next.focus(); } catch { /* ignore */ }
    },

    /** Public — change the Coach Review source mode. Wires up the
     *  Save-Observation flow on the first tactical-board entry; tears
     *  down the board controller when leaving tactical mode so a
     *  re-entry starts from a clean state. */
    setCoachReviewSource(source) {
        if (source !== 'video' && source !== 'tactical_board') source = 'video';
        // If we're already on this source AND fully mounted, no-op.
        if (this._coachReviewSource === source && this._coachTab === 'review') return;
        // Save the requested source so renderCoachReview picks it up
        // when Review re-renders (covers the cross-tab routing case).
        this._coachReviewRequestedSource = source;
        if (this._coachTab !== 'review') {
            this.setCoachTab('review');
            return;
        }
        this._applyCoachReviewSource(source);
    },

    _applyCoachReviewSource(source) {
        if (source !== 'video' && source !== 'tactical_board') source = 'video';
        const shell = document.querySelector('#coach-tab-review .coach-review-shell');
        if (!shell) return;
        shell.dataset.source = source;
        // Mirror the source mode onto <body> so source-only show/hide
        // rules still scope correctly when openCoachFocusInspector
        // re-parents `.coach-review-side` to <body> (which moves it
        // out of the .coach-review-shell ancestry — see styles.css
        // body[data-coach-review-source] rules). Cleared in
        // tearDownCoachReview / setLoggedOut so it can't leak.
        document.body.dataset.coachReviewSource = source;
        // Toggle button states + roving tabindex (only the active
        // tab is in the tab order; arrow keys move focus WITHIN the
        // tablist via handleCoachReviewSourceKeydown). Mirrors the
        // tone radiogroup pattern in `_syncToneRadiogroup`.
        //
        // The selector is scoped to `.coach-review-source-toggle
        // [data-coach-review-source]` so it only matches the two
        // tablist buttons. A bare `[data-coach-review-source]`
        // selector would also match `<body
        // data-coach-review-source>` (the body-level mirror used by
        // the focus drawer's off-shell scoping rules) and bizarrely
        // toggle `is-active` / `aria-selected` / `tabindex` on the
        // <body> element.
        document.querySelectorAll('.coach-review-source-toggle [data-coach-review-source]').forEach((btn) => {
            const on = btn.dataset.coachReviewSource === source;
            btn.classList.toggle('is-active', on);
            btn.setAttribute('aria-selected', on ? 'true' : 'false');
            btn.setAttribute('tabindex', on ? '0' : '-1');
        });
        // Defense-in-depth: clear any state we may have stamped onto
        // <body> in earlier (pre-fix) calls. Idempotent — both
        // `removeAttribute` calls are no-ops if the attribute is
        // already absent.
        if (document.body.dataset.coachReviewSource === source) {
            document.body.classList.remove('is-active');
            document.body.removeAttribute('aria-selected');
            document.body.removeAttribute('tabindex');
        }
        // Refresh the keyboard-shortcuts help popover so its kbd list
        // reflects the active source mode (video shortcuts vs tactical-
        // board shortcuts). Idempotent — no-op if the popover element
        // hasn't been rendered yet.
        this._refreshCoachShortcutsHelpForSource?.(source);
        const previous = this._coachReviewSource;
        this._coachReviewSource = source;
        if (source === 'tactical_board') {
            // Tear down any video-mode state so a paused match in the
            // background doesn't keep the heartbeat warm or steal
            // the canvas.
            this._stopFeedbackHeartbeat();
            this.deactivateCoachCanvas?.();
            this._mountCoachReviewBoard();
        } else {
            this._unmountCoachReviewBoard();
            // Re-arm the empty placeholder if no video is loaded.
            if (!this._coachReview) {
                const empty = document.getElementById('coach-review-empty');
                if (empty) empty.style.display = 'flex';
            }
        }
        // If we switched modes, also reset focus mode so a focused video
        // doesn't keep its drawer open over a board canvas.
        if (previous && previous !== source) this.exitCoachFocusMode();
    },

    /** Mount the tactical-board authoring canvas + side panel for the
     *  current Review session. Idempotent — a second call replaces the
     *  initial board (used when routing in with a player_id intent). */
    _mountCoachReviewBoard() {
        const stageEl = document.getElementById('coach-review-board-canvas');
        const toolbarEl = document.getElementById('coach-tb-toolbar');
        const formEl = document.getElementById('coach-tb-form');
        const statusEl = document.getElementById('coach-review-board-status');
        if (!stageEl || !toolbarEl || !formEl) return;
        // Re-render the form every mount so new bundle data (e.g. a
        // newly-linked player) flows in.
        this._renderCoachTacticalBoardForm(formEl);
        // Mount the canvas + tools controller.
        const initialBoard = this._coachReviewBoardCtrl
            ? this._coachReviewBoardCtrl.scenePayload()
            : null;
        if (this._coachReviewBoardCtrl) this._coachReviewBoardCtrl.destroy();
        this._coachReviewBoardCtrl = this.mountTacticalBoardReviewCanvas({
            stageEl, toolbarEl, statusEl, initialBoard,
        });
        // Apply any pending player preselection from the routing intent.
        const intent = this._coachReviewIntent;
        if (intent?.playerId) {
            const opt = formEl.querySelector(`[data-field="players"] .coach-check-option[data-value="${this.esc(intent.playerId)}"]`);
            if (opt) {
                opt.classList.add('is-selected');
                opt.setAttribute('aria-pressed', 'true');
            }
            // Default visibility=player when launched from a roster entry.
            const visEl = formEl.querySelector('[data-field="visibility"]');
            if (visEl && !visEl.dataset.userTouched) visEl.value = 'player';
        }
        this._coachReviewIntent = null;
        // Phase 6d-2 follow-up — match the side panel height to the
        // pitch's rendered height so the inspector column equals the
        // board column (the video-mode counterpart to this lives in
        // `_syncCoachReviewSideHeight`). Initial sync runs after the
        // board has been mounted; a ResizeObserver keeps it accurate
        // when the viewport changes. The observer is torn down in
        // `_unmountCoachReviewBoard` so it doesn't leak between
        // source-mode toggles.
        this._syncCoachReviewSideHeightFromBoard();
        if (this._coachBoardSizeObserver) {
            this._coachBoardSizeObserver.disconnect();
        }
        if (typeof ResizeObserver !== 'undefined') {
            // Observe the outer .coach-review-stage column so the sync
            // tracks the visible left-column height (pitch + status
            // row). Watching the inner board canvas would miss the
            // stage's intrinsic padding / status pill row and leave a
            // small gap below the inspector.
            const stageColumn = document.querySelector('#coach-tab-review .coach-review-stage');
            this._coachBoardSizeObserver = new ResizeObserver(() => {
                this._syncCoachReviewSideHeightFromBoard();
            });
            if (stageColumn) this._coachBoardSizeObserver.observe(stageColumn);
        }
    },

    _unmountCoachReviewBoard() {
        if (this._coachBoardSizeObserver) {
            this._coachBoardSizeObserver.disconnect();
            this._coachBoardSizeObserver = null;
        }
        // Clear the inline max-height we stamped on the aside so the
        // video-mode height sync starts from a clean slate when the
        // coach toggles back. (`_syncCoachReviewSideHeight` will set
        // it again from the video wrapper's rendered height.)
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (side) side.style.maxHeight = '';
        if (this._coachReviewBoardCtrl) {
            this._coachReviewBoardCtrl.destroy();
            this._coachReviewBoardCtrl = null;
        }
    },

    /** Render the observation composer fields into the side panel for
     *  Tactical Board mode. Mirrors the structured fields the modal
     *  observation composer offers, but lives inline (no nested modal)
     *  per the Phase 6d-1 UX rules. */
    _renderCoachTacticalBoardForm(container) {
        if (!container) return;
        const players = this._coachBundle?.players || [];
        container.innerHTML = `
            <input type="text" id="coach-tb-title" maxlength="160" placeholder="Title (optional)" aria-label="Observation title">
            <div class="coach-tb-row">
                <select id="coach-tb-category" aria-label="Category">
                    ${NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
                <select id="coach-tb-visibility" data-field="visibility" aria-label="Visibility">
                    ${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
            </div>
            <div id="coach-tb-tone" class="coach-review-tone" role="radiogroup" aria-label="Note tone">
                ${NOTE_TYPES.map(([v, l, glyph]) => `
                    <button type="button" class="coach-review-tone-btn${v === DEFAULT_NOTE_TYPE ? ' is-active' : ''}" role="radio" aria-checked="${v === DEFAULT_NOTE_TYPE}" tabindex="${v === DEFAULT_NOTE_TYPE ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}" onclick="app.setCoachTbNoteType('${v}')">
                        <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                        <span class="coach-review-tone-label">${this.esc(l)}</span>
                    </button>
                `).join('')}
            </div>
            <div class="coach-tb-section-label">Linked players</div>
            <div data-field="players" class="coach-check-list compact" role="listbox" aria-label="Linked players">
                ${this.coachCheckListHtml(players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet')}
            </div>
            <details class="coach-review-advanced">
                <summary>More details</summary>
                <div class="coach-review-advanced-body">
                    <label class="coach-review-field-label">
                        <span>Player summary <small>(visible to player/family)</small></span>
                        <textarea id="coach-tb-player-summary" rows="2" maxlength="2000" placeholder="Short, age-appropriate version they'll read."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What happened</span>
                        <textarea id="coach-tb-what-happened" rows="2" maxlength="2000" placeholder="The observation."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Why it matters</span>
                        <textarea id="coach-tb-why-it-matters" rows="2" maxlength="2000" placeholder="The coaching context."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What to do next</span>
                        <textarea id="coach-tb-what-to-do-next" rows="2" maxlength="2000" placeholder="The actionable next step."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Coach context (private)</span>
                        <textarea id="coach-tb-coach-private-note" rows="2" maxlength="4000" placeholder="Internal — never sent to players or families."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Long notes</span>
                        <textarea id="coach-tb-body" rows="3" maxlength="4000" placeholder="Anything that doesn't fit the structured fields above."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Tags</span>
                        <input type="text" id="coach-tb-tags" maxlength="300" placeholder="tags,comma,separated">
                    </label>
                </div>
            </details>
        `;
        const toneEl = document.getElementById('coach-tb-tone');
        if (toneEl) {
            toneEl.dataset.value = DEFAULT_NOTE_TYPE;
            this._setupToneRadiogroup(toneEl);
        }
        // Track when the coach manually changes visibility so a routed
        // intent (from Roster) doesn't clobber their explicit choice.
        const visEl = document.getElementById('coach-tb-visibility');
        if (visEl) {
            visEl.addEventListener('change', () => { visEl.dataset.userTouched = '1'; });
        }
    },

    /** Tone-chip click target for the tactical-board side form. */
    setCoachTbNoteType(value) {
        const group = document.getElementById('coach-tb-tone');
        if (!group) return;
        this._syncToneRadiogroup(group, value);
    },

    /** Save Observation — Phase 6d-1 primary save action for Tactical
     *  Board mode. Reads structured fields from the inline side panel,
     *  pulls the current scene from the board controller, and POSTs to
     *  the existing observation endpoint. */
    async saveTacticalBoardObservation() {
        const ctrl = this._coachReviewBoardCtrl;
        if (!ctrl) { this.showError('Tactical board is not ready.'); return; }
        const scene = ctrl.hasContent() ? ctrl.scenePayload() : null;
        const title = (document.getElementById('coach-tb-title')?.value || '').trim();
        const eventTitle = (document.getElementById('coach-tb-event-title')?.value || '').trim();
        const eventDate = (document.getElementById('coach-tb-event-date')?.value || '').trim();
        const eventType = (document.getElementById('coach-tb-event-type')?.value || '').trim();
        const playerSummary = (document.getElementById('coach-tb-player-summary')?.value || '').trim();
        const whatHappened = (document.getElementById('coach-tb-what-happened')?.value || '').trim();
        const whyMatters = (document.getElementById('coach-tb-why-it-matters')?.value || '').trim();
        const whatNext = (document.getElementById('coach-tb-what-to-do-next')?.value || '').trim();
        const body = (document.getElementById('coach-tb-body')?.value || '').trim();
        const meaningful = title || eventTitle || playerSummary || whatHappened
            || whyMatters || whatNext || body || !!scene;
        if (!meaningful) {
            this.showError('Add a title, event title, some content, or a board sketch before saving.');
            return;
        }
        const noteType = document.getElementById('coach-tb-tone')?.dataset.value || DEFAULT_NOTE_TYPE;
        const playerIds = Array.from(document.querySelectorAll('#coach-tb-form [data-field="players"] .coach-check-option.is-selected'))
            .map((b) => b.dataset.value);
        const tags = ((document.getElementById('coach-tb-tags')?.value || '')
            .split(',').map((s) => s.trim()).filter(Boolean));
        const payload = {
            note_context: 'observation',
            title,
            event_title: eventTitle,
            event_date: eventDate,
            event_type: eventType,
            body,
            category: document.getElementById('coach-tb-category')?.value || 'other',
            visibility: document.getElementById('coach-tb-visibility')?.value || 'team',
            player_ids: playerIds,
            tags,
            note_type: noteType,
            player_summary: playerSummary,
            what_happened: whatHappened,
            why_it_matters: whyMatters,
            what_to_do_next: whatNext,
            coach_private_note: (document.getElementById('coach-tb-coach-private-note')?.value || '').trim(),
            tactical_board_json: scene,
        };
        try {
            await this.createCoachNote(payload);
            this.showSuccess('Observation saved.');
            // Reset per-moment fields. Keep visibility / category / tone /
            // selected players so the coach can save a related observation
            // with one more click.
            const PER_MOMENT_IDS = [
                'coach-tb-title', 'coach-tb-event-title', 'coach-tb-event-date',
                'coach-tb-player-summary', 'coach-tb-what-happened',
                'coach-tb-why-it-matters', 'coach-tb-what-to-do-next',
                'coach-tb-body', 'coach-tb-tags', 'coach-tb-coach-private-note',
            ];
            PER_MOMENT_IDS.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
            // Clear the board so the next observation starts blank.
            ctrl.loadScene(null);
            this._coachBundle = await this.loadCoachBundle();
        } catch (err) {
            this.showError(err.message);
        }
    },

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

    // ===== Sprint 6: Wide / Focus mode =====
    //
    // Toggle that hides page chrome + collapses the right inspector so the
    // video and drawing canvas use nearly the entire screen. Tools and
    // composer remain reachable via a slide-over inspector drawer triggered
    // from a small floating button. Escape exits. State is session-local
    // and resets when the user leaves the Review sub-tab.

    toggleCoachFocusMode() {
        if (this._coachFocusMode) this.exitCoachFocusMode();
        else this.enterCoachFocusMode();
    },

    enterCoachFocusMode() {
        if (this._coachFocusMode) return;
        this._coachFocusMode = true;
        this._coachFocusInspectorOpen = false;
        // Sprint 6 fix: snap the page to the top so the cockpit isn't
        // anchored to wherever the user happened to be scrolled (e.g. they
        // scrolled down to see the timeline rail). The fixed-position drawer
        // is viewport-relative, so a scrolled page would render the drawer
        // at the right edge of an ambiguous slice of the cockpit. Saving the
        // previous scroll position lets us restore it on exit.
        this._coachFocusPreviousScrollY = window.scrollY;
        window.scrollTo({ top: 0, behavior: 'instant' });
        const coachView = document.getElementById('coach-view');
        if (coachView) coachView.classList.add('is-focus-mode');
        document.body.classList.add('coach-focus-mode');  // for global overlays / scrollbar gutters
        const toggle = document.getElementById('coach-review-focus-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', 'true');
            toggle.classList.add('is-active');
        }
        // Close the drawer if it was somehow left open from a previous session.
        document.getElementById('coach-view')?.classList.remove('is-focus-drawer-open');
        // Bind Escape (capturing handler so it wins over <details>/canvas).
        this._coachFocusEscapeHandler = (event) => {
            if (event.key !== 'Escape') return;
            // Close the drawer first if it's open; otherwise exit focus mode.
            if (this._coachFocusInspectorOpen) {
                event.preventDefault();
                this.closeCoachFocusInspector();
                return;
            }
            event.preventDefault();
            this.exitCoachFocusMode();
        };
        // Capture phase so the handler runs before any descendant Escape
        // listener (e.g. the browser's default <details> toggle), matching
        // the comment above. Stored phase mirrored on removal in
        // exitCoachFocusMode for symmetry.
        window.addEventListener('keydown', this._coachFocusEscapeHandler, true);
        // The wrapper just changed size — re-sync canvas + inspector height.
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            requestAnimationFrame(() => {
                this._syncCoachReviewSideHeight(video);
                const canvas = document.getElementById(this._coachCanvasId);
                if (canvas) this._resizeCoachCanvas(canvas, video);
            });
        }
    },

    exitCoachFocusMode() {
        if (!this._coachFocusMode) return;
        // Close the inspector first so the side panel returns to its
        // original DOM parent before focus mode exits. closeCoachFocusInspector
        // is a no-op if the inspector wasn't mounted to body.
        this.closeCoachFocusInspector();
        this._coachFocusMode = false;
        this._coachFocusInspectorOpen = false;
        const coachView = document.getElementById('coach-view');
        if (coachView) {
            coachView.classList.remove('is-focus-mode');
            coachView.classList.remove('is-focus-drawer-open');
        }
        // Restore the page scroll position the user had before entering focus.
        if (typeof this._coachFocusPreviousScrollY === 'number') {
            requestAnimationFrame(() => {
                window.scrollTo({ top: this._coachFocusPreviousScrollY, behavior: 'instant' });
                this._coachFocusPreviousScrollY = null;
            });
        }
        document.body.classList.remove('coach-focus-mode');
        const toggle = document.getElementById('coach-review-focus-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', 'false');
            toggle.classList.remove('is-active');
        }
        if (this._coachFocusEscapeHandler) {
            window.removeEventListener('keydown', this._coachFocusEscapeHandler, true);
            this._coachFocusEscapeHandler = null;
        }
        // Re-sync canvas + inspector height for the restored layout.
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            requestAnimationFrame(() => {
                this._syncCoachReviewSideHeight(video);
                const canvas = document.getElementById(this._coachCanvasId);
                if (canvas) this._resizeCoachCanvas(canvas, video);
            });
        }
    },

    openCoachFocusInspector() {
        if (!this._coachFocusMode) return;
        this._coachFocusInspectorOpen = true;
        document.getElementById('coach-view')?.classList.add('is-focus-drawer-open');
        // Body class lets the CSS target the side panel after it gets
        // re-parented to <body> below — bypasses the bounded stacking
        // context created by .coach-tab-panel's animation property.
        document.body.classList.add('coach-focus-drawer-open');
        const t = document.getElementById('coach-review-focus-inspector-toggle');
        if (t) t.setAttribute('aria-pressed', 'true');
        // Phase 6d-1 — in Tactical Board mode the pitch IS the work
        // surface. We still want the click-outside-closes-drawer
        // affordance, but a clicking the PITCH should ALSO be
        // received by the pitch's mousedown handler so the armed
        // tool drops a token / starts a drag in the same gesture.
        // Achieved by:
        //   * mounting the backdrop with `pointer-events: none` (CSS)
        //     so the pitch and picker bar still receive clicks
        //     (visual dim only), AND
        //   * binding a click-on-pitch listener that closes the
        //     drawer when a click lands on the pitch (mirroring the
        //     "tap outside to close" affordance without stealing the
        //     event from the pitch's own handlers).
        //
        // In Video mode the backdrop stays as the standard click-
        // outside-to-close — the video itself doesn't accept primary
        // clicks for note authoring (clicks go through the canvas
        // overlay / picker bar).
        let backdrop = document.getElementById('coach-focus-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'coach-focus-backdrop';
            backdrop.className = 'coach-focus-backdrop';
            backdrop.addEventListener('click', () => this.closeCoachFocusInspector());
            document.body.appendChild(backdrop);
        }
        backdrop.hidden = false;
        // TB-mode-only: bind a delegated mousedown listener to the
        // STABLE board-canvas wrapper (not the SVG itself, which gets
        // recreated on every controller refresh). When a click lands
        // on the pitch the listener closes the drawer; the pitch's
        // own controller handler runs in the same mousedown event
        // dispatch so the tool drops / starts a drag in one gesture.
        // The listener is stored so `closeCoachFocusInspector` can
        // remove it cleanly.
        if (this._coachReviewSource === 'tactical_board') {
            const canvasHost = document.getElementById('coach-review-board-canvas');
            if (canvasHost && !this._tbFocusCloseHandler) {
                this._tbFocusCloseHandler = () => {
                    if (this._coachFocusInspectorOpen) this.closeCoachFocusInspector();
                };
                canvasHost.addEventListener('mousedown', this._tbFocusCloseHandler, { passive: true });
                canvasHost.addEventListener('touchstart', this._tbFocusCloseHandler, { passive: true });
            }
            // Toggle a body class so the CSS can switch the backdrop
            // to `pointer-events: none` (keeps the dim overlay visual
            // but lets clicks pass through to the pitch).
            document.body.classList.add('coach-focus-drawer-tb-mode');
        } else {
            document.body.classList.remove('coach-focus-drawer-tb-mode');
        }
        // Move the inspector to <body> so it shares the root stacking context
        // with the backdrop. Without this, an ancestor with animation /
        // transform / filter (e.g. .coach-tab-panel's coachTabFade animation)
        // creates a bounded stacking context that traps the drawer's z-index
        // — the backdrop renders ABOVE the drawer and intercepts every click.
        const side = document.querySelector('.coach-review-side');
        if (side && !this._coachFocusSideOriginalParent) {
            this._coachFocusSideOriginalParent = side.parentElement;
            this._coachFocusSideOriginalNextSibling = side.nextSibling;
            // Sprint 6 fix: clear the inline `max-height` that Sprint 1's
            // _syncCoachReviewSideHeight set while the panel was inline in
            // the grid. That value (matched to the video wrapper height)
            // would clip the drawer's content vertically once the drawer's
            // own `bottom: 1rem` rule takes over. We save the inline value
            // and restore it on close.
            this._coachFocusSideOriginalMaxHeight = side.style.maxHeight;
            side.style.maxHeight = '';
            document.body.appendChild(side);
        }
        // Sprint 6: scroll the drawer to its top so the telestrator section is
        // visible. .coach-review-side carries a scrollTop value from when it
        // lived inline in the inspector column (Sprint 1 height-sync) — that
        // stale offset would crop the top tools out of view if not reset.
        if (side) {
            // requestAnimationFrame so layout settles after re-parenting before
            // we scroll.
            requestAnimationFrame(() => { side.scrollTop = 0; });
        }
    },

    closeCoachFocusInspector() {
        this._coachFocusInspectorOpen = false;
        document.getElementById('coach-view')?.classList.remove('is-focus-drawer-open');
        document.body.classList.remove('coach-focus-drawer-open');
        // Phase 6d-1 — clear the TB-mode pointer-events pass-through
        // marker AND remove the canvas-host mousedown listener so
        // the next open can re-bind cleanly. The handler is stored
        // on `_tbFocusCloseHandler` so we can remove it without
        // chasing element references through controller refreshes.
        document.body.classList.remove('coach-focus-drawer-tb-mode');
        if (this._tbFocusCloseHandler) {
            const canvasHost = document.getElementById('coach-review-board-canvas');
            if (canvasHost) {
                canvasHost.removeEventListener('mousedown', this._tbFocusCloseHandler);
                canvasHost.removeEventListener('touchstart', this._tbFocusCloseHandler);
            }
            this._tbFocusCloseHandler = null;
        }
        const t = document.getElementById('coach-review-focus-inspector-toggle');
        if (t) t.setAttribute('aria-pressed', 'false');
        const backdrop = document.getElementById('coach-focus-backdrop');
        if (backdrop) backdrop.hidden = true;
        // Restore the inspector to its original DOM position so the rest of
        // the layout (Sprint 1 height-sync ResizeObserver, the timeline rail
        // grid placement) keeps working when focus mode exits.
        const side = document.querySelector('.coach-review-side');
        if (side && this._coachFocusSideOriginalParent) {
            const parent = this._coachFocusSideOriginalParent;
            const next = this._coachFocusSideOriginalNextSibling;
            if (next && next.parentElement === parent) {
                parent.insertBefore(side, next);
            } else {
                parent.appendChild(side);
            }
            // Restore the inline max-height we cleared in openCoachFocusInspector
            // so Sprint 1's height-sync continues to work. _syncCoachReviewSideHeight
            // will overwrite it on the next resize regardless, but restoring here
            // keeps the layout from flickering at zero height for one frame.
            if (this._coachFocusSideOriginalMaxHeight !== undefined) {
                side.style.maxHeight = this._coachFocusSideOriginalMaxHeight;
                this._coachFocusSideOriginalMaxHeight = undefined;
            }
            this._coachFocusSideOriginalParent = null;
            this._coachFocusSideOriginalNextSibling = null;
        }
    },

    toggleCoachFocusInspector() {
        if (this._coachFocusInspectorOpen) this.closeCoachFocusInspector();
        else this.openCoachFocusInspector();
    },

    // ===== Sprint 7: Coach Review keyboard shortcuts =====
    //
    // Per the plan: scoped to Coach > Review only. Listener installed on
    // setCoachTab('review') and removed when leaving the sub-tab so other
    // surfaces (Roster, Notes, Playlists, Feedback, public match) are
    // unaffected. Skips while focus is in any text input / textarea /
    // select / contenteditable so typing isn't intercepted. Reuses
    // existing video methods (currentTime mutation, paused) and existing
    // tool / save methods so behavior stays consistent with mouse use.

    installCoachReviewShortcuts() {
        if (this._coachShortcutsHandler) return;  // already installed
        this._coachShortcutsHandler = (event) => this._handleCoachReviewShortcut(event);
        window.addEventListener('keydown', this._coachShortcutsHandler);
    },

    uninstallCoachReviewShortcuts() {
        if (!this._coachShortcutsHandler) return;
        window.removeEventListener('keydown', this._coachShortcutsHandler);
        this._coachShortcutsHandler = null;
    },

    _coachShortcutShouldSkip(event) {
        // Don't intercept when typing or operating a form control.
        const target = event.target;
        if (!target) return false;
        const tag = (target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
        if (target.isContentEditable) return true;
        // PR 1b: don't intercept while focus is inside the tone radiogroup
        // (Coach Review composer or the Notes-tab Edit modal). The video-
        // seek arrow shortcuts would otherwise scrub the video when a
        // keyboard user tabs into the chip group and presses arrow keys.
        // Full WAI-ARIA roving-tabindex / arrow-key cycling is a future
        // accessibility item; this guard just stops the conflict.
        if (target.closest && (
            target.closest('#coach-review-tone') ||
            target.closest('.coach-review-tone') ||
            target.closest('[role="radiogroup"]') ||
            target.closest('[role="radio"]')
        )) return true;
        // Don't fight other modifier-driven shortcuts (Cmd+S, Ctrl+R, …).
        if (event.metaKey || event.ctrlKey || event.altKey) return true;
        return false;
    },

    _handleCoachReviewShortcut(event) {
        if (this._coachShortcutShouldSkip(event)) return;
        // The Sprint 6 focus-mode Escape handler runs in the capture
        // phase, so it wins over this bubble-phase handler when active.
        // We still bind Escape here as a fallback for cancelling a
        // formation draft when focus mode is OFF. (Skip-typing guard
        // above already lets Escape pass through native input handling
        // when a form control is focused.)
        if (event.key === 'Escape' && !this._coachFocusMode) {
            if (this._coachFormationDraft) {
                event.preventDefault();
                this._coachFormationDraft = null;
                this._renderFormationControls?.();
                this.paintCoachCanvas?.();
            }
            return;
        }
        // Only intercept when the Review tab is actually showing.
        const reviewPanel = document.getElementById('coach-tab-review');
        if (!reviewPanel || reviewPanel.hidden) return;
        // Phase 6d-2 — tactical_board source mode owns its own keydown
        // handler (mountTacticalBoardReviewCanvas), which uses the SAME
        // letter shortcuts where they overlap (A / F / Z / T) plus the
        // tactical-only V / P / B / L. Returning early here keeps the
        // two handlers from double-firing AND prevents this handler
        // from hitting the video setCoachDrawingTool path (which would
        // try to paint on a non-existent video canvas in tactical mode).
        if (this._coachReviewSource === 'tactical_board' && event.key !== '?') return;
        const video = document.getElementById(this._coachVideoId);

        switch (event.key) {
            case ' ':
            case 'k':
                if (!video) return;
                event.preventDefault();
                if (video.paused) video.play().catch(() => {});
                else video.pause();
                return;
            case 'ArrowLeft':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.max(0, (video.currentTime || 0) - (event.shiftKey ? 10 : 1));
                return;
            case 'ArrowRight':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.min(video.duration || Infinity, (video.currentTime || 0) + (event.shiftKey ? 10 : 1));
                return;
            case 'j':
            case 'J':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.max(0, (video.currentTime || 0) - 5);
                return;
            case 'l':
            case 'L':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.min(video.duration || Infinity, (video.currentTime || 0) + 5);
                return;
            case 's':
            case 'S':
                event.preventDefault();
                this.saveReviewNote();
                return;
            case 'a':
            case 'A':
                event.preventDefault();
                this.setCoachDrawingTool('arrow');
                return;
            case 'f':
            case 'F':
                event.preventDefault();
                this.setCoachDrawingTool('freehand');
                return;
            case 'z':
            case 'Z':
                event.preventDefault();
                this.setCoachDrawingTool('zone');
                return;
            case 'c':
            case 'C':
                event.preventDefault();
                this.setCoachDrawingTool('circle');
                return;
            case 't':
            case 'T':
                event.preventDefault();
                this.setCoachDrawingTool('label');
                return;
            case 'd':
            case 'D':
                // Per the plan: "D — Dim/spotlight tool, whichever is most useful".
                // Spotlight is the more interactive of the two (the dim is just
                // a global overlay), so favour it.
                event.preventDefault();
                this.setCoachDrawingTool('spotlight');
                return;
            case '?':
                // Toggle the shortcuts help popover. The plan asks for "a
                // small keyboard shortcuts help popover or tooltip".
                event.preventDefault();
                this.toggleCoachShortcutsHelp();
                return;
        }
    },

    toggleCoachShortcutsHelp() {
        const dialog = document.getElementById('coach-shortcuts-help');
        if (!dialog) return;
        const willOpen = dialog.hidden;
        dialog.hidden = !willOpen;
        // Keep the trigger button's aria-pressed in sync with the popover
        // state so screen readers correctly report whether help is showing.
        // Matches the pattern used by enterCoachFocusMode / setCoachDrawingTool
        // and is exercised by the Sprint 8 a11y audit.
        const toggle = document.getElementById('coach-review-shortcuts-toggle');
        if (toggle) toggle.setAttribute('aria-pressed', willOpen ? 'true' : 'false');
        // Phase 6d-1 — refresh the kbd list to match the active source
        // mode every time the popover opens, in case the source
        // changed since last open without firing _applyCoachReviewSource.
        if (willOpen) this._refreshCoachShortcutsHelpForSource(this._coachReviewSource);
    },

    /** Phase 6d-1 — populate the keyboard-shortcuts help popover with
     *  shortcuts relevant to the active source mode. Video mode keeps
     *  the existing video-scrubbing + telestrator shortcuts. Tactical
     *  Board mode (no video, no telestrator tools yet — those bind to
     *  the video keydown layer) shows only the universally-relevant
     *  shortcuts (Esc, ?) plus a note that mode-specific shortcuts
     *  arrive in Phase 6d-2. */
    _refreshCoachShortcutsHelpForSource(source) {
        const list = document.querySelector('#coach-shortcuts-help .coach-shortcuts-help-list');
        if (!list) return;
        const VIDEO_ITEMS = [
            ['<kbd>Space</kbd> / <kbd>K</kbd>', 'Play / pause'],
            ['<kbd>J</kbd> / <kbd>L</kbd>', 'Back / forward 5 s'],
            ['<kbd>←</kbd> / <kbd>→</kbd>', 'Back / forward 1 s'],
            ['<kbd>Shift</kbd>+<kbd>←</kbd> / <kbd>→</kbd>', 'Back / forward 10 s'],
            ['<kbd>S</kbd>', 'Save note at current time'],
            ['<kbd>A</kbd> <kbd>F</kbd> <kbd>Z</kbd> <kbd>C</kbd> <kbd>T</kbd> <kbd>D</kbd>', 'Arrow / Freehand / Zone / Circle / Label / Spotlight'],
            ['<kbd>Esc</kbd>', 'Exit focus mode'],
            ['<kbd>?</kbd>', 'Show / hide this help'],
        ];
        // Phase 6d-2 — tactical-board keyboard shortcuts. Shortcut
        // letters mirror the video telestrator's conventions where the
        // tools overlap (A / F / Z / T / V); tactical-only tools take
        // P (Player) / B (Ball) / L (Line). Bound in
        // mountTacticalBoardReviewCanvas's keydown handler, gated on
        // `body[data-coach-review-source="tactical_board"]`.
        const TB_ITEMS = [
            ['<kbd>V</kbd>', 'Select / move'],
            ['<kbd>P</kbd>', 'Player token'],
            ['<kbd>B</kbd>', 'Ball'],
            ['<kbd>A</kbd> / <kbd>1</kbd>', 'Arrow'],
            ['<kbd>L</kbd>', 'Line'],
            ['<kbd>Z</kbd>', 'Zone'],
            ['<kbd>F</kbd>', 'Pen / freehand'],
            ['<kbd>T</kbd>', 'Label / text'],
            ['<kbd>Delete</kbd> / <kbd>Backspace</kbd>', 'Delete the selected token or shape'],
            ['<kbd>Esc</kbd>', 'Clear selection or exit drawing tool'],
            ['<kbd>?</kbd>', 'Show / hide this help'],
        ];
        const items = source === 'tactical_board' ? TB_ITEMS : VIDEO_ITEMS;
        const note = '';
        list.innerHTML = items.map(([keys, label]) => `<li>${keys}<span>${this.esc(label)}</span></li>`).join('') + note;
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
            <button type="button" id="coach-review-save-form" class="btn-primary" onclick="app.saveReviewNote()">Save at --:--</button>
            <details class="coach-review-advanced">
                <summary>More details</summary>
                <div class="coach-review-advanced-body">
                    <label class="coach-review-field-label">
                        <span>Visibility</span>
                        <select id="coach-review-visibility" aria-label="Visibility">
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

    // ===== Telestrator (operates on whichever canvas/video pair is current) =====

    renderCoachTelestratorToolbar() {
        // Sprint 3: icon-first toolbar grouped into three sections — drawing
        // tools, paint controls (color + width), and canvas/destructive
        // actions. Each tool button uses inline SVG (no font dependency)
        // plus a visually-hidden text label that re-appears on touch
        // devices via the pointer-aware CSS in styles.css. Every icon
        // button carries title + aria-label + aria-pressed so AT users
        // and tooltip hover stay first-class. Drawing payload, handler
        // names, and data-coach-tool values are unchanged so existing
        // saved drawings + click handlers keep working.
        const tools = [
            ['select',    'Select',         'Select / move objects',
                'M5 3l14 8-6 1.5L11 19z'],
            ['freehand',  'Freehand line',  'Freehand line',
                'M3 17c2-4 4-6 6-6s2 4 4 4 4-4 6-6'],
            ['arrow',     'Arrow',          'Arrow',
                'M4 12h13m-4-5l5 5-5 5'],
            ['circle',    'Circle',         'Circle',
                'M12 4a8 8 0 100 16 8 8 0 000-16z'],
            ['zone',      'Zone',           'Zone (dashed rectangle)',
                'M4 6h4M10 6h4M16 6h4M20 8v4M20 14v4M20 18h-4M14 18h-4M8 18H4M4 16v-4M4 10V6'],
            ['label',     'Label',          'Text label / player number',
                'M6 6h12M12 6v12'],
            ['spotlight', 'Spotlight',      'Spotlight (highlight one player)',
                'M12 4v3M12 17v3M4 12h3M17 12h3M6.3 6.3l2 2M15.7 15.7l2 2M6.3 17.7l2-2M15.7 8.3l2-2M12 9a3 3 0 100 6 3 3 0 000-6z'],
            ['dim',       'Dim',            'Dim the field',
                'M12 4a8 8 0 100 16 8 8 0 008-8 6 6 0 01-8-8z'],
            ['formation', 'Formation',      'Formation (multi-player highlight)',
                'M7 7a2 2 0 110 4 2 2 0 010-4zm10 0a2 2 0 110 4 2 2 0 010-4zM7 15a2 2 0 110 4 2 2 0 010-4zm10 0a2 2 0 110 4 2 2 0 010-4zM12 10a2 2 0 110 4 2 2 0 010-4z'],
        ];
        const colors = ['#38bdf8', '#f97316', '#22c55e', '#facc15', '#f43f5e', '#ffffff'];
        const colorNames = {
            '#38bdf8': 'Sky blue',
            '#f97316': 'Orange',
            '#22c55e': 'Green',
            '#facc15': 'Yellow',
            '#f43f5e': 'Red',
            '#ffffff': 'White',
        };
        const renderToolBtn = ([tool, label, tip, path]) => {
            const active = this._coachDrawingTool === tool;
            return `
                <button type="button"
                        data-coach-tool="${tool}"
                        class="coach-tool-btn ${active ? 'active' : ''}"
                        title="${tip}"
                        aria-label="${tip}"
                        aria-pressed="${active ? 'true' : 'false'}"
                        onclick="app.setCoachDrawingTool('${tool}')">
                    <svg class="coach-tool-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="${path}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span class="coach-tool-label">${label}</span>
                </button>
            `;
        };
        return `
            <div class="coach-telestrator" role="toolbar" aria-label="Telestrator tools">
                <div class="coach-tool-grid" role="group" aria-label="Drawing tools">
                    ${tools.map(renderToolBtn).join('')}
                </div>
                <div class="coach-tool-row" role="group" aria-label="Color and width">
                    ${colors.map((color) => {
                        const active = this._coachDrawingColor === color;
                        const name = colorNames[color] || color;
                        return `
                            <button type="button"
                                    data-coach-color="${color}"
                                    class="coach-color-swatch ${active ? 'active' : ''}"
                                    style="--swatch:${color}"
                                    title="${name}"
                                    aria-label="Color: ${name}"
                                    aria-pressed="${active ? 'true' : 'false'}"
                                    onclick="app.setCoachDrawingColor('${color}')"></button>
                        `;
                    }).join('')}
                    <label class="coach-width-control" title="Stroke width">
                        <span class="coach-width-label" aria-hidden="true">W</span>
                        <input type="range" min="2" max="10" value="${this._coachDrawingWidth}"
                               aria-label="Stroke width"
                               onchange="app.setCoachDrawingWidth(this.value)">
                    </label>
                </div>
                <input type="text" id="coach-label-text" maxlength="40" placeholder="Label / player number"
                       aria-label="Text label or player number for the next label drawing">
                <div id="coach-formation-controls" class="coach-formation-controls" hidden></div>
                <div class="coach-draw-actions" role="group" aria-label="Canvas actions">
                    <button type="button" data-coach-canvas-toggle
                            class="mini-action-btn"
                            aria-pressed="${this._coachDrawingActive ? 'true' : 'false'}"
                            onclick="app.toggleCoachDrawing()">Canvas ${this._coachDrawingActive ? 'On' : 'Off'}</button>
                    <button type="button" class="mini-action-btn"
                            title="Undo last object"
                            onclick="app.undoCoachDrawing()">Undo</button>
                    <button type="button" class="mini-action-btn"
                            title="Delete selected object"
                            onclick="app.deleteSelectedCoachObject()">Delete</button>
                    <button type="button" class="mini-action-btn btn-danger-soft"
                            title="Clear all drawings on this freeze frame"
                            onclick="app.clearCoachDrawing()">Clear</button>
                </div>
            </div>
        `;
    },

    setupCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        const video = document.getElementById(this._coachVideoId);
        if (!canvas || !video) return;
        if (canvas._coachBound) { this._resizeCoachCanvas(canvas, video); return; }
        const resize = () => {
            this._resizeCoachCanvas(canvas, video);
            // Sprint 2 polish: keep the inspector's max-height matched to the
            // video wrapper so the side panel and player are visually the same
            // height. Re-runs whenever the wrapper resizes (window or layout).
            this._syncCoachReviewSideHeight(video);
        };
        window.addEventListener('resize', resize);
        video.addEventListener('loadedmetadata', resize);
        // Sprint 1: the inspector is now independently scrollable, which means the
        // wrapper can change size without window resizing (e.g. inspector grows and
        // pushes the video column narrower). Observe the wrapper directly so the
        // canvas bitmap stays aligned with the rendered video.
        const wrapper = video.closest('.coach-review-wrapper, .feedback-player-wrapper');
        if (wrapper && typeof ResizeObserver === 'function') {
            const ro = new ResizeObserver(resize);
            ro.observe(wrapper);
            canvas._coachResizeObserver = ro;
        }
        canvas.addEventListener('pointerdown', (event) => this.coachDrawStart(event));
        canvas.addEventListener('pointermove', (event) => this.coachDrawMove(event));
        canvas.addEventListener('pointerup', (event) => this.coachDrawEnd(event));
        canvas.addEventListener('pointerleave', (event) => this.coachDrawEnd(event));
        canvas._coachBound = true;
        canvas._coachResize = resize;
        resize();
    },

    _resizeCoachCanvas(canvas, video) {
        const rect = video.getBoundingClientRect();
        canvas.width = Math.max(1, Math.round(rect.width));
        canvas.height = Math.max(1, Math.round(rect.height));
        this.paintCoachCanvas();
    },

    _syncCoachReviewSideHeight(video) {
        // Match the right inspector's max-height to the video wrapper's
        // current rendered height so they always look like sibling columns
        // of equal height. Only applies in Review mode; the feedback modal
        // doesn't need it. Skip on narrow viewports where the layout is
        // already single-column, and skip when the Review sub-tab isn't the
        // active one (the global resize handler in setCoachTab fires on every
        // tab — relying solely on null DOM lookups would still work today but
        // the explicit gate survives any future refactor of tab visibility).
        if (window.innerWidth < 1024) return;
        if (this._coachTab !== 'review') return;
        const wrapper = video.closest('.coach-review-wrapper');
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (!wrapper || !side) return;
        const h = Math.round(wrapper.getBoundingClientRect().height);
        if (h > 0) side.style.maxHeight = `${h}px`;
    },

    /** Phase 6d-2 follow-up — tactical-mode counterpart to
     *  `_syncCoachReviewSideHeight`. The `.coach-review-stage` column
     *  (which contains the pitch + status row) takes the same role
     *  the video wrapper plays in video mode: the right inspector's
     *  max-height is set to match the stage's current rendered height
     *  so the two columns are equal-height on every viewport, with no
     *  dead space at the bottom of either side.
     *
     *  We sync from the stage (`.coach-review-stage`) rather than the
     *  inner board canvas because the stage carries the pitch + the
     *  tiny status pill below it, and the user's expectation is that
     *  the inspector matches the visible LEFT column edge-to-edge.
     *
     *  Wired up at mount time via a ResizeObserver on the stage; the
     *  observer is cleaned up in `_unmountCoachReviewBoard`. */
    _syncCoachReviewSideHeightFromBoard() {
        if (this._coachTab !== 'review') return;
        if (this._coachReviewSource !== 'tactical_board') return;
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (!side) return;
        // On narrow viewports the layout is single-column and there's
        // no separate side rail to clamp; clear any stale max-height
        // from a prior wide-viewport sync so the column stays its
        // natural size when the viewport is resized down.
        if (window.innerWidth < 1024) {
            if (side.style.maxHeight) side.style.maxHeight = '';
            return;
        }
        const stage = document.querySelector('#coach-tab-review .coach-review-stage');
        if (!stage) return;
        const h = Math.round(stage.getBoundingClientRect().height);
        if (h > 0) side.style.maxHeight = `${h}px`;
    },

    // Detach the global resize listener registered by setupCoachCanvas.
    // The Review tab's canvas is persistent in the DOM, so this is only
    // needed for the feedback player modal whose canvas is removed when
    // the modal closes — without this the closure stays attached to
    // window, leaking the canvas it captured.
    teardownCoachCanvasListeners(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !canvas._coachResize) return;
        window.removeEventListener('resize', canvas._coachResize);
        if (canvas._coachResizeObserver) {
            canvas._coachResizeObserver.disconnect();
            canvas._coachResizeObserver = null;
        }
        canvas._coachResize = null;
        canvas._coachBound = false;
    },

    activateCoachCanvas() {
        this.setupCoachCanvas();
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = true;
        canvas.style.display = 'block';
        canvas.style.pointerEvents = 'auto';
        this.updateCoachCanvasToggleLabel();
    },

    deactivateCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = false;
        canvas.style.display = this._coachDrawing ? 'block' : 'none';
        canvas.style.pointerEvents = 'none';
        this.updateCoachCanvasToggleLabel();
    },

    updateCoachCanvasToggleLabel() {
        document.querySelectorAll('[data-coach-canvas-toggle]').forEach((btn) => {
            btn.textContent = `Canvas ${this._coachDrawingActive ? 'On' : 'Off'}`;
            btn.setAttribute('aria-pressed', this._coachDrawingActive ? 'true' : 'false');
        });
    },

    normalizeCoachDrawing(drawing) {
        if (!drawing) return null;
        if (drawing.version === 2 && Array.isArray(drawing.objects)) return { version: 2, objects: [...drawing.objects] };
        if (Array.isArray(drawing.strokes)) {
            return {
                version: 2,
                objects: drawing.strokes.map((stroke) => ({
                    type: 'freehand',
                    color: stroke.color || '#38bdf8',
                    width: stroke.width || 3,
                    points: stroke.points || [],
                })),
            };
        }
        return null;
    },

    ensureCoachDrawing() {
        if (!this._coachDrawing || this._coachDrawing.version !== 2) {
            this._coachDrawing = this.normalizeCoachDrawing(this._coachDrawing) || { version: 2, objects: [] };
        }
        if (!Array.isArray(this._coachDrawing.objects)) this._coachDrawing.objects = [];
        return this._coachDrawing;
    },

    toggleCoachDrawing() {
        if (this._coachDrawingActive) this.deactivateCoachCanvas();
        else this.activateCoachCanvas();
    },

    setCoachDrawingTool(tool) {
        // Switching away from formation mid-draft discards the in-progress
        // anchors; the user can restart by re-selecting Formation.
        if (this._coachDrawingTool === 'formation' && tool !== 'formation') {
            this._coachFormationDraft = null;
        }
        this._coachDrawingTool = tool;
        document.querySelectorAll('[data-coach-tool]').forEach((btn) => {
            const active = btn.dataset.coachTool === tool;
            btn.classList.toggle('active', active);
            // Sprint 3: keep aria-pressed in sync with the visual active
            // state so screen readers announce the toggle change without
            // re-rendering the toolbar.
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        this._renderFormationControls();
        this.activateCoachCanvas();
        this.paintCoachCanvas();
    },

    setCoachDrawingColor(color) {
        this._coachDrawingColor = color;
        document.querySelectorAll('[data-coach-color]').forEach((btn) => {
            const active = btn.dataset.coachColor === color;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    },

    setCoachDrawingWidth(width) {
        this._coachDrawingWidth = Math.max(2, Math.min(10, Number(width || 3)));
    },

    coachDrawPoint(event) {
        const canvas = document.getElementById(this._coachCanvasId);
        const rect = canvas.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) / Math.max(1, rect.width),
            y: (event.clientY - rect.top) / Math.max(1, rect.height),
        };
    },

    coachDrawStart(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const drawing = this.ensureCoachDrawing();
        const point = this.coachDrawPoint(event);
        if (this._coachDrawingTool === 'formation') {
            if (!this._coachFormationDraft) {
                this._coachFormationDraft = {
                    mode: this._coachFormationMode || 'quick',
                    anchors: [],
                    queuedPlayerIds: [],
                };
                this._renderFormationControls();
            }
            const draft = this._coachFormationDraft;
            if (draft.anchors.length >= 16) {
                this.showError?.('A formation can hold at most 16 players.');
                return;
            }
            const anchor = { x: point.x, y: point.y };
            if (draft.mode === 'linked' && draft.queuedPlayerIds.length) {
                const pid = draft.queuedPlayerIds.shift();
                const p = (this._coachBundle?.players || []).find((pl) => String(pl.id) === String(pid));
                if (p) {
                    anchor.player_id = String(p.id);
                    anchor.label = String(p.jersey_number || (p.display_name || '?').slice(0, 1)).toUpperCase().slice(0, 8);
                }
            }
            draft.anchors.push(anchor);
            this._renderFormationDraftPreview();
            return;
        }
        if (this._coachDrawingTool === 'select') {
            const index = this.hitCoachDrawingObject(point);
            this._coachSelectedObjectIndex = index;
            this._coachDragState = index === null ? null : { index, start: point };
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'label') {
            const text = document.getElementById('coach-label-text')?.value.trim() || 'Player';
            drawing.objects.push({ type: 'label', color: this._coachDrawingColor, x: point.x, y: point.y, text });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'dim') {
            drawing.objects.push({ type: 'dim', opacity: 0.45 });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        let object = null;
        if (this._coachDrawingTool === 'freehand') {
            object = { type: 'freehand', color: this._coachDrawingColor, width: this._coachDrawingWidth, points: [point] };
        } else if (this._coachDrawingTool === 'arrow') {
            object = { type: 'arrow', color: this._coachDrawingColor, width: this._coachDrawingWidth, x1: point.x, y1: point.y, x2: point.x, y2: point.y };
        } else if (this._coachDrawingTool === 'spotlight') {
            object = { type: 'spotlight', color: this._coachDrawingColor, width: this._coachDrawingWidth,
                       x: Math.max(0, point.x - 0.08), y: Math.max(0, point.y - 0.08), w: 0.16, h: 0.16 };
        } else if (['circle', 'zone'].includes(this._coachDrawingTool)) {
            object = { type: this._coachDrawingTool, color: this._coachDrawingColor, width: this._coachDrawingWidth, x: point.x, y: point.y, w: 0.001, h: 0.001 };
        }
        if (!object) return;
        drawing.objects.push(object);
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._coachCurrentObject = { object, start: point };
        this.paintCoachCanvas();
    },

    coachDrawMove(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const point = this.coachDrawPoint(event);
        if (this._coachDragState) {
            const object = this._coachDrawing?.objects?.[this._coachDragState.index];
            if (object) {
                const dx = point.x - this._coachDragState.start.x;
                const dy = point.y - this._coachDragState.start.y;
                this.moveCoachDrawingObject(object, dx, dy);
                this._coachDragState.start = point;
            }
            this.paintCoachCanvas();
            return;
        }
        if (!this._coachCurrentObject) return;
        const { object, start } = this._coachCurrentObject;
        if (object.type === 'freehand') {
            object.points.push(point);
        } else if (object.type === 'arrow') {
            object.x2 = point.x;
            object.y2 = point.y;
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            const minSize = object.type === 'spotlight' ? 0.08 : 0.001;
            const w = Math.max(minSize, Math.abs(point.x - start.x));
            const h = Math.max(minSize, Math.abs(point.y - start.y));
            object.x = Math.min(start.x, point.x);
            object.y = Math.min(start.y, point.y);
            object.w = w;
            object.h = h;
        }
        this.paintCoachCanvas();
    },

    coachDrawEnd(event) {
        if (event?.target?.releasePointerCapture && event.pointerId !== undefined) {
            try { event.target.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
        }
        this._coachCurrentObject = null;
        this._coachDragState = null;
    },

    paintCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const drawing = this.normalizeCoachDrawing(this._coachDrawing);
        const objects = drawing?.objects || [];
        objects.forEach((object, index) => {
            this.paintCoachObject(ctx, canvas, object);
            if (index === this._coachSelectedObjectIndex) this.paintCoachSelection(ctx, canvas, object);
        });
    },

    paintCoachObject(ctx, canvas, object) {
        const color = object.color || '#38bdf8';
        const width = object.width || 3;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        if (object.type === 'dim') {
            ctx.fillStyle = `rgba(0, 0, 0, ${object.opacity ?? 0.45})`;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else if (object.type === 'freehand') {
            ctx.beginPath();
            (object.points || []).forEach((pt, idx) => {
                const x = pt.x * canvas.width;
                const y = pt.y * canvas.height;
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
        } else if (object.type === 'arrow') {
            const x1 = object.x1 * canvas.width;
            const y1 = object.y1 * canvas.height;
            const x2 = object.x2 * canvas.width;
            const y2 = object.y2 * canvas.height;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
            const angle = Math.atan2(y2 - y1, x2 - x1);
            const head = 14 + width;
            ctx.beginPath();
            ctx.moveTo(x2, y2);
            ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
            ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
            ctx.closePath();
            ctx.fill();
        } else if (object.type === 'circle' || object.type === 'spotlight') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const w = object.w * canvas.width;
            const h = object.h * canvas.height;
            if (object.type === 'spotlight') {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.48)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                ctx.beginPath();
                ctx.ellipse(x + w / 2, y + h / 2, Math.max(8, w / 2), Math.max(8, h / 2), 0, 0, Math.PI * 2);
                ctx.fill();
                ctx.globalCompositeOperation = 'source-over';
                ctx.strokeStyle = color;
            }
            ctx.beginPath();
            ctx.ellipse(x + w / 2, y + h / 2, Math.max(4, w / 2), Math.max(4, h / 2), 0, 0, Math.PI * 2);
            ctx.stroke();
        } else if (object.type === 'zone') {
            ctx.strokeRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
            ctx.globalAlpha = 0.14;
            ctx.fillRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
        } else if (object.type === 'label') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const text = object.text || 'Player';
            ctx.font = '700 18px system-ui, sans-serif';
            const metrics = ctx.measureText(text);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
            ctx.fillRect(x - 6, y - 22, metrics.width + 12, 28);
            ctx.fillStyle = color;
            ctx.fillText(text, x, y);
        } else if (object.type === 'formation') {
            const anchors = object.anchors || [];
            const hullPts = object.hull_points || [];
            // One dim layer per formation, then cut spotlight holes at every
            // anchor with destination-out (mirrors the existing `spotlight`
            // tool's pattern; stacking dims per-anchor would compound).
            if (anchors.length) {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.42)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                anchors.forEach((a) => {
                    ctx.beginPath();
                    ctx.arc(a.x * canvas.width, a.y * canvas.height, 22, 0, Math.PI * 2);
                    ctx.fill();
                });
                ctx.globalCompositeOperation = 'source-over';
            }
            // Outline + label badge per anchor
            anchors.forEach((a, idx) => {
                const x = a.x * canvas.width, y = a.y * canvas.height;
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(x, y, 22, 0, Math.PI * 2);
                ctx.stroke();
                const label = (a.label && String(a.label)) || String(idx + 1);
                ctx.font = '700 12px system-ui, sans-serif';
                const m = ctx.measureText(label);
                ctx.fillStyle = 'rgba(0, 0, 0, 0.78)';
                ctx.fillRect(x - m.width / 2 - 5, y - 38, m.width + 10, 18);
                ctx.fillStyle = color;
                ctx.fillText(label, x - m.width / 2, y - 25);
            });
            // Convex hull polygon — translucent fill + crisp stroke
            if (hullPts.length >= 3) {
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                hullPts.forEach((p, idx) => {
                    const x = p.x * canvas.width, y = p.y * canvas.height;
                    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.save();
                ctx.globalAlpha = 0.18;
                ctx.fillStyle = color;
                ctx.fill();
                ctx.restore();
                ctx.stroke();
            }
        }
        ctx.restore();
    },

    paintCoachSelection(ctx, canvas, object) {
        const box = this.coachObjectBounds(object);
        if (!box) return;
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeRect(box.x * canvas.width, box.y * canvas.height, box.w * canvas.width, box.h * canvas.height);
        ctx.restore();
    },

    coachObjectBounds(object) {
        if (!object) return null;
        if (object.type === 'arrow') {
            const x = Math.min(object.x1, object.x2);
            const y = Math.min(object.y1, object.y2);
            return { x, y, w: Math.abs(object.x2 - object.x1) || 0.02, h: Math.abs(object.y2 - object.y1) || 0.02 };
        }
        if (['circle', 'zone', 'spotlight'].includes(object.type)) return { x: object.x, y: object.y, w: object.w, h: object.h };
        if (object.type === 'label') return { x: object.x, y: Math.max(0, object.y - 0.08), w: 0.12, h: 0.08 };
        if (object.type === 'freehand') {
            const points = object.points || [];
            if (!points.length) return null;
            const xs = points.map((p) => p.x);
            const ys = points.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.02, Math.max(...xs) - x), h: Math.max(0.02, Math.max(...ys) - y) };
        }
        if (object.type === 'dim') return { x: 0, y: 0, w: 1, h: 1 };
        if (object.type === 'formation') {
            const pts = (object.hull_points || []).concat(object.anchors || []);
            if (!pts.length) return null;
            const xs = pts.map((p) => p.x);
            const ys = pts.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.04, Math.max(...xs) - x), h: Math.max(0.04, Math.max(...ys) - y) };
        }
        return null;
    },

    hitCoachDrawingObject(point) {
        const objects = this._coachDrawing?.objects || [];
        for (let i = objects.length - 1; i >= 0; i -= 1) {
            const box = this.coachObjectBounds(objects[i]);
            if (!box) continue;
            const pad = 0.025;
            if (point.x >= box.x - pad && point.x <= box.x + box.w + pad &&
                point.y >= box.y - pad && point.y <= box.y + box.h + pad) {
                return i;
            }
        }
        return null;
    },

    moveCoachDrawingObject(object, dx, dy) {
        const clamp = (value) => Math.max(0, Math.min(1, value));
        if (object.type === 'freehand') {
            object.points = (object.points || []).map((pt) => ({ x: clamp(pt.x + dx), y: clamp(pt.y + dy) }));
        } else if (object.type === 'arrow') {
            object.x1 = clamp(object.x1 + dx); object.y1 = clamp(object.y1 + dy);
            object.x2 = clamp(object.x2 + dx); object.y2 = clamp(object.y2 + dy);
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'label') {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'formation') {
            (object.anchors || []).forEach((a) => {
                a.x = clamp(a.x + dx);
                a.y = clamp(a.y + dy);
            });
            (object.hull_points || []).forEach((p) => {
                p.x = clamp(p.x + dx);
                p.y = clamp(p.y + dy);
            });
        }
    },

    undoCoachDrawing() {
        const drawing = this.ensureCoachDrawing();
        drawing.objects.pop();
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    deleteSelectedCoachObject() {
        const drawing = this.ensureCoachDrawing();
        if (this._coachSelectedObjectIndex === null || this._coachSelectedObjectIndex === undefined) return;
        drawing.objects.splice(this._coachSelectedObjectIndex, 1);
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    clearCoachDrawing() {
        this._coachDrawing = null;
        this._coachSelectedObjectIndex = null;
        this._coachFormationDraft = null;
        this._renderFormationControls?.();
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    renderCoachDrawing(drawing) {
        this._coachDrawing = this.normalizeCoachDrawing(drawing);
        this._coachSelectedObjectIndex = null;
        const canvas = document.getElementById(this._coachCanvasId);
        if (canvas) canvas.style.display = this._coachDrawing ? 'block' : (this._coachDrawingActive ? 'block' : 'none');
        if (canvas) canvas.style.pointerEvents = this._coachDrawingActive ? 'auto' : 'none';
        this.setupCoachCanvas();
        const video = document.getElementById(this._coachVideoId);
        if (canvas && video) {
            const rect = video.getBoundingClientRect();
            canvas.width = Math.max(1, Math.round(rect.width));
            canvas.height = Math.max(1, Math.round(rect.height));
        }
        this.paintCoachCanvas();
    },

    // ===== Formation overlay (multi-player highlight + convex hull) =====

    setCoachFormationMode(mode) {
        this._coachFormationMode = (mode === 'linked') ? 'linked' : 'quick';
        if (this._coachFormationDraft) {
            this._coachFormationDraft.mode = this._coachFormationMode;
            // Switching mode discards any queued (unconsumed) player selections.
            this._coachFormationDraft.queuedPlayerIds = [];
        }
        this._renderFormationControls();
    },

    queueFormationPlayer(playerId) {
        if (!this._coachFormationDraft) {
            this._coachFormationDraft = { mode: this._coachFormationMode || 'quick', anchors: [], queuedPlayerIds: [] };
        }
        const id = String(playerId);
        const queue = this._coachFormationDraft.queuedPlayerIds;
        const at = queue.indexOf(id);
        if (at >= 0) queue.splice(at, 1); else queue.push(id);
        this._renderFormationControls();
    },

    cancelFormation() {
        this._coachFormationDraft = null;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    finalizeFormation() {
        const draft = this._coachFormationDraft;
        if (!draft || draft.anchors.length < 3) {
            this.showError?.('A formation needs at least 3 anchor points.');
            return;
        }
        const hull = this._computeConvexHull(draft.anchors);
        // Andrew's monotone-chain returns < 3 points only when every anchor
        // is collinear (the algorithm pops collinear interior points and
        // both endpoints). The painter and the backend validator both
        // require a 3+ point polygon, so reject early with a coach-readable
        // message instead of silently saving a hull-less formation.
        if (hull.length < 3) {
            this.showError?.('Formation anchors are collinear — nudge one off the line so the hull has area.');
            return;
        }
        const drawing = this.ensureCoachDrawing();
        drawing.objects.push({
            type: 'formation',
            color: this._coachDrawingColor,
            width: this._coachDrawingWidth,
            anchors: draft.anchors.map((a) => ({ ...a })),
            hull_points: hull,
        });
        this._coachFormationDraft = null;
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    // Andrew's monotone-chain convex hull (counter-clockwise, no duplicates).
    // Inputs and outputs are normalized 0..1 {x, y} points.
    _computeConvexHull(points) {
        if (!Array.isArray(points) || points.length < 3) return points.slice();
        const pts = points.map((p) => ({ x: Number(p.x) || 0, y: Number(p.y) || 0 }))
            .sort((a, b) => (a.x - b.x) || (a.y - b.y));
        const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
        const lower = [];
        for (const p of pts) {
            while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
            lower.push(p);
        }
        const upper = [];
        for (let i = pts.length - 1; i >= 0; i -= 1) {
            const p = pts[i];
            while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
            upper.push(p);
        }
        upper.pop(); lower.pop();
        return lower.concat(upper);
    },

    // Repaint the in-progress draft on top of the existing canvas paint —
    // shows the user where they've clicked before they hit Done.
    _renderFormationDraftPreview() {
        this.paintCoachCanvas();
        const draft = this._coachFormationDraft;
        if (!draft || !draft.anchors.length) return;
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const color = this._coachDrawingColor || '#38bdf8';
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        draft.anchors.forEach((a, idx) => {
            const x = a.x * canvas.width, y = a.y * canvas.height;
            ctx.beginPath();
            ctx.arc(x, y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.font = '700 11px system-ui, sans-serif';
            ctx.fillText(a.label || String(idx + 1), x + 12, y - 6);
        });
        ctx.restore();
        this._renderFormationControls();
    },

    // Render the per-tool controls panel beneath the toolbar. Hidden when
    // any tool other than Formation is active.
    _renderFormationControls() {
        const el = document.getElementById('coach-formation-controls');
        if (!el) return;
        if (this._coachDrawingTool !== 'formation') {
            el.hidden = true;
            el.innerHTML = '';
            return;
        }
        el.hidden = false;
        const draft = this._coachFormationDraft;
        const anchorCount = draft?.anchors?.length || 0;
        const mode = this._coachFormationMode || 'quick';
        const players = this._coachBundle?.players || [];
        const queued = new Set((draft?.queuedPlayerIds || []).map(String));
        const queueOrderFor = (pid) => {
            const list = draft?.queuedPlayerIds || [];
            const at = list.findIndex((q) => String(q) === String(pid));
            return at >= 0 ? at + 1 : null;
        };
        const linkedRoster = mode === 'linked'
            ? `<div class="coach-formation-roster" role="listbox" aria-label="Players to anchor">
                 ${players.length
                    ? players.map((p) => {
                        const order = queueOrderFor(p.id);
                        const sel = queued.has(String(p.id));
                        return `<button type="button" class="coach-check-option ${sel ? 'is-selected' : ''}"
                                    aria-pressed="${sel}" onclick="app.queueFormationPlayer('${this.esc(p.id)}')">
                                    <span class="coach-check-box" aria-hidden="true">${order || ''}</span>
                                    <span class="coach-check-label">${this.esc(this.playerLabel(p))}</span>
                                </button>`;
                    }).join('')
                    : '<div class="coach-check-empty">No roster players yet.</div>'}
               </div>
               <p class="coach-formation-hint">Tap players in the order you want to place them, then click their position on the field.</p>`
            : '<p class="coach-formation-hint">Click each player’s position on the freeze frame, then press Done.</p>';
        el.innerHTML = `
            <div class="coach-formation-head">
                <strong>Formation</strong>
                <div class="coach-formation-modes" role="tablist">
                    <button type="button" role="tab" aria-selected="${mode === 'quick'}"
                        class="mini-action-btn ${mode === 'quick' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('quick')">Quick</button>
                    <button type="button" role="tab" aria-selected="${mode === 'linked'}"
                        class="mini-action-btn ${mode === 'linked' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('linked')">Linked</button>
                </div>
            </div>
            ${linkedRoster}
            <div class="coach-formation-actions">
                <span class="coach-formation-count">${anchorCount} anchor${anchorCount === 1 ? '' : 's'} (min 3, max 16)</span>
                <button type="button" class="mini-action-btn" onclick="app.cancelFormation()" ${draft ? '' : 'disabled'}>Cancel</button>
                <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.finalizeFormation()" ${anchorCount >= 3 ? '' : 'disabled'}>Done</button>
            </div>
        `;
    },

    // ===== /feedback view =====

    async renderMyFeedback() {
        const linkedStrip = document.getElementById('feedback-linked-strip');
        const playlistsList = document.getElementById('feedback-playlists-list');
        const notesList = document.getElementById('feedback-notes-list');
        const clipsList = document.getElementById('feedback-clips-list');
        const summariesList = document.getElementById('feedback-summaries-list');
        if (linkedStrip) linkedStrip.innerHTML = '';
        if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (notesList) notesList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (clipsList) clipsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (summariesList) summariesList.innerHTML = '<div class="session-empty">Loading…</div>';
        try {
            const data = await this.loadMyFeedback();
            this._feedbackData = data;
            this.renderFeedbackLinkedStrip(data);
            this.renderFeedbackPlaylists(data);
            this.renderFeedbackNotes(data);
            this.renderFeedbackClips(data);
            this.renderFeedbackMatchSummaries(data);
        } catch (err) {
            if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Could not load feedback.</div>';
            if (notesList) notesList.innerHTML = '';
            if (clipsList) clipsList.innerHTML = '';
            if (summariesList) summariesList.innerHTML = '';
            this.showError(err.message);
        }
    },

    renderFeedbackLinkedStrip(data) {
        const el = document.getElementById('feedback-linked-strip');
        if (!el) return;
        const players = data?.players || [];
        if (!players.length) {
            el.innerHTML = '<span class="feedback-linked-empty">No roster player is linked to your account yet. Ask a coach to link you.</span>';
            return;
        }
        el.innerHTML = `<span class="feedback-linked-label">Linked players:</span>` + players.map((p) => `<span class="feedback-linked-pill">${this.esc(this.playerLabel(p))}</span>`).join('');
    },

    /** PR 1c — viewer-facing "summary" for a coaching note. The player-
     *  facing text is `player_summary` when present (the short, age-
     *  appropriate version the coach wrote in the composer), with a
     *  fallback to `body` for legacy notes that pre-date Phase 1. The
     *  long-form `body` is also surfaced when both are non-empty so the
     *  coach can write a polished one-line summary without losing their
     *  longer note. */
    _feedbackNoteSummary(note) {
        const summary = (note?.player_summary || '').trim();
        const body = (note?.body || '').trim();
        if (summary && body && summary !== body) return { primary: summary, secondary: body };
        if (summary) return { primary: summary, secondary: '' };
        return { primary: body, secondary: '' };
    },

    /** PR 1c — tone pill HTML for My Feedback. Coach-facing chip labels
     *  are short ("Team", "Goal"); player-facing labels are written out
     *  for clarity ("Team concept", "Individual goal"). The `data-tone`
     *  attribute drives the pill's accent colour. Returns `''` when the
     *  note has no `note_type` (defensive — every note post-v9 has one
     *  but a legacy export might not). */
    _feedbackTonePillHtml(noteType) {
        const label = FEEDBACK_NOTE_TYPE_LABELS[noteType];
        if (!label) return '';
        return `<span class="feedback-tone-pill" data-tone="${this.esc(noteType)}">${this.esc(label)}</span>`;
    },

    /** PR 1c — structured what / why / next stack. Renders only the
     *  fields that are non-empty so a simple note (with only
     *  `player_summary`) still feels lightweight. `coach_private_note`
     *  is NEVER rendered here; the server scrubs it for viewers
     *  (`_strip_private_fields`) but we also do not template it client-
     *  side as defense-in-depth. */
    _feedbackStructuredHtml(note) {
        const items = [
            ['What happened',     note?.what_happened],
            ['Why it matters',    note?.why_it_matters],
            ['What to do next',   note?.what_to_do_next],
        ].filter(([, v]) => (v || '').trim());
        if (!items.length) return '';
        return `
            <dl class="feedback-structured">
                ${items.map(([label, value]) => `
                    <div class="feedback-structured-item">
                        <dt>${this.esc(label)}</dt>
                        <dd>${this.esc(value.trim())}</dd>
                    </div>
                `).join('')}
            </dl>`;
    },

    /** Render the Playlists tab as a responsive grid of self-contained
     *  cards. Each card shows the playlist's title, clip count,
     *  description, and a Play session / Mark reviewed action row.
     *  Click "Play session" → `openFeedbackPlaylist()` opens the
     *  focused modal (same player used by the rest of the app). */
    renderFeedbackPlaylists(data) {
        const container = document.getElementById('feedback-playlists-list');
        if (!container) return;
        const playlists = data?.playlists || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.playlist_id).map((r) => Number(r.playlist_id)));
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists have been shared with you yet.</div>';
            return;
        }
        // Phase 3b: feedback playlists embed their items under
        // `playlists[].items[]` (server `_playlists_with_items`), each
        // already scrubbed of `coach_private_note`. The cover thumbnail
        // is the first item whose standalone thumbnail the viewer can
        // actually load — see `_resolveFeedbackPlaylistCover` below.
        // PR #92 review follow-up: previously we hard-pinned to
        // `items[0]`, which meant a private-first-item playlist always
        // showed the placeholder cover even when later items had
        // viewer-accessible thumbnails. Walking the list fixes that
        // without weakening the standalone GET endpoint's auth model.
        container.innerHTML = playlists.map((p) => {
            const isReviewed = reviewed.has(Number(p.id));
            const clipCount = p.note_ids?.length || p.items?.length || 0;
            // Always render a placeholder tile first so layout is
            // stable while the cover-resolver runs. The
            // `data-feedback-cover-playlist` attribute lets the
            // resolver find this <img> without holding a DOM ref.
            const coverThumb = `
                <div class="coach-thumb coach-thumb--card" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                    <img class="coach-thumb-img" data-feedback-cover-playlist="${Number(p.id)}" alt="" loading="lazy" decoding="async">
                </div>
            `;
            return `
            <article class="feedback-card feedback-playlist-card feedback-card--with-thumb">
                ${coverThumb}
                <div class="feedback-card-body">
                    <span class="feedback-card-kicker">Review Session</span>
                    <h3 class="feedback-card-title">${this.esc(p.title)}</h3>
                    <div class="feedback-card-meta">${clipCount} clip${clipCount === 1 ? '' : 's'} · ${isReviewed ? 'Reviewed' : 'New'}</div>
                    ${p.description ? `<p class="feedback-card-description">${this.esc(p.description)}</p>` : ''}
                    <div class="feedback-card-actions">
                        <button type="button" class="btn-primary" onclick="app.openFeedbackPlaylist(${p.id})">▶ Play session</button>
                        <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">${isReviewed ? 'Reviewed ✓' : 'Mark reviewed'}</button>
                    </div>
                </div>
            </article>`;
        }).join('');
        // Kick off cover resolution for each playlist in parallel —
        // each playlist walks its own items[] until one returns a
        // non-null thumbnail URL. Failures stay as placeholders.
        for (const p of playlists) {
            this._resolveFeedbackPlaylistCover(container, p);
        }
    },

    /** Phase 3b PR #92 review follow-up — walk `playlist.items[]` until
     *  we find one whose standalone thumbnail actually loads, then
     *  assign that URL to the playlist's cover `<img>`. The standalone
     *  endpoint deliberately doesn't honour the playlist-grants-access
     *  rule for private items (per CLAUDE.md), so a private item
     *  returns null here and we fall through to the next item. If
     *  every item fails, the placeholder remains in place — which is
     *  the correct "no cover available" state.
     *
     *  Sequential rather than `Promise.all` so a long playlist stops
     *  fetching as soon as a cover is found, and so we don't race
     *  multiple winners onto the same `<img>`. */
    async _resolveFeedbackPlaylistCover(container, playlist) {
        if (!container || !playlist) return;
        const items = playlist.items || [];
        if (!items.length) return;
        const imgEl = container.querySelector(
            `img[data-feedback-cover-playlist="${Number(playlist.id)}"]`
        );
        if (!imgEl) return;
        for (const item of items) {
            // Check the cache via loadCoachNoteThumbnail; on a hit it
            // resolves immediately. On a miss it goes through the same
            // auth-bearing fetch + negative-cache path used everywhere
            // else, so subsequent renders short-circuit.
            const url = await this.loadCoachNoteThumbnail(item?.id);
            if (!url) continue;
            // The container may have re-rendered (or the user navigated
            // away) before this cover resolved. Bail if so.
            if (!imgEl.isConnected) return;
            imgEl.src = url;
            imgEl.dataset.thumbState = 'loaded';
            const wrapper = imgEl.closest('[data-thumb]');
            if (wrapper) wrapper.dataset.thumbState = 'loaded';
            return;
        }
        // All items failed → placeholder stays as-is. Nothing else to do.
    },

    /** Render the Notes tab as a responsive grid of self-contained
     *  cards. Each card shows tone pill, title, match/timestamp meta,
     *  player_summary (or body fallback), the structured what / why /
     *  next stack, optional Coach context disclosure, and a Watch /
     *  Mark reviewed action row. Click "Watch" → `openFeedbackNote()`
     *  opens the focused modal with telestration. */
    renderFeedbackNotes(data) {
        const container = document.getElementById('feedback-notes-list');
        if (!container) return;
        const notes = data?.notes || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.note_id).map((r) => Number(r.note_id)));
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes have been shared with you yet.</div>';
            return;
        }
        // Cards are intentionally compact: thumb + tone + title + meta
        // only. No inline summary, no inline board, no row of action
        // buttons. Clicking the card opens the unified detail/playback
        // modal (`openFeedbackNote(id)`) which is the single review
        // surface — same layout for video, observation, and tactical-
        // board notes — so a viewer always lands in one consistent UI.
        container.innerHTML = notes.map((n) => {
            const isReviewed = reviewed.has(Number(n.id));
            const isObservation = (n.note_context || 'video') === 'observation';
            const tonePill = this._feedbackTonePillHtml(n.note_type);
            // Observation notes have no match/slot/timestamp anchor — use
            // event metadata so the meta line never shows "null · 0:00".
            const metaParts = [];
            if (isObservation) {
                if (n.event_type) {
                    const typeLabel = `${n.event_type[0].toUpperCase()}${n.event_type.slice(1)}`;
                    metaParts.push(`${typeLabel} observation`);
                } else {
                    metaParts.push('Observation');
                }
                if (n.event_date) metaParts.push(n.event_date);
            } else {
                metaParts.push(this.matchLabel(n.match_id));
                metaParts.push(this.formatClock(n.timestamp_seconds));
            }
            metaParts.push(isReviewed ? 'Reviewed' : 'New');
            const meta = metaParts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
            const titleText = (n.title || '').trim()
                || (isObservation ? ((n.event_title || '').trim() || 'Observation note') : '(untitled)');
            // Thumbnail variants:
            //  - video note: source-video JPEG via the auth-checked
            //    thumbnail mount
            //  - observation with tactical board: compact SVG chip of
            //    the board
            //  - observation without board: clipboard glyph placeholder
            const hasBoard = isObservation && this.tacticalBoardHasContent(n.tactical_board_json);
            const thumb = isObservation
                ? (hasBoard
                    ? `<div class="coach-thumb coach-thumb--card coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(n.tactical_board_json, { size: 'chip' })}</div>`
                    : '<div class="coach-thumb coach-thumb--card coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
                : this._coachNoteThumbHtml(n, { size: 'card' });
            return `
            <article class="feedback-card feedback-note-card feedback-card--with-thumb feedback-card--clickable" data-note-context="${isObservation ? 'observation' : 'video'}" tabindex="0" role="button" aria-label="Open ${this.esc(titleText)}" onclick="app.openFeedbackNote(${n.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackNote(${n.id});}">
                ${thumb}
                <div class="feedback-card-body">
                    <div class="feedback-card-head">
                        ${tonePill}
                        ${isReviewed ? '<span class="feedback-card-status">Reviewed ✓</span>' : ''}
                    </div>
                    <h3 class="feedback-card-title">${this.esc(titleText)}</h3>
                    <div class="feedback-card-meta">${meta}</div>
                </div>
            </article>`;
        }).join('');
        // Phase 3b: viewer-side mount uses the same authenticated fetch
        // path. Visibility is enforced server-side per-note — a viewer
        // who can't see a note will get a 404 from the endpoint and
        // we'll render the placeholder. No client-side filtering needed.
        this.mountCoachNoteThumbnailsIn(container);
    },

    /** Open the unified feedback review modal for a note. The same
     *  modal handles both video notes (with HLS playback + telestration)
     *  and observation notes (with a read-only tactical board where the
     *  video would be); the body always shows the same structured-field
     *  layout so a viewer never sees three different shells across the
     *  three review types. */
    openFeedbackNote(noteId) {
        const note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) {
            this.showError('Note not available.');
            return;
        }
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    openFeedbackPlaylist(playlistId) {
        const playlist = (this._feedbackData?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'feedback' });
    },

    /** Phase 4b — render the My Feedback Clips tab. Clips are
     *  server-filtered by visibility before they ever reach the
     *  client (`/api/my-feedback`'s `clips[]` already excludes
     *  private clips and player-tagged clips for unrelated viewers).
     *  No client-side authorization here — same model as Notes /
     *  Playlists.
     *
     *  Card layout mirrors `renderFeedbackNotes`: thumbnail (from the
     *  source note when available, otherwise placeholder) + title +
     *  meta (match · slot · window · duration · category) + optional
     *  description + Watch button. */
    renderFeedbackClips(data) {
        const container = document.getElementById('feedback-clips-list');
        if (!container) return;
        const clips = data?.clips || [];
        if (!clips.length) {
            container.innerHTML = '<div class="session-empty">No coaching clips have been shared with you yet.</div>';
            return;
        }
        // Compact clip cards — thumb + clip pill + title + meta. The
        // description, structured fields, and Watch/Mark-reviewed live
        // inside the unified detail modal that opens on card click,
        // matching the notes/observations behaviour so the viewer never
        // sees three different layouts for three review types.
        container.innerHTML = clips.map((c) => {
            const meta = `${this.esc(this.matchLabel(c.match_id))} · `
                + `${this.esc(this.formatClock(c.start_seconds))}–${this.esc(this.formatClock(c.end_seconds))} `
                + `(${this.esc(this._clipDurationLabel(c))})`;
            return `
            <article class="feedback-card feedback-clip-card feedback-card--with-thumb feedback-card--clickable" tabindex="0" role="button" aria-label="Open ${this.esc(c.title)}" onclick="app.openFeedbackClip(${c.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackClip(${c.id});}">
                ${this._coachClipThumbHtml(c)}
                <div class="feedback-card-body">
                    <div class="feedback-card-head">
                        <span class="feedback-clip-pill">Clip · ${this.esc(c.category || 'other')}</span>
                    </div>
                    <h3 class="feedback-card-title">${this.esc(c.title)}</h3>
                    <div class="feedback-card-meta">${meta}</div>
                </div>
            </article>`;
        }).join('');
        // Phase 4e: clip thumbnails first, with source-note / co-located
        // note as the auth-checked fallback for clips not yet generated.
        this.mountCoachClipThumbnailsIn(container);
    },

    openFeedbackClip(clipId) {
        const clip = (this._feedbackData?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) return;
        this.openFeedbackPlayer({ mode: 'clip', clip, playerSource: 'feedback' });
    },

    // ===== Phase 6e — viewer detail modals =====
    //
    // The detail modal is the single read-only surface a player/family
    // viewer uses to read the full structured feedback for a note,
    // observation, or clip. It is composed from the data the server
    // already returned in `/api/my-feedback` (or
    // `/api/my-feedback/players/{id}/development`) — no new endpoints, no
    // new client-side authorization, no client-side filtering.
    //
    // Privacy invariants (defense in depth):
    //   - `coach_private_note` is NEVER templated here. The server
    //     scrubs it via `_strip_private_fields` for viewers; we also
    //     refuse to render it client-side regardless of payload.
    //   - The detail modal pulls the note/clip out of `_feedbackData`,
    //     so it can only show what the viewer endpoint already returned.
    //   - `tactical_board_json` follows the parent note's visibility on
    //     the server. If a board reaches us, the parent note is visible.
    //
    // Defensive rendering:
    //   - Missing optional structured fields collapse cleanly (no empty
    //     section headings, no "null" / "undefined" / "NaN").
    //   - Observation notes without a board fall through to the text
    //     layout — no empty board container.
    //   - Older notes without Phase 6 fields render without the event
    //     metadata block.

    /** Resolve linked-player chips for a note/clip from the data the
     *  server already shipped. Falls back to `_feedbackData.players`
     *  (the linked-strip payload) and then to a "Player {short id}" label
     *  so a defensive payload never produces "undefined". */
    _resolveLinkedPlayerChips(playerIds) {
        if (!Array.isArray(playerIds) || !playerIds.length) return '';
        const knownPlayers = (this._feedbackData?.players || []);
        const byId = new Map(knownPlayers.map((p) => [String(p.id), p]));
        const chips = playerIds.map((pid) => {
            const player = byId.get(String(pid));
            const label = player ? this.playerLabel(player) : 'Linked player';
            return `<span class="feedback-linked-pill">${this.esc(label)}</span>`;
        });
        return chips.join('');
    },

    /** Build the structured-fields stack — this is the single composition
     *  point shared between the My Feedback note detail modal and the
     *  focused-feedback-player body. Renders only what's non-empty so a
     *  viewer never sees an empty "What happened" block. */
    _detailStructuredHtml(note) {
        const items = [
            ['What happened',     note?.what_happened],
            ['Why it matters',    note?.why_it_matters],
            ['What to do next',   note?.what_to_do_next],
        ].filter(([, v]) => (v || '').trim());
        if (!items.length) return '';
        return items.map(([label, value]) => `
            <section class="feedback-detail-section">
                <h4 class="feedback-detail-section-title">${this.esc(label)}</h4>
                <p class="feedback-detail-section-body">${this.esc(value.trim())}</p>
            </section>
        `).join('');
    },

    /** Build the meta line for a video note's detail header. */
    _detailVideoMetaHtml(note) {
        const parts = [
            this.matchLabel(note.match_id),
            this.slotLabel(note.slot),
            this.formatClock(note.timestamp_seconds),
        ].filter(Boolean);
        return parts.map((p) => this.esc(p)).join(' · ');
    },

    /** Build the meta line for an observation note's detail header.
     *  Returns HTML-escaped text safe to drop into innerHTML. */
    _detailObservationMetaHtml(note) {
        return this.esc(this._observationMetaText(note));
    },

    /** Plain-text variant — safe to assign via textContent. The HTML
     *  helper above escapes the same string; assigning the escaped
     *  HTML to textContent would double-escape characters like `&`,
     *  so the modal subtitle uses this plain-text form. */
    _observationMetaText(note) {
        const parts = [];
        if (note.event_type) {
            const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
            parts.push(`${typeLabel} observation`);
        } else {
            parts.push('Coach observation');
        }
        if (note.event_title && note.event_title !== (note.title || '')) {
            parts.push(note.event_title);
        }
        if (note.event_date) parts.push(note.event_date);
        return parts.filter(Boolean).join(' · ');
    },

    /** Phase 6e — the unified review-modal body composer. Builds the
     *  same structured layout for video notes, observation notes, and
     *  clips so the viewer always sees one consistent reading
     *  experience. The visual (video / tactical board / playback
     *  window) is rendered ABOVE this body by the focused-feedback
     *  player template; this composer fills the body slot below it
     *  with: tone + category + linked players + Summary +
     *  What happened / Why / Next + Additional detail + tags.
     *
     *  `coach_private_note` is NEVER referenced or templated — defense
     *  in depth even though the server already scrubs it for viewers
     *  via `_strip_private_fields`.
     *
     *  Inputs:
     *    { kind: 'note',  note }   — video or observation note
     *    { kind: 'clip',  clip }   — coaching clip
     */
    _renderUnifiedFeedbackBody(target, { kind, note = null, clip = null }) {
        if (!target) return;
        const reviews = this._feedbackData?.reviews || [];
        let parts = [];
        if (kind === 'note' && note) {
            const isObservation = (note.note_context || 'video') === 'observation';
            const isReviewed = reviews.some((r) => Number(r.note_id) === Number(note.id));
            const tonePill = this._feedbackTonePillHtml(note.note_type);
            const categoryHtml = note.category
                ? `<span class="feedback-detail-chip">${this.esc(this._categoryLabel(note.category))}</span>`
                : '';
            const contextPill = isObservation
                ? `<span class="feedback-detail-context-pill" data-context="observation">${this.esc(this._observationContextLabel(note))}</span>`
                : `<span class="feedback-detail-context-pill" data-context="video">Video note</span>`;
            const reviewedChip = isReviewed
                ? '<span class="feedback-detail-chip feedback-detail-chip--reviewed">Reviewed ✓</span>'
                : '';
            const linkedHtml = this._resolveLinkedPlayerChips(note.player_ids);
            const linkedSection = linkedHtml
                ? `<div class="feedback-detail-linked"><span class="feedback-detail-linked-label">For:</span>${linkedHtml}</div>`
                : '';
            const { primary, secondary } = this._feedbackNoteSummary(note);
            const structured = this._detailStructuredHtml(note);
            const tagsHtml = (note.tags && note.tags.length)
                ? `<div class="feedback-detail-chips" aria-label="Tags">${note.tags.map((t) => `<span class="feedback-detail-chip feedback-detail-chip--tag">#${this.esc(t)}</span>`).join('')}</div>`
                : '';
            parts.push(`
                <div class="feedback-detail-head-row">
                    ${contextPill}
                    ${tonePill}
                    ${categoryHtml}
                    ${reviewedChip}
                </div>
                ${linkedSection}
            `);
            if (primary) {
                parts.push(`<section class="feedback-detail-summary"><h4 class="feedback-detail-section-title">Summary</h4><p>${this.esc(primary)}</p></section>`);
            }
            if (structured) parts.push(structured);
            if (secondary) {
                parts.push(`<section class="feedback-detail-section feedback-detail-additional"><h4 class="feedback-detail-section-title">Additional detail</h4><p class="feedback-detail-section-body">${this.esc(secondary)}</p></section>`);
            }
            if (tagsHtml) parts.push(tagsHtml);
        } else if (kind === 'clip' && clip) {
            const categoryLabel = this._categoryLabel(clip.category || 'other');
            const linkedHtml = this._resolveLinkedPlayerChips(clip.player_ids);
            const linkedSection = linkedHtml
                ? `<div class="feedback-detail-linked"><span class="feedback-detail-linked-label">For:</span>${linkedHtml}</div>`
                : '';
            const description = (clip.description || '').trim();
            parts.push(`
                <div class="feedback-detail-head-row">
                    <span class="feedback-detail-context-pill" data-context="clip">Coaching clip</span>
                    ${categoryLabel ? `<span class="feedback-detail-chip">${this.esc(categoryLabel)}</span>` : ''}
                </div>
                ${linkedSection}
            `);
            if (description) {
                parts.push(`<section class="feedback-detail-summary"><h4 class="feedback-detail-section-title">Description</h4><p>${this.esc(description)}</p></section>`);
            }
        }
        target.classList.add('feedback-detail-body');
        target.dataset.context = kind === 'clip' ? 'clip' : ((note?.note_context || 'video') === 'observation' ? 'observation' : 'video');
        target.innerHTML = parts.join('');
    },

    /** Helper — resolve a category code to its display label. Falls back
     *  to the raw value (capitalized) for unknown codes so a forward-
     *  compat payload from a future migration still renders sensibly. */
    _categoryLabel(category) {
        if (!category) return '';
        const map = Object.fromEntries(NOTE_CATEGORIES);
        return map[category] || category.charAt(0).toUpperCase() + category.slice(1).replace(/_/g, ' ');
    },

    /** Helper — choose a human-friendly observation context label for
     *  the detail modal pill. Mirrors the card-meta wording but avoids
     *  the suffix "observation" duplication when the event_type already
     *  spells it out. */
    _observationContextLabel(note) {
        if (note.event_type === 'tactical' && this.tacticalBoardHasContent(note.tactical_board_json)) {
            return 'Tactical observation';
        }
        if (note.event_type) {
            const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
            return `${typeLabel} observation`;
        }
        return 'Coach observation';
    },

    // ===== Focused feedback / playlist player modal =====

    async openFeedbackPlayer({ mode, note = null, playlist = null, clip = null, playerSource = 'feedback' }) {
        const tpl = document.getElementById('feedback-player-template');
        if (!tpl) { this.showError('Feedback player template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Snapshot the canvas/video ids the telestrator points at, so we can restore on close.
        const prevCanvasId = this._coachCanvasId;
        const prevVideoId = this._coachVideoId;
        // Rebind the painter to the modal's elements.
        this._coachCanvasId = 'feedback-drawing-canvas';
        this._coachVideoId = 'feedback-player-video';

        const cleanup = () => {
            this._stopFeedbackHeartbeat();
            this.stopFeedbackPlaylistSession();
            // Phase 4b: tear down the clip end-of-window watcher if a
            // clip session was active. Idempotent — no-op when not in
            // clip mode.
            this._stopClipMonitor();
            this.destroyHlsPlayer();
            this.deactivateCoachCanvas();
            // Modal canvas was cloned fresh from the template and is removed
            // from the DOM when the modal closes. Detach the window-resize
            // listener bound to it so the closure (and the canvas it captured)
            // can be garbage-collected.
            this.teardownCoachCanvasListeners('feedback-drawing-canvas');
            this._coachDrawing = null;
            this._coachCanvasId = prevCanvasId;
            this._coachVideoId = prevVideoId;
            this._feedbackPlayer = null;
        };

        const onMount = () => {
            this._feedbackPlayer = { body, mode, note, playlist, clip, playerSource };
            const videoWrapper = body.querySelector('[data-field="video-wrapper"]');
            const boardWrapper = body.querySelector('[data-field="board-wrapper"]');
            if (mode === 'note') {
                const isObservation = (note.note_context || 'video') === 'observation';
                body.querySelector('[data-field="title"]').textContent = note.title || (isObservation ? 'Coach observation' : 'Coaching note');
                body.querySelector('[data-field="subtitle"]').textContent = isObservation
                    ? this._observationMetaText(note)
                    : `${this.matchLabel(note.match_id)} · ${this.formatClock(note.timestamp_seconds)} · ${this.slotLabel(note.slot)}`;
                // Phase 6e — the focused player modal is the SINGLE
                // review surface for notes (video + observation). For
                // observation notes there's no playable video: hide the
                // <video>+canvas wrapper and reveal the read-only
                // tactical board (when present) where the video would
                // be. For video notes, hide the board wrapper and load
                // the HLS source as before.
                if (isObservation) {
                    if (videoWrapper) videoWrapper.hidden = true;
                    if (boardWrapper) {
                        const hasBoard = this.tacticalBoardHasContent(note.tactical_board_json);
                        if (hasBoard) {
                            boardWrapper.hidden = false;
                            boardWrapper.innerHTML = this.tacticalBoardSvg(note.tactical_board_json, { size: 'preview' });
                        } else {
                            boardWrapper.hidden = true;
                        }
                    }
                } else {
                    if (boardWrapper) boardWrapper.hidden = true;
                    if (videoWrapper) videoWrapper.hidden = false;
                    this._loadFeedbackVideoForNote(note);
                }
                // Always render the unified structured-field body
                // (Summary / What happened / Why / Next / Additional
                // detail / tags / linked players). `coach_private_note`
                // is never templated.
                this._renderUnifiedFeedbackBody(body.querySelector('[data-field="body"]'), { kind: 'note', note });
            } else if (mode === 'playlist') {
                body.querySelector('[data-field="title"]').textContent = playlist.title || 'Review playlist';
                body.querySelector('[data-field="subtitle"]').textContent = `${(playlist.note_ids || []).length} clips`;
                body.querySelector('[data-field="body"]').textContent = playlist.description || '';
                if (boardWrapper) boardWrapper.hidden = true;
                this.startCoachingPlaylistSession(playlist, { playerSource });
            } else if (mode === 'clip') {
                // Phase 4b: clip playback. Title + a subtitle that
                // names the match, slot, and the [start–end] window
                // so the player knows what they're about to watch.
                body.querySelector('[data-field="title"]').textContent = clip.title || 'Coaching clip';
                body.querySelector('[data-field="subtitle"]').textContent =
                    `${this.matchLabel(clip.match_id)} · ${this.slotLabel(clip.slot)} · `
                    + `${this.formatClock(clip.start_seconds)}–${this.formatClock(clip.end_seconds)} `
                    + `(${this._clipDurationLabel(clip)})`;
                if (boardWrapper) boardWrapper.hidden = true;
                if (videoWrapper) videoWrapper.hidden = false;
                this._loadFeedbackVideoForClip(clip);
                // Phase 6e — clips share the unified body layout. Show
                // category + meta + description in the same Summary /
                // section structure as notes so the viewer sees one
                // consistent layout across all three review types.
                this._renderUnifiedFeedbackBody(body.querySelector('[data-field="body"]'), { kind: 'clip', clip });
                // Clips have no Mark-reviewed backend yet — hide the
                // confirm button so Close is the only action.
                const modalCard = body.closest('.app-modal-card');
                const confirmBtn = modalCard?.querySelector('.app-modal-confirm');
                if (confirmBtn) confirmBtn.hidden = true;
            }
        };

        // Phase 6e — title reflects the kind so the player knows what
        // they're looking at, but the modal shell is the same one for
        // every review type. Observation notes carry a context-aware
        // kicker ("Practice observation" / "Tactical observation"
        // etc.) so the reading experience matches the card meta.
        const modalTitle = (() => {
            if (mode === 'playlist') return 'Review Session';
            if (mode === 'clip') return 'Coaching Clip';
            if (mode === 'note' && (note.note_context || 'video') === 'observation') {
                return this._observationContextLabel(note);
            }
            return 'Coaching Note';
        })();
        await this.formModal({
            title: modalTitle,
            kicker: 'Feedback',
            body,
            confirmLabel: 'Mark reviewed',
            cancelLabel: 'Close',
            size: 'wide',
            onMount,
            onSubmit: async (close) => {
                try {
                    if (mode === 'note' && note) await this.markFeedbackReviewed({ note_id: note.id });
                    else if (mode === 'playlist' && playlist) await this.markFeedbackReviewed({ playlist_id: playlist.id });
                    // Phase 4b: clips don't have a "mark reviewed"
                    // backend yet (the `coaching_reviews` table only
                    // accepts note_id / playlist_id). Close cleanly
                    // without firing an API call — the coach/player
                    // can still close normally.
                    if (mode === 'note' || mode === 'playlist') {
                        this.showSuccess('Marked reviewed.');
                        await this.renderMyFeedback();
                    }
                } catch (err) { this.showError(err.message); }
                close(true);
            },
        });
        cleanup();
    },

    /** Phase 4b — load the clip's source match video, seek to
     *  `start_seconds`, and arm a `timeupdate` watcher that pauses at
     *  `end_seconds`. No MP4 export, no segment download — pure
     *  seek-based playback against the existing match HLS.
     *
     *  Replay-after-end (PR #96 review fix): once the playhead reaches
     *  `end_seconds` we pause + snap to the boundary AND set a
     *  `clipAtEnd` flag. The next `play` event on the video element
     *  reads that flag and seeks back to `start_seconds`, so the
     *  player gets a from-the-start replay instead of immediately
     *  re-pausing on the next monitor tick. The flag is also reset on
     *  any user-initiated seek that lands strictly before the end
     *  boundary (so a manual scrub-back-and-play behaves the same as
     *  a fresh playthrough). */
    async _loadFeedbackVideoForClip(clip) {
        const video = document.getElementById('feedback-player-video');
        if (!video) return;
        const { hlsUrl, mp4Url } = this.getStreamUrls(clip.match_id, clip.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        // Phase 4c (issue #99): clips do NOT render a telestrator
        // overlay. Earlier code called `setupCoachCanvas()` here for
        // the resize-listener side effect, but that wired the canvas
        // event handlers (`paintCoachCanvas`, the global resize
        // observer) into a session that never paints anything — pure
        // wasted work, and it implied clip-drawing support exists
        // when it doesn't. The drawing canvas is left dormant for
        // clip mode; if a future phase adds clip telestration, it
        // can opt back in by calling `setupCoachCanvas` here AND
        // wiring the equivalent of `_renderFeedbackTelestration` for
        // clip drawings. Note + playlist playback paths still call
        // `setupCoachCanvas` themselves — unchanged.
        //
        // Issue #105: the cloned `<canvas id="feedback-drawing-canvas">`
        // sits absolute-positioned over the `<video>` with
        // `pointer-events: auto` (see `.coach-drawing-canvas` in
        // styles.css). For note / playlist mode `setupCoachCanvas` is
        // the bridge that consumes those events for painting. In clip
        // mode nothing consumes them — but the overlay still receives
        // every click, swallowing presses on the native video Play /
        // Pause / scrub controls. Hide and decouple it explicitly so
        // the user can drive playback through the native chrome.
        const clipCanvas = document.getElementById('feedback-drawing-canvas');
        if (clipCanvas) {
            clipCanvas.style.display = 'none';
            clipCanvas.style.pointerEvents = 'none';
        }

        const startTime = Math.max(0, Number(clip.start_seconds || 0));
        const endTime = Math.max(startTime + 0.5, Number(clip.end_seconds || 0));

        // Tear down any prior clip monitor BEFORE wiring the new one.
        // This also resets `clipAtEnd` for the new session — opening a
        // fresh clip never inherits an end-of-clip state from the
        // previous one.
        this._stopClipMonitor();

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            // Seek to the clip's start. Playback does NOT autoplay —
            // the player presses Play when ready (consistent with
            // single-note feedback playback).
            video.currentTime = startTime;
        };
        video.addEventListener('loadedmetadata', onLoaded);

        // Mutable session state for this clip. `_clipMonitor` is the
        // single source of truth — both the listeners and the fallback
        // timer read from it via the `monitor` closure, and
        // `_stopClipMonitor` clears every reference on cleanup so a
        // closed modal can't leak event handlers or the interval.
        const session = {
            videoEl: video,
            startTime,
            endTime,
            clipAtEnd: false,
            // Listener references — needed so `_stopClipMonitor` can
            // remove the SAME function objects we registered.
            timeupdate: null,
            play: null,
            seeked: null,
            intervalId: 0,
        };

        const monitor = () => {
            if (!video.isConnected) { this._stopClipMonitor(); return; }
            // The session may have been replaced (or cleared) by a
            // teardown that fired between intervals. Bail gracefully
            // in that case so we never act on a torn-down clip.
            if (this._clipMonitor !== session) return;
            // If the playhead crosses `end_seconds`, pause + snap to
            // the boundary and flag the at-end state. The flag is the
            // signal the `play` listener uses to know it must rewind
            // before allowing playback to continue (PR #96 review fix
            // — without this, pressing Play would immediately re-fire
            // this same condition and re-pause).
            if (video.currentTime >= endTime - 0.05 && !video.paused) {
                video.pause();
                video.currentTime = endTime;
                session.clipAtEnd = true;
            }
        };

        // On `play`: if we're at the end boundary (either via the
        // pause-snap above, or the user manually scrubbed past), rewind
        // to `start_seconds` so the next playback frame is from the
        // beginning of the clip instead of from the locked end position.
        // Avoids the recursive pause/play loop that the previous
        // implementation had.
        const onPlay = () => {
            if (this._clipMonitor !== session) return;
            // `clipAtEnd` covers the snap-paused case; the
            // `currentTime >= endTime` half covers a user who
            // manually scrubbed the timeline past `endTime` and then
            // hit Play — same outcome either way: rewind to start.
            if (session.clipAtEnd || video.currentTime >= endTime - 0.05) {
                session.clipAtEnd = false;
                video.currentTime = startTime;
            }
        };

        // On `seeked`: if the user manually scrubbed BACKWARD to a
        // time strictly before `end_seconds`, clear the at-end flag so
        // playback proceeds normally. Without this, a user who scrubs
        // back from the boundary would still be in `clipAtEnd === true`
        // state, and the next play event would yank them all the way
        // back to `startTime` — surprising. Tolerance of 0.05s mirrors
        // the boundary check above.
        const onSeeked = () => {
            if (this._clipMonitor !== session) return;
            if (video.currentTime < endTime - 0.05) {
                session.clipAtEnd = false;
            }
        };

        session.timeupdate = monitor;
        session.play = onPlay;
        session.seeked = onSeeked;
        video.addEventListener('timeupdate', session.timeupdate);
        video.addEventListener('play', session.play);
        video.addEventListener('seeked', session.seeked);
        // Belt-and-braces fallback timer: some HLS sources throttle
        // `timeupdate` during seeks / buffer stalls. 250 ms is fine —
        // a clip's end boundary is enforced cooperatively, not
        // sample-accurately.
        session.intervalId = window.setInterval(monitor, 250);
        this._clipMonitor = session;

        this._startFeedbackHeartbeat(clip.match_id, clip.slot, video);
    },

    /** Tear down the clip end-of-window watcher. Safe to call when
     *  the modal isn't in clip mode — short-circuits on missing
     *  state. Called by `cleanup` inside `openFeedbackPlayer` and at
     *  the top of `_loadFeedbackVideoForClip` so a fresh clip session
     *  never inherits the previous one's listeners or `clipAtEnd`
     *  flag. */
    _stopClipMonitor() {
        const m = this._clipMonitor;
        if (!m) return;
        try {
            if (m.videoEl) {
                if (m.timeupdate) m.videoEl.removeEventListener('timeupdate', m.timeupdate);
                if (m.play) m.videoEl.removeEventListener('play', m.play);
                if (m.seeked) m.videoEl.removeEventListener('seeked', m.seeked);
            }
            if (m.intervalId) window.clearInterval(m.intervalId);
        } catch { /* ignore */ }
        this._clipMonitor = null;
    },

    async _loadFeedbackVideoForNote(note) {
        const video = document.getElementById('feedback-player-video');
        if (!video) return;
        const { hlsUrl, mp4Url } = this.getStreamUrls(note.match_id, note.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        // PR 1c follow-up: bind the canvas listeners + ResizeObserver
        // BEFORE the video paints so the canvas bitmap dimensions
        // catch up to the wrapper as soon as the layout settles.
        this.setupCoachCanvas();

        // PR 1c follow-up: cache the saved drawing payload on the
        // modal session so we can re-show the telestration when the
        // player scrubs back to (or before) the timestamp. We use a
        // dedicated `noteDrawing` slot rather than `_coachDrawing`
        // because `_coachDrawing` gets nulled on Play; the cached
        // copy is the source of truth for the entire modal lifetime.
        if (this._feedbackPlayer) this._feedbackPlayer.noteDrawing = note.drawing || {};
        this._renderFeedbackTelestration();
        const targetTime = Math.max(0, Number(note.timestamp_seconds || 0));

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            video.currentTime = targetTime;
            this._renderFeedbackTelestration();
            // PR 1c follow-up: do NOT autoplay. The drawing is a
            // freeze-frame coaching overlay — let the player study
            // the telestration first. They press Play when ready.
        };
        video.addEventListener('loadedmetadata', onLoaded);

        // Repaint when the first frame paints (some HLS sources reach
        // loadedmetadata with a 0×0 wrapper rect).
        const onPainted = () => {
            video.removeEventListener('loadeddata', onPainted);
            this._renderFeedbackTelestration();
        };
        video.addEventListener('loadeddata', onPainted);

        // PR 1c follow-up: drive telestration visibility from the
        // player state. A persistent `play` / `pause` / `seeked`
        // listener trio so the drawing reappears whenever the player
        // scrubs back to (or pauses at) the freeze timestamp, and
        // disappears whenever the player presses Play. Listeners are
        // removed by `cleanup()` in `openFeedbackPlayer` (the canvas
        // teardown destroys the closure references).
        const onPlay = () => this._clearFeedbackTelestration();
        const onPause = () => this._renderFeedbackTelestration();
        const onSeeked = () => {
            // Show the drawing when the playhead is at or before the
            // saved timestamp; hide it otherwise. We check `paused`
            // too so a seek that happens while playing doesn't flash
            // the drawing into view mid-play.
            if (video.paused && video.currentTime <= targetTime + 0.05) {
                this._renderFeedbackTelestration();
            } else {
                this._clearFeedbackTelestration();
            }
        };
        video.addEventListener('play', onPlay);
        video.addEventListener('pause', onPause);
        video.addEventListener('seeked', onSeeked);

        this._startFeedbackHeartbeat(note.match_id, note.slot, video);
    },

    /** PR 1c follow-up: paint the telestration cached on the current
     *  modal session. Safe to call any number of times — `render
     *  CoachDrawing` is idempotent. */
    _renderFeedbackTelestration() {
        const drawing = this._feedbackPlayer?.noteDrawing
            || this._coachPlaylistSession?.items[this._coachPlaylistSession.index]?.drawing
            || null;
        if (!drawing) return;
        this.renderCoachDrawing(drawing);
    },

    /** PR 1c follow-up: hide the telestration without destroying the
     *  cached drawing payload — so the modal can re-show it later if
     *  the player scrubs back. Mirrors `clearCoachDrawing` for the
     *  visible state but does NOT clear the cache. */
    _clearFeedbackTelestration() {
        // Equivalent to `clearCoachDrawing()` for the visible state
        // but the cache (`_feedbackPlayer.noteDrawing`) survives.
        this._coachDrawing = null;
        this._coachSelectedObjectIndex = null;
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    _startFeedbackHeartbeat(matchId, slot, videoEl) {
        this._stopFeedbackHeartbeat();
        if (!matchId || !slot) return;
        const url = `/api/matches/${encodeURIComponent(matchId)}/heartbeat?slot=${encodeURIComponent(slot)}`;
        const ping = async ({ skipPausedCheck = false } = {}) => {
            if (!skipPausedCheck && videoEl && (videoEl.paused || videoEl.ended)) return;
            try {
                const resp = await fetch(url, { method: 'POST', credentials: 'same-origin' });
                if (resp.status === 403) {
                    if (videoEl) videoEl.pause();
                    this.showError?.('This stream was disconnected by an administrator.');
                    this._stopFeedbackHeartbeat();
                    this.destroyHlsPlayer();
                }
            } catch { /* transient — try again next tick */ }
        };
        ping({ skipPausedCheck: true });
        this._feedbackHeartbeatTimer = window.setInterval(() => ping(), 10000);
    },

    _stopFeedbackHeartbeat() {
        if (this._feedbackHeartbeatTimer) {
            window.clearInterval(this._feedbackHeartbeatTimer);
            this._feedbackHeartbeatTimer = null;
        }
    },

    // ===== Playlist controller (operates on whichever video the modal exposes) =====

    playlistItems(playlist) {
        if (Array.isArray(playlist?.items) && playlist.items.length) return playlist.items;
        const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
        const byId = new Map(notes.map((note) => [Number(note.id), note]));
        return (playlist?.note_ids || []).map((id) => byId.get(Number(id))).filter(Boolean);
    },

    startCoachingPlaylistSession(playlist, { playerSource = 'feedback' } = {}) {
        const items = this.playlistItems(playlist);
        if (!items.length) {
            this.showError('This playlist has no playable notes.');
            return;
        }
        this.stopFeedbackPlaylistSession();
        this._coachPlaylistSession = {
            playlist, items, index: 0,
            frozeCurrentItem: false, paused: false, opening: false,
            playerSource,
        };
        this.openCoachingPlaylistItem(0);
    },

    async openCoachingPlaylistItem(index) {
        const session = this._coachPlaylistSession;
        if (!session) return;
        if (index < 0 || index >= session.items.length) {
            this.finishCoachingPlaylistSession();
            return;
        }
        const item = session.items[index];
        session.index = index;
        // PR 1c follow-up: each playlist item now opens paused at the
        // timestamp with the saved drawing visible — same UX as the
        // standalone note. The previous flow auto-played pre-roll →
        // freeze → post-roll, which made the telestration feel
        // fleeting. Pre-roll is intentionally skipped: the freeze
        // IS the moment; pressing Play reveals the post-roll context.
        // `frozeCurrentItem` starts true because we're already at the
        // freeze position; the monitor only needs to advance to the
        // next item once the post-roll window completes.
        session.frozeCurrentItem = true;
        session.opening = true;
        // Cache the per-item drawing on the modal session so seek-
        // back / pause re-shows it (matches the standalone-note path).
        if (this._feedbackPlayer) this._feedbackPlayer.noteDrawing = item.drawing || {};
        this._coachDrawing = null;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (!video) { session.opening = false; return; }
        const { hlsUrl, mp4Url } = this.getStreamUrls(item.match_id, item.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        this.setupCoachCanvas();
        this._renderFeedbackTelestration();
        const targetTime = Math.max(0, Number(item.timestamp_seconds || 0));

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            video.currentTime = targetTime;
            this._renderFeedbackTelestration();
            session.opening = false;
            this.startPlaylistMonitor();
            this._startFeedbackHeartbeat(item.match_id, item.slot, video);
        };
        video.addEventListener('loadedmetadata', onLoaded);

        const onPainted = () => {
            video.removeEventListener('loadeddata', onPainted);
            this._renderFeedbackTelestration();
        };
        video.addEventListener('loadeddata', onPainted);

        // PR 1c follow-up: same persistent play/pause/seeked trio as
        // the standalone note — drawing reappears whenever the
        // player scrubs back to (or pauses at) the freeze timestamp,
        // and disappears whenever they press Play.
        const onPlay = () => this._clearFeedbackTelestration();
        const onPause = () => this._renderFeedbackTelestration();
        const onSeeked = () => {
            if (video.paused && video.currentTime <= targetTime + 0.05) {
                this._renderFeedbackTelestration();
            } else {
                this._clearFeedbackTelestration();
            }
        };
        video.addEventListener('play', onPlay);
        video.addEventListener('pause', onPause);
        video.addEventListener('seeked', onSeeked);
    },

    startPlaylistMonitor() {
        this.stopPlaylistMonitor();
        this._coachPlaylistMonitor = window.setInterval(() => {
            const session = this._coachPlaylistSession;
            const video = document.getElementById('feedback-player-video');
            if (!session || !video || session.opening || session.paused) return;
            const item = session.items[session.index];
            const timestamp = Number(item.timestamp_seconds || 0);
            const end = timestamp + Number(session.playlist.post_roll_seconds ?? 8);
            // PR 1c follow-up: the playlist item now opens paused AT
            // the freeze timestamp with the saved drawing visible. The
            // pre-roll-then-freeze loop was removed (`frozeCurrentItem`
            // is set to true in `openCoachingPlaylistItem` so the
            // freeze branch never runs). The monitor's only remaining
            // job is to advance to the next item when the player has
            // pressed Play and watched through the post-roll window.
            if (video.currentTime >= end || video.ended) {
                this.openCoachingPlaylistItem(session.index + 1);
            }
        }, 250);
    },

    stopPlaylistMonitor() {
        if (this._coachPlaylistMonitor) {
            window.clearInterval(this._coachPlaylistMonitor);
            this._coachPlaylistMonitor = null;
        }
        if (this._coachPlaylistFreezeTimer) {
            window.clearTimeout(this._coachPlaylistFreezeTimer);
            this._coachPlaylistFreezeTimer = null;
        }
    },

    renderPlaylistSessionRail() {
        const player = this._feedbackPlayer;
        if (!player) return;
        const rail = player.body.querySelector('[data-field="rail"]');
        if (!rail) return;
        const session = this._coachPlaylistSession;
        if (!session) { rail.hidden = true; rail.innerHTML = ''; return; }
        rail.hidden = false;
        const item = session.items[session.index];
        // PR 1c: surface the per-item tone pill + the player-facing
        // summary INSIDE the playlist player too, so a player watching
        // a session sees the same context they'd see if they opened
        // the standalone note. coach_private_note is never rendered
        // (server already scrubs it; we never template it client-side).
        const tone = this._feedbackTonePillHtml(item.note_type);
        const { primary } = this._feedbackNoteSummary(item);
        rail.innerHTML = `
            ${this._coachNoteThumbHtml(item, { size: 'rail' })}
            <div class="feedback-rail-info">
                <span>Review Session</span>
                <strong>${this.esc(session.playlist.title)}</strong>
                <small>${session.index + 1} of ${session.items.length} · ${this.esc(item.title)} · ${this.esc(item.category || 'note')}</small>
                ${tone || primary ? `
                    <div class="feedback-rail-item-detail">
                        ${tone}
                        ${primary ? `<span class="feedback-rail-item-summary">${this.esc(primary)}</span>` : ''}
                    </div>
                ` : ''}
            </div>
            <div class="feedback-rail-controls">
                <button type="button" class="mini-action-btn" onclick="app.previousCoachingPlaylistItem()">Prev</button>
                <button type="button" class="mini-action-btn" onclick="app.toggleCoachingPlaylistPause()">${session.paused ? 'Resume' : 'Pause'}</button>
                <button type="button" class="mini-action-btn" onclick="app.restartCoachingPlaylistItem()">Restart</button>
                <button type="button" class="mini-action-btn" onclick="app.nextCoachingPlaylistItem()">Next</button>
            </div>
        `;
        this.mountCoachNoteThumbnailsIn(rail);
    },

    toggleCoachingPlaylistPause() {
        const session = this._coachPlaylistSession;
        const video = document.getElementById('feedback-player-video');
        if (!session || !video) return;
        session.paused = !session.paused;
        if (session.paused) video.pause();
        else video.play().catch(() => {});
        this.renderPlaylistSessionRail();
    },

    restartCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index);
    },

    nextCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index + 1);
    },

    previousCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(Math.max(0, session.index - 1));
    },

    finishCoachingPlaylistSession() {
        this.stopPlaylistMonitor();
        const session = this._coachPlaylistSession;
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (video) video.pause();
        if (session) this.showSuccess('Playlist finished.');
    },

    stopFeedbackPlaylistSession() {
        this.stopPlaylistMonitor();
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
    },

    // Backwards-compat shims for any lingering callers (e.g. teardownGameView).
    stopCoachingPlaylistSession() { this.stopFeedbackPlaylistSession(); },

    // ===== Match-page deep link to /coach?tab=review =====

    updateCoachThisMatchLink(match) {
        const link = document.getElementById('coach-this-match-link');
        if (!link) return;
        if (!match || !this.canCoach()) { link.hidden = true; return; }
        const slot = this.activeSlot || 'full';
        link.href = this._coachUrl('review', match.id, slot);
        link.hidden = false;
    },

    async markFeedbackItemReviewed(data) {
        try {
            await this.markFeedbackReviewed(data);
            this.showSuccess('Marked reviewed.');
            await this.renderMyFeedback();
        } catch (err) { this.showError(err.message); }
    },

    _goalPlayer(goal) {
        return (this._coachBundle?.players || this._feedbackData?.players || [])
            .find((p) => String(p.id) === String(goal?.player_id));
    },

    _goalStatusLabel(status) { return GOAL_STATUS_LABELS[status] || status || 'Open'; },
    _goalContextLabel(context) { return GOAL_CONTEXT_LABELS[context] || context || 'Goal'; },
    _goalVisibilityLabel(visibility) { return GOAL_VISIBILITY_LABELS[visibility] || visibility || 'Player/family'; },
    _goalPriorityLabel(priority) { return GOAL_PRIORITY_LABELS[priority] || priority || 'Medium'; },

    _goalSourceSummary(goal) {
        if (goal?.source_note) {
            const n = goal.source_note;
            const title = (n.title || n.event_title || n.player_summary || n.body || 'Coaching note').trim();
            return { label: 'Source note', text: title, kind: 'note' };
        }
        if (goal?.source_clip) return { label: 'Source clip', text: goal.source_clip.title || 'Coaching clip', kind: 'clip' };
        if (goal?.source_playlist) return { label: 'Source playlist', text: goal.source_playlist.title || 'Review playlist', kind: 'playlist' };
        return null;
    },

    _renderGoalCard(goal, { viewer = false, actions = true } = {}) {
        const player = this._goalPlayer(goal);
        const source = this._goalSourceSummary(goal);
        const reflections = goal.reflections || [];
        const latest = goal.latest_reflection || reflections[0] || null;
        const status = goal.status || 'open';
        const active = ACTIVE_GOAL_STATUSES.has(status);
        const coachMeta = !viewer ? [
            this._goalVisibilityLabel(goal.visibility || 'player'),
            `${this._goalPriorityLabel(goal.priority || 'medium')} priority`,
            goal.target_date ? `Target ${this.formatDate(goal.target_date)}` : '',
        ].filter(Boolean).join(' · ') : '';
        return `
            <article class="player-goal-card${active ? '' : ' is-muted'}" data-goal-id="${Number(goal.id)}">
                <div class="player-goal-card-head">
                    <div class="player-goal-card-title">
                        <span class="player-goal-kicker">${this.esc(this._goalContextLabel(goal.context))}${player && !viewer ? ` · ${this.esc(this.playerLabel(player))}` : ''}</span>
                        <h4>${this.esc(goal.title || 'Player goal')}</h4>
                        ${coachMeta ? `<span class="player-goal-meta">${this.esc(coachMeta)}</span>` : ''}
                    </div>
                    <span class="player-goal-status" data-status="${this.esc(status)}">${this.esc(this._goalStatusLabel(status))}</span>
                </div>
                ${goal.description ? `<div class="player-goal-preview-block"><span>Action plan</span><p class="player-goal-desc">${this.esc(goal.description)}</p></div>` : ''}
                ${goal.success_criteria ? `<div class="player-goal-preview-block"><span>Success criteria</span><p class="player-goal-desc">${this.esc(goal.success_criteria)}</p></div>` : ''}
                ${!viewer && goal.coach_private_note ? `<div class="player-goal-preview-block player-goal-private-note"><span>Coach private note</span><p class="player-goal-desc">${this.esc(goal.coach_private_note)}</p></div>` : ''}
                ${source ? `<div class="player-goal-source"><span>${this.esc(source.label)}</span><strong>${this.esc(source.text)}</strong></div>` : ''}
                ${latest ? `<div class="player-goal-reflection"><span>Latest reflection</span><p>${this.esc(latest.reflection || '')}</p></div>` : ''}
                ${actions ? `<div class="player-goal-actions">
                    ${viewer ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openGoalReflectionModal(${Number(goal.id)})">Add reflection</button>` : `
                        <select class="player-goal-status-select" aria-label="Goal status" onchange="app.handleCoachGoalStatus(${Number(goal.id)}, this.value)">
                            ${GOAL_STATUS_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === status ? 'selected' : ''}>${this.esc(l)}</option>`).join('')}
                        </select>
                        <button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ goalId: ${Number(goal.id)} })">Edit</button>
                        <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteGoal(${Number(goal.id)})">Delete</button>`}
                </div>` : ''}
            </article>`;
    },

    async openCoachGoalModal({ goalId = null, playerId = null, source = null } = {}) {
        if (!this.canCoach()) return;
        const goal = goalId ? (this._coachBundle?.goals || []).find((g) => Number(g.id) === Number(goalId)) : null;
        const players = this._coachBundle?.players || [];
        const body = document.createElement('div');
        body.className = 'coach-mini-form player-goal-form';
        body.innerHTML = `
            <div class="form-grid two">
                <label>Player<select data-field="player_id" ${goal ? 'disabled' : ''}>${players.map((p) => `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`).join('')}</select></label>
                <label>Context<select data-field="context">${GOAL_CONTEXT_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
            </div>
            <div class="form-grid two">
                <label>Visibility<select data-field="visibility">${GOAL_VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
                <label>Priority<select data-field="priority">${GOAL_PRIORITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
            </div>
            <label>Goal title<input type="text" data-field="title" maxlength="160" placeholder="Scan before receiving"></label>
            <label>Action plan<textarea data-field="description" rows="4" maxlength="2000" placeholder="What should the player try next?"></textarea></label>
            <div class="form-grid two">
                <label>Status<select data-field="status">${GOAL_STATUS_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
                <label>Target date<input type="date" data-field="target_date"></label>
            </div>
            <label>Success criteria<textarea data-field="success_criteria" rows="3" maxlength="2000" placeholder="How will we know this goal is working?"></textarea></label>
            <label>Coach private note, not visible to family/player<textarea data-field="coach_private_note" rows="3" maxlength="2000" placeholder="Internal coaching context"></textarea></label>
            <label>Target match<select data-field="target_match_id"><option value="">— none —</option>${(this.matches || []).map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('')}</select></label>
            <input type="hidden" data-field="source_note_id"><input type="hidden" data-field="source_clip_id"><input type="hidden" data-field="source_playlist_id">
            <p class="form-help" data-field="source_help">Optional: create from a note/clip/list via its Create goal action.</p>`;
        body.querySelector('[data-field="player_id"]').value = goal?.player_id || playerId || players[0]?.id || '';
        body.querySelector('[data-field="context"]').value = goal?.context || 'next_match';
        body.querySelector('[data-field="visibility"]').value = goal?.visibility || 'player';
        body.querySelector('[data-field="priority"]').value = goal?.priority || 'medium';
        body.querySelector('[data-field="title"]').value = goal?.title || source?.title || '';
        body.querySelector('[data-field="description"]').value = goal?.description || source?.description || '';
        body.querySelector('[data-field="status"]').value = goal?.status || 'open';
        body.querySelector('[data-field="target_date"]').value = goal?.target_date || '';
        body.querySelector('[data-field="success_criteria"]').value = goal?.success_criteria || '';
        body.querySelector('[data-field="coach_private_note"]').value = goal?.coach_private_note || '';
        body.querySelector('[data-field="target_match_id"]').value = goal?.target_match_id || '';
        for (const field of ['source_note_id', 'source_clip_id', 'source_playlist_id']) body.querySelector(`[data-field="${field}"]`).value = goal?.[field] || source?.[field] || '';
        if (source?.label || goal) {
            const summary = source?.label || this._goalSourceSummary(goal)?.text || '';
            body.querySelector('[data-field="source_help"]').textContent = summary ? `Evidence: ${summary}` : 'Evidence attached.';
        }
        const result = await this.formModal({
            title: goal ? 'Edit Player Goal' : 'New Player Goal', kicker: 'Coaching', body,
            confirmLabel: goal ? 'Save goal' : 'Create goal',
            onSubmit: (close) => {
                const data = {
                    player_id: body.querySelector('[data-field="player_id"]').value,
                    title: body.querySelector('[data-field="title"]').value.trim(),
                    description: body.querySelector('[data-field="description"]').value.trim(),
                    context: body.querySelector('[data-field="context"]').value,
                    visibility: body.querySelector('[data-field="visibility"]').value,
                    priority: body.querySelector('[data-field="priority"]').value,
                    status: body.querySelector('[data-field="status"]').value,
                    target_date: body.querySelector('[data-field="target_date"]').value || '',
                    success_criteria: body.querySelector('[data-field="success_criteria"]').value.trim(),
                    coach_private_note: body.querySelector('[data-field="coach_private_note"]').value.trim(),
                    target_match_id: body.querySelector('[data-field="target_match_id"]').value || null,
                };
                for (const field of ['source_note_id', 'source_clip_id', 'source_playlist_id']) {
                    const v = body.querySelector(`[data-field="${field}"]`).value;
                    if (v) data[field] = Number(v);
                }
                if (!data.player_id) { this.showError('Pick a player.'); return; }
                if (!data.title) { this.showError('Goal title is required.'); return; }
                close(data);
            },
        });
        if (!result) return;
        try {
            if (goal) {
                const { player_id, ...updates } = result;
                await this.updateCoachGoal(goal.id, updates);
            } else await this.createCoachGoal(result);
            this.showSuccess(goal ? 'Goal updated.' : 'Goal created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachGoalStatus(goalId, status) {
        try {
            await this.updateCoachGoal(goalId, { status });
            this.showSuccess('Goal status updated.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteGoal(goalId) {
        const ok = await this.confirmAction({ title: 'Delete goal', message: 'Delete this player goal?', confirmLabel: 'Delete goal', danger: true });
        if (!ok) return;
        try { await this.deleteCoachGoal(goalId); this.showSuccess('Goal deleted.'); await this.renderCoachWorkspace(); }
        catch (err) { this.showError(err.message); }
    },

    async openGoalReflectionModal(goalId) {
        const goal = (this._feedbackData?.goals || []).find((g) => Number(g.id) === Number(goalId));
        if (!goal) { this.showError('Goal not available.'); return; }
        const body = document.createElement('div');
        body.className = 'coach-mini-form player-goal-form';
        body.innerHTML = `
            <div class="player-goal-card is-preview">${this._renderGoalCard(goal, { viewer: true, actions: false })}</div>
            <label>Your reflection<textarea data-field="reflection" rows="4" maxlength="1000" placeholder="What did you try? What should your coach know?"></textarea></label>`;
        const result = await this.formModal({
            title: 'Reflect on goal', kicker: 'My Feedback', body, confirmLabel: 'Save reflection',
            onSubmit: (close) => {
                const reflection = body.querySelector('[data-field="reflection"]').value.trim();
                if (!reflection) { this.showError('Reflection is required.'); return; }
                close(reflection);
            },
        });
        if (!result) return;
        try {
            await this.createMyGoalReflection(goalId, result);
            this.showSuccess('Reflection saved for your coach.');
            await this.renderMyFeedback();
            if (this._feedbackTab === 'development') await this.renderFeedbackDevelopment();
        } catch (err) { this.showError(err.message); }
    },

    // ===== Phase 5b — Player development profiles =====
    //
    // Two surfaces share the same render helpers:
    //   - Coach > Roster > "View development profile" → modal, viewer=false
    //   - My Feedback > Development tab               → inline, viewer=true
    //
    // Both go through the same `_renderPlayerDevelopmentProfile` so the
    // visible structure stays consistent. Privacy lives entirely server-
    // side: the coach surface renders whatever the coach endpoint
    // returned (the coach payload includes `linked_accounts` — surfaced
    // by `_renderDevHeader`. Coach-only goal fields such as
    // `coach_private_note` are rendered only when `viewer=false`; note
    // private text is still intentionally NOT templated by `_renderDevNoteItem`).
    // The viewer surface renders whatever the viewer endpoint returned (already
    // scrubbed by `_strip_private_fields`). No client-side
    // authorization decisions.

    async openCoachPlayerDevelopmentModal(playerId) {
        if (!this.canCoach()) return;
        const players = this._coachBundle?.players || [];
        const player = players.find((p) => String(p.id) === String(playerId));
        const headerName = player ? this.playerLabel(player) : 'Player';
        const body = document.createElement('div');
        body.className = 'player-dev-modal-body';
        body.innerHTML = '<div class="session-empty">Loading development profile…</div>';
        await this.formModal({
            title: headerName,
            kicker: 'Development Profile',
            body,
            confirmLabel: 'Close',
            cancelLabel: '',
            size: 'wide',
            onSubmit: (close) => close(true),
            onMount: async () => {
                try {
                    const profile = await this.getCoachPlayerDevelopment(playerId);
                    if (!profile) {
                        body.innerHTML = '<div class="session-empty">Profile unavailable.</div>';
                        return;
                    }
                    body.innerHTML = this._renderPlayerDevelopmentProfile(profile, { viewer: false });
                    this.mountCoachNoteThumbnailsIn(body);
                    this.mountCoachClipThumbnailsIn(body);
                } catch (err) {
                    body.innerHTML = `<div class="session-empty">Could not load profile. ${this.esc(err.message || '')}</div>`;
                }
            },
        });
    },

    /** Render the inline Development tab in My Feedback. Driven by
     *  `_feedbackData.players` (linked players) + a per-player viewer
     *  endpoint fetch. If multiple players are linked, a chip selector
     *  switches between them — for a single player we skip the
     *  selector and show the profile straight away. */
    renderFeedbackMatchSummaries(data) {
        const list = document.getElementById('feedback-summaries-list');
        if (!list) return;
        const summaries = data?.match_summaries || [];
        if (!summaries.length) {
            list.innerHTML = '<div class="session-empty">No team-visible match summaries yet.</div>';
            return;
        }
        const notesById = new Map((data?.notes || []).map((n) => [Number(n.id), n]));
        const clipsById = new Map((data?.clips || []).map((c) => [Number(c.id), c]));
        const playlistsById = new Map((data?.playlists || []).map((p) => [Number(p.id), p]));
        list.innerHTML = summaries.map((s) => {
            const sections = [
                ['What went well', s.team_positives],
                ['What we can improve', s.team_improvements],
                ['Training focus', s.training_focus],
                ['Coach recap', s.body],
            ].filter(([, value]) => (value || '').trim());
            const notes = (s.note_ids || []).map((id) => notesById.get(Number(id))).filter(Boolean);
            const clips = (s.clip_ids || []).map((id) => clipsById.get(Number(id))).filter(Boolean);
            const playlists = (s.playlist_ids || []).map((id) => playlistsById.get(Number(id))).filter(Boolean);
            const sources = [
                ...notes.map((n) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackNote(${Number(n.id)})">Note: ${this.esc(n.title || 'Moment')}</button>`),
                ...clips.map((c) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackClip(${Number(c.id)})">Clip: ${this.esc(c.title || 'Clip')}</button>`),
                ...playlists.map((p) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackPlaylist(${Number(p.id)})">Playlist: ${this.esc(p.title || 'Session')}</button>`),
            ];
            return `
                <article class="feedback-card feedback-summary-card">
                    <div class="feedback-card-body">
                        <div class="feedback-card-kicker">Match summary</div>
                        <h3>${this.esc(this.matchLabel(s.match_id))}</h3>
                        ${sections.map(([label, value]) => `<section class="feedback-detail-summary"><h4 class="feedback-detail-section-title">${this.esc(label)}</h4><p>${this.esc(value)}</p></section>`).join('')}
                        ${sources.length ? `<div class="feedback-card-actions">${sources.join('')}</div>` : ''}
                    </div>
                </article>`;
        }).join('');
    },

    async renderFeedbackDevelopment() {
        const root = document.getElementById('feedback-development-content');
        if (!root) return;
        const players = this._feedbackData?.players || [];
        if (!players.length) {
            root.innerHTML = '<div class="session-empty">No roster player is linked to your account yet. Ask a coach to link you.</div>';
            return;
        }
        // Pick the active player — sticky across re-renders so the user
        // doesn't get yanked back to the first chip on every refresh.
        const known = new Set(players.map((p) => String(p.id)));
        if (!this._feedbackDevPlayerId || !known.has(String(this._feedbackDevPlayerId))) {
            this._feedbackDevPlayerId = String(players[0].id);
        }
        const activeId = this._feedbackDevPlayerId;
        // Player IDs are UUID strings; build a safe JS literal for the
        // onclick attribute the same way the Roster row does (see
        // `renderCoachRoster`). `this.esc()` HTML-encodes for innerHTML
        // and is the wrong tool for JS-literal construction.
        const chips = players.length > 1 ? `
            <div class="feedback-dev-player-strip" role="tablist" aria-label="Linked players">
                ${players.map((p) => {
                    const playerIdJs = JSON.stringify(String(p.id)).replace(/"/g, '&quot;');
                    const isActive = String(p.id) === activeId;
                    return `
                    <button type="button"
                            class="feedback-dev-player-chip${isActive ? ' is-active' : ''}"
                            role="tab"
                            aria-selected="${isActive ? 'true' : 'false'}"
                            onclick="app.setFeedbackDevPlayer(${playerIdJs})">
                        ${this.esc(this.playerLabel(p))}
                    </button>`;
                }).join('')}
            </div>` : '';
        root.innerHTML = `${chips}<div id="feedback-development-profile"><div class="session-empty">Loading development profile…</div></div>`;
        const target = document.getElementById('feedback-development-profile');
        try {
            const profile = await this.getMyPlayerDevelopment(activeId);
            if (!profile) {
                target.innerHTML = '<div class="session-empty">Profile not available.</div>';
                return;
            }
            // Phase 6e — cache the per-player profile so a viewer who
            // clicks a recent-note row in Development can open the
            // detail modal even when the underlying note wasn't in the
            // main /api/my-feedback notes[] payload (the dev endpoint
            // applies the same visibility ladder).
            this._feedbackDevCache = this._feedbackDevCache || {};
            this._feedbackDevCache[String(activeId)] = profile;
            target.innerHTML = this._renderPlayerDevelopmentProfile(profile, { viewer: true });
            this.mountCoachNoteThumbnailsIn(target);
            this.mountCoachClipThumbnailsIn(target);
        } catch (err) {
            target.innerHTML = `<div class="session-empty">Could not load profile. ${this.esc(err.message || '')}</div>`;
        }
    },

    setFeedbackDevPlayer(playerId) {
        // Defensive: only accept non-empty strings. The chip handlers
        // never pass undefined/null today, but a stray inline call
        // shouldn't be able to wedge the selector into a "no player"
        // limbo state.
        const id = playerId == null ? '' : String(playerId);
        if (!id) return;
        this._feedbackDevPlayerId = id;
        this.renderFeedbackDevelopment();
    },

    /** Single render path for Coach + viewer development profiles.
     *  `viewer=true` swaps coach-only labels ("Linked accounts",
     *  technical wording) for player-friendly copy. Both surfaces
     *  render the same fields when present so the structure is
     *  predictable. */
    _renderPlayerDevelopmentProfile(profile, { viewer = false } = {}) {
        const sections = [];
        sections.push(this._renderDevHeader(profile, { viewer }));
        sections.push(this._renderDevCounts(profile, { viewer }));
        sections.push(this._renderDevGoals(profile, { viewer }));
        if (!viewer) sections.push(this._renderDevThemes(profile));
        sections.push(this._renderDevFocusAreas(profile, { viewer }));
        sections.push(this._renderDevRecentPositives(profile, { viewer }));
        sections.push(this._renderDevRecentCorrections(profile, { viewer }));
        sections.push(this._renderDevRecentClips(profile, { viewer }));
        sections.push(this._renderDevRecentPlaylists(profile, { viewer }));
        // Empty-state collapse: if NOTHING in the profile has data, show
        // a single friendly message instead of seven "no items" blocks.
        const counts = profile.counts || {};
        const total = Number(counts.notes || 0) + Number(counts.clips || 0) + Number(counts.playlists || 0) + Number(counts.goals || 0);
        if (total === 0) {
            const msg = viewer
                ? 'No development feedback yet.'
                : 'No coaching activity for this player yet.';
            return `${sections[0]}<div class="player-dev-empty session-empty">${this.esc(msg)}</div>`;
        }
        return sections.join('');
    },

    _renderDevHeader(profile, { viewer }) {
        const p = profile.player || {};
        const jersey = p.jersey_number
            ? `<span class="player-dev-jersey">#${this.esc(p.jersey_number)}</span>`
            : '';
        const status = p.active
            ? '<span class="roster-status-pill is-active"><span class="roster-status-dot" aria-hidden="true"></span>Active</span>'
            : '<span class="roster-status-pill is-inactive"><span class="roster-status-dot" aria-hidden="true"></span>Inactive</span>';
        const notes = !viewer && p.notes_field
            ? `<p class="player-dev-notes">${this.esc(p.notes_field)}</p>`
            : '';
        const linkedAccounts = !viewer && Array.isArray(profile.linked_accounts) && profile.linked_accounts.length
            ? `<div class="player-dev-linked">
                  <span class="player-dev-linked-label">Linked accounts (${profile.linked_accounts.length}):</span>
                  ${profile.linked_accounts.map((l) => `
                      <span class="player-dev-linked-chip" title="${this.esc(l.relationship || '')}">
                          <span class="player-dev-linked-rel">${this.esc(l.relationship || 'link')}</span>
                          <span class="player-dev-linked-user">@${this.esc(l.username || '')}</span>
                      </span>`).join('')}
              </div>`
            : '';
        return `
            <header class="player-dev-header">
                <div class="player-dev-headline">
                    ${jersey}
                    <h3 class="player-dev-name">${this.esc(p.display_name || 'Player')}</h3>
                    ${status}
                </div>
                ${notes}
                ${linkedAccounts}
            </header>`;
    },

    _renderDevCounts(profile, { viewer }) {
        const c = profile.counts || {};
        const r = profile.review_status || {};
        const noteRev = r.notes || {};
        const plRev = r.playlists || {};
        const clipRev = r.clips || {};
        const tiles = [
            { label: viewer ? 'Notes shared' : 'Notes', value: c.notes ?? 0 },
            { label: viewer ? 'Clips shared' : 'Clips', value: c.clips ?? 0 },
            { label: viewer ? 'Playlists shared' : 'Playlists', value: c.playlists ?? 0 },
            { label: viewer ? 'Active goals' : 'Goals', value: c.goals ?? (profile.active_goals || []).length },
            {
                label: viewer ? 'Notes reviewed' : 'Notes reviewed',
                value: `${noteRev.reviewed_count ?? 0} / ${noteRev.assigned_count ?? 0}`,
            },
            {
                label: 'Playlists reviewed',
                value: `${plRev.reviewed_count ?? 0} / ${plRev.assigned_count ?? 0}`,
            },
            {
                label: 'Reflections',
                value: r.reflection_count ?? 0,
            },
        ];
        if (!viewer && clipRev.review_supported === false) {
            // Surface that clip-review is not yet supported so the coach
            // doesn't read "0 / N" as a coverage gap.
            tiles.push({
                label: 'Clips reviewed',
                value: '—',
                hint: 'Clip review not tracked yet',
            });
        }
        return `
            <section class="player-dev-section player-dev-counts">
                <h4 class="player-dev-section-title">Summary</h4>
                <div class="player-dev-tile-grid">
                    ${tiles.map((t) => `
                        <div class="player-dev-tile" ${t.hint ? `title="${this.esc(t.hint)}"` : ''}>
                            <span class="player-dev-tile-label">${this.esc(t.label)}</span>
                            <strong class="player-dev-tile-value">${this.esc(String(t.value))}</strong>
                        </div>
                    `).join('')}
                </div>
            </section>`;
    },

    _renderDevGoals(profile, { viewer }) {
        const goals = profile.active_goals || [];
        const pid = profile.player?.id;
        const playerIdJs = JSON.stringify(String(pid || '')).replace(/"/g, '&quot;');
        if (!goals.length) {
            return `
                <section class="player-dev-section player-dev-goals">
                    <div class="player-dev-section-headline">
                        <div>
                            <h4 class="player-dev-section-title">${this.esc(viewer ? 'Current goals' : 'Active goals')}</h4>
                            <p class="player-dev-section-sub">${this.esc(viewer ? 'Goals your coach wants you to try next.' : 'Create explicit action plans tied to notes, clips, or the player profile.')}</p>
                        </div>
                        ${!viewer && pid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachGoalModal({ playerId: ${playerIdJs} })">+ New goal</button>` : ''}
                    </div>
                    <div class="player-dev-empty">${this.esc(viewer ? 'No active goals yet.' : 'No active goals yet.')}</div>
                </section>`;
        }
        return `
            <section class="player-dev-section player-dev-goals">
                <div class="player-dev-section-headline">
                    <div>
                        <h4 class="player-dev-section-title">${this.esc(viewer ? 'Current goals' : 'Active goals')}</h4>
                        <p class="player-dev-section-sub">${this.esc(viewer ? 'Add a reflection when you have tried one.' : 'Status changes are tracked and viewer reflections appear here.')}</p>
                    </div>
                    ${!viewer && pid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachGoalModal({ playerId: ${playerIdJs} })">+ New goal</button>` : ''}
                </div>
                <div class="player-goal-grid">
                    ${goals.map((g) => this._renderGoalCard(g, { viewer })).join('')}
                </div>
            </section>`;
    },

    _renderDevThemes(profile) {
        // Coach-only: a viewer doesn't need positives-vs-corrections
        // ratios or top-tag breakdowns.
        const t = profile.themes || {};
        const byType = t.by_note_type || {};
        const order = ['positive', 'correction', 'question', 'team_concept', 'individual_goal'];
        const labels = {
            positive: 'Positives',
            correction: 'Corrections',
            question: 'Questions',
            team_concept: 'Team concepts',
            individual_goal: 'Individual goals',
        };
        const typeChips = order
            .filter((k) => (byType[k] ?? 0) > 0)
            .map((k) => `
                <span class="player-dev-chip player-dev-chip--type" data-tone="${this.esc(k)}">
                    ${this.esc(labels[k])} <strong>${this.esc(String(byType[k]))}</strong>
                </span>`).join('');
        const ratioStr = (() => {
            const r = t.positive_to_correction_ratio;
            if (r === null || r === undefined) return '—';
            return r.toFixed ? r.toFixed(2) : String(r);
        })();
        const topCats = (t.top_categories || []).map((c) => `
            <span class="player-dev-chip">${this.esc(c.value || '—')} <strong>${this.esc(String(c.count))}</strong></span>
        `).join('');
        const topTags = (t.top_tags || []).map((c) => `
            <span class="player-dev-chip player-dev-chip--tag">#${this.esc(c.value || '')} <strong>${this.esc(String(c.count))}</strong></span>
        `).join('');
        const empty = !typeChips && !topCats && !topTags;
        if (empty) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Themes</h4>
                    <div class="player-dev-empty">No themes yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Themes</h4>
                ${typeChips ? `<div class="player-dev-chip-row">${typeChips}</div>` : ''}
                <div class="player-dev-meta-row">
                    <span class="player-dev-meta-item">
                        <span class="player-dev-meta-label">Positive : Correction ratio</span>
                        <strong>${this.esc(ratioStr)}</strong>
                    </span>
                </div>
                ${topCats ? `<div class="player-dev-subsection">
                    <span class="player-dev-subsection-title">Top categories</span>
                    <div class="player-dev-chip-row">${topCats}</div>
                </div>` : ''}
                ${topTags ? `<div class="player-dev-subsection">
                    <span class="player-dev-subsection-title">Top tags</span>
                    <div class="player-dev-chip-row">${topTags}</div>
                </div>` : ''}
            </section>`;
    },

    _renderDevFocusAreas(profile, { viewer }) {
        const focus = profile.current_focus_areas || [];
        const title = viewer ? 'Focus areas from recent feedback' : 'Suggested focus areas from recent notes';
        const subtitle = viewer
            ? 'Things to keep working on, drawn from your most recent feedback.'
            : 'Derived from recent feedback. Phase 6 will add explicit goals and action plans.';
        if (!focus.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <p class="player-dev-section-sub">${this.esc(subtitle)}</p>
                    <div class="player-dev-empty">No focus areas yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <p class="player-dev-section-sub">${this.esc(subtitle)}</p>
                <ul class="player-dev-focus-list">
                    ${focus.map((f) => `
                        <li class="player-dev-focus-item">
                            <span class="player-dev-focus-cat">${this.esc(f.category || f.note_type || '')}</span>
                            <span class="player-dev-focus-body">${this.esc(f.what_to_do_next || '')}</span>
                        </li>
                    `).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentPositives(profile, { viewer }) {
        const items = profile.recent_positives || [];
        const title = viewer ? 'Recent positives' : 'Recent positives';
        if (!items.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <div class="player-dev-empty">No positives yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <ul class="player-dev-note-list">
                    ${items.map((n) => this._renderDevNoteItem(n, { viewer })).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentCorrections(profile, { viewer }) {
        const items = profile.recent_corrections || [];
        const title = viewer ? 'Recent things to work on' : 'Recent corrections';
        if (!items.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <div class="player-dev-empty">${this.esc(viewer ? 'Nothing to work on right now.' : 'No corrections yet.')}</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <ul class="player-dev-note-list">
                    ${items.map((n) => this._renderDevNoteItem(n, { viewer, emphasizeNext: true })).join('')}
                </ul>
            </section>`;
    },

    /** Single row layout for a recent note across positives /
     *  corrections / general lists. Renders only what the server
     *  returned. `coach_private_note` is intentionally never templated
     *  (the viewer endpoint scrubs it server-side; the coach endpoint
     *  exposes it but we don't show coach-private text in this UI to
     *  keep the surface consistent — Phase 6 may add an explicit
     *  coach-only block). */
    /** Phase 6e — open the unified review modal for a recent dev row.
     *  The viewer surface routes through the SAME `openFeedbackPlayer`
     *  modal that the My Feedback Notes tab uses, so a viewer never
     *  sees a different reading layout depending on which tab they
     *  clicked from.
     *
     *  When the note isn't in the main `/api/my-feedback` notes[]
     *  payload (the dev endpoint applies the same visibility ladder
     *  but is scoped per-player), we fall back to the cached
     *  development payload for the active player. No client-side
     *  authorization is added. */
    openFeedbackNoteDetailFromDev(noteId) {
        let note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) {
            const dev = this._feedbackDevCache?.[this._feedbackDevPlayerId];
            const allDevNotes = [
                ...(dev?.recent_notes || []),
                ...(dev?.recent_positives || []),
                ...(dev?.recent_corrections || []),
            ];
            note = allDevNotes.find((n) => Number(n.id) === Number(noteId)) || null;
        }
        if (!note) {
            this.showError('Note not available.');
            return;
        }
        // Cache the dev-only note temporarily on _feedbackData so the
        // unified body composer's review-state lookup + linked-player
        // resolver still work. Defensive — `_feedbackData.notes` may be
        // empty for a viewer who only browsed Development.
        if (!this._feedbackData) this._feedbackData = { notes: [], clips: [], reviews: [], players: [] };
        if (!this._feedbackData.notes.some((n) => Number(n.id) === Number(note.id))) {
            this._feedbackData.notes = [...(this._feedbackData.notes || []), note];
        }
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    /** Phase 6e — open the unified review modal for a recent dev clip
     *  row, reusing the same focused-player modal as the Clips tab. */
    openFeedbackClipDetailFromDev(clipId) {
        let clip = (this._feedbackData?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) {
            const dev = this._feedbackDevCache?.[this._feedbackDevPlayerId];
            clip = (dev?.recent_clips || []).find((c) => Number(c.id) === Number(clipId)) || null;
        }
        if (!clip) {
            this.showError('Clip not available.');
            return;
        }
        if (!this._feedbackData) this._feedbackData = { notes: [], clips: [], reviews: [], players: [] };
        if (!this._feedbackData.clips.some((c) => Number(c.id) === Number(clip.id))) {
            this._feedbackData.clips = [...(this._feedbackData.clips || []), clip];
        }
        this.openFeedbackPlayer({ mode: 'clip', clip });
    },

    _renderDevNoteItem(note, { viewer, emphasizeNext = false } = {}) {
        const isObservation = (note.note_context || 'video') === 'observation';
        const summary = (note.player_summary || '').trim() || (note.body || '').trim();
        const title = (note.title || '').trim() || (isObservation ? (note.event_title || '').trim() : '');
        const next = (note.what_to_do_next || '').trim();
        // Phase 6b — observation notes have no match/slot/timestamp.
        // Build the meta line from event metadata when available so
        // a profile that mixes video + observation notes never shows
        // "null" or "0:00" for fields that don't apply.
        let meta = '';
        if (isObservation) {
            const parts = [];
            if (note.event_type) {
                const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
                parts.push(`${typeLabel} observation`);
            } else {
                parts.push('Observation');
            }
            if (note.event_title && note.event_title !== title) parts.push(note.event_title);
            if (note.event_date) parts.push(note.event_date);
            meta = parts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
        } else {
            const matchPart = note.match_id ? this.esc(this.matchLabel(note.match_id)) : '';
            const slotPart = note.slot ? this.esc(this.slotLabel(note.slot)) : '';
            const tsPart = Number.isFinite(Number(note.timestamp_seconds))
                ? this.esc(this.formatClock(note.timestamp_seconds)) : '';
            meta = [matchPart, slotPart, tsPart].filter(Boolean).join(' · ');
        }
        const tonePill = this._feedbackTonePillHtml(note.note_type);
        // Phase 6c — observation notes with a tactical board show a
        // compact SVG preview tile in place of the clipboard glyph
        // so the development profile surfaces the sketch at-a-glance
        // without breaking layout.
        const hasBoard = isObservation && this.tacticalBoardHasContent(note.tactical_board_json);
        const thumb = isObservation
            ? (hasBoard
                ? `<div class="coach-thumb coach-thumb--list coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(note.tactical_board_json, { size: 'chip' })}</div>`
                : '<div class="coach-thumb coach-thumb--list coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
            : this._coachNoteThumbHtml(note, { size: 'list' });
        const boardPill = hasBoard
            ? '<span class="coach-row-board-pill" title="Tactical board attached">⌬ Board</span>'
            : '';
        // Phase 6e — make viewer-side dev rows clickable so a parent
        // browsing the development profile can open the same detail
        // modal as the My Feedback Notes tab. Coach-side preview stays
        // unchanged (the coach surface uses the modal it already mounts
        // for the development view; click-to-detail isn't its job).
        const detailHandler = viewer && Number.isFinite(Number(note.id))
            ? `onclick="app.openFeedbackNoteDetailFromDev(${Number(note.id)})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackNoteDetailFromDev(${Number(note.id)});}"`
            : '';
        const interactiveAttrs = viewer && detailHandler
            ? `tabindex="0" role="button" aria-label="Open details for ${this.esc(title || 'note')}"`
            : '';
        const itemClass = `player-dev-note-item${viewer && detailHandler ? ' player-dev-note-item--clickable' : ''}`;
        return `
            <li class="${itemClass}" data-note-context="${isObservation ? 'observation' : 'video'}" ${interactiveAttrs} ${detailHandler}>
                ${thumb}
                <div class="player-dev-note-body">
                    <div class="player-dev-note-head">
                        ${tonePill}
                        ${boardPill}
                        ${title ? `<strong class="player-dev-note-title">${this.esc(title)}</strong>` : ''}
                    </div>
                    ${meta ? `<div class="player-dev-note-meta">${meta}</div>` : ''}
                    ${summary ? `<p class="player-dev-note-summary">${this.esc(summary)}</p>` : ''}
                    ${next ? `<p class="player-dev-note-next${emphasizeNext ? ' is-emphasized' : ''}">
                        <span class="player-dev-note-next-label">${this.esc(viewer ? 'Try this next:' : 'What to do next:')}</span>
                        ${this.esc(next)}
                    </p>` : ''}
                </div>
            </li>`;
    },

    _renderDevRecentClips(profile, { viewer }) {
        const clips = profile.recent_clips || [];
        if (!clips.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Recent clips</h4>
                    <div class="player-dev-empty">No clips yet.</div>
                </section>`;
        }
        // Phase 6e — viewers route through the dev-aware fallback so a
        // recent clip that's only in the per-player development payload
        // (and not in the main /api/my-feedback clips[]) still opens the
        // unified modal. `openFeedbackClip` would silently no-op on the
        // miss because it only looks in `_feedbackData.clips`. The note
        // path uses the same fallback via `openFeedbackNoteDetailFromDev`.
        const watchHandler = viewer ? 'app.openFeedbackClipDetailFromDev' : 'app.previewCoachClip';
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Recent clips</h4>
                <ul class="player-dev-clip-list">
                    ${clips.map((c) => {
                        // Validate the id once: if it's missing or not a
                        // finite number, drop the Watch/Preview button
                        // (the lookup helper would silently no-op anyway,
                        // but rendering a button that does nothing is
                        // worse than not rendering it). Server JSON
                        // always populates this today; the guard is
                        // defense-in-depth for malformed payloads.
                        const cid = Number(c?.id);
                        const idValid = Number.isFinite(cid) && cid > 0;
                        const meta = [
                            this.matchLabel(c.match_id),
                            this.slotLabel(c.slot),
                            `${this.formatClock(c.start_seconds)}–${this.formatClock(c.end_seconds)}`,
                            this._clipDurationLabel(c),
                            c.category || '',
                        ].filter(Boolean).map((s) => this.esc(s)).join(' · ');
                        return `
                            <li class="player-dev-clip-item">
                                ${this._coachClipThumbHtml(c)}
                                <div class="player-dev-clip-body">
                                    <strong class="player-dev-clip-title">${this.esc(c.title || 'Untitled clip')}</strong>
                                    <div class="player-dev-clip-meta">${meta}</div>
                                    ${c.description ? `<p class="player-dev-clip-desc">${this.esc(c.description)}</p>` : ''}
                                </div>
                                <div class="player-dev-clip-actions">
                                    ${idValid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="${watchHandler}(${cid})">${viewer ? '▶ Watch' : 'Preview'}</button>` : ''}
                                </div>
                            </li>`;
                    }).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentPlaylists(profile, { viewer }) {
        const playlists = profile.recent_playlists || [];
        if (!playlists.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Recent playlists</h4>
                    <div class="player-dev-empty">No playlists yet.</div>
                </section>`;
        }
        // Phase 5b finding #11: the coach surface previously rendered
        // no Preview button for recent playlists, an undocumented
        // asymmetry vs. recent clips. Reuse the existing
        // `previewCoachPlaylist` helper from Coach > Playlists — it
        // looks the playlist up in `_coachBundle.playlists` (always
        // loaded on the coach surface) and opens the same focused
        // feedback player the viewer surface uses, so this introduces
        // no new playback behavior.
        const playHandler = viewer ? 'app.openFeedbackPlaylist' : 'app.previewCoachPlaylist';
        const playLabel   = viewer ? '▶ Play session' : '▶ Preview';
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Recent playlists</h4>
                <ul class="player-dev-playlist-list">
                    ${playlists.map((p) => {
                        const pid = Number(p?.id);
                        const idValid = Number.isFinite(pid) && pid > 0;
                        return `
                        <li class="player-dev-playlist-item">
                            <div class="player-dev-playlist-body">
                                <strong>${this.esc(p.title || 'Untitled playlist')}</strong>
                                <span class="player-dev-playlist-meta">${this.esc(String(p.item_count || 0))} item${(p.item_count || 0) === 1 ? '' : 's'} · ${this.esc(p.visibility || '')}</span>
                            </div>
                            ${idValid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="${playHandler}(${pid})">${playLabel}</button>` : ''}
                        </li>`;
                    }).join('')}
                </ul>
            </section>`;
    },

};
