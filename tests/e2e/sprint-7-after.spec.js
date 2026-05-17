// Sprint 7 "after" capture for the Coach Review redesign.
// Verifies the keyboard shortcut layer scoped to Coach > Review:
// install/uninstall on tab change, no interception while typing, tool
// selection, video seek, save, focus-mode Escape coexistence, and the
// shortcuts help popover.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8091 npx playwright test sprint-7-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-7-after';
mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });

test('shortcuts handler installs on Review and uninstalls on Roster', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);

    expect(await page.evaluate(() => !!window.app._coachShortcutsHandler)).toBe(true);

    await page.evaluate(() => window.app.setCoachTab('roster'));
    await page.waitForTimeout(150);
    expect(await page.evaluate(() => !!window.app._coachShortcutsHandler)).toBe(false);

    // Returning to Review re-installs.
    await page.evaluate(() => window.app.setCoachTab('review'));
    await page.waitForTimeout(150);
    expect(await page.evaluate(() => !!window.app._coachShortcutsHandler)).toBe(true);
});

test('tool letter keys switch the active drawing tool', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-tool-btn');
    // Click into the body so the keypress isn't sent to a focused form control.
    await page.locator('body').click({ position: { x: 5, y: 5 } });

    const cases = [
        ['a', 'arrow'],
        ['f', 'freehand'],
        ['z', 'zone'],
        ['c', 'circle'],
        ['t', 'label'],
        ['d', 'spotlight'],
    ];
    for (const [key, expected] of cases) {
        await page.keyboard.press(key);
        await page.waitForTimeout(50);
        const tool = await page.evaluate(() => window.app._coachDrawingTool);
        expect(tool).toBe(expected);
    }
});

test('typing in a text input does NOT trigger the shortcut handler', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-title');

    const titleBefore = await page.evaluate(() => window.app._coachDrawingTool);
    // Focus the title input and type "afzc" — these would all trigger tool
    // changes if the shortcut handler intercepted them.
    await page.locator('#coach-review-title').focus();
    await page.keyboard.type('afzc');
    await page.waitForTimeout(100);

    const titleAfter = await page.evaluate(() => ({
        title: document.getElementById('coach-review-title').value,
        tool: window.app._coachDrawingTool,
    }));
    expect(titleAfter.title).toBe('afzc');
    // Tool must NOT have changed mid-typing.
    expect(titleAfter.tool).toBe(titleBefore);
});

test('Space toggles play/pause when not typing', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-video');
    await page.locator('body').click({ position: { x: 5, y: 5 } });

    // The seeded match has no real video file, so video.play() returns a
    // rejected promise; the handler swallows it. We just verify the
    // shortcut event was preventDefault'd (returned true via dispatchEvent).
    const defaultPrevented = await page.evaluate(() => {
        const ev = new KeyboardEvent('keydown', { key: ' ', cancelable: true });
        return !window.dispatchEvent(ev);  // dispatchEvent returns false if preventDefault was called
    });
    expect(defaultPrevented).toBe(true);
});

test('Arrow / J / L seek the video by the documented amounts', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-video');
    await page.locator('body').click({ position: { x: 5, y: 5 } });

    // Seed currentTime so the seek deltas are observable.
    await page.evaluate(() => {
        const v = document.getElementById('coach-review-video');
        v.currentTime = 100;
    });

    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(50);
    expect(await page.evaluate(() => document.getElementById('coach-review-video').currentTime)).toBeCloseTo(101, 1);

    await page.keyboard.press('Shift+ArrowLeft');
    await page.waitForTimeout(50);
    // Now should be ~91 (101 - 10)
    expect(await page.evaluate(() => document.getElementById('coach-review-video').currentTime)).toBeCloseTo(91, 1);

    await page.keyboard.press('l');
    await page.waitForTimeout(50);
    // Now should be ~96 (91 + 5)
    expect(await page.evaluate(() => document.getElementById('coach-review-video').currentTime)).toBeCloseTo(96, 1);

    await page.keyboard.press('j');
    await page.waitForTimeout(50);
    // Now should be ~91 (96 - 5)
    expect(await page.evaluate(() => document.getElementById('coach-review-video').currentTime)).toBeCloseTo(91, 1);
});

test('S triggers saveReviewNote (calls through to existing handler)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-save-form');
    await page.locator('body').click({ position: { x: 5, y: 5 } });

    // Stub saveReviewNote and verify the keypress invokes it.
    await page.evaluate(() => {
        window.__sCalled = 0;
        const orig = window.app.saveReviewNote.bind(window.app);
        window.app.saveReviewNote = function () { window.__sCalled++; return orig.apply(this, arguments); };
    });
    await page.keyboard.press('s');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => window.__sCalled)).toBe(1);
});

test('? toggles the shortcuts help popover', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-shortcuts-help', { state: 'attached' });
    await page.locator('body').click({ position: { x: 5, y: 5 } });

    expect(await page.evaluate(() => document.getElementById('coach-shortcuts-help').hidden)).toBe(true);
    // Use Shift+/ which is what ? actually is on a US layout
    await page.keyboard.press('?');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => document.getElementById('coach-shortcuts-help').hidden)).toBe(false);

    await page.screenshot({ path: `${OUT}/shortcuts-help-1440.png`, fullPage: false });

    await page.keyboard.press('?');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => document.getElementById('coach-shortcuts-help').hidden)).toBe(true);
});

test('Escape cancels formation draft when focus mode is OFF', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-tool-btn');

    // Start a formation draft programmatically (the seed has no video so
    // we can't click the canvas to add anchors; mimicking the state here).
    await page.evaluate(() => {
        window.app._coachFormationDraft = { mode: 'quick', anchors: [{ x: 0.5, y: 0.5 }], queuedPlayerIds: [] };
    });
    await page.keyboard.press('Escape');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => window.app._coachFormationDraft)).toBeNull();
});

test('shortcuts toggle button in the picker bar opens the help popover', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('#coach-review-shortcuts-toggle', { state: 'attached' });

    await page.click('#coach-review-shortcuts-toggle');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => document.getElementById('coach-shortcuts-help').hidden)).toBe(false);
});
