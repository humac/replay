// Smoke coverage for the single-team VOD + live app: the public surface
// renders, removed surfaces 404, and the admin console boots for an admin.
//
// The app must be running at PLAYWRIGHT_BASE_URL (default
// http://127.0.0.1:8091) before this runs. Provide the admin password via
// ADMIN_PASS (must match the running server's ADMIN_PASS).
//
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8091 ADMIN_PASS=... npx playwright test

import { test, expect } from '@playwright/test';
import { login, gotoAndSettle } from './_login.js';

const ADMIN_PASS = process.env.ADMIN_PASS || 'ReplayLocalAdmin123!';

test.describe('public surface', () => {
    test('season view renders', async ({ page }) => {
        await gotoAndSettle(page, '/');
        await expect(page.locator('#season-view')).toHaveClass(/active/);
    });

    test('live page renders', async ({ page }) => {
        await gotoAndSettle(page, '/live');
        await expect(page.locator('#live-view')).toHaveClass(/active/);
    });

    test('matches API responds with a list', async ({ page }) => {
        const resp = await page.request.get('/api/matches');
        expect(resp.ok()).toBeTruthy();
        expect(Array.isArray(await resp.json())).toBeTruthy();
    });

    test('removed surfaces 404', async ({ page }) => {
        for (const path of ['/coach', '/feedback', '/me', '/welcome',
                            '/api/me', '/api/admin/teams', '/api/admin/email/status']) {
            const resp = await page.request.get(path);
            expect(resp.status(), `${path} should be 404`).toBe(404);
        }
    });
});

test.describe('admin console', () => {
    test('admin can open the dashboard and users section', async ({ page }) => {
        await login(page, 'admin', ADMIN_PASS);
        await gotoAndSettle(page, '/admin/overview');
        await expect(page.locator('#admin-view')).toHaveClass(/active/);
        await gotoAndSettle(page, '/admin/users');
        await expect(page.locator('#admin-view')).toHaveClass(/active/);
    });
});
