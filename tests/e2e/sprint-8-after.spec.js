// Sprint 8 "after" capture for the Coach Review redesign.
// Audits responsive + accessibility coverage across 5 widths:
//   - tap targets ≥44 px under pointer:coarse / narrow viewports
//   - ARIA: aria-label, aria-pressed, role on every interactive control
//   - canvas alignment over the video survives focus-mode + resize
//   - no horizontal page overflow (except intentional timeline rail)
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8091 npx playwright test sprint-8-after.spec.js

import { test, expect, devices } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-8-after';
mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });

const widths = [
    { label: '390-mobile', width: 390, height: 844 },
    { label: '768-tablet', width: 768, height: 1024 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1920-wide', width: 1920, height: 1080 },
];

for (const w of widths) {
    test(`a11y + responsive @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('.coach-tool-btn');
        await page.waitForTimeout(300);

        const audit = await page.evaluate(() => {
            // Every tool button has aria-label + title + aria-pressed
            const tools = Array.from(document.querySelectorAll('.coach-tool-btn'));
            const swatches = Array.from(document.querySelectorAll('.coach-color-swatch'));
            const chips = Array.from(document.querySelectorAll('.coach-timeline-chip'));
            const focusToggle = document.getElementById('coach-review-focus-toggle');
            const shortcutsToggle = document.getElementById('coach-review-shortcuts-toggle');
            const railLabel = document.getElementById('coach-review-notes')?.getAttribute('aria-label');
            return {
                toolsAllHaveAria: tools.every((b) =>
                    b.getAttribute('aria-label') && b.getAttribute('title') && b.hasAttribute('aria-pressed')),
                swatchesAllHaveAria: swatches.every((b) =>
                    b.getAttribute('aria-label')?.startsWith('Color: ') && b.hasAttribute('aria-pressed')),
                chipsAllHaveAria: chips.every((c) =>
                    c.getAttribute('aria-label')?.startsWith('Jump to') && c.hasAttribute('aria-pressed')),
                focusToggleAria: focusToggle?.getAttribute('aria-label'),
                focusTogglePressed: focusToggle?.getAttribute('aria-pressed'),
                shortcutsToggleAria: shortcutsToggle?.getAttribute('aria-label'),
                railLabel,
                bodyHasHorizScroll: document.body.scrollWidth > window.innerWidth + 1,
                railOverflowX: document.querySelector('.coach-timeline-rail')
                    ? getComputedStyle(document.querySelector('.coach-timeline-rail')).overflowX
                    : null,
            };
        });

        expect(audit.toolsAllHaveAria).toBe(true);
        expect(audit.swatchesAllHaveAria).toBe(true);
        if (audit.chipsAllHaveAria !== null) expect(audit.chipsAllHaveAria).toBe(true);
        expect(audit.focusToggleAria).toBeTruthy();
        expect(audit.shortcutsToggleAria).toBeTruthy();
        expect(audit.railLabel).toMatch(/^Notes for /);
        // No horizontal page overflow (except the intentional timeline rail
        // which is a contained scroll surface).
        expect(audit.bodyHasHorizScroll).toBe(false);
        expect(audit.railOverflowX).toBe('auto');

        await page.screenshot({ path: `${OUT}/a11y-${w.label}-top.png`, fullPage: false });
    });
}

test('tap targets are ≥44 px on iPad Mini emulation', async ({ browser }) => {
    const ctx = await browser.newContext({ ...devices['iPad Mini'] });
    const page = await ctx.newPage();
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-tool-btn');
    // Wait for the timeline rail chips to render (they paint after
    // loadCoachReviewVideo resolves — slower on emulated viewports).
    await page.waitForSelector('.coach-timeline-chip', { state: 'attached', timeout: 5000 }).catch(() => {});

    const sizes = await page.evaluate(() => {
        const measure = (sel) => {
            const els = Array.from(document.querySelectorAll(sel));
            return els
                .map((el) => Math.round(el.getBoundingClientRect().height))
                .filter((h) => h > 0);  // skip elements that aren't laid out yet
        };
        return {
            tools: measure('.coach-tool-btn'),
            chips: measure('.coach-timeline-chip'),
            saveBtn: measure('.coach-review-picker-save'),
            focusBtns: measure('.coach-review-picker-focus'),
        };
    });
    expect(sizes.tools.length).toBeGreaterThan(0);
    for (const h of sizes.tools) expect(h).toBeGreaterThanOrEqual(44);
    for (const h of sizes.chips) expect(h).toBeGreaterThanOrEqual(44);
    for (const h of sizes.saveBtn) expect(h).toBeGreaterThanOrEqual(44);
    for (const h of sizes.focusBtns) expect(h).toBeGreaterThanOrEqual(44);

    await page.screenshot({ path: `${OUT}/a11y-ipad-mini.png`, fullPage: false });
    await ctx.close();
});

test('canvas stays aligned with video after viewport resize', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-review-wrapper');
    // Activate the canvas so it has a current size.
    await page.evaluate(() => window.app.activateCoachCanvas());
    await page.waitForTimeout(300);

    const at = (w, h) => page.setViewportSize({ width: w, height: h }).then(() => page.waitForTimeout(300));
    const probe = () => page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        const c = document.getElementById('coach-drawing-canvas');
        return {
            videoW: Math.round(v.getBoundingClientRect().width),
            videoH: Math.round(v.getBoundingClientRect().height),
            canvasW: c.width,
            canvasH: c.height,
        };
    });

    for (const [w, h] of [[1920, 1080], [1024, 768], [1440, 900]]) {
        await at(w, h);
        const m = await probe();
        // Canvas bitmap dimensions (set by _resizeCoachCanvas) match the
        // video's CSS px size — alignment invariant from Sprint 1.
        expect(Math.abs(m.canvasW - m.videoW)).toBeLessThanOrEqual(2);
        expect(Math.abs(m.canvasH - m.videoH)).toBeLessThanOrEqual(2);
    }
});

test('canvas stays aligned through focus-mode toggle', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-review-wrapper');
    await page.evaluate(() => window.app.activateCoachCanvas());
    await page.waitForTimeout(300);

    // Enter focus → canvas re-syncs to the wider video
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.waitForTimeout(400);
    const onFocus = await page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        const c = document.getElementById('coach-drawing-canvas');
        return {
            videoW: Math.round(v.getBoundingClientRect().width),
            canvasW: c.width,
        };
    });
    expect(Math.abs(onFocus.canvasW - onFocus.videoW)).toBeLessThanOrEqual(2);

    // Exit focus → canvas re-syncs back to the original video size
    await page.evaluate(() => window.app.exitCoachFocusMode());
    await page.waitForTimeout(400);
    const offFocus = await page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        const c = document.getElementById('coach-drawing-canvas');
        return {
            videoW: Math.round(v.getBoundingClientRect().width),
            canvasW: c.width,
        };
    });
    expect(Math.abs(offFocus.canvasW - offFocus.videoW)).toBeLessThanOrEqual(2);
});

test('keyboard tab order through the cockpit reaches all primary controls', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-match');

    // Focus the match select first, then walk forward several Tab presses
    // and collect the focused element ids.
    await page.locator('#coach-review-match').focus();
    const visited = new Set();
    visited.add('coach-review-match');
    for (let i = 0; i < 20; i++) {
        await page.keyboard.press('Tab');
        const id = await page.evaluate(() => document.activeElement?.id || document.activeElement?.tagName);
        if (id) visited.add(id);
    }
    // Critical interactive controls must be reachable via Tab from the start.
    const expected = [
        'coach-review-match',
        'coach-review-slot',
        'coach-review-save-top',
        'coach-review-focus-toggle',
    ];
    for (const id of expected) expect(visited).toContain(id);
});
