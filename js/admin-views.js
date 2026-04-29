// Admin view renderers and action methods.

export const adminViewsMixin = {
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

        // Performance Tuning card (admin only — needs the tuning_knobs schema
        // which is only returned by the admin settings endpoint).
        if (this.isAdmin()) this.renderTuningKnobsCard();

        // Show user management for admins
        const userCard = document.getElementById('user-management-card');
        if (userCard) {
            userCard.style.display = this.isAdmin() ? 'block' : 'none';
            if (this.isAdmin()) this.renderUsersList();
        }
    },

    // ===== PERFORMANCE TUNING =====
    async renderTuningKnobsCard() {
        const card = document.getElementById('tuning-knobs-card');
        const grid = document.getElementById('tuning-knobs-grid');
        if (!card || !grid) return;

        // Pull the admin settings payload (knob schema lives there, not in the
        // public bootstrap). Cache on the app object so the preset buttons can
        // re-use it without an extra fetch.
        let payload;
        try {
            const resp = await this.authFetch('/api/admin/settings', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load tuning settings');
            payload = await resp.json();
        } catch (err) {
            grid.innerHTML = `<div class="session-empty">${this.esc(err.message)}</div>`;
            return;
        }
        this._tuningPayload = payload;
        const settings = payload.settings || {};
        const knobs = payload.tuning_knobs || {};

        const order = [
            'transcode_concurrency', 'replay_hwaccel', 'hls_segment_duration',
            'max_upload_size_bytes', 'upload_chunk_size_bytes',
            'min_free_disk_bytes', 'upload_disk_headroom_multiplier',
            'stale_upload_session_seconds', 'video_stream_chunk_bytes',
            'hls_variant_presets',
            'live_hls_variant', 'live_record_enabled', 'live_transcode_enabled',
        ];
        const html = order.filter((key) => knobs[key]).map((key) => {
            const spec = knobs[key];
            const value = settings[key] ?? '';
            const restart = spec.restart
                ? '<span class="status-pill warn">Restart required</span>'
                : '';
            return `
                <div class="form-group" data-tuning-key="${key}">
                    <label for="tuning-${key}">
                        ${this.esc(spec.label || key)}
                        ${restart}
                    </label>
                    ${this.tuningKnobInput(key, spec, value)}
                    <div class="form-help">${this.esc(spec.help || '')}</div>
                </div>
            `;
        }).join('');
        grid.innerHTML = html;

        // Audit list
        const auditList = document.getElementById('tuning-audit-list');
        const auditCountEl = document.getElementById('diag-audit-count');
        if (auditList) {
            const entries = payload.audit || [];
            if (auditCountEl) auditCountEl.textContent = String(entries.length);
            auditList.innerHTML = entries.length
                ? entries.map((e) => `
                    <div class="session-item">
                        <div class="session-title-row">
                            <strong>${this.esc(e.key)}</strong>
                            <span class="status-pill neutral">${this.esc(e.actor || 'system')}</span>
                        </div>
                        <div class="session-meta">
                            <span>${this.esc(e.ts)}</span>
                            <span>${this.esc(e.old_value ?? '∅')} → ${this.esc(e.new_value)}</span>
                        </div>
                    </div>
                `).join('')
                : '<div class="session-empty">No tuning changes yet.</div>';
        }

        // Wire preset buttons (idempotent — replaces handlers on re-render)
        const card2 = document.getElementById('tuning-knobs-card');
        if (card2) {
            card2.querySelectorAll('[data-tuning-preset]').forEach((btn) => {
                btn.onclick = () => this.applyTuningPreset(btn.dataset.tuningPreset);
            });
        }
    },

    tuningKnobInput(key, spec, value) {
        const id = `tuning-${key}`;
        if (spec.kind === 'bool') {
            return `
                <label class="checkbox-label">
                    <input type="checkbox" id="${id}" data-tuning-input="${key}" data-tuning-kind="bool" ${value === '1' ? 'checked' : ''}>
                    Enable
                </label>
            `;
        }
        if (spec.kind === 'enum') {
            const opts = (spec.choices || []).map((c) => `<option value="${this.esc(c)}" ${c === value ? 'selected' : ''}>${this.esc(c)}</option>`).join('');
            return `<select id="${id}" data-tuning-input="${key}" data-tuning-kind="enum">${opts}</select>`;
        }
        if (spec.kind === 'json') {
            // Variant ladder gets its own structured editor; everything else
            // falls back to a JSON textarea.
            if (key === 'hls_variant_presets') {
                return this.renderHlsLadderEditor(value);
            }
            return `<textarea id="${id}" data-tuning-input="${key}" data-tuning-kind="json" rows="6">${this.esc(value)}</textarea>`;
        }
        // int / float
        const min = spec.min ?? '';
        const max = spec.max ?? '';
        const step = spec.kind === 'float' ? 'any' : '1';
        return `<input type="number" id="${id}" data-tuning-input="${key}" data-tuning-kind="${spec.kind}" min="${min}" max="${max}" step="${step}" value="${this.esc(value)}">`;
    },

    renderHlsLadderEditor(rawValue) {
        let rows = [];
        try {
            const parsed = JSON.parse(rawValue || '[]');
            if (Array.isArray(parsed)) rows = parsed;
        } catch (_) { /* leave empty */ }
        const headers = ['Enabled', 'Name', 'Height', 'Width', 'Video kbps', 'Maxrate', 'Bufsize', 'Audio kbps', 'Bandwidth'];
        const tableHead = headers.map((h) => `<th>${h}</th>`).join('');
        const body = rows.map((r, idx) => `
            <tr data-ladder-row="${idx}">
                <td><input type="checkbox" data-ladder-field="enabled" ${r.enabled !== false ? 'checked' : ''}></td>
                <td><input type="text" data-ladder-field="name" value="${this.esc(r.name || '')}" maxlength="12" size="6"></td>
                <td><input type="number" data-ladder-field="height" value="${this.esc(r.height ?? '')}" min="240" max="2160" step="2" size="5"></td>
                <td><input type="number" data-ladder-field="width" value="${this.esc(r.width ?? '')}" min="320" max="3840" step="2" size="5"></td>
                <td><input type="text" data-ladder-field="video_bitrate" value="${this.esc(r.video_bitrate || '')}" size="6"></td>
                <td><input type="text" data-ladder-field="maxrate" value="${this.esc(r.maxrate || '')}" size="6"></td>
                <td><input type="text" data-ladder-field="bufsize" value="${this.esc(r.bufsize || '')}" size="6"></td>
                <td><input type="text" data-ladder-field="audio_bitrate" value="${this.esc(r.audio_bitrate || '')}" size="5"></td>
                <td><input type="number" data-ladder-field="bandwidth" value="${this.esc(r.bandwidth ?? '')}" size="9"></td>
            </tr>
        `).join('');
        return `
            <div class="ladder-editor" data-tuning-input="hls_variant_presets" data-tuning-kind="json">
                <table class="ladder-table">
                    <thead><tr>${tableHead}</tr></thead>
                    <tbody>${body}</tbody>
                </table>
            </div>
        `;
    },

    collectTuningKnobs() {
        const out = {};
        const card = document.getElementById('tuning-knobs-card');
        if (!card) return out;
        card.querySelectorAll('[data-tuning-input]').forEach((el) => {
            const key = el.dataset.tuningInput;
            const kind = el.dataset.tuningKind;
            if (kind === 'bool') {
                out[key] = el.checked ? '1' : '0';
            } else if (kind === 'json' && el.classList.contains('ladder-editor')) {
                const rows = [];
                el.querySelectorAll('[data-ladder-row]').forEach((tr) => {
                    const row = {};
                    tr.querySelectorAll('[data-ladder-field]').forEach((f) => {
                        const field = f.dataset.ladderField;
                        if (field === 'enabled') row.enabled = f.checked;
                        else if (field === 'height' || field === 'width' || field === 'bandwidth') row[field] = Number(f.value || 0);
                        else row[field] = f.value;
                    });
                    rows.push(row);
                });
                out[key] = JSON.stringify(rows);
            } else if (kind === 'json') {
                out[key] = el.value;
            } else {
                out[key] = el.value;
            }
        });
        return out;
    },

    async applyTuningPreset(preset) {
        const presets = {
            'conservative': {
                transcode_concurrency: '2',
                replay_hwaccel: 'auto',
                hls_segment_duration: '6',
                live_hls_variant: 'mpegts',
                live_record_enabled: '0',
                live_transcode_enabled: '0',
            },
            'balanced-10g': {
                transcode_concurrency: '4',
                replay_hwaccel: 'qsv',
                hls_segment_duration: '4',
                video_stream_chunk_bytes: String(2 * 1024 * 1024),
                upload_chunk_size_bytes: String(32 * 1024 * 1024),
            },
            'live-first': {
                transcode_concurrency: '2',
                replay_hwaccel: 'qsv',
                hls_segment_duration: '4',
                live_hls_variant: 'lowLatency',
                live_record_enabled: '1',
                live_transcode_enabled: '1',
            },
        };
        const body = presets[preset];
        if (!body) return;
        const ok = await this.confirmAction({
            title: 'Apply tuning preset',
            message: `Apply the "${preset}" preset? This updates several settings at once.`,
            confirmLabel: 'Apply preset',
        });
        if (!ok) return;
        await this.saveTuningKnobs(body, `Applied preset: ${preset}`);
    },

    async saveTuningKnobs(body, successMessage) {
        try {
            const resp = await this.authFetch('/api/admin/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const detail = err.detail;
                const msg = (detail && typeof detail === 'object' && detail.errors)
                    ? Object.entries(detail.errors).map(([k, v]) => `${k}: ${v}`).join('; ')
                    : (typeof detail === 'string' ? detail : 'Failed to save tuning knobs');
                throw new Error(msg);
            }
            const payload = await resp.json();
            this._tuningPayload = payload;
            await this.loadAppSettings(true);
            await this.renderTuningKnobsCard();
            this.showSuccess(successMessage || 'Tuning saved.');
        } catch (err) {
            this.showError(err.message);
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
        const resp = await this.authFetch(`/api/admin/settings/asset?kind=${kind}`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
            body: form,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to upload ${kind}`);
        }
        this.setAppSettingsPayload(await resp.json());
        this.applyAppSettings();
    },

    // Tuning-only save path used by the Performance section's #tuning-save-btn.
    // /api/admin/settings PUT accepts partial bodies (server iterates submitted
    // keys), so omitting branding/copy/live fields leaves them untouched. This
    // avoids the bug where saving tuning from the Performance section would
    // PUT empty live form values (HTML defaults) and silently disable live
    // streaming + clear the configured RTMP URL.
    async handleTuningSubmit() {
        const submitBtn = document.getElementById('tuning-save-btn');
        const body = { ...this.collectTuningKnobs() };
        const restore = this.btnLoading(submitBtn, 'Saving...');
        try {
            const resp = await this.authFetch('/api/admin/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const detail = err.detail;
                const msg = (detail && typeof detail === 'object' && detail.errors)
                    ? Object.entries(detail.errors).map(([k, v]) => `${k}: ${v}`).join('; ')
                    : (typeof detail === 'string' ? detail : 'Failed to save tuning');
                throw new Error(msg);
            }
            this.setAppSettingsPayload(await resp.json());
            this.applyAppSettings();
            this.renderTuningKnobsCard();
            this.showSuccess('Tuning saved.');
        } catch (error) {
            this.showError(error.message);
        } finally {
            restore('Save Tuning');
        }
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
            ...this.collectTuningKnobs(),
        };

        const restore = this.btnLoading(submitBtn, 'Saving...');
        try {
            const resp = await this.authFetch('/api/admin/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const detail = err.detail;
                const msg = (detail && typeof detail === 'object' && detail.errors)
                    ? Object.entries(detail.errors).map(([k, v]) => `${k}: ${v}`).join('; ')
                    : (typeof detail === 'string' ? detail : 'Failed to save settings');
                throw new Error(msg);
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
            const resp = await this.authFetch('/api/admin/diagnostics', {
                headers: this.getAuthHeaders(),
            });
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

    // ===== MATCH LIBRARY TABLE =====
    //
    // Library state lives on the app instance so filter inputs survive
    // re-renders and the expanded-row set persists across status polls.
    _libraryFilters: null,
    _libraryExpanded: null,
    _libraryWired: false,

    _ensureLibraryState() {
        if (!this._libraryFilters) {
            this._libraryFilters = { q: '', status: '', format: '', sort: 'date_desc' };
        }
        if (!this._libraryExpanded) {
            this._libraryExpanded = new Set();
        }
    },

    setLibraryFilter(patch = {}) {
        this._ensureLibraryState();
        Object.assign(this._libraryFilters, patch);
        this.renderMatchLibraryTable();
    },

    _wireLibraryControls() {
        if (this._libraryWired) return;
        this._libraryWired = true;
        const search = document.getElementById('library-search');
        if (search) {
            search.addEventListener('input', () => this.setLibraryFilter({ q: search.value.trim() }));
        }
        const status = document.getElementById('library-status-filter');
        if (status) {
            status.addEventListener('change', () => this.setLibraryFilter({ status: status.value }));
        }
        const format = document.getElementById('library-format-filter');
        if (format) {
            format.addEventListener('change', () => this.setLibraryFilter({ format: format.value }));
        }
        const sort = document.getElementById('library-sort');
        if (sort) {
            sort.addEventListener('change', () => this.setLibraryFilter({ sort: sort.value }));
        }
    },

    _matchSlotsForFormat(match) {
        return match.format === 'two_halves' ? ['first_half', 'second_half'] : ['full'];
    },

    _matchAggregateStatus(match) {
        const slots = this._matchSlotsForFormat(match);
        const states = slots.map((s) => this.slotStatus(match, s));
        if (states.includes('error')) return 'error';
        if (states.includes('transcoding')) return 'transcoding';
        if (states.every((s) => s === 'ready')) return 'ready';
        if (states.every((s) => s === 'none')) return 'none';
        return 'partial';
    },

    _slotPillHtml(match, slot) {
        const status = this.slotStatus(match, slot);
        const cls = status === 'transcoding' ? 'transcoding'
                  : status === 'error' ? 'error'
                  : status === 'ready' ? 'ready'
                  : 'neutral';
        const shortLabel = slot === 'first_half' ? '1H' : slot === 'second_half' ? '2H' : 'Full';
        const stateText = status === 'none' ? 'no video' : status;
        return `<span class="slot-pill ${cls}" title="${shortLabel} · ${stateText}">${shortLabel} · ${this.esc(stateText)}</span>`;
    },

    _filteredLibraryMatches() {
        this._ensureLibraryState();
        const f = this._libraryFilters;
        const q = (f.q || '').toLowerCase();
        let rows = (this.matches || []).slice();
        if (q) {
            rows = rows.filter((m) => {
                const blob = `${m.home_team || ''} ${m.away_team || ''} ${m.location || ''} ${m.id || ''}`.toLowerCase();
                return blob.includes(q);
            });
        }
        if (f.format) rows = rows.filter((m) => (m.format || 'full') === f.format);
        if (f.status) rows = rows.filter((m) => this._matchAggregateStatus(m) === f.status);
        const cmpDate = (a, b) => (a.date || '').localeCompare(b.date || '');
        const cmpUpdated = (a, b) => (b.updated_at || '').localeCompare(a.updated_at || '');
        if (f.sort === 'date_asc') rows.sort(cmpDate);
        else if (f.sort === 'updated_desc') rows.sort(cmpUpdated);
        else rows.sort((a, b) => cmpDate(b, a)); // date_desc
        return rows;
    },

    renderMatchLibraryTable() {
        const wrap = document.getElementById('library-table-wrap');
        const summary = document.getElementById('library-summary-line');
        if (!wrap) return;
        this._ensureLibraryState();
        this._wireLibraryControls();

        const matches = this.matches || [];
        if (summary) {
            const encoding = matches.filter((m) => this._matchAggregateStatus(m) === 'transcoding').length;
            const failed = matches.filter((m) => this._matchAggregateStatus(m) === 'error').length;
            summary.textContent = `${matches.length} match${matches.length === 1 ? '' : 'es'} · ${encoding} encoding · ${failed} failed`;
        }

        const filtered = this._filteredLibraryMatches();
        if (!filtered.length) {
            wrap.innerHTML = '<div class="session-empty">No matches yet. Use Add Match to record one.</div>';
            return;
        }

        const headerRow = `
            <thead>
                <tr>
                    <th class="lib-col-expand" aria-label="Expand"></th>
                    <th class="lib-col-date">Date</th>
                    <th class="lib-col-matchup">Matchup</th>
                    <th class="lib-col-format">Format</th>
                    <th class="lib-col-slots">Slots</th>
                    <th class="lib-col-score">Score</th>
                    <th class="lib-col-updated">Updated</th>
                    <th class="lib-col-menu" aria-label="Actions"></th>
                </tr>
            </thead>
        `;

        const bodyRows = filtered.map((m) => this._renderMatchRow(m)).join('');
        wrap.innerHTML = `<table class="match-library-table">${headerRow}<tbody>${bodyRows}</tbody></table>`;
    },

    _renderMatchRow(match) {
        const expanded = this._libraryExpanded.has(match.id);
        const slots = this._matchSlotsForFormat(match);
        const slotPills = slots.map((s) => this._slotPillHtml(match, s)).join(' ');
        const formatLabel = match.format === 'two_halves' ? 'Halves' : 'Full';
        const aggregate = this._matchAggregateStatus(match);
        const aggregateClass = aggregate === 'error' ? 'is-error'
                             : aggregate === 'transcoding' ? 'is-encoding'
                             : aggregate === 'ready' ? 'is-ready'
                             : '';
        const score = (match.score_home != null && match.score_away != null)
            ? `${this.esc(match.score_home)}–${this.esc(match.score_away)}`
            : '<span class="muted">—</span>';
        const updatedLabel = match.updated_at ? this.esc(match.updated_at.replace('T', ' ').slice(0, 16)) : '<span class="muted">—</span>';
        const safeId = this.esc(match.id);
        const thumbHtml = match.has_thumbnail
            ? `<img class="library-thumb" src="/api/matches/${safeId}/thumbnail" alt="" loading="lazy">`
            : `<div class="library-thumb library-thumb-placeholder" aria-hidden="true"></div>`;
        const matchup = `
            <div class="library-matchup">
                ${thumbHtml}
                <div class="library-matchup-text">
                    <div><strong>${this.esc(match.home_team || '')}</strong> <span class="muted">vs</span> <strong>${this.esc(match.away_team || '')}</strong></div>
                    ${match.location ? `<div class="row-sub">${this.esc(match.location)}</div>` : ''}
                </div>
            </div>
        `;

        const headRow = `
            <tr class="library-row ${aggregateClass} ${expanded ? 'is-expanded' : ''}" data-match-row="${safeId}">
                <td class="lib-col-expand">
                    <button type="button" class="row-expand-btn" aria-expanded="${expanded}" aria-controls="library-detail-${safeId}" title="Toggle diagnostics" onclick="app.toggleMatchRow('${safeId}')">${expanded ? '▾' : '▸'}</button>
                </td>
                <td class="lib-col-date">${this.esc(match.date || '')}${match.time ? `<div class="row-sub">${this.esc(match.time)}</div>` : ''}</td>
                <td class="lib-col-matchup">${matchup}</td>
                <td class="lib-col-format"><span class="format-pill">${formatLabel}</span></td>
                <td class="lib-col-slots"><div class="slot-pill-stack">${slotPills}</div></td>
                <td class="lib-col-score">${score}</td>
                <td class="lib-col-updated">${updatedLabel}</td>
                <td class="lib-col-menu">
                    <div class="row-menu">
                        <button type="button" class="row-menu-btn" title="Actions" onclick="app.toggleRowMenu('${safeId}', event)">⋯</button>
                        <div class="row-menu-list" id="row-menu-${safeId}" hidden>
                            <button type="button" onclick="app.openEditMatchModal('${safeId}')">Edit details</button>
                            <button type="button" onclick="app.openMatchInPlayer('${safeId}')">Open in player</button>
                            <button type="button" class="is-danger" onclick="app.deleteMatch('${safeId}')">Delete match</button>
                        </div>
                    </div>
                </td>
            </tr>
        `;

        const detailRow = `
            <tr class="library-detail-row" id="library-detail-${safeId}" ${expanded ? '' : 'hidden'}>
                <td colspan="8">
                    ${this._renderSlotDiagnosticsPanel(match)}
                </td>
            </tr>
        `;

        return headRow + detailRow;
    },

    _renderSlotDiagnosticsPanel(match) {
        const slots = this._matchSlotsForFormat(match);
        const isAdmin = !!this.isAdmin?.();
        const safeId = this.esc(match.id);
        const slotCards = slots.map((slot) => {
            const status = this.slotStatus(match, slot);
            const filename = match.videos?.[slot] || null;
            const pillCls = status === 'transcoding' ? 'transcoding'
                          : status === 'error' ? 'error'
                          : status === 'ready' ? 'ready'
                          : 'neutral';
            const safeSlot = this.esc(slot);
            const buttons = [];
            // Verify is read-only — available to uploaders too.
            buttons.push(`<button type="button" class="mini-action-btn" onclick="app.verifyAssets('${safeId}')">Verify</button>`);
            if (isAdmin) {
                if (status === 'ready') {
                    buttons.push(`<button type="button" class="mini-action-btn" onclick="app.regenerateHls('${safeId}', '${safeSlot}')" title="Rebuild HLS variants only — fast, no re-encode">Regen HLS</button>`);
                    buttons.push(`<button type="button" class="mini-action-btn" onclick="app.forceRetranscode('${safeId}', '${safeSlot}')" title="Full re-encode from existing MP4 — multi-minute">Re-transcode</button>`);
                } else if (status === 'error') {
                    buttons.push(`<button type="button" class="mini-action-btn" onclick="app.retryTranscode('${safeId}', '${safeSlot}')">Retry</button>`);
                    buttons.push(`<button type="button" class="mini-action-btn" onclick="app.forceRetranscode('${safeId}', '${safeSlot}')">Force Re-transcode</button>`);
                } else if (status === 'transcoding') {
                    buttons.push(`<span class="muted">Encoder is working on this slot…</span>`);
                }
            }
            buttons.push(`<button type="button" class="mini-action-btn" onclick="app.viewMatchErrors('${safeId}', '${safeSlot}')">Logs</button>`);
            return `
                <div class="slot-card">
                    <div class="slot-card-head">
                        <span class="status-pill ${pillCls}">${this.slotLabel(slot)}</span>
                        <span class="muted">${this.esc(status === 'none' ? 'no video uploaded' : status)}</span>
                    </div>
                    <div class="slot-card-meta">
                        ${filename ? `<span>file: ${this.esc(filename)}</span>` : '<span class="muted">no file on disk</span>'}
                    </div>
                    <div class="slot-card-actions">
                        ${buttons.join('')}
                    </div>
                </div>
            `;
        }).join('');

        const thumbBlock = isAdmin
            ? `<div class="slot-card slot-card-thumb">
                    <div class="slot-card-head">
                        <span class="status-pill ${match.has_thumbnail ? 'ready' : 'neutral'}">Thumbnail</span>
                        <span class="muted">${match.has_thumbnail ? 'present' : 'missing'}</span>
                    </div>
                    <div class="slot-card-actions">
                        <button type="button" class="mini-action-btn" onclick="app.regenerateMatchThumbnail('${safeId}')">Regenerate Thumbnail</button>
                    </div>
                </div>`
            : '';

        // Clickable when admin + viewers > 0 — opens a modal listing the VOD
        // sessions with Kill buttons. Static pill otherwise.
        const vodViewers = this.vodViewersForMatch?.(match.id) ?? 0;
        const viewersPill = vodViewers
            ? (isAdmin
                ? `<button type="button" class="slot-diagnostics-viewers is-clickable" onclick="app.openMatchViewersModal('${safeId}')">${vodViewers} viewer${vodViewers === 1 ? '' : 's'} watching now</button>`
                : `<span class="slot-diagnostics-viewers">${vodViewers} viewer${vodViewers === 1 ? '' : 's'} watching now</span>`)
            : '';

        return `
            <div class="slot-diagnostics-panel">
                <div class="slot-diagnostics-head">
                    <span class="muted">Match ID</span>
                    <code>${safeId}</code>
                    ${viewersPill}
                </div>
                <div class="slot-cards-grid">
                    ${slotCards}
                    ${thumbBlock}
                </div>
            </div>
        `;
    },

    toggleMatchRow(matchId) {
        this._ensureLibraryState();
        if (this._libraryExpanded.has(matchId)) this._libraryExpanded.delete(matchId);
        else this._libraryExpanded.add(matchId);
        this.renderMatchLibraryTable();
    },

    toggleRowMenu(matchId, event) {
        if (event) event.stopPropagation();
        document.querySelectorAll('.row-menu-list').forEach((el) => {
            if (el.id === `row-menu-${matchId}`) {
                el.hidden = !el.hidden;
            } else {
                el.hidden = true;
            }
        });
        // One-shot click-away listener.
        if (!this._rowMenuClickAway) {
            this._rowMenuClickAway = (e) => {
                if (!e.target.closest?.('.row-menu')) {
                    document.querySelectorAll('.row-menu-list').forEach((el) => { el.hidden = true; });
                }
            };
            document.addEventListener('click', this._rowMenuClickAway);
        }
    },

    openMatchInPlayer(matchId) {
        const match = (this.matches || []).find((m) => m.id === matchId);
        if (!match) return;
        const slug = match.slug || match.id;
        try { window.open(`/match/${encodeURIComponent(slug)}`, '_blank', 'noopener'); }
        catch { window.location.href = `/match/${encodeURIComponent(slug)}`; }
    },

    async viewMatchErrors(matchId, slot = null) {
        try {
            const resp = await fetch(`/api/admin/matches/${matchId}/errors`, {
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) throw new Error('Failed to load error log');
            const data = await resp.json();
            const errors = (data.errors || []).filter((e) => !slot || e.slot === slot);
            if (!errors.length) {
                await this.notifyModal({
                    title: 'No errors recorded',
                    message: slot
                        ? `No errors logged for ${this.slotLabel(slot)}.`
                        : 'No errors logged for this match.',
                });
                return;
            }
            const lines = errors.slice(0, 10).map((e) => {
                const when = (e.created_at || '').replace('T', ' ').slice(0, 19);
                const detail = e.details ? ` — ${String(e.details).slice(0, 120)}` : '';
                return `[${when}] ${e.slot} · ${e.error_code}: ${e.reason}${detail}`;
            });
            await this.notifyModal({
                title: `Recent errors${slot ? ` · ${this.slotLabel(slot)}` : ''}`,
                message: lines.join('\n'),
            });
        } catch (error) {
            this.showError(error.message);
        }
    },

    async regenerateMatchThumbnail(matchId) {
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
        const url = `/api/admin/matches/${matchId}/regenerate-thumbnail${slot ? `?slot=${slot}` : ''}`;
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
            await this.loadMatches?.();
            this.renderMatchLibraryTable();
        } catch (error) {
            this.showError(error.message);
        }
    },

    // Fetch /api/admin/streams and store on the app instance. Rendering is
    // delegated to renderActiveStreams() (Live Console viewers list — live
    // sessions only) and the on-air pill in the Live Console header. VOD
    // viewer counts surface per-row in the matches library (vodViewersForMatch).
    async refreshActiveStreams() {
        if (!this.authToken) return;
        try {
            const resp = await fetch('/api/admin/streams', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load active streams');
            const data = await resp.json();
            this.activeStreams = data.active || [];
            this.streamBlocks = data.blocks || [];
            this.renderActiveStreams();
            this.renderLiveConsoleHeader?.();
            this.renderLiveBlocks?.();
        } catch (error) {
            const list = document.getElementById('live-viewers-list');
            if (list) list.innerHTML = `<div class="session-empty">${this.esc(error.message)}</div>`;
        }
    },

    // Live Console viewers list — live-kind only. VOD viewers are shown per
    // match in the library expanded row, not here.
    renderActiveStreams() {
        const list = document.getElementById('live-viewers-list');
        const countEl = document.getElementById('live-viewers-count');
        if (!list) return;
        const liveOnly = (this.activeStreams || []).filter((s) => s.kind === 'live');
        if (countEl) countEl.textContent = String(liveOnly.length);
        if (!liveOnly.length) {
            list.innerHTML = '<div class="session-empty">No live viewers right now.</div>';
            return;
        }
        list.innerHTML = liveOnly.map((s) => {
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
                            <strong>${this.esc(s.ip)}</strong>
                            <span class="status-pill">live</span>
                        </div>
                        <div class="session-meta">${this.esc(geoText)} • ${dur} • ${this.formatBytes(s.bytes_sent || 0)}</div>
                        <div class="session-meta" title="${this.esc(s.user_agent || '')}">${this.esc(ua)}${s.user_agent && s.user_agent.length > 60 ? '…' : ''}</div>
                    </div>
                    <div class="session-actions">
                        <button type="button" class="mini-action-btn" onclick="app.killStream('${this.esc(s.id)}')">Kill</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    // ON-AIR pill in the Live Console header. Reflects MediaMTX publisher
    // state (derived from any kind === 'live' session being active) plus the
    // user-set live_enabled flag.
    renderLiveConsoleHeader() {
        const pill = document.getElementById('live-onair-pill');
        const label = document.getElementById('live-onair-label');
        const viewers = document.getElementById('live-console-viewers');
        if (!pill || !label) return;
        const settings = this.getAppSettings();
        const enabled = settings.live_enabled === '1';
        const liveCount = (this.activeStreams || []).filter((s) => s.kind === 'live').length;
        const isOnAir = enabled && liveCount > 0;
        pill.dataset.state = !enabled ? 'off' : isOnAir ? 'on' : 'standby';
        label.textContent = !enabled ? 'OFF AIR' : isOnAir ? 'ON AIR' : 'STANDBY';
        if (viewers) viewers.textContent = `${liveCount} viewer${liveCount === 1 ? '' : 's'}`;
    },

    renderLiveBlocks() {
        const section = document.getElementById('live-blocks-section');
        const list = document.getElementById('live-blocks-list');
        if (!section || !list) return;
        const blocks = this.streamBlocks || [];
        if (!blocks.length) {
            section.style.display = 'none';
            return;
        }
        section.style.display = '';
        list.innerHTML = blocks.map((b, idx) => `
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
        list.querySelectorAll('.stream-unblock-btn').forEach((btn) => {
            const idx = parseInt(btn.dataset.idx, 10);
            btn.addEventListener('click', () => this.unblockStream(blocks[idx]));
        });
    },

    // ===== LIVE CONSOLE — read-rail polling =====
    //
    // Polls /api/admin/streams (viewers + blocks) every 5 s while the Live
    // section is active, plus a parallel /api/admin/performance fetch to
    // drive the throughput card and encoder-load tile. Stops on section
    // exit (admin.js calls stopLiveConsolePolling).
    _liveConsoleTimer: null,
    _liveThroughputSamples: [],

    startLiveConsolePolling() {
        // Reset the rolling sparkline buffer on every entry so the chart
        // shows only the current session, not a mix of old samples from a
        // previous visit.
        this._liveThroughputSamples = [];
        this.refreshLiveConsole();
        if (this._liveConsoleTimer) return;
        this._liveConsoleTimer = setInterval(() => {
            const liveSection = document.querySelector('.admin-section[data-admin-section="live"]');
            if (!liveSection || !liveSection.classList.contains('is-active')) {
                this.stopLiveConsolePolling();
                return;
            }
            this.refreshLiveConsole();
        }, 5000);
    },

    stopLiveConsolePolling() {
        if (this._liveConsoleTimer) {
            clearInterval(this._liveConsoleTimer);
            this._liveConsoleTimer = null;
        }
    },

    async refreshLiveConsole() {
        if (!this.authToken || !this.isAdmin?.()) return;
        await this.refreshActiveStreams();
        try {
            const resp = await this.authFetch('/api/admin/performance', { headers: this.getAuthHeaders() });
            if (!resp.ok) return;
            const perf = await resp.json();
            this.renderLiveThroughputCard(perf);
            this.renderLiveEncoderTile(perf);
        } catch (err) {
            console.warn('live console performance fetch failed', err);
        }
    },

    renderLiveThroughputCard(perf) {
        const bpsEl = document.getElementById('live-throughput-bps');
        const avgEl = document.getElementById('live-throughput-avg');
        const sparkEl = document.getElementById('live-throughput-spark');
        if (!bpsEl) return;
        const t = perf?.throughput || {};
        const last = t.last || {};
        const liveBps = last.bps_live_out || 0;
        const avg = t.avg_live_bps_30s || 0;
        bpsEl.textContent = this._fmtMbps(liveBps);
        if (avgEl) avgEl.textContent = `Avg 30 s: ${this._fmtMbps(avg)} · ${last.active_live || 0} viewers`;
        // Maintain a rolling window of samples for the sparkline.
        this._liveThroughputSamples.push(liveBps);
        if (this._liveThroughputSamples.length > 60) this._liveThroughputSamples.shift();
        if (sparkEl && typeof this.sparklineSvg === 'function') {
            sparkEl.innerHTML = this.sparklineSvg(this._liveThroughputSamples, { width: 200, height: 36 });
        }
    },

    renderLiveEncoderTile(perf) {
        const grid = document.getElementById('live-encoder-grid');
        if (!grid) return;
        const host = perf?.host || {};
        const tx = perf?.transcode || {};
        const last = perf?.throughput?.last || {};
        const tiles = [
            { kicker: 'CPU', value: host.cpu_percent != null ? `${host.cpu_percent.toFixed(0)}%` : '—' },
            { kicker: 'iGPU', value: host.intel_gpu_busy_pct != null ? `${host.intel_gpu_busy_pct}%` : '—' },
            { kicker: 'Memory', value: host.memory ? `${host.memory.percent.toFixed(0)}%` : '—' },
            { kicker: 'NIC TX', value: host.net ? this._fmtMbps(host.net.bps_tx) : '—' },
            { kicker: 'VOD egress', value: this._fmtMbps(last.bps_vod_out || 0) },
            { kicker: 'Encoder slots', value: `${tx.in_flight || 0} / ${tx.concurrency_limit || 0}` },
        ];
        grid.innerHTML = tiles.map((t) => `
            <div class="live-encoder-cell">
                <span class="live-encoder-kicker">${this.esc(t.kicker)}</span>
                <span class="live-encoder-value">${this.esc(t.value)}</span>
            </div>
        `).join('');
    },

    _fmtMbps(bps) {
        if (!bps) return '0 Mbps';
        return `${(bps / 1_000_000).toFixed(2)} Mbps`;
    },

    // VOD viewer count for a single match — used by the matches library
    // expanded row. Reads from the cached this.activeStreams; the status
    // strip's 10 s `/api/admin/streams` poll also writes that cache (see
    // refreshAdminStatusStrip in admin.js), so the count stays current
    // while the user is on any admin section.
    vodViewersForMatch(matchId) {
        return (this.activeStreams || []).filter((s) => s.kind === 'vod' && s.match_id === matchId).length;
    },

    // Manage-viewers modal for a single match. Lists the active VOD sessions
    // and exposes Kill on each — restores the kill capability that the
    // standalone Streams page used to provide. Uses formModal as a generic
    // container; the "submit" action is just Done (no PUT).
    async openMatchViewersModal(matchId) {
        const match = (this.matches || []).find((m) => m.id === matchId);
        const matchLabel = match ? `${match.home_team || ''} vs ${match.away_team || ''}` : matchId;

        const body = document.createElement('div');
        body.className = 'match-viewers-modal-body';

        const renderList = () => {
            const viewers = (this.activeStreams || []).filter((s) => s.kind === 'vod' && s.match_id === matchId);
            if (!viewers.length) {
                body.innerHTML = '<div class="session-empty">No active viewers right now.</div>';
                return;
            }
            body.innerHTML = `<div class="session-list">${viewers.map((s) => {
                const geoBits = [];
                if (s.geo) {
                    if (s.geo.city) geoBits.push(s.geo.city);
                    if (s.geo.country) geoBits.push(s.geo.country);
                }
                const geoText = geoBits.length ? geoBits.join(', ') : '—';
                const dur = this.formatDuration ? this.formatDuration(s.duration_seconds) : `${Math.round(s.duration_seconds)}s`;
                return `
                    <div class="session-item">
                        <div class="session-main">
                            <div class="session-title-row">
                                <strong>${this.esc(s.ip)}</strong>
                                <span class="status-pill">${this.esc(s.slot ? this.slotLabel(s.slot) : 'vod')}</span>
                            </div>
                            <div class="session-meta">${this.esc(geoText)} · ${dur} · ${this.formatBytes(s.bytes_sent || 0)}</div>
                        </div>
                        <div class="session-actions">
                            <button type="button" class="mini-action-btn" data-kill-id="${this.esc(s.id)}">Kill</button>
                        </div>
                    </div>
                `;
            }).join('')}</div>`;
            body.querySelectorAll('button[data-kill-id]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    await this.killStream(btn.dataset.killId);
                    // killStream calls refreshActiveStreams on success, which
                    // updates this.activeStreams. Re-render the modal list.
                    renderList();
                });
            });
        };

        renderList();

        await this.formModal({
            title: `Viewers · ${matchLabel}`,
            kicker: 'Active VOD sessions',
            body,
            confirmLabel: 'Done',
            cancelLabel: 'Close',
            onSubmit: async (close) => close(true),
        });
        // Refresh the matches library row counts on close.
        this.renderMatchLibraryTable?.();
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

        // Per-match active jobs and failed slots used to render here as
        // standalone session-list panels. Both moved into the Match Library
        // table (per-row aggregate pill + expanded slot diagnostics), which
        // gives admins a row identity rather than a fleet-wide list of
        // anonymous slots. Counts still surface in the diagnostic tiles
        // above ("Failed Slots", "Matches" — ready/processing breakdown).

        // Recent errors — rendered inside a <details> accordion on Performance.
        // The accordion stays closed by default; the count pill in its summary
        // is the at-a-glance signal.
        const errorsList = document.getElementById('recent-errors-list');
        const errorsCount = document.getElementById('diag-errors-count');
        if (errorsList) {
            if (recent_errors && recent_errors.length) {
                errorsList.innerHTML = recent_errors.map((e) => `
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
                errorsList.innerHTML = '<div class="session-empty">No recent encoder errors.</div>';
            }
        }
        if (errorsCount) errorsCount.textContent = String((recent_errors || []).length);

        // Upload sessions — server side
        const uploadCountEl = document.getElementById('diag-uploads-count');
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
        if (uploadCountEl) uploadCountEl.textContent = String(upload_sessions.length);

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
            message: `Rebuild the HLS variant ladder for ${this.slotLabel(slot)}? Uses the existing MP4 — no re-encode.`,
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
            await this.loadMatches?.();
            this.renderMatchLibraryTable?.();
        } catch (error) {
            this.showError(error.message);
        }
    },

    async forceRetranscode(matchId, slot) {
        const ok = await this.confirmAction({
            title: 'Re-transcode slot',
            message: `Re-encode the ${this.slotLabel(slot)} slot from scratch? This is multi-minute per match. Use it to pick up new encoder settings (QSV, 1440p, audio bitrate).`,
            confirmLabel: 'Re-transcode',
            danger: true,
        });
        if (!ok) return;
        try {
            const resp = await fetch(
                `/api/admin/matches/${matchId}/slots/${slot}/retry?force=true`,
                { method: 'POST', headers: this.getAuthHeaders() },
            );
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Re-transcode failed to start');
            }
            this.showSuccess(`Re-transcode started for ${slot}.`);
            await this.refreshAdminDiagnostics();
            await this.loadMatches?.();
            this.renderMatchLibraryTable?.();
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
                const headers = { 'Content-Type': 'application/json', ...this.getAuthHeaders() };
                if (this._editMatchETag) headers['If-Match'] = `"${this._editMatchETag}"`;
                const resp = await this.authFetch(`/api/matches/${editId}`, {
                    method: 'PUT',
                    headers,
                    body: JSON.stringify(matchData),
                });
                if (resp.status === 409) {
                    throw new Error('Match was modified by another user. Reload the page and try again.');
                }
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Failed to update match');
                }
                match = await resp.json();
            } else {
                const resp = await this.authFetch('/api/matches', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                    body: JSON.stringify(matchData),
                });
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
            // Reset the form first so cancelEdit's lookups still find the
            // hidden #edit-match-id field; then tear it down. The form
            // template gets re-cloned each time the modal opens, so leaving
            // detached DOM behind is fine.
            const liveForm = document.getElementById('add-match-form');
            if (liveForm) liveForm.reset();
            this.resetFileLabels();
            this.cancelEdit();
            // Re-render the library table so the new/updated match appears
            // immediately. We stay on /admin/matches; the caller modal closes
            // itself when this resolves cleanly.
            this.renderMatchLibraryTable?.();

            this.checkTranscodePolling();
            return true;

        } catch (e) {
            if (document.getElementById('edit-match-id').value) {
                await this.loadMatches();
                this.renderSeasonView();
            }
            const resumeHint = createdNewMatch
                ? ' The match record was created. Re-submit this form to resume any incomplete upload for the same selected file.'
                : '';
            this.showError(e.message + resumeHint);
            return false;
        } finally {
            const btnLabel = document.getElementById('edit-match-id').value ? 'Update Match' : 'Create Match';
            restore(btnLabel);
        }
    },

    editMatch(matchId, { pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        // Legacy entry point — public season-view "Edit" buttons call this.
        // Route through the modal so the entry point is uniform.
        this.openEditMatchModal(matchId, { pushHistory, replaceHistory, scrollTop });
    },

    cancelEdit() {
        // Reset hidden form state. The modal close handler tears down the DOM
        // entirely, so guard each lookup — these elements may be detached.
        const hiddenId = document.getElementById('edit-match-id');
        if (hiddenId) hiddenId.value = '';
        this._editMatchETag = null;
        const form = document.getElementById('add-match-form');
        if (form) form.reset();
        const heading = document.getElementById('form-heading');
        if (heading) heading.textContent = 'Add New Match';
        const submit = document.getElementById('submit-btn');
        if (submit) submit.textContent = 'Create Match';
        const cancelBtn = document.getElementById('cancel-edit-btn');
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (form) this.resetFileLabels();
    },

    // ===== ADD / EDIT MATCH MODAL =====
    //
    // The form template lives inside <template id="match-form-template"> in
    // index.html so all of its input ids (f-home-team, f-video-full, …) are
    // unique in the DOM only while the modal is open. Existing helpers
    // (handleFormSubmit, toggleFormatFields, uploadFileIfSelected,
    // uploadVideoIfSelected, renderEditAssetStates) read those ids at call
    // time and therefore work without modification.

    _mountMatchForm() {
        const tpl = document.getElementById('match-form-template');
        if (!tpl) return null;
        const fragment = tpl.content.cloneNode(true);
        const form = fragment.querySelector('#add-match-form');
        const wrapper = document.createElement('div');
        wrapper.appendChild(form);
        return wrapper;
    },

    _wireMountedFormFileLabels() {
        // Mirror the boot-time wiring in script.js, scoped to the cloned form.
        const ids = ['f-home-logo', 'f-away-logo', 'f-video-full', 'f-video-first', 'f-video-second'];
        ids.forEach((id) => {
            const input = document.getElementById(id);
            const label = document.getElementById(id + '-label');
            if (!input || !label || input.dataset.wired) return;
            input.dataset.wired = '1';
            input.addEventListener('change', () => {
                const file = input.files[0];
                if (file) {
                    const n = file.name;
                    label.textContent = n.length > 24
                        ? n.slice(0, 14) + '…' + n.slice(-8)
                        : n;
                } else {
                    label.textContent = 'No file chosen';
                }
                this.updatePendingUploadState(id, file || null);
            });
        });
    },

    async openAddMatchModal() {
        await this._openMatchModal({ mode: 'add' });
    },

    async openEditMatchModal(matchId, { pushHistory = true, replaceHistory = false } = {}) {
        const match = (this.matches || []).find((m) => m.id === matchId);
        if (!match) {
            this.showError('Match not found.');
            return;
        }
        if (pushHistory) {
            this.pushHistoryState?.(
                { view: 'admin', section: 'matches', mode: 'edit', matchId },
                { replace: replaceHistory, url: '/admin/matches' },
            );
        }
        await this._openMatchModal({ mode: 'edit', match });
    },

    async _openMatchModal({ mode, match = null }) {
        const body = this._mountMatchForm();
        if (!body) {
            this.showError('Match form template missing.');
            return;
        }

        const isEdit = mode === 'edit' && match;
        const title = isEdit ? `Edit · ${match.home_team || ''} vs ${match.away_team || ''}` : 'Add Match';
        const confirmLabel = isEdit ? 'Update Match' : 'Create Match';
        const kicker = isEdit ? 'Edit match' : 'New match';

        await this.formModal({
            title,
            kicker,
            body,
            confirmLabel,
            cancelLabel: 'Cancel',
            size: 'wide',
            // onMount runs synchronously after the modal DOM is appended but
            // before the user can interact. This is where we wire change
            // listeners and seed edit-mode field values — doing it after the
            // formModal `await` would be too late, since that Promise resolves
            // only when the modal is already closed.
            onMount: () => {
                this._wireMountedFormFileLabels();
                if (isEdit) {
                    const m = match;
                    const setVal = (id, v) => {
                        const el = document.getElementById(id);
                        if (el) el.value = v;
                    };
                    setVal('edit-match-id', m.id);
                    this._editMatchETag = m.updated_at || null;
                    setVal('f-home-team', m.home_team || '');
                    setVal('f-away-team', m.away_team || '');
                    setVal('f-date', m.date || '');
                    setVal('f-time', m.time || '');
                    setVal('f-location', m.location || '');
                    setVal('f-score-home', m.score_home != null ? m.score_home : '');
                    setVal('f-score-away', m.score_away != null ? m.score_away : '');
                    const formatRadio = document.querySelector(`input[name="format"][value="${m.format || 'full'}"]`);
                    if (formatRadio) formatRadio.checked = true;
                    this.toggleFormatFields();
                    this.resetFileLabels();
                    this.renderEditAssetStates(m);
                    const heading = document.getElementById('form-heading');
                    if (heading) heading.textContent = 'Edit Match';
                    const submit = document.getElementById('submit-btn');
                    if (submit) submit.textContent = 'Update Match';
                } else {
                    this.toggleFormatFields();
                    this.resetFileLabels();
                }
            },
            onSubmit: async (close) => {
                const before = this.matches?.length || 0;
                // handleFormSubmit returns true on success, false on caught
                // error (it surfaces its own error toasts). Anything that
                // would have gone unhandled comes through as a thrown
                // exception — treat that as a failure too and keep the
                // modal open so the user can retry.
                let ok = false;
                try { ok = await this.handleFormSubmit(); }
                catch (err) {
                    console.error('match form submit threw', err);
                    this.showError(err?.message || 'Submit failed');
                    ok = false;
                }
                if (!ok) return;
                close(true);
                this.renderMatchLibraryTable();
                if (!isEdit && (this.matches?.length || 0) > before) {
                    this.showInfo('Match added — encoding will continue in the background.');
                }
            },
        });

        // Post-close cleanup. cancelEdit's lookups are null-safe so detached
        // DOM is fine; renderMatchLibraryTable refreshes the table for the
        // user-cancelled path (the success path already refreshes inline).
        this.cancelEdit();
        this.renderMatchLibraryTable();
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
            const resp = await this.authFetch(`/api/matches/${matchId}`, { method: 'DELETE', headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to delete');
            await this.loadMatches();
            this.renderSeasonView();
            this.showSuccess('Match deleted.');
        } catch (e) {
            this.showError(e.message);
        }
    },

    // ===== PERFORMANCE TUNING PANEL =====
    _perfTimer: null,
    _perfPayload: null,

    startPerformanceTuningPolling() {
        if (!this.isAdmin?.()) return;
        // Wire buttons once.
        const card = document.getElementById('performance-tuning-card');
        if (card && !card.dataset.wired) {
            card.dataset.wired = '1';
            document.getElementById('perf-refresh-btn')?.addEventListener('click', () => this.refreshPerformanceTuning());
            document.getElementById('perf-capture-btn')?.addEventListener('click', () => this.startPerformanceCapture());
            document.getElementById('perf-copy-btn')?.addEventListener('click', () => this.copyPerformanceSnapshot());
            document.getElementById('perf-download-btn')?.addEventListener('click', () => this.downloadPerformanceSnapshot());
        }
        this.refreshPerformanceTuning();
        if (this._perfTimer) return;
        this._perfTimer = setInterval(() => {
            const perfSection = document.querySelector('.admin-section[data-admin-section="performance"]');
            if (!perfSection || !perfSection.classList.contains('is-active')) {
                this.stopPerformanceTuningPolling();
                return;
            }
            this.refreshPerformanceTuning();
        }, 5000);
    },

    stopPerformanceTuningPolling() {
        if (this._perfTimer) { clearInterval(this._perfTimer); this._perfTimer = null; }
    },

    async refreshPerformanceTuning() {
        if (!this.authToken) return;
        try {
            const resp = await this.authFetch('/api/admin/performance', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load performance');
            this._perfPayload = await resp.json();
            this.renderPerformanceTuning();
        } catch (err) {
            const grid = document.getElementById('perf-grid');
            if (grid) grid.innerHTML = `<div class="session-empty">${this.esc(err.message)}</div>`;
        }
    },

    renderPerformanceTuning() {
        const p = this._perfPayload;
        const grid = document.getElementById('perf-grid');
        if (!grid || !p) return;

        const fmtMbps = (bps) => bps ? `${(bps / 1_000_000).toFixed(2)} Mbps` : '0 Mbps';
        const fmtBytes = (b) => {
            if (!b && b !== 0) return '—';
            const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
            let i = 0; let v = b;
            while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
            return `${v.toFixed(1)} ${u[i]}`;
        };

        const t = p.throughput || {};
        const last = t.last || {};
        const host = p.host || {};
        const tx = p.transcode || {};
        const cap = (t.capture && t.capture.fast)
            ? `<span class="status-pill warn">capture ${t.capture.remaining_seconds}s left</span>` : '';
        const ssd = p.disk?.ssd;

        const tiles = [
            { label: 'Live throughput', value: fmtMbps(last.bps_live_out || 0), note: `30s avg ${fmtMbps(t.avg_live_bps_30s)} · ${last.active_live || 0} viewers` },
            { label: 'VOD throughput', value: fmtMbps(last.bps_vod_out || 0), note: `30s avg ${fmtMbps(t.avg_vod_bps_30s)} · ${last.active_vod || 0} sessions` },
            { label: 'NIC TX / RX', value: host.net ? `${fmtMbps(host.net.bps_tx)} / ${fmtMbps(host.net.bps_rx)}` : '—', note: 'Host NIC totals' },
            { label: 'CPU', value: host.cpu_percent != null ? `${host.cpu_percent.toFixed(0)}%` : '—', note: host.loadavg ? `load ${host.loadavg.map(l => l.toFixed(2)).join(' / ')}` : `${host.cpu_count || '?'} cores` },
            { label: 'Memory', value: host.memory ? `${host.memory.percent.toFixed(0)}%` : '—', note: host.memory ? `${fmtBytes(host.memory.used)} / ${fmtBytes(host.memory.total)}` : '' },
            { label: 'iGPU busy', value: host.intel_gpu_busy_pct != null ? `${host.intel_gpu_busy_pct}%` : '—', note: 'Intel i915 sysfs' },
            { label: 'SSD free', value: ssd ? fmtBytes(ssd.free) : '—', note: ssd ? `of ${fmtBytes(ssd.total)}` : '' },
            { label: 'Encoder pipeline', value: `${tx.concurrency_limit || 0} max`, note: `GPU ${tx.gpu?.succeeded || 0}✓ / ${tx.gpu?.failed || 0}✗` },
        ];

        grid.innerHTML = tiles.map((tile) => `
            <div class="diagnostic-card">
                <span class="diagnostic-label">${this.esc(tile.label)}</span>
                <strong class="diagnostic-value">${this.esc(tile.value)}</strong>
                ${tile.note ? `<span class="diagnostic-note">${this.esc(tile.note)}</span>` : ''}
            </div>
        `).join('') + (cap ? `<div class="diagnostic-card">${cap}</div>` : '');

        const rtList = document.getElementById('perf-rt-list');
        const rtCountEl = document.getElementById('diag-transcodes-count');
        if (rtList) {
            const rows = (tx.recent || []);
            if (rtCountEl) rtCountEl.textContent = String(rows.length);
            rtList.innerHTML = rows.length
                ? rows.map((h) => `
                    <div class="session-item">
                        <div class="session-title-row">
                            <strong>${this.esc(h.match_id)} / ${this.esc(h.slot)}</strong>
                            <span class="status-pill ${h.rt_factor < 1 ? 'ready' : 'neutral'}">${h.rt_factor}× realtime</span>
                            <span class="status-pill neutral">${this.esc(h.hwaccel)}</span>
                        </div>
                        <div class="session-meta">
                            <span>${h.source_seconds ? Math.round(h.source_seconds) + 's source' : ''}</span>
                            <span>${h.wall_seconds.toFixed(1)}s wall</span>
                            <span>${h.variant_count || 0} variants</span>
                        </div>
                    </div>
                `).join('')
                : '<div class="session-empty">No transcodes recorded yet.</div>';
        }

        const sessList = document.getElementById('perf-sessions-list');
        const sessCountEl = document.getElementById('diag-sessions-count');
        if (sessList) {
            const sessions = p.active_sessions || [];
            if (sessCountEl) sessCountEl.textContent = String(sessions.length);
            sessList.innerHTML = sessions.length
                ? sessions.map((s) => `
                    <div class="session-item">
                        <div class="session-title-row">
                            <strong>${this.esc(s.kind)} ${this.esc(s.match_id || '')}/${this.esc(s.slot || '')}</strong>
                            <span class="status-pill neutral">${this.esc(s.geo?.country_code || '')} ${this.esc(s.ip)}</span>
                        </div>
                        <div class="session-meta">
                            <span>${fmtBytes(s.bytes_sent)}</span>
                            <span>${Math.round(s.duration_seconds || 0)}s</span>
                            <span>idle ${Math.round(s.idle_seconds || 0)}s</span>
                        </div>
                    </div>
                `).join('')
                : '<div class="session-empty">No active streaming sessions.</div>';
        }
    },

    async startPerformanceCapture() {
        try {
            const resp = await this.authFetch('/api/admin/performance/capture', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify({ seconds: 60 }),
            });
            if (!resp.ok) throw new Error('Failed to start capture');
            this.showInfo?.('Capture started — sampling at 1 Hz for 60 s.');
            this.refreshPerformanceTuning();
        } catch (err) {
            this.showError(err.message);
        }
    },

    _buildPerfBundle() {
        // Bundle the latest payload + a redaction note so a coding agent has
        // enough context to tune. IPs in active_sessions are passed through
        // as-is (admin already sees them on the page); strip if you don't
        // want to share them.
        if (!this._perfPayload) return null;
        return {
            generated_at: new Date().toISOString(),
            note: 'Replay performance snapshot. Tuning knobs and counters; client IPs are intentionally not redacted in this admin-only export.',
            payload: this._perfPayload,
        };
    },

    async copyPerformanceSnapshot() {
        const bundle = this._buildPerfBundle();
        if (!bundle) { this.showError('No performance data loaded yet.'); return; }
        try {
            await navigator.clipboard.writeText(JSON.stringify(bundle, null, 2));
            this.showSuccess('Snapshot copied to clipboard.');
        } catch (_) {
            this.showError('Could not access clipboard.');
        }
    },

    downloadPerformanceSnapshot() {
        const bundle = this._buildPerfBundle();
        if (!bundle) { this.showError('No performance data loaded yet.'); return; }
        const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const ts = new Date().toISOString().replace(/[:.]/g, '-');
        const a = document.createElement('a');
        a.href = url;
        a.download = `replay-perf-${ts}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    },
};
