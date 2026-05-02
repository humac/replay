// Sprint 0 baseline screenshot capture for the Coach Review redesign.
// Reads BASE_URL (default http://127.0.0.1:8090), logs in as coach1 via the
// existing seed user, drives the Review tab through several states, and saves
// PNGs to docs/screenshots/sprint-0-baseline/.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL with the
// canonical seed (docs/_seed/seed.py from main):
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-0-baseline.spec.js
//
// IMPORTANT: this captures the BEFORE state. To regenerate the baseline you
// must run it against a checkout that does NOT include the Sprint 1
// is-review-mode changes (e.g. `git stash` styles.css + js/coaching.js first).
// Sprint 1+ should NOT update these files in normal use; they are the
// before-state record.

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';
const FAMILY_USER = 'family1';
const FAMILY_PASS = 'Replay!Demo123';

const OUT = '../../docs/screenshots/sprint-0-baseline';
mkdirSync(OUT, { recursive: true });

// Cache tokens per username so we don't trip the 5-logins-per-IP backend rate
// limit while the spec authenticates ~12 times across all tests.
const _tokenCache = {};

async function login(page, user, pass) {
    // Acquire a token via the API (out of page), then inject it into
    // sessionStorage on EVERY future page load via addInitScript. This
    // guarantees `app.canCoach()` is true during init() on the first
    // navigation, so /coach?tab=* doesn't bounce to the season fallback.
    const baseURL = page.context()._options?.baseURL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';
    if (!_tokenCache[user]) {
        const resp = await page.request.post(`${baseURL}/api/login`, {
            data: { username: user, password: pass },
        });
        const j = await resp.json();
        _tokenCache[user] = j.token;
    }
    const token = _tokenCache[user];
    await page.addInitScript((t) => {
        sessionStorage.setItem('replay_admin_token', t);
    }, token);
    return token;
}

async function gotoAndSettle(page, url) {
    await page.goto(url);
    await page.waitForFunction(() => Array.isArray(window.app?.matches), null, { timeout: 5000 });
    await page.waitForFunction(() => document.querySelector('.view.active') !== null, null, { timeout: 5000 });
    await page.waitForTimeout(200);
}

async function pickMatchWithMostNotes(page, token) {
    const baseURL = page.context()._options?.baseURL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';
    const resp = await page.request.get(`${baseURL}/api/coach/notes`, {
        headers: { Authorization: 'Bearer ' + token },
    });
    const j = await resp.json();
    const counts = {};
    (j.notes || []).forEach((n) => { counts[n.match_id] = (counts[n.match_id] || 0) + 1; });
    let bestId = null, bestN = 0;
    for (const [id, n] of Object.entries(counts)) if (n > bestN) { bestN = n; bestId = id; }
    return bestId;
}

async function dims(page) {
    return page.evaluate(() => {
        const dim = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top) };
        };
        return {
            viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio },
            grid: dim('.coach-review-grid'),
            video: dim('#coach-review-video'),
            wrapper: dim('.coach-review-wrapper'),
            sidePanel: dim('.coach-review-side'),
            shell: dim('.coach-review-shell'),
            picker: dim('.coach-review-picker'),
            subnav: dim('.coach-subnav'),
            toolbar: dim('#coach-review-toolbar'),
            form: dim('#coach-review-form'),
            notes: dim('#coach-review-notes'),
            chromeAboveVideo: dim('.coach-review-wrapper')?.top || null,
        };
    });
}

const widths = [
    { label: '1920-wide', width: 1920, height: 1080 },
    { label: '1440-desktop', width: 1440, height: 900 },
    { label: '1024-laptop', width: 1024, height: 768 },
    { label: '768-tablet', width: 768, height: 1024 },
    { label: '390-mobile', width: 390, height: 844 },
];

// Run all tests serially. The parallel default lets concurrent tests race the
// dev server, which has caused the regression-tab captures to occasionally
// land on the season fallback. Serial is plenty fast (~13s for the whole spec).
test.describe.configure({ mode: 'serial' });

for (const w of widths) {
    test(`coach review baseline @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        const token = await login(page, COACH_USER, COACH_PASS);
        const matchId = await pickMatchWithMostNotes(page, token);
        await gotoAndSettle(page, `/coach?tab=review&match=${matchId}&slot=full`);
        await page.waitForSelector('#coach-review-toolbar .coach-tool-grid');

        const measured = await dims(page);
        console.log(`[${w.label}] dims:`, JSON.stringify(measured, null, 2));

        await page.screenshot({ path: `${OUT}/coach-review-${w.label}-top.png`, fullPage: false });
        await page.screenshot({ path: `${OUT}/coach-review-${w.label}-fullpage.png`, fullPage: true });

        await expect(page.locator('#coach-tab-review')).toBeVisible();
        await expect(page.locator('#coach-review-match')).toBeAttached();
        await expect(page.locator('#coach-review-slot')).toBeAttached();
        await expect(page.locator('#coach-review-toolbar')).toBeVisible();
        await expect(page.locator('#coach-review-form')).toBeVisible();
        await expect(page.locator('#coach-review-notes')).toBeAttached();
    });
}

test('public season page (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/');
    await page.screenshot({ path: `${OUT}/public-season-1440.png`, fullPage: false });
});

test('coach roster tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=roster');
    await page.waitForSelector('#coach-tab-roster:not([hidden]) #coach-roster-list', { timeout: 5000 });
    await expect(page.locator('#coach-tab-roster:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-roster-1440.png`, fullPage: true });
});

test('coach notes tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=notes');
    await page.waitForSelector('#coach-tab-notes:not([hidden]) #coach-notes-list', { timeout: 5000 });
    await expect(page.locator('#coach-tab-notes:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-notes-1440.png`, fullPage: true });
});

test('coach playlists tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await gotoAndSettle(page, '/coach?tab=playlists');
    await page.waitForSelector('#coach-tab-playlists:not([hidden]) #coach-playlists-list', { timeout: 5000 });
    await expect(page.locator('#coach-tab-playlists:not([hidden])')).toBeVisible();
    await page.screenshot({ path: `${OUT}/coach-playlists-1440.png`, fullPage: true });
});

test('feedback notes tab (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await gotoAndSettle(page, '/feedback?tab=notes');
    await page.waitForSelector('#feedback-tab-notes:not([hidden])', { timeout: 5000 });
    await page.screenshot({ path: `${OUT}/feedback-notes-1440.png`, fullPage: true });
});

test('feedback playlists tab (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await gotoAndSettle(page, '/feedback?tab=playlists');
    await page.waitForSelector('#feedback-tab-playlists:not([hidden])', { timeout: 5000 });
    await page.screenshot({ path: `${OUT}/feedback-playlists-1440.png`, fullPage: true });
});
