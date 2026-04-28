// Public view rendering: season, game, score reveal, team stats.

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
                        <span>Reveal score</span>
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
