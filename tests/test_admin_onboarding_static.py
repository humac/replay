from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_invite_acceptance_uses_membership_role_and_shared_login_helper():
    team_members_js = _read("js/coaching/team-members.js")
    api_js = _read("js/api.js")

    assert "async loginWith(username, password)" in api_js
    assert "await this.loginWith(username, password)" in team_members_js
    assert "body.membership?.role" in team_members_js
    assert "body.role" not in team_members_js
    assert "routeAfterInviteAcceptance" in team_members_js
    assert "showFeedbackView?.({ replaceHistory: true })" in team_members_js


def test_admin_people_console_is_available_to_membership_admins_static_hooks():
    index_html = _read("index.html")
    api_js = _read("js/api.js")
    admin_js = _read("js/admin.js")

    assert 'data-admin-section="people"' in index_html
    assert "admin-people-members-content" in index_html
    assert "admin-people-invites-content" in index_html
    assert "Open Admin &rsaquo; People" in index_html
    assert "canAccessAdminConsole()" in api_js
    assert "m.role === 'team_admin'" in api_js
    assert "navAdmin.style.display = this.canAccessAdminConsole()" in api_js
    assert "if (section === 'people') return this.isAdmin() || this.canManageTeamMembers?.();" in admin_js
    assert "if (this.canManageTeamMembers?.()) return 'people';" in admin_js
    assert "if (section === 'matches') return this.canEdit();" in admin_js


def test_welcome_redirect_and_coach_settings_copy_are_current():
    index_html = _read("index.html")
    script_js = _read("script.js")
    coaching_js = _read("js/coaching.js")

    assert "maybeRedirectToWelcome" in script_js
    assert "if (!redirectedToWelcome)" in script_js
    assert "this.loadCoachTeamMembers?.();" not in coaching_js
    assert "this.loadCoachTeamInvites?.();" not in coaching_js
    assert "once invite acceptance ships" not in index_html
    assert "team-admin invite flow lands shortly" not in index_html
    assert "send invites later from Admin &rsaquo; People" in index_html

