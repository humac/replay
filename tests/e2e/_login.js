// Shared login + nav helpers for the Replay e2e smoke specs.
// The auth.py login rate limit is 5 attempts per IP per window, and specs
// running back-to-back can trip it, so we retry with exponential backoff.

const _tokenCache = {};

function baseUrl(page) {
    return page.context()._options?.baseURL
        || process.env.PLAYWRIGHT_BASE_URL
        || 'http://127.0.0.1:8091';
}

export async function login(page, user, pass) {
    const baseURL = baseUrl(page);
    if (!_tokenCache[user]) {
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
            _tokenCache[user] = (await resp.json()).token;
            break;
        }
        if (!_tokenCache[user]) throw lastErr || new Error(`Login failed for ${user}`);
    }
    const token = _tokenCache[user];
    // Inject the token into sessionStorage on every page load so the SPA
    // boots authenticated on the first navigation.
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
