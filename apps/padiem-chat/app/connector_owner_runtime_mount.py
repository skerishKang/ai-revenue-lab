"""#4139 single existing B54 owner registration path, default-unmounted.

This module connects the CURRENT canonical Identity/Broker private bindings
to the already existing owner login / consent / challenge handlers. Neither
browser JSON nor HTTP headers can supply the owner, tenant, workspace, or
private binding. Device redemption remains EXCLUSIVELY via authenticated WSS.

The runtime composer is intentionally OFF in checked-in Worker configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.routing import Route

from .canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from .claw_connector_enrollment_routes import (
    CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
    CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH,
    CONNECTOR_ENROLLMENT_ISSUE_PATH,
    connector_enrollment_consent_grant,
    connector_enrollment_consent_revoke,
    connector_enrollment_issue,
)
from .control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from .control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from .same_origin_guard import expected_browser_origin
from .worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

_OWNER_FLAG = "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED"
_RELEASE_SCOPE = "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"
_REVIEW_SCOPE = "isolated-operator-acceptance-4139"
OWNER_REGISTRATION_PRODUCTION_DEFAULT_MOUNTED = False

_IDENTITY_METHODS = (
    "grant_connector_enrollment_consent",
    "revoke_connector_enrollment_consent",
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
)
_BROKER_METHODS = (
    "issue_enrollment_challenge",
    "get_enrollment_binding",
    "verify_enrollment_bootstrap",
    "redeem_enrollment",
    "revoke_binding",
)


class ExactOwnerOrigin:
    """Session mutations require an exact trusted-config HTTPS browser Origin.

    The product's existing SameOriginGuardMiddleware already enforces
    cookie-authenticated writes. This additional port is required by the
    canonical connector's own browser routes, and never uses request.Host,
    X-Forwarded-Proto, or browser-supplied tenant/owner information.
    """
    def verify(self, request: Any) -> bool:
        try:
            expected = expected_browser_origin(request.app.state.settings)
            return (
                expected is not None
                and request.method == "POST"
                and request.headers.get("origin") == expected
                and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json"
            )
        except (AttributeError, ValueError, TypeError):
            return False


@dataclass(frozen=True, slots=True)
class OwnerEnrollmentPorts:
    identity: CloudflareControlPlaneIdentityAuthority
    host: CanonicalConnectorEnrollmentAsyncHost
    csrf: ExactOwnerOrigin


def compose_owner_enrollment_from_worker(worker_env: Any) -> OwnerEnrollmentPorts | None:
    """Only exact, server-controlled operator acceptance can mount the routes."""
    if (
        binding_value(worker_env, _OWNER_FLAG) != "enabled"
        or binding_value(worker_env, _RELEASE_SCOPE) != _REVIEW_SCOPE
    ):
        return None

    identity_binding = binding_value(worker_env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME)
    broker_binding = binding_value(worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if (
        identity_binding is None
        or broker_binding is None
        or any(not callable(getattr(identity_binding, method, None)) for method in _IDENTITY_METHODS)
        or any(not callable(getattr(broker_binding, method, None)) for method in _BROKER_METHODS)
    ):
        # Explicitly armed but missing authority is a deployment failure,
        # not a public route that silently accepts unauthenticated clients.
        raise ValueError("canonical connector owner Identity/Broker authority unavailable")
    identity = CloudflareControlPlaneIdentityAuthority(identity_binding)
    broker = CloudflareCanonicalBrokerPairingClient(broker_binding)
    return OwnerEnrollmentPorts(
        identity=identity,
        host=CanonicalConnectorEnrollmentAsyncHost(
            identity=identity, broker=broker, credential_handoff=None,
        ),
        csrf=ExactOwnerOrigin(),
    )


def reviewed_owner_enrollment_routes(ports: OwnerEnrollmentPorts) -> tuple[Route, ...]:
    if type(ports) is not OwnerEnrollmentPorts:
        raise ValueError("canonical connector owner registration ports missing")
    if (
        type(ports.identity) is not CloudflareControlPlaneIdentityAuthority
        or type(ports.host) is not CanonicalConnectorEnrollmentAsyncHost
        or type(ports.csrf) is not ExactOwnerOrigin
    ):
        raise ValueError("canonical connector owner registration authority invalid")
    return (
        Route(CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
              connector_enrollment_consent_grant, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH,
              connector_enrollment_consent_revoke, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_ISSUE_PATH, connector_enrollment_issue, methods=["POST"]),
    )
