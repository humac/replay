from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_coach_engagement_css_is_split_without_build_step():
    html = (ROOT / "index.html").read_text()
    main_css = (ROOT / "styles.css").read_text()
    engagement_css = (ROOT / "styles" / "coaching-engagement.css").read_text()

    assert '<link rel="stylesheet" href="/static/styles.css' in html
    assert '<link rel="stylesheet" href="/static/styles/coaching-engagement.css' in html
    assert html.index('/static/styles.css') < html.index('/static/styles/coaching-engagement.css')

    assert 'Phase 5.3: Coach Engagement dashboard styles moved' in main_css
    assert '.coach-engagement-shell {' not in main_css
    assert '.coach-engagement-shell {' in engagement_css
    assert '[data-theme="light"] .coach-engagement-shell' in engagement_css
    assert '@media (max-width: 640px)' in engagement_css


def test_static_export_allowlist_includes_split_styles_directory():
    server = (ROOT / "server.py").read_text()
    export_block = server[server.index('_STATIC_EXPORT_PATHS = ('):server.index(')', server.index('_STATIC_EXPORT_PATHS = ('))]

    assert '"styles.css"' in export_block
    assert '"styles"' in export_block
