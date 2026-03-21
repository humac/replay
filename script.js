// Entry point — state, init, navigation, event binding.
// Assembles all module mixins into the global `app` object.

import { utilsMixin } from './js/utils.js';
import { apiMixin } from './js/api.js';
import { playerMixin } from './js/player.js';
import { uploadsMixin } from './js/uploads.js';
import { viewsMixin } from './js/views.js';
import { uiMixin } from './js/ui.js';

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
    userName: null,
    diagnostics: null,
    transcodeProgress: {},

    // ===== INIT & LIFECYCLE =====
    async init() {
        await this.checkAuth();
        await this.loadAppSettings();
        await this.loadMatches();
        this.bindEvents();
        this.applyAppSettings();
        this.renderSeasonView();
        this.initializeHistory();
        this.initAirPlay();
        this.initCast();
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

        if (state.view === 'add-match') {
            if (!this.authToken) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            if (state.mode === 'edit' && state.matchId) {
                this.editMatch(state.matchId, { pushHistory: false, scrollTop });
                return;
            }
            this.cancelEdit();
            this.openAddMatchView({ pushHistory: false, scrollTop });
            return;
        }

        if (state.view === 'settings') {
            if (!this.authToken) {
                this.showSeasonView({ pushHistory: false, scrollTop });
                return;
            }
            this.showSettingsView({ pushHistory: false, scrollTop });
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
        this.activeMatchId = null;
        this.activeSlot = null;
        this.destroyHlsPlayer();
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn) gameEditBtn.style.display = 'none';
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
        this.updateRemotePlaybackNote();
    },

    showSeasonView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('season-view', 'season');
        this.renderSeasonView();
        if (pushHistory) {
            this.pushHistoryState({ view: 'season' }, { replace: replaceHistory, url: '/' });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    openAddMatchView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('add-match-view', 'add-match');
        if (this.authToken) this.refreshAdminDiagnostics();
        if (pushHistory) {
            this.pushHistoryState({ view: 'add-match', mode: 'create' }, { replace: replaceHistory });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    showSettingsView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('settings-view', 'settings');
        this.renderSettingsForm();
        if (pushHistory) {
            this.pushHistoryState({ view: 'settings' }, { replace: replaceHistory });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
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
                const view = e.target.dataset.view;
                if (view === 'season') {
                    this.cancelEdit();
                    this.showSeasonView();
                } else if (view === 'add-match') {
                    this.cancelEdit();
                    this.openAddMatchView();
                } else if (view === 'settings') {
                    this.cancelEdit();
                    this.showSettingsView();
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

        document.getElementById('add-match-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFormSubmit();
        });

        document.getElementById('settings-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleSettingsSubmit();
        });

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
                    label.textContent = input.files[0] ? input.files[0].name : 'No file chosen';
                    if (id.startsWith('settings-')) {
                        this.updateSettingsPendingState(id, input.files[0] || null);
                    } else {
                        this.updatePendingUploadState(id, input.files[0] || null);
                    }
                });
            }
        });
    },

    // Merge all module mixins
    ...utilsMixin,
    ...apiMixin,
    ...playerMixin,
    ...uploadsMixin,
    ...viewsMixin,
    ...uiMixin,
};

// Expose globally for inline onclick handlers
window.app = app;

// Boot
document.addEventListener('DOMContentLoaded', () => app.init());
