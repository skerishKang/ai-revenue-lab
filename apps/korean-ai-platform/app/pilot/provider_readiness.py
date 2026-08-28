"""Provider-neutral, read-only readiness truth for Business 14.

This endpoint exists to prove deployment readiness for platform-owned Providers
without exposing secret values, secret binding names, raw environment values, or
making any upstream Provider call.
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router

# Importing platform registers the approved platform-owned Provider specs.
from app.pilot import platform as _platform_registration  # noqa: F401
from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    is_secret_present,
    list_platform_providers,
)

router = Router()

_PROVIDER_MODES = frozenset({"mock", "live"})


def _provider_mode() -> str:
    raw = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
    return raw if raw in _PROVIDER_MODES else "mock"


def _credential_ready(spec: PlatformProviderSpec) -> bool:
    if spec.credential_source == CredentialSource.NONE:
        return True
    if spec.credential_source == CredentialSource.PLATFORM_SECRET:
        return is_secret_present(spec)
    # Request-scoped BYOK is intentionally not considered platform-ready here.
    return False


def _enabled_models_for_provider(provider_id: str) -> list[str]:
    """Return all exact manual-route platform models for a Provider.

    Use the exact-ID registry rather than only the legacy OpenRouter public/auto
    list. This lets explicit-only Provider models (such as initial Poolside
    rollout models) appear in readiness without making them eligible for
    ``b14/auto`` or the legacy public catalog surface.
    """

    return sorted(
        model.model_id
        for model in CATALOG_BY_ID.values()
        if model.enabled
        and model.provider_type == "platform"
        and model.platform_provider_id == provider_id
    )


@router.route("/provider-readiness", methods=["GET"])
async def provider_readiness(request: Request) -> JSONResponse:
    """Return non-secret platform Provider readiness facts only.

    No network or upstream Provider call occurs. `credential_ready` is a boolean
    derived from the existing platform-secret eligibility contract; secret values
    and binding names never enter the response.
    """
    mode = _provider_mode()
    providers: list[dict[str, object]] = []

    for spec in sorted(list_platform_providers(), key=lambda item: item.provider_id):
        model_ids = _enabled_models_for_provider(spec.provider_id)
        credential_ready = _credential_ready(spec)
        route_ready = bool(
            mode == "live"
            and spec.enabled
            and credential_ready
            and model_ids
        )
        providers.append(
            {
                "provider_id": spec.provider_id,
                "enabled": spec.enabled,
                "credential_source": spec.credential_source.value,
                "credential_ready": credential_ready,
                "models": model_ids,
                "route_ready": route_ready,
            }
        )

    ready = any(bool(item["route_ready"]) for item in providers)
    return JSONResponse(
        {
            "status": "ready" if ready else "not_ready",
            "provider_mode": mode,
            "platform_provider_count": len(providers),
            "ready_provider_count": sum(
                1 for item in providers if bool(item["route_ready"])
            ),
            "providers": providers,
        }
    )
