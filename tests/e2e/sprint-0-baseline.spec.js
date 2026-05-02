// Sprint 0 baseline screenshot capture for the Coach Review redesign.
// Reads BASE_URL (default http://127.0.0.1:8090), logs in as coach1 via the
// existing seed user, drives the Review tab through several states, and saves
// PNGs to docs/screenshots/sprint-0-baseline/.
//
// Run from this folder once the app is up at PLAYWRIGHT_BASE_URL:
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-0-baseline.spec.js
//
// Sprint-1+ should NOT update these files; they are the before-state record.

import { test, expect } from '@playwright/test';
import { mkdirSync } from 'fs';
import { dirname } from 'path';

const COACH_USER = 'coach1';
const COACH_PASS = 'Replay!Demo123';
const FAMILY_USER = 'family1';
const FAMILY_PASS = 'Replay!Demo123';
const SEEDED_MATCH_ID = 'e6bee436-d568-422e-a2a4-cc1339c86a12';

const OUT = '../../docs/screenshots/sprint-0-baseline';

mkdirSync(OUT, { recursive: true });

async function login(page, user, pass) {
    await page.goto('/');
    const token = await page.evaluate(async ({ u, p }) => {
        const r = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
        });
        const j = await r.json();
        sessionStorage.setItem('replay_admin_token', j.token);
        return j.token;
    }, { u: user, p: pass });
    return token;
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

test.describe.configure({ mode: 'serial' });

for (const w of widths) {
    test(`coach review baseline @ ${w.label}`, async ({ page }) => {
        await page.setViewportSize({ width: w.width, height: w.height });
        await login(page, COACH_USER, COACH_PASS);
        await page.goto(`/coach?tab=review&match=${SEEDED_MATCH_ID}&slot=full`);
        await page.waitForSelector('#coach-review-toolbar .coach-tool-grid');
        await page.waitForTimeout(800);

        const measured = await dims(page);
        console.log(`[${w.label}] dims:`, JSON.stringify(measured, null, 2));

        await page.screenshot({
            path: `${OUT}/coach-review-${w.label}-top.png`,
            fullPage: false,
        });
        await page.screenshot({
            path: `${OUT}/coach-review-${w.label}-fullpage.png`,
            fullPage: true,
        });

        // Sanity: required selectors still present
        await expect(page.locator('#coach-tab-review')).toBeVisible();
        await expect(page.locator('#coach-review-match')).toBeAttached();
        await expect(page.locator('#coach-review-slot')).toBeAttached();
        await expect(page.locator('#coach-review-toolbar')).toBeVisible();
        await expect(page.locator('#coach-review-form')).toBeVisible();
        await expect(page.locator('#coach-review-notes')).toBeVisible();
    });
}

test('public match page (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/');
    await page.waitForSelector('.match-card', { timeout: 5000 }).catch(() => {});
    await page.screenshot({ path: `${OUT}/public-season-1440.png`, fullPage: false });
});

test('coach roster tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/coach?tab=roster');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/coach-roster-1440.png`, fullPage: true });
});

test('coach notes tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/coach?tab=notes');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/coach-notes-1440.png`, fullPage: true });
});

test('coach playlists tab (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, COACH_USER, COACH_PASS);
    await page.goto('/coach?tab=playlists');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/coach-playlists-1440.png`, fullPage: true });
});

test('feedback notes tab (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await page.goto('/feedback?tab=notes');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/feedback-notes-1440.png`, fullPage: true });
});

test('feedback playlists tab (family1, 1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, FAMILY_USER, FAMILY_PASS);
    await page.goto('/feedback?tab=playlists');
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/feedback-playlists-1440.png`, fullPage: true });
});
