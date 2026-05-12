// Admin Dashboard mixin: shell, sub-routing, status strip polling, role gating.
//
// The dashboard lives at /admin/{section} and consolidates Add Match (uploader+)
// and the legacy Settings page (admin only). All inner DOM IDs (form fields,
// diagnostics lists, live config, users list) are preserved so existing
// renderers in views.js / live.js keep working without changes.

// Section list — Live before Performance because operating a live broadcast
// is the higher-frequency task. The legacy `streams` section folded into
// Live Console (live viewers) and per-row VOD viewers in Matches; legacy
// `system` was renamed to `performance` so the tuning knobs and the live
// signal they control share one page. Old URLs redirect via
// resolveAdminSection() below.
const ADMIN_SECTIONS = ['overview', 'matches', 'live', 'performance', 'people', 'teams', 'users', 'settings'];
const ADMIN_ONLY_SECTIONS = new Set(['overview', 'live', 'performance', 'teams', 'users', 'settings']);
const LEGACY_SECTION_REDIRECTS = {
    streams: 'live',
    system: 'performance',
};

const SECTION_META = {
    overview:    { label: 'Overview',    glyph: '01', kicker: 'Status' },
    matches:     { label: 'Matches',     glyph: '02', kicker: 'Library' },
    live:        { label: 'Live',        glyph: '03', kicker: 'Broadcast' },
    performance: { label: 'Performance', glyph: '04', kicker: 'Encoder & host' },
    people:      { label: 'People',      glyph: '05', kicker: 'Team access' },
    teams:       { label: 'Teams',       glyph: '06', kicker: 'Tenants' },
    users:       { label: 'Users',       glyph: '07', kicker: 'Accounts' },
    settings:    { label: 'Settings',    glyph: '08', kicker: 'Branding' },
};

// Visual grouping of the admin sidebar. Routes are unchanged; only the
// rendered sidebar gains group headers so a global admin can mentally split
// broadcast ops (the public VOD/live product) from tenant ops (the secured
// coaching product) and platform-wide settings.
const ADMIN_NAV_GROUPS = [
    { label: 'Broadcast',  sections: ['overview', 'matches', 'live', 'performance'] },
    { label: 'Tenants',    sections: ['people', 'teams'] },
    { label: 'Platform',   sections: ['users', 'settings'] },
];

