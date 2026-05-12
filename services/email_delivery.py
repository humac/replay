"""Transactional email delivery boundary.

Brevo uses "smtp" in its transactional API naming, but the production path
here is the HTTPS API (`POST /v3/smtp/email`), not SMTP relay credentials.
Raw invitation/reset/verification tokens are passed only in memory to build
links and are never logged or persisted by this module.
"""

from __future__ import annotations

import os
from html import escape
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(slots=True)
class EmailResult:
    ok: bool
    status: str
    provider: str
    message_id: str = ""
    detail: str = ""


def provider() -> str:
    return (os.environ.get("REPLAY_EMAIL_PROVIDER") or "disabled").strip().lower() or "disabled"


def public_base_url() -> str:
    return (os.environ.get("REPLAY_PUBLIC_BASE_URL") or "").strip().rstrip("/")


def is_configured() -> bool:
    if provider() != "brevo":
        return False
    return bool(
        public_base_url()
        and os.environ.get("REPLAY_BREVO_API_KEY")
        and os.environ.get("REPLAY_EMAIL_FROM")
    )


def config_status() -> dict:
    return {
        "provider": provider(),
        "configured": is_configured(),
        "has_public_base_url": bool(public_base_url()),
        "has_from": bool(os.environ.get("REPLAY_EMAIL_FROM")),
        "has_brevo_api_key": bool(os.environ.get("REPLAY_BREVO_API_KEY")),
    }


def invite_url(token: str) -> str:
    return f"{public_base_url()}/invite/{quote(token)}"


def password_reset_url(token: str) -> str:
    return f"{public_base_url()}/reset-password?{urlencode({'token': token})}"


def verification_url(token: str) -> str:
    return f"{public_base_url()}/verify-email?{urlencode({'token': token})}"


def _sender() -> dict:
    sender = {"email": os.environ.get("REPLAY_EMAIL_FROM", "").strip()}
    name = (os.environ.get("REPLAY_EMAIL_FROM_NAME") or "Replay").strip()
    if name:
        sender["name"] = name
    return sender


def _send_brevo(*, to_email: str, subject: str, text: str, html: str, tags: list[str]) -> EmailResult:
    if not is_configured():
        return EmailResult(False, "not_configured", provider(), detail="Brevo email delivery is not configured")

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
        "api-key": os.environ.get("REPLAY_BREVO_API_KEY", ""),
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
    if provider() == "disabled":
        return EmailResult(False, "disabled", "disabled", detail="Email delivery is disabled")
    if provider() != "brevo":
        return EmailResult(False, "not_configured", provider(), detail="Unsupported email provider")
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
