// Phase 7 — player goals/action items screenshot/evidence captures.
//
// Uses docs seed users/data. Run with the app listening on :8097:
//   REPLAY_DATA_DIR=/tmp/replay-phase7-e2e python docs/_seed/seed.py
//   REPLAY_PORT=8097 REPLAY_DATA_DIR=/tmp/replay-phase7-e2e python server.py
//   cd tests/e2e && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8097 npm run capture-phase-7
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-7-goals');
mkdirSync(OUT, { recursive: true });

const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8097';

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });

async function ensureGoal(page) {
    const created = await page.evaluate(async () => {
        const token = sessionStorage.getItem('replay_admin_token');
        const headers = { Authorization: `Bearer ${token}` };
        const goalsResp = await fetch('/api/coach/goals', { headers });
        const goals = (await goalsResp.json()).goals || [];
        if (goals.length) return goals[0];
        const playersResp = await fetch('/api/coach/players', { headers });
        const players = (await playersResp.json()).players || [];
        if (!players.length) throw new Error('seed has no players');
        const resp = await fetch('/api/coach/goals', {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                player_id: players[0].id,
                title: 'Phase 7 screenshot goal',
                description: 'Check shoulder before receiving and reflect after the match.',
                context: 'next_match',
                status: 'open',
            }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        return (await resp.json()).goal;
    });
    expect(created.id).toBeTruthy();
    return created;
}

test.describe('Phase 7 — goals UI and privacy captures', () => {
    test('01 — coach can view active goals on a development profile', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=roster');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        const goal = await ensureGoal(page);
        await page.evaluate((playerId) => { window.app.openCoachPlayerDevelopmentModal(playerId); return true; }, goal.player_id);
        await expect(page.locator('.app-modal-card')).toBeVisible();
        await expect(page.locator('.player-goal-card').first()).toBeVisible();
        await page.locator('.app-modal-card').first().screenshot({ path: path.join(OUT, '01-coach-development-goals.png') });
    });

    test('02 — coach goal form supports action plan, status, context, and evidence fields', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=roster');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        const goal = await ensureGoal(page);
        await page.evaluate((goalId) => { window.app.openCoachGoalModal({ goalId }); return true; }, goal.id);
        await expect(page.locator('.app-modal-card [data-field="title"]')).toBeVisible();
        await expect(page.locator('.app-modal-card [data-field="status"]')).toBeVisible();
        await expect(page.locator('.app-modal-card [data-field="context"]')).toBeVisible();
        await page.locator('.app-modal-card').first().screenshot({ path: path.join(OUT, '02-coach-goal-edit-modal.png') });
    });

    test('03 — family viewer sees goals/reflections without coach-private leakage', async ({ page }) => {
        await login(page, 'family1', PASS);
        await page.goto('/feedback?tab=development');
        await page.waitForFunction(() => !!window.app?._feedbackData);
        await expect(page.locator('#feedback-development-profile')).toBeVisible();
        await expect(page.locator('.player-goal-card').first()).toBeVisible();
        const payload = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/my-feedback', { headers: { Authorization: `Bearer ${token}` } });
            const dev = document.querySelector('#feedback-development-profile')?.innerText || '';
            return JSON.stringify(await r.json()) + dev;
        });
        expect(payload).not.toContain('PHASE7_SECRET');
        const visibleText = await page.locator('#feedback-view').innerText();
        expect(visibleText).not.toContain('coach_private_note');
        expect(visibleText).not.toContain('PHASE7_SECRET');
        await page.screenshot({ path: path.join(OUT, '03-family-current-goals.png'), fullPage: false });
    });
});
