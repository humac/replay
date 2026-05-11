// My Feedback domain mixin — viewer-side `/feedback` shell.
//
// Owns the four-tab Feedback shell (Playlists / Notes / Clips / Match
// Summaries / Development), the per-tab list renderers, viewer-facing
// composition helpers (tone pill, structured what/why/next, summary
// fallback), the linked-player chip strip, and the small wrappers that
// mark a note/playlist as reviewed.
//
// The focused feedback player modal (`openFeedbackPlayer`), playlist
// session controller, drawing-canvas painter, and the per-mode loaders
// (`_loadFeedbackVideoForNote` / `_loadFeedbackVideoForClip`) remain in
// js/coaching.js — they belong to the feedback-player and review
// domains and migrate in later PR-FE steps.

// PR 1c: My Feedback uses longer, more player-friendly labels for the
// tone (the Coach Review composer's chip labels above are clipped for
// the dense inspector). Same key set as `_VALID_NOTE_TYPES`.
const FEEDBACK_NOTE_TYPE_LABELS = {
    positive:        'Positive',
    correction:      'Correction',
    question:        'Question',
    team_concept:    'Team concept',
    individual_goal: 'Individual goal',
};

export const VALID_FEEDBACK_TABS = ['playlists', 'notes', 'clips', 'summaries', 'development'];

