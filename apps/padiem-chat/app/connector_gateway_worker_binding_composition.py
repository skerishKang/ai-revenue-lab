"""#4139 CENTRAL: source-only Cloudflare Worker Service Binding composition.

The public Worker, asset router, production app_factory and Python ASGI/WSGI
entrypoint DO NOT import, mount or call this module. Explicit review harnesses
may inject the existing worker.env and independent trusted ingress verifier.

No browser-provided device id, headers, cookies, CF-looking request metadata,
or client URL may select an Identity/Broker binding or establish TLS trust.
No new local credential repository, Broker, consent authority or public HTTP
fallback is created here.
"""
from __future__ import annotations

from typing import Any

from .canonical_connector_gateway_source_composition import (
    create_review_only_connector_gateway_app,
)
from .worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED = False
WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED = False
WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED = False


def build_review_only_gateway_from_worker_env(
    *, worker_env: Any = None, trusted_tls_ingress: Any = None,
    source_test_authorized: bool = False,
) -> Any:
    """Compose existing two private services, only after explicit source review.

    The sole namespace for private clients is the Worker-injected environment.
    This function never reads Request/headers or os.environ, and does not
    derive authority from HTTP Host, CF-Visitor, X-Forwarded-Proto or device_id.
    The trusted ingress port MUST be provided independently by a future
    operator-reviewed Cloudflare-edge verifier. No such verifier is supplied
    by this integration PR.
    """
    if source_test_authorized is not True:
        raise RuntimeError("PADIEM Connector Worker WSS source not activated")
    if worker_env is None:
        raise ValueError("Worker Service Binding environment unavailable")
    identity = binding_value(worker_env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME)
    broker = binding_value(worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if identity is None or broker is None:
        raise ValueError("Canonical Identity/Broker private bindings unavailable")
    if not callable(getattr(trusted_tls_ingress, "verify", None)):
        raise ValueError("Independently reviewed Worker TLS ingress verifier missing")
    return create_review_only_connector_gateway_app(
        identity_binding=identity,
        broker_binding=broker,
        trusted_tls_ingress=trusted_tls_ingress,
        source_test_authorized=True,
    )


__all__ = [
    "WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED",
    "WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED",
    "WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED",
    "build_review_only_gateway_from_worker_env",
]
