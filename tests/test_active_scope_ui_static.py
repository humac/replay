from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nav_shell_contains_active_scope_switcher_mount_points():
    html = (ROOT / "index.html").read_text()

    assert 'id="nav-scope-switcher"' in html
    assert 'id="nav-scope-trigger"' in html
    assert 'id="nav-scope-team"' in html
    assert 'id="nav-scope-season"' in html


def test_scope_state_mixin_exposes_active_scope_lifecycle_methods():
    state_js = (ROOT / "js" / "coaching" / "state.js").read_text()
    api_js = (ROOT / "js" / "api.js").read_text()

    for method in [
        "loadMeScope(",
        "renderScopeSwitcher(",
        "toggleScopeSwitcher(",
        "handleScopeTeamChange(",
        "handleScopeSeasonChange(",
        "saveActiveScope(",
        "clearScopedViewData(",
    ]:
        assert method in state_js
    assert "const seasonCount = teams.reduce" in state_js
    assert "teams.length > 1 || seasonCount > 1" in state_js
    assert "this.matches = [];" in state_js
    assert "params.set('team_id', this.activeScope.team.id);" in api_js
    assert "params.set('season_id', this.activeScope.season.id);" in api_js
    for stale_placeholder_id in [
        "coach-roster-list",
        "coach-engagement-dashboard",
        "feedback-development-content",
        "library-table-wrap",
    ]:
        assert stale_placeholder_id in state_js


def test_scope_switcher_styles_cover_dark_and_light_themes():
    css = (ROOT / "styles.css").read_text()

    assert ".nav-scope-switcher" in css
    assert ".nav-scope-panel" in css
    assert '[data-theme="light"] .nav-scope-panel' in css
