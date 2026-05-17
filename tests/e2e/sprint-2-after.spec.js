// Sprint 2 "after" capture for the Coach Review redesign.
// Verifies the compact match/slot/time/save-note top bar replaces the old
// form-style picker, captures screenshots, and exercises the Sprint 2
// acceptance criteria from docs/archive/coach-review-ui-ux-implementation-plan.md.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8091 npx playwright test sprint-2-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-2-after';
mkdirSync(OUT, { recursive: true });

async function pickerDims(page) {
    return page.evaluate(() => {
        const dim = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top) };
        };
        return {
            picker: dim('.coach-review-picker'),
            match: dim('.coach-review-picker-group:nth-child(1)'),
            slot: dim('.coach-review-picker-group:nth-child(2)'),
            time: dim('.coach-review-picker-time'),
            save: dim('#coach-review-save-top'),
            timeText: document.getElementById('coach-review-time')?.textContent,
            wrapper: dim('.coach-review-wrapper'),
            chromeAboveVideo: dim('.coach-review-wrapper')?.top || null,
        };
    });
}

test.describe.configure({ mode: 'serial' });

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '700-narrow', width: 700, height: 900 },
    { label: '390-mobile', width: 390, height: 844 },
];

for (const w of widths) {
    test(`compact picker bar @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('.coach-review-picker');

        const m = await pickerDims(page);
        console.log(`[${w.label}] picker:`, JSON.stringify(m, null, 2));

        await page.screenshot({ path: `${OUT}/coach-review-${w.label}-top.png`, fullPage: false });

        // Sprint 2 acceptance: existing IDs preserved, new IDs added.
        await expect(page.locator('#coach-review-match')).toBeAttached();
        await expect(page.locator('#coach-review-slot')).toBeAttached();
        await expect(page.locator('#coach-review-time')).toBeVisible();
        await expect(page.locator('#coach-review-save-top')).toBeVisible();
        // Picker height should now be way under the 118px form-row baseline
        // at desktop widths (the bar wraps to ~110px on the 700px breakpoint).
        if (w.width >= 1024) {
            expect(m.picker.h).toBeLessThan(70);
        }
    });
}

test('time readout updates on timeupdate event', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-time');

    // Force a timeupdate without needing actual playback (seeded matches have
    // no real video files in the dev fixture).
    const text = await page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        v.currentTime = 762;
        v.dispatchEvent(new Event('timeupdate'));
        return document.getElementById('coach-review-time').textContent;
    });
    expect(text).toBe('12:42');
});

test('top-bar Save Note shares saveReviewNote handler', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    const onclick = await page.locator('#coach-review-save-top').getAttribute('onclick');
    expect(onclick).toBe('app.saveReviewNote()');
});
