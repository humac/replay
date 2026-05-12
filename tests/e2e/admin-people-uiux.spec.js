import { test, expect } from '@playwright/test';
import { login, gotoAndSettle } from './_login.js';

const ADMIN_PASS = process.env.ADMIN_PASS || 'ReplayLocalAdmin123!';

function uniqueSlug(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

test('membership-only team admin can manage active-team people but not global admin sections', async ({ page }) => {
    const baseURL = page.context()._options?.baseURL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8090';
    const suffix = uniqueSlug('people-uiux');
    const adminToken = await login(page, 'admin', ADMIN_PASS);
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };

    const teamResp = await page.request.post(`${baseURL}/api/admin/teams`, {
        headers: adminHeaders,
        data: { name: `People UIUX ${suffix}`, slug: suffix, game_format: '9v9' },
    });
    expect(teamResp.ok()).toBeTruthy();
    const team = await teamResp.json();

    const seasonResp = await page.request.post(`${baseURL}/api/admin/teams/${team.id}/seasons`, {
        headers: adminHeaders,
        data: { name: 'Spring 2026' },
    });
    expect(seasonResp.ok()).toBeTruthy();
    const season = await seasonResp.json();

    const userResp = await page.request.post(`${baseURL}/api/users`, {
        headers: adminHeaders,
        data: {
            username: `teamadmin_${suffix.replace(/-/g, '_')}`,
            password: 'Passw0rd!',
            role: 'viewer',
            display_name: 'Team Admin E2E',
        },
    });
    expect(userResp.ok()).toBeTruthy();
    const user = (await userResp.json()).user;

    const membershipResp = await page.request.post(`${baseURL}/api/admin/teams/${team.id}/memberships`, {
        headers: adminHeaders,
        data: { user_id: user.id, role: 'team_admin' },
    });
    expect(membershipResp.ok()).toBeTruthy();

    const teamAdminToken = await login(page, user.username, 'Passw0rd!');
    const scopeResp = await page.request.put(`${baseURL}/api/me/scope`, {
        headers: { Authorization: `Bearer ${teamAdminToken}` },
        data: { team_id: team.id, season_id: season.id },
    });
    expect(scopeResp.ok()).toBeTruthy();

    const inviteResp = await page.request.post(`${baseURL}/api/team/invites`, {
        headers: { Authorization: `Bearer ${teamAdminToken}` },
        data: { team_id: team.id, email: `guardian-${suffix}@example.com`, role: 'guardian' },
    });
    expect(inviteResp.ok()).toBeTruthy();

    await gotoAndSettle(page, '/admin/people');
    await expect(page.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
    await expect(page.locator('#admin-brand-role')).toHaveText('Team Admin Console');
    await expect(page.locator('#admin-nav')).toContainText('People');
    await expect(page.locator('#admin-nav')).not.toContainText('Teams');
    await expect(page.locator('#admin-nav')).not.toContainText('Users');
    await expect(page.locator('#admin-people-scope-note')).toContainText(`People UIUX ${suffix}`);
    await expect(page.locator('#admin-people-members-content')).toContainText('Team Admin E2E');
    await expect(page.locator('#admin-people-invites-content')).toContainText(`guardian-${suffix}@example.com`);
    await expect(page.locator('#admin-people-invites-content')).toContainText('Email off');
    await expect(page.getByRole('button', { name: 'Resend' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Revoke' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Copy link' })).toHaveCount(0);
});
