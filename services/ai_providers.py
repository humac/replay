"""AI provider abstraction and mock drafting service for Phase 8.3.

Service-only boundary: this module does not expose API routes, streaming,
chat/messages, or raw prompt/output persistence. Provider secrets are read only
from environment/secret config and are never stored in team settings, job
payloads, logs, or audit rows.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from services import ai_context, ai_drafting
from services.team_settings import can_generate_draft


DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MOCK_MODEL = "mock-model-v1"
_PROVIDER_SECRET_ENV = "REPLAY_AI_PROVIDER_API_KEY"
_SAFE_FAILURE_MESSAGES = {
    "drafting_disabled": "AI drafting is disabled",
    "provider_not_configured": "AI provider is not configured",
    "provider_secret_missing": "AI provider secret is missing",
    "provider_unsupported": "AI provider is not supported",
    "provider_timeout": "AI provider timed out",
    "provider_error": "AI provider failed",
    "context_error": "AI context could not be built",
}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    timeout_seconds: float
    api_key: str | None = None


@dataclass(frozen=True)
class ProviderDraftRequest:
    team_id: str
    draft_target: str
    target_visibility: str
    context: dict[str, Any]
    instruction: str | None = None


@dataclass(frozen=True)
class ProviderDraftResult:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProvider(Protocol):
    def generate(self, request: ProviderDraftRequest, *, timeout_seconds: float | None = None) -> ProviderDraftResult:
        """Generate draft text from bounded, privacy-safe request context.

        Provider adapters must enforce timeout_seconds at the network/client
        layer. The orchestrator does not rely on thread cancellation because a
        running provider call cannot be safely killed once dispatched.
        """


class AIProviderError(RuntimeError):
    """Base provider failure. Exception text must never be persisted/logged."""


class AIProviderTimeout(AIProviderError):
    """Raised when a provider call exceeds configured timeout."""


class ProviderConfigError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(_SAFE_FAILURE_MESSAGES.get(code, "AI provider is not available"))


class MockAIProvider:
    """Deterministic mock provider for service tests and local smoke checks."""

    def __init__(self, *, draft_text: str | None = None, fail_with: str | None = None, delay_seconds: float = 0.0):
        self.draft_text = draft_text
        self.fail_with = fail_with
        self.delay_seconds = delay_seconds

    def generate(self, request: ProviderDraftRequest, *, timeout_seconds: float | None = None) -> ProviderDraftResult:
        if timeout_seconds is not None and self.delay_seconds > timeout_seconds:
            raise AIProviderTimeout("provider timed out")
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        if self.fail_with is not None:
            raise AIProviderError(self.fail_with)
        item_count = len((request.context.get("context") or {}).get("items") or [])
        target = request.draft_target.replace("_", " ")
        text = self.draft_text or f"Mock draft for {target} using {item_count} context item(s)."
        return ProviderDraftResult(
            text=text,
            input_tokens=max(1, _rough_token_count(request.context)),
            output_tokens=max(1, _rough_token_count(text)),
        )


def _rough_token_count(value: Any) -> int:
    return max(0, len(str(value).split()))


def _env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _parse_timeout(value: str | None) -> float:
    if not value:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(0.001, min(parsed, 120.0))


def resolve_provider_config(env: Mapping[str, str] | None = None) -> ProviderConfig:
    values = _env(env)
    provider_name = (values.get("REPLAY_AI_PROVIDER") or "").strip().lower()
    if not provider_name:
        raise ProviderConfigError("provider_not_configured")
    model = (values.get("REPLAY_AI_PROVIDER_MODEL") or (DEFAULT_MOCK_MODEL if provider_name == "mock" else "default")).strip()
    timeout_seconds = _parse_timeout(values.get("REPLAY_AI_PROVIDER_TIMEOUT_SECONDS"))
    if provider_name == "mock":
        return ProviderConfig(name="mock", model=model or DEFAULT_MOCK_MODEL, timeout_seconds=timeout_seconds)
    api_key = (values.get(_PROVIDER_SECRET_ENV) or "").strip()
    if not api_key:
        raise ProviderConfigError("provider_secret_missing")
    # Phase 8.3 intentionally ships only the mock implementation. Known future
    # providers fail closed until a later PR adds data-handling review/tests.
    raise ProviderConfigError("provider_unsupported")


def provider_from_config(config: ProviderConfig) -> AIProvider:
    if config.name == "mock":
        return MockAIProvider()
    raise ProviderConfigError("provider_unsupported")


def _config_failure_run(
    *,
    team_id: str,
    actor_user: dict[str, Any],
    draft_target: str,
    error_code: str,
    env: Mapping[str, str] | None,
) -> dict[str, Any]:
    values = _env(env)
    provider_name = (values.get("REPLAY_AI_PROVIDER") or "unconfigured").strip().lower() or "unconfigured"
    model = (values.get("REPLAY_AI_PROVIDER_MODEL") or "unconfigured").strip() or "unconfigured"
    run = ai_drafting.create_run(
        team_id=team_id,
        draft_target=draft_target,
        provider=provider_name,
        model=model,
        created_by_user_id=str(actor_user.get("id") or ""),
        evidence_refs=[],
        actor_user=actor_user,
    )
    return ai_drafting.fail_run(
        run["id"],
        team_id=team_id,
        error_code=error_code,
        error_message=_SAFE_FAILURE_MESSAGES.get(error_code, "AI provider is not available"),
        actor_user=actor_user,
    )


def _safe_response(*, ok: bool, error_code: str | None = None, run: dict[str, Any] | None = None, text: str = "") -> dict[str, Any]:
    response: dict[str, Any] = {"ok": ok, "text": text, "run": run}
    if error_code:
        response["error_code"] = error_code
        response["error_message"] = _SAFE_FAILURE_MESSAGES.get(error_code, "AI drafting failed")
    return response


def _flatten_audit_refs(audit: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for bucket in ("included", "excluded_by_visibility", "excluded_by_cross_team_scope", "excluded_by_permanent_policy", "excluded_by_policy"):
        for ref in audit.get(bucket) or []:
            if not isinstance(ref, dict):
                continue
            ref_type = str(ref.get("type") or "")
            ref_id = str(ref.get("id") or "")
            status = "included" if bucket == "included" else "excluded"
            key = (ref_type, ref_id, status)
            if key in seen:
                continue
            seen.add(key)
            refs.append({"type": ref_type, "id": ref_id, "status": status})
    return refs


def _call_with_timeout(provider: AIProvider, request: ProviderDraftRequest, timeout_seconds: float) -> ProviderDraftResult:
    return provider.generate(request, timeout_seconds=timeout_seconds)


def generate_draft(
    *,
    team_id: str,
    actor_user: dict[str, Any],
    draft_target: str,
    target_visibility: str,
    evidence_refs: list[dict[str, Any]] | None = None,
    target_player_ids: list[str] | None = None,
    instruction: str | None = None,
    provider: AIProvider | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build safe context, invoke configured provider, and audit lifecycle.

    Raw coach instructions, formatted prompts, provider responses, exception
    text, and secrets are never persisted. On team-policy preflight failures no
    provider is called. Provider configuration/execution failures after
    team-policy approval create failed runs with bounded codes.
    """
    if not can_generate_draft(team_id, draft_target, visibility=target_visibility, actor_user=actor_user):
        return _safe_response(ok=False, error_code="drafting_disabled")

    try:
        config = resolve_provider_config(env)
    except ProviderConfigError as exc:
        run = _config_failure_run(
            team_id=team_id,
            actor_user=actor_user,
            draft_target=draft_target,
            error_code=exc.code,
            env=env,
        )
        return _safe_response(ok=False, error_code=exc.code, run=run)

    try:
        provider_impl = provider if provider is not None else provider_from_config(config)
    except ProviderConfigError as exc:
        run = _config_failure_run(
            team_id=team_id,
            actor_user=actor_user,
            draft_target=draft_target,
            error_code=exc.code,
            env=env,
        )
        return _safe_response(ok=False, error_code=exc.code, run=run)

    try:
        context_payload = ai_context.build_context(
            team_id=team_id,
            actor_user=actor_user,
            draft_target=draft_target,
            target_visibility=target_visibility,
            evidence_refs=evidence_refs,
            target_player_ids=target_player_ids,
        )
    except Exception:
        return _safe_response(ok=False, error_code="context_error")

    run = ai_drafting.create_run(
        team_id=team_id,
        draft_target=draft_target,
        provider=config.name,
        model=config.model,
        created_by_user_id=str(actor_user.get("id") or ""),
        evidence_refs=_flatten_audit_refs(context_payload.get("audit") or {}),
        actor_user=actor_user,
    )
    run = ai_drafting.start_run(run["id"], team_id=team_id, actor_user=actor_user)
    request = ProviderDraftRequest(
        team_id=team_id,
        draft_target=draft_target,
        target_visibility=target_visibility,
        context=context_payload,
        instruction=instruction,
    )
    try:
        provider_result = _call_with_timeout(provider_impl, request, config.timeout_seconds)
    except AIProviderTimeout:
        run = ai_drafting.fail_run(
            run["id"],
            team_id=team_id,
            error_code="provider_timeout",
            error_message=_SAFE_FAILURE_MESSAGES["provider_timeout"],
            actor_user=actor_user,
        )
        return _safe_response(ok=False, error_code="provider_timeout", run=run)
    except Exception:
        run = ai_drafting.fail_run(
            run["id"],
            team_id=team_id,
            error_code="provider_error",
            error_message=_SAFE_FAILURE_MESSAGES["provider_error"],
            actor_user=actor_user,
        )
        return _safe_response(ok=False, error_code="provider_error", run=run)

    run = ai_drafting.succeed_run(
        run["id"],
        team_id=team_id,
        input_tokens=provider_result.input_tokens,
        output_tokens=provider_result.output_tokens,
        actor_user=actor_user,
    )
    return _safe_response(ok=True, run=run, text=provider_result.text)
