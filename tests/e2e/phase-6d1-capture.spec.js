// Phase 6d-1 — capture screenshots of the unified Coach Review for the
// docs/screenshots/phase-6d1-unified-coach-review/ deliverable folder.
// Logs in as the seeded `coach1` and `family1` accounts (password lives
// in docs/_seed/seed.py). Uses page.screenshot() so the captured PNGs
// match what the user sees in the live preview, not a synthetic mock.
//
// Run from the repo root with the dev server already up at :8090:
//   cd tests/e2e && npx playwright test phase-6d1-capture.spec.js
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-6d1-unified-coach-review');
mkdirSync(OUT, { recursive: true });

const COACH = 'coach1';
const FAMILY = 'family1';
const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';

async function shotShell(page, name) {
    // Capture only the Coach Review shell area (not the full viewport
    // including page chrome) so each PNG focuses on what changed.
    const shell = page.locator('#coach-tab-review .coach-review-shell');
    await shell.screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function shotFull(page, name) {
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
}

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });

// `auth.py` has a per-IP login rate limit (5 / window) and this spec
// logs in twice per worker (coach1 + family1). Running with the
// default 6-worker config in `playwright.config.js` trips the limit
// and flakes captures 05 + 09. Wrapping the spec in a serial-mode
// describe block forces every test in this FILE to run sequentially
// inside a single worker — even if the caller forgets the
// `--workers=2` flag (the dedicated `npm run capture-phase-6d1`
// script in `tests/e2e/package.json` also pins it for the
// canonical invocation). `_login.js`'s 429-retry is the second
// line of defence.
//
// The trade-off: the capture suite runs ~30 s instead of ~8 s. That
// is acceptable for deliverable PNG generation; the suite is not on
// any CI gate.
test.describe.configure({ mode: 'serial' });
test.describe('Phase 6d-1 — unified Coach Review captures', () => {

test('01 — video mode picker bar + telestrator side panel', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('video'));
    // Pick a seeded video note's match so the timeline rail populates.
    await page.evaluate(async () => {
        const note = (window.app._coachBundle?.notes || [])
            .find((n) => (n.note_context || 'video') === 'video');
        if (note) {
            document.getElementById('coach-review-match').value = note.match_id;
            document.getElementById('coach-review-slot').value = note.slot || 'full';
            await window.app.loadCoachReviewVideo(note.match_id, note.slot || 'full', 0, null);
        }
    });
    await page.waitForTimeout(400);
    await shotShell(page, '01-coach-review-video-mode');
});

test('02 — tactical board mode picker bar + tactical tools', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('tactical_board'));
    await page.waitForTimeout(300);
    // Load a sample scene + pre-fill picker fields so the screenshot
    // proves the board renders content end-to-end.
    await page.evaluate(() => {
        window.app._coachReviewBoardCtrl.loadScene({
            pitch_kind: 'soccer_full',
            tokens: [
                { kind: 'player', x: 0.20, y: 0.30, label: '2' },
                { kind: 'player', x: 0.20, y: 0.50, label: '5' },
                { kind: 'player', x: 0.20, y: 0.70, label: '3' },
                { kind: 'player', x: 0.42, y: 0.40, label: '8' },
                { kind: 'player', x: 0.42, y: 0.60, label: '10' },
                { kind: 'ball', x: 0.42, y: 0.50 },
            ],
            shapes: [
                { kind: 'arrow', x1: 0.42, y1: 0.50, x2: 0.78, y2: 0.30 },
                { kind: 'arrow', x1: 0.42, y1: 0.50, x2: 0.78, y2: 0.70 },
                { kind: 'zone', x: 0.55, y: 0.20, w: 0.30, h: 0.20 },
                { kind: 'freehand', points: [
                    { x: 0.25, y: 0.85 }, { x: 0.30, y: 0.82 }, { x: 0.35, y: 0.80 },
                    { x: 0.40, y: 0.78 }, { x: 0.45, y: 0.78 }, { x: 0.50, y: 0.79 },
                    { x: 0.55, y: 0.81 }, { x: 0.60, y: 0.82 }, { x: 0.65, y: 0.82 },
                ]},
                { kind: 'label', x: 0.70, y: 0.20, text: 'pin wide 7' },
            ],
        });
        document.getElementById('coach-tb-event-title').value = 'Tuesday practice — wide play';
        document.getElementById('coach-tb-event-date').value = '2026-05-07';
        document.getElementById('coach-tb-event-type').value = 'practice';
        document.getElementById('coach-tb-title').value = 'Switch the point of attack';
    });
    await page.waitForTimeout(200);
    await shotShell(page, '02-coach-review-tactical-board-mode');
});

