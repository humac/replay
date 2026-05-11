// Coaching thumbnails domain mixin (PR-FE 5/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.
//
// Scope: per-coaching-note thumbnail composition (Phase 3) and
// per-coaching-clip thumbnail composition (Phase 4e). The actual
// fetch + blob URL machinery (loadCoachNoteThumbnail /
// loadCoachClipThumbnail / mountCoachNoteThumbnailsIn /
// mountCoachClipThumbnailsIn / regenerateCoachNoteThumbnail /
// regenerateCoachClipThumbnail) lives in js/api.js and is not
// duplicated here — these helpers compose the `<img
// data-coach-*-thumb>` placeholders that those mount helpers swap
// JPEGs into. The playlist thumbnail strip is in
// js/coaching/playlists.js (already migrated in step 4).

export const coachingThumbnailsMixin = {
    /** Phase 3b — render the thumbnail tile for a coaching note. The
     *  tile starts with a CSS placeholder background; the real JPEG is
     *  swapped in by `mountCoachNoteThumbnailsIn()` after auth-fetch.
     *
     *  Variants:
     *    `list`  — Notes-tab row tile (~120 × 68 px), shows time chip
     *    `chip`  — Coach Review timeline chip (smaller, 56 × 32 px)
     *    `card`  — Feedback card (full-width, 16:9, with time chip)
     *    `rail`  — playlist session rail strip (compact 80 × 45 px)
     *    `strip` — playlist row stacked tiles (very compact, no chip)
     */
    _coachNoteThumbHtml(note, { size = 'list' } = {}) {
        const id = Number(note?.id);
        if (!Number.isFinite(id) || id <= 0) return '';
        const sizeClass = `coach-thumb--${size}`;
        const ts = this.formatClock(note?.timestamp_seconds);
        // Time chip is helpful on the larger variants where it's
        // legible — skip on the timeline chip (which already shows the
        // timestamp on its label) and the rail strip (very small).
        const timeChip = (size === 'list' || size === 'card')
            ? `<span class="coach-thumb-time">${this.esc(ts)}</span>`
            : '';
        // `data-thumb-state="placeholder"` lets CSS pin the empty state
        // until the mount completes; on success the mount sets it to
        // `loaded` and the background-image is hidden.
        return `
            <div class="coach-thumb ${sizeClass}" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                <img class="coach-thumb-img" data-coach-note-thumb="${id}" alt="" loading="lazy" decoding="async">
                ${timeChip}
            </div>
        `;
    },

    /** Phase 3b — coach/admin "Regenerate thumbnail" action exposed on
     *  Coach Notes list rows. Useful when the source video was uploaded
     *  after the note was saved (the original best-effort spawn would
     *  have logged "no source MP4" and returned generated:false). */
    async handleRegenCoachThumb(noteId) {
        try {
            const result = await this.regenerateCoachNoteThumbnail(noteId);
            if (result?.generated) {
                this.showSuccess('Thumbnail regenerated.');
            } else {
                this.showInfo('Could not regenerate — source video may still be processing.');
            }
            // The regenerate call already invalidated the per-note cache
            // entry. Re-mount thumbnail placeholders in every currently
            // visible surface container so the freshly-generated JPEG
            // appears without a full view re-render.
            this._refreshCoachNoteThumbnailSurfaces();
        } catch (err) {
            this.showError(err.message);
        }
    },

    /** Phase 3b PR #92 review follow-up — remount any `<img
     *  data-coach-note-thumb>` placeholders inside the known thumbnail
     *  containers that are currently in the DOM. Each surface that
     *  isn't mounted (because the user is on a different tab) is a
     *  silent no-op via `mountCoachNoteThumbnailsIn`'s null-safe check.
     *
     *  Used after `regenerateCoachNoteThumbnail` so the new JPEG
     *  surfaces wherever it's already on screen. Does NOT trigger any
     *  re-render of the surrounding view, so DOM identities, focus
     *  state, scroll position, and the Coach Review video element are
     *  all preserved. */
    _refreshCoachNoteThumbnailSurfaces() {
        // Containers currently rendered with thumbnail tiles — each owns
        // one of the size variants from `_coachNoteThumbHtml` /
        // `_coachClipThumbHtml`. Despite the historical name, this
        // helper now refreshes BOTH note and clip thumbnail mounts for
        // every visible coaching surface so a regenerate hit on either
        // type lands wherever it's already on screen. The list is
        // intentionally hard-coded rather than discovered because each
        // container has a different lifecycle (e.g. the playlist
        // session rail lives inside a modal that may not be mounted).
        // A no-op `null` check covers each absent surface; the mount
        // helpers themselves are no-ops on a container with zero
        // matching `data-*` placeholders.
        const containerIds = [
            'coach-notes-list',                // Coach > Notes
            'coach-review-notes',              // Coach > Review timeline rail
            'coach-playlists-list',            // Coach > Playlists
            'coach-clips-list',                // Coach > Clips
            'feedback-notes-list',             // My Feedback > Notes
            'feedback-playlists-list',         // My Feedback > Playlists
            'feedback-clips-list',             // My Feedback > Clips
            // Phase 5b — also remount thumbnails inside the viewer
            // Development tab. Re-mounting both note + clip thumbnails
            // so a regenerate hit while Development is open surfaces
            // the new JPEG without forcing a tab re-render.
            'feedback-development-content',    // My Feedback > Development
        ];
        for (const id of containerIds) {
            const el = document.getElementById(id);
            if (el) {
                this.mountCoachNoteThumbnailsIn(el);
                // Clip thumbnails appear in Coach > Clips, My Feedback
                // > Clips, and the Development surfaces alongside notes.
                // The mount helper is itself a no-op for containers
                // without `<img data-coach-clip-thumb>` placeholders, so
                // the cost on notes-only containers is a single
                // `querySelectorAll` returning zero matches.
                this.mountCoachClipThumbnailsIn?.(el);
            }
        }
        // The focused-feedback player modal's session rail is not an
        // id-bound container — it's `[data-field="rail"]` inside a
        // cloned template. Look it up via the active player ref so we
        // don't accidentally pick up an unrelated `[data-field="rail"]`.
        const railEl = this._feedbackPlayer?.body?.querySelector?.('[data-field="rail"]');
        if (railEl) this.mountCoachNoteThumbnailsIn(railEl);
        // Phase 5b — the coach development modal mounts a transient
        // `.player-dev-modal-body` div that's re-created on each open.
        // It's not id-addressable, but we can find the live one by
        // class so a Coach > Notes regenerate refreshes the modal in
        // place when both happen to be open. Only one such body is
        // ever in the DOM at a time (the modal layer enforces this).
        const modalBody = document.querySelector('.player-dev-modal-body');
        if (modalBody) {
            this.mountCoachNoteThumbnailsIn(modalBody);
            this.mountCoachClipThumbnailsIn?.(modalBody);
        }
    },

    /** Render a thumbnail tile for a clip. Phase 4e adds first-class
     *  per-clip thumbnails generated from the source video at
     *  `start_seconds`, served from `GET /api/coach/clips/{id}/thumbnail`
     *  (visibility-checked per-viewer).
     *
     *  Resolution order (single `<img>` element with a fallback hint):
     *    1. clip thumbnail        — `data-coach-clip-thumb="<id>"`
     *    2. source-note thumbnail — `data-coach-note-thumb-fallback="<noteId>"`
     *       used when (1) returns null AND `clip.source_note_id` is set
     *    3. co-located note thumb — same fallback, derived from the
     *       client-side `notes[]` bundle when no explicit linkage exists
     *    4. placeholder           — both above failed; the
     *       `data-thumb-state="placeholder"` tile stays visible
     *
     *  `mountCoachClipThumbnailsIn` runs the chain in `js/api.js`. The
     *  thumbnail GETs each enforce `_can_view_coach_clip` /
     *  `_can_view_coach_note` server-side, so a viewer who can't see a
     *  private note or private clip never sees its thumbnail leak. */
    _coachClipThumbHtml(clip) {
        const clipId = Number(clip?.id);
        if (!Number.isFinite(clipId) || clipId <= 0) {
            return `
                <div class="coach-thumb coach-thumb--list" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                    <span class="coach-thumb-time">${this.esc(this.formatClock(clip?.start_seconds))}</span>
                </div>
            `;
        }
        // Pick the best note fallback: explicit `source_note_id` first,
        // then a co-located note from the user's bundle/feedback notes.
        let fallbackNoteId = Number(clip?.source_note_id);
        if (!Number.isFinite(fallbackNoteId) || fallbackNoteId <= 0) {
            const notes = this._coachBundle?.notes || this._feedbackData?.notes || [];
            const co = this._coLocatedNoteId(clip, notes);
            fallbackNoteId = Number.isFinite(co) && co > 0 ? co : 0;
        }
        const fallbackAttr = fallbackNoteId > 0
            ? ` data-coach-note-thumb-fallback="${fallbackNoteId}"`
            : '';
        return `
            <div class="coach-thumb coach-thumb--list" data-thumb data-thumb-state="placeholder" aria-hidden="true">
                <img class="coach-thumb-img" data-coach-clip-thumb="${clipId}"${fallbackAttr} alt="" loading="lazy" decoding="async">
                <span class="coach-thumb-time">${this.esc(this.formatClock(clip?.start_seconds))}</span>
            </div>
        `;
    },

    /** Find a note from `notes` that's most representative of the
     *  clip — same `match_id` / `slot`, `timestamp_seconds` inside
     *  `[start_seconds, end_seconds]`, closest to window midpoint
     *  when several match. Returns the note id or null. Used by
     *  `_coachClipThumbHtml` as a render-time thumbnail fallback for
     *  clips that have no explicit `source_note_id`. */
    _coLocatedNoteId(clip, notes) {
        if (!clip || !Array.isArray(notes) || !notes.length) return null;
        const matchId = clip.match_id;
        const slot = clip.slot || 'full';
        const start = Number(clip.start_seconds);
        const end = Number(clip.end_seconds);
        if (!matchId || !(end > start)) return null;
        const mid = (start + end) / 2;
        let best = null;
        let bestDelta = Infinity;
        for (const n of notes) {
            if (n.match_id !== matchId) continue;
            if ((n.slot || 'full') !== slot) continue;
            const ts = Number(n.timestamp_seconds);
            if (!Number.isFinite(ts)) continue;
            if (ts < start || ts > end) continue;
            const delta = Math.abs(ts - mid);
            if (delta < bestDelta) {
                best = Number(n.id);
                bestDelta = delta;
            }
        }
        return best;
    },
};