export const adminMixin = {
    _adminStatusTimer: null,
    _adminSection: null,

    isAdminSection(section) {
        return ADMIN_SECTIONS.includes(section) || section in LEGACY_SECTION_REDIRECTS;
    },

    canViewAdminSection(section) {
        if (section in LEGACY_SECTION_REDIRECTS) section = LEGACY_SECTION_REDIRECTS[section];
        if (section === 'matches') return this.canEdit();
        if (section === 'people') return this.isAdmin() || this.canManageTeamMembers?.();
        if (ADMIN_ONLY_SECTIONS.has(section)) return this.isAdmin();
        return this.canAccessAdminConsole?.() || this.canEdit();
    },

    resolveAdminSection(section) {
        // Honor legacy URLs so existing bookmarks (/admin/streams, /admin/system)
        // keep working after the layout refactor.
        if (section in LEGACY_SECTION_REDIRECTS) section = LEGACY_SECTION_REDIRECTS[section];
        if (!ADMIN_SECTIONS.includes(section)) return this.defaultAdminSection();
        if (!this.canViewAdminSection(section)) return this.defaultAdminSection();
        return section;
    },

    defaultAdminSection() {
        if (this.isAdmin()) return 'overview';
        if (this.canManageTeamMembers?.()) return 'people';
        return 'matches';
    },

    adminSectionUrl(section) {
        return `/admin/${this.resolveAdminSection(section)}`;
    },

    showAdminView(section, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        if (!this.canAccessAdminConsole?.()) {
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
        const groupsHtml = ADMIN_NAV_GROUPS.map((group) => {
            const visibleSections = group.sections.filter(
                (s) => this.canViewAdminSection(s)
            );
            if (!visibleSections.length) return '';
            const items = visibleSections.map((s) => {
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
            }).join('');
            return `
                <div class="admin-nav-group" data-admin-group="${group.label.toLowerCase()}">
                    <div class="admin-nav-group-head">${group.label}</div>
                    <div class="admin-nav-group-items">${items}</div>
                </div>
            `;
        }).filter(Boolean).join('');
        nav.innerHTML = groupsHtml;

        const brandLabel = document.getElementById('admin-brand-name');
        if (brandLabel) brandLabel.textContent = (this.getAppSettings().app_name || 'Replay');
        const brandRole = document.getElementById('admin-brand-role');
        if (brandRole) brandRole.textContent = isAdmin ? 'Admin Console' : (this.canManageTeamMembers?.() ? 'Team Admin Console' : 'Match Studio');
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
                // Render the form first so DOM ids exist, then start the
                // read-rail poll (viewers + throughput + encoder load).
                if (typeof this.renderLiveSettingsCard === 'function') {
                    this.renderLiveSettingsCard();
                }
                if (typeof this.renderSettingsForm === 'function') {
                    this.renderSettingsForm();
                }
                this.startLiveConsolePolling?.();
                break;
            case 'users':
                if (typeof this.renderUsersList === 'function') this.renderUsersList();
                break;
            case 'people':
                this.renderAdminPeople?.();
                break;
            case 'settings':
                if (typeof this.renderSettingsForm === 'function') this.renderSettingsForm();
                break;
            case 'performance':
                this.refreshAdminDiagnostics?.();
                this.startPerformanceTuningPolling?.();
                // Tuning knobs render here now (moved out of Settings).
                if (this.isAdmin?.() && typeof this.renderTuningKnobsCard === 'function') {
                    this.renderTuningKnobsCard();
                }
                break;
            case 'teams':
                // Phase C: global-admin team CRUD lives in js/admin-teams.js.
                this.loadAdminTeams?.();
                break;
        }
        if (section !== 'performance') this.stopPerformanceTuningPolling?.();
        if (section !== 'live') this.stopLiveConsolePolling?.();
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
            // Populate the shared cache so consumers like vodViewersForMatch
            // (matches library expanded row) and renderActiveStreams (Live
            // Console) read fresh data on the 10 s status-strip cadence
            // without having to call refreshActiveStreams themselves.
            if (streams) {
                this.activeStreams = streams.active || [];
                this.streamBlocks = streams.blocks || [];
            }
            this.renderAdminStatusStrip({ diag, streams });
            const overviewSection = document.querySelector('.admin-section[data-admin-section="overview"]');
            if (overviewSection && overviewSection.classList.contains('is-active') && diag) {
                this.diagnostics = diag;
                this.refreshOverviewKpis?.(diag, streams);
            }

            // The matches library viewers pill is computed at row-render
            // time from this.activeStreams. Without an explicit re-render
            // the pill stays at whatever value it had when the user
            // entered /admin/matches and never updates as VOD viewers
            // come and go. Cheap to re-render — just rewrites
            // #library-table-wrap, leaves filter inputs and the
            // _libraryExpanded set untouched.
            const matchesSection = document.querySelector('.admin-section[data-admin-section="matches"]');
            if (matchesSection && matchesSection.classList.contains('is-active') && typeof this.renderMatchLibraryTable === 'function') {
                this.renderMatchLibraryTable();
            }
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

    // ===== Overview KPI tiles + activity strip =====
    refreshOverviewKpis(diagnostics, streams) {
        const grid = document.getElementById('overview-kpi-grid');
        if (!grid) return;
        const counts = diagnostics?.counts || {};
        const disk = diagnostics?.disk || {};
        const settings = this.getAppSettings();
        const activeViewers = Array.isArray(streams?.active) ? streams.active.length : 0;
        const liveOn = settings.live_enabled === '1';

        // Slimmed from 6 tiles → 4. The dropped tiles (Library, HLS Backfill,
        // Active Viewers as a separate tile) move into either the matches
        // library or the activity strip / Live Console.
        const tiles = [
            {
                kicker: 'Disk',
                value: this.formatBytes(disk.free_bytes || 0),
                note: disk.enough_space === false ? 'Headroom is low.' : 'Healthy headroom for new uploads.',
                tone: disk.enough_space === false ? 'warn' : 'good',
            },
            {
                kicker: 'Encoding',
                value: counts.transcoding_slots != null ? counts.transcoding_slots : '—',
                note: `${counts.matches || 0} matches · ${counts.ready_slots || 0} ready`,
                tone: counts.transcoding_slots ? 'accent' : 'neutral',
            },
            {
                kicker: 'Failed Slots',
                value: counts.failed_slots != null ? counts.failed_slots : '—',
                note: counts.failed_slots ? 'Open Matches → expand a row to retry.' : 'No slots are stuck right now.',
                tone: counts.failed_slots ? 'bad' : 'good',
            },
            {
                kicker: 'Live',
                value: liveOn ? `On · ${activeViewers}` : 'Off',
                note: liveOn ? `${activeViewers} viewer${activeViewers === 1 ? '' : 's'} watching now.` : 'Toggle on from the Live section.',
                tone: liveOn ? 'good' : 'idle',
            },
        ];

        grid.innerHTML = tiles.map((tile) => `
            <article class="overview-tile tone-${tile.tone}">
                <span class="overview-tile-kicker">${this.esc(tile.kicker)}</span>
                <strong class="overview-tile-value">${tile.value}</strong>
                <span class="overview-tile-note">${tile.note}</span>
            </article>
        `).join('');

        this.renderActivityStrip?.(diagnostics, streams);
    },

    // Activity strip — persisted operational feed from diagnostics.recent_activity,
    // plus a few "right now" rows for active uploads/transcodes/streams.
    renderActivityStrip(diagnostics, streams) {
        const strip = document.getElementById('overview-activity-strip');
        if (!strip) return;
        const events = [];
        const nowTs = new Date().toISOString();
        const severityTone = (severity) => ({
            error: 'bad',
            warning: 'warn',
            success: 'good',
            info: 'accent',
        }[severity] || 'accent');
        const severityGlyph = (severity) => ({
            error: '!',
            warning: '!',
            success: '+',
            info: 'i',
        }[severity] || 'i');
        const eventVerb = (type) => {
            const root = String(type || 'activity').split('.')[0] || 'activity';
            return root.replace(/_/g, ' ');
        };
        const eventDetail = (e) => {
            const bits = [];
            if (e.match_id) bits.push(e.match_id);
            if (e.slot) bits.push(this.slotLabel(e.slot));
            if (e.actor) bits.push(`by ${e.actor}`);
            return bits.join(' · ');
        };

        (diagnostics?.recent_activity || []).slice(0, 12).forEach((e) => {
            events.push({
                ts: e.created_at || '',
                glyph: severityGlyph(e.severity),
                tone: severityTone(e.severity),
                verb: this.esc(eventVerb(e.event_type)),
                subject: this.esc(e.message || e.event_type || 'Activity'),
                detail: this.esc(eventDetail(e)),
            });
        });

        (diagnostics?.active_jobs || []).slice(0, 4).forEach((j) => {
            events.push({
                ts: nowTs,
                glyph: '>',
                tone: 'accent',
                verb: 'encoding now',
                subject: `${this.esc(j.home_team || '')} vs ${this.esc(j.away_team || '')} · ${this.slotLabel(j.slot)}`,
                detail: j.pct != null ? `${j.pct}%` : (j.stage || ''),
            });
        });

        (diagnostics?.upload_sessions || [])
            .filter((s) => s.status === 'active')
            .slice(0, 3)
            .forEach((s) => {
                events.push({
                    ts: nowTs,
                    glyph: '>',
                    tone: 'accent',
                    verb: 'uploading now',
                    subject: `${this.esc(s.match_id || '')} · ${this.slotLabel(s.slot)}`,
                    detail: s.progress_pct != null ? `${s.progress_pct}%` : '',
                });
            });

        const activeStreams = Array.isArray(streams?.active) ? streams.active : [];
        if (activeStreams.length) {
            const liveCount = activeStreams.filter((s) => s.kind === 'live').length;
            const vodCount = activeStreams.length - liveCount;
            events.push({
                ts: nowTs,
                glyph: 'i',
                tone: 'good',
                verb: 'streaming now',
                subject: `${activeStreams.length} viewer${activeStreams.length === 1 ? '' : 's'}`,
                detail: liveCount ? `${liveCount} live · ${vodCount} vod` : `${vodCount} vod`,
            });
        }

        if (!events.length) {
            strip.innerHTML = '<div class="activity-empty">All quiet - no recent activity in the last 72 hours.</div>';
            return;
        }

        const sorted = events.sort((a, b) => (b.ts || '').localeCompare(a.ts || '')).slice(0, 8);
        strip.innerHTML = sorted.map((ev) => `
            <div class="activity-event tone-${ev.tone}">
                <span class="activity-glyph" aria-hidden="true">${ev.glyph}</span>
                <span class="activity-verb">${ev.verb}</span>
                <span class="activity-subject">${ev.subject}</span>
                ${ev.detail ? `<span class="activity-detail">${ev.detail}</span>` : ''}
                ${ev.ts ? `<span class="activity-time">${this.esc(ev.ts.replace('T', ' ').slice(11, 16))}</span>` : ''}
            </div>
        `).join('');
    },
};

const ADMIN_SECTION_BLURBS = {
    overview:    'At-a-glance dashboard with KPIs, recent activity, and quick actions.',
    matches:     'Add a new match to the library and watch its encoding pipeline progress.',
    live:        'Broadcast cockpit: RTMP key, MediaMTX state, live viewers, and encoder load — in one place.',
    users:       'Operator accounts: create, suspend, or delete admins, uploaders, and viewers.',
    settings:    'Branding, public copy, navigation labels, and visitor download permissions.',
    performance: 'Encoder + host telemetry with tuning knobs. Change a setting, watch its impact.',
    teams:       'Tenants: create teams + seasons, manage memberships, and audit cross-team access.',
};
