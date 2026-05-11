// Coaching clips domain mixin (PR-FE 3/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.

import {
    NOTE_CATEGORIES,
    COACH_CLIP_DEFAULT_PRE_ROLL,
    COACH_CLIP_DEFAULT_POST_ROLL,
    COACH_CLIP_MAX_DURATION_SECONDS,
} from '../coaching.js';

export const coachingClipsMixin = {
    renderCoachClips() {
        const container = document.getElementById('coach-clips-list');
        if (!container) return;
        const clips = this._coachBundle?.clips || [];
        if (!clips.length) {
            container.innerHTML = '<div class="session-empty">No clips yet. Create one from the <strong>Review</strong> tab via <em>Save clip</em>, or click <strong>+ New clip</strong> above.</div>';
            return;
        }
        // Sort newest-first by updated_at so a coach who just edited
        // a clip's window or player tags sees it bubble to the top.
        const sorted = clips.slice().sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
        container.innerHTML = sorted.map((c) => {
            const playerCount = c.player_ids?.length || 0;
            const meta = [
                this.matchLabel(c.match_id),
                this.slotLabel(c.slot),
                `${this.formatClock(c.start_seconds)}–${this.formatClock(c.end_seconds)}`,
                `${this._clipDurationLabel(c)}`,
                this.esc(c.category),
                this.esc(c.visibility),
            ];
            if (playerCount) meta.push(`${playerCount} player${playerCount === 1 ? '' : 's'}`);
            const sourceBadge = c.source_note_id
                ? '<span class="coach-clip-source-pill" title="Created from a coaching note">From note</span>'
                : '';
            return `
            <article class="coach-row coach-row-with-thumb">
                ${this._coachClipThumbHtml(c)}
                <div class="coach-row-body">
                    <strong>${this.esc(c.title)}</strong>
                    <span>${meta.map((s) => this.esc(s)).join(' · ')} ${sourceBadge}</span>
                    ${c.description ? `<p>${this.esc(c.description)}</p>` : ''}
                </div>
                <div class="coach-row-actions">
                    <button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.previewCoachClip(${c.id})">Preview</button>
                    ${c.player_ids?.length ? `<button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ playerId: ${JSON.stringify(String(c.player_ids[0])).replace(/"/g, '&quot;')}, source: { source_clip_id: ${Number(c.id)}, title: ${JSON.stringify(c.title || 'Clip goal').replace(/"/g, '&quot;')}, description: ${JSON.stringify(c.description || '').replace(/"/g, '&quot;')}, label: ${JSON.stringify(c.title || 'Coaching clip').replace(/"/g, '&quot;')} } })">Create goal</button>` : ''}
                    <button type="button" class="mini-action-btn" onclick="app.openCoachClipModal(${c.id})">Edit</button>
                    <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteClip(${c.id})">Delete</button>
                </div>
            </article>
            `;
        }).join('');
        // Phase 4e: clip thumbnails first (per-clip JPEGs at start_seconds),
        // with `data-coach-note-thumb-fallback` providing the source-note /
        // co-located note as a render-time fallback for clips that haven't
        // been generated yet. `mountCoachClipThumbnailsIn` runs the chain.
        this.mountCoachClipThumbnailsIn(container);
    },

    /** Open the clip composer pre-filled from the Coach Review video's
     *  current time. If no video is loaded, surface a friendly error
     *  and bail — the coach has to pick a match first. */
    openClipComposerFromReview() {
        const review = this._coachReview;
        if (!review?.matchId) {
            this.showError('Pick a match in the Review tab before saving a clip.');
            return;
        }
        // Phase 4c (issue #100): metadata must be loaded before we
        // trust `currentTime` / `duration`. The `loadedmetadata`
        // listener in `loadCoachReviewVideo` flips `metadataReady`
        // to true; until then `currentTime` is 0 and pre-fill would
        // silently produce a [0, 8] window with no relation to what
        // the coach was watching. Surface a clear message instead.
        const video = document.getElementById(this._coachVideoId);
        const ready = review.metadataReady && video && Number.isFinite(video.duration) && video.duration > 0;
        if (!ready) {
            this.showError('Wait for the video to load before saving a clip.');
            return;
        }
        const t = Number(video.currentTime || 0);
        const start = Math.max(0, t - COACH_CLIP_DEFAULT_PRE_ROLL);
        const end = Math.max(start + 1, t + COACH_CLIP_DEFAULT_POST_ROLL);
        // Cap at the MVP duration ceiling so the pre-fill always
        // produces a server-acceptable window.
        const capped_end = Math.min(end, start + COACH_CLIP_MAX_DURATION_SECONDS);
        // Also cap end at the video's duration so a clip near the
        // end of the match doesn't suggest a timestamp past EOS.
        const safe_end = Math.min(capped_end, video.duration);
        // Issue #104: clip thumbnails reuse the source note's thumbnail,
        // but the composer never set `source_note_id` so every saved
        // clip rendered as a placeholder tile. Derive a candidate source
        // note here when the coach is clearly working off a moment:
        //   1) prefer the explicitly-active timeline chip (set when the
        //      coach clicks a note in Coach Review),
        //   2) otherwise pick the same-match/same-slot note whose
        //      `timestamp_seconds` falls inside the [start, end] window.
        // The candidate is a hint — the composer renders a "From note
        // #N" pill so the coach can confirm or clear it before saving.
        const sourceNoteId = this._deriveClipSourceNoteId(
            review.matchId, review.slot || 'full', start, safe_end,
        );
        this.openCoachClipModal(null, {
            match_id: review.matchId,
            slot: review.slot || 'full',
            start_seconds: Number(start.toFixed(1)),
            end_seconds: Number(safe_end.toFixed(1)),
            source_note_id: sourceNoteId,
        });
    },

    /** Pick a source note for a new clip when the coach is clearly
     *  working off a specific moment. Returns the note id or null.
     *  Order of preference:
     *    1. The active timeline chip in Coach Review (`_coachActiveNoteId`).
     *    2. A note on the same `match_id`/`slot` whose
     *       `timestamp_seconds` falls inside `[start, end]`. When
     *       multiple notes match, pick the one closest to the window
     *       midpoint (most representative frame).
     *  Returns null when no plausible source note exists — the clip
     *  will then render the placeholder tile, which is the correct
     *  degraded state. */
    _deriveClipSourceNoteId(matchId, slot, start, end) {
        const notes = this._coachBundle?.notes || [];
        if (!matchId || !notes.length) return null;
        // Prefer the explicitly-selected note when it matches the clip's
        // match/slot. A coach who clicked a chip and then "Save Clip"
        // expects that note to drive the clip.
        if (this._coachActiveNoteId) {
            const active = notes.find((n) => Number(n.id) === Number(this._coachActiveNoteId));
            if (active && active.match_id === matchId && (active.slot || 'full') === slot) {
                return Number(active.id);
            }
        }
        // Fall through to the same co-located picker the render-time
        // fallback uses, so the linkage logic has one source of truth.
        return this._coLocatedNoteId({
            match_id: matchId, slot, start_seconds: start, end_seconds: end,
        }, notes);
    },

    /** Mount the clip composer modal. `clipId === null` is the create
     *  flow; `seed` is an optional set of pre-filled fields used by
     *  `openClipComposerFromReview`. */
    async openCoachClipModal(clipId = null, seed = null) {
        const clip = clipId ? (this._coachBundle?.clips || []).find((c) => Number(c.id) === Number(clipId)) : null;
        const tpl = document.getElementById('coach-clip-form-template');
        if (!tpl) { this.showError('Clip form template missing.'); return; }
        const body = tpl.content.firstElementChild.cloneNode(true);

        // Match select — same option set as the note composer modal.
        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        const initialMatchId = clip?.match_id || seed?.match_id || (this.matches[0]?.id || '');
        matchSel.value = initialMatchId;

        const slotSel = body.querySelector('[data-field="slot"]');
        slotSel.value = clip?.slot || seed?.slot || 'full';

        // PR #96 review fix: on EDIT, disable Match + Slot. The
        // backend's `UpdateCoachingClipRequest` is `extra="forbid"` and
        // the previous PATCH path silently stripped these fields,
        // causing the coach's edits to disappear without explanation.
        // Disabling the controls makes the constraint visible. Both
        // the visual class and `aria-disabled` keep the controls in
        // tab order with focus rings (`disabled` would also block them
        // — that's the right behavior here, since changes are not
        // accepted by the server). On CREATE the controls stay
        // editable as before.
        if (clip) {
            matchSel.disabled = true;
            slotSel.disabled = true;
            // Append a tiny "fixed on edit" hint so the coach knows
            // why these dropdowns are greyed out without having to
            // experiment.
            const matchHint = matchSel.parentElement;
            const slotHint = slotSel.parentElement;
            const fixedNote = document.createElement('span');
            fixedNote.className = 'coach-clip-field-hint';
            fixedNote.textContent = 'Fixed on edit — create a new clip to change.';
            if (matchHint && !matchHint.querySelector('.coach-clip-field-hint')) {
                matchHint.appendChild(fixedNote);
            }
            // The slot dropdown gets its own copy via cloneNode so
            // both fields are equally explanatory; one node would only
            // attach to the first parent.
            if (slotHint && !slotHint.querySelector('.coach-clip-field-hint')) {
                slotHint.appendChild(fixedNote.cloneNode(true));
            }
        }

        body.querySelector('[data-field="title"]').value = clip?.title || '';
        body.querySelector('[data-field="visibility"]').value = clip?.visibility || 'private';
        body.querySelector('[data-field="description"]').value = clip?.description || '';

        // Category select — pull from NOTE_CATEGORIES so the vocabulary
        // is identical to notes / playlists.
        const categorySel = body.querySelector('[data-field="category"]');
        categorySel.innerHTML = NOTE_CATEGORIES.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('');
        categorySel.value = clip?.category || 'other';

        // Window numeric inputs — formatted to one decimal so a coach
        // can type 12.5 without the input rounding to whole seconds.
        const startEl = body.querySelector('[data-field="startSeconds"]');
        const endEl = body.querySelector('[data-field="endSeconds"]');
        startEl.value = Number(clip?.start_seconds ?? seed?.start_seconds ?? 0).toFixed(1);
        endEl.value = Number(clip?.end_seconds ?? seed?.end_seconds ?? 10).toFixed(1);

        // Live duration label — recompute on every input edit so the
        // coach sees instantly when the window violates the cap.
        const durationEl = body.querySelector('[data-field="durationDisplay"]');
        const refreshDuration = () => {
            const start = Number(startEl.value || 0);
            const end = Number(endEl.value || 0);
            const dur = Math.max(0, end - start);
            const mins = Math.floor(dur / 60);
            const secs = Math.round(dur % 60);
            durationEl.textContent = `${mins}:${String(secs).padStart(2, '0')}`;
            durationEl.classList.toggle('coach-clip-duration--invalid',
                dur <= 0 || dur > COACH_CLIP_MAX_DURATION_SECONDS);
        };
        startEl.addEventListener('input', refreshDuration);
        endEl.addEventListener('input', refreshDuration);
        refreshDuration();

        // Player check-list — same primitive as notes / playlists.
        const playersBox = body.querySelector('[data-field="players"]');
        const players = this._coachBundle?.players || [];
        this.renderCoachCheckList(playersBox, players.map((p) => ({ value: p.id, label: this.playerLabel(p) })), 'No players yet');
        const initialPlayerIds = clip?.player_ids || seed?.player_ids || [];
        if (initialPlayerIds.length) {
            const sel = new Set(initialPlayerIds.map(String));
            playersBox.querySelectorAll('.coach-check-option').forEach((btn) => {
                if (sel.has(btn.dataset.value)) {
                    btn.classList.add('is-selected');
                    btn.setAttribute('aria-pressed', 'true');
                }
            });
        }

        // Source-note pill — show on EDIT when the clip was created
        // from a note, OR on CREATE when `openClipComposerFromReview`
        // pre-derived a candidate source note (issue #104). On edit
        // `source_note_id` is intentionally NOT editable (rebinding
        // would silently swap the saved drawing snapshot — see
        // `db.update_coaching_clip`'s docstring). On create the coach
        // can simply not save with the candidate (the field is hidden
        // on the form; it's a hint, not a control).
        const seedSourceNoteId = Number(seed?.source_note_id) || null;
        const effectiveSourceNoteId = clip?.source_note_id || seedSourceNoteId || null;
        if (effectiveSourceNoteId) {
            const sourceRow = body.querySelector('[data-field="sourceRow"]');
            const sourceLabel = body.querySelector('[data-field="sourceLabel"]');
            sourceRow.hidden = false;
            sourceLabel.textContent = `From note #${effectiveSourceNoteId}`;
        }

        const result = await this.formModal({
            title: clip ? 'Edit Coaching Clip' : 'New Coaching Clip',
            kicker: 'Coaching',
            body,
            confirmLabel: clip ? 'Save changes' : 'Save clip',
            onSubmit: (close) => {
                const root = body;
                const titleVal = root.querySelector('[data-field="title"]').value.trim();
                if (!titleVal) { this.showError('Clip title is required.'); return; }
                const matchVal = root.querySelector('[data-field="match"]').value;
                if (!matchVal) { this.showError('Match is required.'); return; }
                const start = Number(root.querySelector('[data-field="startSeconds"]').value || 0);
                const end = Number(root.querySelector('[data-field="endSeconds"]').value || 0);
                if (!(end > start)) { this.showError('End time must be greater than start time.'); return; }
                if ((end - start) > COACH_CLIP_MAX_DURATION_SECONDS) {
                    this.showError(`Clip duration must be ${COACH_CLIP_MAX_DURATION_SECONDS} seconds or less.`);
                    return;
                }
                const out = {
                    match_id: matchVal,
                    slot: root.querySelector('[data-field="slot"]').value || 'full',
                    start_seconds: start,
                    end_seconds: end,
                    title: titleVal,
                    description: root.querySelector('[data-field="description"]').value.trim(),
                    category: root.querySelector('[data-field="category"]').value || 'other',
                    visibility: root.querySelector('[data-field="visibility"]').value || 'private',
                    player_ids: Array.from(root.querySelector('[data-field="players"]').querySelectorAll('.coach-check-option.is-selected')).map((b) => b.dataset.value),
                };
                // Issue #104: only include `source_note_id` on CREATE
                // when the seed pre-derived one. On EDIT we never
                // re-emit it (the backend's `UpdateCoachingClipRequest`
                // is `extra="forbid"` and rebinding mid-life would
                // silently swap the captured drawing snapshot).
                if (!clip && seedSourceNoteId) {
                    out.source_note_id = seedSourceNoteId;
                }
                close(out);
            },
        });
        if (!result) return;
        try {
            if (clip) {
                // PATCH only the fields a coach can actually edit on
                // an existing clip. `match_id` and `slot` are NOT in
                // the backend's `UpdateCoachingClipRequest` allowed
                // set, so we filter them out client-side too — server
                // would 422 on `extra="forbid"` otherwise.
                const patchBody = { ...result };
                delete patchBody.match_id;
                delete patchBody.slot;
                await this.updateCoachClip(clip.id, patchBody);
            } else {
                await this.createCoachClip(result);
            }
            this.showSuccess(clip ? 'Clip updated.' : 'Clip created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteClip(clipId) {
        const ok = await this.confirmAction({
            title: 'Delete clip', message: 'Delete this coaching clip?',
            confirmLabel: 'Delete clip', danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachClip(clipId);
            await this.renderCoachWorkspace();
            this.showSuccess('Clip deleted.');
        } catch (err) { this.showError(err.message); }
    },

    /** Coach-side preview opens the focused feedback player in clip
     *  mode. Reuses the same modal + canvas + heartbeat as note /
     *  playlist preview. */
    previewCoachClip(clipId) {
        const clip = (this._coachBundle?.clips || []).find((c) => Number(c.id) === Number(clipId));
        if (!clip) return;
        this.openFeedbackPlayer({ mode: 'clip', clip, playerSource: 'coach' });
    },
};
