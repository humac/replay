"""Phase 4e — clip thumbnail screenshot capture.

Runs against http://localhost:8090 which must already have Phase 4e
running (server restarted after the merge). Logs in as the seeded
`coach1` and `family1` demo accounts (`docs/_seed/seed.py`,
`Replay!Demo123`), navigates to Coach > Clips and My Feedback > Clips,
and saves PNGs into this directory.

Usage:
    python3 docs/screenshots/phase-4e-clip-thumbnails/_capture.py

Pre-conditions (the script does NOT create these):
    - Demo seed has been run.
    - At least one clip exists on a match that has a playable source MP4.
    - Server is running with Phase 4e backend so the GET endpoint
      `/api/coach/clips/{id}/thumbnail` returns 200 with a real JPEG.
      If the server pre-dates Phase 4e the cards will fall back to
      placeholder / source-note thumbnail and the screenshots will
      reflect that — useful for the placeholder screenshot only.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("REPLAY_BASE", "http://localhost:8090")
COACH = {"username": "coach1", "password": "Replay!Demo123"}
VIEWER = {"username": "family1", "password": "Replay!Demo123"}


async def login(page, who):
    await page.goto(BASE)
    await page.evaluate(
        """async ({u, p}) => {
            const r = await fetch('/api/login', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({username: u, password: p}),
            });
            const d = await r.json();
            sessionStorage.setItem('replay_admin_token', d.token);
        }""",
        {"u": who["username"], "p": who["password"]},
    )
    await page.reload()
    # Wait for the app's auth init to finish populating `app.userName`
    # off the sessionStorage token; without this the next page.goto can
    # race the bootstrap and land on the public-landing page.
    await page.wait_for_function(
        "() => window.app && app.userName && app.userName.length > 0",
        timeout=5000,
    )


async def shoot(page, file: str) -> None:
    out = HERE / file
    await page.screenshot(path=str(out), full_page=False)
    print("  saved", file)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        print("\n=== Coach > Clips (dark) ===")
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            color_scheme="dark",
        )
        page = await ctx.new_page()
        await login(page, COACH)
        await page.goto(f"{BASE}/coach?tab=clips")
        try:
            await page.wait_for_selector("#coach-clips-list article", timeout=5000)
        except Exception:
            print("  no clip rows yet — capturing whatever rendered")
        await page.wait_for_timeout(2500)
        await shoot(page, "01-coach-clips-dark.png")

        print("\n=== Coach > Clips (light) ===")
        await page.evaluate(
            """() => { document.documentElement.setAttribute('data-theme', 'light'); }"""
        )
        await page.wait_for_timeout(400)
        await shoot(page, "02-coach-clips-light.png")
        await ctx.close()

        print("\n=== My Feedback > Clips (viewer desktop) ===")
        ctx2 = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            color_scheme="dark",
        )
        page2 = await ctx2.new_page()
        await login(page2, VIEWER)
        await page2.goto(f"{BASE}/feedback?tab=clips")
        await page2.wait_for_timeout(2500)
        await shoot(page2, "03-my-feedback-clips-desktop.png")
        await ctx2.close()

        print("\n=== My Feedback > Clips (viewer mobile) ===")
        ctx3 = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            color_scheme="dark",
        )
        page3 = await ctx3.new_page()
        await login(page3, VIEWER)
        await page3.goto(f"{BASE}/feedback?tab=clips")
        await page3.wait_for_timeout(2500)
        # Scroll past the placeholder card so the screenshot frames a
        # real clip-specific thumbnail (the placeholder card is captured
        # in 05-placeholder-demo.png).
        await page3.evaluate(
            """() => {
              const cards = document.querySelectorAll('#feedback-clips-list article');
              for (const c of cards) {
                const img = c.querySelector('img[data-coach-clip-thumb]');
                if (img && img.dataset.thumbState === 'loaded') {
                  c.scrollIntoView({block: 'start'});
                  return;
                }
              }
            }"""
        )
        await page3.wait_for_timeout(400)
        await shoot(page3, "04-my-feedback-clips-mobile.png")
        await ctx3.close()

        print("\n=== Placeholder demo (clip with no source video) ===")
        ctx4 = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            color_scheme="dark",
        )
        page4 = await ctx4.new_page()
        await login(page4, COACH)
        await page4.goto(f"{BASE}/coach?tab=clips")
        try:
            await page4.wait_for_selector("#coach-clips-list article", timeout=5000)
        except Exception:
            pass
        await page4.evaluate(
            """() => {
              const articles = document.querySelectorAll('#coach-clips-list article');
              for (const a of articles) {
                const t = a.textContent || '';
                if (t.includes('placeholder') || t.includes('no source video')) {
                  a.scrollIntoView({block: 'center'});
                  return;
                }
              }
            }"""
        )
        await page4.wait_for_timeout(800)
        await shoot(page4, "05-placeholder-demo.png")
        await ctx4.close()

        await browser.close()
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
