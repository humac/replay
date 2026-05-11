from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOMAIN_MIXINS = {
    "roster": "coachingRosterMixin",
    "notes": "coachingNotesMixin",
    "clips": "coachingClipsMixin",
    "playlists": "coachingPlaylistsMixin",
    "review": "coachingReviewMixin",
    "observations": "coachingObservationsMixin",
    "development": "coachingDevelopmentMixin",
    "goals": "coachingGoalsMixin",
    "match-summaries": "coachingMatchSummariesMixin",
    "engagement": "coachingEngagementMixin",
    "feedback": "coachingFeedbackMixin",
    "feedback-player": "coachingFeedbackPlayerMixin",
    "thumbnails": "coachingThumbnailsMixin",
}


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


def test_phase5_domain_modules_are_imported_and_assembled_without_build_tooling():
    script = (ROOT / "script.js").read_text()
    html = (ROOT / "index.html").read_text()

    assert re.search(r'<script[^>]+type="module"[^>]+src="/static/script\.js(?:\?v=[^"]+)?"', html)
    assert script.count("window.app = app;") == 1
    assert "...coachingStateMixin," in script
    assert "...coachingMixin," in script
    assert script.index("...coachingStateMixin,") < script.index("...coachingMixin,")

    for file_stem, mixin_name in DOMAIN_MIXINS.items():
        rel = f"./js/coaching/{file_stem}.js"
        module = (ROOT / "js" / "coaching" / f"{file_stem}.js").read_text()
        assert f"import {{ {mixin_name} }} from '{rel}';" in script
        assert f"export const {mixin_name}" in module
        assert f"...{mixin_name}," in script
        assert script.index("...coachingMixin,") < script.index(f"...{mixin_name},")

    assert not (ROOT / "package.json").exists()
    assert "VALID_COACH_TABS = ['roster', 'notes', 'playlists', 'clips', 'summaries', 'engagement', 'settings', 'review']" in (ROOT / "js" / "coaching.js").read_text()


def test_phase5_engagement_dashboard_lives_in_domain_module():
    core = (ROOT / "js" / "coaching.js").read_text()
    engagement = (ROOT / "js" / "coaching" / "engagement.js").read_text()

    for method in [
        "renderCoachEngagementFilters",
        "coachEngagementFilters",
        "renderCoachEngagement",
        "loadCoachEngagementDashboard",
        "renderCoachEngagementDashboard",
    ]:
        assert f"    {method}(" in engagement or f"    async {method}(" in engagement
        assert f"    {method}(" not in core
        assert f"    async {method}(" not in core


def test_index_inline_app_handlers_still_have_a_mixin_method_definition():
    html = (ROOT / "index.html").read_text()
    script = (ROOT / "script.js").read_text()
    module_text = script + "\n".join(path.read_text() for path in [
        *sorted((ROOT / "js").glob("*.js")),
        *sorted((ROOT / "js" / "coaching").glob("*.js")),
    ])
    handlers = set(re.findall(r"app\.([A-Za-z_$][\w$]*)\(", html))
    missing = [name for name in sorted(handlers) if not re.search(rf"(?:async\s+)?{re.escape(name)}\s*\(", module_text)]

    assert not missing
