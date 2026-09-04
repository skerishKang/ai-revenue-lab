"""Wire-level enforcement for first-party Padiem AI Engine callers.

The contract is server-side only: callers identify themselves with a bounded
caller id plus a high-entropy credential kept in deployment secret storage.
The request body remains the source of the requested ``app_id``; identity
verification binds that app to the authenticated caller before execution.

Deployment configuration supports two mutually exclusive authorities:

- ``PADIEM_ENGINE_CALLER_REGISTRY_V1``: a versioned, secret-backed,
  bounded multi-caller registry payload. When configured it is the only
  caller authority; a malformed or blank payload fails closed and never
  falls back to the legacy configuration.
- the legacy one-caller trio (``PADIEM_ENGINE_CALLER_ID``,
  ``PADIEM_ENGINE_CALLER_SECRET``, ``PADIEM_ENGINE_ALLOWED_APPS``):
  authoritative only while the V1 registry variable is genuinely absent,
  preserving existing deployment behavior unchanged.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.service_identity import (
    MAX_ENGINE_CALLERS,
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

CALLER_REGISTRY_V1_ENV = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
CALLER_REGISTRY_V1_VERSION = 1

# Bounded serialized registry input. A registry legally packed to the
# generic contract limits (64 callers, 32 app ids and a 512-byte credential
# each) stays well below this cap, so the bound only rejects absurd
# deployment payloads before any parsing or credential digesting happens.
MAX_CALLER_REGISTRY_V1_BYTES = 524288

_CALLER_REGISTRY_V1_TOP_LEVEL_KEYS = frozenset({"version", "callers"})
_CALLER_REGISTRY_V1_ENTRY_KEYS = frozenset(
    {"caller_id", "credential", "allowed_app_ids"}
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_caller_registry_v1(raw: str) -> EngineCallerRegistry:
    """Parse the bounded V1 secret-backed multi-caller registry payload.

    Every failure raises ``ServiceIdentityError`` (fail closed). Safe error
    messages never contain payload fragments or credential plaintext. Each
    entry credential is immediately converted with the existing
    ``caller_secret_digest`` contract before constructing a
    ``TrustedEngineCaller``; no second authentication implementation is
    introduced here.
    """

    if not isinstance(raw, str):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 must be a JSON string",
        )
    if len(raw.encode("utf-8")) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 exceeds the bounded input size",
        )

    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 is not valid JSON",
        ) from None

    if not isinstance(payload, dict) or set(payload.keys()) != _CALLER_REGISTRY_V1_TOP_LEVEL_KEYS:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 must contain exactly version and callers",
        )

    version = payload["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != CALLER_REGISTRY_V1_VERSION
    ):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 version is unsupported",
        )

    callers_raw = payload["callers"]
    if not isinstance(callers_raw, list):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry V1 callers must be a JSON array",
        )
    if not 1 <= len(callers_raw) <= MAX_ENGINE_CALLERS:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            f"Padiem AI Engine caller registry V1 must contain 1 to {MAX_ENGINE_CALLERS} callers",
        )

    callers = []
    for entry in callers_raw:
        if not isinstance(entry, dict) or set(entry.keys()) != _CALLER_REGISTRY_V1_ENTRY_KEYS:
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry V1 caller entries must contain exactly caller_id, credential, and allowed_app_ids",
            )
        allowed_app_ids = entry["allowed_app_ids"]
        if not isinstance(allowed_app_ids, list):
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry V1 allowed_app_ids must be a JSON array",
            )
        callers.append(
            TrustedEngineCaller(
                caller_id=entry["caller_id"],
                allowed_app_ids=tuple(allowed_app_ids),
                credential_sha256=caller_secret_digest(entry["credential"]),
            )
        )

    return EngineCallerRegistry(callers=tuple(callers))


def build_registry_from_env(env: Any) -> EngineCallerRegistry | None:
    """Build the caller registry from deployment configuration.

    When ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` is configured, the parsed
    secret-backed registry is the single caller authority: a malformed,
    blank, or unsupported payload fails closed and never falls back to the
    legacy one-caller trio. When the registry variable is genuinely absent,
    the legacy one-caller trio remains authoritative with unchanged
    behavior and refuses partially configured state.
    """

    registry_raw = getattr(env, CALLER_REGISTRY_V1_ENV, None)
    if registry_raw is not None:
        if not isinstance(registry_raw, str):
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry V1 must be a JSON string",
            )
        if not registry_raw.strip():
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry V1 is configured but blank",
            )
        return parse_caller_registry_v1(registry_raw)

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
