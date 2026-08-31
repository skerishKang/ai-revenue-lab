from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.identity_enforcement import (
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
    authenticate_request,
    build_registry_from_env,
)
from app.service_identity import ServiceIdentityError, caller_secret_digest


SECRET = "S" * 48


@dataclass
class Env:
    PADIEM_ENGINE_CALLER_ID: str = "b62-service"
    PADIEM_ENGINE_CALLER_SECRET: str = SECRET
    PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"


def test_registry_never_exposes_plaintext_secret() -> None:
    registry = build_registry_from_env(Env())
    assert registry is not None
    caller = registry.callers[0]
    assert caller.credential_sha256 == caller_secret_digest(SECRET)
    assert SECRET not in repr(caller)
    assert SECRET not in str(caller.to_public_dict())


def test_valid_caller_is_bound_to_requested_app() -> None:
    authenticate_request(
        env=Env(),
        headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
        requested_app_id="padiem-chat",
    )


def test_wrong_credential_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Env(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: "W" * 48},
            requested_app_id="padiem-chat",
        )
    assert exc_info.value.code == "service_authentication_failed"


def test_cross_app_impersonation_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Env(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="other-product",
        )
    assert exc_info.value.code == "service_app_not_authorized"


def test_missing_server_identity_fails_closed() -> None:
    class Unconfigured:
        pass

    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Unconfigured(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="padiem-chat",
        )
    assert exc_info.value.code == "service_identity_unavailable"


def test_partial_server_identity_configuration_fails_closed() -> None:
    class Partial:
        PADIEM_ENGINE_CALLER_ID = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET = SECRET
        PADIEM_ENGINE_ALLOWED_APPS = ""

    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(Partial())
    assert exc_info.value.code == "service_identity_misconfigured"
