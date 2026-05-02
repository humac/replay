// Sprint 1 "after" capture for the Coach Review redesign.
// Re-runs the same dimension probes as the Sprint 0 baseline against the new
// is-review-mode layout, then saves PNGs for the PR description.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-1-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';
const FAMILY_USER = 'family1';
const FAMILY_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-1-after';
mkdirSync(OUT, { recursive: true });

async function login(page, user, pass) {
    await page.goto('/');
    return page.evaluate(async ({ u, p }) => {
        const r = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
        });
        const j = await r.json();
        sessionStorage.setItem('replay_admin_token', j.token);
        return j.token;
    }, { u: user, p: pass });
}

async function pickMatchWithMostNotes(page, token) {
    return page.evaluate(async (t) => {
        const r = await fetch('/api/coach/notes', { headers: { Authorization: 'Bearer ' + t } });
        const j = await r.json();
        const counts = {};
        (j.notes || []).forEach((n) => { counts[n.match_id] = (counts[n.match_id] || 0) + 1; });
        let bestId = null, bestN = 0;
        for (const [id, n] of Object.entries(counts)) if (n > bestN) { bestN = n; bestId = id; }
        return bestId;
    }, token);
}

async function dims(page) {
    return page.evaluate(() => {
        const dim = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top) };
        };
        const v = document.querySelector('#coach-review-video')?.getBoundingClientRect();
        const g = document.querySelector('.coach-review-grid')?.getBoundingClientRect();
        return {
            viewport: { w: window.innerWidth, h: window.innerHeight },
            isReviewMode: document.getElementById('coach-view')?.classList.contains('is-review-mode') ?? false,
            grid: dim('.coach-review-grid'),
            video: dim('#coach-review-video'),
            wrapper: dim('.coach-review-wrapper'),
            sidePanel: dim('.coach-review-side'),
            shell: dim('.coach-review-shell'),
            pageHead: dim('.coach-page-head'),
            chromeAboveVideo: dim('.coach-review-wrapper')?.top || null,
            videoPctOfGrid: (v && g) ? Math.round((v.width / g.width) * 100) : null,
        };
    });
}

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '768-tablet', width: 768, height: 1024 },
    { label: '390-mobile', width: 390, height: 844 },
];

test.describe.configure({ mode: 'serial' });

for (const w of widths) {
    test(`coach review after @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await page.goto(`/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('#coach-review-toolbar .coach-tool-grid');
        await page.waitForTimeout(800);

        const measured = await dims(page);
        console.log(`[${w.label}] dims:`, JSON.stringify(measured, null, 2));

        await page.screenshot({ path: `${OUT}/coach-review-${w.label}-top.png`, fullPage: false });
        await page.screenshot({ path: `${OUT}/coach-review-${w.label}-fullpage.png`, fullPage: true });

        // Sprint 1 acceptance — class is set on Review tab.
        expect(measured.isReviewMode).toBe(true);

        // Selectors must still exist after the layout change.
        await expect(page.locator('#coach-tab-review')).toBeVisible();
        await expect(page.locator('#coach-review-match')).toBeAttached();
        await expect(page.locator('#coach-review-slot')).toBeAttached();
        await expect(page.locator('#coach-review-toolbar')).toBeVisible();
        await expect(page.locator('#coach-review-form')).toBeVisible();
        await expect(page.locator('#coach-review-notes')).toBeAttached();
    });
}

test('regression: roster tab does NOT have is-review-mode (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/coach?tab=roster');
    await page.waitForTimeout(400);
    const isReview = await page.evaluate(() =>
        document.getElementById('coach-view')?.classList.contains('is-review-mode'),
    );
    expect(isReview).toBe(false);
});

test('regression: feedback view unchanged (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await page.goto('/feedback?tab=notes');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/feedback-notes-1440.png`, fullPage: true });
    // Confirm the feedback view does not get the review-mode class either.
    const isReview = await page.evaluate(() =>
        document.getElementById('coach-view')?.classList.contains('is-review-mode') ?? false,
    );
    expect(isReview).toBe(false);
});

test('regression: public season page unchanged (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/');
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/public-season-1440.png`, fullPage: false });
});

test('regression: coach roster, notes, playlists tabs (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    for (const tab of ['roster', 'notes', 'playlists']) {
        await page.goto(`/coach?tab=${tab}`);
        await page.waitForTimeout(400);
        await page.screenshot({ path: `${OUT}/coach-${tab}-1440.png`, fullPage: true });
    }
});
