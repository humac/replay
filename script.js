// Entry point — state, init, navigation, event binding.
// Assembles all module mixins into the global `app` object.

import { utilsMixin } from './js/utils.js';
import { apiMixin } from './js/api.js';
import { playerMixin } from './js/player.js';
import { uploadsMixin } from './js/uploads.js';
import { viewsMixin } from './js/views.js';
import { adminViewsMixin } from './js/admin-views.js';
import { uiMixin } from './js/ui.js';
import { liveMixin } from './js/live.js';
import { adminMixin } from './js/admin.js';
import { coachingMixin } from './js/coaching.js';

const app = {
    // ===== STATE & CONFIG =====
    MAX_VIDEO_SIZE_BYTES: 12 * 1024 * 1024 * 1024,
    UPLOAD_TIMEOUT_MS: 4 * 60 * 60 * 1000,
    CHUNK_RETRY_COUNT: 3,
    UPLOAD_SESSION_STORAGE_KEY: 'replay_upload_sessions_v1',
    matches: [],
    appSettings: null,
    appAssets: null,
    activeMatchId: null,
    activeSlot: null,
    activeFilter: 'all',
    searchQuery: '',
    teamStatsExpanded: false,
    castSession: null,
    hlsPlayer: null,
    airplayAvailable: false,
    airplayActive: false,
    castAvailable: false,
    castSupportedBrowser: false,
    castSdkReady: false,
    castSecureContextAllowed: false,
    _castInitialized: false,
    _playRequestToken: 0,
    _pollTimer: null,
    authToken: null,
    userRole: null,
    userRoles: [],
    userName: null,
    diagnostics: null,
    transcodeProgress: {},
    _revealedScores: new Set(),
    recordVisible: false,

    // ===== INIT & LIFECYCLE =====
    async init() {
        this.applyStoredTheme();
        await this.checkAuth();
        await this.loadAppSettings();
        await this.loadMatches();
        this.bindEvents();
        this.applyAppSettings();
        this.renderSeasonView();
        this.initializeHistory();
        this.initAirPlay();
        this.initCast();
        this.initLiveRemotePlayback();
        this.initKeyboardShortcuts();
        this.checkTranscodePolling();
    },

    // ===== NAVIGATION & HISTORY =====
    initializeHistory() {
        const path = window.location.pathname;
        const matchRoute = path.match(/^\/match\/([^/]+)(?:\/([^/]+))?$/);
        if (matchRoute) {
            const slug = matchRoute[1];
            const slot = matchRoute[2] ? matchRoute[2].replace(/-/g, '_') : null;
            const match = this.matches.find(m => m.slug === slug);
            if (match) {
                const state = { view: 'game', matchId: match.id, slug, slot };
                window.history.replaceState(state, '', path);
                this.openMatch(match.id, { pushHistory: false, scrollTop: false, initialSlot: slot });
                return;
            }
        }

        const adminRoute = path.match(/^\/admin(?:\/([^/]+))?\/?$/);
        if (adminRoute) {
            if (!this.canEdit()) {
                window.history.replaceState({ view: 'season' }, '', '/');
                return;
            }
            const requested = adminRoute[1] || this.defaultAdminSection();
            const resolved = this.resolveAdminSection(requested);
            window.history.replaceState({ view: 'admin', section: resolved }, '', `/admin/${resolved}`);
            this.showAdminView(resolved, { pushHistory: false, scrollTop: false });
            return;
        }

        if (path === '/coach') {
            if (!this.canCoach()) {
                window.history.replaceState({ view: 'season' }, '', '/');
                return;
            }
            window.history.replaceState({ view: 'coach' }, '', '/coach');
            this.showCoachView({ pushHistory: false, scrollTop: false });
            return;
        }

        if (path === '/feedback') {
            if (!this.authToken) {
                window.history.replaceState({ view: 'season' }, '', '/');
                return;
            }
            window.history.replaceState({ view: 'feedback' }, '', '/feedback');
            this.showFeedbackView({ pushHistory: false, scrollTop: false });
            return;
        }

        if (path === '/live') {
            window.history.replaceState({ view: 'live' }, '', '/live');
            this.showLiveView({ pushHistory: false, scrollTop: false });
            return;
        }

        const current = window.history.state;
        if (!current || !current.view) {
            window.history.replaceState({ view: 'season' }, '', '/');
            return;
        }
        this.restoreHistoryState(current, { scrollTop: false });
    },

    pushHistoryState(state, { replace = false, url = null } = {}) {
        const href = url || window.location.href;
        if (replace) {
            window.history.replaceState(state, '', href);
            return;
        }
        window.history.pushState(state, '', href);
    },

    restoreHistoryState(state, { scrollTop = false } = {}) {
        if (!state?.view) {
            this.showSeasonView({ pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'game' && state.matchId) {
            this.openMatch(state.matchId, { pushHistory: false, scrollTop, initialSlot: state.slot || null });
            return;
        }

        if (state.view === 'admin') {
            if (!this.canEdit()) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            if (state.mode === 'edit' && state.matchId) {
                this.editMatch(state.matchId, { pushHistory: false, scrollTop });
                return;
            }
            this.showAdminView(state.section || this.defaultAdminSection(),
                { pushHistory: false, scrollTop });
            return;
        }

        // Legacy state shapes from older sessions; route them into the new dashboard.
        if (state.view === 'add-match') {
            if (!this.canEdit()) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            if (state.mode === 'edit' && state.matchId) {
                this.editMatch(state.matchId, { pushHistory: false, scrollTop });
                return;
            }
            this.showAdminView('matches', { pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'settings') {
            if (!this.isAdmin()) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            this.showAdminView('settings', { pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'live') {
            this.showLiveView({ pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'coach') {
            this.showCoachView({ pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'feedback') {
            this.showFeedbackView({ pushHistory: false, scrollTop });
            return;
        }

        this.showSeasonView({ pushHistory: false, scrollTop });
    },

    activateView(viewId, navView = null) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const activeView = document.getElementById(viewId);
        if (activeView) activeView.classList.add('active');

        document.querySelectorAll('.nav-links a').forEach(l => l.classList.remove('active'));
        if (navView) {
            const navLink = document.querySelector(`.nav-links a[data-view="${navView}"]`);
            if (navLink) navLink.classList.add('active');
        }
    },

    teardownGameView() {
        // Save final position before tearing down
        if (this.activeMatchId && this.activeSlot) {
            const videoEl = document.getElementById('game-video');
            if (videoEl && videoEl.currentTime > 0) {
                this._savePosition(this.activeMatchId, this.activeSlot, videoEl.currentTime);
            }
        }
        this._stopPositionTracking();
        this._stopVodHeartbeat?.();
        this.activeMatchId = null;
        this.activeSlot = null;
        this.destroyHlsPlayer();
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn) gameEditBtn.style.display = 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn) regenThumbBtn.style.display = 'none';
        const videoEl = document.getElementById('game-video');
        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
        }
        const overlay = document.getElementById('cast-overlay');
        if (overlay && !this.castSession) {
            overlay.style.display = 'none';
        }
        const downloadActions = document.getElementById('download-actions');
        if (downloadActions) {
            downloadActions.style.display = 'none';
            downloadActions.innerHTML = '';
        }
        const coachPanel = document.getElementById('coach-match-panel');
        if (coachPanel) coachPanel.style.display = 'none';
        const coachCanvas = document.getElementById('coach-drawing-canvas');
        if (coachCanvas) coachCanvas.style.display = 'none';
        this.updateRemotePlaybackNote();
    },

    showSeasonView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.teardownLiveView();
        this.activateView('season-view', 'season');
        this.renderSeasonView();
        this.refreshSeasonLiveCta?.();
        if (pushHistory) {
            this.pushHistoryState({ view: 'season' }, { replace: replaceHistory, url: '/' });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    // Backwards-compatible shims — delegate into the unified dashboard.
    openAddMatchView(opts = {}) {
        this.showAdminView('matches', opts);
    },

    showSettingsView(opts = {}) {
        this.showAdminView('settings', opts);
    },

    goHome() {
        this.cancelEdit();
        this.showSeasonView({ replaceHistory: true });
    },

    editActiveMatch() {
        if (!this.authToken || !this.activeMatchId) return;
        this.editMatch(this.activeMatchId);
    },

    // ===== EVENTS =====
    bindEvents() {
        window.addEventListener('popstate', (event) => {
            this.restoreHistoryState(event.state, { scrollTop: false });
        });

        document.querySelectorAll('.nav-links a').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const view = e.currentTarget.dataset.view;
                if (view === 'season') {
                    this.cancelEdit();
                    this.showSeasonView();
                } else if (view === 'admin') {
                    this.cancelEdit();
                    this.showAdminView(this.defaultAdminSection());
                } else if (view === 'live') {
                    this.cancelEdit();
                    this.showLiveView();
                } else if (view === 'coach') {
                    this.cancelEdit();
                    this.showCoachView();
                } else if (view === 'feedback') {
                    this.cancelEdit();
                    this.showFeedbackView();
                }
            });
        });

        document.querySelectorAll('#season-filter-group .filter-btn').forEach((button) => {
            button.addEventListener('click', () => {
                this.setSeasonFilter(button.dataset.filter || 'all');
            });
        });

        document.getElementById('team-stats-toggle')?.addEventListener('click', () => {
            this.toggleTeamStats();
        });

        document.getElementById('match-search')?.addEventListener('input', (e) => {
            this.searchQuery = e.target.value;
            this.renderSeasonView();
        });

        // Form submits are bound via inline `onsubmit` in index.html so they survive
        // moves between admin sub-pages without re-wiring.

        document.getElementById('refresh-diagnostics-btn')?.addEventListener('click', () => {
            this.refreshAdminDiagnostics();
        });
        document.getElementById('backfill-hls-btn')?.addEventListener('click', () => {
            this.backfillExistingHls();
        });
        document.getElementById('cleanup-uploads-btn')?.addEventListener('click', () => {
            this.cleanupStaleUploads();
        });
        document.getElementById('export-db-btn')?.addEventListener('click', () => {
            this.exportDatabase();
        });

        ['f-home-logo', 'f-away-logo', 'f-video-full', 'f-video-first', 'f-video-second', 'settings-app-logo', 'settings-favicon'].forEach(id => {
            const input = document.getElementById(id);
            const label = document.getElementById(id + '-label');
            if (input && label) {
                input.addEventListener('change', () => {
                    const file = input.files[0];
                    // Inline label uses a middle-ellipsis truncation so long
                    // filenames don't crowd the row. Full filename is shown
                    // unmodified in the "Selected for upload" status below.
                    if (file) {
                        const n = file.name;
                        label.textContent = n.length > 24
                            ? n.slice(0, 14) + '…' + n.slice(-8)
                            : n;
                    } else {
                        label.textContent = 'No file chosen';
                    }
                    if (id.startsWith('settings-')) {
                        this.updateSettingsPendingState(id, file || null);
                    } else {
                        this.updatePendingUploadState(id, file || null);
                    }
                });
            }
        });
    },

    // ===== LIVE VIEW STATE =====
    liveStatusTimer: null,
    liveHls: null,
    liveLastActive: false,
    liveCastingActive: false,

    // Merge all module mixins
    ...utilsMixin,
    ...apiMixin,
    ...playerMixin,
    ...uploadsMixin,
    ...viewsMixin,
    ...adminViewsMixin,
    ...uiMixin,
    ...liveMixin,
    ...adminMixin,
    ...coachingMixin,
};

// Expose globally for inline onclick handlers
window.app = app;

// Boot
document.addEventListener('DOMContentLoaded', () => app.init());
