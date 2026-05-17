// Playwright config for Replay end-to-end smoke checks.
// Scoped to tests/e2e/ so the repo root stays no-build.
//
// Run from this directory:
//   npx playwright test
//
// The replay app must be running at PLAYWRIGHT_BASE_URL (default http://localhost:8091)
// before tests start. We do NOT auto-start a dev server here so the same config works
// against a local docker-compose stack or a deployed staging environment.

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
    testDir: '.',
    timeout: 30_000,
    expect: { timeout: 5_000 },
    fullyParallel: true,
    reporter: [['list']],
    use: {
        baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8091',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
    },
    projects: [
        { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    ],
});
