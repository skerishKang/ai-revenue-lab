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

from starlette.routing import Route, Router
from starlette.requests import Request
from starlette.responses import Response

from app.factory import render_template
from app.pilot.demo_models import get_pilot_models, get_pilot_provider_count, get_pilot_model_count
from app.pilot.locale import PLATFORM_SITE_NAME, gettext, locale_from_request, set_locale_cookie, Locale
from app.pilot.routing import resolve_configuration, PilotConfigurationState
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.platform_secrets import any_platform_secret_present
from app.pilot.catalog import CATALOG_BY_ID

#: The PADIEM grades a caller can be served on, in roster order. The grade words
#: are product names; a Provider or model identity never appears here (#6828).
_PADIEM_GRADES: tuple[tuple[str, str], ...] = (
    ("free", "PADIEM 무료 모델"),
    ("plus", "PADIEM Plus 모델"),
    ("pro", "PADIEM Pro 모델"),
    ("max", "PADIEM Max 모델"),
    ("admin", "PADIEM 관리자 모델"),
)


def _workspace_grade_by_model() -> dict[str, str]:
    """Map each model the owner pinned into a grade roster to that grade (#6828).

    Only the deployed registry document declares a roster, so a host without one
    answers an empty map and the picker falls back to a neutral ordinal label. The
    picker never infers a grade the owner did not pin.
    """
    from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

    rosters = effective_tier_fallback()
    grades: dict[str, str] = {}
    free_primary = effective_tier_default()
    if free_primary:
        grades[free_primary] = "free"
    for grade, _label in _PADIEM_GRADES:
        for model_id in rosters.get(grade, ()):
            grades.setdefault(model_id, grade)
    return grades


def _workspace_catalog_models() -> list[dict]:
    """Populate the B14 manual picker from the one owner-approved JSON catalog.

    The historical CATALOG_MODELS scorer contains no customer-selectable IDs.
    Do not infer a Plus/Pro/Max assignment or expose retired model identities.

    #6828: the picker is rendered on an unauthenticated page, so an entry hands
    the screen a PADIEM grade label and never the Provider or model identity. The
    model id stays the option value because it is the wire identity the caller
    has to send back; nothing renders it as text.
    """
    entries = [
        m
        for m in sorted(CATALOG_BY_ID.values(), key=lambda m: (m.sort_order, m.model_id))
        if m.enabled
    ]
    grades = _workspace_grade_by_model()
    labels = [_workspace_catalog_label(m, grades.get(m.model_id)) for m in entries]
    # A grade can back more than one entry; the ordinal keeps two options apart
    # without naming either one.
    counts: dict[str, int] = {}
    rendered: list[dict] = []
    for model, label in zip(entries, labels):
        counts[label] = counts.get(label, 0) + 1
        rendered.append(
            {
                "model_id": model.model_id,
                "label": label if counts[label] == 1 else f"{label} {counts[label]}",
                "korean_score": model.korean_score,
            }
        )
    return rendered


def _workspace_catalog_label(model, grade: str | None) -> str:
    """Return the label the picker shows for one catalog entry (#6828).

    The owner-pinned grade roster decides the label when the model sits in one.
    Otherwise a declared free capability is the only grade the catalog records,
    and the rest fall back to a neutral ordinal label: the picker does not invent
    a Plus/Pro/Max assignment the owner never made.
    """
    for name, label in _PADIEM_GRADES:
        if name == grade:
            return label
    if "free" in model.capabilities:
        return "PADIEM 무료 모델"
    return "PADIEM 모델"


logger = logging.getLogger("korean-ai-platform.pilot")

def _new_request_id() -> str:
    import uuid
    return f"b14req_{uuid.uuid4().hex[:12]}"


async def workspace_page(request: Request):
    """Korean-first chat workspace page.

    Renders the workspace template and injects configuration via a safe
    application/json script element (no |safe JSON in script context).
    Supports locale switching via ?lang= or locale_preference cookie.
    """
    from app.pilot.platform_secrets import ensure_any_platform_secret
    await ensure_any_platform_secret()
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
        "maxTokens": None,
        "b14ProviderMode": runtime_config.provider_mode,
        "b14HasKey": any_platform_secret_present(),
        "b14SiteName": PLATFORM_SITE_NAME,
        "b14CatalogModels": _workspace_catalog_models(),
    }

    # Invalid registry
    if state == PilotConfigurationState.INVALID_REGISTRY:
        config["errorCode"] = "registry_invalid"
        config["pilotConfigured"] = False
        config["b14HasKey"] = any_platform_secret_present()
        ctx["pilot_configured"] = False
        ctx["pilot_models"] = []
        ctx["pilot_provider_count"] = 0
        ctx["pilot_model_count"] = 0
        ctx["pilot_models_json"] = "[]"
        ctx["workspace_config"] = config
        ctx["b14_provider_mode"] = runtime_config.provider_mode
        ctx["b14_has_key"] = any_platform_secret_present()
        ctx["b14_site_name"] = PLATFORM_SITE_NAME
        ctx["b14_catalog_models"] = _workspace_catalog_models()
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
        ctx["b14_provider_mode"] = runtime_config.provider_mode
        ctx["b14_has_key"] = any_platform_secret_present()
        ctx["b14_site_name"] = PLATFORM_SITE_NAME
        ctx["b14_catalog_models"] = _workspace_catalog_models()
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
    ctx["b14_provider_mode"] = runtime_config.provider_mode
    ctx["b14_has_key"] = any_platform_secret_present()
    ctx["b14_site_name"] = PLATFORM_SITE_NAME
    ctx["b14_catalog_models"] = _workspace_catalog_models()
    ctx["error"] = None

    resp = render_template(request, "workspace.html", ctx)
    return _maybe_set_locale(request, resp, locale)


def _maybe_set_locale(request: Request, response: Response, locale: Locale) -> Response:
    """Set locale_preference cookie if lang query param is present."""
    q = request.query_params.get("lang", "")
    if q in (Locale.KO, Locale.EN):
        set_locale_cookie(response, locale)
    return response


router = Router(
    routes=[
        Route("/workspace", workspace_page, methods=["GET"]),
    ]
)
