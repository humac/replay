// Focused feedback player + playlist session controller mixin.
//
// PR-FE 11: mechanical move out of js/coaching.js. Owns the focused
// feedback review modal (the single review surface for video notes,
// observation notes, and clips — mounted from
// `<template id="feedback-player-template">`), the HLS + telestration
// loaders, the 10s heartbeat, the clip end-of-window monitor, the
// playlist session controller (turning visible playlist items into a
// guided playback session through the same modal), the detail-modal
// composers that produce the unified structured body (`_renderUnified
// FeedbackBody` + helpers), and the match-page deep-link helper
// `updateCoachThisMatchLink`.
//
// Cross-domain helpers stay in coaching.js: `setupCoachCanvas` /
// `paintCoachCanvas` / `renderCoachDrawing` (telestrator painter is
// shared between Coach Review and the feedback player) and the
// tactical-board renderer (`tacticalBoardSvg` / `tacticalBoardHasContent`,
// from js/tactical-board.js). Mixin merge resolves the `this.x()`
// peer calls into the assembled `window.app`.

import { NOTE_CATEGORIES } from '../coaching.js';

export const coachingFeedbackPlayerMixin = {
    _coachPlaylistSession: null,
    _coachPlaylistMonitor: null,
    _coachPlaylistFreezeTimer: null,

    openFeedbackNote(noteId) {
        const note = (this._feedbackData?.notes || []).find((n) => Number(n.id) === Number(noteId));
        if (!note) {
            this.showError('Note not available.');
            return;
        }
        this.openFeedbackPlayer({ mode: 'note', note });
    },

    openFeedbackPlaylist(playlistId) {
        const playlist = (this._feedbackData?.playlists || []).find((p) => Number(p.id) === Number(playlistId));
        if (!playlist) return;
        this.openFeedbackPlayer({ mode: 'playlist', playlist, playerSource: 'feedback' });
    },

    // TODO(PR-FE 10): renderFeedbackClips moved to js/coaching/feedback.js.

    openFeedbackClip(clipId) {
        const clip = (this._feedbackData?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) return;
        this.openFeedbackPlayer({ mode: 'clip', clip, playerSource: 'feedback' });
    },

    // ===== Phase 6e — viewer detail modals =====
    //
    // The detail modal is the single read-only surface a player/family
    // viewer uses to read the full structured feedback for a note,
    // observation, or clip. It is composed from the data the server
    // already returned in `/api/my-feedback` (or
    // `/api/my-feedback/players/{id}/development`) — no new endpoints, no
    // new client-side authorization, no client-side filtering.
    //
    // Privacy invariants (defense in depth):
    //   - `coach_private_note` is NEVER templated here. The server
    //     scrubs it via `_strip_private_fields` for viewers; we also
    //     refuse to render it client-side regardless of payload.
    //   - The detail modal pulls the note/clip out of `_feedbackData`,
    //     so it can only show what the viewer endpoint already returned.
    //   - `tactical_board_json` follows the parent note's visibility on
    //     the server. If a board reaches us, the parent note is visible.
    //
    // Defensive rendering:
    //   - Missing optional structured fields collapse cleanly (no empty
    //     section headings, no "null" / "undefined" / "NaN").
    //   - Observation notes without a board fall through to the text
    //     layout — no empty board container.
    //   - Older notes without Phase 6 fields render without the event
    //     metadata block.

    /** Resolve linked-player chips for a note/clip from the data the
     *  server already shipped. Falls back to `_feedbackData.players`
     *  (the linked-strip payload) and then to a "Player {short id}" label
     *  so a defensive payload never produces "undefined". */
    _resolveLinkedPlayerChips(playerIds) {
        if (!Array.isArray(playerIds) || !playerIds.length) return '';
        const knownPlayers = (this._feedbackData?.players || []);
        const byId = new Map(knownPlayers.map((p) => [String(p.id), p]));
        const chips = playerIds.map((pid) => {
            const player = byId.get(String(pid));
            const label = player ? this.playerLabel(player) : 'Linked player';
            return `<span class="feedback-linked-pill">${this.esc(label)}</span>`;
        });
        return chips.join('');
    },

    /** Build the structured-fields stack — this is the single composition
     *  point shared between the My Feedback note detail modal and the
     *  focused-feedback-player body. Renders only what's non-empty so a
     *  viewer never sees an empty "What happened" block. */
    _detailStructuredHtml(note) {
        const items = [
            ['What happened',     note?.what_happened],
            ['Why it matters',    note?.why_it_matters],
            ['What to do next',   note?.what_to_do_next],
        ].filter(([, v]) => (v || '').trim());
        if (!items.length) return '';
        return items.map(([label, value]) => `
            <section class="feedback-detail-section">
                <h4 class="feedback-detail-section-title">${this.esc(label)}</h4>
                <p class="feedback-detail-section-body">${this.esc(value.trim())}</p>
            </section>
        `).join('');
    },

    /** Build the meta line for a video note's detail header. */
    _detailVideoMetaHtml(note) {
        const parts = [
            this.matchLabel(note.match_id),
            this.slotLabel(note.slot),
            this.formatClock(note.timestamp_seconds),
        ].filter(Boolean);
        return parts.map((p) => this.esc(p)).join(' · ');
    },

    /** Build the meta line for an observation note's detail header.
     *  Returns HTML-escaped text safe to drop into innerHTML. */
    _detailObservationMetaHtml(note) {
        return this.esc(this._observationMetaText(note));
    },

    /** Plain-text variant — safe to assign via textContent. The HTML
     *  helper above escapes the same string; assigning the escaped
     *  HTML to textContent would double-escape characters like `&`,
     *  so the modal subtitle uses this plain-text form. */
    _observationMetaText(note) {
        const parts = [];
        if (note.event_type) {
            const typeLabel = `${note.event_type[0].toUpperCase()}${note.event_type.slice(1)}`;
            parts.push(`${typeLabel} observation`);
        } else {
            parts.push('Coach observation');
        }
        if (note.event_title && note.event_title !== (note.title || '')) {
            parts.push(note.event_title);
        }
        if (note.event_date) parts.push(note.event_date);
        return parts.filter(Boolean).join(' · ');
    },

    /** Phase 6e — the unified review-modal body composer. Builds the
     *  same structured layout for video notes, observation notes, and
     *  clips so the viewer always sees one consistent reading
     *  experience. The visual (video / tactical board / playback
     *  window) is rendered ABOVE this body by the focused-feedback
     *  player template; this composer fills the body slot below it
     *  with: tone + category + linked players + Summary +
     *  What happened / Why / Next + Additional detail + tags.
     *
     *  `coach_private_note` is NEVER referenced or templated — defense
     *  in depth even though the server already scrubs it for viewers
     *  via `_strip_private_fields`.
     *
     *  Inputs:
     *    { kind: 'note',  note }   — video or observation note
     *    { kind: 'clip',  clip }   — coaching clip
     */
    _renderUnifiedFeedbackBody(target, { kind, note = null, clip = null }) {
        if (!target) return;
        const reviews = this._feedbackData?.reviews || [];
        let parts = [];
        if (kind === 'note' && note) {
            const isObservation = (note.note_context || 'video') === 'observation';
            const isReviewed = reviews.some((r) => Number(r.note_id) === Number(note.id));
            const tonePill = this._feedbackTonePillHtml(note.note_type);
            const categoryHtml = note.category
                ? `<span class="feedback-detail-chip">${this.esc(this._categoryLabel(note.category))}</span>`
                : '';
            const contextPill = isObservation
                ? `<span class="feedback-detail-context-pill" data-context="observation">${this.esc(this._observationContextLabel(note))}</span>`
                : `<span class="feedback-detail-context-pill" data-context="video">Video note</span>`;
            const reviewedChip = isReviewed
                ? '<span class="feedback-detail-chip feedback-detail-chip--reviewed">Reviewed ✓</span>'
                : '';
            const linkedHtml = this._resolveLinkedPlayerChips(note.player_ids);
            const linkedSection = linkedHtml
                ? `<div class="feedback-detail-linked"><span class="feedback-detail-linked-label">For:</span>${linkedHtml}</div>`
                : '';
            const { primary, secondary } = this._feedbackNoteSummary(note);
            const structured = this._detailStructuredHtml(note);
            const tagsHtml = (note.tags && note.tags.length)
                ? `<div class="feedback-detail-chips" aria-label="Tags">${note.tags.map((t) => `<span class="feedback-detail-chip feedback-detail-chip--tag">#${this.esc(t)}</span>`).join('')}</div>`
                : '';
            parts.push(`
                <div class="feedback-detail-head-row">
                    ${contextPill}
                    ${tonePill}
                    ${categoryHtml}
                    ${reviewedChip}
                </div>
                ${linkedSection}
            `);
            if (primary) {
                parts.push(`<section class="feedback-detail-summary"><h4 class="feedback-detail-section-title">Summary</h4><p>${this.esc(primary)}</p></section>`);
            }
            if (structured) parts.push(structured);
            if (secondary) {
                parts.push(`<section class="feedback-detail-section feedback-detail-additional"><h4 class="feedback-detail-section-title">Additional detail</h4><p class="feedback-detail-section-body">${this.esc(secondary)}</p></section>`);
            }
            if (tagsHtml) parts.push(tagsHtml);
        } else if (kind === 'clip' && clip) {
            const categoryLabel = this._categoryLabel(clip.category || 'other');
            const linkedHtml = this._resolveLinkedPlayerChips(clip.player_ids);
            const linkedSection = linkedHtml
                ? `<div class="feedback-detail-linked"><span class="feedback-detail-linked-label">For:</span>${linkedHtml}</div>`
                : '';
            const description = (clip.description || '').trim();
            parts.push(`
                <div class="feedback-detail-head-row">
                    <span class="feedback-detail-context-pill" data-context="clip">Coaching clip</span>
                    ${categoryLabel ? `<span class="feedback-detail-chip">${this.esc(categoryLabel)}</span>` : ''}
                </div>
                ${linkedSection}
            `);
            if (description) {
                parts.push(`<section class="feedback-detail-summary"><h4 class="feedback-detail-section-title">Description</h4><p>${this.esc(description)}</p></section>`);
            }
        }
        target.classList.add('feedback-detail-body');
        target.dataset.context = kind === 'clip' ? 'clip' : ((note?.note_context || 'video') === 'observation' ? 'observation' : 'video');
        target.innerHTML = parts.join('');
    },

    /** Helper — resolve a category code to its display label. Falls back
     *  to the raw value (capitalized) for unknown codes so a forward-
     *  compat payload from a future migration still renders sensibly. */
    _categoryLabel(category) {
        if (!category) return '';
        const map = Object.fromEntries(NOTE_CATEGORIES);
        return map[category] || category.charAt(0).toUpperCase() + category.slice(1).replace(/_/g, ' ');
    },

    // TODO(PR-FE 10): _observationContextLabel moved to js/coaching/feedback.js.

    // ===== Focused feedback / playlist player modal =====

    async openFeedbackPlayer({ mode, note = null, playlist = null, clip = null, playerSource = 'feedback' }) {
        const tpl = document.getElementById('feedback-player-template');
        if (!tpl) { this.showError('Feedback player template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Snapshot the canvas/video ids the telestrator points at, so we can restore on close.
        const prevCanvasId = this._coachCanvasId;
        const prevVideoId = this._coachVideoId;
        // Rebind the painter to the modal's elements.
        this._coachCanvasId = 'feedback-drawing-canvas';
        this._coachVideoId = 'feedback-player-video';

        const cleanup = () => {
            this._stopFeedbackHeartbeat();
            this.stopFeedbackPlaylistSession();
            // Phase 4b: tear down the clip end-of-window watcher if a
            // clip session was active. Idempotent — no-op when not in
            // clip mode.
            this._stopClipMonitor();
            this.destroyHlsPlayer();
            this.deactivateCoachCanvas();
            // Modal canvas was cloned fresh from the template and is removed
            // from the DOM when the modal closes. Detach the window-resize
            // listener bound to it so the closure (and the canvas it captured)
            // can be garbage-collected.
            this.teardownCoachCanvasListeners('feedback-drawing-canvas');
            this._coachDrawing = null;
            this._coachCanvasId = prevCanvasId;
            this._coachVideoId = prevVideoId;
            this._feedbackPlayer = null;
        };

        const onMount = () => {
            this._feedbackPlayer = { body, mode, note, playlist, clip, playerSource };
            const videoWrapper = body.querySelector('[data-field="video-wrapper"]');
            const boardWrapper = body.querySelector('[data-field="board-wrapper"]');
            if (mode === 'note') {
                const isObservation = (note.note_context || 'video') === 'observation';
                body.querySelector('[data-field="title"]').textContent = note.title || (isObservation ? 'Coach observation' : 'Coaching note');
                body.querySelector('[data-field="subtitle"]').textContent = isObservation
                    ? this._observationMetaText(note)
                    : `${this.matchLabel(note.match_id)} · ${this.formatClock(note.timestamp_seconds)} · ${this.slotLabel(note.slot)}`;
                // Phase 6e — the focused player modal is the SINGLE
                // review surface for notes (video + observation). For
                // observation notes there's no playable video: hide the
                // <video>+canvas wrapper and reveal the read-only
                // tactical board (when present) where the video would
                // be. For video notes, hide the board wrapper and load
                // the HLS source as before.
                if (isObservation) {
                    if (videoWrapper) videoWrapper.hidden = true;
                    if (boardWrapper) {
                        const hasBoard = this.tacticalBoardHasContent(note.tactical_board_json);
                        if (hasBoard) {
                            boardWrapper.hidden = false;
                            boardWrapper.innerHTML = this.tacticalBoardSvg(note.tactical_board_json, { size: 'preview' });
                        } else {
                            boardWrapper.hidden = true;
                        }
                    }
                } else {
                    if (boardWrapper) boardWrapper.hidden = true;
                    if (videoWrapper) videoWrapper.hidden = false;
                    this._loadFeedbackVideoForNote(note);
                }
                // Always render the unified structured-field body
                // (Summary / What happened / Why / Next / Additional
                // detail / tags / linked players). `coach_private_note`
                // is never templated.
                this._renderUnifiedFeedbackBody(body.querySelector('[data-field="body"]'), { kind: 'note', note });
            } else if (mode === 'playlist') {
                body.querySelector('[data-field="title"]').textContent = playlist.title || 'Review playlist';
                body.querySelector('[data-field="subtitle"]').textContent = `${(playlist.note_ids || []).length} clips`;
                body.querySelector('[data-field="body"]').textContent = playlist.description || '';
                if (boardWrapper) boardWrapper.hidden = true;
                this.startCoachingPlaylistSession(playlist, { playerSource });
            } else if (mode === 'clip') {
                // Phase 4b: clip playback. Title + a subtitle that
                // names the match, slot, and the [start–end] window
                // so the player knows what they're about to watch.
                body.querySelector('[data-field="title"]').textContent = clip.title || 'Coaching clip';
                body.querySelector('[data-field="subtitle"]').textContent =
                    `${this.matchLabel(clip.match_id)} · ${this.slotLabel(clip.slot)} · `
                    + `${this.formatClock(clip.start_seconds)}–${this.formatClock(clip.end_seconds)} `
                    + `(${this._clipDurationLabel(clip)})`;
                if (boardWrapper) boardWrapper.hidden = true;
                if (videoWrapper) videoWrapper.hidden = false;
                this._loadFeedbackVideoForClip(clip);
                // Phase 6e — clips share the unified body layout. Show
                // category + meta + description in the same Summary /
                // section structure as notes so the viewer sees one
                // consistent layout across all three review types.
                this._renderUnifiedFeedbackBody(body.querySelector('[data-field="body"]'), { kind: 'clip', clip });
                // Clips have no Mark-reviewed backend yet — hide the
                // confirm button so Close is the only action.
                const modalCard = body.closest('.app-modal-card');
                const confirmBtn = modalCard?.querySelector('.app-modal-confirm');
                if (confirmBtn) confirmBtn.hidden = true;
            }
        };

        // Phase 6e — title reflects the kind so the player knows what
        // they're looking at, but the modal shell is the same one for
        // every review type. Observation notes carry a context-aware
        // kicker ("Practice observation" / "Tactical observation"
        // etc.) so the reading experience matches the card meta.
        const modalTitle = (() => {
            if (mode === 'playlist') return 'Review Session';
            if (mode === 'clip') return 'Coaching Clip';
            if (mode === 'note' && (note.note_context || 'video') === 'observation') {
                return this._observationContextLabel(note);
            }
            return 'Coaching Note';
        })();
        await this.formModal({
            title: modalTitle,
            kicker: 'Feedback',
            body,
            confirmLabel: 'Mark reviewed',
            cancelLabel: 'Close',
            size: 'wide',
            onMount,
            onSubmit: async (close) => {
                try {
                    if (mode === 'note' && note) await this.markFeedbackReviewed({ note_id: note.id });
                    else if (mode === 'playlist' && playlist) await this.markFeedbackReviewed({ playlist_id: playlist.id });
                    // Phase 4b: clips don't have a "mark reviewed"
                    // backend yet (the `coaching_reviews` table only
                    // accepts note_id / playlist_id). Close cleanly
                    // without firing an API call — the coach/player
                    // can still close normally.
                    if (mode === 'note' || mode === 'playlist') {
                        this.showSuccess('Marked reviewed.');
                        await this.renderMyFeedback();
                    }
                } catch (err) { this.showError(err.message); }
                close(true);
            },
        });
        cleanup();
    },

    /** Phase 4b — load the clip's source match video, seek to
     *  `start_seconds`, and arm a `timeupdate` watcher that pauses at
     *  `end_seconds`. No MP4 export, no segment download — pure
     *  seek-based playback against the existing match HLS.
     *
     *  Replay-after-end (PR #96 review fix): once the playhead reaches
     *  `end_seconds` we pause + snap to the boundary AND set a
     *  `clipAtEnd` flag. The next `play` event on the video element
     *  reads that flag and seeks back to `start_seconds`, so the
     *  player gets a from-the-start replay instead of immediately
     *  re-pausing on the next monitor tick. The flag is also reset on
     *  any user-initiated seek that lands strictly before the end
     *  boundary (so a manual scrub-back-and-play behaves the same as
     *  a fresh playthrough). */
    async _loadFeedbackVideoForClip(clip) {
        const video = document.getElementById('feedback-player-video');
        if (!video) return;
        const { hlsUrl, mp4Url } = this.getStreamUrls(clip.match_id, clip.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        // Phase 4c (issue #99): clips do NOT render a telestrator
        // overlay. Earlier code called `setupCoachCanvas()` here for
        // the resize-listener side effect, but that wired the canvas
        // event handlers (`paintCoachCanvas`, the global resize
        // observer) into a session that never paints anything — pure
        // wasted work, and it implied clip-drawing support exists
        // when it doesn't. The drawing canvas is left dormant for
        // clip mode; if a future phase adds clip telestration, it
        // can opt back in by calling `setupCoachCanvas` here AND
        // wiring the equivalent of `_renderFeedbackTelestration` for
        // clip drawings. Note + playlist playback paths still call
        // `setupCoachCanvas` themselves — unchanged.
        //
        // Issue #105: the cloned `<canvas id="feedback-drawing-canvas">`
        // sits absolute-positioned over the `<video>` with
        // `pointer-events: auto` (see `.coach-drawing-canvas` in
        // styles.css). For note / playlist mode `setupCoachCanvas` is
        // the bridge that consumes those events for painting. In clip
        // mode nothing consumes them — but the overlay still receives
        // every click, swallowing presses on the native video Play /
        // Pause / scrub controls. Hide and decouple it explicitly so
        // the user can drive playback through the native chrome.
        const clipCanvas = document.getElementById('feedback-drawing-canvas');
        if (clipCanvas) {
            clipCanvas.style.display = 'none';
            clipCanvas.style.pointerEvents = 'none';
        }

        const startTime = Math.max(0, Number(clip.start_seconds || 0));
        const endTime = Math.max(startTime + 0.5, Number(clip.end_seconds || 0));

        // Tear down any prior clip monitor BEFORE wiring the new one.
        // This also resets `clipAtEnd` for the new session — opening a
        // fresh clip never inherits an end-of-clip state from the
        // previous one.
        this._stopClipMonitor();

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            // Seek to the clip's start. Playback does NOT autoplay —
            // the player presses Play when ready (consistent with
            // single-note feedback playback).
            video.currentTime = startTime;
        };
        video.addEventListener('loadedmetadata', onLoaded);

        // Mutable session state for this clip. `_clipMonitor` is the
        // single source of truth — both the listeners and the fallback
        // timer read from it via the `monitor` closure, and
        // `_stopClipMonitor` clears every reference on cleanup so a
        // closed modal can't leak event handlers or the interval.
        const session = {
            videoEl: video,
            startTime,
            endTime,
            clipAtEnd: false,
            // Listener references — needed so `_stopClipMonitor` can
            // remove the SAME function objects we registered.
            timeupdate: null,
            play: null,
            seeked: null,
            intervalId: 0,
        };

        const monitor = () => {
            if (!video.isConnected) { this._stopClipMonitor(); return; }
            // The session may have been replaced (or cleared) by a
            // teardown that fired between intervals. Bail gracefully
            // in that case so we never act on a torn-down clip.
            if (this._clipMonitor !== session) return;
            // If the playhead crosses `end_seconds`, pause + snap to
            // the boundary and flag the at-end state. The flag is the
            // signal the `play` listener uses to know it must rewind
            // before allowing playback to continue (PR #96 review fix
            // — without this, pressing Play would immediately re-fire
            // this same condition and re-pause).
            if (video.currentTime >= endTime - 0.05 && !video.paused) {
                video.pause();
                video.currentTime = endTime;
                session.clipAtEnd = true;
            }
        };

        // On `play`: if we're at the end boundary (either via the
        // pause-snap above, or the user manually scrubbed past), rewind
        // to `start_seconds` so the next playback frame is from the
        // beginning of the clip instead of from the locked end position.
        // Avoids the recursive pause/play loop that the previous
        // implementation had.
        const onPlay = () => {
            if (this._clipMonitor !== session) return;
            // `clipAtEnd` covers the snap-paused case; the
            // `currentTime >= endTime` half covers a user who
            // manually scrubbed the timeline past `endTime` and then
            // hit Play — same outcome either way: rewind to start.
            if (session.clipAtEnd || video.currentTime >= endTime - 0.05) {
                session.clipAtEnd = false;
                video.currentTime = startTime;
            }
        };

        // On `seeked`: if the user manually scrubbed BACKWARD to a
        // time strictly before `end_seconds`, clear the at-end flag so
        // playback proceeds normally. Without this, a user who scrubs
        // back from the boundary would still be in `clipAtEnd === true`
        // state, and the next play event would yank them all the way
        // back to `startTime` — surprising. Tolerance of 0.05s mirrors
        // the boundary check above.
        const onSeeked = () => {
            if (this._clipMonitor !== session) return;
            if (video.currentTime < endTime - 0.05) {
                session.clipAtEnd = false;
            }
        };

        session.timeupdate = monitor;
        session.play = onPlay;
        session.seeked = onSeeked;
        video.addEventListener('timeupdate', session.timeupdate);
        video.addEventListener('play', session.play);
        video.addEventListener('seeked', session.seeked);
        // Belt-and-braces fallback timer: some HLS sources throttle
        // `timeupdate` during seeks / buffer stalls. 250 ms is fine —
        // a clip's end boundary is enforced cooperatively, not
        // sample-accurately.
        session.intervalId = window.setInterval(monitor, 250);
        this._clipMonitor = session;

        this._startFeedbackHeartbeat(clip.match_id, clip.slot, video);
    },

    /** Tear down the clip end-of-window watcher. Safe to call when
     *  the modal isn't in clip mode — short-circuits on missing
     *  state. Called by `cleanup` inside `openFeedbackPlayer` and at
     *  the top of `_loadFeedbackVideoForClip` so a fresh clip session
     *  never inherits the previous one's listeners or `clipAtEnd`
     *  flag. */
    _stopClipMonitor() {
        const m = this._clipMonitor;
        if (!m) return;
        try {
            if (m.videoEl) {
                if (m.timeupdate) m.videoEl.removeEventListener('timeupdate', m.timeupdate);
                if (m.play) m.videoEl.removeEventListener('play', m.play);
                if (m.seeked) m.videoEl.removeEventListener('seeked', m.seeked);
            }
            if (m.intervalId) window.clearInterval(m.intervalId);
        } catch { /* ignore */ }
        this._clipMonitor = null;
    },

    async _loadFeedbackVideoForNote(note) {
        const video = document.getElementById('feedback-player-video');
        if (!video) return;
        const { hlsUrl, mp4Url } = this.getStreamUrls(note.match_id, note.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        // PR 1c follow-up: bind the canvas listeners + ResizeObserver
        // BEFORE the video paints so the canvas bitmap dimensions
        // catch up to the wrapper as soon as the layout settles.
        this.setupCoachCanvas();

        // PR 1c follow-up: cache the saved drawing payload on the
        // modal session so we can re-show the telestration when the
        // player scrubs back to (or before) the timestamp. We use a
        // dedicated `noteDrawing` slot rather than `_coachDrawing`
        // because `_coachDrawing` gets nulled on Play; the cached
        // copy is the source of truth for the entire modal lifetime.
        if (this._feedbackPlayer) this._feedbackPlayer.noteDrawing = note.drawing || {};
        this._renderFeedbackTelestration();
        const targetTime = Math.max(0, Number(note.timestamp_seconds || 0));

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            video.currentTime = targetTime;
            this._renderFeedbackTelestration();
            // PR 1c follow-up: do NOT autoplay. The drawing is a
            // freeze-frame coaching overlay — let the player study
            // the telestration first. They press Play when ready.
        };
        video.addEventListener('loadedmetadata', onLoaded);

        // Repaint when the first frame paints (some HLS sources reach
        // loadedmetadata with a 0×0 wrapper rect).
        const onPainted = () => {
            video.removeEventListener('loadeddata', onPainted);
            this._renderFeedbackTelestration();
        };
        video.addEventListener('loadeddata', onPainted);

        // PR 1c follow-up: drive telestration visibility from the
        // player state. A persistent `play` / `pause` / `seeked`
        // listener trio so the drawing reappears whenever the player
        // scrubs back to (or pauses at) the freeze timestamp, and
        // disappears whenever the player presses Play. Listeners are
        // removed by `cleanup()` in `openFeedbackPlayer` (the canvas
        // teardown destroys the closure references).
        const onPlay = () => this._clearFeedbackTelestration();
        const onPause = () => this._renderFeedbackTelestration();
        const onSeeked = () => {
            // Show the drawing when the playhead is at or before the
            // saved timestamp; hide it otherwise. We check `paused`
            // too so a seek that happens while playing doesn't flash
            // the drawing into view mid-play.
            if (video.paused && video.currentTime <= targetTime + 0.05) {
                this._renderFeedbackTelestration();
            } else {
                this._clearFeedbackTelestration();
            }
        };
        video.addEventListener('play', onPlay);
        video.addEventListener('pause', onPause);
        video.addEventListener('seeked', onSeeked);

        this._startFeedbackHeartbeat(note.match_id, note.slot, video);
    },

    /** PR 1c follow-up: paint the telestration cached on the current
     *  modal session. Safe to call any number of times — `render
     *  CoachDrawing` is idempotent. */
    _renderFeedbackTelestration() {
        const drawing = this._feedbackPlayer?.noteDrawing
            || this._coachPlaylistSession?.items[this._coachPlaylistSession.index]?.drawing
            || null;
        if (!drawing) return;
        this.renderCoachDrawing(drawing);
    },

    /** PR 1c follow-up: hide the telestration without destroying the
     *  cached drawing payload — so the modal can re-show it later if
     *  the player scrubs back. Mirrors `clearCoachDrawing` for the
     *  visible state but does NOT clear the cache. */
    _clearFeedbackTelestration() {
        // Equivalent to `clearCoachDrawing()` for the visible state
        // but the cache (`_feedbackPlayer.noteDrawing`) survives.
        this._coachDrawing = null;
        this._coachSelectedObjectIndex = null;
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    _startFeedbackHeartbeat(matchId, slot, videoEl) {
        this._stopFeedbackHeartbeat();
        if (!matchId || !slot) return;
        const url = `/api/matches/${encodeURIComponent(matchId)}/heartbeat?slot=${encodeURIComponent(slot)}`;
        const ping = async ({ skipPausedCheck = false } = {}) => {
            if (!skipPausedCheck && videoEl && (videoEl.paused || videoEl.ended)) return;
            try {
                const resp = await fetch(url, { method: 'POST', credentials: 'same-origin' });
                if (resp.status === 403) {
                    if (videoEl) videoEl.pause();
                    this.showError?.('This stream was disconnected by an administrator.');
                    this._stopFeedbackHeartbeat();
                    this.destroyHlsPlayer();
                }
            } catch { /* transient — try again next tick */ }
        };
        ping({ skipPausedCheck: true });
        this._feedbackHeartbeatTimer = window.setInterval(() => ping(), 10000);
    },

    _stopFeedbackHeartbeat() {
        if (this._feedbackHeartbeatTimer) {
            window.clearInterval(this._feedbackHeartbeatTimer);
            this._feedbackHeartbeatTimer = null;
        }
    },

    // ===== Playlist controller (operates on whichever video the modal exposes) =====

    playlistItems(playlist) {
        if (Array.isArray(playlist?.items) && playlist.items.length) return playlist.items;
        const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
        const byId = new Map(notes.map((note) => [Number(note.id), note]));
        return (playlist?.note_ids || []).map((id) => byId.get(Number(id))).filter(Boolean);
    },

    startCoachingPlaylistSession(playlist, { playerSource = 'feedback' } = {}) {
        const items = this.playlistItems(playlist);
        if (!items.length) {
            this.showError('This playlist has no playable notes.');
            return;
        }
        this.stopFeedbackPlaylistSession();
        this._coachPlaylistSession = {
            playlist, items, index: 0,
            frozeCurrentItem: false, paused: false, opening: false,
            playerSource,
        };
        this.openCoachingPlaylistItem(0);
    },

    async openCoachingPlaylistItem(index) {
        const session = this._coachPlaylistSession;
        if (!session) return;
        if (index < 0 || index >= session.items.length) {
            this.finishCoachingPlaylistSession();
            return;
        }
        const item = session.items[index];
        session.index = index;
        // PR 1c follow-up: each playlist item now opens paused at the
        // timestamp with the saved drawing visible — same UX as the
        // standalone note. The previous flow auto-played pre-roll →
        // freeze → post-roll, which made the telestration feel
        // fleeting. Pre-roll is intentionally skipped: the freeze
        // IS the moment; pressing Play reveals the post-roll context.
        // `frozeCurrentItem` starts true because we're already at the
        // freeze position; the monitor only needs to advance to the
        // next item once the post-roll window completes.
        session.frozeCurrentItem = true;
        session.opening = true;
        // Cache the per-item drawing on the modal session so seek-
        // back / pause re-shows it (matches the standalone-note path).
        if (this._feedbackPlayer) this._feedbackPlayer.noteDrawing = item.drawing || {};
        this._coachDrawing = null;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (!video) { session.opening = false; return; }
        const { hlsUrl, mp4Url } = this.getStreamUrls(item.match_id, item.slot);
        this._playRequestToken = (this._playRequestToken || 0) + 1;
        const token = this._playRequestToken;
        this.destroyHlsPlayer();
        this.loadPlaybackSource(video, hlsUrl, mp4Url, token);

        this.setupCoachCanvas();
        this._renderFeedbackTelestration();
        const targetTime = Math.max(0, Number(item.timestamp_seconds || 0));

        const onLoaded = () => {
            video.removeEventListener('loadedmetadata', onLoaded);
            video.currentTime = targetTime;
            this._renderFeedbackTelestration();
            session.opening = false;
            this.startPlaylistMonitor();
            this._startFeedbackHeartbeat(item.match_id, item.slot, video);
        };
        video.addEventListener('loadedmetadata', onLoaded);

        const onPainted = () => {
            video.removeEventListener('loadeddata', onPainted);
            this._renderFeedbackTelestration();
        };
        video.addEventListener('loadeddata', onPainted);

        // PR 1c follow-up: same persistent play/pause/seeked trio as
        // the standalone note — drawing reappears whenever the
        // player scrubs back to (or pauses at) the freeze timestamp,
        // and disappears whenever they press Play.
        const onPlay = () => this._clearFeedbackTelestration();
        const onPause = () => this._renderFeedbackTelestration();
        const onSeeked = () => {
            if (video.paused && video.currentTime <= targetTime + 0.05) {
                this._renderFeedbackTelestration();
            } else {
                this._clearFeedbackTelestration();
            }
        };
        video.addEventListener('play', onPlay);
        video.addEventListener('pause', onPause);
        video.addEventListener('seeked', onSeeked);
    },

    startPlaylistMonitor() {
        this.stopPlaylistMonitor();
        this._coachPlaylistMonitor = window.setInterval(() => {
            const session = this._coachPlaylistSession;
            const video = document.getElementById('feedback-player-video');
            if (!session || !video || session.opening || session.paused) return;
            const item = session.items[session.index];
            const timestamp = Number(item.timestamp_seconds || 0);
            const end = timestamp + Number(session.playlist.post_roll_seconds ?? 8);
            // PR 1c follow-up: the playlist item now opens paused AT
            // the freeze timestamp with the saved drawing visible. The
            // pre-roll-then-freeze loop was removed (`frozeCurrentItem`
            // is set to true in `openCoachingPlaylistItem` so the
            // freeze branch never runs). The monitor's only remaining
            // job is to advance to the next item when the player has
            // pressed Play and watched through the post-roll window.
            if (video.currentTime >= end || video.ended) {
                this.openCoachingPlaylistItem(session.index + 1);
            }
        }, 250);
    },

    stopPlaylistMonitor() {
        if (this._coachPlaylistMonitor) {
            window.clearInterval(this._coachPlaylistMonitor);
            this._coachPlaylistMonitor = null;
        }
        if (this._coachPlaylistFreezeTimer) {
            window.clearTimeout(this._coachPlaylistFreezeTimer);
            this._coachPlaylistFreezeTimer = null;
        }
    },

    renderPlaylistSessionRail() {
        const player = this._feedbackPlayer;
        if (!player) return;
        const rail = player.body.querySelector('[data-field="rail"]');
        if (!rail) return;
        const session = this._coachPlaylistSession;
        if (!session) { rail.hidden = true; rail.innerHTML = ''; return; }
        rail.hidden = false;
        const item = session.items[session.index];
        // PR 1c: surface the per-item tone pill + the player-facing
        // summary INSIDE the playlist player too, so a player watching
        // a session sees the same context they'd see if they opened
        // the standalone note. coach_private_note is never rendered
        // (server already scrubs it; we never template it client-side).
        const tone = this._feedbackTonePillHtml(item.note_type);
        const { primary } = this._feedbackNoteSummary(item);
        rail.innerHTML = `
            ${this._coachNoteThumbHtml(item, { size: 'rail' })}
            <div class="feedback-rail-info">
                <span>Review Session</span>
                <strong>${this.esc(session.playlist.title)}</strong>
                <small>${session.index + 1} of ${session.items.length} · ${this.esc(item.title)} · ${this.esc(item.category || 'note')}</small>
                ${tone || primary ? `
                    <div class="feedback-rail-item-detail">
                        ${tone}
                        ${primary ? `<span class="feedback-rail-item-summary">${this.esc(primary)}</span>` : ''}
                    </div>
                ` : ''}
            </div>
            <div class="feedback-rail-controls">
                <button type="button" class="mini-action-btn" onclick="app.previousCoachingPlaylistItem()">Prev</button>
                <button type="button" class="mini-action-btn" onclick="app.toggleCoachingPlaylistPause()">${session.paused ? 'Resume' : 'Pause'}</button>
                <button type="button" class="mini-action-btn" onclick="app.restartCoachingPlaylistItem()">Restart</button>
                <button type="button" class="mini-action-btn" onclick="app.nextCoachingPlaylistItem()">Next</button>
            </div>
        `;
        this.mountCoachNoteThumbnailsIn(rail);
    },

    toggleCoachingPlaylistPause() {
        const session = this._coachPlaylistSession;
        const video = document.getElementById('feedback-player-video');
        if (!session || !video) return;
        session.paused = !session.paused;
        if (session.paused) video.pause();
        else video.play().catch(() => {});
        this.renderPlaylistSessionRail();
    },

    restartCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index);
    },

    nextCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(session.index + 1);
    },

    previousCoachingPlaylistItem() {
        const session = this._coachPlaylistSession;
        if (session) this.openCoachingPlaylistItem(Math.max(0, session.index - 1));
    },

    finishCoachingPlaylistSession() {
        this.stopPlaylistMonitor();
        const session = this._coachPlaylistSession;
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
        const video = document.getElementById('feedback-player-video');
        if (video) video.pause();
        if (session) this.showSuccess('Playlist finished.');
    },

    stopFeedbackPlaylistSession() {
        this.stopPlaylistMonitor();
        this._coachPlaylistSession = null;
        this.renderPlaylistSessionRail();
    },

    // Backwards-compat shims for any lingering callers (e.g. teardownGameView).
    stopCoachingPlaylistSession() { this.stopFeedbackPlaylistSession(); },

    // ===== Match-page deep link to /coach?tab=review =====

    updateCoachThisMatchLink(match) {
        const link = document.getElementById('coach-this-match-link');
        if (!link) return;
        if (!match || !this.canCoach()) { link.hidden = true; return; }
        const slot = this.activeSlot || 'full';
        link.href = this._coachUrl('review', match.id, slot);
        link.hidden = false;
    },

};