test('03 — coach > notes management surface with routing buttons', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=notes');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.waitForTimeout(300);
    await page.locator('#coach-tab-notes').screenshot({ path: path.join(OUT, '03-coach-notes-routing-buttons.png') });
});

test('04 — coach > roster with add observation icon button', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=roster');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.waitForTimeout(300);
    await page.locator('#coach-tab-roster').screenshot({ path: path.join(OUT, '04-coach-roster-add-observation.png') });
});

test('05 — tactical board mode picker bar in focus mode (no wrap)', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.waitForTimeout(200);
    await page.evaluate(() => window.app.setCoachReviewSource('tactical_board'));
    await page.waitForTimeout(300);
    // enterCoachFocusMode briefly window.scrollTo's; calling
    // requestAnimationFrame here gives the layout a tick to settle
    // before the screenshot.
    await page.evaluate(() => new Promise((r) => {
        window.app.enterCoachFocusMode();
        requestAnimationFrame(() => requestAnimationFrame(r));
    }));
    await page.waitForTimeout(300);
    // Screenshot only the picker bar so the deliverable focuses on the
    // single-row layout proof; the full pitch is already covered in 02.
    await page.locator('.coach-review-picker').screenshot({
        path: path.join(OUT, '05-tactical-board-focus-mode-picker.png'),
    });
});

test('06 — tactical board focus drawer (board tools only)', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('tactical_board'));
    await page.waitForTimeout(300);
    await page.evaluate(async () => {
        // Arm a tool so the status pill is visible — proves the
        // pitch-readable status overlay works end-to-end.
        window.app.enterCoachFocusMode();
        await new Promise((r) => setTimeout(r, 100));
        window.app.openCoachFocusInspector();
        await new Promise((r) => setTimeout(r, 100));
        document.querySelector('[data-coach-tb-tool="player"]')?.click();
    });
    await page.waitForTimeout(300);
    await shotFull(page, '06-tactical-board-focus-drawer');
});

test('07 — video focus drawer (telestrator only, regression check)', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('video'));
    await page.waitForTimeout(300);
    await page.evaluate(async () => {
        window.app.enterCoachFocusMode();
        await new Promise((r) => setTimeout(r, 100));
        window.app.openCoachFocusInspector();
    });
    await page.waitForTimeout(300);
    await shotFull(page, '07-video-focus-drawer');
});

test('08 — saved observation appears in coach > notes (full E2E)', async ({ page }) => {
    await login(page, COACH, PASS);
    await page.goto('/coach?tab=review');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.evaluate(() => window.app.setCoachReviewSource('tactical_board'));
    await page.waitForTimeout(300);
    // Build + save an observation through the actual button.
    await page.evaluate(() => {
        window.app._coachReviewBoardCtrl.loadScene({
            pitch_kind: 'soccer_full',
            tokens: [{ kind: 'player', x: 0.4, y: 0.5, label: '7' }, { kind: 'ball', x: 0.5, y: 0.5 }],
            shapes: [
                { kind: 'arrow', x1: 0.4, y1: 0.5, x2: 0.7, y2: 0.4 },
                { kind: 'freehand', points: [
                    { x: 0.2, y: 0.7 }, { x: 0.3, y: 0.65 }, { x: 0.4, y: 0.6 }, { x: 0.5, y: 0.6 },
                ]},
                { kind: 'label', x: 0.6, y: 0.3, text: 'switch' },
            ],
        });
        document.getElementById('coach-tb-event-title').value = 'Phase 6d-1 capture — wide switch';
        document.getElementById('coach-tb-event-type').value = 'practice';
        document.getElementById('coach-tb-title').value = 'Switch the field early';
        document.getElementById('coach-tb-player-summary').value = 'When the ball comes back to a CB, scan and switch.';
    });
    await page.locator('#coach-review-save-observation').click();
    await page.waitForTimeout(800);
    await page.goto('/coach?tab=notes');
    await page.waitForFunction(() => !!window.app?._coachBundle);
    await page.waitForTimeout(400);
    await page.locator('#coach-tab-notes').screenshot({ path: path.join(OUT, '08-saved-observation-in-notes-list.png') });
});

test('09 — viewer (family1) my-feedback notes (privacy regression)', async ({ page }) => {
    await login(page, FAMILY, PASS);
    await page.goto('/feedback?tab=notes');
    // The /feedback URL boots into the Feedback view automatically;
    // waitForFunction polls until _feedbackData populates. The view
    // also waits for the linked-player strip to render.
    await page.waitForFunction(() => !!(window.app?._feedbackData?.notes?.length >= 0), null, { timeout: 15000 });
    await page.waitForTimeout(400);
    await page.locator('#feedback-view').screenshot({
        path: path.join(OUT, '09-viewer-feedback-notes.png'),
    });
});
}); // end describe — Phase 6d-1 captures
