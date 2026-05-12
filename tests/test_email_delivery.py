from __future__ import annotations


def test_brevo_send_invite_uses_transactional_api(monkeypatch):
    from services import email_delivery

    calls = []

    class FakeResponse:
        status_code = 201
        content = b'{"messageId":"msg-123"}'
        text = '{"messageId":"msg-123"}'

        def json(self):
            return {"messageId": "msg-123"}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(email_delivery._settings, "email_effective_config", lambda: {
        "email_provider": "brevo",
        "email_public_base_url": "https://replay.example.test",
        "email_brevo_api_key": "brevo-secret",
        "email_from": "noreply@example.test",
        "email_from_name": "Replay Ops",
    })
    monkeypatch.setattr(email_delivery.httpx, "Client", FakeClient)

    result = email_delivery.send_invite_email(
        to_email="parent@example.test",
        token="raw-token",
        team_name="U12 <Steel>",
        role="team_admin",
    )

    assert result.ok is True
    assert result.status == "sent"
    assert result.message_id == "msg-123"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == email_delivery.BREVO_SEND_URL
    assert call["headers"]["api-key"] == "brevo-secret"
    assert call["json"]["sender"] == {"email": "noreply@example.test", "name": "Replay Ops"}
    assert call["json"]["to"] == [{"email": "parent@example.test"}]
    assert "https://replay.example.test/invite/raw-token" in call["json"]["textContent"]
    assert "U12 &lt;Steel&gt;" in call["json"]["htmlContent"]


def test_brevo_missing_config_fails_closed_without_network(monkeypatch):
    from services import email_delivery

    def fail_client(*args, **kwargs):
        raise AssertionError("network client should not be constructed")

    monkeypatch.setattr(email_delivery._settings, "email_effective_config", lambda: {
        "email_provider": "brevo",
        "email_public_base_url": "",
        "email_brevo_api_key": "brevo-secret",
        "email_from": "noreply@example.test",
        "email_from_name": "Replay",
    })
    monkeypatch.setattr(email_delivery.httpx, "Client", fail_client)

    result = email_delivery.send_password_reset_email(to_email="person@example.test", token="reset-token")

    assert result.ok is False
    assert result.provider == "brevo"
    assert result.status == "not_configured"
