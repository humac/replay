// Shared login + nav helpers for the Coach Review redesign e2e specs.
// Each spec file used to inline its own copy of these; centralising them
// here keeps them DRY and lets us add retry-on-429 in one place. The
// auth.py login rate limit is 5 attempts per IP per window, and several
// specs running back-to-back can trip it. We retry with exponential
// backoff so transient rate-limit hits don't fail the test.

const _tokenCache = {};

export async function login(page, user, pass, opts = {}) {
    const baseURL = page.context()._options?.baseURL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8091';
    if (!_tokenCache[user]) {
        // Retry on 429 (login rate limit). The server's window is short
        // (~60 s); we wait 5 s, 10 s, 20 s, 40 s, 60 s before giving up.
        const backoffs = [0, 5_000, 10_000, 20_000, 40_000, 60_000];
        let lastErr = null;
        for (const wait of backoffs) {
            if (wait > 0) await new Promise((r) => setTimeout(r, wait));
            const resp = await page.request.post(`${baseURL}/api/login`, {
                data: { username: user, password: pass },
            });
            if (resp.status() === 429) {
                lastErr = new Error('429 rate-limited');
                continue;
            }
            if (!resp.ok()) {
                throw new Error(`Login failed for ${user}: HTTP ${resp.status()}`);
            }
            const j = await resp.json();
            _tokenCache[user] = j.token;
            break;
        }
        if (!_tokenCache[user]) throw lastErr || new Error(`Login failed for ${user}`);
    }
    const token = _tokenCache[user];
    await page.addInitScript((t) => {
        sessionStorage.setItem('replay_admin_token', t);
    }, token);
    return token;
}

export async function gotoAndSettle(page, url) {
    await page.goto(url);
    await page.waitForFunction(() => Array.isArray(window.app?.matches), null, { timeout: 5000 });
    await page.waitForFunction(() => document.querySelector('.view.active') !== null, null, { timeout: 5000 });
    await page.waitForTimeout(200);
}

export async function pickMatchWithMostNotes(page, token) {
    const baseURL = page.context()._options?.baseURL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8091';
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
