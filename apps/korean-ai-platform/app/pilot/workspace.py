"""Phase 3: Korean-first session workspace pilot.

Routes:
- GET  /workspace  — Korean-first chat workspace page

The client-side JS calls POST /api/pilot/v1/chat/completions directly
(Phase 2 API), so no server-side proxy endpoint is needed.

Design principles:
- Korean-first UI (English optional via ?lang=en)
- Session-only: messages in JS memory, keys in JS memory
- No server-side storage of keys, prompts, or responses
- XSS-safe: all user/assistant content rendered via textContent
- Config injected via application/json script element (safe from XSS)
"""

from __future__ import annotations

import json
import logging

from starlette.routing import Router
from starlette.requests import Request
from starlette.responses import Response

from app.factory import render_template
from app.pilot.demo_models import get_pilot_models, get_pilot_provider_count, get_pilot_model_count
from app.pilot.locale import gettext, locale_from_request, set_locale_cookie, Locale
from app.pilot.routing import resolve_configuration, PilotConfigurationState
from app.pilot.openrouter_config import openrouter_config
from app.pilot.catalog import list_catalog_summaries

logger = logging.getLogger("korean-ai-platform.pilot")

router = Router()


def _new_request_id() -> str:
    import uuid
    return f"b14req_{uuid.uuid4().hex[:12]}"


@router.route("/workspace", methods=["GET"])
async def workspace_page(request: Request):
    """Korean-first chat workspace page.

    Renders the workspace template and injects configuration via a safe
    application/json script element (no |safe JSON in script context).
    Supports locale switching via ?lang= or locale_preference cookie.
    """
    locale = locale_from_request(request)
    _ = lambda key: gettext(key, locale)  # noqa: E731
    state = resolve_configuration()

    # Build base context
    ctx = {
        "_": lambda key, **kw: gettext(key, locale, **kw),
        "lang": locale.value,
        "html_lang": locale.value,
    }

    # Default config for JS init
    config = {
        "models": [],
        "pilotConfigured": False,
        "providerCount": 0,
        "modelCount": 0,
        "lang": locale.value,
        "errorCode": None,
        "maxTokens": 512,
        "b14ProviderMode": openrouter_config.provider_mode,
        "b14HasKey": openrouter_config.has_key,
        "b14SiteName": openrouter_config.site_name,
        "b14CatalogModels": list_catalog_summaries(),
        "b14AutoModelId": "b14/auto",
    }

    # Invalid registry
    if state == PilotConfigurationState.INVALID_REGISTRY:
        config["errorCode"] = "registry_invalid"
        config["pilotConfigured"] = False
        config["b14HasKey"] = openrouter_config.has_key
        ctx["pilot_configured"] = False
        ctx["pilot_models"] = []
        ctx["pilot_provider_count"] = 0
        ctx["pilot_model_count"] = 0
        ctx["pilot_models_json"] = "[]"
        ctx["workspace_config"] = config
        ctx["b14_provider_mode"] = openrouter_config.provider_mode
        ctx["b14_has_key"] = openrouter_config.has_key
        ctx["b14_site_name"] = openrouter_config.site_name
        ctx["b14_catalog_models"] = list_catalog_summaries()
        ctx["error"] = {
            "code": "registry_invalid",
            "message": _("error.registry_invalid"),
            "request_id": _new_request_id(),
        }
        resp = render_template(request, "workspace.html", ctx)
        return _maybe_set_locale(request, resp, locale)

    # Not configured
    if state == PilotConfigurationState.NOT_CONFIGURED:
        config["pilotConfigured"] = False
        ctx["pilot_configured"] = False
        ctx["pilot_models"] = []
        ctx["pilot_provider_count"] = 0
        ctx["pilot_model_count"] = 0
        ctx["pilot_models_json"] = "[]"
        ctx["workspace_config"] = config
        ctx["b14_provider_mode"] = openrouter_config.provider_mode
        ctx["b14_has_key"] = openrouter_config.has_key
        ctx["b14_site_name"] = openrouter_config.site_name
        ctx["b14_catalog_models"] = list_catalog_summaries()
        ctx["error"] = None
        resp = render_template(request, "workspace.html", ctx)
        return _maybe_set_locale(request, resp, locale)

    # Valid registry or legacy
    models = get_pilot_models()
    provider_count = get_pilot_provider_count()
    model_count = get_pilot_model_count()

    config["models"] = models
    config["pilotConfigured"] = True
    config["providerCount"] = provider_count
    config["modelCount"] = model_count

    ctx["pilot_configured"] = True
    ctx["pilot_models"] = models
    ctx["pilot_provider_count"] = provider_count
    ctx["pilot_model_count"] = model_count
    ctx["pilot_models_json"] = json.dumps(models, ensure_ascii=False)
    ctx["workspace_config"] = config
    ctx["b14_provider_mode"] = openrouter_config.provider_mode
    ctx["b14_has_key"] = openrouter_config.has_key
    ctx["b14_site_name"] = openrouter_config.site_name
    ctx["b14_catalog_models"] = list_catalog_summaries()
    ctx["error"] = None

    resp = render_template(request, "workspace.html", ctx)
    return _maybe_set_locale(request, resp, locale)


def _maybe_set_locale(request: Request, response: Response, locale: Locale) -> Response:
    """Set locale_preference cookie if lang query param is present."""
    q = request.query_params.get("lang", "")
    if q in (Locale.KO, Locale.EN):
        set_locale_cookie(response, locale)
    return response
