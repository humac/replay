// Admin Dashboard mixin: shell, sub-routing, status strip polling, role gating.
//
// The dashboard lives at /admin/{section} and consolidates Add Match (uploader+)
// and the legacy Settings page (admin only). All inner DOM IDs (form fields,
// diagnostics lists, live config, users list) are preserved so existing
// renderers in views.js / live.js keep working without changes.

const ADMIN_SECTIONS = ['overview', 'matches', 'live', 'streams', 'users', 'settings', 'system'];
const ADMIN_ONLY_SECTIONS = new Set(['overview', 'live', 'streams', 'users', 'settings', 'system']);

const SECTION_META = {
    overview:  { label: 'Overview',  glyph: '01', kicker: 'Status' },
    matches:   { label: 'Matches',   glyph: '02', kicker: 'Library' },
    live:      { label: 'Live',      glyph: '03', kicker: 'Broadcast' },
    streams:   { label: 'Streams',   glyph: '04', kicker: 'Viewers' },
    users:     { label: 'Users',     glyph: '05', kicker: 'Accounts' },
    settings:  { label: 'Settings',  glyph: '06', kicker: 'Branding' },
    system:    { label: 'System',    glyph: '07', kicker: 'Diagnostics' },
};

export const adminMixin = {
    _adminStatusTimer: null,
    _adminSection: null,

    isAdminSection(section) {
        return ADMIN_SECTIONS.includes(section);
    },

    resolveAdminSection(section) {
        if (!ADMIN_SECTIONS.includes(section)) return this.isAdmin() ? 'overview' : 'matches';
        if (!this.isAdmin() && ADMIN_ONLY_SECTIONS.has(section)) return 'matches';
        return section;
    },

    defaultAdminSection() {
        return this.isAdmin() ? 'overview' : 'matches';
    },

    adminSectionUrl(section) {
        return `/admin/${this.resolveAdminSection(section)}`;
    },

    showAdminView(section, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        if (!this.canEdit()) {
            this.showSeasonView({ pushHistory: false, replaceHistory: true, scrollTop: false });
            return;
        }
        const resolved = this.resolveAdminSection(section);
        this.teardownGameView?.();
        this.teardownLiveView?.();
        this.stopSeasonLiveCtaPolling?.();

        this.activateView('admin-view', 'admin');
        this.renderAdminSidebar();
        this.setAdminSection(resolved);

        if (pushHistory) {
            this.pushHistoryState({ view: 'admin', section: resolved },
                { replace: replaceHistory, url: `/admin/${resolved}` });
        }
        this.startAdminStatusPolling();
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    renderAdminSidebar() {
        const nav = document.getElementById('admin-nav');
        if (!nav) return;
        const isAdmin = this.isAdmin();
        const items = ADMIN_SECTIONS
            .filter((s) => isAdmin || !ADMIN_ONLY_SECTIONS.has(s))
            .map((s) => {
                const meta = SECTION_META[s];
                return `
                    <a href="/admin/${s}" class="admin-nav-item" data-admin-section="${s}"
                       onclick="event.preventDefault(); app.showAdminView('${s}')">
                        <span class="admin-nav-glyph">${meta.glyph}</span>
                        <span class="admin-nav-text">
                            <span class="admin-nav-kicker">${meta.kicker}</span>
                            <span class="admin-nav-label">${meta.label}</span>
                        </span>
                    </a>
                `;
            })
            .join('');
        nav.innerHTML = items;

        const brandLabel = document.getElementById('admin-brand-name');
        if (brandLabel) brandLabel.textContent = (this.getAppSettings().app_name || 'Replay');
        const brandRole = document.getElementById('admin-brand-role');
        if (brandRole) brandRole.textContent = isAdmin ? 'Admin Console' : 'Match Studio';
    },

    setAdminSection(section) {
        this._adminSection = section;
        document.querySelectorAll('.admin-nav-item').forEach((el) => {
            el.classList.toggle('is-active', el.dataset.adminSection === section);
        });
        document.querySelectorAll('.admin-section').forEach((el) => {
            el.classList.toggle('is-active', el.dataset.adminSection === section);
        });
        const heading = document.getElementById('admin-section-heading');
        const sub = document.getElementById('admin-section-sub');
        const meta = SECTION_META[section];
        if (heading && meta) heading.textContent = meta.label;
        if (sub && meta) sub.textContent = ADMIN_SECTION_BLURBS[section] || '';

        // Lazy-render the section the user just landed on.
        this.renderAdminSectionContent(section);
    },

    renderAdminSectionContent(section) {
        switch (section) {
            case 'overview':
                this.refreshAdminDiagnostics?.();
                break;
            case 'matches':
                if (typeof this.renderMatchLibraryTable === 'function') {
                    this.renderMatchLibraryTable();
                }
                // Background refresh so tile counts (status strip) and
                // per-slot statuses stay current while the user is on the
                // library page. Matches list itself comes from this.matches,
                // which loadMatches() keeps refreshed.
                if (this.authToken && typeof this.refreshAdminDiagnostics === 'function') {
                    this.refreshAdminDiagnostics();
                }
                break;
            case 'live':
                if (typeof this.renderLiveSettingsCard === 'function') {
                    this.renderLiveSettingsCard();
                }
                if (typeof this.renderSettingsForm === 'function') {
                    this.renderSettingsForm();
                }
                break;
            case 'streams':
                this.refreshActiveStreams?.();
                break;
            case 'users':
                if (typeof this.renderUsersList === 'function') this.renderUsersList();
                break;
            case 'settings':
                if (typeof this.renderSettingsForm === 'function') this.renderSettingsForm();
                break;
            case 'system':
                this.refreshAdminDiagnostics?.();
                this.startPerformanceTuningPolling?.();
                break;
        }
        if (section !== 'system') this.stopPerformanceTuningPolling?.();
    },

    startAdminStatusPolling() {
        this.refreshAdminStatusStrip();
        if (this._adminStatusTimer) return;
        this._adminStatusTimer = setInterval(() => {
            const adminView = document.getElementById('admin-view');
            if (!adminView || !adminView.classList.contains('active')) {
                this.stopAdminStatusPolling();
                return;
            }
            this.refreshAdminStatusStrip();
        }, 10000);
    },

    stopAdminStatusPolling() {
        if (this._adminStatusTimer) {
            clearInterval(this._adminStatusTimer);
            this._adminStatusTimer = null;
        }
    },

    async refreshAdminStatusStrip() {
        if (!this.authToken) return;
        const strip = document.getElementById('admin-status-strip');
        if (!strip) return;

        // Diagnostics is admin-only; for uploaders we render a minimal strip.
        if (!this.isAdmin()) {
            this.renderAdminStatusStrip({ uploaderOnly: true });
            return;
        }
        try {
            const [diagResp, streamsResp] = await Promise.all([
                this.authFetch('/api/admin/diagnostics', { headers: this.getAuthHeaders() }),
                this.authFetch('/api/admin/streams', { headers: this.getAuthHeaders() }),
            ]);
            const diag = diagResp.ok ? await diagResp.json() : null;
            const streams = streamsResp.ok ? await streamsResp.json() : null;
            this.renderAdminStatusStrip({ diag, streams });
        } catch (e) {
            console.warn('status strip refresh failed', e);
        }
    },

    renderAdminStatusStrip({ diag = null, streams = null, uploaderOnly = false } = {}) {
        const strip = document.getElementById('admin-status-strip');
        if (!strip) return;

        if (uploaderOnly) {
            const settings = this.getAppSettings();
            const liveDot = settings.live_enabled === '1' ? 'state-good' : 'state-idle';
            strip.innerHTML = `
                <div class="status-cell">
                    <span class="status-dot ${liveDot}" aria-hidden="true"></span>
                    <span class="status-label">Live</span>
                    <span class="status-value">${settings.live_enabled === '1' ? 'Enabled' : 'Off'}</span>
                </div>
                <div class="status-cell">
                    <span class="status-label">Role</span>
                    <span class="status-value">${this.esc(this.userRole || 'viewer')}</span>
                </div>
            `;
            return;
        }

        const counts = diag?.counts || {};
        const disk = diag?.disk || {};
        const settings = this.getAppSettings();
        const activeViewers = Array.isArray(streams?.active) ? streams.active.length : 0;
        const blocks = Array.isArray(streams?.blocks) ? streams.blocks.length : 0;
        const failedSlots = counts.failed_slots || 0;
        const transcoding = counts.transcoding_slots || 0;
        const totalMatches = counts.matches || 0;

        const diskOk = disk.enough_space !== false;
        const liveOn = settings.live_enabled === '1';

        strip.innerHTML = `
            <div class="status-cell ${diskOk ? '' : 'is-warn'}">
                <span class="status-dot ${diskOk ? 'state-good' : 'state-warn'}" aria-hidden="true"></span>
                <span class="status-label">Disk</span>
                <span class="status-value">${this.formatBytes(disk.free_bytes || 0)}</span>
            </div>
            <div class="status-cell">
                <span class="status-dot ${liveOn ? 'state-good' : 'state-idle'}" aria-hidden="true"></span>
                <span class="status-label">Live</span>
                <span class="status-value">${liveOn ? 'On' : 'Off'}</span>
            </div>
            <div class="status-cell">
                <span class="status-dot state-accent" aria-hidden="true"></span>
                <span class="status-label">Viewers</span>
                <span class="status-value">${activeViewers}</span>
            </div>
            <div class="status-cell ${transcoding ? 'is-busy' : ''}">
                <span class="status-dot ${transcoding ? 'state-busy' : 'state-idle'}" aria-hidden="true"></span>
                <span class="status-label">Encoding</span>
                <span class="status-value">${transcoding}</span>
            </div>
            <div class="status-cell ${failedSlots ? 'is-bad' : ''}">
                <span class="status-dot ${failedSlots ? 'state-bad' : 'state-good'}" aria-hidden="true"></span>
                <span class="status-label">Failed</span>
                <span class="status-value">${failedSlots}</span>
            </div>
            <div class="status-cell">
                <span class="status-label">Matches</span>
                <span class="status-value">${totalMatches}</span>
            </div>
            ${blocks ? `
                <div class="status-cell is-bad">
                    <span class="status-dot state-bad" aria-hidden="true"></span>
                    <span class="status-label">Blocks</span>
                    <span class="status-value">${blocks}</span>
                </div>
            ` : ''}
        `;
    },

    // ===== Overview KPI tiles =====
    refreshOverviewKpis(diagnostics, streams) {
        const grid = document.getElementById('overview-kpi-grid');
        if (!grid) return;
        const counts = diagnostics?.counts || {};
        const disk = diagnostics?.disk || {};
        const settings = this.getAppSettings();
        const activeViewers = Array.isArray(streams?.active) ? streams.active.length : 0;
        const liveOn = settings.live_enabled === '1';
        const liveRtmp = settings.live_rtmp_public_url || 'Not configured';

        const tiles = [
            {
                kicker: 'Disk',
                value: this.formatBytes(disk.free_bytes || 0),
                note: disk.enough_space === false ? 'Headroom is low.' : 'Healthy headroom for new uploads.',
                tone: disk.enough_space === false ? 'warn' : 'good',
            },
            {
                kicker: 'Library',
                value: counts.matches != null ? counts.matches : '—',
                note: `${counts.ready_slots || 0} ready · ${counts.transcoding_slots || 0} encoding`,
                tone: 'neutral',
            },
            {
                kicker: 'Failed Slots',
                value: counts.failed_slots != null ? counts.failed_slots : '—',
                note: counts.failed_slots ? 'Open Matches → expand a row to retry.' : 'No slots are stuck right now.',
                tone: counts.failed_slots ? 'bad' : 'good',
            },
            {
                kicker: 'Active Viewers',
                value: activeViewers,
                note: activeViewers ? 'Open Streams to monitor or kill sessions.' : 'No one is currently watching.',
                tone: 'accent',
            },
            {
                kicker: 'Live Stream',
                value: liveOn ? 'Enabled' : 'Off',
                note: liveOn ? this.esc(liveRtmp) : 'Toggle on from the Live section.',
                tone: liveOn ? 'good' : 'idle',
            },
            {
                kicker: 'HLS Backfill',
                value: counts.hls_missing_slots != null ? counts.hls_missing_slots : '—',
                note: counts.hls_missing_slots
                    ? 'Ready MP4s missing variant ladders. Use System → Backfill.'
                    : 'All ready slots have HLS ladders.',
                tone: counts.hls_missing_slots ? 'warn' : 'good',
            },
        ];

        grid.innerHTML = tiles.map((tile) => `
            <article class="overview-tile tone-${tile.tone}">
                <span class="overview-tile-kicker">${this.esc(tile.kicker)}</span>
                <strong class="overview-tile-value">${tile.value}</strong>
                <span class="overview-tile-note">${tile.note}</span>
            </article>
        `).join('');
    },
};

const ADMIN_SECTION_BLURBS = {
    overview: 'Realtime snapshot of platform health, encoding queue, and live viewers.',
    matches:  'Add a new match to the library and watch its encoding pipeline progress.',
    live:     'Configure RTMP ingest, rotate the camera key, and inspect MediaMTX state.',
    streams:  'Active viewer sessions across live and VOD playback. Kill abusers in one click.',
    users:    'Operator accounts: create, suspend, or delete admins, uploaders, and viewers.',
    settings: 'Branding, public copy, navigation labels, and visitor download permissions.',
    system:   'Disk headroom, transcoding errors, upload sessions, and recovery operations.',
};
