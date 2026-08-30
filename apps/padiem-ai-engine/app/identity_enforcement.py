"""Wire-level enforcement for first-party Padiem AI Engine callers.

The contract is server-side only: callers identify themselves with a bounded
caller id plus a high-entropy credential kept in deployment secret storage.
The request body remains the source of the requested ``app_id``; identity
verification binds that app to the authenticated caller before execution.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.service_identity import (
    EngineCallerRegistry,
    ServiceIdentityError,
    TrustedEngineCaller,
    authenticate_engine_caller,
    caller_secret_digest,
)

CALLER_ID_HEADER = "x-padiem-engine-caller"
CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential"
CALLER_ID_ENV = "PADIEM_ENGINE_CALLER_ID"
CALLER_SECRET_ENV = "PADIEM_ENGINE_CALLER_SECRET"
CALLER_ALLOWED_APPS_ENV = "PADIEM_ENGINE_ALLOWED_APPS"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def build_registry_from_env(env: Any) -> EngineCallerRegistry | None:
    """Build the one-caller registry from deployment configuration.

    Multiple callers can be introduced later with a dedicated secret-backed
    registry. This first activation slice intentionally supports one explicit
    first-party caller and refuses partially configured state.
    """

    caller_id = _text(getattr(env, CALLER_ID_ENV, None)).strip()
    secret = _text(getattr(env, CALLER_SECRET_ENV, None))
    allowed_raw = _text(getattr(env, CALLER_ALLOWED_APPS_ENV, None)).strip()

    if not caller_id and not secret and not allowed_raw:
        return None
    if not caller_id or not secret or not allowed_raw:
        raise ServiceIdentityError(
            "service_identity_misconfigured",
            "Padiem AI Engine service identity is misconfigured",
        )

    allowed_apps = tuple(item.strip() for item in allowed_raw.split(",") if item.strip())
    if not allowed_apps:
        raise ServiceIdentityError(
            "service_identity_misconfigured",
            "Padiem AI Engine caller scope is empty",
        )

    caller = TrustedEngineCaller(
        caller_id=caller_id,
        allowed_app_ids=allowed_apps,
        credential_sha256=caller_secret_digest(secret),
    )
    return EngineCallerRegistry(callers=(caller,))


def authenticate_request(
    *,
    env: Any,
    headers: Mapping[str, Any] | None,
    requested_app_id: str,
) -> None:
    """Fail closed unless the request authenticates as a registered caller."""

    registry = build_registry_from_env(env)
    if registry is None:
        raise ServiceIdentityError(
            "service_identity_unavailable",
            "Padiem AI Engine service identity is unavailable",
        )

    caller_id = _text(headers.get(CALLER_ID_HEADER) if headers is not None else None).strip()
    credential = _text(
        headers.get(CALLER_CREDENTIAL_HEADER) if headers is not None else None
    )
    if not caller_id or not credential:
        raise ServiceIdentityError(
            "service_authentication_failed",
            "Engine caller authentication failed",
        )

    authenticate_engine_caller(
        registry=registry,
        caller_id=caller_id,
        credential=credential,
        requested_app_id=requested_app_id,
    )
