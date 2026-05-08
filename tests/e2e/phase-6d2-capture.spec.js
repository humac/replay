// Phase 6d-2 — capture screenshots for the
// docs/screenshots/phase-6d2-tactical-board-tools/ deliverable folder.
// Logs in as the seeded `coach1` (password lives in docs/_seed/seed.py)
// and exercises the new game-format / formation controls, zone resize
// handles, the updated tactical-board shortcut popover, and a mobile
// viewport check.
//
// Run from the repo root with the dev server already up at :8090:
//   cd tests/e2e && npm run capture-phase-6d2
//
// Same serial-mode wrapper rationale as the 6d-1 capture spec: the
// per-IP login rate limit (auth.py) trips when a Playwright project
// runs >1 worker against the same coach account.
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-6d2-tactical-board-tools');
mkdirSync(OUT, { recursive: true });

const COACH = 'coach1';
const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';

async function shotShell(page, name) {
    const shell = page.locator('#coach-tab-review .coach-review-shell');
    await shell.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });
test.describe('Phase 6d-2 — tactical board authoring captures', () => {

async function openTacticalBoard(page) {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('tactical_board'));
    await page.waitForTimeout(300);
}

test('01 — empty board with game format + formation selectors', async ({ page }) => {
    await openTacticalBoard(page);
    // Empty board so the "no players → applying replaces nothing" UX
    // is the first frame. Coach can pick a format / formation here.
    await page.evaluate(() => window.app._coachReviewBoardCtrl.loadScene(null));
    await page.waitForTimeout(150);
    await shotShell(page, '01-tactical-board-format-formation-controls');
});

test('02 — 7v7 2-3-1 applied', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => window.app._coachReviewBoardCtrl.loadScene(null));
    await page.evaluate(() => window.app._coachReviewBoardCtrl.applyFormation('7v7', '2-3-1'));
    await page.waitForTimeout(150);
    await shotShell(page, '02-7v7-2-3-1-formation');
});

test('03 — 9v9 3-2-3 applied', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => window.app._coachReviewBoardCtrl.loadScene(null));
    await page.evaluate(() => window.app._coachReviewBoardCtrl.applyFormation('9v9', '3-2-3'));
    await page.waitForTimeout(150);
    await shotShell(page, '03-9v9-3-2-3-formation');
});

test('04 — 11v11 4-3-3 applied', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => window.app._coachReviewBoardCtrl.loadScene(null));
    await page.evaluate(() => window.app._coachReviewBoardCtrl.applyFormation('11v11', '4-3-3'));
    await page.waitForTimeout(150);
    await shotShell(page, '04-11v11-4-3-3-formation');
});

test('05 — selected zone with resize handles visible', async ({ page }) => {
    await openTacticalBoard(page);
    // Build a scene with a zone and select it so the eight handles render.
    await page.evaluate(() => {
        const ctrl = window.app._coachReviewBoardCtrl;
        ctrl.loadScene({
            pitch_kind: 'soccer_full',
            tokens: [
                { kind: 'player', x: 0.20, y: 0.40, label: '4' },
                { kind: 'player', x: 0.20, y: 0.60, label: '5' },
                { kind: 'ball', x: 0.30, y: 0.50 },
            ],
            shapes: [
                { kind: 'zone', x: 0.45, y: 0.30, w: 0.35, h: 0.40 },
                { kind: 'arrow', x1: 0.30, y1: 0.50, x2: 0.55, y2: 0.50 },
            ],
        });
        // Select the zone so the eight resize handles render.
        const state = ctrl.getState();
        const zone = state.shapes.find((s) => s.kind === 'zone');
        ctrl.selectShapeById(zone.id);
    });
    await page.waitForTimeout(150);
    await shotShell(page, '05-zone-resize-handles');
});

