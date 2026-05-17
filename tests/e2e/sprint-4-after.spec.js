// Sprint 4 "after" capture for the Coach Review redesign.
// Verifies the fast compact note composer: title + player chips + category +
// Save-at-MM:SS as the default state, with visibility / body / tags collapsed
// behind a <details> disclosure. Captures screenshots in collapsed and
// expanded states, and exercises the Sprint 4 acceptance criteria from
// docs/archive/coach-review-ui-ux-implementation-plan.md.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8091 npx playwright test sprint-4-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-4-after';
mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });

test('compact composer hides advanced fields by default (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-form');

    const state = await page.evaluate(() => {
        const dim = (el) => el ? Math.round(el.getBoundingClientRect().height) : 0;
        const body = document.getElementById('coach-review-body');
        const visibility = document.getElementById('coach-review-visibility');
        const tags = document.getElementById('coach-review-tags');
        const details = document.querySelector('.coach-review-advanced');
        return {
            // All existing IDs preserved (saveReviewNote depends on them)
            ids: ['coach-review-title', 'coach-review-body', 'coach-review-category',
                  'coach-review-visibility', 'coach-review-players', 'coach-review-tags']
                .every((id) => !!document.getElementById(id)),
            detailsOpen: details?.open,
            // When closed, the advanced fields render at zero height
            bodyH: dim(body),
            visibilityH: dim(visibility),
            tagsH: dim(tags),
            // Category and title are still visible (default composer)
            titleVisible: dim(document.getElementById('coach-review-title')) > 0,
            categoryVisible: dim(document.getElementById('coach-review-category')) > 0,
            saveBtnText: document.getElementById('coach-review-save-form')?.textContent,
        };
    });
    expect(state.ids).toBe(true);
    expect(state.detailsOpen).toBe(false);
    expect(state.bodyH).toBe(0);
    expect(state.visibilityH).toBe(0);
    expect(state.tagsH).toBe(0);
    expect(state.titleVisible).toBe(true);
    expect(state.categoryVisible).toBe(true);
    expect(state.saveBtnText).toMatch(/^Save at \d+:\d+$/);

    await page.screenshot({ path: `${OUT}/composer-collapsed-1440.png`, fullPage: false });
});

test('compact composer reveals advanced fields when expanded (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-form');

    // Open the disclosure
    await page.evaluate(() => { document.querySelector('.coach-review-advanced').open = true; });
    await page.waitForTimeout(150);

    const state = await page.evaluate(() => {
        const dim = (el) => el ? Math.round(el.getBoundingClientRect().height) : 0;
        return {
            bodyH: dim(document.getElementById('coach-review-body')),
            visibilityH: dim(document.getElementById('coach-review-visibility')),
            tagsH: dim(document.getElementById('coach-review-tags')),
        };
    });
    expect(state.bodyH).toBeGreaterThan(40);
    expect(state.visibilityH).toBeGreaterThan(20);
    expect(state.tagsH).toBeGreaterThan(20);

    await page.screenshot({ path: `${OUT}/composer-expanded-1440.png`, fullPage: false });
});

test('Save-at button text tracks video timestamp (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-save-form');

    // Force a timestamp change without a real video file in the fixture
    const text = await page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        v.currentTime = 762;  // 12:42 like the spec example
        v.dispatchEvent(new Event('timeupdate'));
        return document.getElementById('coach-review-save-form').textContent;
    });
    expect(text).toBe('Save at 12:42');
});

test('save handler still fires from the new form button (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-save-form');

    // The new compact button delegates to app.saveReviewNote() — same as the
    // top-bar Save Note button. Verify the onclick handler is still wired.
    const onclick = await page.locator('#coach-review-save-form').getAttribute('onclick');
    expect(onclick).toBe('app.saveReviewNote()');
});

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '390-mobile', width: 390, height: 844 },
];

for (const w of widths) {
    test(`composer renders @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('#coach-review-form');
        await page.screenshot({ path: `${OUT}/composer-${w.label}-top.png`, fullPage: false });
    });
}
