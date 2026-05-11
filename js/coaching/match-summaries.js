// match summaries domain mixin for Phase 5.2 modular assembly.

import { VISIBILITY_OPTIONS } from '../coaching.js';

export const coachingMatchSummariesMixin = {
    _summaryVisibilityLabel(visibility) {
        return (VISIBILITY_OPTIONS.find(([v]) => v === visibility)?.[1]) || visibility || 'Private';
    },

    _summaryLinkedCounts(summary) {
        const bits = [];
        const noteCount = (summary?.note_ids || []).length;
        const clipCount = (summary?.clip_ids || []).length;
        const playlistCount = (summary?.playlist_ids || []).length;
        if (noteCount) bits.push(`${noteCount} note${noteCount === 1 ? '' : 's'}`);
        if (clipCount) bits.push(`${clipCount} clip${clipCount === 1 ? '' : 's'}`);
        if (playlistCount) bits.push(`${playlistCount} playlist${playlistCount === 1 ? '' : 's'}`);
        return bits.join(' · ');
    },

    _summarySectionData(summary, labels = {}) {
        return [
            [labels.team_positives || 'Positives', summary?.team_positives],
            [labels.team_improvements || 'Improve', summary?.team_improvements],
            [labels.training_focus || 'Training focus', summary?.training_focus],
            [labels.body || 'Coach recap', summary?.body],
        ].filter(([, value]) => (value || '').trim());
    },

    _summarySourceCount(summary) {
        return (summary?.note_ids || []).length + (summary?.clip_ids || []).length + (summary?.playlist_ids || []).length;
    },

    renderCoachMatchSummaries() {
        const list = document.getElementById('coach-summaries-list');
        if (!list) return;
        const summaries = this._coachBundle?.match_summaries || [];
        if (!summaries.length) {
            list.innerHTML = '<div class="session-empty">No match summaries yet. Add a team-visible recap after a match.</div>';
            return;
        }
        list.innerHTML = summaries.map((s) => {
            const sections = this._summarySectionData(s);
            const linked = this._summaryLinkedCounts(s);
            const sourceCount = this._summarySourceCount(s);
            return `
                <article class="coach-list-item" data-summary-id="${Number(s.id)}">
                    <div class="coach-list-main">
                        <div class="coach-summary-row-head">
                            <strong>${this.esc(this.matchLabel(s.match_id))}</strong>
                            <span class="coach-summary-meta">${this.esc(this._summaryVisibilityLabel(s.visibility))}${linked ? ` · ${this.esc(linked)}` : ''}</span>
                        </div>
                        <div class="coach-summary-preview" aria-label="Summary preview">
                            ${sections.slice(0, 3).map(([label, value]) => `
                                <section class="coach-summary-preview-section">
                                    <span class="coach-summary-preview-label">${this.esc(label)}</span>
                                    <p>${this.esc(value)}</p>
                                </section>`).join('')}
                        </div>
                        <span class="coach-summary-source-meta">${sourceCount ? `${sourceCount} linked source${sourceCount === 1 ? '' : 's'} · ` : ''}Edit to view full recap and evidence.</span>
                    </div>
                    <div class="coach-list-actions">
                        <button type="button" class="mini-action-btn" onclick="app.openCoachMatchSummaryModal(${Number(s.id)})">Edit</button>
                        <button type="button" class="mini-action-btn btn-danger-soft" onclick="app.handleCoachDeleteMatchSummary(${Number(s.id)})">Delete</button>
                    </div>
                </article>`;
        }).join('');
    },

    _renderSummaryChecklist(box, items, selectedIds, emptyLabel) {
        this.renderCoachCheckList(box, items, emptyLabel);
        const selected = new Set((selectedIds || []).map(String));
        box.querySelectorAll('.coach-check-option').forEach((btn) => {
            if (selected.has(btn.dataset.value)) {
                btn.classList.add('is-selected');
                btn.setAttribute('aria-pressed', 'true');
            }
        });
    },

    async openCoachMatchSummaryModal(summaryId = null) {
        const summary = summaryId ? (this._coachBundle?.match_summaries || []).find((s) => Number(s.id) === Number(summaryId)) : null;
        const body = document.createElement('div');
        body.className = 'coach-link-modal coach-summary-modal';
        const idPrefix = `coach-summary-${summary ? Number(summary.id) : 'new'}`;
        body.innerHTML = `
            <span class="admin-card-kicker">Match Summary</span>
            <h3>${summary ? 'Edit match summary' : 'New match summary'}</h3>
            <p class="admin-card-sub">Team-visible summaries appear in My Feedback. Linked private source notes/clips/playlists are filtered server-side and are never exposed to viewers.</p>
            <div class="coach-summary-form-card">
                <span class="coach-summary-form-kicker">Match &amp; visibility</span>
                <div class="form-row">
                    <div class="form-group"><label for="${idPrefix}-match">Match</label><select id="${idPrefix}-match" data-field="match"></select></div>
                    <div class="form-group"><label for="${idPrefix}-visibility">Visibility</label><select id="${idPrefix}-visibility" data-field="visibility">${VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></div>
                </div>
            </div>
            <div class="coach-summary-form-card">
                <span class="coach-summary-form-kicker">Team recap</span>
                <div class="form-group"><label for="${idPrefix}-team-positives">Team positives</label><textarea id="${idPrefix}-team-positives" data-field="team_positives" rows="3" maxlength="4000" placeholder="What went well as a team?"></textarea></div>
                <div class="form-group"><label for="${idPrefix}-team-improvements">Areas to improve</label><textarea id="${idPrefix}-team-improvements" data-field="team_improvements" rows="3" maxlength="4000" placeholder="What should we clean up next match?"></textarea></div>
                <div class="form-group"><label for="${idPrefix}-training-focus">Training focus</label><textarea id="${idPrefix}-training-focus" data-field="training_focus" rows="2" maxlength="2000" placeholder="Next practice focus"></textarea></div>
                <div class="form-group"><label for="${idPrefix}-body">Coach recap</label><textarea id="${idPrefix}-body" data-field="body" rows="4" maxlength="8000" placeholder="Optional full recap for the team"></textarea></div>
            </div>
            <details class="coach-summary-disclosure">
                <summary><span>Evidence</span><small>Link notes, clips, and playlists</small></summary>
                <div class="form-row coach-summary-evidence-grid">
                    <div class="form-group"><span id="${idPrefix}-notes-label" class="form-label-like">Notes</span><div data-field="notes" class="coach-check-list" role="group" aria-labelledby="${idPrefix}-notes-label"></div></div>
                    <div class="form-group"><span id="${idPrefix}-clips-label" class="form-label-like">Clips</span><div data-field="clips" class="coach-check-list" role="group" aria-labelledby="${idPrefix}-clips-label"></div></div>
                    <div class="form-group"><span id="${idPrefix}-playlists-label" class="form-label-like">Playlists</span><div data-field="playlists" class="coach-check-list" role="group" aria-labelledby="${idPrefix}-playlists-label"></div></div>
                </div>
            </details>`;
        const matchSel = body.querySelector('[data-field="match"]');
        matchSel.innerHTML = this.matches.map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('') || '<option value="">No matches yet</option>';
        if (summary) {
            matchSel.value = summary.match_id;
            matchSel.disabled = true;
            matchSel.title = 'Match cannot be changed after a summary is created.';
            matchSel.closest('.form-group')?.insertAdjacentHTML('beforeend', '<small class="form-help">Create a new summary to recap a different match.</small>');
        }
        body.querySelector('[data-field="visibility"]').value = summary?.visibility || 'private';
        ['team_positives', 'team_improvements', 'training_focus', 'body'].forEach((field) => {
            body.querySelector(`[data-field="${field}"]`).value = summary?.[field] || '';
        });
        const notes = (this._coachBundle?.notes || []).filter((n) => !summary || n.match_id === summary.match_id || (summary.note_ids || []).includes(n.id));
        const clips = (this._coachBundle?.clips || []).filter((c) => !summary || c.match_id === summary.match_id || (summary.clip_ids || []).includes(c.id));
        const playlists = this._coachBundle?.playlists || [];
        this._renderSummaryChecklist(body.querySelector('[data-field="notes"]'), notes.map((n) => ({ value: n.id, label: this.noteLabel(n) })), summary?.note_ids, 'No notes yet');
        this._renderSummaryChecklist(body.querySelector('[data-field="clips"]'), clips.map((c) => ({ value: c.id, label: `${this.formatClock(c.start_seconds)}-${this.formatClock(c.end_seconds)} · ${c.title}` })), summary?.clip_ids, 'No clips yet');
        this._renderSummaryChecklist(body.querySelector('[data-field="playlists"]'), playlists.map((p) => ({ value: p.id, label: p.title })), summary?.playlist_ids, 'No playlists yet');

        const result = await this.formModal({
            title: summary ? 'Edit Match Summary' : 'New Match Summary',
            kicker: 'Coaching',
            body,
            confirmLabel: summary ? 'Save changes' : 'Save summary',
            onSubmit: (close) => {
                const textFields = ['team_positives', 'team_improvements', 'training_focus', 'body'];
                const data = Object.fromEntries(textFields.map((f) => [f, body.querySelector(`[data-field="${f}"]`).value.trim()]));
                if (!Object.values(data).some(Boolean)) { this.showError('Add at least one summary field.'); return; }
                const matchId = body.querySelector('[data-field="match"]').value;
                if (!matchId) { this.showError('Match is required.'); return; }
                const selected = (field) => Array.from(body.querySelector(`[data-field="${field}"]`).querySelectorAll('.coach-check-option.is-selected')).map((b) => Number(b.dataset.value));
                close({
                    match_id: matchId,
                    visibility: body.querySelector('[data-field="visibility"]').value || 'private',
                    ...data,
                    note_ids: selected('notes'),
                    clip_ids: selected('clips'),
                    playlist_ids: selected('playlists'),
                });
            },
        });
        if (!result) return;
        try {
            if (summary) {
                const patchBody = { ...result };
                delete patchBody.match_id;
                await this.updateCoachMatchSummary(summary.id, patchBody);
            } else {
                await this.createCoachMatchSummary(result);
            }
            this.showSuccess(summary ? 'Match summary updated.' : 'Match summary saved.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteMatchSummary(summaryId) {
        const ok = await this.confirmAction({
            title: 'Delete match summary',
            message: 'Delete this match-level coaching summary?',
            confirmLabel: 'Delete summary',
            danger: true,
        });
        if (!ok) return;
        try {
            await this.deleteCoachMatchSummary(summaryId);
            this.showSuccess('Match summary deleted.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },
};
