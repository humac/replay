from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_scope_lifecycle_lives_in_dedicated_frontend_module():
    script = (ROOT / "script.js").read_text()
    api = (ROOT / "js" / "api.js").read_text()
    scope = (ROOT / "js" / "coaching" / "state.js").read_text()

    assert "import { coachingStateMixin } from './js/coaching/state.js';" in script
    assert "...apiMixin," in script
    assert "...coachingStateMixin," in script
    assert script.index("...apiMixin,") < script.index("...coachingStateMixin,")

    for method in [
        "loadMeScope",
        "renderScopeSwitcher",
        "saveActiveScope",
        "clearScopedViewData",
        "refreshAfterScopeChange",
    ]:
        assert f"    {method}(" in scope or f"    async {method}(" in scope
        assert f"    {method}(" not in api
        assert f"    async {method}(" not in api


def test_api_mixin_keeps_auth_and_match_loading_while_using_active_scope_state():
    api = (ROOT / "js" / "api.js").read_text()

    assert "async checkAuth()" in api
    assert "async loadMatches()" in api
    assert "await this.loadMeScope();" in api
    assert "params.set('team_id', this.activeScope.team.id);" in api
    assert "params.set('season_id', this.activeScope.season.id);" in api
