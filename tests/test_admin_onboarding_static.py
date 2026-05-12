from __future__ import annotations

import subprocess
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


def test_welcome_redirect_honors_nested_me_admin_shape(tmp_path):
    onboarding_js = _read("js/onboarding.js")
    assert "me.user?.is_global_admin ?? me.is_global_admin" in onboarding_js

    module = onboarding_js.replace("export const onboardingMixin =", "const onboardingMixin =")
    module += r'''

globalThis.localStorage = { getItem: () => null };
const cases = [
  [{ user: { is_global_admin: true }, teams: [] }, true, 'nested global admin with no teams redirects'],
  [{ user: { is_global_admin: false }, teams: [] }, false, 'nested non-admin does not redirect'],
  [{ user: { is_global_admin: true }, teams: [{ id: 1 }] }, false, 'nested global admin with teams does not redirect'],
  [{ is_global_admin: true, teams: [] }, true, 'legacy top-level global admin remains compatible'],
];
for (const [payload, expected, label] of cases) {
  const actual = onboardingMixin.shouldRedirectToWelcome(payload);
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}
'''
    test_module = tmp_path / "onboarding-test.mjs"
    test_module.write_text(module)

    subprocess.run(["node", str(test_module)], cwd=ROOT, check=True)


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


def test_admin_settings_exposes_notification_settings_without_echoing_secret():
    index_html = _read("index.html")
    admin_views_js = _read("js/admin-views.js")
    settings_py = _read("settings.py")
    env_example = _read(".env.example")

    assert "settings-email-provider" in index_html
    assert "settings-email-brevo-api-key" in index_html
    assert "settings-email-test-address" in index_html
    assert "renderNotificationSettingsCard" in admin_views_js
    assert "/api/admin/email/settings" in admin_views_js
    assert "clear_brevo_api_key" in admin_views_js
    assert "email_brevo_api_key" in settings_py
    assert 'PRIVATE_SETTING_KEYS = {"live_stream_key", "email_brevo_api_key"}' in settings_py
    assert "Admin > Settings > Notifications" in env_example
    assert "REPLAY_EMAIL_PROVIDER=disabled" in env_example
    assert "REPLAY_PUBLIC_BASE_URL=" in env_example
    assert "REPLAY_BREVO_API_KEY=" in env_example
    assert "REPLAY_EMAIL_FROM=" in env_example
    assert "REPLAY_EMAIL_FROM_NAME=Replay" in env_example
    assert "REPLAY_DEV_TOKEN_DELIVERY=0" in env_example
