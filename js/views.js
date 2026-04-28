// All view rendering: season, game, match form, settings form, admin panel.

export const viewsMixin = {
    // ===== SETTINGS APPLY =====
    applyAppSettings() {
        const settings = this.getAppSettings();
        const assets = this.appAssets || {};
        document.title = settings.app_name || 'Replay';

        const faviconEl = document.querySelector('link[rel="icon"]');
        if (faviconEl && assets.favicon_url) faviconEl.href = assets.favicon_url;

        const mappings = [
            ['nav-app-name', settings.app_name],
            ['nav-season-link', settings.nav_matches_label],
            ['nav-admin', settings.nav_admin_label],
            ['season-title', settings.season_title],
            ['season-intro', settings.season_intro],
            ['filter-all-btn', settings.filter_all_label],
            ['filter-home-btn', settings.filter_home_label],
            ['filter-away-btn', settings.filter_away_label],
            ['stat-played-label', settings.stat_matches_label],
            ['stat-ready-label', settings.stat_ready_label],
            ['stat-processing-label', settings.stat_processing_label],
            ['game-back-label', settings.game_back_label],
            ['game-replay-label', settings.game_replay_label],
            ['game-video-status-label', settings.game_video_status_label],
            ['team-stats-title', `${settings.main_team_name || 'Team'} Performance`],
        ];
        mappings.forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el && value != null) el.textContent = value;
        });

        const teamStatsSubtitle = document.getElementById('team-stats-subtitle');
        if (teamStatsSubtitle) {
            teamStatsSubtitle.textContent = settings.main_team_name
                ? `Results update automatically from recorded scores for ${settings.main_team_name}.`
                : 'Set a main team name in Settings to see team results and scoring stats here.';
        }

        const seasonLogo = document.getElementById('season-logo');
        if (seasonLogo && assets.logo_url) seasonLogo.src = assets.logo_url;

        if (typeof this.refreshSeasonLiveCta === 'function') this.refreshSeasonLiveCta();

        if (this.matches.length) this.renderSeasonView();
        if (this.activeMatchId) {
            const match = this.matches.find((item) => item.id === this.activeMatchId);
            if (match) this.renderDownloadActions(match);
        }
    },

    setSeasonFilter(filter) {
        this.activeFilter = filter;
        document.querySelectorAll('#season-filter-group .filter-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.filter === filter);
        });
        this.renderSeasonView();
    },

    toggleTeamStats(force) {
        this.teamStatsExpanded = typeof force === 'boolean' ? force : !this.teamStatsExpanded;
        this.renderSeasonView();
    },

    // ===== ADMIN PANEL =====
    setAdminPanelVisibility(visible) {
        const panel = document.getElementById('admin-ops-card');
        if (!panel) return;
        panel.style.display = visible ? 'block' : 'none';
        if (!visible) {
            const diagnosticsGrid = document.getElementById('diagnostics-grid');
            const serverList = document.getElementById('upload-sessions-list');
            const localList = document.getElementById('local-upload-sessions-list');
            if (diagnosticsGrid) diagnosticsGrid.innerHTML = '';
            if (serverList) serverList.innerHTML = '';
            if (localList) localList.innerHTML = '';
        }
    },

    // ===== SETTINGS FORM =====
    renderSettingsForm() {
        const settings = this.getAppSettings();
        const fieldMap = {
            'settings-app-name': settings.app_name,
            'settings-main-team-name': settings.main_team_name,
            'settings-season-title': settings.season_title,
            'settings-season-intro': settings.season_intro,
            'settings-nav-matches-label': settings.nav_matches_label,
            'settings-nav-admin-label': settings.nav_admin_label,
            'settings-filter-all-label': settings.filter_all_label,
            'settings-filter-home-label': settings.filter_home_label,
            'settings-filter-away-label': settings.filter_away_label,
            'settings-stat-matches-label': settings.stat_matches_label,
            'settings-stat-ready-label': settings.stat_ready_label,
            'settings-stat-processing-label': settings.stat_processing_label,
            'settings-game-back-label': settings.game_back_label,
            'settings-game-replay-label': settings.game_replay_label,
            'settings-game-video-status-label': settings.game_video_status_label,
            'settings-download-label': settings.download_label,
        };
        Object.entries(fieldMap).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el) el.value = value || '';
        });
        const downloadsEnabled = document.getElementById('settings-downloads-enabled');
        if (downloadsEnabled) downloadsEnabled.checked = settings.downloads_enabled === '1';
        this.renderSettingsAssetStates();

        // Live streaming card (admin only)
        if (typeof this.renderLiveSettingsCard === 'function') this.renderLiveSettingsCard();

        // Show user management for admins
        const userCard = document.getElementById('user-management-card');
        if (userCard) {
            userCard.style.display = this.isAdmin() ? 'block' : 'none';
            if (this.isAdmin()) this.renderUsersList();
        }
    },

    async renderUsersList() {
        const container = document.getElementById('users-list');
        if (!container) return;
        const users = await this.loadUsers();
        if (!users.length) {
            container.innerHTML = '<p class="text-muted">No additional user accounts. Only the env-var admin is active.</p>';
            return;
        }
        const rows = users.map(u => `
            <div class="user-row" data-user-id="${u.id}">
                <div class="user-info">
                    <span class="user-name">${this.esc(u.display_name || u.username)}</span>
                    <span class="user-username">@${this.esc(u.username)}</span>
                </div>
                <span class="badge ${u.role}">${u.role}</span>
                <span class="badge ${u.enabled ? 'ready' : 'error'}">${u.enabled ? 'Active' : 'Disabled'}</span>
                <div class="user-actions">
                    <button class="btn-sm" onclick="app.toggleUserEnabled('${u.id}', ${!u.enabled})">${u.enabled ? 'Disable' : 'Enable'}</button>
                    <button class="btn-sm btn-danger" onclick="app.handleDeleteUser('${u.id}', '${this.esc(u.username)}')">Delete</button>
                </div>
            </div>
        `).join('');
        container.innerHTML = rows;
    },

    async handleAddUser() {
        const username = document.getElementById('new-user-username')?.value?.trim();
        const password = document.getElementById('new-user-password')?.value;
        const role = document.getElementById('new-user-role')?.value || 'viewer';
        const displayName = document.getElementById('new-user-display-name')?.value?.trim() || '';

        if (!username || !password) {
            this.showError('Username and password are required.');
            return;
        }
        if (password.length < 8) {
            this.showError('Password must be at least 8 characters.');
            return;
        }

        const btn = document.getElementById('add-user-btn');
        const restore = this.btnLoading(btn, 'Adding...');
        try {
            await this.createUser({ username, password, role, display_name: displayName });
            this.showSuccess(`User "${username}" created.`);
            document.getElementById('new-user-username').value = '';
            document.getElementById('new-user-password').value = '';
            document.getElementById('new-user-display-name').value = '';
            document.getElementById('new-user-role').value = 'viewer';
            await this.renderUsersList();
        } catch (err) {
            this.showError(err.message);
        } finally {
            restore();
        }
    },

    async toggleUserEnabled(userId, enabled) {
        try {
            await this.updateUser(userId, { enabled });
            await this.renderUsersList();
        } catch (err) {
            this.showError(err.message);
        }
    },

    async handleDeleteUser(userId, username) {
        const ok = await this.confirmAction({
            title: 'Delete user',
            message: `Delete user "${username}"? This cannot be undone.`,
            confirmLabel: 'Delete user',
            danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteUser(userId);
            this.showSuccess(`User "${username}" deleted.`);
            await this.renderUsersList();
        } catch (err) {
            this.showError(err.message);
        }
    },

    renderSettingsAssetStates() {
        const settings = this.getAppSettings();
        const logoState = document.getElementById('settings-app-logo-state');
        const faviconState = document.getElementById('settings-favicon-state');
        if (logoState) {
            logoState.textContent = settings.app_logo_filename
                ? `Current app logo: ${settings.app_logo_filename}`
                : 'No custom app logo uploaded.';
            logoState.className = `uploaded-state ${settings.app_logo_filename ? 'ready' : ''}`.trim();
        }
        if (faviconState) {
            faviconState.textContent = settings.favicon_filename
                ? `Current favicon: ${settings.favicon_filename}`
                : 'No custom favicon uploaded.';
            faviconState.className = `uploaded-state ${settings.favicon_filename ? 'ready' : ''}`.trim();
        }
    },

    updateSettingsPendingState(inputId, file) {
        const stateMap = {
            'settings-app-logo': 'settings-app-logo-state',
            'settings-favicon': 'settings-favicon-state',
        };
        const stateEl = document.getElementById(stateMap[inputId]);
        if (!stateEl) return;
        if (file) {
            stateEl.textContent = `Selected for upload: ${file.name}`;
            stateEl.className = 'uploaded-state pending';
            return;
        }
        this.renderSettingsAssetStates();
    },

    resetSettingsFileLabels() {
        ['settings-app-logo', 'settings-favicon'].forEach((id) => {
            const input = document.getElementById(id);
            const label = document.getElementById(id + '-label');
            if (input) input.value = '';
            if (label) label.textContent = 'No file chosen';
        });
        this.renderSettingsAssetStates();
    },

    async uploadSettingsAsset(inputId, kind) {
        const input = document.getElementById(inputId);
        if (!input || !input.files[0]) return;
        const form = new FormData();
        form.append('file', input.files[0]);
        const resp = await fetch(`/api/admin/settings/asset?kind=${kind}`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
            body: form,
        });
        if (resp.status === 401) {
            this.setLoggedOut();
            sessionStorage.removeItem('replay_admin_token');
            this.showLoginModal();
            throw new Error('Session expired. Please log in again.');
        }
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to upload ${kind}`);
        }
        this.setAppSettingsPayload(await resp.json());
        this.applyAppSettings();
    },

    async handleSettingsSubmit() {
        const submitBtn = document.getElementById('settings-submit-btn');
        const body = {
            app_name: document.getElementById('settings-app-name').value.trim(),
            main_team_name: document.getElementById('settings-main-team-name').value.trim(),
            season_title: document.getElementById('settings-season-title').value.trim(),
            season_intro: document.getElementById('settings-season-intro').value.trim(),
            nav_matches_label: document.getElementById('settings-nav-matches-label')?.value.trim() ?? '',
            nav_admin_label: document.getElementById('settings-nav-admin-label')?.value.trim() ?? '',
            filter_all_label: document.getElementById('settings-filter-all-label').value.trim(),
            filter_home_label: document.getElementById('settings-filter-home-label').value.trim(),
            filter_away_label: document.getElementById('settings-filter-away-label').value.trim(),
            stat_matches_label: document.getElementById('settings-stat-matches-label').value.trim(),
            stat_ready_label: document.getElementById('settings-stat-ready-label').value.trim(),
            stat_processing_label: document.getElementById('settings-stat-processing-label').value.trim(),
            game_back_label: document.getElementById('settings-game-back-label').value.trim(),
            game_replay_label: document.getElementById('settings-game-replay-label').value.trim(),
            game_video_status_label: document.getElementById('settings-game-video-status-label').value.trim(),
            download_label: document.getElementById('settings-download-label').value.trim(),
            downloads_enabled: document.getElementById('settings-downloads-enabled').checked,
            live_enabled: document.getElementById('settings-live-enabled')?.checked ?? true,
            live_rtmp_public_url: document.getElementById('settings-live-rtmp-public-url')?.value.trim() || '',
            live_offline_message: document.getElementById('settings-live-offline-message')?.value.trim() || '',
        };

        const restore = this.btnLoading(submitBtn, 'Saving...');
        try {
            const resp = await fetch('/api/admin/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify(body),
            });
            if (resp.status === 401) {
                this.setLoggedOut();
                sessionStorage.removeItem('replay_admin_token');
                this.showLoginModal();
                throw new Error('Session expired. Please log in again.');
            }
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to save settings');
            }
            this.setAppSettingsPayload(await resp.json());
            await this.uploadSettingsAsset('settings-app-logo', 'logo');
            await this.uploadSettingsAsset('settings-favicon', 'favicon');
            await this.loadAppSettings(true);
            this.applyAppSettings();
            this.renderSettingsForm();
            this.renderSeasonView();
            this.showSuccess('Settings saved.');
        } catch (error) {
            this.showError(error.message);
        } finally {
            restore('Save Settings');
            this.resetSettingsFileLabels();
        }
    },

    // ===== ADMIN DIAGNOSTICS =====
    async refreshAdminDiagnostics() {
        if (!this.authToken) return;

        const diagnosticsGrid = document.getElementById('diagnostics-grid');
        const serverList = document.getElementById('upload-sessions-list');
        const localList = document.getElementById('local-upload-sessions-list');
        if (diagnosticsGrid) diagnosticsGrid.innerHTML = '<div class="diagnostic-card"><span class="diagnostic-label">Loading</span><strong class="diagnostic-value">Updating...</strong></div>';
        if (serverList) serverList.innerHTML = '<div class="session-empty">Loading upload sessions...</div>';
        if (localList) localList.innerHTML = '<div class="session-empty">Checking resumable uploads...</div>';

        try {
            const resp = await fetch('/api/admin/diagnostics', {
                headers: this.getAuthHeaders(),
            });
            if (resp.status === 401) {
                this.setLoggedOut();
                sessionStorage.removeItem('replay_admin_token');
                this.showLoginModal();
                return;
            }
            if (!resp.ok) throw new Error('Failed to load diagnostics');
            this.diagnostics = await resp.json();
            this.renderAdminDiagnostics();
            this.renderTranscodingQueuePanel?.();
        } catch (error) {
            if (diagnosticsGrid) diagnosticsGrid.innerHTML = `<div class="session-empty">${this.esc(error.message)}</div>`;
            if (serverList) serverList.innerHTML = '<div class="session-empty">Diagnostics unavailable.</div>';
            if (localList) localList.innerHTML = this.renderLocalResumeSessions();
        }

        await this.refreshActiveStreams();
        this.refreshOverviewKpis?.(this.diagnostics, { active: this.activeStreams, blocks: this.streamBlocks });
    },

    renderTranscodingQueuePanel() {
        const list = document.getElementById('matches-queue-list');
        if (!list) return;
        const active = this.diagnostics?.active_jobs || [];
        const failed = this.diagnostics?.failed_slots || [];
        if (!active.length && !failed.length) {
            list.innerHTML = '<div class="session-empty">No active or failed encodes. New uploads will appear here while they process.</div>';
            return;
        }
        const activeRows = active.map((j) => `
            <div class="session-item">
                <div class="session-main">
                    <div class="session-title-row">
                        <strong>${this.esc(j.home_team)} vs ${this.esc(j.away_team)}</strong>
                        <span class="status-pill transcoding">${this.esc(j.stage || 'transcoding')}</span>
                    </div>
                    <div class="session-meta">${this.slotLabel(j.slot)}${j.pct != null ? ' • ' + j.pct + '%' : ''}${j.elapsed_s != null ? ' • ' + this.formatAge(j.elapsed_s) : ''}</div>
                    ${j.pct != null ? `<div class="progress-bar-container"><div class="progress-bar" style="width:${j.pct}%"></div></div>` : ''}
                </div>
            </div>
        `).join('');
        const failedRows = failed.map((f) => `
            <div class="session-item">
                <div class="session-main">
                    <div class="session-title-row">
                        <strong>${this.esc(f.home_team)} vs ${this.esc(f.away_team)}</strong>
                        <span class="status-pill error">Stuck</span>
                    </div>
                    <div class="session-meta">${this.slotLabel(f.slot)}</div>
                </div>
                <div class="session-actions">
                    <button type="button" class="mini-action-btn" onclick="app.retryTranscode('${this.esc(f.match_id)}', '${this.esc(f.slot)}')">Retry</button>
                    <button type="button" class="mini-action-btn" onclick="app.verifyAssets('${this.esc(f.match_id)}')">Verify</button>
                </div>
            </div>
        `).join('');
        list.innerHTML = activeRows + failedRows;
    },

    async refreshActiveStreams() {
        if (!this.authToken) return;
        const list = document.getElementById('active-streams-list');
        const blocksSection = document.getElementById('stream-blocks-section');
        const blocksList = document.getElementById('stream-blocks-list');
        if (!list) return;
        try {
            const resp = await fetch('/api/admin/streams', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load active streams');
            const data = await resp.json();
            this.activeStreams = data.active || [];
            this.streamBlocks = data.blocks || [];
            this.renderActiveStreams();
            if (blocksSection && blocksList) {
                if (this.streamBlocks.length) {
                    blocksSection.style.display = '';
                    blocksList.innerHTML = this.streamBlocks.map((b, idx) => `
                        <div class="session-item">
                            <div class="session-main">
                                <div class="session-title-row">
                                    <strong>${this.esc(b.ip)}</strong>
                                    <span class="status-pill error">${this.esc(b.kind)}</span>
                                </div>
                                <div class="session-meta">
                                    ${b.match_id ? this.esc(b.match_id) + (b.slot ? ' • ' + this.slotLabel(b.slot) : '') : 'live stream'}
                                    • clears in ${Math.max(0, Math.round(b.expires_in_seconds))}s
                                </div>
                            </div>
                            <div class="session-actions">
                                <button type="button" class="mini-action-btn stream-unblock-btn" data-idx="${idx}">Unblock</button>
                            </div>
                        </div>
                    `).join('');
                    blocksList.querySelectorAll('.stream-unblock-btn').forEach(btn => {
                        const idx = parseInt(btn.dataset.idx, 10);
                        btn.addEventListener('click', () => this.unblockStream(this.streamBlocks[idx]));
                    });
                } else {
                    blocksSection.style.display = 'none';
                }
            }
        } catch (error) {
            list.innerHTML = `<div class="session-empty">${this.esc(error.message)}</div>`;
        }
    },

    renderActiveStreams() {
        const list = document.getElementById('active-streams-list');
        if (!list) return;
        if (!this.activeStreams || !this.activeStreams.length) {
            list.innerHTML = '<div class="session-empty">No active streaming connections.</div>';
            return;
        }
        list.innerHTML = this.activeStreams.map((s) => {
            const target = s.kind === 'live'
                ? 'Live stream'
                : `${this.esc(s.match_label || s.match_id || 'match')}${s.slot ? ' • ' + this.slotLabel(s.slot) : ''}`;
            const geoBits = [];
            if (s.geo) {
                if (s.geo.city) geoBits.push(s.geo.city);
                if (s.geo.country) geoBits.push(s.geo.country);
            }
            const geoText = geoBits.length ? geoBits.join(', ') : '—';
            const ua = (s.user_agent || '').slice(0, 60);
            const dur = this.formatDuration ? this.formatDuration(s.duration_seconds) : `${Math.round(s.duration_seconds)}s`;
            return `
                <div class="session-item">
                    <div class="session-main">
                        <div class="session-title-row">
                            <strong>${target}</strong>
                            <span class="status-pill">${this.esc(s.kind)}</span>
                        </div>
                        <div class="session-meta">${this.esc(s.ip)} • ${this.esc(geoText)} • ${dur} • ${this.formatBytes(s.bytes_sent || 0)}</div>
                        <div class="session-meta" title="${this.esc(s.user_agent || '')}">${this.esc(ua)}${s.user_agent && s.user_agent.length > 60 ? '…' : ''}</div>
                    </div>
                    <div class="session-actions">
                        <button type="button" class="mini-action-btn" onclick="app.killStream('${this.esc(s.id)}')">Kill</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    async killStream(sessionId) {
        const ok = await this.confirmAction({
            title: 'Disconnect viewer',
            message: 'They will be blocked from this stream for 5 minutes.',
            confirmLabel: 'Disconnect',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await fetch(`/api/admin/streams/${sessionId}/kill`, {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Kill failed');
            }
            this.showSuccess('Stream disconnected.');
            await this.refreshActiveStreams();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async unblockStream(block) {
        try {
            const resp = await fetch('/api/admin/streams/blocks', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify({
                    ip: block.ip,
                    kind: block.kind,
                    match_id: block.match_id,
                    slot: block.slot,
                }),
            });
            if (!resp.ok) throw new Error('Unblock failed');
            this.showSuccess('Block cleared.');
            await this.refreshActiveStreams();
        } catch (error) {
            this.showError(error.message);
        }
    },

    renderAdminDiagnostics() {
        const diagnosticsGrid = document.getElementById('diagnostics-grid');
        const serverList = document.getElementById('upload-sessions-list');
        const localList = document.getElementById('local-upload-sessions-list');
        if (!this.diagnostics || !diagnosticsGrid || !serverList || !localList) return;

        const { counts, disk, upload_limits, upload_sessions, hls, failed_slots, active_jobs, recent_errors } = this.diagnostics;
        diagnosticsGrid.innerHTML = `
            <div class="diagnostic-card">
                <span class="diagnostic-label">Free Disk</span>
                <strong class="diagnostic-value">${this.formatBytes(disk.free_bytes)}</strong>
                <span class="diagnostic-note">Need at least ${this.formatBytes(disk.min_free_bytes)} minimum</span>
            </div>
            <div class="diagnostic-card ${disk.enough_space ? '' : 'danger'}">
                <span class="diagnostic-label">Upload Headroom</span>
                <strong class="diagnostic-value">${disk.enough_space ? 'Ready' : 'Low'}</strong>
                <span class="diagnostic-note">${disk.enough_space ? 'Disk can accept new chunk sessions.' : 'Large uploads may be rejected.'}</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">Matches</span>
                <strong class="diagnostic-value">${counts.matches}</strong>
                <span class="diagnostic-note">${counts.ready_slots} ready slots, ${counts.transcoding_slots} processing</span>
            </div>
            <div class="diagnostic-card ${counts.failed_slots > 0 ? 'danger' : ''}">
                <span class="diagnostic-label">Failed Slots</span>
                <strong class="diagnostic-value">${counts.failed_slots}</strong>
                <span class="diagnostic-note">${counts.failed_slots > 0 ? 'Slots need attention — retry or inspect errors below.' : 'No failed slots.'}</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">HLS Backfill</span>
                <strong class="diagnostic-value">${counts.hls_missing_slots}</strong>
                <span class="diagnostic-note">${hls.backfill_running ? 'Backfill is running now.' : 'Ready MP4 slots still missing HLS assets.'}</span>
            </div>
            <div class="diagnostic-card">
                <span class="diagnostic-label">Chunk Size</span>
                <strong class="diagnostic-value">${this.formatBytes(upload_limits.chunk_size_bytes)}</strong>
                <span class="diagnostic-note">Session timeout after ${this.formatDuration(upload_limits.stale_upload_session_seconds)}</span>
            </div>
        `;

        // Active jobs
        const jobsSection = document.getElementById('active-jobs-section');
        const jobsList = document.getElementById('active-jobs-list');
        if (jobsSection && jobsList) {
            if (active_jobs && active_jobs.length) {
                jobsSection.style.display = '';
                jobsList.innerHTML = active_jobs.map(j => `
                    <div class="session-item">
                        <div class="session-main">
                            <div class="session-title-row">
                                <strong>${this.esc(j.home_team)} vs ${this.esc(j.away_team)}</strong>
                                <span class="status-pill transcoding">${this.esc(j.stage || 'transcoding')}</span>
                            </div>
                            <div class="session-meta">${this.slotLabel(j.slot)}${j.pct != null ? ' • ' + j.pct + '%' : ''}${j.elapsed_s != null ? ' • ' + this.formatAge(j.elapsed_s) : ''}</div>
                            ${j.pct != null ? `<div class="progress-bar-container"><div class="progress-bar" style="width:${j.pct}%"></div></div>` : ''}
                        </div>
                    </div>
                `).join('');
            } else {
                jobsSection.style.display = 'none';
            }
        }

        // Failed slots
        const failedSection = document.getElementById('failed-slots-section');
        const failedList = document.getElementById('failed-slots-list');
        if (failedSection && failedList) {
            if (failed_slots && failed_slots.length) {
                failedSection.style.display = '';
                failedList.innerHTML = failed_slots.map(f => `
                    <div class="session-item">
                        <div class="session-main">
                            <div class="session-title-row">
                                <strong>${this.esc(f.home_team)} vs ${this.esc(f.away_team)}</strong>
                                <span class="status-pill error">Error</span>
                            </div>
                            <div class="session-meta">${this.slotLabel(f.slot)} • ${this.esc(f.match_id)}</div>
                        </div>
                        <div class="session-actions">
                            <button type="button" class="mini-action-btn" onclick="app.retryTranscode('${this.esc(f.match_id)}', '${this.esc(f.slot)}')">Retry</button>
                            <button type="button" class="mini-action-btn" onclick="app.verifyAssets('${this.esc(f.match_id)}')">Verify</button>
                        </div>
                    </div>
                `).join('');
            } else {
                failedSection.style.display = 'none';
            }
        }

        // Recent errors
        const errorsSection = document.getElementById('recent-errors-section');
        const errorsList = document.getElementById('recent-errors-list');
        if (errorsSection && errorsList) {
            if (recent_errors && recent_errors.length) {
                errorsSection.style.display = '';
                errorsList.innerHTML = recent_errors.map(e => `
                    <div class="session-item">
                        <div class="session-main">
                            <div class="session-title-row">
                                <strong>${this.esc(e.match_id)}</strong>
                                <span class="status-pill error">${this.esc(e.error_code)}</span>
                            </div>
                            <div class="session-meta">${this.slotLabel(e.slot)} • ${this.esc(e.reason)}</div>
                            ${e.details ? `<div class="session-meta error-details">${this.esc(e.details).substring(0, 200)}</div>` : ''}
                            <div class="session-meta">${this.esc(e.created_at)}</div>
                        </div>
                    </div>
                `).join('');
            } else {
                errorsSection.style.display = 'none';
            }
        }

        if (!upload_sessions.length) {
            serverList.innerHTML = '<div class="session-empty">No recent upload sessions.</div>';
        } else {
            serverList.innerHTML = upload_sessions.map((session) => `
                <div class="session-item">
                    <div class="session-main">
                        <div class="session-title-row">
                            <strong>${this.esc(session.match_id)}</strong>
                            <span class="status-pill ${this.statusClass(session.status)}">${this.statusLabel(session.status)}</span>
                        </div>
                        <div class="session-meta">${this.slotLabel(session.slot)} • ${this.formatBytes(session.uploaded_bytes)} / ${this.formatBytes(session.size_bytes)} • ${session.progress_pct}%</div>
                        <div class="session-meta">Idle ${this.formatAge(session.idle_seconds)}${session.stale ? ' • stale' : ''}</div>
                    </div>
                    <div class="session-actions">
                        ${session.status === 'active' ? `<button type="button" class="mini-action-btn" onclick="app.cancelUploadSession('${this.esc(session.session_id)}')">Cancel</button>` : ''}
                    </div>
                </div>
            `).join('');
        }

        localList.innerHTML = this.renderLocalResumeSessions();
    },

    renderLocalResumeSessions() {
        const entries = Object.entries(this.getSavedUploadSessions());
        if (!entries.length) {
            return '<div class="session-empty">No resumable uploads saved in this browser.</div>';
        }

        return entries.map(([key, session]) => `
            <div class="session-item">
                <div class="session-main">
                    <div class="session-title-row">
                        <strong>${this.esc(session.file_name || session.match_id)}</strong>
                        <span class="status-pill resume">Resume</span>
                    </div>
                    <div class="session-meta">${this.esc(session.match_id)} • ${this.slotLabel(session.slot)} • ${this.formatBytes(session.size_bytes || 0)}</div>
                    <div class="session-meta">Re-open this match form, select the same file, and submit again.</div>
                </div>
                <div class="session-actions">
                    <button type="button" class="mini-action-btn" onclick="app.clearLocalResumeSession(decodeURIComponent('${encodeURIComponent(key)}'))">Clear</button>
                </div>
            </div>
        `).join('');
    },

    async cleanupStaleUploads() {
        if (!this.authToken) return;
        try {
            const resp = await fetch('/api/uploads/sessions/cleanup', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to cleanup upload sessions');
            const data = await resp.json();
            this.showSuccess(`Cleaned ${data.count} stale upload session${data.count === 1 ? '' : 's'}.`);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async retryTranscode(matchId, slot) {
        const ok = await this.confirmAction({
            title: 'Retry transcode',
            message: `Send ${this.slotLabel(slot)} back through the encoding pipeline?`,
            confirmLabel: 'Retry',
        });
        if (!ok) return;
        try {
            const resp = await fetch(`/api/admin/matches/${matchId}/slots/${slot}/retry`, {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Retry failed');
            }
            this.showSuccess(`Retry started for ${slot}.`);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async verifyAssets(matchId) {
        try {
            const resp = await fetch(`/api/admin/matches/${matchId}/verify`, {
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Verification failed');
            const data = await resp.json();
            const lines = Object.entries(data.slots).map(([slot, info]) => {
                const parts = [];
                parts.push(`${slot}: status=${info.status}`);
                parts.push(`mp4=${info.mp4_exists ? this.formatBytes(info.mp4_size) : 'missing'}`);
                parts.push(`hls=${info.hls_complete ? 'ok' : (info.hls_master_exists ? 'incomplete' : 'missing')}`);
                if (info.missing_variants && info.missing_variants.length) {
                    parts.push(`missing: ${info.missing_variants.join(', ')}`);
                }
                return parts.join(' • ');
            });
            await this.notifyModal({
                title: 'Asset verification',
                message: lines.length ? lines.join('\n') : 'No slots found for this match.',
            });
        } catch (error) {
            this.showError(error.message);
        }
    },

    async regenerateActiveThumbnail() {
        if (!this.activeMatchId) return;
        const slot = await this.promptChoice({
            title: 'Regenerate thumbnail',
            message: 'Pick the slot to grab a frame from. "Auto" uses the default priority (full → 1st half → 2nd half).',
            options: [
                { value: '', label: 'Auto' },
                { value: 'full', label: 'Full match' },
                { value: 'first_half', label: '1st Half' },
                { value: 'second_half', label: '2nd Half' },
            ],
            initialValue: '',
            confirmLabel: 'Regenerate',
        });
        if (slot === null) return;
        const url = `/api/admin/matches/${this.activeMatchId}/regenerate-thumbnail${slot ? `?slot=${slot}` : ''}`;
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Thumbnail regeneration failed');
            }
            const data = await resp.json();
            this.showSuccess(`Thumbnail regenerated from ${data.slot}.`);
            // Bust the in-page <img> cache so admins see the new thumb without
            // reloading. Server already sends Cache-Control no-cache, but in-DOM
            // <img src> won't refetch unless the URL changes.
            const cacheBust = `?t=${Date.now()}`;
            document.querySelectorAll(`img[src*="/api/matches/${this.activeMatchId}/thumbnail"]`).forEach(img => {
                const base = img.src.split('?')[0];
                img.src = base + cacheBust;
            });
        } catch (error) {
            this.showError(error.message);
        }
    },

    async regenerateHls(matchId, slot) {
        const ok = await this.confirmAction({
            title: 'Regenerate HLS',
            message: `Rebuild the HLS variant ladder for ${this.slotLabel(slot)}?`,
            confirmLabel: 'Regenerate',
        });
        if (!ok) return;
        try {
            const resp = await fetch(`/api/admin/matches/${matchId}/slots/${slot}/regenerate-hls`, {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'HLS regeneration failed');
            }
            this.showSuccess(`HLS regenerated for ${slot}.`);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async exportDatabase() {
        try {
            const resp = await fetch('/api/admin/export-database', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Export failed');
            const blob = await resp.blob();
            const disposition = resp.headers.get('Content-Disposition') || '';
            const match = disposition.match(/filename="(.+?)"/);
            const filename = match ? match[1] : 'replay-backup.db';
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            this.showSuccess('Database exported.');
        } catch (error) {
            this.showError(error.message);
        }
    },

    async backfillExistingHls() {
        if (!this.authToken) return;
        try {
            const resp = await fetch('/api/admin/backfill-hls', {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to backfill HLS assets');
            const data = await resp.json();
            if (data.reason === 'already-running') {
                this.showInfo('HLS backfill is already running.');
            } else {
                this.showSuccess(`Backfill checked ${data.processed} ready slot${data.processed === 1 ? '' : 's'} and generated ${data.generated} HLS ladder${data.generated === 1 ? '' : 's'}.`);
            }
            await this.refreshAdminDiagnostics();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async cancelUploadSession(sessionId) {
        const ok = await this.confirmAction({
            title: 'Cancel upload session',
            message: 'This removes the partial file on disk and frees the slot. The viewer can re-upload if needed.',
            confirmLabel: 'Cancel upload',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await fetch(`/api/uploads/sessions/${sessionId}`, {
                method: 'DELETE',
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to cancel upload session');
            this.clearSavedUploadSessionBySessionId(sessionId);
            await this.refreshAdminDiagnostics();
        } catch (error) {
            this.showError(error.message);
        }
    },

    clearLocalResumeSession(key) {
        this.clearSavedUploadSession(key);
        if (this.authToken) this.renderAdminDiagnostics();
    },

    // ===== MATCH FORM =====
    toggleFormatFields() {
        const format = document.querySelector('input[name="format"]:checked').value;
        document.getElementById('video-full-group').style.display = format === 'full' ? 'block' : 'none';
        document.getElementById('video-halves-group').style.display = format === 'two_halves' ? 'block' : 'none';
    },

    updatePendingUploadState(inputId, file) {
        const stateEl = document.getElementById(inputId + '-state');
        if (!stateEl) return;

        if (file) {
            stateEl.textContent = `Selected for upload: ${file.name}`;
            stateEl.className = 'uploaded-state pending';
            return;
        }

        if (!document.getElementById('edit-match-id').value) {
            if (inputId.includes('logo')) {
                stateEl.textContent = 'No logo uploaded yet.';
            } else {
                stateEl.textContent = 'No video uploaded yet.';
            }
            stateEl.className = 'uploaded-state';
        }
    },

    renderEditAssetStates(match) {
        const assetStates = [
            {
                elementId: 'f-home-logo-state',
                present: !!match.home_logo,
                readyText: `Current logo uploaded: ${match.home_logo}`,
                emptyText: 'No home logo uploaded yet.',
            },
            {
                elementId: 'f-away-logo-state',
                present: !!match.away_logo,
                readyText: `Current logo uploaded: ${match.away_logo}`,
                emptyText: 'No away logo uploaded yet.',
            },
            {
                elementId: 'f-video-full-state',
                present: !!match.videos?.full,
                readyText: this.describeVideoState(match, 'full', 'Full match video'),
                emptyText: 'No full match video uploaded yet.',
            },
            {
                elementId: 'f-video-first-state',
                present: !!match.videos?.first_half,
                readyText: this.describeVideoState(match, 'first_half', '1st half video'),
                emptyText: 'No 1st half video uploaded yet.',
            },
            {
                elementId: 'f-video-second-state',
                present: !!match.videos?.second_half,
                readyText: this.describeVideoState(match, 'second_half', '2nd half video'),
                emptyText: 'No 2nd half video uploaded yet.',
            },
        ];

        assetStates.forEach(({ elementId, present, readyText, emptyText }) => {
            const el = document.getElementById(elementId);
            if (!el) return;
            el.textContent = present ? readyText : emptyText;
            el.className = `uploaded-state ${present ? 'ready' : ''}`.trim();
        });
    },

    describeVideoState(match, slot, label) {
        const status = this.slotStatus(match, slot);
        if (status === 'transcoding') return `${label} uploaded and processing.`;
        if (status === 'ready') return `${label} uploaded and ready to play.`;
        if (status === 'error') return `${label} upload exists but processing failed.`;
        return `${label} uploaded.`;
    },

    async handleFormSubmit() {
        const editId = document.getElementById('edit-match-id').value;
        const submitBtn = document.getElementById('submit-btn');
        const format = document.querySelector('input[name="format"]:checked').value;
        const fullFile = document.getElementById('f-video-full')?.files?.[0];
        const firstFile = document.getElementById('f-video-first')?.files?.[0];
        const secondFile = document.getElementById('f-video-second')?.files?.[0];
        let createdNewMatch = false;

        const matchData = {
            home_team: document.getElementById('f-home-team').value.trim(),
            away_team: document.getElementById('f-away-team').value.trim(),
            date: document.getElementById('f-date').value,
            time: document.getElementById('f-time').value,
            location: document.getElementById('f-location').value.trim(),
            score_home: document.getElementById('f-score-home').value ? parseInt(document.getElementById('f-score-home').value) : null,
            score_away: document.getElementById('f-score-away').value ? parseInt(document.getElementById('f-score-away').value) : null,
            format,
        };

        const restore = this.btnLoading(submitBtn, editId ? 'Updating...' : 'Creating...');

        try {
            if (!editId && format === 'full' && !fullFile) {
                throw new Error('Please choose a full-match video file before creating the match.');
            }

            if (!editId && format === 'two_halves' && !firstFile && !secondFile) {
                throw new Error('Please choose at least one half video before creating the match.');
            }

            const filesToValidate = [];
            if (format === 'full' && fullFile) filesToValidate.push(fullFile);
            if (format === 'two_halves' && firstFile) filesToValidate.push(firstFile);
            if (format === 'two_halves' && secondFile) filesToValidate.push(secondFile);
            for (const f of filesToValidate) {
                if (f.size > this.MAX_VIDEO_SIZE_BYTES) {
                    throw new Error(`File ${f.name} exceeds ${Math.round(this.MAX_VIDEO_SIZE_BYTES / (1024 * 1024 * 1024))}GB upload limit.`);
                }
            }

            let match;
            if (editId) {
                const resp = await fetch(`/api/matches/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                    body: JSON.stringify(matchData),
                });
                if (resp.status === 401) {
                    this.setLoggedOut();
                    sessionStorage.removeItem('replay_admin_token');
                    this.showLoginModal();
                    throw new Error('Session expired. Please log in again.');
                }
                match = await resp.json();
            } else {
                const resp = await fetch('/api/matches', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                    body: JSON.stringify(matchData),
                });
                if (resp.status === 401) {
                    this.setLoggedOut();
                    sessionStorage.removeItem('replay_admin_token');
                    this.showLoginModal();
                    throw new Error('Session expired. Please log in again.');
                }
                if (!resp.ok) {
                    const err = await resp.json();
                    throw new Error(err.detail || 'Failed to create match');
                }
                match = await resp.json();
                createdNewMatch = true;
                document.getElementById('edit-match-id').value = match.id;
                document.getElementById('form-heading').textContent = 'Edit Match';
                document.getElementById('submit-btn').textContent = 'Update Match';
                document.getElementById('cancel-edit-btn').style.display = 'inline-block';
            }

            await this.uploadFileIfSelected('f-home-logo', match.id, 'logo', 'home');
            await this.uploadFileIfSelected('f-away-logo', match.id, 'logo', 'away');

            if (format === 'full') {
                await this.uploadVideoIfSelected('f-video-full', match.id, 'full');
            } else {
                await this.uploadVideoIfSelected('f-video-first', match.id, 'first_half');
                await this.uploadVideoIfSelected('f-video-second', match.id, 'second_half');
            }

            await this.loadMatches();
            this.renderSeasonView();
            this.cancelEdit();
            document.getElementById('add-match-form').reset();
            this.resetFileLabels();
            this.showSeasonView({ replaceHistory: true });

            this.checkTranscodePolling();

        } catch (e) {
            if (document.getElementById('edit-match-id').value) {
                await this.loadMatches();
                this.renderSeasonView();
            }
            const resumeHint = createdNewMatch
                ? ' The match record was created. Re-submit this form to resume any incomplete upload for the same selected file.'
                : '';
            this.showError(e.message + resumeHint);
        } finally {
            const btnLabel = document.getElementById('edit-match-id').value ? 'Update Match' : 'Create Match';
            restore(btnLabel);
        }
    },

    editMatch(matchId, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        const match = this.matches.find(m => m.id === matchId);
        if (!match) return;

        this.showAdminView('matches', { pushHistory: false, scrollTop: false });
        if (this.authToken) this.refreshAdminDiagnostics();

        document.getElementById('edit-match-id').value = match.id;
        document.getElementById('f-home-team').value = match.home_team || '';
        document.getElementById('f-away-team').value = match.away_team || '';
        document.getElementById('f-date').value = match.date || '';
        document.getElementById('f-time').value = match.time || '';
        document.getElementById('f-location').value = match.location || '';
        document.getElementById('f-score-home').value = match.score_home != null ? match.score_home : '';
        document.getElementById('f-score-away').value = match.score_away != null ? match.score_away : '';

        const formatRadio = document.querySelector(`input[name="format"][value="${match.format || 'full'}"]`);
        if (formatRadio) formatRadio.checked = true;
        this.toggleFormatFields();
        this.resetFileLabels();
        this.renderEditAssetStates(match);

        document.getElementById('form-heading').textContent = 'Edit Match';
        document.getElementById('submit-btn').textContent = 'Update Match';
        document.getElementById('cancel-edit-btn').style.display = 'inline-block';

        if (pushHistory) {
            this.pushHistoryState(
                { view: 'admin', section: 'matches', mode: 'edit', matchId },
                { replace: replaceHistory, url: '/admin/matches' },
            );
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    cancelEdit() {
        document.getElementById('edit-match-id').value = '';
        document.getElementById('add-match-form').reset();
        document.getElementById('form-heading').textContent = 'Add New Match';
        document.getElementById('submit-btn').textContent = 'Create Match';
        document.getElementById('cancel-edit-btn').style.display = 'none';
        this.resetFileLabels();
    },

    async deleteMatch(matchId) {
        const ok = await this.confirmAction({
            title: 'Delete match',
            message: 'This removes the match record, all uploaded video slots, and any HLS assets. It cannot be undone.',
            confirmLabel: 'Delete match',
            danger: true,
        });
        if (!ok) return;

        try {
            const resp = await fetch(`/api/matches/${matchId}`, { method: 'DELETE', headers: this.getAuthHeaders() });
            if (resp.status === 401) {
                this.setLoggedOut();
                sessionStorage.removeItem('replay_admin_token');
                this.showLoginModal();
                throw new Error('Session expired. Please log in again.');
            }
            if (!resp.ok) throw new Error('Failed to delete');
            await this.loadMatches();
            this.renderSeasonView();
            this.showSuccess('Match deleted.');
        } catch (e) {
            this.showError(e.message);
        }
    },

    // ===== SEASON VIEW =====
    updateTranscodeBadges() {
        document.querySelectorAll('.match-card[data-match-id]').forEach(card => {
            const m = this.matches.find(x => x.id === card.dataset.matchId);
            if (!m) return;
            const metaEl = card.querySelector('.match-meta');
            if (!metaEl) return;
            const isTranscoding = this.matchTranscoding(m);
            metaEl.innerHTML = isTranscoding
                ? `<span class="badge processing">${this.matchProgressLabel(m)}</span>`
                : '';
        });
    },

    renderSeasonView() {
        const grid = document.getElementById('matches-grid');
        if (!grid) return;

        const visibleMatches = this.filteredMatches();

        document.querySelectorAll('#season-filter-group .filter-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.filter === this.activeFilter);
        });

        this.renderSeasonTeamStats(visibleMatches);

        grid.innerHTML = '';
        if (visibleMatches.length === 0) {
            const emptyMessage = this.matches.length === 0
                ? 'No matches yet. Click "Add Match" to get started.'
                : 'No matches found for the current filter.';
            grid.innerHTML = `<p style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 2rem;">${emptyMessage}</p>`;
            return;
        }

        const sorted = [...visibleMatches].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

        sorted.forEach(m => {
            const card = document.createElement('div');
            card.className = 'match-card';
            card.dataset.matchId = m.id;
            card.onclick = () => this.openMatch(m.id);

            const homeLogo = m.home_logo
                ? `<img src="/api/matches/${m.id}/logo/home" class="card-team-logo" alt="${this.esc(m.home_team)}">`
                : `<div class="card-team-initial">${this.esc((m.home_team || '?')[0])}</div>`;
            const awayLogo = m.away_logo
                ? `<img src="/api/matches/${m.id}/logo/away" class="card-team-logo" alt="${this.esc(m.away_team)}">`
                : `<div class="card-team-initial">${this.esc((m.away_team || '?')[0])}</div>`;

            const hasScore = m.score_home != null && m.score_away != null;
            const revealed = this.isMatchScoreRevealed(m.id);
            const showScore = hasScore && revealed;
            const homeScoreHtml = showScore
                ? `<span class="card-team-score">${m.score_home}</span>`
                : (hasScore ? '<span class="card-team-score is-hidden" aria-hidden="true">\u2014</span>' : '');
            const awayScoreHtml = showScore
                ? `<span class="card-team-score">${m.score_away}</span>`
                : (hasScore ? '<span class="card-team-score is-hidden" aria-hidden="true">\u2014</span>' : '');

            const dateStr = this.formatDate(m.date);
            const timeStr = m.time ? ` \u00b7 ${m.time}` : '';
            const locationHtml = m.location
                ? `<span class="match-detail-pill location"><span class="pill-label">Location</span>${this.esc(m.location)}</span>`
                : '';
            const revealChipHtml = (hasScore && !revealed)
                ? `<button type="button" class="score-reveal-chip" onclick="app.revealMatchScore('${m.id}', event)" aria-label="Reveal final score for this match">
                       <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                       <span>Reveal score</span>
                   </button>`
                : '';

            const isTranscoding = this.matchTranscoding(m);
            if (m.has_thumbnail) card.classList.add('has-thumb');

            const thumbHtml = m.has_thumbnail
                ? `<img src="/api/matches/${m.id}/thumbnail" class="card-thumb" alt="" loading="lazy">`
                : '';
            const bodyOpen = m.has_thumbnail ? '<div class="card-body">' : '';
            const bodyClose = m.has_thumbnail ? '</div>' : '';

            card.innerHTML = `
                ${thumbHtml}
                ${bodyOpen}
                <div class="card-bg"></div>
                <div class="card-matchup">
                    <div class="card-team-col">
                        ${homeLogo}
                        <span class="team-side-label">Home</span>
                        <div class="team-name-score-row">
                            <span class="card-team-name">${this.esc(m.home_team)}</span>
                            ${homeScoreHtml}
                        </div>
                    </div>
                    <div class="card-vs-col">
                        <span class="card-vs">VS</span>
                    </div>
                    <div class="card-team-col">
                        ${awayLogo}
                        <span class="team-side-label">Away</span>
                        <div class="team-name-score-row">
                            <span class="card-team-name">${this.esc(m.away_team)}</span>
                            ${awayScoreHtml}
                        </div>
                    </div>
                </div>
                <div class="match-detail-row">
                    <span class="match-detail-pill">${this.esc(dateStr)}${timeStr}</span>
                    ${locationHtml}
                    ${revealChipHtml}
                </div>
                <div class="match-meta">
                    ${isTranscoding ? `<span class="badge processing">${this.matchProgressLabel(m)}</span>` : ''}
                </div>
                <div class="hover-reveal">VIEW MATCH <span>&rarr;</span></div>
                ${bodyClose}
                ${this.canEdit() ? `
                <button class="match-card-edit-btn" onclick="app.triggerEdit(event, '${m.id}')" title="Edit">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                ${this.isAdmin() ? `<button class="match-card-delete-btn" onclick="app.triggerDelete(event, '${m.id}')" title="Delete">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>` : ''}
                ` : ''}
            `;
            grid.appendChild(card);
        });
    },

    triggerEdit(event, matchId) {
        event.stopPropagation();
        this.editMatch(matchId);
    },

    triggerDelete(event, matchId) {
        event.stopPropagation();
        this.deleteMatch(matchId);
    },

    isMatchScoreRevealed(matchId) {
        return !!this._revealedScores && this._revealedScores.has(String(matchId));
    },

    revealMatchScore(matchId, event) {
        if (event) event.stopPropagation();
        if (!this._revealedScores) this._revealedScores = new Set();
        this._revealedScores.add(String(matchId));
        if (document.getElementById('season-view')?.classList.contains('active')) {
            this.renderSeasonView();
        }
        if (document.getElementById('game-view')?.classList.contains('active') && this.activeMatchId === matchId) {
            const match = this.matches.find((m) => m.id === matchId);
            if (match) this.renderGameMatchup(match);
        }
    },

    renderGameMatchup(match) {
        const matchupEl = document.getElementById('game-matchup');
        const revealEl = document.getElementById('game-score-reveal');
        if (!matchupEl) return;

        const homeLogo = match.home_logo
            ? `<img src="/api/matches/${match.id}/logo/home" class="game-logo-large">`
            : `<div class="game-logo-initial-large">${this.esc((match.home_team || '?')[0])}</div>`;
        const awayLogo = match.away_logo
            ? `<img src="/api/matches/${match.id}/logo/away" class="game-logo-large">`
            : `<div class="game-logo-initial-large">${this.esc((match.away_team || '?')[0])}</div>`;

        const hasScore = match.score_home != null && match.score_away != null;
        const revealed = this.isMatchScoreRevealed(match.id);
        const showScore = hasScore && revealed;
        const homeScoreHtml = showScore
            ? `<span class="game-team-score">${match.score_home}</span>`
            : (hasScore ? '<span class="game-team-score is-hidden" aria-hidden="true">—</span>' : '');
        const awayScoreHtml = showScore
            ? `<span class="game-team-score">${match.score_away}</span>`
            : (hasScore ? '<span class="game-team-score is-hidden" aria-hidden="true">—</span>' : '');

        matchupEl.innerHTML = `
            <div class="game-team-col">
                ${homeLogo}
                <span class="team-side-label game-side-label">Home</span>
                <div class="team-name-score-row game-team-name-score-row">
                    <span class="game-team-name">${this.esc(match.home_team)}</span>
                    ${homeScoreHtml}
                </div>
            </div>
            <div class="game-vs-col">VS</div>
            <div class="game-team-col">
                ${awayLogo}
                <span class="team-side-label game-side-label">Away</span>
                <div class="team-name-score-row game-team-name-score-row">
                    <span class="game-team-name">${this.esc(match.away_team)}</span>
                    ${awayScoreHtml}
                </div>
            </div>
        `;

        if (revealEl) {
            if (hasScore && !revealed) {
                revealEl.innerHTML = `
                    <button type="button" class="score-reveal-chip score-reveal-chip-large" onclick="app.revealMatchScore('${match.id}', event)" aria-label="Reveal final score for this match">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        <span>Reveal final score</span>
                    </button>
                `;
            } else {
                revealEl.innerHTML = '';
            }
        }
    },

    toggleSeasonRecord() {
        this.recordVisible = !this.recordVisible;
        this.renderSeasonView();
    },

    countAvailableReplays(matches) {
        return matches.filter((match) => {
            if (match.format === 'two_halves') {
                return this.slotStatus(match, 'first_half') === 'ready'
                    || this.slotStatus(match, 'second_half') === 'ready';
            }
            return this.slotStatus(match, 'full') === 'ready';
        }).length;
    },

    // ===== GAME VIEW =====
    openMatch(matchId, { pushHistory = true, replaceHistory = false, scrollTop = true, initialSlot = null } = {}) {
        const match = this.matches.find(m => m.id === matchId);
        if (!match) return;
        this._pendingInitialSlot = initialSlot;
        if (typeof this.teardownLiveView === 'function') this.teardownLiveView();
        if (typeof this.stopSeasonLiveCtaPolling === 'function') this.stopSeasonLiveCtaPolling();

        this.activeMatchId = matchId;
        const gameEditBtn = document.getElementById('game-edit-btn');
        if (gameEditBtn) gameEditBtn.style.display = this.canEdit() ? 'inline-flex' : 'none';
        const regenThumbBtn = document.getElementById('game-regen-thumb-btn');
        if (regenThumbBtn) regenThumbBtn.style.display = this.isAdmin() ? 'inline-flex' : 'none';

        // Update prev/next nav buttons
        const prevBtn = document.getElementById('prev-match-btn');
        const nextBtn = document.getElementById('next-match-btn');
        if (prevBtn) prevBtn.style.display = this.getAdjacentMatch(-1) ? 'inline-flex' : 'none';
        if (nextBtn) nextBtn.style.display = this.getAdjacentMatch(1) ? 'inline-flex' : 'none';

        document.getElementById('active-game-date').textContent =
            this.formatDate(match.date) + (match.time ? ` \u00b7 ${match.time}` : '');

        document.getElementById('active-game-loc').textContent = match.location || '-';
        this.renderGameStatus(match);

        this.renderGameMatchup(match);

        this.activateView('game-view');
        if (pushHistory) {
            const matchUrl = match.slug ? `/match/${match.slug}` : null;
            this.pushHistoryState({ view: 'game', matchId, slug: match.slug }, { replace: replaceHistory, url: matchUrl });
        }

        this.setupVideoSlots(match);
        this.renderDownloadActions(match);
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    setupVideoSlots(match) {
        const segSelector = document.getElementById('segment-selector');
        segSelector.innerHTML = '';

        if (match.format === 'two_halves') {
            segSelector.style.display = 'flex';
            const readySlots = [];

            ['first_half', 'second_half'].forEach(slot => {
                const status = this.slotStatus(match, slot);
                const btn = document.createElement('button');
                btn.className = 'segment-btn';
                btn.dataset.slot = slot;

                if (status === 'ready') {
                    btn.textContent = slot === 'first_half' ? '1st Half' : '2nd Half';
                    btn.onclick = () => this.playSlot(match.id, slot);
                    readySlots.push(slot);
                } else if (status === 'transcoding') {
                    const pLabel = this.slotProgressLabel(match.id, slot);
                    const suffix = pLabel ? ` (${pLabel})` : ' (processing)';
                    btn.textContent = (slot === 'first_half' ? '1st Half' : '2nd Half') + suffix;
                    btn.disabled = true;
                    btn.style.opacity = '0.5';
                } else {
                    return;
                }
                segSelector.appendChild(btn);
            });

            if (readySlots.length > 0) {
                const preferred = this._pendingInitialSlot && readySlots.includes(this._pendingInitialSlot)
                    ? this._pendingInitialSlot : readySlots[0];
                this._pendingInitialSlot = null;
                this.playSlot(match.id, preferred);
            } else if (this.matchTranscoding(match)) {
                this.showProcessingState();
            } else {
                this.showNoVideoState();
            }
        } else {
            segSelector.style.display = 'none';
            const status = this.slotStatus(match, 'full');
            if (status === 'ready') {
                this.playSlot(match.id, 'full');
            } else if (status === 'transcoding') {
                this.showProcessingState();
            } else {
                this.showNoVideoState();
            }
        }
    },

    refreshGameView(match) {
        if (!document.getElementById('game-view').classList.contains('active')) return;
        this.renderGameStatus(match);
        this.renderDownloadActions(match);

        if (this.activeSlot) {
            const status = this.slotStatus(match, this.activeSlot);
            if (status === 'ready') return;
        }

        this.setupVideoSlots(match);
    },

    closeGame() {
        this.showSeasonView({ replaceHistory: true });
    },

    renderDownloadActions(match) {
        const container = document.getElementById('download-actions');
        if (!container) return;
        const settings = this.getAppSettings();
        if (settings.downloads_enabled !== '1') {
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        const slots = match.format === 'two_halves'
            ? [['first_half', this.slotLabel('first_half')], ['second_half', this.slotLabel('second_half')]]
            : [['full', this.slotLabel('full')]];
        const readySlots = slots.filter(([slot]) => this.slotStatus(match, slot) === 'ready');
        if (!readySlots.length) {
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        container.style.display = 'flex';
        container.innerHTML = readySlots.map(([slot, label]) => `
            <a class="download-btn" href="/api/matches/${match.id}/download/${slot}" download>
                ${this.esc(settings.download_label)} ${this.esc(label)}
            </a>
        `).join('');
    },

    // ===== SEASON TEAM STATS =====
    renderSeasonTeamStats(visibleMatches) {
        const section = document.getElementById('season-team-stats');
        const grid = document.getElementById('team-stats-grid');
        const empty = document.getElementById('team-stats-empty');
        const title = document.getElementById('team-stats-title');
        const toggle = document.getElementById('team-stats-toggle');
        if (!section || !grid || !empty || !title) return;

        if (toggle) {
            toggle.setAttribute('aria-expanded', this.teamStatsExpanded ? 'true' : 'false');
        }
        section.classList.toggle('is-collapsed', !this.teamStatsExpanded);
        section.setAttribute('aria-hidden', this.teamStatsExpanded ? 'false' : 'true');

        const settings = this.getAppSettings();
        const mainTeamName = settings.main_team_name?.trim();
        title.textContent = `${mainTeamName || 'Team'} Performance`;

        if (!mainTeamName) {
            grid.innerHTML = '';
            empty.style.display = 'block';
            empty.textContent = 'Set the main team name in Settings to unlock score-based season stats.';
            return;
        }

        const teamMatches = visibleMatches.filter((match) => this.matchFilterCategory(match) !== 'other');
        const scoredMatches = teamMatches.filter((match) => match.score_home != null && match.score_away != null);

        if (!scoredMatches.length) {
            grid.innerHTML = '';
            empty.style.display = 'block';
            empty.textContent = teamMatches.length
                ? 'Scores have not been entered for the matches in this view yet.'
                : `No ${mainTeamName} matches are currently visible for this filter.`;
            return;
        }

        let wins = 0;
        let draws = 0;
        let losses = 0;
        let goalsFor = 0;
        let goalsAgainst = 0;
        let cleanSheets = 0;

        scoredMatches.forEach((match) => {
            const category = this.matchFilterCategory(match);
            const teamScore = category === 'home' ? Number(match.score_home || 0) : Number(match.score_away || 0);
            const opponentScore = category === 'home' ? Number(match.score_away || 0) : Number(match.score_home || 0);
            goalsFor += teamScore;
            goalsAgainst += opponentScore;
            if (teamScore > opponentScore) wins += 1;
            else if (teamScore < opponentScore) losses += 1;
            else draws += 1;
            if (opponentScore === 0) cleanSheets += 1;
        });

        const points = wins * 3 + draws;
        const gamesPlayed = scoredMatches.length;
        const goalDiff = goalsFor - goalsAgainst;
        const pointsPerGame = gamesPlayed ? (points / gamesPlayed).toFixed(2) : '0.00';
        const avgGoals = gamesPlayed ? (goalsFor / gamesPlayed).toFixed(1) : '0.0';
        const replayCount = this.countAvailableReplays(teamMatches);

        // Effort-first KPIs — what was played and produced, not won.
        const effortCards = [
            {
                label: 'Matches Played',
                value: String(gamesPlayed),
                note: gamesPlayed === 1 ? 'with a final score recorded' : 'with final scores recorded',
            },
            {
                label: 'Goals Scored',
                value: String(goalsFor),
                note: `${avgGoals} per match on average`,
            },
            {
                label: 'Clean Sheets',
                value: String(cleanSheets),
                note: cleanSheets === 0 ? 'No shutouts yet — there\'s next week.' : `Out of ${gamesPlayed} scored matches`,
            },
            {
                label: 'Replays Available',
                value: String(replayCount),
                note: replayCount === teamMatches.length
                    ? 'Every match has a replay ready to watch.'
                    : `${teamMatches.length - replayCount} still uploading or processing.`,
            },
        ];

        empty.style.display = 'none';
        const recordOpen = !!this.recordVisible;
        grid.innerHTML = `
            <div class="team-stat-grid-tiles">
                ${effortCards.map((card) => `
                    <article class="team-stat-card neutral">
                        <span class="team-stat-label">${this.esc(card.label)}</span>
                        <strong class="team-stat-value">${this.esc(card.value)}</strong>
                        <span class="team-stat-note">${this.esc(card.note)}</span>
                    </article>
                `).join('')}
            </div>
            <button type="button"
                    class="team-record-toggle ${recordOpen ? 'is-open' : ''}"
                    aria-expanded="${recordOpen ? 'true' : 'false'}"
                    onclick="app.toggleSeasonRecord()">
                <span class="team-record-toggle-label">${recordOpen ? 'Hide record' : 'Show record'}</span>
                <span class="team-record-toggle-caret" aria-hidden="true">▾</span>
            </button>
            ${recordOpen ? `
                <div class="team-record-strip" role="group" aria-label="Win-loss record">
                    <div class="team-record-cell record">
                        <span class="team-record-label">Record</span>
                        <strong class="team-record-value">${wins}-${draws}-${losses}</strong>
                        <span class="team-record-note">W-D-L</span>
                    </div>
                    <div class="team-record-cell points">
                        <span class="team-record-label">Points</span>
                        <strong class="team-record-value">${points}</strong>
                        <span class="team-record-note">${pointsPerGame} per game</span>
                    </div>
                    <div class="team-record-cell difference">
                        <span class="team-record-label">Goal Diff</span>
                        <strong class="team-record-value">${goalDiff > 0 ? '+' : ''}${goalDiff}</strong>
                        <span class="team-record-note">${goalsFor} for · ${goalsAgainst} against</span>
                    </div>
                </div>
            ` : ''}
        `;
    },

    // ===== GAME STATUS =====
    renderGameStatus(match) {
        const pills = document.getElementById('game-status-pills');
        const slotList = document.getElementById('game-slot-status-list');
        if (!slotList) return;

        const formatLabel = match.format === 'two_halves' ? 'Two Halves' : 'Full Match';
        const readySlots = this.readySlotsCount(match);
        const totalSlots = match.format === 'two_halves' ? 2 : 1;
        if (pills) {
            pills.innerHTML = `
                <span class="status-pill neutral">${this.esc(formatLabel)}</span>
                <span class="status-pill ${this.matchTranscoding(match) ? 'processing' : 'ready'}">${readySlots}/${totalSlots} Ready</span>
            `;
        }

        const slots = match.format === 'two_halves'
            ? [['first_half', '1st Half'], ['second_half', '2nd Half']]
            : [['full', 'Full Match']];
        slotList.innerHTML = slots.map(([slot, label]) => {
            const status = this.slotStatus(match, slot);
            const progressLabel = status === 'transcoding' ? this.slotProgressLabel(match.id, slot) : null;
            const displayLabel = progressLabel || this.statusLabel(status);
            return `
                <div class="slot-status-row">
                    <span class="slot-status-label">${label}</span>
                    <span class="status-pill ${this.statusClass(status)}">${this.esc(displayLabel)}</span>
                </div>
            `;
        }).join('');
    },
};
