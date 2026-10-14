"""#4139 real Worker entrypoint seam for the canonical single-socket pairing.

This is NOT an activation: the deployed Worker does not carry either the
explicit opt-in or the required private Broker Service Binding. The only
existing Cloudflare WSS implementation is reused after exact ingress/TLS
admission. Browser input cannot provide enablement, scope, or Worker binding.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from .worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

# These values are SERVER-owned Worker configuration (NOT HTTP request data).
_ENABLED = "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED"
_RELEASE_SCOPE = "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"
_APPROVED_SCOPE = "isolated-operator-acceptance-4139"
PRODUCTION_GATEWAY_DEFAULT_ON = False


async def maybe_dispatch_connector_gateway(
    *, request: Any, worker_env: Any,
    response_factory: Any,
) -> Any | None:
    """Return None for default-OFF; otherwise dispatch canonical WSS or 503.

    A review/acceptance environment must supply *both* explicit, server-owned
    gates and the real typed private Identity + Broker bindings. This adds a
    direct executable Worker→WSS dispatch seam; no deploy, route setting or
    permission is added to the canonical production manifest.
    """
    raw_url = getattr(request, "url", "")
    if type(raw_url) is not str or urlparse(raw_url).path != CONNECTOR_GATEWAY_WSS_PATH:
        return None
    if (
        binding_value(worker_env, _ENABLED) != "enabled"
        or binding_value(worker_env, _RELEASE_SCOPE) != _APPROVED_SCOPE
    ):
        return None

    def unavailable():
        return response_factory(
            "Connector gateway unavailable.",
            status=503,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    if (
        binding_value(worker_env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME) is None
        or binding_value(worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME) is None
    ):
        return unavailable()
    if binding_value(
        worker_env, "PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED",
    ) == "enabled":
        # EXACT isolated-acceptance route ONLY. No production/public Worker
        # dispatch and no ASGI fallback if the private DO bridge refuses.
        from .connector_gateway_broker_do_upgrade import (
            dispatch_isolated_native_pc_wss,
        )
        from workers import Request
        return await dispatch_isolated_native_pc_wss(
            request=request, worker_env=worker_env,
            request_factory=Request, response_factory=response_factory,
        )
    try:
        # Import AFTER strict Worker-owned gates. The sole real WebSocketPair
        # adapter validates exact origin, pre-pair Cloudflare request.cf TLS,
        # original Broker possession proofs, Identity consent and DPAPI ACK.
        from .connector_gateway_worker_asgi_review import (
            dispatch_review_only_worker_first_pairing_upgrade,
        )
        return await dispatch_review_only_worker_first_pairing_upgrade(
            request=request, worker_env=worker_env,
            source_test_authorized=True,
        )
    except (RuntimeError, ValueError, TypeError, AttributeError):
        # Deny before a successful upgrade without projecting Cloudflare
        # binding contents, raw pairing code, request URL or internal errors.
        return unavailable()
