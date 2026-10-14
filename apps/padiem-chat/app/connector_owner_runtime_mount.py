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
from .connector_owner_setup_page import (
    SETUP_PATH, SCRIPT_PATH, owner_setup_page, owner_setup_script,
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
_ONE_CLICK_OWNER_FLAG = "PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"
_IDENTITY_PC_PREFLIGHT_FLAG = "PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED"
_NATIVE_PC_DELIVERY_FLAG = "PADIEM_CONNECTOR_OWNER_PC_NATIVE_DELIVERY_ENABLED"
_RELEASE_SCOPE = "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"
_REVIEW_SCOPE = "isolated-operator-acceptance-4139"
_LIVE_SCOPE = "owner-controlled-production-4139"
_LIVE_ENABLED = "PADIEM_CONNECTOR_OWNER_PRODUCTION_ENABLED"
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
    one_click_factory: Any = None
    identity_pc_preflight: Any = None
    native_pc_completion: Any = None


def compose_owner_enrollment_from_worker(worker_env: Any) -> OwnerEnrollmentPorts | None:
    """Only exact, server-controlled operator acceptance can mount the routes."""
    scope = binding_value(worker_env, _RELEASE_SCOPE)
    if (
        binding_value(worker_env, _OWNER_FLAG) != "enabled"
        or (
            scope != _REVIEW_SCOPE
            and not (
                scope == _LIVE_SCOPE
                and binding_value(worker_env, _LIVE_ENABLED) == "enabled"
            )
        )
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
    host = CanonicalConnectorEnrollmentAsyncHost(
        identity=identity, broker=broker, credential_handoff=None,
    )
    one_click = None
    # This is additional, explicit server-owned acceptance configuration.
    # The ordinary B54 consent/issue flow remains unchanged and unaffected.
    if binding_value(worker_env, _ONE_CLICK_OWNER_FLAG) == "enabled":
        from .connector_owner_one_click_factory import VerifiedOwnerOneClickFactory
        one_click = VerifiedOwnerOneClickFactory(
            identity=identity, host=host, broker_binding=broker_binding,
        )
    identity_pc_preflight = None
    if binding_value(worker_env, _IDENTITY_PC_PREFLIGHT_FLAG) == "enabled":
        # B54 can only reach the exact PC WSS through the existing
        # canonical Broker private Service Binding. This port never
        # mounts an HTTP route or issues a device credential itself.
        if one_click is None:
            raise ValueError("B54 one-click owner enrollment must be enabled first")
        from .connector_owner_identity_pc_completion import CanonicalOwnerPcIdentityPreflight
        identity_pc_preflight = CanonicalOwnerPcIdentityPreflight(
            identity=identity, broker=broker, private_broker=broker_binding,
        )
    native_completion = None
    if binding_value(worker_env, _NATIVE_PC_DELIVERY_FLAG) == "enabled":
        if identity_pc_preflight is None:
            raise ValueError("B54 verified native PC identity preflight required")
        from .connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
        native_completion = CanonicalOwnerNativePcCompletion(
            identity=identity, broker=broker,
            private_broker=broker_binding,
            preflight=identity_pc_preflight,
        )
        from .connector_native_pc_gateway_port import _RPC
        if any(not callable(getattr(broker_binding, method, None)) for method in _RPC):
            raise ValueError("canonical same-PC private native gateway unavailable")
    return OwnerEnrollmentPorts(
        identity=identity, host=host, csrf=ExactOwnerOrigin(),
        one_click_factory=one_click,
        identity_pc_preflight=identity_pc_preflight,
        native_pc_completion=native_completion,
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
    # No one-click route without a verified server-provided Broker RPC.
    one_click_route = ()
    if ports.one_click_factory is not None:
        from .connector_owner_one_click_factory import VerifiedOwnerOneClickFactory
        from .connector_one_click_approval_route import (
            OWNER_APPROVE_LINK_PATH, owner_approve_pc_link,
        )
        if type(ports.one_click_factory) is not VerifiedOwnerOneClickFactory:
            raise ValueError("untrusted one-click owner approval factory")
        one_click_route = (
            Route(OWNER_APPROVE_LINK_PATH, owner_approve_pc_link, methods=["POST"]),
        )
    return (
        Route(SETUP_PATH, owner_setup_page, methods=["GET"]),
        Route(SCRIPT_PATH, owner_setup_script, methods=["GET"]),
        Route(CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
              connector_enrollment_consent_grant, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH,
              connector_enrollment_consent_revoke, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_ISSUE_PATH, connector_enrollment_issue, methods=["POST"]),
    ) + one_click_route
