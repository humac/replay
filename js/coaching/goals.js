// Coaching player goals domain mixin (PR-FE 7/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.

import {
    GOAL_STATUS_OPTIONS,
    GOAL_STATUS_LABELS,
    GOAL_CONTEXT_OPTIONS,
    GOAL_CONTEXT_LABELS,
    GOAL_VISIBILITY_OPTIONS,
    GOAL_VISIBILITY_LABELS,
    GOAL_PRIORITY_OPTIONS,
    GOAL_PRIORITY_LABELS,
    ACTIVE_GOAL_STATUSES,
} from '../coaching.js';

export const coachingGoalsMixin = {
    _goalPlayer(goal) {
        return (this._coachBundle?.players || this._feedbackData?.players || [])
            .find((p) => String(p.id) === String(goal?.player_id));
    },

    _goalStatusLabel(status) { return GOAL_STATUS_LABELS[status] || status || 'Open'; },
    _goalContextLabel(context) { return GOAL_CONTEXT_LABELS[context] || context || 'Goal'; },
    _goalVisibilityLabel(visibility) { return GOAL_VISIBILITY_LABELS[visibility] || visibility || 'Player/family'; },
    _goalPriorityLabel(priority) { return GOAL_PRIORITY_LABELS[priority] || priority || 'Medium'; },

    _goalSourceSummary(goal) {
        if (goal?.source_note) {
            const n = goal.source_note;
            const title = (n.title || n.event_title || n.player_summary || n.body || 'Coaching note').trim();
            return { label: 'Source note', text: title, kind: 'note' };
        }
        if (goal?.source_clip) return { label: 'Source clip', text: goal.source_clip.title || 'Coaching clip', kind: 'clip' };
        if (goal?.source_playlist) return { label: 'Source playlist', text: goal.source_playlist.title || 'Review playlist', kind: 'playlist' };
        return null;
    },

    _renderGoalCard(goal, { viewer = false, actions = true } = {}) {
        const player = this._goalPlayer(goal);
        const source = this._goalSourceSummary(goal);
        const reflections = goal.reflections || [];
        const latest = goal.latest_reflection || reflections[0] || null;
        const status = goal.status || 'open';
        const active = ACTIVE_GOAL_STATUSES.has(status);
        const coachMeta = !viewer ? [
            this._goalVisibilityLabel(goal.visibility || 'player'),
            `${this._goalPriorityLabel(goal.priority || 'medium')} priority`,
            goal.target_date ? `Target ${this.formatDate(goal.target_date)}` : '',
        ].filter(Boolean).join(' · ') : '';
        return `
            <article class="player-goal-card${active ? '' : ' is-muted'}" data-goal-id="${Number(goal.id)}">
                <div class="player-goal-card-head">
                    <div class="player-goal-card-title">
                        <span class="player-goal-kicker">${this.esc(this._goalContextLabel(goal.context))}${player && !viewer ? ` · ${this.esc(this.playerLabel(player))}` : ''}</span>
                        <h4>${this.esc(goal.title || 'Player goal')}</h4>
                        ${coachMeta ? `<span class="player-goal-meta">${this.esc(coachMeta)}</span>` : ''}
                    </div>
                    <span class="player-goal-status" data-status="${this.esc(status)}">${this.esc(this._goalStatusLabel(status))}</span>
                </div>
                ${goal.description ? `<div class="player-goal-preview-block"><span>Action plan</span><p class="player-goal-desc">${this.esc(goal.description)}</p></div>` : ''}
                ${goal.success_criteria ? `<div class="player-goal-preview-block"><span>Success criteria</span><p class="player-goal-desc">${this.esc(goal.success_criteria)}</p></div>` : ''}
                ${!viewer && goal.coach_private_note ? `<div class="player-goal-preview-block player-goal-private-note"><span>Coach private note</span><p class="player-goal-desc">${this.esc(goal.coach_private_note)}</p></div>` : ''}
                ${source ? `<div class="player-goal-source"><span>${this.esc(source.label)}</span><strong>${this.esc(source.text)}</strong></div>` : ''}
                ${latest ? `<div class="player-goal-reflection"><span>Latest reflection</span><p>${this.esc(latest.reflection || '')}</p></div>` : ''}
                ${actions ? `<div class="player-goal-actions">
                    ${viewer ? `<button type="button" class="mini-action-btn mini-action-btn-primary" onclick="app.openGoalReflectionModal(${Number(goal.id)})">Add reflection</button>` : `
                        <select class="player-goal-status-select" aria-label="Goal status" onchange="app.handleCoachGoalStatus(${Number(goal.id)}, this.value)">
                            ${GOAL_STATUS_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === status ? 'selected' : ''}>${this.esc(l)}</option>`).join('')}
                        </select>
                        <button type="button" class="mini-action-btn" onclick="app.openCoachGoalModal({ goalId: ${Number(goal.id)} })">Edit</button>
                        <button type="button" class="mini-action-btn" onclick="app.handleCoachDeleteGoal(${Number(goal.id)})">Delete</button>`}
                </div>` : ''}
            </article>`;
    },

    async openCoachGoalModal({ goalId = null, playerId = null, source = null } = {}) {
        if (!this.canCoach()) return;
        const goal = goalId ? (this._coachBundle?.goals || []).find((g) => Number(g.id) === Number(goalId)) : null;
        const players = this._coachBundle?.players || [];
        const body = document.createElement('div');
        body.className = 'coach-mini-form player-goal-form';
        body.innerHTML = `
            <div class="form-grid two">
                <label>Player<select data-field="player_id" ${goal ? 'disabled' : ''}>${players.map((p) => `<option value="${this.esc(p.id)}">${this.esc(this.playerLabel(p))}</option>`).join('')}</select></label>
                <label>Context<select data-field="context">${GOAL_CONTEXT_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
            </div>
            <div class="form-grid two">
                <label>Visibility<select data-field="visibility">${GOAL_VISIBILITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
                <label>Priority<select data-field="priority">${GOAL_PRIORITY_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
            </div>
            <label>Goal title<input type="text" data-field="title" maxlength="160" placeholder="Scan before receiving"></label>
            <label>Action plan<textarea data-field="description" rows="4" maxlength="2000" placeholder="What should the player try next?"></textarea></label>
            <div class="form-grid two">
                <label>Status<select data-field="status">${GOAL_STATUS_OPTIONS.map(([v, l]) => `<option value="${v}">${this.esc(l)}</option>`).join('')}</select></label>
                <label>Target date<input type="date" data-field="target_date"></label>
            </div>
            <label>Success criteria<textarea data-field="success_criteria" rows="3" maxlength="2000" placeholder="How will we know this goal is working?"></textarea></label>
            <label>Coach private note, not visible to family/player<textarea data-field="coach_private_note" rows="3" maxlength="2000" placeholder="Internal coaching context"></textarea></label>
            <label>Target match<select data-field="target_match_id"><option value="">— none —</option>${(this.matches || []).map((m) => `<option value="${this.esc(m.id)}">${this.esc(this.matchLabel(m.id))}</option>`).join('')}</select></label>
            <input type="hidden" data-field="source_note_id"><input type="hidden" data-field="source_clip_id"><input type="hidden" data-field="source_playlist_id">
            <p class="form-help" data-field="source_help">Optional: create from a note/clip/list via its Create goal action.</p>`;
        body.querySelector('[data-field="player_id"]').value = goal?.player_id || playerId || players[0]?.id || '';
        body.querySelector('[data-field="context"]').value = goal?.context || 'next_match';
        body.querySelector('[data-field="visibility"]').value = goal?.visibility || 'player';
        body.querySelector('[data-field="priority"]').value = goal?.priority || 'medium';
        body.querySelector('[data-field="title"]').value = goal?.title || source?.title || '';
        body.querySelector('[data-field="description"]').value = goal?.description || source?.description || '';
        body.querySelector('[data-field="status"]').value = goal?.status || 'open';
        body.querySelector('[data-field="target_date"]').value = goal?.target_date || '';
        body.querySelector('[data-field="success_criteria"]').value = goal?.success_criteria || '';
        body.querySelector('[data-field="coach_private_note"]').value = goal?.coach_private_note || '';
        body.querySelector('[data-field="target_match_id"]').value = goal?.target_match_id || '';
        for (const field of ['source_note_id', 'source_clip_id', 'source_playlist_id']) body.querySelector(`[data-field="${field}"]`).value = goal?.[field] || source?.[field] || '';
        if (source?.label || goal) {
            const summary = source?.label || this._goalSourceSummary(goal)?.text || '';
            body.querySelector('[data-field="source_help"]').textContent = summary ? `Evidence: ${summary}` : 'Evidence attached.';
        }
        const result = await this.formModal({
            title: goal ? 'Edit Player Goal' : 'New Player Goal', kicker: 'Coaching', body,
            confirmLabel: goal ? 'Save goal' : 'Create goal',
            onSubmit: (close) => {
                const data = {
                    player_id: body.querySelector('[data-field="player_id"]').value,
                    title: body.querySelector('[data-field="title"]').value.trim(),
                    description: body.querySelector('[data-field="description"]').value.trim(),
                    context: body.querySelector('[data-field="context"]').value,
                    visibility: body.querySelector('[data-field="visibility"]').value,
                    priority: body.querySelector('[data-field="priority"]').value,
                    status: body.querySelector('[data-field="status"]').value,
                    target_date: body.querySelector('[data-field="target_date"]').value || '',
                    success_criteria: body.querySelector('[data-field="success_criteria"]').value.trim(),
                    coach_private_note: body.querySelector('[data-field="coach_private_note"]').value.trim(),
                    target_match_id: body.querySelector('[data-field="target_match_id"]').value || null,
                };
                for (const field of ['source_note_id', 'source_clip_id', 'source_playlist_id']) {
                    const v = body.querySelector(`[data-field="${field}"]`).value;
                    if (v) data[field] = Number(v);
                }
                if (!data.player_id) { this.showError('Pick a player.'); return; }
                if (!data.title) { this.showError('Goal title is required.'); return; }
                close(data);
            },
        });
        if (!result) return;
        try {
            if (goal) {
                const { player_id, ...updates } = result;
                await this.updateCoachGoal(goal.id, updates);
            } else await this.createCoachGoal(result);
            this.showSuccess(goal ? 'Goal updated.' : 'Goal created.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachGoalStatus(goalId, status) {
        try {
            await this.updateCoachGoal(goalId, { status });
            this.showSuccess('Goal status updated.');
            await this.renderCoachWorkspace();
        } catch (err) { this.showError(err.message); }
    },

    async handleCoachDeleteGoal(goalId) {
        const ok = await this.confirmAction({ title: 'Delete goal', message: 'Delete this player goal?', confirmLabel: 'Delete goal', danger: true });
        if (!ok) return;
        try { await this.deleteCoachGoal(goalId); this.showSuccess('Goal deleted.'); await this.renderCoachWorkspace(); }
        catch (err) { this.showError(err.message); }
    },

    async openGoalReflectionModal(goalId) {
        const goal = (this._feedbackData?.goals || []).find((g) => Number(g.id) === Number(goalId));
        if (!goal) { this.showError('Goal not available.'); return; }
        const body = document.createElement('div');
        body.className = 'coach-mini-form player-goal-form';
        body.innerHTML = `
            <div class="player-goal-card is-preview">${this._renderGoalCard(goal, { viewer: true, actions: false })}</div>
            <label>Your reflection<textarea data-field="reflection" rows="4" maxlength="1000" placeholder="What did you try? What should your coach know?"></textarea></label>`;
        const result = await this.formModal({
            title: 'Reflect on goal', kicker: 'My Feedback', body, confirmLabel: 'Save reflection',
            onSubmit: (close) => {
                const reflection = body.querySelector('[data-field="reflection"]').value.trim();
                if (!reflection) { this.showError('Reflection is required.'); return; }
                close(reflection);
            },
        });
        if (!result) return;
        try {
            await this.createMyGoalReflection(goalId, result);
            this.showSuccess('Reflection saved for your coach.');
            await this.renderMyFeedback();
            if (this._feedbackTab === 'development') await this.renderFeedbackDevelopment();
        } catch (err) { this.showError(err.message); }
    },
};
