// Phase 9 — engagement dashboard screenshot/evidence captures.
//
// Uses docs seed users/data. Run with the app listening on :8099:
//   REPLAY_DATA_DIR=/tmp/replay-phase9-e2e python docs/_seed/seed.py
//   REPLAY_PORT=8099 REPLAY_DATA_DIR=/tmp/replay-phase9-e2e python server.py
//   cd tests/e2e && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8099 npm run capture-phase-9
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-9-engagement-dashboard');
mkdirSync(OUT, { recursive: true });

const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8099';

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });

async function seedReviewActivity(page) {
    await login(page, 'family1', PASS);
    await page.goto('/feedback?tab=notes');
    await page.waitForFunction(() => !!window.app?._feedbackData);
    const token = await page.evaluate(() => sessionStorage.getItem('replay_admin_token'));
    const headers = { Authorization: `Bearer ${token}` };
    const dataResp = await page.request.get(`${BASE}/api/my-feedback`, { headers });
    const data = await dataResp.json();
    const note = (data.notes || [])[0];
    const playlist = (data.playlists || [])[0];
    const results = [];
    if (note) {
        const resp = await page.request.post(`${BASE}/api/my-feedback/review`, {
            headers,
            data: { note_id: note.id, reflection: 'Phase 9 E2E reflection needing coach response.' },
        });
        results.push({ kind: 'note', status: resp.status(), body: await resp.json().catch(() => ({})) });
    }
    if (playlist) {
        const resp = await page.request.post(`${BASE}/api/my-feedback/review`, {
            headers,
            data: { playlist_id: playlist.id },
        });
        results.push({ kind: 'playlist', status: resp.status(), body: await resp.json().catch(() => ({})) });
    }
    return results;
}

test.describe('Phase 9 — engagement dashboard UI and privacy captures', () => {
    test('01 — coach sees engagement aggregates and filters', async ({ page }) => {
        const seedResults = await seedReviewActivity(page);
        expect(seedResults.some((r) => r.kind === 'note' && r.status === 200 && r.body?.review?.reflection)).toBeTruthy();
        expect(seedResults.some((r) => r.kind === 'playlist' && r.status === 200 && r.body?.review?.playlist_id)).toBeTruthy();
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=engagement');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await expect(page.locator('#coach-tab-engagement')).toBeVisible();
        await expect(page.locator('#coach-engagement-dashboard')).toContainText('Review completion by player');
        await expect(page.locator('#coach-engagement-visibility')).toBeVisible();
        await expect(page.locator('#coach-engagement-dashboard')).toContainText('Reflections needing response');
        await expect(page.locator('#coach-engagement-dashboard')).toContainText('feedback review reflections only');
        await expect(page.locator('#coach-engagement-visibility')).not.toContainText('Private');
        await page.screenshot({ path: path.join(OUT, '01-coach-engagement-dashboard.png'), fullPage: false });
    });

    test('02 — visibility filter updates dashboard without private content leakage', async ({ page }) => {
        await login(page, 'coach1', PASS);
        await page.goto('/coach?tab=engagement');
        await page.waitForFunction(() => !!window.app?._coachBundle);
        await page.locator('#coach-engagement-visibility').selectOption('player');
        await page.waitForLoadState('networkidle');
        await expect(page.locator('#coach-engagement-dashboard')).toContainText('Review completion by match');
        const payload = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/coach/engagement?visibility=player', { headers: { Authorization: `Bearer ${token}` } });
            return JSON.stringify(await r.json()) + document.querySelector('#coach-engagement-dashboard')?.innerText;
        });
        expect(payload).not.toContain('coach_private_note');
        expect(payload).not.toContain('DO NOT LEAK');
        expect(payload).not.toContain('PRIVATE CANARY');
        await page.screenshot({ path: path.join(OUT, '02-player-visibility-filter.png'), fullPage: false });
    });

    test('03 — viewer cannot access the coach engagement API', async ({ page }) => {
        await login(page, 'family1', PASS);
        await page.goto('/');
        const status = await page.evaluate(async () => {
            const token = sessionStorage.getItem('replay_admin_token');
            const r = await fetch('/api/coach/engagement', { headers: { Authorization: `Bearer ${token}` } });
            return r.status;
        });
        expect(status).toBe(403);
        await page.setContent('<main style="font: 18px system-ui; padding: 32px;"><h1>Viewer denied</h1><p>/api/coach/engagement returned 403 for family1.</p></main>');
        await page.screenshot({ path: path.join(OUT, '03-viewer-denied.png'), fullPage: false });
    });
});
