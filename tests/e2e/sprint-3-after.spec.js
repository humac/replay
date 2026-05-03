// Sprint 3 "after" capture for the Coach Review redesign.
// Verifies the icon-first telestrator toolbar replaces the text-labelled
// `.mini-action-btn` grid, asserts every tool button carries title + aria-label
// + aria-pressed, captures pointer-fine and pointer-coarse screenshots, and
// exercises the Sprint 3 acceptance criteria from
// docs/coach-review-ui-ux-implementation-plan.md.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-3-after.spec.js

import { test, expect, devices } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-3-after';
mkdirSync(OUT, { recursive: true });

async function toolbarMetrics(page) {
    return page.evaluate(() => {
        const dim = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { w: Math.round(r.width), h: Math.round(r.height) };
        };
        const btns = Array.from(document.querySelectorAll('.coach-tool-btn'));
        const colors = Array.from(document.querySelectorAll('.coach-color-swatch'));
        const firstBtn = btns[0];
        return {
            viewport: { w: window.innerWidth, h: window.innerHeight },
            toolbar: dim('#coach-review-toolbar'),
            toolGrid: dim('.coach-tool-grid'),
            toolBtnCount: btns.length,
            toolBtnSize: firstBtn ? Math.round(firstBtn.getBoundingClientRect().height) : null,
            allHaveAria: btns.every((b) =>
                b.getAttribute('aria-label') &&
                b.getAttribute('title') &&
                b.hasAttribute('aria-pressed'),
            ),
            allTools: btns.map((b) => b.dataset.coachTool),
            colorSwatchAriaCount: colors.filter((c) => c.getAttribute('aria-label')?.startsWith('Color: ')).length,
            telestratorRole: document.querySelector('.coach-telestrator')?.getAttribute('role'),
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
    test(`icon toolbar @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('.coach-tool-btn');

        const m = await toolbarMetrics(page);
        console.log(`[${w.label}] toolbar:`, JSON.stringify(m, null, 2));

        await page.screenshot({ path: `${OUT}/toolbar-${w.label}-top.png`, fullPage: false });

        // Sprint 3 acceptance: 9 tools present + every tool has title + aria-label + aria-pressed
        expect(m.toolBtnCount).toBe(9);
        expect(m.allTools.sort()).toEqual(['arrow', 'circle', 'dim', 'formation', 'freehand', 'label', 'select', 'spotlight', 'zone']);
        expect(m.allHaveAria).toBe(true);
        expect(m.colorSwatchAriaCount).toBe(6);
        expect(m.telestratorRole).toBe('toolbar');

        // Pointer-aware sizing: at desktop widths (≥1024) the buttons should be
        // close to the 34px compact target. At narrower widths the button
        // should be at least 44px (touch target).
        if (w.width >= 1024) {
            // Desktop: 34px square (allow 30-40 for padding/border tolerance)
            expect(m.toolBtnSize).toBeGreaterThan(30);
            expect(m.toolBtnSize).toBeLessThan(45);
        } else {
            // Touch / narrow: at least 44px
            expect(m.toolBtnSize).toBeGreaterThanOrEqual(44);
        }
    });
}

test('aria-pressed updates when tool is changed', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-tool-btn');

    // Initial: freehand active by default
    const initial = await page.evaluate(() => ({
        freehand: document.querySelector('[data-coach-tool="freehand"]').getAttribute('aria-pressed'),
        arrow: document.querySelector('[data-coach-tool="arrow"]').getAttribute('aria-pressed'),
    }));
    expect(initial.freehand).toBe('true');
    expect(initial.arrow).toBe('false');

    // Click arrow → arrow becomes pressed, freehand un-pressed
    await page.click('[data-coach-tool="arrow"]');
    const after = await page.evaluate(() => ({
        freehand: document.querySelector('[data-coach-tool="freehand"]').getAttribute('aria-pressed'),
        arrow: document.querySelector('[data-coach-tool="arrow"]').getAttribute('aria-pressed'),
    }));
    expect(after.freehand).toBe('false');
    expect(after.arrow).toBe('true');
});

test('color swatch aria-pressed updates on selection', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-color-swatch');

    await page.click('[data-coach-color="#22c55e"]');
    const after = await page.evaluate(() => ({
        green: document.querySelector('[data-coach-color="#22c55e"]').getAttribute('aria-pressed'),
        sky: document.querySelector('[data-coach-color="#38bdf8"]').getAttribute('aria-pressed'),
    }));
    expect(after.green).toBe('true');
    expect(after.sky).toBe('false');
});

test('canvas-toggle button aria-pressed mirrors active state', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('[data-coach-canvas-toggle]');

    // Activate the canvas
    await page.evaluate(() => app.activateCoachCanvas());
    const onState = await page.evaluate(() => ({
        text: document.querySelector('[data-coach-canvas-toggle]').textContent,
        aria_pressed: document.querySelector('[data-coach-canvas-toggle]').getAttribute('aria-pressed'),
    }));
    expect(onState.text).toBe('Canvas On');
    expect(onState.aria_pressed).toBe('true');

    await page.evaluate(() => app.deactivateCoachCanvas());
    const offState = await page.evaluate(() => ({
        text: document.querySelector('[data-coach-canvas-toggle]').textContent,
        aria_pressed: document.querySelector('[data-coach-canvas-toggle]').getAttribute('aria-pressed'),
    }));
    expect(offState.text).toBe('Canvas Off');
    expect(offState.aria_pressed).toBe('false');
});

test('tablet emulation gives ≥44px tap targets', async ({ browser }) => {
    // Use Playwright's iPad Mini device profile so we exercise the
    // pointer:coarse path of the responsive CSS.
    const ctx = await browser.newContext({ ...devices['iPad Mini'] });
    const page = await ctx.newPage();
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-tool-btn');

    const sizes = await page.evaluate(() =>
        Array.from(document.querySelectorAll('.coach-tool-btn')).map((b) => Math.round(b.getBoundingClientRect().height)),
    );
    expect(sizes.length).toBe(9);
    for (const h of sizes) {
        expect(h).toBeGreaterThanOrEqual(44);
    }

    await page.screenshot({ path: `${OUT}/toolbar-ipad-mini-top.png`, fullPage: false });
    await ctx.close();
});
