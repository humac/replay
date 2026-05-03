// Sprint 6 "after" capture for the Coach Review redesign.
// Verifies the Wide / Focus mode toggle hides chrome, expands the video to
// near-full-width, exposes the inspector via a slide-over drawer, and exits
// cleanly on Escape and on Review-tab leave. Captures screenshots in
// normal / focus / focus+drawer states.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-6-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-6-after';
mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });

test('focus toggle exists in picker bar; drawer toggle hidden by default', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);

    const state = await page.evaluate(() => {
        const t = document.getElementById('coach-review-focus-toggle');
        const d = document.getElementById('coach-review-focus-inspector-toggle');
        return {
            toggleExists: !!t,
            toggleAriaPressed: t?.getAttribute('aria-pressed'),
            drawerToggleExists: !!d,
            drawerToggleHidden: d ? getComputedStyle(d).display === 'none' : null,
            focusModeFlag: window.app._coachFocusMode,
        };
    });
    expect(state.toggleExists).toBe(true);
    expect(state.toggleAriaPressed).toBe('false');
    expect(state.drawerToggleExists).toBe(true);
    expect(state.drawerToggleHidden).toBe(true);
    expect(state.focusModeFlag).toBe(false);
});

test('toggling focus mode hides chrome and expands the video (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-focus-toggle');

    const probe = async () => page.evaluate(() => {
        const wrapper = document.querySelector('.coach-review-wrapper');
        const head = document.querySelector('.coach-page-head');
        const sub = document.querySelector('.coach-subnav');
        const side = document.querySelector('.coach-review-side');
        const isVisible = (el) => el && getComputedStyle(el).display !== 'none';
        return {
            focusModeFlag: window.app._coachFocusMode,
            videoWidth: Math.round(wrapper?.getBoundingClientRect().width || 0),
            pageHeadVisible: isVisible(head),
            subnavVisible: isVisible(sub),
            sideVisible: isVisible(side),
            bodyHasClass: document.body.classList.contains('coach-focus-mode'),
            viewHasClass: document.getElementById('coach-view')?.classList.contains('is-focus-mode'),
        };
    });
    const before = await probe();
    expect(before.focusModeFlag).toBe(false);
    expect(before.pageHeadVisible).toBe(true);
    expect(before.sideVisible).toBe(true);

    await page.evaluate(() => window.app.toggleCoachFocusMode());
    await page.waitForTimeout(250);
    const on = await probe();
    expect(on.focusModeFlag).toBe(true);
    expect(on.pageHeadVisible).toBe(false);
    expect(on.subnavVisible).toBe(false);
    expect(on.sideVisible).toBe(false);
    expect(on.bodyHasClass).toBe(true);
    expect(on.viewHasClass).toBe(true);
    // Video should have grown by at least 200 px (typical at 1440 = video col
    // gains ~340 px once the inspector + grid gap collapse).
    expect(on.videoWidth - before.videoWidth).toBeGreaterThan(200);

    await page.screenshot({ path: `${OUT}/focus-on-1440.png`, fullPage: false });
});

test('drawer slides in over the video and dims the backdrop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.evaluate(() => window.app.openCoachFocusInspector());
    await page.waitForTimeout(250);

    const state = await page.evaluate(() => {
        const side = document.querySelector('.coach-review-side');
        const backdrop = document.getElementById('coach-focus-backdrop');
        const drawerToggle = document.getElementById('coach-review-focus-inspector-toggle');
        return {
            sidePosition: side ? getComputedStyle(side).position : null,
            sideWidth: side ? Math.round(side.getBoundingClientRect().width) : 0,
            backdropExists: !!backdrop,
            backdropHidden: backdrop?.hidden,
            drawerToggleAria: drawerToggle?.getAttribute('aria-pressed'),
            inspectorOpenFlag: window.app._coachFocusInspectorOpen,
        };
    });
    expect(state.sidePosition).toBe('fixed');
    expect(state.sideWidth).toBeGreaterThan(300);
    expect(state.backdropExists).toBe(true);
    expect(state.backdropHidden).toBe(false);
    expect(state.drawerToggleAria).toBe('true');
    expect(state.inspectorOpenFlag).toBe(true);

    await page.screenshot({ path: `${OUT}/focus-drawer-1440.png`, fullPage: false });
});

test('Escape closes the drawer first, then exits focus mode', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.evaluate(() => window.app.openCoachFocusInspector());
    await page.waitForTimeout(150);

    // First Escape: drawer closes, focus mode stays on
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
    const after1 = await page.evaluate(() => ({
        focus: window.app._coachFocusMode,
        drawerOpen: window.app._coachFocusInspectorOpen,
    }));
    expect(after1.focus).toBe(true);
    expect(after1.drawerOpen).toBe(false);

    // Second Escape: focus mode exits
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    const after2 = await page.evaluate(() => ({
        focus: window.app._coachFocusMode,
        bodyHasClass: document.body.classList.contains('coach-focus-mode'),
        listenerCleaned: window.app._coachFocusEscapeHandler === null,
    }));
    expect(after2.focus).toBe(false);
    expect(after2.bodyHasClass).toBe(false);
    expect(after2.listenerCleaned).toBe(true);
});

test('leaving the Review sub-tab exits focus mode automatically', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.waitForTimeout(150);
    expect(await page.evaluate(() => window.app._coachFocusMode)).toBe(true);

    // Switch to Roster sub-tab
    await page.evaluate(() => window.app.setCoachTab('roster'));
    await page.waitForTimeout(200);

    const after = await page.evaluate(() => ({
        focus: window.app._coachFocusMode,
        viewHasClass: document.getElementById('coach-view')?.classList.contains('is-focus-mode'),
        bodyHasClass: document.body.classList.contains('coach-focus-mode'),
    }));
    expect(after.focus).toBe(false);
    expect(after.viewHasClass).toBe(false);
    expect(after.bodyHasClass).toBe(false);
});

test('clicking the backdrop closes the drawer (does not exit focus mode)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.evaluate(() => window.app.openCoachFocusInspector());
    await page.waitForTimeout(200);

    await page.click('#coach-focus-backdrop');
    await page.waitForTimeout(200);

    const state = await page.evaluate(() => ({
        focus: window.app._coachFocusMode,
        drawerOpen: window.app._coachFocusInspectorOpen,
        backdropHidden: document.getElementById('coach-focus-backdrop')?.hidden,
    }));
    expect(state.focus).toBe(true);
    expect(state.drawerOpen).toBe(false);
    expect(state.backdropHidden).toBe(true);
});

test('focus state does NOT persist across page reloads (session-local)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.evaluate(() => window.app.enterCoachFocusMode());
    await page.waitForTimeout(150);

    // Reload — focus state should reset
    await page.reload();
    await page.waitForFunction(() => Array.isArray(window.app?.matches), null, { timeout: 5000 });
    await page.waitForTimeout(200);

    const state = await page.evaluate(() => ({
        focus: window.app._coachFocusMode,
        viewHasClass: document.getElementById('coach-view')?.classList.contains('is-focus-mode'),
    }));
    expect(state.focus).toBe(false);
    expect(state.viewHasClass).toBe(false);
});

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
];

for (const w of widths) {
    test(`focus mode capture @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.evaluate(() => window.app.enterCoachFocusMode());
        await page.waitForTimeout(250);
        await page.screenshot({ path: `${OUT}/focus-${w.label}-top.png`, fullPage: false });
    });
}
