"""Settings + branding asset routes.

PR-BE 12a/N — mechanical extraction from server.py.

Routes moved (5 handlers):
    GET  /api/settings                       (public settings — admin-only fields stripped)
    GET  /api/admin/settings                 (admin read)
    PUT  /api/admin/settings                 (partial-update; resizes transcode semaphore live)
    POST /api/admin/settings/asset           (branding upload: logo / favicon)
    GET  /api/app-assets/{kind}              (serve uploaded branding)

Per CLAUDE.md: the PUT handler calls ``TRANSCODE_SEMAPHORE.resize()``
when ``transcode_concurrency`` changes so the change is live without a
restart, and the public GET strips admin-only fields via
``_public_settings_payload``. The asset POST is admin-only and the
asset GET is public (cache-control immutable, with SVG XSS hardening
headers).

Late imports of server-side helpers (``_settings``, ``_auth``,
``_save_settings``, etc.) break the ``server -> routers.settings ->
server`` import cycle that would otherwise occur at startup.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/api/settings")
async def get_public_settings():
    from server import _public_settings_payload

    return await _public_settings_payload()


@router.get("/api/admin/settings")
async def get_admin_settings(request: Request):
    from server import _admin_settings_payload, _auth

    _auth.require_role(request, "admin")
    return await _admin_settings_payload()


@router.get("/api/admin/email/status")
async def get_admin_email_status(request: Request):
    from server import _auth
    from services import email_delivery

    _auth.require_role(request, "admin")
    return email_delivery.config_status()


@router.post("/api/admin/email/test")
async def send_admin_email_test(request: Request):
    from server import _auth
    from services import email_delivery

    _auth.require_role(request, "admin")
    body = await request.json()
    to_email = (body.get("email") or "").strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(422, "A test email address is required")
    result = email_delivery.send_test_email(to_email=to_email)
    return {
        "ok": result.ok,
        "status": result.status,
        "provider": result.provider,
        "message_id": result.message_id,
        "detail": result.detail if not result.ok else "",
    }


@router.put("/api/admin/settings")
async def update_admin_settings(request: Request):
    from server import (
        TRANSCODE_SEMAPHORE,
        _auth,
        _log_activity,
        _save_settings,
        _settings,
    )

    user = _auth.require_role(request, "admin")
    body = await request.json()
    updates: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, value in body.items():
        if key not in _settings.EDITABLE_APP_SETTING_KEYS:
            continue
        try:
            updates[key] = _settings.normalize_value(key, value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise HTTPException(400, {"message": "Invalid settings", "errors": errors})

    actor = user.get("username") if isinstance(user, dict) else None
    settings = await _save_settings(updates, actor=actor)

    # Apply live-reloadable side effects (semaphore resize). Other knobs are
    # picked up on the next call site read — see current_*() helpers.
    if "transcode_concurrency" in updates:
        await TRANSCODE_SEMAPHORE.resize(_settings.get_int(settings, "transcode_concurrency", 2))

    if updates:
        tuning_keys = [key for key in updates if key in _settings.TUNING_KNOBS]
        event_type = "settings.tuning_updated" if tuning_keys else "settings.updated"
        _log_activity(
            event_type,
            severity="info",
            message="Tuning settings saved" if tuning_keys else "Settings saved",
            actor=actor,
            metadata={"keys": sorted(updates.keys()), "tuning_keys": sorted(tuning_keys)},
        )

    return {
        "ok": True,
        "settings": settings,
        "assets": {
            "logo_url": _settings.app_asset_url("logo", settings),
            "favicon_url": _settings.app_asset_url("favicon", settings),
        },
        "tuning_knobs": {
            key: dict(spec) for key, spec in _settings.TUNING_KNOBS.items()
        },
        "audit": _settings.list_audit_entries(20),
    }


@router.post("/api/admin/settings/asset")
async def upload_app_asset(file: UploadFile, request: Request):
    from server import (
        APP_ASSETS_DIR,
        _auth,
        _load_settings,
        _log_activity,
        _save_settings,
        _save_upload_file,
        _settings,
    )

    _auth.require_role(request, "admin")
    kind = request.query_params.get("kind", "logo")
    if kind not in _settings.APP_ASSET_CONFIG:
        raise HTTPException(400, "kind must be logo or favicon")

    config = _settings.APP_ASSET_CONFIG[kind]
    filename = file.filename or f"{kind}.png"
    ext = Path(filename).suffix.lower()
    if ext not in config["allowed_exts"]:
        raise HTTPException(400, f"Unsupported {kind} format")

    settings = await _load_settings()
    current_name = settings.get(config["setting_key"], "")
    if current_name:
        (APP_ASSETS_DIR / current_name).unlink(missing_ok=True)

    dest_name = f"app_{kind}{ext}"
    dest = APP_ASSETS_DIR / dest_name
    await _save_upload_file(file, dest, max_size_bytes=config["max_size"])
    actor = _auth.require_auth(request)["username"]
    settings = await _save_settings({config["setting_key"]: dest_name}, actor=actor)
    _log_activity(
        "settings.asset_updated",
        severity="info",
        message=f"{kind.title()} asset updated",
        actor=actor,
        metadata={"kind": kind, "filename": dest_name},
    )
    return {
        "ok": True,
        "kind": kind,
        "filename": dest_name,
        "settings": settings,
        "assets": {
            "logo_url": _settings.app_asset_url("logo", settings),
            "favicon_url": _settings.app_asset_url("favicon", settings),
        },
    }


@router.get("/api/app-assets/{kind}")
async def serve_app_asset(kind: str):
    from server import APP_ASSETS_DIR, _load_settings, _settings

    if kind not in _settings.APP_ASSET_CONFIG:
        raise HTTPException(400, "Invalid asset kind")
    settings = await _load_settings()
    filename = settings.get(_settings.APP_ASSET_CONFIG[kind]["setting_key"], "")
    if not filename:
        raise HTTPException(404, "Asset not configured")
    asset_path = APP_ASSETS_DIR / filename
    if not asset_path.is_file():
        raise HTTPException(404, "Asset not found")
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
    }
    mt = media_types.get(asset_path.suffix.lower(), "application/octet-stream")
    headers = {"Cache-Control": "public, max-age=3600, immutable"}
    if asset_path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["Content-Disposition"] = f"inline; filename=\"{asset_path.name}\""
    return FileResponse(
        str(asset_path),
        media_type=mt,
        headers=headers,
    )
