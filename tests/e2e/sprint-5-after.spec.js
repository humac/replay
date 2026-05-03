// Sprint 5 "after" capture for the Coach Review redesign.
// Verifies the timeline rail of note chips replaces the old stacked notes
// list under the right inspector. Captures screenshots, exercises clicking
// chips, asserts category dot colors / player indicators / aria state.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-5-after.spec.js

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { login, gotoAndSettle, pickMatchWithMostNotes } from './_login.js';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-5-after';
mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });

test('rail lives under the video grid (not in the inspector) at 1440', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-timeline-rail');

    const layout = await page.evaluate(() => {
        const rail = document.getElementById('coach-review-notes');
        const wrapper = document.querySelector('.coach-review-wrapper');
        const side = document.querySelector('.coach-review-side');
        const inspectorContains = side?.contains(rail) ?? false;
        const railRect = rail?.getBoundingClientRect();
        const videoRect = wrapper?.getBoundingClientRect();
        const sideRect = side?.getBoundingClientRect();
        return {
            railClass: rail?.className,
            railRole: rail?.getAttribute('role'),
            inspectorContainsRail: inspectorContains,
            railSpansFullWidth: getComputedStyle(rail).gridColumn,
            railIsBelowVideo: railRect && videoRect ? Math.round(railRect.top) >= Math.round(videoRect.bottom) - 2 : null,
            railIsBelowSide: railRect && sideRect ? Math.round(railRect.top) >= Math.round(sideRect.bottom) - 2 : null,
            railOverflowX: getComputedStyle(rail).overflowX,
        };
    });

    expect(layout.railClass).toContain('coach-timeline-rail');
    expect(layout.railRole).toBe('toolbar');
    // Sprint 5 critical: rail is NO LONGER inside .coach-review-side
    expect(layout.inspectorContainsRail).toBe(false);
    expect(layout.railSpansFullWidth).toBe('1 / -1');
    expect(layout.railIsBelowVideo).toBe(true);
    expect(layout.railIsBelowSide).toBe(true);
    expect(layout.railOverflowX).toBe('auto');

    await page.screenshot({ path: `${OUT}/timeline-rail-1440.png`, fullPage: true });
});

test('chips render with timestamp + player indicator + category dot + title', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-timeline-chip');

    const chips = await page.evaluate(() =>
        Array.from(document.querySelectorAll('.coach-timeline-chip')).map((c) => ({
            time: c.querySelector('.coach-timeline-chip-time')?.textContent,
            player: c.querySelector('.coach-timeline-chip-player')?.textContent,
            category: c.querySelector('.coach-timeline-chip-cat')?.dataset.cat,
            title: c.querySelector('.coach-timeline-chip-title')?.textContent,
            ariaLabel: c.getAttribute('aria-label'),
            ariaPressed: c.getAttribute('aria-pressed'),
        })),
    );
    expect(chips.length).toBeGreaterThan(0);
    for (const c of chips) {
        expect(c.time).toMatch(/^\d+:\d+$/);
        expect(c.player).toBeTruthy();
        expect(c.category).toBeTruthy();
        expect(c.title).toBeTruthy();
        expect(c.ariaLabel).toContain('Jump to');
        expect(c.ariaPressed).toBe('false');  // none active on first render
    }
});

test('clicking a chip routes through seekCoachReviewNote and marks active', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-timeline-chip');

    const result = await page.evaluate(async () => {
        const chip = document.querySelector('.coach-timeline-chip');
        const noteId = Number(chip.dataset.coachNoteId);
        chip.click();
        await new Promise((r) => setTimeout(r, 200));
        const refetched = document.querySelector(`.coach-timeline-chip[data-coach-note-id="${noteId}"]`);
        return {
            clickedNoteId: noteId,
            activeNoteId: window.app._coachActiveNoteId,
            isActive: refetched?.classList.contains('is-active'),
            ariaPressed: refetched?.getAttribute('aria-pressed'),
        };
    });
    expect(result.activeNoteId).toBe(result.clickedNoteId);
    expect(result.isActive).toBe(true);
    expect(result.ariaPressed).toBe('true');
});

test('switching slot clears active chip', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    const matchId = await pickMatchWithMostNotes(page, token);
    await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
    await page.waitForSelector('.coach-timeline-chip');

    // Click a chip
    await page.evaluate(() => document.querySelector('.coach-timeline-chip').click());
    await page.waitForTimeout(150);

    // Force slot change
    await page.evaluate(() => {
        const sel = document.getElementById('coach-review-slot');
        sel.value = 'first_half';
        window.app.handleCoachReviewSlotChange();
    });
    await page.waitForTimeout(200);

    const activeId = await page.evaluate(() => window.app._coachActiveNoteId);
    expect(activeId).toBeNull();
});

test('empty match shows the "no notes" empty state', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const token = await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, `/coach?tab=review`);
    await page.waitForSelector('.coach-timeline-rail');

    // Pick a match that has NO notes (one of the 12 placeholder matches in the seed)
    const emptyId = await page.evaluate(() => {
        // Walk the match select for an option whose match has no notes
        const sel = document.getElementById('coach-review-match');
        return Array.from(sel.options).find((o) => o.value && !window.app._coachBundle?.notes?.some((n) => n.match_id === o.value))?.value;
    });
    if (!emptyId) return;  // skip if every match has notes

    await page.evaluate((id) => {
        const sel = document.getElementById('coach-review-match');
        sel.value = id;
        window.app.handleCoachReviewMatchChange();
    }, emptyId);
    await page.waitForTimeout(300);

    const state = await page.evaluate(() => {
        const rail = document.getElementById('coach-review-notes');
        const empty = rail?.querySelector('.coach-timeline-empty');
        return {
            chipCount: rail?.querySelectorAll('.coach-timeline-chip').length,
            emptyVisible: !!empty,
            emptyText: empty?.textContent,
        };
    });
    expect(state.chipCount).toBe(0);
    expect(state.emptyVisible).toBe(true);
    expect(state.emptyText).toContain('No notes');
});

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '390-mobile', width: 390, height: 844 },
];

for (const w of widths) {
    test(`rail captures @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('.coach-timeline-chip');
        // Scroll the rail into view so the screenshot crop captures it
        await page.evaluate(() => {
            document.getElementById('coach-review-notes')?.scrollIntoView({ block: 'end' });
        });
        await page.screenshot({ path: `${OUT}/timeline-${w.label}-top.png`, fullPage: false });
    });
}
