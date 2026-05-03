// Sprint 1 "after" capture for the Coach Review redesign.
// Re-runs the same dimension probes as the Sprint 0 baseline against the new
// is-review-mode layout, then saves PNGs for the PR description.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-1-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';
const FAMILY_USER = 'family1';
const FAMILY_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-1-after';
mkdirSync(OUT, { recursive: true });

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

// Run all tests serially. The parallel default lets concurrent tests race the
// dev server (and Playwright's reporter aggregating screenshots), which has
// caused the regression-tab captures to occasionally land on the season
// fallback. The serial-mode line MUST be at top level (it errors inside a
// describe in this Playwright version), and applies to every top-level test
// in this file.
test.describe.configure({ mode: 'serial' });

for (const w of widths) {
    test(`coach review after @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('#coach-review-toolbar .coach-tool-grid');

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
    await gotoAndSettle(page, '/coach?tab=roster');
    const isReview = await page.evaluate(() =>
        document.getElementById('coach-view')?.classList.contains('is-review-mode'),
    );
    expect(isReview).toBe(false);
});

test('regression: feedback view unchanged (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await gotoAndSettle(page, '/feedback?tab=notes');
    // Wait for the feedback notes list to actually render before screenshotting.
    await page.waitForSelector('#feedback-tab-notes:not([hidden])', { timeout: 5000 });
    await page.screenshot({ path: `${OUT}/feedback-notes-1440.png`, fullPage: true });
    const isReview = await page.evaluate(() =>
        document.getElementById('coach-view')?.classList.contains('is-review-mode') ?? false,
    );
    expect(isReview).toBe(false);
});

test('regression: public season page unchanged (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/');
    await page.screenshot({ path: `${OUT}/public-season-1440.png`, fullPage: false });
});

test('regression: coach roster tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=roster');
    await page.waitForSelector('#coach-tab-roster:not([hidden]) #coach-roster-list', { timeout: 5000 });
    // Confirm the page has rendered the actual roster, not the season fallback.
    await expect(page.locator('#coach-tab-roster:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-roster-1440.png`, fullPage: true });
});

test('regression: coach notes tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=notes');
    await page.waitForSelector('#coach-tab-notes:not([hidden]) #coach-notes-list', { timeout: 5000 });
    await expect(page.locator('#coach-tab-notes:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-notes-1440.png`, fullPage: true });
});

test('regression: coach playlists tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=playlists');
    await page.waitForSelector('#coach-tab-playlists:not([hidden]) #coach-playlists-list', { timeout: 5000 });
    await expect(page.locator('#coach-tab-playlists:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-playlists-1440.png`, fullPage: true });
});
