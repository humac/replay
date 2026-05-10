// Phase 8 — match-level coaching summary screenshot/evidence captures.
//
// Uses the docs seed users and data. Run with the app listening on :8098:
//   REPLAY_DATA_DIR=/tmp/replay-phase8-e2e python docs/_seed/seed.py
//   PORT=8098 REPLAY_DATA_DIR=/tmp/replay-phase8-e2e python server.py
//   cd tests/e2e && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8098 npm run capture-phase-8
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-8-match-summaries');
mkdirSync(OUT, { recursive: true });

const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8098';

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });

test.describe('Phase 8 — match summaries UI and privacy captures', () => {
    test('01 — coach can see the match summaries workspace', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=summaries');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await expect(page.locator('#coach-tab-summaries')).toBeVisible();
        await expect(page.locator('#coach-summaries-list [data-summary-id]').first()).toBeVisible();
        await page.screenshot({ path: path.join(OUT, '01-coach-match-summaries-list.png'), fullPage: false });
    });

    test('02 — coach edit modal shows visibility, recap fields, and linked source pickers', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=summaries');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await page.locator('#coach-summaries-list [data-summary-id] button', { hasText: 'Edit' }).first().click();
        await expect(page.locator('.app-modal-card')).toBeVisible();
        await expect(page.locator('.app-modal-card textarea[data-field="team_positives"]')).toBeVisible();
        await expect(page.locator('.app-modal-card select[data-field="visibility"]')).toBeVisible();
        await page.locator('.app-modal-card details').evaluate((el) => { el.open = true; });
        await page.locator('.app-modal-card').first().screenshot({ path: path.join(OUT, '02-coach-summary-edit-modal.png') });
    });

    test('03 — family viewer sees only team-visible summaries and safe linked sources', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=summaries');
        const privateSourceId = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/coach/notes', { headers: { Authorization: 'Bearer ' + token } });
            const j = await r.json();
            return (j.notes || []).find((n) => String(n.title || '').includes('PHASE8_PRIVATE_SOURCE_CANARY'))?.id || null;
        });
        expect(privateSourceId).not.toBeNull();
        await login(page, 'family1', PASS);
        await page.goto('/feedback?tab=summaries');
        await page.waitForFunction(() => !!window.app?._feedbackData);
        await expect(page.locator('#feedback-tab-summaries')).toBeVisible();
        await expect(page.locator('#feedback-summaries-list .feedback-summary-card').first()).toBeVisible();
        const payloadObj = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/my-feedback', { headers: { Authorization: 'Bearer ' + token } });
            return await r.json();
        });
        const payload = JSON.stringify(payloadObj);
        expect(payload).not.toContain('PRIVATE_PHASE8_CANARY');
        expect(payload).not.toContain('PHASE8_PRIVATE_SOURCE_CANARY');
        const privateSourceIds = payloadObj.notes
            .filter((n) => String(n.title || '').includes('PHASE8_PRIVATE_SOURCE_CANARY'))
            .map((n) => n.id);
        expect(privateSourceIds).toEqual([]);
        for (const summary of payloadObj.match_summaries || []) {
            expect(summary.note_ids || []).not.toContain(privateSourceId);
        }
        const visibleText = await page.locator('#feedback-view').innerText();
        expect(visibleText).not.toContain('PRIVATE_PHASE8_CANARY');
        expect(visibleText).not.toContain('PHASE8_PRIVATE_SOURCE_CANARY');
        expect(visibleText).not.toContain('coach_private_note');
        await page.screenshot({ path: path.join(OUT, '03-family-match-summaries-list.png'), fullPage: false });
    });
});
