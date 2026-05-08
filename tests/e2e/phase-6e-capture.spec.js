// Phase 6e — capture screenshots for the
// docs/screenshots/phase-6e-viewer-feedback-details/ deliverable folder.
//
// Phase 6e ships the unified viewer review modal: the existing focused
// feedback player is the single review surface for video notes,
// observation notes (text + tactical-board), and clips. Cards are
// compact (no inline summary, no inline board); clicking a card opens
// the unified modal which shows the visual (video OR board) on top
// and the structured fields below.
//
// Logs in as the seeded `family1` (linked to roster #7 — Alex Park).
// Run from the repo root with the dev server up at :8090:
//   cd tests/e2e && npm run capture-phase-6e
//
// Same serial-mode wrapper as the 6d-1 / 6d-2 capture specs.
import { test, expect } from '@playwright/test';
import { login } from './_login.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, '../../docs/screenshots/phase-6e-viewer-feedback-details');
mkdirSync(OUT, { recursive: true });

const VIEWER = 'family1';
const PASS = 'Replay!Demo123';
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';

async function gotoFeedback(page, tab = 'notes') {
    await login(page, VIEWER, PASS);
    await page.goto(`/feedback?tab=${tab}`);
    await page.waitForFunction(() => !!window.app?._feedbackData);
    await page.waitForTimeout(400);
}

async function fullPage(page, name) {
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
}

async function modalShot(page, name) {
    await page.locator('.app-modal-card').first().screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function findNoteId(page, predicate) {
    return page.evaluate((predSrc) => {
        const fn = new Function('n', `return (${predSrc})(n)`);
        const notes = window.app._feedbackData?.notes || [];
        const hit = notes.find(fn);
        return hit ? hit.id : null;
    }, predicate.toString());
}

async function findClipId(page) {
    return page.evaluate(() => {
        const clips = window.app._feedbackData?.clips || [];
        return clips[0]?.id ?? null;
    });
}

test.use({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
test.describe.configure({ mode: 'serial' });
test.describe('Phase 6e — unified viewer review modal captures', () => {

test('01 — notes tab compact cards (no inline detail)', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    await fullPage(page, '01-notes-tab-compact-cards');
});

test('02 — video note unified review modal', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    const id = await findNoteId(page, (n) => (n.note_context || 'video') === 'video');
    expect(id, 'expected at least one visible video note for family1').toBeTruthy();
    await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
    await page.waitForSelector('.app-modal-card .feedback-player video');
    await page.waitForSelector('.app-modal-card [data-field="body"][data-context="video"]');
    await page.waitForTimeout(200);
    await modalShot(page, '02-video-note-unified-modal');
});

test('03 — observation note (no board) unified modal', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    const id = await findNoteId(page, (n) =>
        (n.note_context || 'video') === 'observation'
        && !(n.tactical_board_json && (n.tactical_board_json.tokens?.length || n.tactical_board_json.shapes?.length)),
    );
    if (!id) test.skip(true, 'No text-only observation visible to family1.');
    await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
    await page.waitForSelector('.app-modal-card [data-field="body"][data-context="observation"]');
    await page.waitForTimeout(200);
    await modalShot(page, '03-observation-no-board-unified-modal');
});

test('04 — tactical-board observation unified modal (board where video would be)', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    const id = await findNoteId(page, (n) =>
        (n.note_context || 'video') === 'observation'
        && !!n.tactical_board_json
        && ((n.tactical_board_json.tokens?.length || 0) + (n.tactical_board_json.shapes?.length || 0)) > 0,
    );
    expect(id, 'expected a tactical-board observation visible to family1').toBeTruthy();
    await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
    await page.waitForSelector('.app-modal-card .feedback-player-board svg');
    await page.waitForTimeout(200);
    await modalShot(page, '04-tactical-board-observation-unified-modal');
});

test('05 — clips tab compact cards', async ({ page }) => {
    await gotoFeedback(page, 'clips');
    const clipCount = await page.locator('#feedback-clips-list .feedback-card').count();
    if (clipCount === 0) test.skip(true, 'No clips visible to family1.');
    await fullPage(page, '05-clips-tab-compact-cards');
});

test('06 — clip unified review modal', async ({ page }) => {
    await gotoFeedback(page, 'clips');
    const id = await findClipId(page);
    if (!id) test.skip(true, 'No clip visible to family1.');
    await page.evaluate((cid) => { window.app.openFeedbackClip(cid); }, id);
    await page.waitForSelector('.app-modal-card .feedback-player video');
    await page.waitForSelector('.app-modal-card [data-field="body"][data-context="clip"]');
    await page.waitForTimeout(200);
    await modalShot(page, '06-clip-unified-modal');
});

test('07 — development tab with recent items (rows route into unified modal)', async ({ page }) => {
    await gotoFeedback(page, 'development');
    await page.waitForFunction(() => !!document.querySelector('#feedback-development-profile .player-dev-section'));
    await page.waitForTimeout(300);
    await fullPage(page, '07-development-tab-recent-items');
});

test('08 — mobile 390px observation unified modal', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoFeedback(page, 'notes');
    const id = await findNoteId(page, (n) =>
        (n.note_context || 'video') === 'observation'
        && !!n.tactical_board_json
        && ((n.tactical_board_json.tokens?.length || 0) + (n.tactical_board_json.shapes?.length || 0)) > 0,
    );
    if (!id) test.skip(true, 'No tactical-board observation visible to family1.');
    await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
    await page.waitForSelector('.app-modal-card .feedback-player-board');
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, '08-mobile-390-observation-unified-modal.png') });
});

test('09 — light mode video note unified modal', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
    const id = await findNoteId(page, (n) => (n.note_context || 'video') === 'video');
    expect(id, 'expected a video note for family1').toBeTruthy();
    await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
    await page.waitForSelector('.app-modal-card [data-field="body"][data-context="video"]');
    await page.waitForTimeout(200);
    await modalShot(page, '09-light-mode-video-note-unified-modal');
});

test('10 — privacy: coach_private_note never appears in viewer DOM or API', async ({ page }) => {
    await gotoFeedback(page, 'notes');
    // Two-layer privacy check:
    //  (a) the raw /api/my-feedback payload must not carry
    //      coach_private_note text (server-side _strip_private_fields).
    //  (b) every unified review modal we render must not template the
    //      canary either, even if a future code path tried to.
    const apiText = await page.evaluate(async () => {
        const token = sessionStorage.getItem('replay_admin_token');
        const r = await fetch('/api/my-feedback', { headers: { Authorization: 'Bearer ' + token } });
        return JSON.stringify(await r.json());
    });
    expect(/Coach note:/i.test(apiText), 'server payload leaked "Coach note:" canary').toBe(false);

    const ids = await page.evaluate(() => (window.app._feedbackData?.notes || []).map((n) => n.id));
    let leak = false;
    for (const id of ids) {
        await page.evaluate(() => {
            document.querySelectorAll('.app-modal').forEach((el) => el.remove());
        });
        await page.evaluate((nid) => { window.app.openFeedbackNote(nid); }, id);
        await page.waitForSelector('.app-modal-card [data-field="body"]', { state: 'attached' });
        const html = await page.locator('.app-modal-card').first().innerHTML();
        if (/coach_private_note/i.test(html) || /Coach note:/i.test(html)) {
            leak = true;
            break;
        }
    }
    expect(leak, 'coach_private_note canary leaked into viewer DOM').toBe(false);
});

}); // describe
