from __future__ import annotations

from pathlib import Path

import settings as _settings


ROOT = Path(__file__).resolve().parents[1]


def test_split_css_is_loaded_after_main_stylesheet_without_build_step():
    html = (ROOT / "index.html").read_text()

    assert '<link rel="stylesheet" href="/static/styles.css' in html
    assert '<link rel="stylesheet" href="/static/styles/admin-users.css' in html
    assert html.index('/static/styles.css') < html.index('/static/styles/admin-users.css')


def test_static_export_allowlist_includes_split_styles_directory():
    server = (ROOT / "server.py").read_text()
    export_block = server[server.index('_STATIC_EXPORT_PATHS = ('):server.index(')', server.index('_STATIC_EXPORT_PATHS = ('))]

    assert '"styles.css"' in export_block
    assert '"styles"' in export_block


def test_rendered_index_versions_split_stylesheet():
    rendered = _settings.render_index_html(_settings.public_payload(_settings.DEFAULT_APP_SETTINGS.copy()))

    assert '/static/styles/admin-users.css?v=' in rendered
