"""#3782 additional Broker-only audience on the original Engine P01 reader.

Unlike a normal Engine app credential, a Broker P01 receipt read requires
*both* the canonical service identity registry and an explicitly provisioned
server-only Broker caller id. A registered B54 caller cannot reuse that path.
No new secret, authenticator, public route, or production binding is created.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.auth_boundary_diagnostic import P01_CHAT_CALLER_ID
from app.identity_enforcement import (
    CALLER_ID_HEADER,
    RETIRED_CALLER_IDS,
    authenticate_request,
)
from app.service_identity import ServiceIdentityError

BROKER_P01_CALLER_ID_ENV = "PADIEM_ENGINE_BROWSER_BROKER_CALLER_ID"
BROKER_P01_CALLER_SCOPE_WIRED = False
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def authenticate_broker_p01_receipt_reader(
    *, env: Any, headers: Mapping[str, Any] | None, requested_app_id: str,
) -> bool:
    """Private second-audience check; False never exposes credential metadata.

    The caller-id header is NOT proof. The existing registry authenticates its
    secret and app scope again here, after the Worker general request gate.
    Only a server-owned explicitly configured Broker identity may pass.
    """
    expected = getattr(env, BROKER_P01_CALLER_ID_ENV, None)
    if (
        type(expected) is not str
        or _ID.fullmatch(expected) is None
        or expected in RETIRED_CALLER_IDS
        or expected == P01_CHAT_CALLER_ID
        or expected.startswith(("b54-", "b62-"))
        or headers is None
        or type(requested_app_id) is not str
        or not requested_app_id
    ):
        return False
    actual = headers.get(CALLER_ID_HEADER)
    if type(actual) is not str or actual != expected:
        return False
    try:
        authenticate_request(
            env=env, headers=headers, requested_app_id=requested_app_id,
        )
    except (ServiceIdentityError, TypeError, ValueError):
        return False
    return True
