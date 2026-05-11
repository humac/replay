// Phase 4 — active team/season selector UI captures and stale-data guard.
//
// This spec keeps the server as the static/SPA host but mocks the small auth
// and /api/me contract needed to exercise the nav selector deterministically.
// Run from tests/e2e:
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8094 npm run capture-phase-4

import { test, expect } from '@playwright/test';
import path from 'path';

const SCREENSHOT_DIR = path.resolve(process.cwd(), '../../docs/screenshots/phase-4-active-scope');

const TEAM_ALPHA = {
    id: 'phase4-alpha',
    slug: 'phase4-alpha',
    name: 'Replay Academy 2012',
    role: 'coach',
    seasons: [
        { id: 'phase4-alpha-spring', team_id: 'phase4-alpha', name: 'Spring 2026', slug: 'spring-2026', starts_on: '2026-03-01', ends_on: '2026-06-01' },
        { id: 'phase4-alpha-fall', team_id: 'phase4-alpha', name: 'Fall 2026', slug: 'fall-2026', starts_on: '2026-08-01', ends_on: '2026-11-01' },
    ],
};

const TEAM_BRAVO = {
    id: 'phase4-bravo',
    slug: 'phase4-bravo',
    name: 'Northside Futsal 2014',
    role: 'team_admin',
    seasons: [
        { id: 'phase4-bravo-winter', team_id: 'phase4-bravo', name: 'Winter 2026', slug: 'winter-2026', starts_on: '2026-01-01', ends_on: '2026-02-28' },
    ],
};

function scopePayload(activeTeam = TEAM_ALPHA, activeSeason = TEAM_ALPHA.seasons[0], selectionRequired = false) {
    return {
        user: {
            id: 'phase4-coach',
            username: 'coach1',
            role: 'coach,uploader',
            display_name: 'Coach Demo',
            enabled: true,
            last_team_id: activeTeam.id,
            last_season_id: activeSeason.id,
        },
        memberships: [
            { team_id: TEAM_ALPHA.id, team_slug: TEAM_ALPHA.slug, team_name: TEAM_ALPHA.name, role: 'coach' },
            { team_id: TEAM_BRAVO.id, team_slug: TEAM_BRAVO.slug, team_name: TEAM_BRAVO.name, role: 'team_admin' },
        ],
        teams: [TEAM_ALPHA, TEAM_BRAVO],
        seasons: [...TEAM_ALPHA.seasons, ...TEAM_BRAVO.seasons],
        active_scope: { team: activeTeam, season: activeSeason },
        selection_required: selectionRequired,
    };
}

async function installScopeMocks(page) {
    let current = scopePayload();
    await page.addInitScript(() => sessionStorage.setItem('replay_admin_token', 'phase4-e2e-token'));
    await page.route('**/api/auth/check', async (route) => {
        await route.fulfill({
            contentType: 'application/json',
            body: JSON.stringify({ authenticated: true, username: 'coach1', role: 'coach', roles: ['coach', 'uploader'] }),
        });
    });
    await page.route('**/api/me', async (route) => {
        if (route.request().method() === 'GET') {
            await route.fulfill({ contentType: 'application/json', body: JSON.stringify(current) });
            return;
        }
        await route.fallback();
    });
    await page.route('**/api/me/scope', async (route) => {
        const request = route.request();
        expect(request.method()).toBe('PUT');
        const body = request.postDataJSON();
        const team = [TEAM_ALPHA, TEAM_BRAVO].find((item) => item.id === body.team_id);
        const season = team?.seasons.find((item) => item.id === body.season_id);
        expect(team, 'selected team exists in available teams').toBeTruthy();
        expect(season, 'selected season belongs to selected team').toBeTruthy();
        current = scopePayload(team, season);
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(current) });
    });
    await page.route('**/api/matches**', async (route) => {
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) });
    });
}

async function activateMockSession(page) {
    // Some browsers keep the init-script sessionStorage write isolated from
    // the app's first auth pass during static-capture runs. Re-run the real
    // auth lifecycle after navigation so the selector is exercised through
    // checkAuth() + loadMeScope(), not by directly mutating DOM state.
    await page.evaluate(async () => {
        sessionStorage.setItem('replay_admin_token', 'phase4-e2e-token');
        await window.app.checkAuth();
        window.app.hideLoginModal?.();
    });
}

test.describe('Phase 4 — active scope selector', () => {
    test('captures themed multi-team selector and verifies switch behavior', async ({ page }) => {
        await installScopeMocks(page);
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto('/');
        await activateMockSession(page);
        await expect(page.locator('#nav-scope-switcher')).toBeVisible();
        await expect(page.locator('#nav-scope-label')).toHaveText('Replay Academy 2012 · Spring 2026');

        await page.locator('#nav-scope-switcher').screenshot({ path: path.join(SCREENSHOT_DIR, '01-nav-scope-closed-dark.png') });

        await page.click('#nav-scope-trigger');
        await expect(page.locator('#nav-scope-panel')).toBeVisible();
        await expect(page.locator('#nav-scope-team')).toHaveValue(TEAM_ALPHA.id);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02-nav-scope-panel-dark.png'), fullPage: true });

        await page.selectOption('#nav-scope-team', TEAM_BRAVO.id);
        await expect(page.locator('#nav-scope-label')).toHaveText('Northside Futsal 2014 · Winter 2026');
        await expect(page.locator('#nav-scope-help')).toContainText('Changes are saved');
        await expect(page.locator('text=Replay Academy 2012 · Spring 2026')).toHaveCount(0);

        await page.click('#theme-toggle-btn');
        await expect(page.locator('#nav-scope-panel')).toBeVisible();
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03-nav-scope-panel-light.png'), fullPage: true });
    });

    test('clears scoped coach/feedback DOM placeholders before reloading bundles', async ({ page }) => {
        await installScopeMocks(page);
        await page.goto('/');
        await activateMockSession(page);
        await page.evaluate(() => {
            document.getElementById('coach-roster-list').innerHTML = '<tr><td>Replay Academy 2012 stale roster</td></tr>';
            document.getElementById('feedback-playlists-list').textContent = 'Replay Academy 2012 stale feedback';
        });
        await page.click('#nav-scope-trigger');
        await page.selectOption('#nav-scope-team', TEAM_BRAVO.id);
        await expect(page.locator('#coach-roster-list')).toContainText('Loading roster');
        await expect(page.locator('#feedback-playlists-list')).toContainText('Loading playlists');
        await expect(page.locator('text=Replay Academy 2012 stale')).toHaveCount(0);
    });
});