export const coachingFeedbackMixin = {
    setFeedbackTab(name, { pushHistory = true } = {}) {
        if (!VALID_FEEDBACK_TABS.includes(name)) name = 'playlists';
        this._feedbackTab = name;
        document.querySelectorAll('[data-feedback-tab]').forEach((btn) => {
            const active = btn.dataset.feedbackTab === name;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        VALID_FEEDBACK_TABS.forEach((tab) => {
            const panel = document.getElementById(`feedback-tab-${tab}`);
            if (panel) panel.hidden = tab !== name;
        });
        if (pushHistory) {
            const url = `/feedback?tab=${name}`;
            this.pushHistoryState({ view: 'feedback', tab: name }, { replace: true, url });
        }
        if (name === 'summaries') this.renderFeedbackMatchSummaries(this._feedbackData || {});
        if (name === 'development') this.renderFeedbackDevelopment();
    },

    /** Returns "1:23" style duration for a clip (clamped to ≥ 0). */
    _clipDurationLabel(clip) {
        const dur = Math.max(0, Number(clip?.end_seconds || 0) - Number(clip?.start_seconds || 0));
        const total = Math.round(dur);
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return `${mins}:${String(secs).padStart(2, '0')}`;
    },

    async renderMyFeedback() {
        const linkedStrip = document.getElementById('feedback-linked-strip');
        const playlistsList = document.getElementById('feedback-playlists-list');
        const notesList = document.getElementById('feedback-notes-list');
        const clipsList = document.getElementById('feedback-clips-list');
        const summariesList = document.getElementById('feedback-summaries-list');
        if (linkedStrip) linkedStrip.innerHTML = '';
        if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (notesList) notesList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (clipsList) clipsList.innerHTML = '<div class="session-empty">Loading…</div>';
        if (summariesList) summariesList.innerHTML = '<div class="session-empty">Loading…</div>';
        try {
            const data = await this.loadMyFeedback();
            this._feedbackData = data;
            this.renderFeedbackLinkedStrip(data);
            this.renderFeedbackPlaylists(data);
            this.renderFeedbackNotes(data);
            this.renderFeedbackClips(data);
            this.renderFeedbackMatchSummaries(data);
        } catch (err) {
            if (playlistsList) playlistsList.innerHTML = '<div class="session-empty">Could not load feedback.</div>';
            if (notesList) notesList.innerHTML = '';
            if (clipsList) clipsList.innerHTML = '';
            if (summariesList) summariesList.innerHTML = '';
            this.showError(err.message);
        }
    },

    renderFeedbackLinkedStrip(data) {
        const el = document.getElementById('feedback-linked-strip');
        if (!el) return;
        const players = data?.players || [];
        if (!players.length) {
            el.innerHTML = '<span class="feedback-linked-empty">No roster player is linked to your account yet. Ask a coach to link you.</span>';
            return;
        }
        el.innerHTML = `<span class="feedback-linked-label">Linked players:</span>` + players.map((p) => `<span class="feedback-linked-pill">${this.esc(this.playerLabel(p))}</span>`).join('');
    },

    /** PR 1c — viewer-facing "summary" for a coaching note. The player-
     *  facing text is `player_summary` when present (the short, age-
     *  appropriate version the coach wrote in the composer), with a
     *  fallback to `body` for legacy notes that pre-date Phase 1. The
     *  long-form `body` is also surfaced when both are non-empty so the
     *  coach can write a polished one-line summary without losing their
     *  longer note. */
    _feedbackNoteSummary(note) {
        const summary = (note?.player_summary || '').trim();
        const body = (note?.body || '').trim();
        if (summary && body && summary !== body) return { primary: summary, secondary: body };
        if (summary) return { primary: summary, secondary: '' };
        return { primary: body, secondary: '' };
    },

    /** PR 1c — tone pill HTML for My Feedback. Coach-facing chip labels
     *  are short ("Team", "Goal"); player-facing labels are written out
     *  for clarity ("Team concept", "Individual goal"). The `data-tone`
     *  attribute drives the pill's accent colour. Returns `''` when the
     *  note has no `note_type` (defensive — every note post-v9 has one
     *  but a legacy export might not). */
    _feedbackTonePillHtml(noteType) {
        const label = FEEDBACK_NOTE_TYPE_LABELS[noteType];
        if (!label) return '';
        return `<span class="feedback-tone-pill" data-tone="${this.esc(noteType)}">${this.esc(label)}</span>`;
    },

    /** PR 1c — structured what / why / next stack. Renders only the
     *  fields that are non-empty so a simple note (with only
     *  `player_summary`) still feels lightweight. `coach_private_note`
     *  is NEVER rendered here; the server scrubs it for viewers
     *  (`_strip_private_fields`) but we also do not template it client-
     *  side as defense-in-depth. */
    _feedbackStructuredHtml(note) {
        const items = [
            ['What happened',     note?.what_happened],
            ['Why it matters',    note?.why_it_matters],
            ['What to do next',   note?.what_to_do_next],
        ].filter(([, v]) => (v || '').trim());
        if (!items.length) return '';
        return `
            <dl class="feedback-structured">
                ${items.map(([label, value]) => `
                    <div class="feedback-structured-item">
                        <dt>${this.esc(label)}</dt>
                        <dd>${this.esc(value.trim())}</dd>
                    </div>
                `).join('')}
            </dl>`;
    },

    /** Render the Playlists tab as a responsive grid of self-contained
     *  cards. Each card shows the playlist's title, clip count,
     *  description, and a Play session / Mark reviewed action row.
     *  Click "Play session" → `openFeedbackPlaylist()` opens the
     *  focused modal (same player used by the rest of the app). */
    renderFeedbackPlaylists(data) {
        const container = document.getElementById('feedback-playlists-list');
        if (!container) return;
        const playlists = data?.playlists || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.playlist_id).map((r) => Number(r.playlist_id)));
        if (!playlists.length) {
            container.innerHTML = '<div class="session-empty">No review playlists have been shared with you yet.</div>';
            return;
        }
        // Phase 3b: feedback playlists embed their items under
        // `playlists[].items[]` (server `_playlists_with_items`), each
        // already scrubbed of `coach_private_note`. The cover thumbnail
        // is the first item whose standalone thumbnail the viewer can
        // actually load — see `_resolveFeedbackPlaylistCover` below.
        // PR #92 review follow-up: previously we hard-pinned to
        // `items[0]`, which meant a private-first-item playlist always
        // showed the placeholder cover even when later items had
        // viewer-accessible thumbnails. Walking the list fixes that
        // without weakening the standalone GET endpoint's auth model.
        container.innerHTML = playlists.map((p) => {
            const isReviewed = reviewed.has(Number(p.id));
            const clipCount = p.note_ids?.length || p.items?.length || 0;
            // Always render a placeholder tile first so layout is
            // stable while the cover-resolver runs. The
            // `data-feedback-cover-playlist` attribute lets the
            // resolver find this <img> without holding a DOM ref.
            const coverThumb = `
                <div class="coach-thumb coach-thumb--card" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                    <img class="coach-thumb-img" data-feedback-cover-playlist="${Number(p.id)}" alt="" loading="lazy" decoding="async">
                </div>
            `;
            return `
            <article class="feedback-card feedback-playlist-card feedback-card--with-thumb">
                ${coverThumb}
                <div class="feedback-card-body">
                    <span class="feedback-card-kicker">Review Session</span>
                    <h3 class="feedback-card-title">${this.esc(p.title)}</h3>
                    <div class="feedback-card-meta">${clipCount} clip${clipCount === 1 ? '' : 's'} · ${isReviewed ? 'Reviewed' : 'New'}</div>
                    ${p.description ? `<p class="feedback-card-description">${this.esc(p.description)}</p>` : ''}
                    <div class="feedback-card-actions">
                        <button type="button" class="btn-primary" onclick="app.openFeedbackPlaylist(${p.id})">▶ Play session</button>
                        <button type="button" class="mini-action-btn" onclick="app.markFeedbackItemReviewed({ playlist_id: ${p.id} })">${isReviewed ? 'Reviewed ✓' : 'Mark reviewed'}</button>
                    </div>
                </div>
            </article>`;
        }).join('');
        // Kick off cover resolution for each playlist in parallel —
        // each playlist walks its own items[] until one returns a
        // non-null thumbnail URL. Failures stay as placeholders.
        for (const p of playlists) {
            this._resolveFeedbackPlaylistCover(container, p);
        }
    },

    /** Phase 3b PR #92 review follow-up — walk `playlist.items[]` until
     *  we find one whose standalone thumbnail actually loads, then
     *  assign that URL to the playlist's cover `<img>`. The standalone
     *  endpoint deliberately doesn't honour the playlist-grants-access
     *  rule for private items (per CLAUDE.md), so a private item
     *  returns null here and we fall through to the next item. If
     *  every item fails, the placeholder remains in place — which is
     *  the correct "no cover available" state.
     *
     *  Sequential rather than `Promise.all` so a long playlist stops
     *  fetching as soon as a cover is found, and so we don't race
     *  multiple winners onto the same `<img>`. */
    async _resolveFeedbackPlaylistCover(container, playlist) {
        if (!container || !playlist) return;
        const items = playlist.items || [];
        if (!items.length) return;
        const imgEl = container.querySelector(
            `img[data-feedback-cover-playlist="${Number(playlist.id)}"]`
        );
        if (!imgEl) return;
        for (const item of items) {
            // Check the cache via loadCoachNoteThumbnail; on a hit it
            // resolves immediately. On a miss it goes through the same
            // auth-bearing fetch + negative-cache path used everywhere
            // else, so subsequent renders short-circuit.
            const url = await this.loadCoachNoteThumbnail(item?.id);
            if (!url) continue;
            // The container may have re-rendered (or the user navigated
            // away) before this cover resolved. Bail if so.
            if (!imgEl.isConnected) return;
            imgEl.src = url;
            imgEl.dataset.thumbState = 'loaded';
            const wrapper = imgEl.closest('[data-thumb]');
            if (wrapper) wrapper.dataset.thumbState = 'loaded';
            return;
        }
        // All items failed → placeholder stays as-is. Nothing else to do.
    },

    /** Render the Notes tab as a responsive grid of self-contained
     *  cards. Each card shows tone pill, title, match/timestamp meta,
     *  player_summary (or body fallback), the structured what / why /
     *  next stack, optional Coach context disclosure, and a Watch /
     *  Mark reviewed action row. Click "Watch" → `openFeedbackNote()`
     *  opens the focused modal with telestration. */
    renderFeedbackNotes(data) {
        const container = document.getElementById('feedback-notes-list');
        if (!container) return;
        const notes = data?.notes || [];
        const reviewed = new Set((data?.reviews || []).filter((r) => r.note_id).map((r) => Number(r.note_id)));
        if (!notes.length) {
            container.innerHTML = '<div class="session-empty">No coaching notes have been shared with you yet.</div>';
            return;
        }
        // Cards are intentionally compact: thumb + tone + title + meta
        // only. No inline summary, no inline board, no row of action
        // buttons. Clicking the card opens the unified detail/playback
        // modal (`openFeedbackNote(id)`) which is the single review
        // surface — same layout for video, observation, and tactical-
        // board notes — so a viewer always lands in one consistent UI.
        container.innerHTML = notes.map((n) => {
            const isReviewed = reviewed.has(Number(n.id));
            const isObservation = (n.note_context || 'video') === 'observation';
            const tonePill = this._feedbackTonePillHtml(n.note_type);
            // Observation notes have no match/slot/timestamp anchor — use
            // event metadata so the meta line never shows "null · 0:00".
            const metaParts = [];
            if (isObservation) {
                if (n.event_type) {
                    const typeLabel = `${n.event_type[0].toUpperCase()}${n.event_type.slice(1)}`;
                    metaParts.push(`${typeLabel} observation`);
                } else {
                    metaParts.push('Observation');
                }
                if (n.event_date) metaParts.push(n.event_date);
            } else {
                metaParts.push(this.matchLabel(n.match_id));
                metaParts.push(this.formatClock(n.timestamp_seconds));
            }
            metaParts.push(isReviewed ? 'Reviewed' : 'New');
            const meta = metaParts.filter(Boolean).map((p) => this.esc(p)).join(' · ');
            const titleText = (n.title || '').trim()
                || (isObservation ? ((n.event_title || '').trim() || 'Observation note') : '(untitled)');
            // Thumbnail variants:
            //  - video note: source-video JPEG via the auth-checked
            //    thumbnail mount
            //  - observation with tactical board: compact SVG chip of
            //    the board
            //  - observation without board: clipboard glyph placeholder
            const hasBoard = isObservation && this.tacticalBoardHasContent(n.tactical_board_json);
            const thumb = isObservation
                ? (hasBoard
                    ? `<div class="coach-thumb coach-thumb--card coach-thumb--board" aria-hidden="false">${this.tacticalBoardSvg(n.tactical_board_json, { size: 'chip' })}</div>`
                    : '<div class="coach-thumb coach-thumb--card coach-thumb--observation" data-thumb-state="placeholder" aria-hidden="true"><span class="coach-thumb-observation-glyph">📋</span></div>')
                : this._coachNoteThumbHtml(n, { size: 'card' });
            return `
            <article class="feedback-card feedback-note-card feedback-card--with-thumb feedback-card--clickable" data-note-context="${isObservation ? 'observation' : 'video'}" tabindex="0" role="button" aria-label="Open ${this.esc(titleText)}" onclick="app.openFeedbackNote(${n.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackNote(${n.id});}">
                ${thumb}
                <div class="feedback-card-body">
                    <div class="feedback-card-head">
                        ${tonePill}
                        ${isReviewed ? '<span class="feedback-card-status">Reviewed ✓</span>' : ''}
                    </div>
                    <h3 class="feedback-card-title">${this.esc(titleText)}</h3>
                    <div class="feedback-card-meta">${meta}</div>
                </div>
            </article>`;
        }).join('');
        // Phase 3b: viewer-side mount uses the same authenticated fetch
        // path. Visibility is enforced server-side per-note — a viewer
        // who can't see a note will get a 404 from the endpoint and
        // we'll render the placeholder. No client-side filtering needed.
        this.mountCoachNoteThumbnailsIn(container);
    },

    /** Phase 4b — render the My Feedback Clips tab. Clips are
     *  server-filtered by visibility before they ever reach the
     *  client (`/api/my-feedback`'s `clips[]` already excludes
     *  private clips and player-tagged clips for unrelated viewers).
     *  No client-side authorization here — same model as Notes /
     *  Playlists.
     *
     *  Card layout mirrors `renderFeedbackNotes`: thumbnail (from the
     *  source note when available, otherwise placeholder) + title +
     *  meta (match · slot · window · duration · category) + optional
     *  description + Watch button. */
    renderFeedbackClips(data) {
        const container = document.getElementById('feedback-clips-list');
        if (!container) return;
        const clips = data?.clips || [];
        if (!clips.length) {
            container.innerHTML = '<div class="session-empty">No coaching clips have been shared with you yet.</div>';
            return;
        }
        // Compact clip cards — thumb + clip pill + title + meta. The
        // description, structured fields, and Watch/Mark-reviewed live
        // inside the unified detail modal that opens on card click,
        // matching the notes/observations behaviour so the viewer never
        // sees three different layouts for three review types.
        container.innerHTML = clips.map((c) => {
            const meta = `${this.esc(this.matchLabel(c.match_id))} · `
                + `${this.esc(this.formatClock(c.start_seconds))}–${this.esc(this.formatClock(c.end_seconds))} `
                + `(${this.esc(this._clipDurationLabel(c))})`;
            return `
            <article class="feedback-card feedback-clip-card feedback-card--with-thumb feedback-card--clickable" tabindex="0" role="button" aria-label="Open ${this.esc(c.title)}" onclick="app.openFeedbackClip(${c.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();app.openFeedbackClip(${c.id});}">
                ${this._coachClipThumbHtml(c)}
                <div class="feedback-card-body">
                    <div class="feedback-card-head">
                        <span class="feedback-clip-pill">Clip · ${this.esc(c.category || 'other')}</span>
                    </div>
                    <h3 class="feedback-card-title">${this.esc(c.title)}</h3>
                    <div class="feedback-card-meta">${meta}</div>
                </div>
            </article>`;
        }).join('');
        // Phase 4e: clip thumbnails first, with source-note / co-located
        // note as the auth-checked fallback for clips not yet generated.
        this.mountCoachClipThumbnailsIn(container);
    },

    /** Helper — choose a human-friendly observation context label for
     *  the detail modal pill. Mirrors the card-meta wording but avoids
     *  the suffix "observation" duplication when the event_type already
     *  spells it out. */
    _observationContextLabel(note) {
        if (note.event_type === 'tactical' && this.tacticalBoardHasContent(note.tactical_board_json)) {
            return 'Tactical observation';
        }
        if (note.event_type) {
            const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
            return `${typeLabel} observation`;
        }
        return 'Coach observation';
    },

    async markFeedbackItemReviewed(data) {
        try {
            await this.markFeedbackReviewed(data);
            this.showSuccess('Marked reviewed.');
            await this.renderMyFeedback();
        } catch (err) { this.showError(err.message); }
    },

    /** Render the inline Development tab in My Feedback. Driven by
     *  `_feedbackData.players` (linked players) + a per-player viewer
     *  endpoint fetch. If multiple players are linked, a chip selector
     *  switches between them — for a single player we skip the
     *  selector and show the profile straight away. */
    renderFeedbackMatchSummaries(data) {
        const list = document.getElementById('feedback-summaries-list');
        if (!list) return;
        const summaries = data?.match_summaries || [];
        if (!summaries.length) {
            list.innerHTML = '<div class="session-empty">No team-visible match summaries yet.</div>';
            return;
        }
        const notesById = new Map((data?.notes || []).map((n) => [Number(n.id), n]));
        const clipsById = new Map((data?.clips || []).map((c) => [Number(c.id), c]));
        const playlistsById = new Map((data?.playlists || []).map((p) => [Number(p.id), p]));
        list.innerHTML = summaries.map((s) => {
            const sections = this._summarySectionData(s, {
                team_positives: 'What went well',
                team_improvements: 'What we can improve',
                body: 'Coach recap',
            });
            const notes = (s.note_ids || []).map((id) => notesById.get(Number(id))).filter(Boolean);
            const clips = (s.clip_ids || []).map((id) => clipsById.get(Number(id))).filter(Boolean);
            const playlists = (s.playlist_ids || []).map((id) => playlistsById.get(Number(id))).filter(Boolean);
            const sources = [
                ...notes.map((n) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackNote(${Number(n.id)})">Note: ${this.esc(n.title || 'Moment')}</button>`),
                ...clips.map((c) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackClip(${Number(c.id)})">Clip: ${this.esc(c.title || 'Clip')}</button>`),
                ...playlists.map((p) => `<button type="button" class="mini-action-btn" onclick="app.openFeedbackPlaylist(${Number(p.id)})">Playlist: ${this.esc(p.title || 'Session')}</button>`),
            ];
            const sourceCount = sources.length;
            return `
                <article class="feedback-card feedback-summary-card">
                    <div class="feedback-card-body">
                        <div class="feedback-card-kicker">Match summary</div>
                        <h3 class="feedback-card-title">${this.esc(this.matchLabel(s.match_id))}</h3>
                        <p class="feedback-card-meta">${sourceCount ? `${sourceCount} source${sourceCount === 1 ? '' : 's'} linked` : 'Team recap'}</p>
                        <div class="feedback-summary-preview" aria-label="Match summary preview">
                            ${sections.slice(0, 3).map(([label, value]) => `<section class="feedback-summary-section"><h4>${this.esc(label)}</h4><p>${this.esc(value)}</p></section>`).join('')}
                        </div>
                        <details class="feedback-summary-more">
                            <summary>Full match summary</summary>
                            <div class="feedback-summary-full">
                                ${sections.map(([label, value]) => `<section><h4>${this.esc(label)}</h4><p>${this.esc(value)}</p></section>`).join('')}
                            </div>
                        </details>
                        ${sources.length ? `<div class="feedback-card-actions feedback-summary-sources" aria-label="Linked evidence">${sources.join('')}</div>` : ''}
                    </div>
                </article>`;
        }).join('');
    },

};
