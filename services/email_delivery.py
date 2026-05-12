"""Transactional email delivery boundary.

Brevo uses "smtp" in its transactional API naming, but the production path
here is the HTTPS API (`POST /v3/smtp/email`), not SMTP relay credentials.
Raw invitation/reset/verification tokens are passed only in memory to build
links and are never logged or persisted by this module.
"""

from __future__ import annotations

from html import escape
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx
import settings as _settings

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(slots=True)
class EmailResult:
    ok: bool
    status: str
    provider: str
    message_id: str = ""
    detail: str = ""


def provider() -> str:
    return (_settings.email_effective_config().get("email_provider") or "disabled").strip().lower() or "disabled"


def public_base_url() -> str:
    return (_settings.email_effective_config().get("email_public_base_url") or "").strip().rstrip("/")


def is_configured() -> bool:
    config = _settings.email_effective_config()
    if (config.get("email_provider") or "disabled").strip().lower() != "brevo":
        return False
    return bool(
        (config.get("email_public_base_url") or "").strip()
        and config.get("email_brevo_api_key")
        and (config.get("email_from") or "").strip()
    )


def config_status() -> dict:
    payload = _settings.email_admin_payload()
    status = payload["status"]
    return {
        "provider": payload["provider"],
        "configured": payload["configured"],
        "has_public_base_url": status["has_public_base_url"],
        "has_from": status["has_from"],
        "has_brevo_api_key": status["has_brevo_api_key"],
    }


def invite_url(token: str) -> str:
    return f"{public_base_url()}/invite/{quote(token)}"


def password_reset_url(token: str) -> str:
    return f"{public_base_url()}/reset-password?{urlencode({'token': token})}"


def verification_url(token: str) -> str:
    return f"{public_base_url()}/verify-email?{urlencode({'token': token})}"


def _sender() -> dict:
    config = _settings.email_effective_config()
    sender = {"email": (config.get("email_from") or "").strip()}
    name = (config.get("email_from_name") or "Replay").strip()
    if name:
        sender["name"] = name
    return sender


def _send_brevo(*, to_email: str, subject: str, text: str, html: str, tags: list[str]) -> EmailResult:
    config = _settings.email_effective_config()
    active_provider = (config.get("email_provider") or "disabled").strip().lower() or "disabled"
    configured = (
        active_provider == "brevo"
        and bool((config.get("email_public_base_url") or "").strip())
        and bool(config.get("email_brevo_api_key"))
        and bool((config.get("email_from") or "").strip())
    )
    if not configured:
        return EmailResult(False, "not_configured", active_provider, detail="Brevo email delivery is not configured")

    payload = {
        "sender": _sender(),
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html,
        "tags": tags,
    }
    headers = {
        "accept": "application/json",
        "api-key": config.get("email_brevo_api_key", ""),
        "content-type": "application/json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(BREVO_SEND_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return EmailResult(False, "failed", "brevo", detail=str(exc)[:300])
    if resp.status_code >= 400:
        detail = resp.text[:300]
        return EmailResult(False, "failed", "brevo", detail=detail)
    data = resp.json() if resp.content else {}
    return EmailResult(True, "sent", "brevo", message_id=str(data.get("messageId") or ""))


def _send(*, to_email: str, subject: str, text: str, html: str, tags: list[str]) -> EmailResult:
    active_provider = provider()
    if active_provider == "disabled":
        return EmailResult(False, "disabled", "disabled", detail="Email delivery is disabled")
    if active_provider != "brevo":
        return EmailResult(False, "not_configured", active_provider, detail="Unsupported email provider")
    return _send_brevo(to_email=to_email, subject=subject, text=text, html=html, tags=tags)


def send_invite_email(*, to_email: str, token: str, team_name: str, role: str) -> EmailResult:
    url = invite_url(token)
    role_label = role.replace("_", " ")
    team_html = escape(team_name)
    role_html = escape(role_label)
    url_html = escape(url, quote=True)
    subject = f"You're invited to {team_name} on Replay"
    text = (
        f"You have been invited to {team_name} as {role_label}.\n\n"
        f"Accept your invite: {url}\n\n"
        "This link is one-time use and expires soon."
    )
    html = (
        f"<p>You have been invited to <strong>{team_html}</strong> as {role_html}.</p>"
        f"<p><a href=\"{url_html}\">Accept your invite</a></p>"
        "<p>This link is one-time use and expires soon.</p>"
    )
    return _send(to_email=to_email, subject=subject, text=text, html=html, tags=["replay-invite"])


def send_password_reset_email(*, to_email: str, token: str) -> EmailResult:
    url = password_reset_url(token)
    url_html = escape(url, quote=True)
    subject = "Reset your Replay password"
    text = f"Reset your Replay password here:\n\n{url}\n\nIf you did not request this, ignore this email."
    html = f"<p>Reset your Replay password here:</p><p><a href=\"{url_html}\">Reset password</a></p><p>If you did not request this, ignore this email.</p>"
    return _send(to_email=to_email, subject=subject, text=text, html=html, tags=["replay-password-reset"])


def send_email_verification_email(*, to_email: str, token: str) -> EmailResult:
    url = verification_url(token)
    url_html = escape(url, quote=True)
    subject = "Verify your Replay email"
    text = f"Verify your Replay email here:\n\n{url}\n\nIf you did not request this, ignore this email."
    html = f"<p>Verify your Replay email here:</p><p><a href=\"{url_html}\">Verify email</a></p><p>If you did not request this, ignore this email.</p>"
    return _send(to_email=to_email, subject=subject, text=text, html=html, tags=["replay-email-verification"])


def send_test_email(*, to_email: str) -> EmailResult:
    subject = "Replay email delivery test"
    text = "Replay email delivery is configured correctly."
    html = "<p>Replay email delivery is configured correctly.</p>"
    return _send(to_email=to_email, subject=subject, text=text, html=html, tags=["replay-email-test"])
