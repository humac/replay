// AI drafting domain mixin (PR-FE 13/13 extraction).
// Methods continue to reference peers as `this.x()` — the mixin
// pattern merges this object into `window.app` alongside the rest of
// coachingMixin, so internal helpers and shared utilities resolve at
// runtime as before.
//
// Scope: Phase 8.5 AI drafting panel inside Coach Review's More-details
// composer. Server enforcement lives in routers/coach_ai.py; this
// module only renders the panel, gates the controls for UX hygiene,
// and dispatches `draftCoachAI()` (defined in js/api.js).

const AI_DRAFT_TARGETS = [
    ['player_summary', 'Player summary', 'coach-review-player-summary'],
    ['what_happened', 'What happened', 'coach-review-what-happened'],
    ['why_it_matters', 'Why it matters', 'coach-review-why-it-matters'],
    ['what_to_do_next', 'What to do next', 'coach-review-what-to-do-next'],
];
const AI_DRAFT_TARGET_LABELS = Object.fromEntries(AI_DRAFT_TARGETS.map(([value, label]) => [value, label]));

export const coachingAIMixin = {
    renderCoachAIDraftPanel() {
        // UX-only: these client-side ai.drafting_enabled / allowed_draft_targets / visibility checks
        // are for UX hygiene (avoiding visible-but-non-functional buttons). routers/coach_ai.py is the
        // authoritative gate — server enforcement is the actual access control.
        const settings = this._teamSettings?.settings || {};
        const enabled = !!settings['ai.drafting_enabled'];
        const allowedTargets = this._coachAIAllowedDraftTargets(settings);
        const blockedVisibilities = settings['ai.never_draft_for_visibilities'] || [];
        const status = enabled
            ? (allowedTargets.length
                ? 'Generate a bounded draft from selected, team-scoped evidence. Nothing is saved until you insert and save.'
                : 'AI drafting is enabled, but no note fields are allowed for drafting in Team settings.')
            : 'AI drafting is disabled for this team. Enable it in Team settings to generate drafts.';
        const disabled = enabled && allowedTargets.length ? '' : 'disabled aria-disabled="true"';
        return `
            <section id="coach-ai-draft-panel" class="coach-ai-draft-panel ${enabled ? 'is-enabled' : 'is-disabled'}" aria-labelledby="coach-ai-draft-title" data-blocked-visibilities="${this.esc(blockedVisibilities.join(','))}">
                <div class="coach-ai-draft-head">
                    <div>
                        <span class="section-kicker">AI assist</span>
                        <h5 id="coach-ai-draft-title">AI drafting</h5>
                    </div>
                    <span class="status-pill ${enabled ? 'ready' : 'waiting'}">${enabled ? 'Opt-in' : 'Disabled'}</span>
                </div>
                <p id="coach-ai-draft-status" class="coach-ai-draft-status">${this.esc(status)}</p>
                <label class="coach-review-field-label" for="coach-ai-draft-target">
                    <span>Draft target</span>
                    <select id="coach-ai-draft-target" ${disabled} onchange="app.refreshCoachAIDraftControls()">
                        ${(enabled ? allowedTargets : AI_DRAFT_TARGETS).map(([value, label]) => `<option value="${this.esc(value)}">${this.esc(label)}</option>`).join('')}
                    </select>
                </label>
                <label class="coach-review-field-label" for="coach-ai-draft-instruction">
                    <span>Coach instruction <small>(not stored)</small></span>
                    <textarea id="coach-ai-draft-instruction" rows="2" maxlength="4000" placeholder="Optional: emphasize confidence, one concise sentence, U12 tone…" ${disabled}></textarea>
                </label>
                <div class="coach-ai-draft-actions">
                    <button type="button" id="coach-ai-draft-generate" class="mini-action-btn" onclick="app.generateCoachAIDraft()" ${disabled}>Generate draft</button>
                    <button type="button" id="coach-ai-draft-insert" class="mini-action-btn" onclick="app.insertCoachAIDraft()" disabled aria-disabled="true">Insert</button>
                </div>
                <textarea id="coach-ai-draft-output" class="coach-ai-draft-output" rows="3" readonly placeholder="Draft appears here for review before insertion."></textarea>
            </section>
        `;
    },

    _coachAIAllowedDraftTargets(settings = this._teamSettings?.settings || {}) {
        const allowed = new Set(settings['ai.allowed_draft_targets'] || []);
        return AI_DRAFT_TARGETS.filter(([value]) => allowed.has(value));
    },

    _coachAIDraftTargetConfig(value = null) {
        const selected = value || document.getElementById('coach-ai-draft-target')?.value || AI_DRAFT_TARGETS[0][0];
        const row = AI_DRAFT_TARGETS.find(([target]) => target === selected) || AI_DRAFT_TARGETS[0];
        return { target: row[0], label: row[1], fieldId: row[2] };
    },

    _coachAIDraftVisibility() {
        return document.getElementById('coach-review-visibility')?.value || this._teamSettings?.settings?.['notes.default_visibility'] || 'private';
    },

    _coachAIDraftSelectedPlayerIds() {
        return Array.from(document.querySelectorAll('#coach-review-players .coach-check-option.is-selected'))
            .map((item) => item.dataset.value)
            .filter(Boolean);
    },

    refreshCoachAIDraftControls() {
        const status = document.getElementById('coach-ai-draft-status');
        const generateBtn = document.getElementById('coach-ai-draft-generate');
        if (!generateBtn) return;
        const settings = this._teamSettings?.settings || {};
        const visibility = this._coachAIDraftVisibility();
        const blocked = new Set(settings['ai.never_draft_for_visibilities'] || []);
        const enabled = !!settings['ai.drafting_enabled'];
        const hasAllowedTarget = this._coachAIAllowedDraftTargets(settings).length > 0;
        const blockedByVisibility = blocked.has(visibility);
        generateBtn.disabled = !enabled || !hasAllowedTarget || blockedByVisibility;
        generateBtn.setAttribute('aria-disabled', generateBtn.disabled ? 'true' : 'false');
        if (status) {
            status.textContent = !hasAllowedTarget && enabled
                ? 'AI drafting is enabled, but no note fields are allowed for drafting in Team settings.'
                : (blockedByVisibility
                    ? `Drafting is blocked for ${visibility} visibility by team policy. Choose a permitted visibility before generating.`
                    : (enabled ? 'Ready. Drafts are review-only until inserted and saved.' : 'AI drafting is disabled for this team.'));
        }
    },

    async generateCoachAIDraft() {
        const btn = document.getElementById('coach-ai-draft-generate');
        const output = document.getElementById('coach-ai-draft-output');
        const insertBtn = document.getElementById('coach-ai-draft-insert');
        const status = document.getElementById('coach-ai-draft-status');
        if (!btn || btn.disabled) return;
        this.refreshCoachAIDraftControls();
        if (btn.disabled) return;
        const done = this.btnLoading ? this.btnLoading(btn, 'Drafting…') : null;
        if (status) status.textContent = 'Generating draft from scoped evidence…';
        if (insertBtn) { insertBtn.disabled = true; insertBtn.setAttribute('aria-disabled', 'true'); }
        try {
            const config = this._coachAIDraftTargetConfig();
            const review = this._coachReview || {};
            const evidenceRefs = [];
            if (review.matchId) evidenceRefs.push({ type: 'match', id: review.matchId });
            const payload = await this.draftCoachAI({
                draft_target: config.target,
                target_resource_type: 'player',
                target_resource_id: this._coachAIDraftSelectedPlayerIds()[0] || null,
                target_visibility: this._coachAIDraftVisibility(),
                target_player_ids: this._coachAIDraftSelectedPlayerIds(),
                evidence_refs: evidenceRefs,
                coach_prompt: document.getElementById('coach-ai-draft-instruction')?.value || '',
            });
            if (output) output.value = payload.text || '';
            if (insertBtn) {
                const hasDraft = !!(payload.text || '').trim();
                insertBtn.disabled = !hasDraft;
                insertBtn.setAttribute('aria-disabled', hasDraft ? 'false' : 'true');
            }
            if (status) status.textContent = `Draft ready for ${AI_DRAFT_TARGET_LABELS[config.target] || config.target}. Review before inserting.`;
        } catch (error) {
            if (output) output.value = '';
            if (status) status.textContent = error.message || 'AI drafting failed.';
            this.showError?.(error.message || 'AI drafting failed.');
        } finally {
            if (done) done();
        }
    },

    insertCoachAIDraft() {
        const output = document.getElementById('coach-ai-draft-output');
        const text = (output?.value || '').trim();
        if (!text) return;
        const config = this._coachAIDraftTargetConfig();
        const target = document.getElementById(config.fieldId);
        if (!target) {
            this.showError?.('Open More details before inserting this draft.');
            return;
        }
        target.value = text;
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.focus?.();
        const status = document.getElementById('coach-ai-draft-status');
        if (status) status.textContent = `Inserted into ${AI_DRAFT_TARGET_LABELS[config.target] || config.target}. Save the note to persist it.`;
    },
};
