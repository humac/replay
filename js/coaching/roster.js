// Coaching roster domain mixin (PR-FE 1/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.

export const coachingRosterMixin = {
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

    _rosterImportSampleCsv() {
        return [
            'display_name,jersey_number,position,guardian_email,relationship,active',
            'Avery Lopez,4,Defender,parent@example.com,guardian,true',
            'Mika Chen,9,Forward,parent@example.com,guardian,true',
        ].join('\n');
    },

    _renderRosterImportResult(target, result) {
        if (!target || !result) return;
        const summary = result.summary || {};
        const rows = result.rows || [];
        const metric = (label, value) => `
            <div class="roster-import-metric">
                <span>${this.esc(label)}</span>
                <strong>${Number(value || 0)}</strong>
            </div>`;
        const rowHtml = rows.slice(0, 12).map((row) => {
            const player = row.player || row.input || {};
            const isError = row.status === 'error';
            const detail = isError
                ? (row.errors || []).join('; ')
                : [row.player_action, row.guardian_action].filter(Boolean).join(' · ');
            const warnings = (row.warnings || []).length
                ? `<span class="roster-import-row-warning">${this.esc(row.warnings.join('; '))}</span>`
                : '';
            return `
                <div class="roster-import-row ${isError ? 'is-error' : 'is-ready'}">
                    <span class="roster-import-row-num">${this.esc(row.row_number || '—')}</span>
                    <span class="roster-import-row-player">
                        <strong>${this.esc(player.display_name || '(missing name)')}</strong>
                        <small>${this.esc([player.jersey_number ? `#${player.jersey_number}` : '', row.guardian_email || player.guardian_email || ''].filter(Boolean).join(' · '))}</small>
                    </span>
                    <span class="roster-import-row-detail">${this.esc(detail || row.status || 'ready')}${warnings}</span>
                </div>`;
        }).join('');
        target.innerHTML = `
            <div class="roster-import-summary" data-mode="${this.esc(result.mode || 'preview')}">
                ${metric('Rows', summary.rows)}
                ${metric('Errors', summary.errors)}
                ${result.mode === 'commit'
                    ? `${metric('Players created', summary.created_players)}${metric('Existing players', summary.existing_players)}${metric('Guardian invites', summary.guardian_invites)}${metric('Existing guardians linked', summary.linked_existing_users)}`
                    : `${metric('Players to create', summary.create_players)}${metric('Players to update', summary.update_players)}${metric('Guardian invites', summary.guardian_invites)}${metric('Existing guardians', summary.linked_existing_users)}`}
            </div>
            ${rows.length ? `<div class="roster-import-rows" aria-label="Roster import ${this.esc(result.mode || 'preview')} rows">${rowHtml}${rows.length > 12 ? `<div class="roster-import-more">${this.esc(rows.length - 12)} more rows not shown</div>` : ''}</div>` : ''}
        `;
    },

    async openCoachRosterImportModal() {
        const body = document.createElement('div');
        body.className = 'roster-import-modal';
        body.innerHTML = `
            <div class="roster-import-help">
                <strong>CSV columns</strong>
                <span>display_name is required. Optional: player_id, jersey_number, position/notes, guardian_email, relationship, active.</span>
            </div>
            <label class="roster-import-field">
                <span>Paste CSV</span>
                <textarea id="coach-roster-import-csv" spellcheck="false" rows="9"></textarea>
            </label>
            <div class="roster-import-actions">
                <button type="button" class="btn-secondary" id="coach-roster-import-sample">Use sample</button>
                <button type="button" class="btn-head" id="coach-roster-import-preview">Preview import</button>
            </div>
            <div id="coach-roster-import-result" class="roster-import-result" aria-live="polite"></div>
        `;
        const csvEl = body.querySelector('#coach-roster-import-csv');
        const previewBtn = body.querySelector('#coach-roster-import-preview');
        const sampleBtn = body.querySelector('#coach-roster-import-sample');
        const resultEl = body.querySelector('#coach-roster-import-result');
        let lastPreview = null;
        const preview = async () => {
            const csv_text = csvEl.value.trim();
            if (!csv_text) { this.showError('Paste roster CSV first.'); return null; }
            const restore = this.btnLoading(previewBtn, 'Previewing…');
            try {
                const result = await this.previewCoachRosterImport({ csv_text });
                result.csv_text = csv_text;
                lastPreview = result;
                this._renderRosterImportResult(resultEl, result);
                if (result.summary?.errors) this.showError('Fix CSV errors before committing.');
                return result;
            } catch (err) {
                this.showError(err.message || 'Roster preview failed.');
                return null;
            } finally {
                restore('Preview import');
            }
        };
        sampleBtn.addEventListener('click', () => {
            csvEl.value = this._rosterImportSampleCsv();
            csvEl.focus();
        });
        previewBtn.addEventListener('click', preview);

        const committed = await this.formModal({
            title: 'Import roster CSV',
            kicker: 'Roster import',
            message: 'Preview is read-only. Commit creates or updates players, links guardians with existing accounts by email, and creates/reuses pending guardian invites for new emails.',
            body,
            confirmLabel: 'Commit import',
            size: 'wide',
            onMount: () => { csvEl.focus(); },
            onSubmit: async (close) => {
                const csv_text = csvEl.value.trim();
                if (!csv_text) { this.showError('Paste roster CSV first.'); return; }
                if (!lastPreview || lastPreview.summary?.errors || lastPreview.csv_text !== csv_text) {
                    const previewResult = await preview();
                    if (!previewResult || previewResult.summary?.errors) return;
                    previewResult.csv_text = csv_text;
                    lastPreview = previewResult;
                }
                try {
                    const result = await this.commitCoachRosterImport({ csv_text });
                    this._renderRosterImportResult(resultEl, result);
                    if (!result.ok || result.summary?.errors) {
                        this.showError('Roster import was not committed. Fix the reported rows and retry.');
                        return;
                    }
                    this.showSuccess(`Roster import committed: ${result.summary?.rows || 0} rows.`);
                    close(true);
                } catch (err) {
                    this.showError(err.message || 'Roster import failed.');
                }
            },
        });
        if (committed) await this.renderCoachWorkspace();
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
};
