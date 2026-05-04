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

const VALID_COACH_TABS = ['roster', 'notes', 'playlists', 'review'];
const VALID_FEEDBACK_TABS = ['playlists', 'notes'];

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
    _coachReview: null,
    _coachCanvasId: 'coach-drawing-canvas',
    _coachVideoId: 'coach-review-video',
    _feedbackPlayer: null,
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
            container.innerHTML = '<div class="session-empty">No coaching notes yet. Click <strong>+ New note</strong> to add the first one.</div>';
            return;
        }
        container.innerHTML = notes.map((n) => `
            <article class="coach-row">
                <div>
                    <strong>${this.esc(n.title)}</strong>
                    <span>${this.esc(this.matchLabel(n.match_id))} · ${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${this.esc(n.category)} · ${this.esc(n.visibility)}</span>
                    ${n.body ? `<p>${this.esc(n.body)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openNoteInReview(${n.id})">Open in Review</button>
                    <button type="button" class="mini-action-btn" onclick="app.openCoachNoteModal(${n.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteNote(${n.id})">Delete</button>
                </div>
            </article>
        `).join('');
    },

    async openCoachNoteModal(noteId = null) {
        const note = noteId ? (this._coachBundle?.notes || []).find((n) => Number(n.id) === Number(noteId)) : null;
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
        toneBox.innerHTML = NOTE_TYPES.map(([v, l, glyph]) => `
            <button type="button" class="coach-review-tone-btn${v === initialNoteType ? ' is-active' : ''}" role="radio" aria-checked="${v === initialNoteType}" data-note-type="${v}" title="${this.esc(l)}">
                <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                <span class="coach-review-tone-label">${this.esc(l)}</span>
            </button>
        `).join('');
        // Wire the tone chips inside the modal — scoped to the cloned
        // body so it doesn't fight the Review composer's group state.
        toneBox.querySelectorAll('.coach-review-tone-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const v = btn.dataset.noteType;
                toneBox.dataset.value = v;
                toneBox.querySelectorAll('.coach-review-tone-btn').forEach((b) => {
                    const active = b === btn;
                    b.classList.toggle('is-active', active);
                    b.setAttribute('aria-checked', active ? 'true' : 'false');
                });
            });
        });
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
            if (note) await this.updateCoachNote(note.id, result);
            else await this.createCoachNote(result);
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

    // ===== Playlists sub-tab =====

    renderCoachPlaylists() {
        const container = document.getElementById('coach-playlists-list');
        if (!container) return;
        const playlists = this._coachBundle?.playlists || [];
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists yet. Click <strong>+ New playlist</strong> to build one.</div>';
            return;
        }
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
            <article class="coach-row">
                <div>
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

    // ===== Review sub-tab =====

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

        const pending = this._coachReviewPending || this._coachReview;
        if (pending?.matchId) {
            const matchSel = document.getElementById('coach-review-match');
            const slotSel = document.getElementById('coach-review-slot');
            if (matchSel) matchSel.value = pending.matchId;
            if (slotSel) slotSel.value = pending.slot || 'full';
            await this.loadCoachReviewVideo(pending.matchId, pending.slot || 'full', pending.seekTo || 0, pending.drawing || null);
            this._coachReviewPending = null;
        } else {
            const empty = document.getElementById('coach-review-empty');
            if (empty) empty.style.display = 'flex';
            await this.renderCoachReviewNotes(null);
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
        this._coachReview = { matchId, slot };

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
                        class="coach-timeline-chip ${active ? 'is-active' : ''}"
                        data-coach-note-id="${n.id}"
                        data-coach-category="${this.esc(cat)}"
                        title="${ariaLabel}"
                        aria-label="${ariaLabel}"
                        aria-pressed="${active ? 'true' : 'false'}"
                        onclick="app.seekCoachReviewNote(${n.id})">
                    <span class="coach-timeline-chip-time">${ts}</span>
                    <span class="coach-timeline-chip-player">${playerIndicator}</span>
                    <span class="coach-timeline-chip-cat" aria-hidden="true" data-cat="${this.esc(cat)}"></span>
                    <span class="coach-timeline-chip-title">${this.esc(n.title)}</span>
                </button>
            `;
        }).join('');
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
        // Mount a real backdrop element so clicking outside the drawer
        // closes it. Pseudo-elements can't receive click events.
        let backdrop = document.getElementById('coach-focus-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'coach-focus-backdrop';
            backdrop.className = 'coach-focus-backdrop';
            backdrop.addEventListener('click', () => this.closeCoachFocusInspector());
            document.body.appendChild(backdrop);
        }
        backdrop.hidden = false;
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
                    <button type="button" class="coach-review-tone-btn${v === DEFAULT_NOTE_TYPE ? ' is-active' : ''}" role="radio" aria-checked="${v === DEFAULT_NOTE_TYPE}" data-note-type="${v}" title="${this.esc(l)}" onclick="app.setCoachReviewNoteType('${v}')">
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
        if (toneEl) toneEl.dataset.value = DEFAULT_NOTE_TYPE;
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
     *  `saveReviewNote()` can read it without a redundant DOM scan. */
    setCoachReviewNoteType(value) {
        const group = document.getElementById('coach-review-tone');
        if (!group) return;
        if (!NOTE_TYPES.some(([v]) => v === value)) return;
        group.dataset.value = value;
        group.querySelectorAll('.coach-review-tone-btn').forEach((btn) => {
            const active = btn.dataset.noteType === value;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-checked', active ? 'true' : 'false');
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
        if (linkedStrip) linkedStrip.innerHTML = '';
        if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (notesList) notesList.innerHTML = '<div class="session-empty">Loading…</div>';
        try {
            const data = await this.loadMyFeedback();
            this._feedbackData = data;
            this.renderFeedbackLinkedStrip(data);
            this.renderFeedbackPlaylists(data);
            this.renderFeedbackNotes(data);
        } catch (err) {
            if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Could not load feedback.</div>';
            if (notesList) notesList.innerHTML = '';
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

    /** PR 1c — paint the focused-note modal body. Same composition
     *  as the notes-list row, scaled up: tone pill, primary summary,
     *  structured what/why/next stack, and a collapsed "Coach context"
     *  disclosure for the long-form `body` when both are present. */
    _renderFeedbackBody(target, note) {
        if (!target) return;
        const { primary, secondary } = this._feedbackNoteSummary(note);
        const parts = [];
        const tone = this._feedbackTonePillHtml(note?.note_type);
        if (tone) parts.push(`<div class="feedback-player-tone">${tone}</div>`);
        if (primary) parts.push(`<p class="feedback-note-summary feedback-player-summary">${this.esc(primary)}</p>`);
        const structured = this._feedbackStructuredHtml(note);
        if (structured) parts.push(structured);
        if (secondary) parts.push(`<details class="feedback-note-more"><summary>Coach context</summary><p>${this.esc(secondary)}</p></details>`);
        target.innerHTML = parts.join('');
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
        container.innerHTML = playlists.map((p) => {
            const isReviewed = reviewed.has(Number(p.id));
            const clipCount = p.note_ids?.length || 0;
            return `
            <article class="feedback-card feedback-playlist-card">
                <span class="feedback-card-kicker">Review Session</span>
                <h3 class="feedback-card-title">${this.esc(p.title)}</h3>
                <div class="feedback-card-meta">${clipCount} clip${clipCount === 1 ? '' : 's'} · ${isReviewed ? 'Reviewed' : 'New'}</div>
                ${p.description ? `<p class="feedback-card-description">${this.esc(p.description)}</p>` : ''}
                <div class="feedback-card-actions">
                    <button type="button" class="btn-primary" onclick="app.openFeedbackPlaylist(${p.id})">▶ Play session</button>
                    <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">${isReviewed ? 'Reviewed ✓' : 'Mark reviewed'}</button>
                </div>
            </article>`;
        }).join('');
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
        // Cards are scannable previews — tone + title + meta + a
        // line of summary + actions. The full structured What /
        // Why / Next stack and the Coach context disclosure live
        // inside the focused Watch modal, where the player has the
        // video + drawing context to anchor them.
        container.innerHTML = notes.map((n) => {
            const isReviewed = reviewed.has(Number(n.id));
            const tonePill = this._feedbackTonePillHtml(n.note_type);
            const { primary } = this._feedbackNoteSummary(n);
            const meta = `${this.esc(this.matchLabel(n.match_id))} · ${this.esc(this.formatClock(n.timestamp_seconds))} · ${this.esc(this.slotLabel(n.slot))} · ${isReviewed ? 'Reviewed' : 'New'}`;
            return `
            <article class="feedback-card feedback-note-card">
                <div class="feedback-card-head">
                    ${tonePill}
                    ${isReviewed ? '<span class="feedback-card-status">Reviewed ✓</span>' : ''}
                </div>
                <h3 class="feedback-card-title">${this.esc(n.title)}</h3>
                <div class="feedback-card-meta">${meta}</div>
                ${primary ? `<p class="feedback-card-summary">${this.esc(primary)}</p>` : ''}
                <div class="feedback-card-actions">
                    <button type="button" class="btn-primary" onclick="app.openFeedbackNote(${n.id})">▶ Watch</button>
                    <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ note_id: ${n.id} })">${isReviewed ? 'Reviewed ✓' : 'Mark reviewed'}</button>
                </div>
            </article>`;
        }).join('');
    },

    openFeedbackNote(noteId) {
        const note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) return;
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    openFeedbackPlaylist(playlistId) {
        const playlist = (this._feedbackData?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'feedback' });
    },

    // ===== Focused feedback / playlist player modal =====

    async openFeedbackPlayer({ mode, note = null, playlist = null, playerSource = 'feedback' }) {
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
            this._feedbackPlayer = { body, mode, note, playlist, playerSource };
            if (mode === 'note') {
                body.querySelector('[data-field="title"]').textContent = note.title || 'Coaching note';
                body.querySelector('[data-field="subtitle"]').textContent = `${this.matchLabel(note.match_id)} · ${this.formatClock(note.timestamp_seconds)} · ${this.slotLabel(note.slot)}`;
                // PR 1c: player_summary first, then structured stack,
                // then body as collapsible "Coach context" if both
                // exist. Switch from textContent to innerHTML so the
                // helper-rendered HTML lands intact (each helper
                // already passes user data through `this.esc()`).
                this._renderFeedbackBody(body.querySelector('[data-field="body"]'), note);
                this._loadFeedbackVideoForNote(note);
            } else if (mode === 'playlist') {
                body.querySelector('[data-field="title"]').textContent = playlist.title || 'Review playlist';
                body.querySelector('[data-field="subtitle"]').textContent = `${(playlist.note_ids || []).length} clips`;
                body.querySelector('[data-field="body"]').textContent = playlist.description || '';
                this.startCoachingPlaylistSession(playlist, { playerSource });
            }
        };

        await this.formModal({
            title: mode === 'playlist' ? 'Review Session' : 'Coaching Note',
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
                    this.showSuccess('Marked reviewed.');
                    await this.renderMyFeedback();
                } catch (err) { this.showError(err.message); }
                close(true);
            },
        });
        cleanup();
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
};