test('10 — color swatches with multi-color shapes (telestrator parity)', async ({ page }) => {
    await openTacticalBoard(page);
    // Build a scene with one shape per palette color so the swatches +
    // colored shapes are both visible in a single frame. Mirrors the
    // video telestrator palette ['#38bdf8','#f97316','#22c55e',
    // '#facc15','#f43f5e','#ffffff'] one-for-one.
    await page.evaluate(() => {
        const ctrl = window.app._coachReviewBoardCtrl;
        ctrl.loadScene({
            pitch_kind: 'soccer_full',
            tokens: [
                { kind: 'player', x: 0.20, y: 0.50, label: '6' },
                { kind: 'ball', x: 0.50, y: 0.50 },
            ],
            shapes: [
                { kind: 'arrow', x1: 0.25, y1: 0.30, x2: 0.55, y2: 0.30, color: '#38bdf8' },
                { kind: 'arrow', x1: 0.25, y1: 0.70, x2: 0.55, y2: 0.70, color: '#f97316' },
                { kind: 'line',  x1: 0.55, y1: 0.20, x2: 0.78, y2: 0.40, color: '#22c55e' },
                { kind: 'zone',  x: 0.55, y: 0.45, w: 0.25, h: 0.20, color: '#facc15' },
                { kind: 'freehand', color: '#f43f5e', points: [
                    { x: 0.30, y: 0.85 }, { x: 0.40, y: 0.82 },
                    { x: 0.50, y: 0.80 }, { x: 0.60, y: 0.80 },
                    { x: 0.70, y: 0.82 },
                ]},
                { kind: 'label', x: 0.78, y: 0.20, text: 'switch', color: '#ffffff' },
            ],
        });
        // Arm a non-default color so the active swatch is visible.
        ctrl.setActiveColor('#f97316');
    });
    await page.waitForTimeout(200);
    await shotShell(page, '10-color-swatches-and-colored-shapes');
});

test('11 — stroke width control with visibly different line widths', async ({ page }) => {
    await openTacticalBoard(page);
    // Render multiple shapes with different stroke_width values so the
    // saved metadata is unmistakably visible. Slider armed at the mid
    // value (5) so the W control is visibly off-default.
    await page.evaluate(() => {
        const ctrl = window.app._coachReviewBoardCtrl;
        ctrl.loadScene({
            pitch_kind: 'soccer_full',
            tokens: [
                { kind: 'player', x: 0.15, y: 0.50, label: '6' },
            ],
            shapes: [
                { kind: 'line', x1: 0.30, y1: 0.20, x2: 0.85, y2: 0.20, color: '#38bdf8', stroke_width: 2 },
                { kind: 'line', x1: 0.30, y1: 0.35, x2: 0.85, y2: 0.35, color: '#22c55e', stroke_width: 4 },
                { kind: 'line', x1: 0.30, y1: 0.50, x2: 0.85, y2: 0.50, color: '#facc15', stroke_width: 6 },
                { kind: 'line', x1: 0.30, y1: 0.65, x2: 0.85, y2: 0.65, color: '#f97316', stroke_width: 8 },
                { kind: 'line', x1: 0.30, y1: 0.80, x2: 0.85, y2: 0.80, color: '#f43f5e', stroke_width: 10 },
            ],
        });
        ctrl.setActiveStrokeWidth(5);
    });
    await page.waitForTimeout(200);
    await shotShell(page, '11-stroke-width-control-and-thicknesses');
});

test('06 — tactical shortcuts popover (updated for 6d-2)', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => window.app.toggleCoachShortcutsHelp());
    await page.waitForTimeout(150);
    await shotShell(page, '06-tactical-shortcuts-popover');
});

test('07 — mobile 390px tactical board layout', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openTacticalBoard(page);
    await page.evaluate(() => window.app._coachReviewBoardCtrl.applyFormation('7v7', '2-3-1'));
    await page.waitForTimeout(200);
    await page.locator('#coach-tab-review .coach-review-shell').screenshot({
        path: path.join(OUT, '07-mobile-390-tactical-board.png'),
    });
});

test('08 — light mode tactical board with formation', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => {
        document.documentElement.dataset.theme = 'light';
    });
    await page.evaluate(() => window.app._coachReviewBoardCtrl.applyFormation('11v11', '4-2-3-1'));
    await page.waitForTimeout(150);
    await shotShell(page, '08-light-mode-11v11-4-2-3-1');
});

test('09 — saved observation (with formation metadata) visible in coach > notes', async ({ page }) => {
    await openTacticalBoard(page);
    await page.evaluate(() => {
        const ctrl = window.app._coachReviewBoardCtrl;
        ctrl.applyFormation('11v11', '4-3-3');
        document.getElementById('coach-tb-event-title').value = 'Phase 6d-2 capture — 4-3-3 build-up';
        document.getElementById('coach-tb-event-type').value = 'tactical';
        document.getElementById('coach-tb-title').value = 'Build out from the back in 4-3-3';
        document.getElementById('coach-tb-player-summary').value = 'GK plays to the CBs, FBs push high, 6 drops to receive.';
    });
    await page.locator('#coach-review-save-observation').click();
    await page.waitForTimeout(800);
    await page.goto('/coach?tab=notes');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.waitForTimeout(400);
    await page.locator('#coach-tab-notes').screenshot({
        path: path.join(OUT, '09-saved-observation-with-formation.png'),
    });
});

}); // describe
