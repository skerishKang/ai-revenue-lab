"""Source-only CENTRAL composition of the EXISTING canonical private clients.

This is a single-review-lane WSS route constructor, not application startup.
The PADIEM Chat app_factory, Cloudflare entrypoint and production routing
do NOT import, mount or instantiate it. A real Worker TLS/peer verifier,
authenticated pre-enrollment hostname/routing and feature-flag release review
must precede a live mount. A browser Origin, cookie, device ID or forwarded
TLS header can NEVER establish trusted ingress provenance.
"""
from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from .canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from .connector_gateway_websocket_session import run_device_initiated_enrollment
from .control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from .control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

CONNECTOR_GATEWAY_WSS_PATH = "/api/claw/connector/gateway/session"
CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED = False
CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED = False
_CONNECTOR_IDENTITY_RPC = (
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
)
_CONNECTOR_BROKER_RPC = (
    "gateway_bootstrap_rpc",
    "get_enrollment_binding",
    "verify_enrollment_bootstrap",
    "redeem_enrollment",
    "revoke_binding",
)


def create_review_only_connector_gateway_app(
    *,
    identity_binding: Any = None,
    broker_binding: Any = None,
    trusted_tls_ingress: Any = None,
    source_test_authorized: bool = False,
) -> Starlette:
    """Connect typed Identity+Broker Service Bindings to the one-socket Host.

    Explicit source/test construction only: default raises, and this module is
    not imported or called by the product Worker entrypoint. The ingress port
    is a reviewed and externally attested TLS provenance verifier, NOT a
    header-based or scheme-only implementation. This constructor does not
    mint such provenance, provision mTLS certificates or switch on a release.
    """
    if source_test_authorized is not True:
        raise RuntimeError("Connector WSS runtime is not operator-activated")
    if any(not callable(getattr(identity_binding, name, None)) for name in _CONNECTOR_IDENTITY_RPC):
        raise ValueError("Reviewed private canonical Identity Service Binding missing")
    if any(not callable(getattr(broker_binding, name, None)) for name in _CONNECTOR_BROKER_RPC):
        raise ValueError("Reviewed private canonical Broker Service Binding missing")
    if not callable(getattr(trusted_tls_ingress, "verify", None)):
        raise ValueError("Independently verified server-side TLS ingress port missing")
    identity = CloudflareControlPlaneIdentityAuthority(identity_binding)
    broker = CloudflareCanonicalBrokerPairingClient(broker_binding)

    def canonical_host_factory(*, handoff):
        # SINGLE redemption owner, SINGLE protected installation path.
        return CanonicalConnectorEnrollmentAsyncHost(
            identity=identity, broker=broker, credential_handoff=handoff,
        )

    async def device_websocket_entry(websocket):
        await run_device_initiated_enrollment(
            websocket,
            trusted_tls=trusted_tls_ingress,
            broker=broker,
            host_factory=canonical_host_factory,
        )

    return Starlette(routes=[
        WebSocketRoute(CONNECTOR_GATEWAY_WSS_PATH, device_websocket_entry),
    ])


__all__ = [
    "CONNECTOR_GATEWAY_WSS_PATH",
    "CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED",
    "CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED",
    "create_review_only_connector_gateway_app",
]
