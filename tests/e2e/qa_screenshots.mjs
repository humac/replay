import { chromium } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8090';
const OUT = '/Users/huynguyen/Development/personal/git/humac/replay/docs/screenshots/phase-6d1-unified-coach-review';

async function loginViaApi(request, username, password) {
  const resp = await request.post(`${BASE}/api/login`, { data: { username, password } });
  const d = await resp.json();
  if (!d.token) throw new Error(`Login failed for ${username}: ${JSON.stringify(d)}`);
  return d.token;
}

async function setupPage(browser, token, opts = {}) {
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 900 },
    colorScheme: opts.colorScheme || 'dark',
    baseURL: BASE,
  });
  // Inject token before every page load — same mechanism as _login.js
  await ctx.addInitScript((t) => {
    sessionStorage.setItem('replay_admin_token', t);
  }, token);
  const page = await ctx.newPage();
  return { page, ctx };
}

async function waitForCoachView(page) {
  // Wait for the SPA to recognise the token and render the coach shell
  await page.waitForFunction(() => {
    const v = document.querySelector('#coach-view');
    return v && !v.hidden && v.style.display !== 'none' && v.offsetParent !== null;
  }, { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(800);
}

async function navigateToCoachTab(page, tab) {
  await page.goto(`${BASE}/coach?tab=${tab}`, { waitUntil: 'networkidle' });
  await waitForCoachView(page);
  await page.waitForFunction((t) => {
    const panel = document.querySelector(`#coach-tab-${t}`);
    return panel && !panel.hidden;
  }, tab, { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(600);
}

async function navigateToReview(page, mode = 'video') {
  await navigateToCoachTab(page, 'review');
  if (mode === 'tactical_board') {
    await page.evaluate(() => app.switchCoachReviewMode('tactical_board'));
    await page.waitForTimeout(700);
  }
  await page.waitForTimeout(300);
}

async function applyLightTheme(page) {
  await page.evaluate(() => {
    if (typeof app !== 'undefined' && app.setTheme) app.setTheme('light');
    document.documentElement.setAttribute('data-theme', 'light');
    document.body && document.body.setAttribute('data-theme', 'light');
  });
  await page.waitForTimeout(400);
}

async function shot(page, name) {
  const dest = path.join(OUT, name);
  await page.screenshot({ path: dest });
  console.log('  ✓', name);
}

const browser = await chromium.launch();
// Use a single request context for API calls
const apiCtx = await browser.newContext();
const request = apiCtx.request;

try {
  const coachToken = await loginViaApi(request, 'coach1', 'Replay!Demo123');
  const familyToken = await loginViaApi(request, 'family1', 'Replay!Demo123');
  console.log('Tokens ✓');

  // ── 01: Coach Review — Video mode, dark ──────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToReview(page, 'video');
    await shot(page, '01-video-mode-dark.png');
    await ctx.close();
  }

  // ── 02: Coach Review — Tactical Board mode, dark ─────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToReview(page, 'tactical_board');
    await shot(page, '02-tactical-board-mode-dark.png');
    await ctx.close();
  }

  // ── 03: Coach > Notes tab — routing buttons, dark ────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'notes');
    await page.waitForTimeout(500);
    await shot(page, '03-notes-routing-buttons-dark.png');
    await ctx.close();
  }

  // ── 04: "+ New note" → Review in video mode ───────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'notes');
    const clicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => b.textContent.trim().match(/^\+?\s*New note$/i) || 
                   (b.textContent.includes('New note') && !b.textContent.includes('observation')));
      if (btn) { btn.click(); return true; }
      return false;
    });
    if (!clicked) await page.evaluate(() => app.goToCoachReviewWithIntent({ mode: 'video', intent: 'note' }));
    await page.waitForTimeout(1400);
    await shot(page, '04-new-note-routed-review-video.png');
    await ctx.close();
  }

  // ── 05: "+ New observation" → Review in tactical_board mode ──────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'notes');
    const clicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => /observation/i.test(b.textContent));
      if (btn) { btn.click(); return true; }
      return false;
    });
    if (!clicked) await page.evaluate(() => app.goToCoachReviewWithIntent({ mode: 'tactical_board', intent: 'observation' }));
    await page.waitForTimeout(1400);
    await shot(page, '05-new-obs-routed-review-board.png');
    await ctx.close();
  }

  // ── 06: "+ New clip" → Review in video mode ───────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'clips');
    const clicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => /New clip/i.test(b.textContent));
      if (btn) { btn.click(); return true; }
      return false;
    });
    if (!clicked) await page.evaluate(() => app.goToCoachReviewWithIntent({ mode: 'video', intent: 'clip' }));
    await page.waitForTimeout(1400);
    await shot(page, '06-new-clip-routed-review-video.png');
    await ctx.close();
  }

  // ── 07: Coach > Roster tab ────────────────────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'roster');
    await page.waitForTimeout(1500);
    await shot(page, '07-roster-tab.png');
    await ctx.close();
  }

  // ── 08: Roster "Add observation" → Review in TB mode, player preselected ─
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'roster');
    await page.waitForTimeout(1500);
    const clicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button[onclick*="tactical_board"]'))[0]
        || Array.from(document.querySelectorAll('button[title*="observation"], button[aria-label*="observation"]'))[0];
      if (btn) { btn.click(); return true; }
      return false;
    });
    if (!clicked) {
      await page.evaluate(() => {
        const players = app._coachBundle && app._coachBundle.players;
        const pid = players && players.length ? players[0].id : null;
        app.goToCoachReviewWithIntent({ mode: 'tactical_board', intent: 'observation', playerId: pid, defaultVisibility: 'player' });
      });
    }
    await page.waitForTimeout(1500);
    await shot(page, '08-roster-add-obs-routed-board.png');
    await ctx.close();
  }

  // ── 09: Observation form filled in ────────────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToReview(page, 'tactical_board');
    // Picker bar: formation + event title
    await page.selectOption('#cr-obs-formation', '11-4-4-2').catch(() => {});
    await page.waitForTimeout(400);
    await page.fill('#cr-obs-event-title', 'Tuesday training — pressing shape').catch(() => {});
    // Side panel observation fields
    await page.fill('#cr-obs-title', 'Compact block out of possession').catch(() => {});
    await page.selectOption('#cr-obs-event-type', 'practice').catch(() => {});
    await page.fill('#cr-obs-event-date', '2026-05-07').catch(() => {});
    await page.selectOption('#cr-obs-category', 'shape').catch(() => {});
    await page.fill('#cr-obs-player-summary', 'Stay tight in the 4-4-2 block; delay the press until we have cover shadow.').catch(() => {});
    await page.waitForTimeout(600);
    await shot(page, '09-obs-form-filled.png');
    await ctx.close();
  }

  // ── 10: Coach > Clips tab (management surface) ────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'clips');
    await page.waitForTimeout(800);
    await shot(page, '10-clips-tab-dark.png');
    await ctx.close();
  }

  // ── 11: Coach > Notes tab (management surface) ────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToCoachTab(page, 'notes');
    await page.waitForTimeout(1000);
    await shot(page, '11-notes-tab-dark.png');
    await ctx.close();
  }

  // ── 12: Video mode regression — switch TB→Video ───────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken);
    await navigateToReview(page, 'tactical_board');
    await page.evaluate(() => app.switchCoachReviewMode('video'));
    await page.waitForTimeout(700);
    await shot(page, '12-video-mode-regression-check.png');
    await ctx.close();
  }

  // ── 13: Tactical Board mode — light theme ─────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { colorScheme: 'light' });
    await navigateToReview(page, 'tactical_board');
    await applyLightTheme(page);
    await shot(page, '13-tactical-board-light-mode.png');
    await ctx.close();
  }

  // ── 14: Video mode — light theme ──────────────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { colorScheme: 'light' });
    await navigateToReview(page, 'video');
    await applyLightTheme(page);
    await shot(page, '14-video-mode-light-mode.png');
    await ctx.close();
  }

  // ── 15: Notes routing buttons — light theme ───────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { colorScheme: 'light' });
    await navigateToCoachTab(page, 'notes');
    await applyLightTheme(page);
    await page.waitForTimeout(400);
    await shot(page, '15-notes-routing-light-mode.png');
    await ctx.close();
  }

  // ── 16: Viewer My Feedback — Notes tab (family1, dark) ───────────────────
  {
    const { page, ctx } = await setupPage(browser, familyToken);
    await page.goto(`${BASE}/feedback?tab=notes`, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => {
      const v = document.querySelector('#feedback-view');
      return v && !v.hidden && v.offsetParent !== null;
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1500);
    await shot(page, '16-viewer-my-feedback-notes.png');
    await ctx.close();
  }

  // ── 17: Mobile 390px — Video mode ─────────────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { viewport: { width: 390, height: 844 } });
    await navigateToReview(page, 'video');
    await shot(page, '17-mobile-video-mode.png');
    await ctx.close();
  }

  // ── 18: Mobile 390px — Tactical Board mode ────────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { viewport: { width: 390, height: 844 } });
    await navigateToReview(page, 'tactical_board');
    await shot(page, '18-mobile-tactical-board.png');
    await ctx.close();
  }

  // ── 19: Mobile 390px — Notes routing buttons ──────────────────────────────
  {
    const { page, ctx } = await setupPage(browser, coachToken, { viewport: { width: 390, height: 844 } });
    await navigateToCoachTab(page, 'notes');
    await page.waitForTimeout(800);
    await shot(page, '19-mobile-notes-routing.png');
    await ctx.close();
  }

  console.log('\nAll 19 screenshots saved ✓');
} finally {
  await apiCtx.close();
  await browser.close();
}
