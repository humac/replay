// Coach engagement dashboard domain mixin (Phase 5.2 extraction).

export const coachingEngagementMixin = {
    // ===== Engagement dashboard sub-tab (Phase 9) =====

    renderCoachEngagementFilters() {
        const bundle = this._coachBundle || { players: [], playlists: [] };
        const playerEl = document.getElementById('coach-engagement-player');
        if (playerEl) {
            const current = playerEl.value || '';
            playerEl.innerHTML = '<option value="">All players</option>' + bundle.players.map((p) => (
                `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`
            )).join('');
            playerEl.value = current;
        }
        const playlistEl = document.getElementById('coach-engagement-playlist');
        if (playlistEl) {
            const current = playlistEl.value || '';
            playlistEl.innerHTML = '<option value="">All playlists</option>' + bundle.playlists.map((p) => (
                `<option value="${Number(p.id)}">${this.esc(p.title)}</option>`
            )).join('');
            playlistEl.value = current;
        }
        const matchEl = document.getElementById('coach-engagement-match');
        if (matchEl) {
            const current = matchEl.value || '';
            matchEl.innerHTML = '<option value="">All matches</option>' + (this.matches || []).map((m) => (
                `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`
            )).join('');
            matchEl.value = current;
        }
    },

    coachEngagementFilters() {
        return {
            player_id: document.getElementById('coach-engagement-player')?.value || '',
            playlist_id: document.getElementById('coach-engagement-playlist')?.value || '',
            match_id: document.getElementById('coach-engagement-match')?.value || '',
            visibility: document.getElementById('coach-engagement-visibility')?.value || '',
            start_date: document.getElementById('coach-engagement-start')?.value || '',
            end_date: document.getElementById('coach-engagement-end')?.value || '',
        };
    },

    renderCoachEngagement() {
        this.renderCoachEngagementFilters();
        this.loadCoachEngagementDashboard();
    },

    async loadCoachEngagementDashboard() {
        const target = document.getElementById('coach-engagement-dashboard');
        if (!target) return;
        target.innerHTML = '<div class="session-empty">Loading engagement dashboard...</div>';
        try {
            const data = await this.getCoachEngagement(this.coachEngagementFilters());
            this.renderCoachEngagementDashboard(data);
        } catch (err) {
            target.innerHTML = `<div class="session-empty">${this.esc(err.message || 'Could not load engagement dashboard.')}</div>`;
        }
    },

    renderCoachEngagementDashboard(data) {
        const target = document.getElementById('coach-engagement-dashboard');
        if (!target) return;
        if (!data) {
            target.innerHTML = '<div class="session-empty">No engagement data available.</div>';
            return;
        }
        const summary = data.summary || {};
        const tiles = [
            ['Assigned items', summary.assigned_items ?? 0],
            ['Reviewed items', summary.reviewed_items ?? 0],
            ['Completion', `${summary.completion_percentage ?? 0}%`],
            ['Reflections', summary.reflection_count ?? 0],
            ['Latest review', summary.latest_reviewed_at ? this.formatDate(summary.latest_reviewed_at) : '—'],
        ];
        const playerRows = (data.by_player || []).map((row) => `
            <tr>
                <td>${this.esc(row.jersey_number ? `#${row.jersey_number} ${row.display_name}` : row.display_name)}</td>
                <td>${Number(row.assigned_count || 0)}</td>
                <td>${Number(row.reviewed_count || 0)}</td>
                <td>${Number(row.completion_percentage || 0)}%</td>
                <td>${row.latest_reviewed_at ? this.esc(this.formatDate(row.latest_reviewed_at)) : '—'}</td>
                <td>${Number(row.reflection_count || 0)}</td>
            </tr>
        `).join('') || '<tr><td colspan="6">No assigned feedback matches these filters.</td></tr>';
        const playlistRows = (data.by_playlist || []).map((row) => `
            <tr>
                <td>${this.esc(row.title || `Playlist ${row.playlist_id}`)}</td>
                <td>${Number(row.assigned_count || 0)}</td>
                <td>${Number(row.reviewed_count || 0)}</td>
                <td>${Number(row.completion_percentage || 0)}%</td>
                <td>${row.latest_reviewed_at ? this.esc(this.formatDate(row.latest_reviewed_at)) : '—'}</td>
            </tr>
        `).join('') || '<tr><td colspan="5">No playlists match these filters.</td></tr>';
        const matchRows = (data.by_match || []).map((row) => `
            <tr>
                <td>${this.esc(row.label || row.match_id || 'No match')}</td>
                <td>${this.esc(row.date || '—')}</td>
                <td>${Number(row.assigned_count || 0)}</td>
                <td>${Number(row.reviewed_count || 0)}</td>
                <td>${Number(row.completion_percentage || 0)}%</td>
            </tr>
        `).join('') || '<tr><td colspan="5">No matches have assigned feedback for these filters.</td></tr>';
        const unreviewed = (data.unreviewed_assigned_items || []).map((item) => `
            <li class="coach-engagement-list-item"><strong>${this.esc(item.title || `${item.kind} ${item.item_id}`)}</strong><span class="coach-engagement-meta-pill">${this.esc(item.kind)} · ${this.esc(item.date || 'no date')}</span></li>
        `).join('') || '<li class="coach-engagement-list-item coach-engagement-list-item--empty">No unreviewed assigned items for these filters.</li>';
        const reflections = (data.reflections_needing_response || []).map((r) => `
            <li class="coach-engagement-list-item"><strong>${this.esc(r.reviewed_at ? this.formatDate(r.reviewed_at) : 'Reflection')}</strong><span class="coach-engagement-preview">${this.esc(r.reflection || '')}</span></li>
        `).join('') || '<li class="coach-engagement-list-item coach-engagement-list-item--empty">No player reflections for these filters.</li>';
        const noRecent = (data.players_with_no_recent_feedback || []).map((p) => `
            <li class="coach-engagement-list-item"><strong>${this.esc(p.jersey_number ? `#${p.jersey_number} ${p.display_name}` : p.display_name)}</strong><span class="coach-engagement-meta-pill">No feedback in the current recent window.</span></li>
        `).join('') || '<li class="coach-engagement-list-item coach-engagement-list-item--empty">Every active filtered player has recent feedback.</li>';
        const mostWatched = (data.most_watched || []).map((item) => `
            <li class="coach-engagement-list-item"><strong>${this.esc(item.title || `${item.kind} ${item.item_id}`)}</strong><span class="coach-engagement-meta-pill">${Number(item.review_count || 0)} review${Number(item.review_count || 0) === 1 ? '' : 's'} · ${this.esc(item.kind)}</span></li>
        `).join('') || '<li class="coach-engagement-list-item coach-engagement-list-item--empty">No review activity yet.</li>';
        target.innerHTML = `
            <div class="coach-engagement-kpis">${tiles.map(([label, value]) => `
                <div class="coach-engagement-kpi"><span class="coach-engagement-kpi-label">${this.esc(label)}</span><strong class="coach-engagement-kpi-value">${this.esc(String(value))}</strong></div>
            `).join('')}</div>
            <p class="coach-engagement-note">${this.esc(data.limitations?.goal_reflections_scope || 'Phase 9 tracks feedback review reflections only.')}</p>
            <div class="coach-engagement-grid">
                <section class="coach-engagement-card coach-engagement-card--wide">
                    <h4>Review completion by player</h4>
                    <div class="coach-engagement-table-wrap"><table class="coach-engagement-table"><thead><tr><th>Player</th><th>Assigned</th><th>Reviewed</th><th>Complete</th><th>Latest</th><th>Reflections</th></tr></thead><tbody>${playerRows}</tbody></table></div>
                </section>
                <section class="coach-engagement-card">
                    <h4>Review completion by playlist</h4>
                    <div class="coach-engagement-table-wrap"><table class="coach-engagement-table"><thead><tr><th>Playlist</th><th>Assigned</th><th>Reviewed</th><th>Complete</th><th>Latest</th></tr></thead><tbody>${playlistRows}</tbody></table></div>
                </section>
                <section class="coach-engagement-card">
                    <h4>Review completion by match</h4>
                    <div class="coach-engagement-table-wrap"><table class="coach-engagement-table"><thead><tr><th>Match</th><th>Date</th><th>Assigned</th><th>Reviewed</th><th>Complete</th></tr></thead><tbody>${matchRows}</tbody></table></div>
                </section>
                <section class="coach-engagement-card"><h4>Unreviewed assigned items</h4><ul class="coach-engagement-list">${unreviewed}</ul></section>
                <section class="coach-engagement-card"><h4>Reflections needing response</h4><ul class="coach-engagement-list">${reflections}</ul></section>
                <section class="coach-engagement-card"><h4>Players with no recent feedback</h4><ul class="coach-engagement-list">${noRecent}</ul></section>
                <section class="coach-engagement-card"><h4>Most watched</h4><ul class="coach-engagement-list">${mostWatched}</ul><p class="coach-engagement-note">${this.esc(data.limitations?.most_watched_source || 'Clip watch tracking is not yet supported.')}</p></section>
            </div>
        `;
    },
};
