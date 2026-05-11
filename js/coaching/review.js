// Coach Review domain — Phase 6d-1 single creation workspace for video
// notes, video clips, and tactical-board observations. This file owns the
// telestrator (drawing canvas + tool state + paint primitives + formation
// overlay), the WAI-ARIA source-mode toggle (video / tactical_board), the
// tactical-board mounter integration, the focus-mode drawer, and the
// keyboard shortcut handler. Composer rendering + save flows + template
// application + routing intents live alongside in a sibling commit; the
// AI drafting panel is the last piece still in js/coaching.js until the
// PR-FE 13 ai-domain split.

import { NOTE_CATEGORIES, VISIBILITY_OPTIONS, NOTE_TYPES, DEFAULT_NOTE_TYPE } from '../coaching.js';

export const coachingReviewMixin = {
    /** Phase 6d-1 — keyboard handler for the source-toggle tablist.
     *  Implements the WAI-ARIA tablist pattern: ArrowLeft / ArrowRight
     *  (and ArrowUp / ArrowDown for vertical-list parity) move focus
     *  to the next / previous tab AND activate it (this is an
     *  "automatic activation" tablist — switching modes has no save-
     *  destroying side effect, so activating on focus matches the
     *  click affordance). Home / End jump to first / last. Does NOT
     *  intercept other keys; the inline `onclick` keeps mouse / touch
     *  / Enter / Space activation working unchanged. */
    handleCoachReviewSourceKeydown(event) {
        const target = event.target;
        if (!target?.dataset?.coachReviewSource) return;
        const tablist = target.closest('[role="tablist"]');
        if (!tablist) return;
        const tabs = Array.from(tablist.querySelectorAll('[data-coach-review-source]'));
        if (tabs.length < 2) return;
        const currentIdx = tabs.indexOf(target);
        let nextIdx = currentIdx;
        switch (event.key) {
            case 'ArrowRight':
            case 'ArrowDown':
                nextIdx = (currentIdx + 1) % tabs.length;
                break;
            case 'ArrowLeft':
            case 'ArrowUp':
                nextIdx = (currentIdx - 1 + tabs.length) % tabs.length;
                break;
            case 'Home':
                nextIdx = 0;
                break;
            case 'End':
                nextIdx = tabs.length - 1;
                break;
            default:
                return;
        }
        event.preventDefault();
        const next = tabs[nextIdx];
        if (!next) return;
        // Activate the new mode (which also updates roving tabindex
        // via _applyCoachReviewSource), then move focus to the now-
        // active tab.
        this.setCoachReviewSource(next.dataset.coachReviewSource);
        try { next.focus(); } catch { /* ignore */ }
    },

    /** Public — change the Coach Review source mode. Wires up the
     *  Save-Observation flow on the first tactical-board entry; tears
     *  down the board controller when leaving tactical mode so a
     *  re-entry starts from a clean state. */
    setCoachReviewSource(source) {
        if (source !== 'video' && source !== 'tactical_board') source = 'video';
        // If we're already on this source AND fully mounted, no-op.
        if (this._coachReviewSource === source && this._coachTab === 'review') return;
        // Save the requested source so renderCoachReview picks it up
        // when Review re-renders (covers the cross-tab routing case).
        this._coachReviewRequestedSource = source;
        if (this._coachTab !== 'review') {
            this.setCoachTab('review');
            return;
        }
        this._applyCoachReviewSource(source);
    },

    _applyCoachReviewSource(source) {
        if (source !== 'video' && source !== 'tactical_board') source = 'video';
        const shell = document.querySelector('#coach-tab-review .coach-review-shell');
        if (!shell) return;
        shell.dataset.source = source;
        // Mirror the source mode onto <body> so source-only show/hide
        // rules still scope correctly when openCoachFocusInspector
        // re-parents `.coach-review-side` to <body> (which moves it
        // out of the .coach-review-shell ancestry — see styles.css
        // body[data-coach-review-source] rules). Cleared in
        // tearDownCoachReview / setLoggedOut so it can't leak.
        document.body.dataset.coachReviewSource = source;
        // Toggle button states + roving tabindex (only the active
        // tab is in the tab order; arrow keys move focus WITHIN the
        // tablist via handleCoachReviewSourceKeydown). Mirrors the
        // tone radiogroup pattern in `_syncToneRadiogroup`.
        //
        // The selector is scoped to `.coach-review-source-toggle
        // [data-coach-review-source]` so it only matches the two
        // tablist buttons. A bare `[data-coach-review-source]`
        // selector would also match `<body
        // data-coach-review-source>` (the body-level mirror used by
        // the focus drawer's off-shell scoping rules) and bizarrely
        // toggle `is-active` / `aria-selected` / `tabindex` on the
        // <body> element.
        document.querySelectorAll('.coach-review-source-toggle [data-coach-review-source]').forEach((btn) => {
            const on = btn.dataset.coachReviewSource === source;
            btn.classList.toggle('is-active', on);
            btn.setAttribute('aria-selected', on ? 'true' : 'false');
            btn.setAttribute('tabindex', on ? '0' : '-1');
        });
        // Defense-in-depth: clear any state we may have stamped onto
        // <body> in earlier (pre-fix) calls. Idempotent — both
        // `removeAttribute` calls are no-ops if the attribute is
        // already absent.
        if (document.body.dataset.coachReviewSource === source) {
            document.body.classList.remove('is-active');
            document.body.removeAttribute('aria-selected');
            document.body.removeAttribute('tabindex');
        }
        // Refresh the keyboard-shortcuts help popover so its kbd list
        // reflects the active source mode (video shortcuts vs tactical-
        // board shortcuts). Idempotent — no-op if the popover element
        // hasn't been rendered yet.
        this._refreshCoachShortcutsHelpForSource?.(source);
        const previous = this._coachReviewSource;
        this._coachReviewSource = source;
        if (source === 'tactical_board') {
            // Tear down any video-mode state so a paused match in the
            // background doesn't keep the heartbeat warm or steal
            // the canvas.
            this._stopFeedbackHeartbeat();
            this.deactivateCoachCanvas?.();
            this._mountCoachReviewBoard();
        } else {
            this._unmountCoachReviewBoard();
            // Re-arm the empty placeholder if no video is loaded.
            if (!this._coachReview) {
                const empty = document.getElementById('coach-review-empty');
                if (empty) empty.style.display = 'flex';
            }
        }
        // If we switched modes, also reset focus mode so a focused video
        // doesn't keep its drawer open over a board canvas.
        if (previous && previous !== source) this.exitCoachFocusMode();
    },

    /** Mount the tactical-board authoring canvas + side panel for the
     *  current Review session. Idempotent — a second call replaces the
     *  initial board (used when routing in with a player_id intent). */
    _mountCoachReviewBoard() {
        const stageEl = document.getElementById('coach-review-board-canvas');
        const toolbarEl = document.getElementById('coach-tb-toolbar');
        const formEl = document.getElementById('coach-tb-form');
        const statusEl = document.getElementById('coach-review-board-status');
        if (!stageEl || !toolbarEl || !formEl) return;
        // Re-render the form every mount so new bundle data (e.g. a
        // newly-linked player) flows in.
        this._renderCoachTacticalBoardForm(formEl);
        // Mount the canvas + tools controller.
        const initialBoard = this._coachReviewBoardCtrl
            ? this._coachReviewBoardCtrl.scenePayload()
            : null;
        if (this._coachReviewBoardCtrl) this._coachReviewBoardCtrl.destroy();
        this._coachReviewBoardCtrl = this.mountTacticalBoardReviewCanvas({
            stageEl, toolbarEl, statusEl, initialBoard,
        });
        // Apply any pending player preselection from the routing intent.
        const intent = this._coachReviewIntent;
        if (intent?.playerId) {
            const opt = formEl.querySelector(`[data-field="players"] .coach-check-option[data-value="${this.esc(intent.playerId)}"]`);
            if (opt) {
                opt.classList.add('is-selected');
                opt.setAttribute('aria-pressed', 'true');
            }
            // Default visibility=player when launched from a roster entry.
            const visEl = formEl.querySelector('[data-field="visibility"]');
            if (visEl && !visEl.dataset.userTouched) visEl.value = 'player';
        }
        this._coachReviewIntent = null;
        // Phase 6d-2 follow-up — match the side panel height to the
        // pitch's rendered height so the inspector column equals the
        // board column (the video-mode counterpart to this lives in
        // `_syncCoachReviewSideHeight`). Initial sync runs after the
        // board has been mounted; a ResizeObserver keeps it accurate
        // when the viewport changes. The observer is torn down in
        // `_unmountCoachReviewBoard` so it doesn't leak between
        // source-mode toggles.
        this._syncCoachReviewSideHeightFromBoard();
        if (this._coachBoardSizeObserver) {
            this._coachBoardSizeObserver.disconnect();
        }
        if (typeof ResizeObserver !== 'undefined') {
            // Observe the outer .coach-review-stage column so the sync
            // tracks the visible left-column height (pitch + status
            // row). Watching the inner board canvas would miss the
            // stage's intrinsic padding / status pill row and leave a
            // small gap below the inspector.
            const stageColumn = document.querySelector('#coach-tab-review .coach-review-stage');
            this._coachBoardSizeObserver = new ResizeObserver(() => {
                this._syncCoachReviewSideHeightFromBoard();
            });
            if (stageColumn) this._coachBoardSizeObserver.observe(stageColumn);
        }
    },

    _unmountCoachReviewBoard() {
        if (this._coachBoardSizeObserver) {
            this._coachBoardSizeObserver.disconnect();
            this._coachBoardSizeObserver = null;
        }
        // Clear the inline max-height we stamped on the aside so the
        // video-mode height sync starts from a clean slate when the
        // coach toggles back. (`_syncCoachReviewSideHeight` will set
        // it again from the video wrapper's rendered height.)
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (side) side.style.maxHeight = '';
        if (this._coachReviewBoardCtrl) {
            this._coachReviewBoardCtrl.destroy();
            this._coachReviewBoardCtrl = null;
        }
    },

    /** Render the observation composer fields into the side panel for
     *  Tactical Board mode. Mirrors the structured fields the modal
     *  observation composer offers, but lives inline (no nested modal)
     *  per the Phase 6d-1 UX rules. */
    _renderCoachTacticalBoardForm(container) {
        if (!container) return;
        const players = this._coachBundle?.players || [];
        container.innerHTML = `
            <input type="text" id="coach-tb-title" maxlength="160" placeholder="Title (optional)" aria-label="Observation title">
            <div class="coach-tb-row">
                <select id="coach-tb-category" aria-label="Category">
                    ${NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
                <select id="coach-tb-visibility" data-field="visibility" aria-label="Visibility">
                    ${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}
                </select>
            </div>
            <div id="coach-tb-tone" class="coach-review-tone" role="radiogroup" aria-label="Note tone">
                ${NOTE_TYPES.map(([v, l, glyph]) => `
                    <button type="button" class="coach-review-tone-btn${v === DEFAULT_NOTE_TYPE ? ' is-active' : ''}" role="radio" aria-checked="${v === DEFAULT_NOTE_TYPE}" tabindex="${v === DEFAULT_NOTE_TYPE ? '0' : '-1'}" data-note-type="${v}" title="${this.esc(l)}" onclick="app.setCoachTbNoteType('${v}')">
                        <span class="coach-review-tone-glyph" aria-hidden="true">${glyph}</span>
                        <span class="coach-review-tone-label">${this.esc(l)}</span>
                    </button>
                `).join('')}
            </div>
            <div class="coach-tb-section-label">Linked players</div>
            <div data-field="players" class="coach-check-list compact" role="listbox" aria-label="Linked players">
                ${this.coachCheckListHtml(players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet')}
            </div>
            <details class="coach-review-advanced">
                <summary>More details</summary>
                <div class="coach-review-advanced-body">
                    <label class="coach-review-field-label">
                        <span>Player summary <small>(visible to player/family)</small></span>
                        <textarea id="coach-tb-player-summary" rows="2" maxlength="2000" placeholder="Short, age-appropriate version they'll read."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What happened</span>
                        <textarea id="coach-tb-what-happened" rows="2" maxlength="2000" placeholder="The observation."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Why it matters</span>
                        <textarea id="coach-tb-why-it-matters" rows="2" maxlength="2000" placeholder="The coaching context."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>What to do next</span>
                        <textarea id="coach-tb-what-to-do-next" rows="2" maxlength="2000" placeholder="The actionable next step."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Coach context (private)</span>
                        <textarea id="coach-tb-coach-private-note" rows="2" maxlength="4000" placeholder="Internal — never sent to players or families."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Long notes</span>
                        <textarea id="coach-tb-body" rows="3" maxlength="4000" placeholder="Anything that doesn't fit the structured fields above."></textarea>
                    </label>
                    <label class="coach-review-field-label">
                        <span>Tags</span>
                        <input type="text" id="coach-tb-tags" maxlength="300" placeholder="tags,comma,separated">
                    </label>
                </div>
            </details>
        `;
        const toneEl = document.getElementById('coach-tb-tone');
        if (toneEl) {
            toneEl.dataset.value = DEFAULT_NOTE_TYPE;
            this._setupToneRadiogroup(toneEl);
        }
        // Track when the coach manually changes visibility so a routed
        // intent (from Roster) doesn't clobber their explicit choice.
        const visEl = document.getElementById('coach-tb-visibility');
        if (visEl) {
            visEl.addEventListener('change', () => { visEl.dataset.userTouched = '1'; });
        }
    },

    /** Tone-chip click target for the tactical-board side form. */
    setCoachTbNoteType(value) {
        const group = document.getElementById('coach-tb-tone');
        if (!group) return;
        this._syncToneRadiogroup(group, value);
    },

    /** Save Observation — Phase 6d-1 primary save action for Tactical
     *  Board mode. Reads structured fields from the inline side panel,
     *  pulls the current scene from the board controller, and POSTs to
     *  the existing observation endpoint. */
    async saveTacticalBoardObservation() {
        const ctrl = this._coachReviewBoardCtrl;
        if (!ctrl) { this.showError('Tactical board is not ready.'); return; }
        const scene = ctrl.hasContent() ? ctrl.scenePayload() : null;
        const title = (document.getElementById('coach-tb-title')?.value || '').trim();
        const eventTitle = (document.getElementById('coach-tb-event-title')?.value || '').trim();
        const eventDate = (document.getElementById('coach-tb-event-date')?.value || '').trim();
        const eventType = (document.getElementById('coach-tb-event-type')?.value || '').trim();
        const playerSummary = (document.getElementById('coach-tb-player-summary')?.value || '').trim();
        const whatHappened = (document.getElementById('coach-tb-what-happened')?.value || '').trim();
        const whyMatters = (document.getElementById('coach-tb-why-it-matters')?.value || '').trim();
        const whatNext = (document.getElementById('coach-tb-what-to-do-next')?.value || '').trim();
        const body = (document.getElementById('coach-tb-body')?.value || '').trim();
        const meaningful = title || eventTitle || playerSummary || whatHappened
            || whyMatters || whatNext || body || !!scene;
        if (!meaningful) {
            this.showError('Add a title, event title, some content, or a board sketch before saving.');
            return;
        }
        const noteType = document.getElementById('coach-tb-tone')?.dataset.value || DEFAULT_NOTE_TYPE;
        const playerIds = Array.from(document.querySelectorAll('#coach-tb-form [data-field="players"] .coach-check-option.is-selected'))
            .map((b) => b.dataset.value);
        const tags = ((document.getElementById('coach-tb-tags')?.value || '')
            .split(',').map((s) => s.trim()).filter(Boolean));
        const payload = {
            note_context: 'observation',
            title,
            event_title: eventTitle,
            event_date: eventDate,
            event_type: eventType,
            body,
            category: document.getElementById('coach-tb-category')?.value || 'other',
            visibility: document.getElementById('coach-tb-visibility')?.value || 'team',
            player_ids: playerIds,
            tags,
            note_type: noteType,
            player_summary: playerSummary,
            what_happened: whatHappened,
            why_it_matters: whyMatters,
            what_to_do_next: whatNext,
            coach_private_note: (document.getElementById('coach-tb-coach-private-note')?.value || '').trim(),
            tactical_board_json: scene,
        };
        try {
            await this.createCoachNote(payload);
            this.showSuccess('Observation saved.');
            // Reset per-moment fields. Keep visibility / category / tone /
            // selected players so the coach can save a related observation
            // with one more click.
            const PER_MOMENT_IDS = [
                'coach-tb-title', 'coach-tb-event-title', 'coach-tb-event-date',
                'coach-tb-player-summary', 'coach-tb-what-happened',
                'coach-tb-why-it-matters', 'coach-tb-what-to-do-next',
                'coach-tb-body', 'coach-tb-tags', 'coach-tb-coach-private-note',
            ];
            PER_MOMENT_IDS.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
            // Clear the board so the next observation starts blank.
            ctrl.loadScene(null);
            this._coachBundle = await this.loadCoachBundle();
        } catch (err) {
            this.showError(err.message);
        }
    },


    // ===== Sprint 6: Wide / Focus mode =====
    //
    // Toggle that hides page chrome + collapses the right inspector so the
    // video and drawing canvas use nearly the entire screen. Tools and
    // composer remain reachable via a slide-over inspector drawer triggered
    // from a small floating button. Escape exits. State is session-local
    // and resets when the user leaves the Review sub-tab.

    toggleCoachFocusMode() {
        if (this._coachFocusMode) this.exitCoachFocusMode();
        else this.enterCoachFocusMode();
    },

    enterCoachFocusMode() {
        if (this._coachFocusMode) return;
        this._coachFocusMode = true;
        this._coachFocusInspectorOpen = false;
        // Sprint 6 fix: snap the page to the top so the cockpit isn't
        // anchored to wherever the user happened to be scrolled (e.g. they
        // scrolled down to see the timeline rail). The fixed-position drawer
        // is viewport-relative, so a scrolled page would render the drawer
        // at the right edge of an ambiguous slice of the cockpit. Saving the
        // previous scroll position lets us restore it on exit.
        this._coachFocusPreviousScrollY = window.scrollY;
        window.scrollTo({ top: 0, behavior: 'instant' });
        const coachView = document.getElementById('coach-view');
        if (coachView) coachView.classList.add('is-focus-mode');
        document.body.classList.add('coach-focus-mode');  // for global overlays / scrollbar gutters
        const toggle = document.getElementById('coach-review-focus-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', 'true');
            toggle.classList.add('is-active');
        }
        // Close the drawer if it was somehow left open from a previous session.
        document.getElementById('coach-view')?.classList.remove('is-focus-drawer-open');
        // Bind Escape (capturing handler so it wins over <details>/canvas).
        this._coachFocusEscapeHandler = (event) => {
            if (event.key !== 'Escape') return;
            // Close the drawer first if it's open; otherwise exit focus mode.
            if (this._coachFocusInspectorOpen) {
                event.preventDefault();
                this.closeCoachFocusInspector();
                return;
            }
            event.preventDefault();
            this.exitCoachFocusMode();
        };
        // Capture phase so the handler runs before any descendant Escape
        // listener (e.g. the browser's default <details> toggle), matching
        // the comment above. Stored phase mirrored on removal in
        // exitCoachFocusMode for symmetry.
        window.addEventListener('keydown', this._coachFocusEscapeHandler, true);
        // The wrapper just changed size — re-sync canvas + inspector height.
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            requestAnimationFrame(() => {
                this._syncCoachReviewSideHeight(video);
                const canvas = document.getElementById(this._coachCanvasId);
                if (canvas) this._resizeCoachCanvas(canvas, video);
            });
        }
    },

    exitCoachFocusMode() {
        if (!this._coachFocusMode) return;
        // Close the inspector first so the side panel returns to its
        // original DOM parent before focus mode exits. closeCoachFocusInspector
        // is a no-op if the inspector wasn't mounted to body.
        this.closeCoachFocusInspector();
        this._coachFocusMode = false;
        this._coachFocusInspectorOpen = false;
        const coachView = document.getElementById('coach-view');
        if (coachView) {
            coachView.classList.remove('is-focus-mode');
            coachView.classList.remove('is-focus-drawer-open');
        }
        // Restore the page scroll position the user had before entering focus.
        if (typeof this._coachFocusPreviousScrollY === 'number') {
            requestAnimationFrame(() => {
                window.scrollTo({ top: this._coachFocusPreviousScrollY, behavior: 'instant' });
                this._coachFocusPreviousScrollY = null;
            });
        }
        document.body.classList.remove('coach-focus-mode');
        const toggle = document.getElementById('coach-review-focus-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', 'false');
            toggle.classList.remove('is-active');
        }
        if (this._coachFocusEscapeHandler) {
            window.removeEventListener('keydown', this._coachFocusEscapeHandler, true);
            this._coachFocusEscapeHandler = null;
        }
        // Re-sync canvas + inspector height for the restored layout.
        const video = document.getElementById(this._coachVideoId);
        if (video) {
            requestAnimationFrame(() => {
                this._syncCoachReviewSideHeight(video);
                const canvas = document.getElementById(this._coachCanvasId);
                if (canvas) this._resizeCoachCanvas(canvas, video);
            });
        }
    },

    openCoachFocusInspector() {
        if (!this._coachFocusMode) return;
        this._coachFocusInspectorOpen = true;
        document.getElementById('coach-view')?.classList.add('is-focus-drawer-open');
        // Body class lets the CSS target the side panel after it gets
        // re-parented to <body> below — bypasses the bounded stacking
        // context created by .coach-tab-panel's animation property.
        document.body.classList.add('coach-focus-drawer-open');
        const t = document.getElementById('coach-review-focus-inspector-toggle');
        if (t) t.setAttribute('aria-pressed', 'true');
        // Phase 6d-1 — in Tactical Board mode the pitch IS the work
        // surface. We still want the click-outside-closes-drawer
        // affordance, but a clicking the PITCH should ALSO be
        // received by the pitch's mousedown handler so the armed
        // tool drops a token / starts a drag in the same gesture.
        // Achieved by:
        //   * mounting the backdrop with `pointer-events: none` (CSS)
        //     so the pitch and picker bar still receive clicks
        //     (visual dim only), AND
        //   * binding a click-on-pitch listener that closes the
        //     drawer when a click lands on the pitch (mirroring the
        //     "tap outside to close" affordance without stealing the
        //     event from the pitch's own handlers).
        //
        // In Video mode the backdrop stays as the standard click-
        // outside-to-close — the video itself doesn't accept primary
        // clicks for note authoring (clicks go through the canvas
        // overlay / picker bar).
        let backdrop = document.getElementById('coach-focus-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'coach-focus-backdrop';
            backdrop.className = 'coach-focus-backdrop';
            backdrop.addEventListener('click', () => this.closeCoachFocusInspector());
            document.body.appendChild(backdrop);
        }
        backdrop.hidden = false;
        // TB-mode-only: bind a delegated mousedown listener to the
        // STABLE board-canvas wrapper (not the SVG itself, which gets
        // recreated on every controller refresh). When a click lands
        // on the pitch the listener closes the drawer; the pitch's
        // own controller handler runs in the same mousedown event
        // dispatch so the tool drops / starts a drag in one gesture.
        // The listener is stored so `closeCoachFocusInspector` can
        // remove it cleanly.
        if (this._coachReviewSource === 'tactical_board') {
            const canvasHost = document.getElementById('coach-review-board-canvas');
            if (canvasHost && !this._tbFocusCloseHandler) {
                this._tbFocusCloseHandler = () => {
                    if (this._coachFocusInspectorOpen) this.closeCoachFocusInspector();
                };
                canvasHost.addEventListener('mousedown', this._tbFocusCloseHandler, { passive: true });
                canvasHost.addEventListener('touchstart', this._tbFocusCloseHandler, { passive: true });
            }
            // Toggle a body class so the CSS can switch the backdrop
            // to `pointer-events: none` (keeps the dim overlay visual
            // but lets clicks pass through to the pitch).
            document.body.classList.add('coach-focus-drawer-tb-mode');
        } else {
            document.body.classList.remove('coach-focus-drawer-tb-mode');
        }
        // Move the inspector to <body> so it shares the root stacking context
        // with the backdrop. Without this, an ancestor with animation /
        // transform / filter (e.g. .coach-tab-panel's coachTabFade animation)
        // creates a bounded stacking context that traps the drawer's z-index
        // — the backdrop renders ABOVE the drawer and intercepts every click.
        const side = document.querySelector('.coach-review-side');
        if (side && !this._coachFocusSideOriginalParent) {
            this._coachFocusSideOriginalParent = side.parentElement;
            this._coachFocusSideOriginalNextSibling = side.nextSibling;
            // Sprint 6 fix: clear the inline `max-height` that Sprint 1's
            // _syncCoachReviewSideHeight set while the panel was inline in
            // the grid. That value (matched to the video wrapper height)
            // would clip the drawer's content vertically once the drawer's
            // own `bottom: 1rem` rule takes over. We save the inline value
            // and restore it on close.
            this._coachFocusSideOriginalMaxHeight = side.style.maxHeight;
            side.style.maxHeight = '';
            document.body.appendChild(side);
        }
        // Sprint 6: scroll the drawer to its top so the telestrator section is
        // visible. .coach-review-side carries a scrollTop value from when it
        // lived inline in the inspector column (Sprint 1 height-sync) — that
        // stale offset would crop the top tools out of view if not reset.
        if (side) {
            // requestAnimationFrame so layout settles after re-parenting before
            // we scroll.
            requestAnimationFrame(() => { side.scrollTop = 0; });
        }
    },

    closeCoachFocusInspector() {
        this._coachFocusInspectorOpen = false;
        document.getElementById('coach-view')?.classList.remove('is-focus-drawer-open');
        document.body.classList.remove('coach-focus-drawer-open');
        // Phase 6d-1 — clear the TB-mode pointer-events pass-through
        // marker AND remove the canvas-host mousedown listener so
        // the next open can re-bind cleanly. The handler is stored
        // on `_tbFocusCloseHandler` so we can remove it without
        // chasing element references through controller refreshes.
        document.body.classList.remove('coach-focus-drawer-tb-mode');
        if (this._tbFocusCloseHandler) {
            const canvasHost = document.getElementById('coach-review-board-canvas');
            if (canvasHost) {
                canvasHost.removeEventListener('mousedown', this._tbFocusCloseHandler);
                canvasHost.removeEventListener('touchstart', this._tbFocusCloseHandler);
            }
            this._tbFocusCloseHandler = null;
        }
        const t = document.getElementById('coach-review-focus-inspector-toggle');
        if (t) t.setAttribute('aria-pressed', 'false');
        const backdrop = document.getElementById('coach-focus-backdrop');
        if (backdrop) backdrop.hidden = true;
        // Restore the inspector to its original DOM position so the rest of
        // the layout (Sprint 1 height-sync ResizeObserver, the timeline rail
        // grid placement) keeps working when focus mode exits.
        const side = document.querySelector('.coach-review-side');
        if (side && this._coachFocusSideOriginalParent) {
            const parent = this._coachFocusSideOriginalParent;
            const next = this._coachFocusSideOriginalNextSibling;
            if (next && next.parentElement === parent) {
                parent.insertBefore(side, next);
            } else {
                parent.appendChild(side);
            }
            // Restore the inline max-height we cleared in openCoachFocusInspector
            // so Sprint 1's height-sync continues to work. _syncCoachReviewSideHeight
            // will overwrite it on the next resize regardless, but restoring here
            // keeps the layout from flickering at zero height for one frame.
            if (this._coachFocusSideOriginalMaxHeight !== undefined) {
                side.style.maxHeight = this._coachFocusSideOriginalMaxHeight;
                this._coachFocusSideOriginalMaxHeight = undefined;
            }
            this._coachFocusSideOriginalParent = null;
            this._coachFocusSideOriginalNextSibling = null;
        }
    },

    toggleCoachFocusInspector() {
        if (this._coachFocusInspectorOpen) this.closeCoachFocusInspector();
        else this.openCoachFocusInspector();
    },

    // ===== Sprint 7: Coach Review keyboard shortcuts =====
    //
    // Per the plan: scoped to Coach > Review only. Listener installed on
    // setCoachTab('review') and removed when leaving the sub-tab so other
    // surfaces (Roster, Notes, Playlists, Feedback, public match) are
    // unaffected. Skips while focus is in any text input / textarea /
    // select / contenteditable so typing isn't intercepted. Reuses
    // existing video methods (currentTime mutation, paused) and existing
    // tool / save methods so behavior stays consistent with mouse use.

    installCoachReviewShortcuts() {
        if (this._coachShortcutsHandler) return;  // already installed
        this._coachShortcutsHandler = (event) => this._handleCoachReviewShortcut(event);
        window.addEventListener('keydown', this._coachShortcutsHandler);
    },

    uninstallCoachReviewShortcuts() {
        if (!this._coachShortcutsHandler) return;
        window.removeEventListener('keydown', this._coachShortcutsHandler);
        this._coachShortcutsHandler = null;
    },

    _coachShortcutShouldSkip(event) {
        // Don't intercept when typing or operating a form control.
        const target = event.target;
        if (!target) return false;
        const tag = (target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
        if (target.isContentEditable) return true;
        // PR 1b: don't intercept while focus is inside the tone radiogroup
        // (Coach Review composer or the Notes-tab Edit modal). The video-
        // seek arrow shortcuts would otherwise scrub the video when a
        // keyboard user tabs into the chip group and presses arrow keys.
        // Full WAI-ARIA roving-tabindex / arrow-key cycling is a future
        // accessibility item; this guard just stops the conflict.
        if (target.closest && (
            target.closest('#coach-review-tone') ||
            target.closest('.coach-review-tone') ||
            target.closest('[role="radiogroup"]') ||
            target.closest('[role="radio"]')
        )) return true;
        // Don't fight other modifier-driven shortcuts (Cmd+S, Ctrl+R, …).
        if (event.metaKey || event.ctrlKey || event.altKey) return true;
        return false;
    },

    _handleCoachReviewShortcut(event) {
        if (this._coachShortcutShouldSkip(event)) return;
        // The Sprint 6 focus-mode Escape handler runs in the capture
        // phase, so it wins over this bubble-phase handler when active.
        // We still bind Escape here as a fallback for cancelling a
        // formation draft when focus mode is OFF. (Skip-typing guard
        // above already lets Escape pass through native input handling
        // when a form control is focused.)
        if (event.key === 'Escape' && !this._coachFocusMode) {
            if (this._coachFormationDraft) {
                event.preventDefault();
                this._coachFormationDraft = null;
                this._renderFormationControls?.();
                this.paintCoachCanvas?.();
            }
            return;
        }
        // Only intercept when the Review tab is actually showing.
        const reviewPanel = document.getElementById('coach-tab-review');
        if (!reviewPanel || reviewPanel.hidden) return;
        // Phase 6d-2 — tactical_board source mode owns its own keydown
        // handler (mountTacticalBoardReviewCanvas), which uses the SAME
        // letter shortcuts where they overlap (A / F / Z / T) plus the
        // tactical-only V / P / B / L. Returning early here keeps the
        // two handlers from double-firing AND prevents this handler
        // from hitting the video setCoachDrawingTool path (which would
        // try to paint on a non-existent video canvas in tactical mode).
        if (this._coachReviewSource === 'tactical_board' && event.key !== '?') return;
        const video = document.getElementById(this._coachVideoId);

        switch (event.key) {
            case ' ':
            case 'k':
                if (!video) return;
                event.preventDefault();
                if (video.paused) video.play().catch(() => {});
                else video.pause();
                return;
            case 'ArrowLeft':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.max(0, (video.currentTime || 0) - (event.shiftKey ? 10 : 1));
                return;
            case 'ArrowRight':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.min(video.duration || Infinity, (video.currentTime || 0) + (event.shiftKey ? 10 : 1));
                return;
            case 'j':
            case 'J':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.max(0, (video.currentTime || 0) - 5);
                return;
            case 'l':
            case 'L':
                if (!video) return;
                event.preventDefault();
                video.currentTime = Math.min(video.duration || Infinity, (video.currentTime || 0) + 5);
                return;
            case 's':
            case 'S':
                event.preventDefault();
                this.saveReviewNote();
                return;
            case 'a':
            case 'A':
                event.preventDefault();
                this.setCoachDrawingTool('arrow');
                return;
            case 'f':
            case 'F':
                event.preventDefault();
                this.setCoachDrawingTool('freehand');
                return;
            case 'z':
            case 'Z':
                event.preventDefault();
                this.setCoachDrawingTool('zone');
                return;
            case 'c':
            case 'C':
                event.preventDefault();
                this.setCoachDrawingTool('circle');
                return;
            case 't':
            case 'T':
                event.preventDefault();
                this.setCoachDrawingTool('label');
                return;
            case 'd':
            case 'D':
                // Per the plan: "D — Dim/spotlight tool, whichever is most useful".
                // Spotlight is the more interactive of the two (the dim is just
                // a global overlay), so favour it.
                event.preventDefault();
                this.setCoachDrawingTool('spotlight');
                return;
            case '?':
                // Toggle the shortcuts help popover. The plan asks for "a
                // small keyboard shortcuts help popover or tooltip".
                event.preventDefault();
                this.toggleCoachShortcutsHelp();
                return;
        }
    },

    toggleCoachShortcutsHelp() {
        const dialog = document.getElementById('coach-shortcuts-help');
        if (!dialog) return;
        const willOpen = dialog.hidden;
        dialog.hidden = !willOpen;
        // Keep the trigger button's aria-pressed in sync with the popover
        // state so screen readers correctly report whether help is showing.
        // Matches the pattern used by enterCoachFocusMode / setCoachDrawingTool
        // and is exercised by the Sprint 8 a11y audit.
        const toggle = document.getElementById('coach-review-shortcuts-toggle');
        if (toggle) toggle.setAttribute('aria-pressed', willOpen ? 'true' : 'false');
        // Phase 6d-1 — refresh the kbd list to match the active source
        // mode every time the popover opens, in case the source
        // changed since last open without firing _applyCoachReviewSource.
        if (willOpen) this._refreshCoachShortcutsHelpForSource(this._coachReviewSource);
    },

    /** Phase 6d-1 — populate the keyboard-shortcuts help popover with
     *  shortcuts relevant to the active source mode. Video mode keeps
     *  the existing video-scrubbing + telestrator shortcuts. Tactical
     *  Board mode (no video, no telestrator tools yet — those bind to
     *  the video keydown layer) shows only the universally-relevant
     *  shortcuts (Esc, ?) plus a note that mode-specific shortcuts
     *  arrive in Phase 6d-2. */
    _refreshCoachShortcutsHelpForSource(source) {
        const list = document.querySelector('#coach-shortcuts-help .coach-shortcuts-help-list');
        if (!list) return;
        const VIDEO_ITEMS = [
            ['<kbd>Space</kbd> / <kbd>K</kbd>', 'Play / pause'],
            ['<kbd>J</kbd> / <kbd>L</kbd>', 'Back / forward 5 s'],
            ['<kbd>←</kbd> / <kbd>→</kbd>', 'Back / forward 1 s'],
            ['<kbd>Shift</kbd>+<kbd>←</kbd> / <kbd>→</kbd>', 'Back / forward 10 s'],
            ['<kbd>S</kbd>', 'Save note at current time'],
            ['<kbd>A</kbd> <kbd>F</kbd> <kbd>Z</kbd> <kbd>C</kbd> <kbd>T</kbd> <kbd>D</kbd>', 'Arrow / Freehand / Zone / Circle / Label / Spotlight'],
            ['<kbd>Esc</kbd>', 'Exit focus mode'],
            ['<kbd>?</kbd>', 'Show / hide this help'],
        ];
        // Phase 6d-2 — tactical-board keyboard shortcuts. Shortcut
        // letters mirror the video telestrator's conventions where the
        // tools overlap (A / F / Z / T / V); tactical-only tools take
        // P (Player) / B (Ball) / L (Line). Bound in
        // mountTacticalBoardReviewCanvas's keydown handler, gated on
        // `body[data-coach-review-source="tactical_board"]`.
        const TB_ITEMS = [
            ['<kbd>V</kbd>', 'Select / move'],
            ['<kbd>P</kbd>', 'Player token'],
            ['<kbd>B</kbd>', 'Ball'],
            ['<kbd>A</kbd> / <kbd>1</kbd>', 'Arrow'],
            ['<kbd>L</kbd>', 'Line'],
            ['<kbd>Z</kbd>', 'Zone'],
            ['<kbd>F</kbd>', 'Pen / freehand'],
            ['<kbd>T</kbd>', 'Label / text'],
            ['<kbd>Delete</kbd> / <kbd>Backspace</kbd>', 'Delete the selected token or shape'],
            ['<kbd>Esc</kbd>', 'Clear selection or exit drawing tool'],
            ['<kbd>?</kbd>', 'Show / hide this help'],
        ];
        const items = source === 'tactical_board' ? TB_ITEMS : VIDEO_ITEMS;
        const note = '';
        list.innerHTML = items.map(([keys, label]) => `<li>${keys}<span>${this.esc(label)}</span></li>`).join('') + note;
    },

    // ===== Telestrator (operates on whichever canvas/video pair is current) =====

    renderCoachTelestratorToolbar() {
        // Sprint 3: icon-first toolbar grouped into three sections — drawing
        // tools, paint controls (color + width), and canvas/destructive
        // actions. Each tool button uses inline SVG (no font dependency)
        // plus a visually-hidden text label that re-appears on touch
        // devices via the pointer-aware CSS in styles.css. Every icon
        // button carries title + aria-label + aria-pressed so AT users
        // and tooltip hover stay first-class. Drawing payload, handler
        // names, and data-coach-tool values are unchanged so existing
        // saved drawings + click handlers keep working.
        const tools = [
            ['select',    'Select',         'Select / move objects',
                'M5 3l14 8-6 1.5L11 19z'],
            ['freehand',  'Freehand line',  'Freehand line',
                'M3 17c2-4 4-6 6-6s2 4 4 4 4-4 6-6'],
            ['arrow',     'Arrow',          'Arrow',
                'M4 12h13m-4-5l5 5-5 5'],
            ['circle',    'Circle',         'Circle',
                'M12 4a8 8 0 100 16 8 8 0 000-16z'],
            ['zone',      'Zone',           'Zone (dashed rectangle)',
                'M4 6h4M10 6h4M16 6h4M20 8v4M20 14v4M20 18h-4M14 18h-4M8 18H4M4 16v-4M4 10V6'],
            ['label',     'Label',          'Text label / player number',
                'M6 6h12M12 6v12'],
            ['spotlight', 'Spotlight',      'Spotlight (highlight one player)',
                'M12 4v3M12 17v3M4 12h3M17 12h3M6.3 6.3l2 2M15.7 15.7l2 2M6.3 17.7l2-2M15.7 8.3l2-2M12 9a3 3 0 100 6 3 3 0 000-6z'],
            ['dim',       'Dim',            'Dim the field',
                'M12 4a8 8 0 100 16 8 8 0 008-8 6 6 0 01-8-8z'],
            ['formation', 'Formation',      'Formation (multi-player highlight)',
                'M7 7a2 2 0 110 4 2 2 0 010-4zm10 0a2 2 0 110 4 2 2 0 010-4zM7 15a2 2 0 110 4 2 2 0 010-4zm10 0a2 2 0 110 4 2 2 0 010-4zM12 10a2 2 0 110 4 2 2 0 010-4z'],
        ];
        const colors = ['#38bdf8', '#f97316', '#22c55e', '#facc15', '#f43f5e', '#ffffff'];
        const colorNames = {
            '#38bdf8': 'Sky blue',
            '#f97316': 'Orange',
            '#22c55e': 'Green',
            '#facc15': 'Yellow',
            '#f43f5e': 'Red',
            '#ffffff': 'White',
        };
        const renderToolBtn = ([tool, label, tip, path]) => {
            const active = this._coachDrawingTool === tool;
            return `
                <button type="button"
                        data-coach-tool="${tool}"
                        class="coach-tool-btn ${active ? 'active' : ''}"
                        title="${tip}"
                        aria-label="${tip}"
                        aria-pressed="${active ? 'true' : 'false'}"
                        onclick="app.setCoachDrawingTool('${tool}')">
                    <svg class="coach-tool-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="${path}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span class="coach-tool-label">${label}</span>
                </button>
            `;
        };
        return `
            <div class="coach-telestrator" role="toolbar" aria-label="Telestrator tools">
                <div class="coach-tool-grid" role="group" aria-label="Drawing tools">
                    ${tools.map(renderToolBtn).join('')}
                </div>
                <div class="coach-tool-row" role="group" aria-label="Color and width">
                    ${colors.map((color) => {
                        const active = this._coachDrawingColor === color;
                        const name = colorNames[color] || color;
                        return `
                            <button type="button"
                                    data-coach-color="${color}"
                                    class="coach-color-swatch ${active ? 'active' : ''}"
                                    style="--swatch:${color}"
                                    title="${name}"
                                    aria-label="Color: ${name}"
                                    aria-pressed="${active ? 'true' : 'false'}"
                                    onclick="app.setCoachDrawingColor('${color}')"></button>
                        `;
                    }).join('')}
                    <label class="coach-width-control" title="Stroke width">
                        <span class="coach-width-label" aria-hidden="true">W</span>
                        <input type="range" min="2" max="10" value="${this._coachDrawingWidth}"
                               aria-label="Stroke width"
                               onchange="app.setCoachDrawingWidth(this.value)">
                    </label>
                </div>
                <input type="text" id="coach-label-text" maxlength="40" placeholder="Label / player number"
                       aria-label="Text label or player number for the next label drawing">
                <div id="coach-formation-controls" class="coach-formation-controls" hidden></div>
                <div class="coach-draw-actions" role="group" aria-label="Canvas actions">
                    <button type="button" data-coach-canvas-toggle
                            class="mini-action-btn"
                            aria-pressed="${this._coachDrawingActive ? 'true' : 'false'}"
                            onclick="app.toggleCoachDrawing()">Canvas ${this._coachDrawingActive ? 'On' : 'Off'}</button>
                    <button type="button" class="mini-action-btn"
                            title="Undo last object"
                            onclick="app.undoCoachDrawing()">Undo</button>
                    <button type="button" class="mini-action-btn"
                            title="Delete selected object"
                            onclick="app.deleteSelectedCoachObject()">Delete</button>
                    <button type="button" class="mini-action-btn btn-danger-soft"
                            title="Clear all drawings on this freeze frame"
                            onclick="app.clearCoachDrawing()">Clear</button>
                </div>
            </div>
        `;
    },

    setupCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        const video = document.getElementById(this._coachVideoId);
        if (!canvas || !video) return;
        if (canvas._coachBound) { this._resizeCoachCanvas(canvas, video); return; }
        const resize = () => {
            this._resizeCoachCanvas(canvas, video);
            // Sprint 2 polish: keep the inspector's max-height matched to the
            // video wrapper so the side panel and player are visually the same
            // height. Re-runs whenever the wrapper resizes (window or layout).
            this._syncCoachReviewSideHeight(video);
        };
        window.addEventListener('resize', resize);
        video.addEventListener('loadedmetadata', resize);
        // Sprint 1: the inspector is now independently scrollable, which means the
        // wrapper can change size without window resizing (e.g. inspector grows and
        // pushes the video column narrower). Observe the wrapper directly so the
        // canvas bitmap stays aligned with the rendered video.
        const wrapper = video.closest('.coach-review-wrapper, .feedback-player-wrapper');
        if (wrapper && typeof ResizeObserver === 'function') {
            const ro = new ResizeObserver(resize);
            ro.observe(wrapper);
            canvas._coachResizeObserver = ro;
        }
        canvas.addEventListener('pointerdown', (event) => this.coachDrawStart(event));
        canvas.addEventListener('pointermove', (event) => this.coachDrawMove(event));
        canvas.addEventListener('pointerup', (event) => this.coachDrawEnd(event));
        canvas.addEventListener('pointerleave', (event) => this.coachDrawEnd(event));
        canvas._coachBound = true;
        canvas._coachResize = resize;
        resize();
    },

    _resizeCoachCanvas(canvas, video) {
        const rect = video.getBoundingClientRect();
        canvas.width = Math.max(1, Math.round(rect.width));
        canvas.height = Math.max(1, Math.round(rect.height));
        this.paintCoachCanvas();
    },

    _syncCoachReviewSideHeight(video) {
        // Match the right inspector's max-height to the video wrapper's
        // current rendered height so they always look like sibling columns
        // of equal height. Only applies in Review mode; the feedback modal
        // doesn't need it. Skip on narrow viewports where the layout is
        // already single-column, and skip when the Review sub-tab isn't the
        // active one (the global resize handler in setCoachTab fires on every
        // tab — relying solely on null DOM lookups would still work today but
        // the explicit gate survives any future refactor of tab visibility).
        if (window.innerWidth < 1024) return;
        if (this._coachTab !== 'review') return;
        const wrapper = video.closest('.coach-review-wrapper');
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (!wrapper || !side) return;
        const h = Math.round(wrapper.getBoundingClientRect().height);
        if (h > 0) side.style.maxHeight = `${h}px`;
    },

    /** Phase 6d-2 follow-up — tactical-mode counterpart to
     *  `_syncCoachReviewSideHeight`. The `.coach-review-stage` column
     *  (which contains the pitch + status row) takes the same role
     *  the video wrapper plays in video mode: the right inspector's
     *  max-height is set to match the stage's current rendered height
     *  so the two columns are equal-height on every viewport, with no
     *  dead space at the bottom of either side.
     *
     *  We sync from the stage (`.coach-review-stage`) rather than the
     *  inner board canvas because the stage carries the pitch + the
     *  tiny status pill below it, and the user's expectation is that
     *  the inspector matches the visible LEFT column edge-to-edge.
     *
     *  Wired up at mount time via a ResizeObserver on the stage; the
     *  observer is cleaned up in `_unmountCoachReviewBoard`. */
    _syncCoachReviewSideHeightFromBoard() {
        if (this._coachTab !== 'review') return;
        if (this._coachReviewSource !== 'tactical_board') return;
        const side = document.querySelector('#coach-tab-review .coach-review-side');
        if (!side) return;
        // On narrow viewports the layout is single-column and there's
        // no separate side rail to clamp; clear any stale max-height
        // from a prior wide-viewport sync so the column stays its
        // natural size when the viewport is resized down.
        if (window.innerWidth < 1024) {
            if (side.style.maxHeight) side.style.maxHeight = '';
            return;
        }
        const stage = document.querySelector('#coach-tab-review .coach-review-stage');
        if (!stage) return;
        const h = Math.round(stage.getBoundingClientRect().height);
        if (h > 0) side.style.maxHeight = `${h}px`;
    },

    // Detach the global resize listener registered by setupCoachCanvas.
    // The Review tab's canvas is persistent in the DOM, so this is only
    // needed for the feedback player modal whose canvas is removed when
    // the modal closes — without this the closure stays attached to
    // window, leaking the canvas it captured.
    teardownCoachCanvasListeners(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !canvas._coachResize) return;
        window.removeEventListener('resize', canvas._coachResize);
        if (canvas._coachResizeObserver) {
            canvas._coachResizeObserver.disconnect();
            canvas._coachResizeObserver = null;
        }
        canvas._coachResize = null;
        canvas._coachBound = false;
    },

    activateCoachCanvas() {
        this.setupCoachCanvas();
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = true;
        canvas.style.display = 'block';
        canvas.style.pointerEvents = 'auto';
        this.updateCoachCanvasToggleLabel();
    },

    deactivateCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        this._coachDrawingActive = false;
        canvas.style.display = this._coachDrawing ? 'block' : 'none';
        canvas.style.pointerEvents = 'none';
        this.updateCoachCanvasToggleLabel();
    },

    updateCoachCanvasToggleLabel() {
        document.querySelectorAll('[data-coach-canvas-toggle]').forEach((btn) => {
            btn.textContent = `Canvas ${this._coachDrawingActive ? 'On' : 'Off'}`;
            btn.setAttribute('aria-pressed', this._coachDrawingActive ? 'true' : 'false');
        });
    },

    normalizeCoachDrawing(drawing) {
        if (!drawing) return null;
        if (drawing.version === 2 && Array.isArray(drawing.objects)) return { version: 2, objects: [...drawing.objects] };
        if (Array.isArray(drawing.strokes)) {
            return {
                version: 2,
                objects: drawing.strokes.map((stroke) => ({
                    type: 'freehand',
                    color: stroke.color || '#38bdf8',
                    width: stroke.width || 3,
                    points: stroke.points || [],
                })),
            };
        }
        return null;
    },

    ensureCoachDrawing() {
        if (!this._coachDrawing || this._coachDrawing.version !== 2) {
            this._coachDrawing = this.normalizeCoachDrawing(this._coachDrawing) || { version: 2, objects: [] };
        }
        if (!Array.isArray(this._coachDrawing.objects)) this._coachDrawing.objects = [];
        return this._coachDrawing;
    },

    toggleCoachDrawing() {
        if (this._coachDrawingActive) this.deactivateCoachCanvas();
        else this.activateCoachCanvas();
    },

    setCoachDrawingTool(tool) {
        // Switching away from formation mid-draft discards the in-progress
        // anchors; the user can restart by re-selecting Formation.
        if (this._coachDrawingTool === 'formation' && tool !== 'formation') {
            this._coachFormationDraft = null;
        }
        this._coachDrawingTool = tool;
        document.querySelectorAll('[data-coach-tool]').forEach((btn) => {
            const active = btn.dataset.coachTool === tool;
            btn.classList.toggle('active', active);
            // Sprint 3: keep aria-pressed in sync with the visual active
            // state so screen readers announce the toggle change without
            // re-rendering the toolbar.
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        this._renderFormationControls();
        this.activateCoachCanvas();
        this.paintCoachCanvas();
    },

    setCoachDrawingColor(color) {
        this._coachDrawingColor = color;
        document.querySelectorAll('[data-coach-color]').forEach((btn) => {
            const active = btn.dataset.coachColor === color;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    },

    setCoachDrawingWidth(width) {
        this._coachDrawingWidth = Math.max(2, Math.min(10, Number(width || 3)));
    },

    coachDrawPoint(event) {
        const canvas = document.getElementById(this._coachCanvasId);
        const rect = canvas.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) / Math.max(1, rect.width),
            y: (event.clientY - rect.top) / Math.max(1, rect.height),
        };
    },

    coachDrawStart(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const drawing = this.ensureCoachDrawing();
        const point = this.coachDrawPoint(event);
        if (this._coachDrawingTool === 'formation') {
            if (!this._coachFormationDraft) {
                this._coachFormationDraft = {
                    mode: this._coachFormationMode || 'quick',
                    anchors: [],
                    queuedPlayerIds: [],
                };
                this._renderFormationControls();
            }
            const draft = this._coachFormationDraft;
            if (draft.anchors.length >= 16) {
                this.showError?.('A formation can hold at most 16 players.');
                return;
            }
            const anchor = { x: point.x, y: point.y };
            if (draft.mode === 'linked' && draft.queuedPlayerIds.length) {
                const pid = draft.queuedPlayerIds.shift();
                const p = (this._coachBundle?.players || []).find((pl) => String(pl.id) === String(pid));
                if (p) {
                    anchor.player_id = String(p.id);
                    anchor.label = String(p.jersey_number || (p.display_name || '?').slice(0, 1)).toUpperCase().slice(0, 8);
                }
            }
            draft.anchors.push(anchor);
            this._renderFormationDraftPreview();
            return;
        }
        if (this._coachDrawingTool === 'select') {
            const index = this.hitCoachDrawingObject(point);
            this._coachSelectedObjectIndex = index;
            this._coachDragState = index === null ? null : { index, start: point };
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'label') {
            const text = document.getElementById('coach-label-text')?.value.trim() || 'Player';
            drawing.objects.push({ type: 'label', color: this._coachDrawingColor, x: point.x, y: point.y, text });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        if (this._coachDrawingTool === 'dim') {
            drawing.objects.push({ type: 'dim', opacity: 0.45 });
            this._coachSelectedObjectIndex = drawing.objects.length - 1;
            this.paintCoachCanvas();
            return;
        }
        let object = null;
        if (this._coachDrawingTool === 'freehand') {
            object = { type: 'freehand', color: this._coachDrawingColor, width: this._coachDrawingWidth, points: [point] };
        } else if (this._coachDrawingTool === 'arrow') {
            object = { type: 'arrow', color: this._coachDrawingColor, width: this._coachDrawingWidth, x1: point.x, y1: point.y, x2: point.x, y2: point.y };
        } else if (this._coachDrawingTool === 'spotlight') {
            object = { type: 'spotlight', color: this._coachDrawingColor, width: this._coachDrawingWidth,
                       x: Math.max(0, point.x - 0.08), y: Math.max(0, point.y - 0.08), w: 0.16, h: 0.16 };
        } else if (['circle', 'zone'].includes(this._coachDrawingTool)) {
            object = { type: this._coachDrawingTool, color: this._coachDrawingColor, width: this._coachDrawingWidth, x: point.x, y: point.y, w: 0.001, h: 0.001 };
        }
        if (!object) return;
        drawing.objects.push(object);
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._coachCurrentObject = { object, start: point };
        this.paintCoachCanvas();
    },

    coachDrawMove(event) {
        if (!this._coachDrawingActive) return;
        event.preventDefault();
        const point = this.coachDrawPoint(event);
        if (this._coachDragState) {
            const object = this._coachDrawing?.objects?.[this._coachDragState.index];
            if (object) {
                const dx = point.x - this._coachDragState.start.x;
                const dy = point.y - this._coachDragState.start.y;
                this.moveCoachDrawingObject(object, dx, dy);
                this._coachDragState.start = point;
            }
            this.paintCoachCanvas();
            return;
        }
        if (!this._coachCurrentObject) return;
        const { object, start } = this._coachCurrentObject;
        if (object.type === 'freehand') {
            object.points.push(point);
        } else if (object.type === 'arrow') {
            object.x2 = point.x;
            object.y2 = point.y;
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            const minSize = object.type === 'spotlight' ? 0.08 : 0.001;
            const w = Math.max(minSize, Math.abs(point.x - start.x));
            const h = Math.max(minSize, Math.abs(point.y - start.y));
            object.x = Math.min(start.x, point.x);
            object.y = Math.min(start.y, point.y);
            object.w = w;
            object.h = h;
        }
        this.paintCoachCanvas();
    },

    coachDrawEnd(event) {
        if (event?.target?.releasePointerCapture && event.pointerId !== undefined) {
            try { event.target.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
        }
        this._coachCurrentObject = null;
        this._coachDragState = null;
    },

    paintCoachCanvas() {
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const drawing = this.normalizeCoachDrawing(this._coachDrawing);
        const objects = drawing?.objects || [];
        objects.forEach((object, index) => {
            this.paintCoachObject(ctx, canvas, object);
            if (index === this._coachSelectedObjectIndex) this.paintCoachSelection(ctx, canvas, object);
        });
    },

    paintCoachObject(ctx, canvas, object) {
        const color = object.color || '#38bdf8';
        const width = object.width || 3;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        if (object.type === 'dim') {
            ctx.fillStyle = `rgba(0, 0, 0, ${object.opacity ?? 0.45})`;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else if (object.type === 'freehand') {
            ctx.beginPath();
            (object.points || []).forEach((pt, idx) => {
                const x = pt.x * canvas.width;
                const y = pt.y * canvas.height;
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
        } else if (object.type === 'arrow') {
            const x1 = object.x1 * canvas.width;
            const y1 = object.y1 * canvas.height;
            const x2 = object.x2 * canvas.width;
            const y2 = object.y2 * canvas.height;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
            const angle = Math.atan2(y2 - y1, x2 - x1);
            const head = 14 + width;
            ctx.beginPath();
            ctx.moveTo(x2, y2);
            ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
            ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
            ctx.closePath();
            ctx.fill();
        } else if (object.type === 'circle' || object.type === 'spotlight') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const w = object.w * canvas.width;
            const h = object.h * canvas.height;
            if (object.type === 'spotlight') {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.48)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                ctx.beginPath();
                ctx.ellipse(x + w / 2, y + h / 2, Math.max(8, w / 2), Math.max(8, h / 2), 0, 0, Math.PI * 2);
                ctx.fill();
                ctx.globalCompositeOperation = 'source-over';
                ctx.strokeStyle = color;
            }
            ctx.beginPath();
            ctx.ellipse(x + w / 2, y + h / 2, Math.max(4, w / 2), Math.max(4, h / 2), 0, 0, Math.PI * 2);
            ctx.stroke();
        } else if (object.type === 'zone') {
            ctx.strokeRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
            ctx.globalAlpha = 0.14;
            ctx.fillRect(object.x * canvas.width, object.y * canvas.height, object.w * canvas.width, object.h * canvas.height);
        } else if (object.type === 'label') {
            const x = object.x * canvas.width;
            const y = object.y * canvas.height;
            const text = object.text || 'Player';
            ctx.font = '700 18px system-ui, sans-serif';
            const metrics = ctx.measureText(text);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
            ctx.fillRect(x - 6, y - 22, metrics.width + 12, 28);
            ctx.fillStyle = color;
            ctx.fillText(text, x, y);
        } else if (object.type === 'formation') {
            const anchors = object.anchors || [];
            const hullPts = object.hull_points || [];
            // One dim layer per formation, then cut spotlight holes at every
            // anchor with destination-out (mirrors the existing `spotlight`
            // tool's pattern; stacking dims per-anchor would compound).
            if (anchors.length) {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.42)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.globalCompositeOperation = 'destination-out';
                anchors.forEach((a) => {
                    ctx.beginPath();
                    ctx.arc(a.x * canvas.width, a.y * canvas.height, 22, 0, Math.PI * 2);
                    ctx.fill();
                });
                ctx.globalCompositeOperation = 'source-over';
            }
            // Outline + label badge per anchor
            anchors.forEach((a, idx) => {
                const x = a.x * canvas.width, y = a.y * canvas.height;
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(x, y, 22, 0, Math.PI * 2);
                ctx.stroke();
                const label = (a.label && String(a.label)) || String(idx + 1);
                ctx.font = '700 12px system-ui, sans-serif';
                const m = ctx.measureText(label);
                ctx.fillStyle = 'rgba(0, 0, 0, 0.78)';
                ctx.fillRect(x - m.width / 2 - 5, y - 38, m.width + 10, 18);
                ctx.fillStyle = color;
                ctx.fillText(label, x - m.width / 2, y - 25);
            });
            // Convex hull polygon — translucent fill + crisp stroke
            if (hullPts.length >= 3) {
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                hullPts.forEach((p, idx) => {
                    const x = p.x * canvas.width, y = p.y * canvas.height;
                    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.save();
                ctx.globalAlpha = 0.18;
                ctx.fillStyle = color;
                ctx.fill();
                ctx.restore();
                ctx.stroke();
            }
        }
        ctx.restore();
    },

    paintCoachSelection(ctx, canvas, object) {
        const box = this.coachObjectBounds(object);
        if (!box) return;
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeRect(box.x * canvas.width, box.y * canvas.height, box.w * canvas.width, box.h * canvas.height);
        ctx.restore();
    },

    coachObjectBounds(object) {
        if (!object) return null;
        if (object.type === 'arrow') {
            const x = Math.min(object.x1, object.x2);
            const y = Math.min(object.y1, object.y2);
            return { x, y, w: Math.abs(object.x2 - object.x1) || 0.02, h: Math.abs(object.y2 - object.y1) || 0.02 };
        }
        if (['circle', 'zone', 'spotlight'].includes(object.type)) return { x: object.x, y: object.y, w: object.w, h: object.h };
        if (object.type === 'label') return { x: object.x, y: Math.max(0, object.y - 0.08), w: 0.12, h: 0.08 };
        if (object.type === 'freehand') {
            const points = object.points || [];
            if (!points.length) return null;
            const xs = points.map((p) => p.x);
            const ys = points.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.02, Math.max(...xs) - x), h: Math.max(0.02, Math.max(...ys) - y) };
        }
        if (object.type === 'dim') return { x: 0, y: 0, w: 1, h: 1 };
        if (object.type === 'formation') {
            const pts = (object.hull_points || []).concat(object.anchors || []);
            if (!pts.length) return null;
            const xs = pts.map((p) => p.x);
            const ys = pts.map((p) => p.y);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            return { x, y, w: Math.max(0.04, Math.max(...xs) - x), h: Math.max(0.04, Math.max(...ys) - y) };
        }
        return null;
    },

    hitCoachDrawingObject(point) {
        const objects = this._coachDrawing?.objects || [];
        for (let i = objects.length - 1; i >= 0; i -= 1) {
            const box = this.coachObjectBounds(objects[i]);
            if (!box) continue;
            const pad = 0.025;
            if (point.x >= box.x - pad && point.x <= box.x + box.w + pad &&
                point.y >= box.y - pad && point.y <= box.y + box.h + pad) {
                return i;
            }
        }
        return null;
    },

    moveCoachDrawingObject(object, dx, dy) {
        const clamp = (value) => Math.max(0, Math.min(1, value));
        if (object.type === 'freehand') {
            object.points = (object.points || []).map((pt) => ({ x: clamp(pt.x + dx), y: clamp(pt.y + dy) }));
        } else if (object.type === 'arrow') {
            object.x1 = clamp(object.x1 + dx); object.y1 = clamp(object.y1 + dy);
            object.x2 = clamp(object.x2 + dx); object.y2 = clamp(object.y2 + dy);
        } else if (['circle', 'zone', 'spotlight'].includes(object.type)) {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'label') {
            object.x = clamp(object.x + dx);
            object.y = clamp(object.y + dy);
        } else if (object.type === 'formation') {
            (object.anchors || []).forEach((a) => {
                a.x = clamp(a.x + dx);
                a.y = clamp(a.y + dy);
            });
            (object.hull_points || []).forEach((p) => {
                p.x = clamp(p.x + dx);
                p.y = clamp(p.y + dy);
            });
        }
    },

    undoCoachDrawing() {
        const drawing = this.ensureCoachDrawing();
        drawing.objects.pop();
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    deleteSelectedCoachObject() {
        const drawing = this.ensureCoachDrawing();
        if (this._coachSelectedObjectIndex === null || this._coachSelectedObjectIndex === undefined) return;
        drawing.objects.splice(this._coachSelectedObjectIndex, 1);
        this._coachSelectedObjectIndex = null;
        this.paintCoachCanvas();
    },

    clearCoachDrawing() {
        this._coachDrawing = null;
        this._coachSelectedObjectIndex = null;
        this._coachFormationDraft = null;
        this._renderFormationControls?.();
        this.deactivateCoachCanvas();
        this.paintCoachCanvas();
    },

    renderCoachDrawing(drawing) {
        this._coachDrawing = this.normalizeCoachDrawing(drawing);
        this._coachSelectedObjectIndex = null;
        const canvas = document.getElementById(this._coachCanvasId);
        if (canvas) canvas.style.display = this._coachDrawing ? 'block' : (this._coachDrawingActive ? 'block' : 'none');
        if (canvas) canvas.style.pointerEvents = this._coachDrawingActive ? 'auto' : 'none';
        this.setupCoachCanvas();
        const video = document.getElementById(this._coachVideoId);
        if (canvas && video) {
            const rect = video.getBoundingClientRect();
            canvas.width = Math.max(1, Math.round(rect.width));
            canvas.height = Math.max(1, Math.round(rect.height));
        }
        this.paintCoachCanvas();
    },

    // ===== Formation overlay (multi-player highlight + convex hull) =====

    setCoachFormationMode(mode) {
        this._coachFormationMode = (mode === 'linked') ? 'linked' : 'quick';
        if (this._coachFormationDraft) {
            this._coachFormationDraft.mode = this._coachFormationMode;
            // Switching mode discards any queued (unconsumed) player selections.
            this._coachFormationDraft.queuedPlayerIds = [];
        }
        this._renderFormationControls();
    },

    queueFormationPlayer(playerId) {
        if (!this._coachFormationDraft) {
            this._coachFormationDraft = { mode: this._coachFormationMode || 'quick', anchors: [], queuedPlayerIds: [] };
        }
        const id = String(playerId);
        const queue = this._coachFormationDraft.queuedPlayerIds;
        const at = queue.indexOf(id);
        if (at >= 0) queue.splice(at, 1); else queue.push(id);
        this._renderFormationControls();
    },

    cancelFormation() {
        this._coachFormationDraft = null;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    finalizeFormation() {
        const draft = this._coachFormationDraft;
        if (!draft || draft.anchors.length < 3) {
            this.showError?.('A formation needs at least 3 anchor points.');
            return;
        }
        const hull = this._computeConvexHull(draft.anchors);
        // Andrew's monotone-chain returns < 3 points only when every anchor
        // is collinear (the algorithm pops collinear interior points and
        // both endpoints). The painter and the backend validator both
        // require a 3+ point polygon, so reject early with a coach-readable
        // message instead of silently saving a hull-less formation.
        if (hull.length < 3) {
            this.showError?.('Formation anchors are collinear — nudge one off the line so the hull has area.');
            return;
        }
        const drawing = this.ensureCoachDrawing();
        drawing.objects.push({
            type: 'formation',
            color: this._coachDrawingColor,
            width: this._coachDrawingWidth,
            anchors: draft.anchors.map((a) => ({ ...a })),
            hull_points: hull,
        });
        this._coachFormationDraft = null;
        this._coachSelectedObjectIndex = drawing.objects.length - 1;
        this._renderFormationControls();
        this.paintCoachCanvas();
    },

    // Andrew's monotone-chain convex hull (counter-clockwise, no duplicates).
    // Inputs and outputs are normalized 0..1 {x, y} points.
    _computeConvexHull(points) {
        if (!Array.isArray(points) || points.length < 3) return points.slice();
        const pts = points.map((p) => ({ x: Number(p.x) || 0, y: Number(p.y) || 0 }))
            .sort((a, b) => (a.x - b.x) || (a.y - b.y));
        const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
        const lower = [];
        for (const p of pts) {
            while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
            lower.push(p);
        }
        const upper = [];
        for (let i = pts.length - 1; i >= 0; i -= 1) {
            const p = pts[i];
            while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
            upper.push(p);
        }
        upper.pop(); lower.pop();
        return lower.concat(upper);
    },

    // Repaint the in-progress draft on top of the existing canvas paint —
    // shows the user where they've clicked before they hit Done.
    _renderFormationDraftPreview() {
        this.paintCoachCanvas();
        const draft = this._coachFormationDraft;
        if (!draft || !draft.anchors.length) return;
        const canvas = document.getElementById(this._coachCanvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const color = this._coachDrawingColor || '#38bdf8';
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        draft.anchors.forEach((a, idx) => {
            const x = a.x * canvas.width, y = a.y * canvas.height;
            ctx.beginPath();
            ctx.arc(x, y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.font = '700 11px system-ui, sans-serif';
            ctx.fillText(a.label || String(idx + 1), x + 12, y - 6);
        });
        ctx.restore();
        this._renderFormationControls();
    },

    // Render the per-tool controls panel beneath the toolbar. Hidden when
    // any tool other than Formation is active.
    _renderFormationControls() {
        const el = document.getElementById('coach-formation-controls');
        if (!el) return;
        if (this._coachDrawingTool !== 'formation') {
            el.hidden = true;
            el.innerHTML = '';
            return;
        }
        el.hidden = false;
        const draft = this._coachFormationDraft;
        const anchorCount = draft?.anchors?.length || 0;
        const mode = this._coachFormationMode || 'quick';
        const players = this._coachBundle?.players || [];
        const queued = new Set((draft?.queuedPlayerIds || []).map(String));
        const queueOrderFor = (pid) => {
            const list = draft?.queuedPlayerIds || [];
            const at = list.findIndex((q) => String(q) === String(pid));
            return at >= 0 ? at + 1 : null;
        };
        const linkedRoster = mode === 'linked'
            ? `<div class="coach-formation-roster" role="listbox" aria-label="Players to anchor">
                 ${players.length
                    ? players.map((p) => {
                        const order = queueOrderFor(p.id);
                        const sel = queued.has(String(p.id));
                        return `<button type="button" class="coach-check-option ${sel ? 'is-selected' : ''}"
                                    aria-pressed="${sel}" onclick="app.queueFormationPlayer('${this.esc(p.id)}')">
                                    <span class="coach-check-box" aria-hidden="true">${order || ''}</span>
                                    <span class="coach-check-label">${this.esc(this.playerLabel(p))}</span>
                                </button>`;
                    }).join('')
                    : '<div class="coach-check-empty">No roster players yet.</div>'}
               </div>
               <p class="coach-formation-hint">Tap players in the order you want to place them, then click their position on the field.</p>`
            : '<p class="coach-formation-hint">Click each player’s position on the freeze frame, then press Done.</p>';
        el.innerHTML = `
            <div class="coach-formation-head">
                <strong>Formation</strong>
                <div class="coach-formation-modes" role="tablist">
                    <button type="button" role="tab" aria-selected="${mode === 'quick'}"
                        class="mini-action-btn ${mode === 'quick' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('quick')">Quick</button>
                    <button type="button" role="tab" aria-selected="${mode === 'linked'}"
                        class="mini-action-btn ${mode === 'linked' ? 'active' : ''}"
                        onclick="app.setCoachFormationMode('linked')">Linked</button>
                </div>
            </div>
            ${linkedRoster}
            <div class="coach-formation-actions">
                <span class="coach-formation-count">${anchorCount} anchor${anchorCount === 1 ? '' : 's'} (min 3, max 16)</span>
                <button type="button" class="mini-action-btn" onclick="app.cancelFormation()" ${draft ? '' : 'disabled'}>Cancel</button>
                <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.finalizeFormation()" ${anchorCount >= 3 ? '' : 'disabled'}>Done</button>
            </div>
        `;
    },

};
