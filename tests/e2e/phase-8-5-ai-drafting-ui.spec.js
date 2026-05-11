// Phase 8.5 — AI drafting UI smoke/evidence captures.
//
// Uses docs seed users/data. Run with the app listening on :8099:
//   REPLAY_DATA_DIR=/tmp/replay-phase8-5-e2e python docs/_seed/seed.py
//   REPLAY_AI_PROVIDER=mock REPLAY_PORT=8099 REPLAY_DATA_DIR=/tmp/replay-phase8-5-e2e python server.py
//   cd tests/e2e && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8099 npm run capture-phase-8-5
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-8-5-ai-drafting-ui');
mkdirSync(OUT, { recursive: true });

const PASS = 'Replay!Demo123';
const ADMIN_PASS = process.env.REPLAY_E2E_ADMIN_PASS || 'Replay!Admin123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8099';

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });

async function updateDraftingSettings(page, settings) {
    const loginResp = await page.request.post(`${BASE}/api/login`, {
        data: { username: 'admin', password: ADMIN_PASS },
    });
    expect(loginResp.ok()).toBeTruthy();
    const { token } = await loginResp.json();
    const settingsResp = await page.request.patch(`${BASE}/api/coach/team/settings`, {
        headers: { Authorization: `Bearer ${token}` },
        data: { settings },
    });
    expect(settingsResp.ok()).toBeTruthy();
}

async function enableDraftingForCoach(page) {
    await updateDraftingSettings(page, { 'ai.drafting_enabled': true, 'ai.allowed_draft_targets': ['player_summary'] });
}

async function enableDraftingWithoutTargets(page) {
    await updateDraftingSettings(page, { 'ai.drafting_enabled': true, 'ai.allowed_draft_targets': [] });
}

test.describe('Phase 8.5 — AI drafting UI', () => {
    test('01 — coach sees disabled AI drafting panel when team setting is off', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=review');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await expect(page.locator('#coach-ai-draft-panel')).toBeVisible();
        await expect(page.locator('#coach-ai-draft-panel')).toContainText('AI drafting');
        await expect(page.locator('#coach-ai-draft-panel')).toContainText(/disabled|enable/i);
        await page.screenshot({ path: path.join(OUT, '01-ai-disabled.png'), fullPage: false });
    });

    test('02 — coach can call draft endpoint and keep output unsaved until insert', async ({ page }) => {
        await enableDraftingForCoach(page);
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=review');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        const result = await page.evaluate(async () => {
            const settings = window.app._teamSettings?.settings || {};
            if (!settings['ai.drafting_enabled']) return { skipped: true };
            document.querySelector('#coach-review-visibility').value = 'team';
            window.app.refreshCoachAIDraftControls();
            document.querySelector('#coach-ai-draft-target').value = 'player_summary';
            document.querySelector('#coach-ai-draft-instruction').value = 'One sentence for a parent.';
            const button = document.querySelector('#coach-ai-draft-generate');
            button.click();
            await new Promise((resolve) => setTimeout(resolve, 600));
            return {
                output: document.querySelector('#coach-ai-draft-output')?.value || '',
                fieldBeforeInsert: document.querySelector('#coach-review-player-summary')?.value || '',
            };
        });
        if (result.skipped) test.skip(true, 'Seed user cannot enable AI drafting settings.');
        expect(result.output).toContain('Mock draft');
        expect(result.fieldBeforeInsert).toBe('');
        await page.locator('#coach-ai-draft-insert').click();
        await expect(page.locator('#coach-review-player-summary')).toHaveValue(/Mock draft/);
        await page.screenshot({ path: path.join(OUT, '02-ai-draft-ready.png'), fullPage: false });
    });

    test('03 — enabled drafting stays disabled when no note targets are allowed', async ({ page }) => {
        await enableDraftingWithoutTargets(page);
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=review');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await expect(page.locator('#coach-ai-draft-panel')).toContainText('no note fields are allowed');
        await expect(page.locator('#coach-ai-draft-generate')).toBeDisabled();
        await page.evaluate(() => {
            const visibility = document.querySelector('#coach-review-visibility');
            visibility.value = 'team';
            window.app.refreshCoachAIDraftControls();
        });
        await expect(page.locator('#coach-ai-draft-generate')).toBeDisabled();
    });

    test('04 — viewer does not see coach AI drafting UI and endpoint is denied', async ({ page }) => {
        await login(page, 'family1', PASS);
        await page.goto('/feedback?tab=notes');
        await expect(page.locator('#coach-ai-draft-panel')).toHaveCount(0);
        const status = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/coach/ai/draft', {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ draft_target: 'player_summary', target_resource_type: 'player', target_visibility: 'team' }),
            });
            return r.status;
        });
        expect(status).toBe(403);
        await page.setContent('<main style="font: 18px system-ui; padding: 32px;"><h1>Viewer denied</h1><p>/api/coach/ai/draft returned 403 for family1; no AI UI is present in feedback.</p></main>');
        await page.screenshot({ path: path.join(OUT, '03-viewer-denied.png'), fullPage: false });
    });
});
