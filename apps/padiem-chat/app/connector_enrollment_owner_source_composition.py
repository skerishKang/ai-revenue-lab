"""#4139 CENTRAL: browser-to-canonical-PC-enrollment source composition.

The real B54 application and deployed Worker DO NOT mount this app. This
separate, explicit review harness wires the already implemented owner login,
CSRF, Identity consent RPC and canonical Broker challenge issuer together.
There is deliberately NO device redeem or credential transfer route here:
the device must use the independently attested same-socket WSS gateway.

No scope is accepted from request JSON; active owner session and canonical
Identity decide the owner/account/workspace. Source review authorization is
never a production activation switch.
"""
from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from .claw_connector_enrollment_routes import (
    CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
    CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH,
    CONNECTOR_ENROLLMENT_ISSUE_PATH,
    connector_enrollment_consent_grant,
    connector_enrollment_consent_revoke,
    connector_enrollment_issue,
)

OWNER_ENROLLMENT_PRODUCTION_MOUNTED = False
OWNER_ENROLLMENT_DEVICE_REDEEM_MOUNTED = False


def build_review_only_owner_enrollment_app(
    *, identity_authority: Any = None, async_host: Any = None,
    browser_csrf: Any = None, source_test_authorized: bool = False,
) -> Starlette:
    """Connect existing owner-only pieces without adding a production route.

    The consent identity port may only be bound to a canonical Identity
    Service Binding in deployment. The host must validate the current consent
    and issue a one-time challenge in the canonical Broker; the browser is
    never permitted to redeem, mint credentials or assert an owner scope.
    """
    if source_test_authorized is not True:
        raise RuntimeError("Connector owner enrollment route not activated")
    if any(not callable(getattr(identity_authority, method, None)) for method in (
        "grant_connector_enrollment_consent",
        "revoke_connector_enrollment_consent",
    )):
        raise ValueError("Canonical Identity owner-consent port missing")
    if not callable(getattr(async_host, "issue", None)):
        raise ValueError("Canonical async Broker enrollment issuer missing")
    if not callable(getattr(browser_csrf, "verify", None)):
        raise ValueError("Signed-in owner CSRF verifier missing")

    app = Starlette(routes=[
        Route(CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
              connector_enrollment_consent_grant, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH,
              connector_enrollment_consent_revoke, methods=["POST"]),
        Route(CONNECTOR_ENROLLMENT_ISSUE_PATH,
              connector_enrollment_issue, methods=["POST"]),
    ])
    app.state.control_plane_identity_authority = identity_authority
    app.state.connector_enrollment_async_host = async_host
    app.state.connector_enrollment_browser_csrf = browser_csrf
    return app


__all__ = [
    "OWNER_ENROLLMENT_PRODUCTION_MOUNTED",
    "OWNER_ENROLLMENT_DEVICE_REDEEM_MOUNTED",
    "build_review_only_owner_enrollment_app",
]
