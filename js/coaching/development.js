// Player development domain mixin — Phase 5a/5b.
//
// Two surfaces share the same render helpers:
//   - Coach > Roster > "View development profile" → modal, viewer=false
//   - My Feedback > Development tab               → inline, viewer=true
//
// Both go through `_renderPlayerDevelopmentProfile` so the visible
// structure stays consistent. Privacy lives entirely server-side:
// the coach surface renders whatever the coach endpoint returned;
// the viewer surface renders whatever the viewer endpoint returned
// (already scrubbed by `_strip_private_fields`). No client-side
// authorization decisions.

export const coachingDevelopmentMixin = {
    // Phase 5b: sticky linked-player selection inside the My Feedback
    // Development sub-tab. Reset by `setLoggedOut()` so it cannot leak
    // across users — the in-render guard in `renderFeedbackDevelopment`
    // is a second line of defense for stale state during a single
    // session (e.g. a coach unlinking a player via the Roster tab).
    _feedbackDevPlayerId: null,

    // ===== Phase 5b — Player development profiles =====
    //
    // Two surfaces share the same render helpers:
    //   - Coach > Roster > "View development profile" → modal, viewer=false
    //   - My Feedback > Development tab               → inline, viewer=true
    //
    // Both go through the same `_renderPlayerDevelopmentProfile` so the
    // visible structure stays consistent. Privacy lives entirely server-
    // side: the coach surface renders whatever the coach endpoint
    // returned (the coach payload includes `linked_accounts` — surfaced
    // by `_renderDevHeader`. Coach-only goal fields such as
    // `coach_private_note` are rendered only when `viewer=false`; note
    // private text is still intentionally NOT templated by `_renderDevNoteItem`).
    // The viewer surface renders whatever the viewer endpoint returned (already
    // scrubbed by `_strip_private_fields`). No client-side
    // authorization decisions.

    async openCoachPlayerDevelopmentModal(playerId) {
        if (!this.canCoach()) return;
        const players = this._coachBundle?.players || [];
        const player = players.find((p) => String(p.id) === String(playerId));
        const headerName = player ? this.playerLabel(player) : 'Player';
        const body = document.createElement('div');
        body.className = 'player-dev-modal-body';
        body.innerHTML = '<div class="session-empty">Loading development profile…</div>';
        await this.formModal({
            title: headerName,
            kicker: 'Development Profile',
            body,
            confirmLabel: 'Close',
            cancelLabel: '',
            size: 'wide',
            onSubmit: (close) => close(true),
            onMount: async () => {
                try {
                    const profile = await this.getCoachPlayerDevelopment(playerId);
                    if (!profile) {
                        body.innerHTML = '<div class="session-empty">Profile unavailable.</div>';
                        return;
                    }
                    body.innerHTML = this._renderPlayerDevelopmentProfile(profile, { viewer: false });
                    this.mountCoachNoteThumbnailsIn(body);
                    this.mountCoachClipThumbnailsIn(body);
                } catch (err) {
                    body.innerHTML = `<div class="session-empty">Could not load profile. ${this.esc(err.message || '')}</div>`;
                }
            },
        });
    },

    async renderFeedbackDevelopment() {
        const root = document.getElementById('feedback-development-content');
        if (!root) return;
        const players = this._feedbackData?.players || [];
        if (!players.length) {
            root.innerHTML = '<div class="session-empty">No roster player is linked to your account yet. Ask a coach to link you.</div>';
            return;
        }
        // Pick the active player — sticky across re-renders so the user
        // doesn't get yanked back to the first chip on every refresh.
        const known = new Set(players.map((p) => String(p.id)));
        if (!this._feedbackDevPlayerId || !known.has(String(this._feedbackDevPlayerId))) {
            this._feedbackDevPlayerId = String(players[0].id);
        }
        const activeId = this._feedbackDevPlayerId;
        // Player IDs are UUID strings; build a safe JS literal for the
        // onclick attribute the same way the Roster row does (see
        // `renderCoachRoster`). `this.esc()` HTML-encodes for innerHTML
        // and is the wrong tool for JS-literal construction.
        const chips = players.length > 1 ? `
            <div class="feedback-dev-player-strip" role="tablist" aria-label="Linked players">
                ${players.map((p) => {
                    const playerIdJs = JSON.stringify(String(p.id)).replace(/"/g, '&quot;');
                    const isActive = String(p.id) === activeId;
                    return `
                    <button type="button"
                            class="feedback-dev-player-chip${isActive ? ' is-active' : ''}"
                            role="tab"
                            aria-selected="${isActive ? 'true' : 'false'}"
                            onclick="app.setFeedbackDevPlayer(${playerIdJs})">
                        ${this.esc(this.playerLabel(p))}
                    </button>`;
                }).join('')}
            </div>` : '';
        root.innerHTML = `${chips}<div id="feedback-development-profile"><div class="session-empty">Loading development profile…</div></div>`;
        const target = document.getElementById('feedback-development-profile');
        try {
            const profile = await this.getMyPlayerDevelopment(activeId);
            if (!profile) {
                target.innerHTML = '<div class="session-empty">Profile not available.</div>';
                return;
            }
            // Phase 6e — cache the per-player profile so a viewer who
            // clicks a recent-note row in Development can open the
            // detail modal even when the underlying note wasn't in the
            // main /api/my-feedback notes[] payload (the dev endpoint
            // applies the same visibility ladder).
            this._feedbackDevCache = this._feedbackDevCache || {};
            this._feedbackDevCache[String(activeId)] = profile;
            target.innerHTML = this._renderPlayerDevelopmentProfile(profile, { viewer: true });
            this.mountCoachNoteThumbnailsIn(target);
            this.mountCoachClipThumbnailsIn(target);
        } catch (err) {
            target.innerHTML = `<div class="session-empty">Could not load profile. ${this.esc(err.message || '')}</div>`;
        }
    },

    setFeedbackDevPlayer(playerId) {
        // Defensive: only accept non-empty strings. The chip handlers
        // never pass undefined/null today, but a stray inline call
        // shouldn't be able to wedge the selector into a "no player"
        // limbo state.
        const id = playerId == null ? '' : String(playerId);
        if (!id) return;
        this._feedbackDevPlayerId = id;
        this.renderFeedbackDevelopment();
    },

    /** Single render path for Coach + viewer development profiles.
     *  `viewer=true` swaps coach-only labels ("Linked accounts",
     *  technical wording) for player-friendly copy. Both surfaces
     *  render the same fields when present so the structure is
     *  predictable. */
    _renderPlayerDevelopmentProfile(profile, { viewer = false } = {}) {
        const sections = [];
        sections.push(this._renderDevHeader(profile, { viewer }));
        sections.push(this._renderDevCounts(profile, { viewer }));
        sections.push(this._renderDevGoals(profile, { viewer }));
        if (!viewer) sections.push(this._renderDevThemes(profile));
        sections.push(this._renderDevFocusAreas(profile, { viewer }));
        sections.push(this._renderDevRecentPositives(profile, { viewer }));
        sections.push(this._renderDevRecentCorrections(profile, { viewer }));
        sections.push(this._renderDevRecentClips(profile, { viewer }));
        sections.push(this._renderDevRecentPlaylists(profile, { viewer }));
        // Empty-state collapse: if NOTHING in the profile has data, show
        // a single friendly message instead of seven "no items" blocks.
        const counts = profile.counts || {};
        const total = Number(counts.notes || 0) + Number(counts.clips || 0) + Number(counts.playlists || 0) + Number(counts.goals || 0);
        if (total === 0) {
            const msg = viewer
                ? 'No development feedback yet.'
                : 'No coaching activity for this player yet.';
            return `${sections[0]}<div class="player-dev-empty session-empty">${this.esc(msg)}</div>`;
        }
        return sections.join('');
    },

    _renderDevHeader(profile, { viewer }) {
        const p = profile.player || {};
        const jersey = p.jersey_number
            ? `<span class="player-dev-jersey">#${this.esc(p.jersey_number)}</span>`
            : '';
        const status = p.active
            ? '<span class="roster-status-pill is-active"><span class="roster-status-dot" aria-hidden="true"></span>Active</span>'
            : '<span class="roster-status-pill is-inactive"><span class="roster-status-dot" aria-hidden="true"></span>Inactive</span>';
        const notes = !viewer && p.notes_field
            ? `<p class="player-dev-notes">${this.esc(p.notes_field)}</p>`
            : '';
        const linkedAccounts = !viewer && Array.isArray(profile.linked_accounts) && profile.linked_accounts.length
            ? `<div class="player-dev-linked">
                  <span class="player-dev-linked-label">Linked accounts (${profile.linked_accounts.length}):</span>
                  ${profile.linked_accounts.map((l) => `
                      <span class="player-dev-linked-chip" title="${this.esc(l.relationship || '')}">
                          <span class="player-dev-linked-rel">${this.esc(l.relationship || 'link')}</span>
                          <span class="player-dev-linked-user">@${this.esc(l.username || '')}</span>
                      </span>`).join('')}
              </div>`
            : '';
        return `
            <header class="player-dev-header">
                <div class="player-dev-headline">
                    ${jersey}
                    <h3 class="player-dev-name">${this.esc(p.display_name || 'Player')}</h3>
                    ${status}
                </div>
                ${notes}
                ${linkedAccounts}
            </header>`;
    },

    _renderDevCounts(profile, { viewer }) {
        const c = profile.counts || {};
        const r = profile.review_status || {};
        const noteRev = r.notes || {};
        const plRev = r.playlists || {};
        const clipRev = r.clips || {};
        const tiles = [
            { label: viewer ? 'Notes shared' : 'Notes', value: c.notes ?? 0 },
            { label: viewer ? 'Clips shared' : 'Clips', value: c.clips ?? 0 },
            { label: viewer ? 'Playlists shared' : 'Playlists', value: c.playlists ?? 0 },
            { label: viewer ? 'Active goals' : 'Goals', value: c.goals ?? (profile.active_goals || []).length },
            {
                label: viewer ? 'Notes reviewed' : 'Notes reviewed',
                value: `${noteRev.reviewed_count ?? 0} / ${noteRev.assigned_count ?? 0}`,
            },
            {
                label: 'Playlists reviewed',
                value: `${plRev.reviewed_count ?? 0} / ${plRev.assigned_count ?? 0}`,
            },
            {
                label: 'Reflections',
                value: r.reflection_count ?? 0,
            },
        ];
        if (!viewer && clipRev.review_supported === false) {
            // Surface that clip-review is not yet supported so the coach
            // doesn't read "0 / N" as a coverage gap.
            tiles.push({
                label: 'Clips reviewed',
                value: '—',
                hint: 'Clip review not tracked yet',
            });
        }
        return `
            <section class="player-dev-section player-dev-counts">
                <h4 class="player-dev-section-title">Summary</h4>
                <div class="player-dev-tile-grid">
                    ${tiles.map((t) => `
                        <div class="player-dev-tile" ${t.hint ? `title="${this.esc(t.hint)}"` : ''}>
                            <span class="player-dev-tile-label">${this.esc(t.label)}</span>
                            <strong class="player-dev-tile-value">${this.esc(String(t.value))}</strong>
                        </div>
                    `).join('')}
                </div>
            </section>`;
    },

    _renderDevGoals(profile, { viewer }) {
        const goals = profile.active_goals || [];
        const pid = profile.player?.id;
        const playerIdJs = JSON.stringify(String(pid || '')).replace(/"/g, '&quot;');
        if (!goals.length) {
            return `
                <section class="player-dev-section player-dev-goals">
                    <div class="player-dev-section-headline">
                        <div>
                            <h4 class="player-dev-section-title">${this.esc(viewer ? 'Current goals' : 'Active goals')}</h4>
                            <p class="player-dev-section-sub">${this.esc(viewer ? 'Goals your coach wants you to try next.' : 'Create explicit action plans tied to notes, clips, or the player profile.')}</p>
                        </div>
                        ${!viewer && pid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachGoalModal({ playerId: ${playerIdJs} })">+ New goal</button>` : ''}
                    </div>
                    <div class="player-dev-empty">${this.esc(viewer ? 'No active goals yet.' : 'No active goals yet.')}</div>
                </section>`;
        }
        return `
            <section class="player-dev-section player-dev-goals">
                <div class="player-dev-section-headline">
                    <div>
                        <h4 class="player-dev-section-title">${this.esc(viewer ? 'Current goals' : 'Active goals')}</h4>
                        <p class="player-dev-section-sub">${this.esc(viewer ? 'Add a reflection when you have tried one.' : 'Status changes are tracked and viewer reflections appear here.')}</p>
                    </div>
                    ${!viewer && pid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openCoachGoalModal({ playerId: ${playerIdJs} })">+ New goal</button>` : ''}
                </div>
                <div class="player-goal-grid">
                    ${goals.map((g) => this._renderGoalCard(g, { viewer })).join('')}
                </div>
            </section>`;
    },

    _renderDevThemes(profile) {
        // Coach-only: a viewer doesn't need positives-vs-corrections
        // ratios or top-tag breakdowns.
        const t = profile.themes || {};
        const byType = t.by_note_type || {};
        const order = ['positive', 'correction', 'question', 'team_concept', 'individual_goal'];
        const labels = {
            positive: 'Positives',
            correction: 'Corrections',
            question: 'Questions',
            team_concept: 'Team concepts',
            individual_goal: 'Individual goals',
        };
        const typeChips = order
            .filter((k) => (byType[k] ?? 0) > 0)
            .map((k) => `
                <span class="player-dev-chip player-dev-chip--type" data-tone="${this.esc(k)}">
                    ${this.esc(labels[k])} <strong>${this.esc(String(byType[k]))}</strong>
                </span>`).join('');
        const ratioStr = (() => {
            const r = t.positive_to_correction_ratio;
            if (r === null || r === undefined) return '—';
            return r.toFixed ? r.toFixed(2) : String(r);
        })();
        const topCats = (t.top_categories || []).map((c) => `
            <span class="player-dev-chip">${this.esc(c.value || '—')} <strong>${this.esc(String(c.count))}</strong></span>
        `).join('');
        const topTags = (t.top_tags || []).map((c) => `
            <span class="player-dev-chip player-dev-chip--tag">#${this.esc(c.value || '')} <strong>${this.esc(String(c.count))}</strong></span>
        `).join('');
        const empty = !typeChips && !topCats && !topTags;
        if (empty) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Themes</h4>
                    <div class="player-dev-empty">No themes yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Themes</h4>
                ${typeChips ? `<div class="player-dev-chip-row">${typeChips}</div>` : ''}
                <div class="player-dev-meta-row">
                    <span class="player-dev-meta-item">
                        <span class="player-dev-meta-label">Positive : Correction ratio</span>
                        <strong>${this.esc(ratioStr)}</strong>
                    </span>
                </div>
                ${topCats ? `<div class="player-dev-subsection">
                    <span class="player-dev-subsection-title">Top categories</span>
                    <div class="player-dev-chip-row">${topCats}</div>
                </div>` : ''}
                ${topTags ? `<div class="player-dev-subsection">
                    <span class="player-dev-subsection-title">Top tags</span>
                    <div class="player-dev-chip-row">${topTags}</div>
                </div>` : ''}
            </section>`;
    },

    _renderDevFocusAreas(profile, { viewer }) {
        const focus = profile.current_focus_areas || [];
        const title = viewer ? 'Focus areas from recent feedback' : 'Suggested focus areas from recent notes';
        const subtitle = viewer
            ? 'Things to keep working on, drawn from your most recent feedback.'
            : 'Derived from recent feedback. Phase 6 will add explicit goals and action plans.';
        if (!focus.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <p class="player-dev-section-sub">${this.esc(subtitle)}</p>
                    <div class="player-dev-empty">No focus areas yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <p class="player-dev-section-sub">${this.esc(subtitle)}</p>
                <ul class="player-dev-focus-list">
                    ${focus.map((f) => `
                        <li class="player-dev-focus-item">
                            <span class="player-dev-focus-cat">${this.esc(f.category || f.note_type || '')}</span>
                            <span class="player-dev-focus-body">${this.esc(f.what_to_do_next || '')}</span>
                        </li>
                    `).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentPositives(profile, { viewer }) {
        const items = profile.recent_positives || [];
        const title = viewer ? 'Recent positives' : 'Recent positives';
        if (!items.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <div class="player-dev-empty">No positives yet.</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <ul class="player-dev-note-list">
                    ${items.map((n) => this._renderDevNoteItem(n, { viewer })).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentCorrections(profile, { viewer }) {
        const items = profile.recent_corrections || [];
        const title = viewer ? 'Recent things to work on' : 'Recent corrections';
        if (!items.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                    <div class="player-dev-empty">${this.esc(viewer ? 'Nothing to work on right now.' : 'No corrections yet.')}</div>
                </section>`;
        }
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">${this.esc(title)}</h4>
                <ul class="player-dev-note-list">
                    ${items.map((n) => this._renderDevNoteItem(n, { viewer, emphasizeNext: true })).join('')}
                </ul>
            </section>`;
    },

    /** Single row layout for a recent note across positives /
     *  corrections / general lists. Renders only what the server
     *  returned. `coach_private_note` is intentionally never templated
     *  (the viewer endpoint scrubs it server-side; the coach endpoint
     *  exposes it but we don't show coach-private text in this UI to
     *  keep the surface consistent — Phase 6 may add an explicit
     *  coach-only block). */
    /** Phase 6e — open the unified review modal for a recent dev row.
     *  The viewer surface routes through the SAME `openFeedbackPlayer`
     *  modal that the My Feedback Notes tab uses, so a viewer never
     *  sees a different reading layout depending on which tab they
     *  clicked from.
     *
     *  When the note isn't in the main `/api/my-feedback` notes[]
     *  payload (the dev endpoint applies the same visibility ladder
     *  but is scoped per-player), we fall back to the cached
     *  development payload for the active player. No client-side
     *  authorization is added. */
    openFeedbackNoteDetailFromDev(noteId) {
        let note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) {
            const dev = this._feedbackDevCache?.[this._feedbackDevPlayerId];
            const allDevNotes = [
                ...(dev?.recent_notes || []),
                ...(dev?.recent_positives || []),
                ...(dev?.recent_corrections || []),
            ];
            note = allDevNotes.find((n) => Number(n.id) === Number(noteId)) || null;
        }
        if (!note) {
            this.showError('Note not available.');
            return;
        }
        // Cache the dev-only note temporarily on _feedbackData so the
        // unified body composer's review-state lookup + linked-player
        // resolver still work. Defensive — `_feedbackData.notes` may be
        // empty for a viewer who only browsed Development.
        if (!this._feedbackData) this._feedbackData = { notes: [], clips: [], reviews: [], players: [] };
        if (!this._feedbackData.notes.some((n) => Number(n.id) === Number(note.id))) {
            this._feedbackData.notes = [...(this._feedbackData.notes || []), note];
        }
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    /** Phase 6e — open the unified review modal for a recent dev clip
     *  row, reusing the same focused-player modal as the Clips tab. */
    openFeedbackClipDetailFromDev(clipId) {
        let clip = (this._feedbackData?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) {
            const dev = this._feedbackDevCache?.[this._feedbackDevPlayerId];
            clip = (dev?.recent_clips || []).find((c) => Number(c.id) === Number(clipId)) || null;
        }
        if (!clip) {
            this.showError('Clip not available.');
            return;
        }
        if (!this._feedbackData) this._feedbackData = { notes: [], clips: [], reviews: [], players: [] };
        if (!this._feedbackData.clips.some((c) => Number(c.id) === Number(clip.id))) {
            this._feedbackData.clips = [...(this._feedbackData.clips || []), clip];
        }
        this.openFeedbackPlayer({ mode: 'clip', clip });
    },

    _renderDevNoteItem(note, { viewer, emphasizeNext = false } = {}) {
        const isObservation = (note.note_context || 'video') === 'observation';
        const summary = (note.player_summary || '').trim() || (note.body || '').trim();
        const title = (note.title || '').trim() || (isObservation ? (note.event_title || '').trim() : '');
        const next = (note.what_to_do_next || '').trim();
        // Phase 6b — observation notes have no match/slot/timestamp.
        // Build the meta line from event metadata when available so
        // a profile that mixes video + observation notes never shows
        // "null" or "0:00" for fields that don't apply.
        let meta = '';
        if (isObservation) {
            const parts = [];
            if (note.event_type) {
                const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
                parts.push(`${typeLabel} observation`);
            } else {
                parts.push('Observation');
            }
            if (note.event_title && note.event_title !== title) parts.push(note.event_title);
            if (note.event_date) parts.push(note.event_date);
            meta = parts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
        } else {
            const matchPart = note.match_id ? this.esc(this.matchLabel(note.match_id)) : '';
            const slotPart = note.slot ? this.esc(this.slotLabel(note.slot)) : '';
            const tsPart = Number.isFinite(Number(note.timestamp_seconds))
                ? this.esc(this.formatClock(note.timestamp_seconds)) : '';
            meta = [matchPart, slotPart, tsPart].filter(Boolean).join(' · ');
        }
        const tonePill = this._feedbackTonePillHtml(note.note_type);
        // Phase 6c — observation notes with a tactical board show a
        // compact SVG preview tile in place of the clipboard glyph
        // so the development profile surfaces the sketch at-a-glance
        // without breaking layout.
        const hasBoard = isObservation && this.tacticalBoardHasContent(note.tactical_board_json);
        const thumb = isObservation
            ? (hasBoard
                ? `<div class="coach-thumb coach-thumb--list coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(note.tactical_board_json, { size: 'chip' })}</div>`
                : '<div class="coach-thumb coach-thumb--list coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
            : this._coachNoteThumbHtml(note, { size: 'list' });
        const boardPill = hasBoard
            ? '<span class="coach-row-board-pill" title="Tactical board attached">⌬ Board</span>'
            : '';
        // Phase 6e — make viewer-side dev rows clickable so a parent
        // browsing the development profile can open the same detail
        // modal as the My Feedback Notes tab. Coach-side preview stays
        // unchanged (the coach surface uses the modal it already mounts
        // for the development view; click-to-detail isn't its job).
        const detailHandler = viewer && Number.isFinite(Number(note.id))
            ? `onclick="app.openFeedbackNoteDetailFromDev(${Number(note.id)})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackNoteDetailFromDev(${Number(note.id)});}"`
            : '';
        const interactiveAttrs = viewer && detailHandler
            ? `tabindex="0" role="button" aria-label="Open details for ${this.esc(title || 'note')}"`
            : '';
        const itemClass = `player-dev-note-item${viewer && detailHandler ? ' player-dev-note-item--clickable' : ''}`;
        return `
            <li class="${itemClass}" data-note-context="${isObservation ? 'observation' : 'video'}" ${interactiveAttrs} ${detailHandler}>
                ${thumb}
                <div class="player-dev-note-body">
                    <div class="player-dev-note-head">
                        ${tonePill}
                        ${boardPill}
                        ${title ? `<strong class="player-dev-note-title">${this.esc(title)}</strong>` : ''}
                    </div>
                    ${meta ? `<div class="player-dev-note-meta">${meta}</div>` : ''}
                    ${summary ? `<p class="player-dev-note-summary">${this.esc(summary)}</p>` : ''}
                    ${next ? `<p class="player-dev-note-next${emphasizeNext ? ' is-emphasized' : ''}">
                        <span class="player-dev-note-next-label">${this.esc(viewer ? 'Try this next:' : 'What to do next:')}</span>
                        ${this.esc(next)}
                    </p>` : ''}
                </div>
            </li>`;
    },

    _renderDevRecentClips(profile, { viewer }) {
        const clips = profile.recent_clips || [];
        if (!clips.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Recent clips</h4>
                    <div class="player-dev-empty">No clips yet.</div>
                </section>`;
        }
        // Phase 6e — viewers route through the dev-aware fallback so a
        // recent clip that's only in the per-player development payload
        // (and not in the main /api/my-feedback clips[]) still opens the
        // unified modal. `openFeedbackClip` would silently no-op on the
        // miss because it only looks in `_feedbackData.clips`. The note
        // path uses the same fallback via `openFeedbackNoteDetailFromDev`.
        const watchHandler = viewer ? 'app.openFeedbackClipDetailFromDev' : 'app.previewCoachClip';
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Recent clips</h4>
                <ul class="player-dev-clip-list">
                    ${clips.map((c) => {
                        // Validate the id once: if it's missing or not a
                        // finite number, drop the Watch/Preview button
                        // (the lookup helper would silently no-op anyway,
                        // but rendering a button that does nothing is
                        // worse than not rendering it). Server JSON
                        // always populates this today; the guard is
                        // defense-in-depth for malformed payloads.
                        const cid = Number(c?.id);
                        const idValid = Number.isFinite(cid) && cid > 0;
                        const meta = [
                            this.matchLabel(c.match_id),
                            this.slotLabel(c.slot),
                            `${this.formatClock(c.start_seconds)}–${this.formatClock(c.end_seconds)}`,
                            this._clipDurationLabel(c),
                            c.category || '',
                        ].filter(Boolean).map((s) => this.esc(s)).join(' · ');
                        return `
                            <li class="player-dev-clip-item">
                                ${this._coachClipThumbHtml(c)}
                                <div class="player-dev-clip-body">
                                    <strong class="player-dev-clip-title">${this.esc(c.title || 'Untitled clip')}</strong>
                                    <div class="player-dev-clip-meta">${meta}</div>
                                    ${c.description ? `<p class="player-dev-clip-desc">${this.esc(c.description)}</p>` : ''}
                                </div>
                                <div class="player-dev-clip-actions">
                                    ${idValid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="${watchHandler}(${cid})">${viewer ? '▶ Watch' : 'Preview'}</button>` : ''}
                                </div>
                            </li>`;
                    }).join('')}
                </ul>
            </section>`;
    },

    _renderDevRecentPlaylists(profile, { viewer }) {
        const playlists = profile.recent_playlists || [];
        if (!playlists.length) {
            return `
                <section class="player-dev-section">
                    <h4 class="player-dev-section-title">Recent playlists</h4>
                    <div class="player-dev-empty">No playlists yet.</div>
                </section>`;
        }
        // Phase 5b finding #11: the coach surface previously rendered
        // no Preview button for recent playlists, an undocumented
        // asymmetry vs. recent clips. Reuse the existing
        // `previewCoachPlaylist` helper from Coach > Playlists — it
        // looks the playlist up in `_coachBundle.playlists` (always
        // loaded on the coach surface) and opens the same focused
        // feedback player the viewer surface uses, so this introduces
        // no new playback behavior.
        const playHandler = viewer ? 'app.openFeedbackPlaylist' : 'app.previewCoachPlaylist';
        const playLabel   = viewer ? '▶ Play session' : '▶ Preview';
        return `
            <section class="player-dev-section">
                <h4 class="player-dev-section-title">Recent playlists</h4>
                <ul class="player-dev-playlist-list">
                    ${playlists.map((p) => {
                        const pid = Number(p?.id);
                        const idValid = Number.isFinite(pid) && pid > 0;
                        return `
                        <li class="player-dev-playlist-item">
                            <div class="player-dev-playlist-body">
                                <strong>${this.esc(p.title || 'Untitled playlist')}</strong>
                                <span class="player-dev-playlist-meta">${this.esc(String(p.item_count || 0))} item${(p.item_count || 0) === 1 ? '' : 's'} · ${this.esc(p.visibility || '')}</span>
                            </div>
                            ${idValid ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="${playHandler}(${pid})">${playLabel}</button>` : ''}
                        </li>`;
                    }).join('')}
                </ul>
            </section>`;
    },

};
