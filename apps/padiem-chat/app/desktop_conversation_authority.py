"""#3436 B2c — the trusted device-session authority behind the Desktop conversation read.

Mirrors the established trusted-composition pattern (``claw_local_access_composition``):
the deployed Python Worker has no process environment, so the authority is built
only from trusted Worker bindings resolved by the composition root. This module
never touches a process environment and never reads request input for identity.

The trusted boundary is the ``LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`` binding
pointing at the canonical Local Agent broker Worker
(``packages/padiem-control-plane/local_agent_broker_worker.py``). That
entrypoint's ``authenticate_device_session`` RPC — the narrow read-only,
session-correlated canonical authentication projection (#3436 B2c) — is the
only thing this composition may consume. The canonical broker verifies the
device credential and the full session/binding scope correlation with its own
existing verifier and derives ``account_ref`` / ``workspace_ref`` from the
verified binding state; nothing here re-verifies a credential, bridges a
browser session, or accepts a caller-named identity. A compatible binding is
wrapped into the typed port the Desktop conversation routes read; any other
state — binding absent (today's deploy), binding without the
``authenticate_device_session`` method, or a construction failure — yields
``None`` plus one bounded public-safe diagnostic, and the app keeps the
fail-closed unconfigured authority installed by ``create_app``. A missing
trusted runtime must never become an accepted device session.

Contract markers
----------------
``TRUSTED_BOUNDARY = "worker:LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"``
``CONSUMED_BROKER_API = "authenticate_device_session RPC (canonical broker Worker)"``
``COMPOSITION_INPUT_SOURCE = "trusted_worker_bindings_only"``
``FAIL_CLOSED_WHEN_BOUNDARY_ABSENT = True``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
``SECOND_IDENTITY_AUTHORITY = 0``
``SECOND_SESSION_AUTHORITY = 0``
``SECOND_CREDENTIAL_VERIFIER = 0``
``BROWSER_PADIEM_SESSION_COOKIE_COPY = 0``
``CALLER_WORKSPACE_AUTHORITY = 0``
``SERVER_DERIVED_ACCOUNT_REF = True``
``SERVER_DERIVED_WORKSPACE_REF = True``
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .worker_config import (
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

__all__ = [
    "DESKTOP_AUTH_DIAG_BINDING_ABSENT",
    "DESKTOP_AUTH_DIAG_PORT_INCOMPATIBLE",
    "DESKTOP_AUTH_DIAG_CONSTRUCTION_FAILED",
    "DesktopDeviceSessionAuthority",
    "UnconfiguredDesktopDeviceSessionAuthority",
    "BrokerAuthorityDeviceSessionAuthPort",
    "build_desktop_device_session_authority",
    "build_desktop_device_session_authority_with_diagnostic",
    "validate_authenticated_device_session",
]

# Bounded public-safe diagnostics. Fixed constants only: exception messages,
# binding values and any trusted-boundary detail are never propagated.
DESKTOP_AUTH_DIAG_BINDING_ABSENT = "desktop_conversation_authority_binding_absent"
DESKTOP_AUTH_DIAG_PORT_INCOMPATIBLE = "desktop_conversation_authority_port_incompatible"
DESKTOP_AUTH_DIAG_CONSTRUCTION_FAILED = "desktop_conversation_authority_construction_failed"

# The closed allowlist the canonical broker's authenticate_device_session
# projection may carry. Anything else — a credential digest, a raw credential,
# a bearer token — fails the projection closed.
_PROJECTION_KEYS = frozenset(
    {
        "authenticated",
        "session_id",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "session_expires_at",
        "credential_digest_exposed",
        "raw_device_credential",
    }
)
_MAX_REF_LENGTH = 256
_MAX_TIMESTAMP_LENGTH = 64
_REF_CHARSET = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-"
)


def _bounded_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_REF_LENGTH:
        return None
    if not all(character in _REF_CHARSET for character in value):
        return None
    if not value[0].isalnum():
        return None
    return value


def validate_authenticated_device_session(projection: Any) -> dict[str, Any] | None:
    """Accept only the exact closed canonical projection, or fail closed.

    ``authenticated`` must be the literal ``True``, the negative markers must
    be the literal ``False``, and every identity field must carry the broker
    safe-reference grammar. Any mismatch — including a projection carrying
    extra material such as a credential digest — returns ``None`` so the route
    refuses instead of trusting a malformed authority answer.
    """

    if not isinstance(projection, Mapping) or isinstance(projection, (str, bytes)):
        return None
    if frozenset(projection) != _PROJECTION_KEYS:
        return None
    if projection.get("authenticated") is not True:
        return None
    if projection.get("credential_digest_exposed") is not False:
        return None
    if projection.get("raw_device_credential") is not False:
        return None
    if not isinstance(projection.get("credential_generation"), int) or isinstance(
        projection.get("credential_generation"), bool
    ):
        return None
    if projection["credential_generation"] < 1:
        return None
    session_id = _bounded_ref(projection.get("session_id"))
    binding_ref = _bounded_ref(projection.get("binding_ref"))
    device_id = _bounded_ref(projection.get("device_id"))
    account_ref = _bounded_ref(projection.get("account_ref"))
    workspace_ref = _bounded_ref(projection.get("workspace_ref"))
    expires_at = projection.get("session_expires_at")
    if None in (session_id, binding_ref, device_id, account_ref, workspace_ref):
        return None
    if not isinstance(expires_at, str) or not expires_at or len(expires_at) > _MAX_TIMESTAMP_LENGTH:
        return None
    return {
        "authenticated": True,
        "session_id": session_id,
        "binding_ref": binding_ref,
        "device_id": device_id,
        "account_ref": account_ref,
        "workspace_ref": workspace_ref,
        "credential_generation": projection["credential_generation"],
        "session_expires_at": expires_at,
    }


class DesktopDeviceSessionAuthority(Protocol):
    """The typed authority the Desktop conversation routes authenticate through."""

    configured: bool

    async def authenticate_device_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential_b64: str,
    ) -> dict[str, Any] | None:  # pragma: no cover - protocol declaration
        ...


class UnconfiguredDesktopDeviceSessionAuthority:
    """Fail-closed default: no canonical broker boundary, so nothing authenticates.

    The Desktop conversation surface reports the same bounded refusal for every
    caller until the trusted Worker runtime is actually deployed. It never
    falls back to a browser session cookie or a self-asserted identity.
    """

    configured = False

    async def authenticate_device_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential_b64: str,
    ) -> dict[str, Any] | None:
        del session_id, binding_ref, credential_b64
        return None


class BrokerAuthorityDeviceSessionAuthPort:
    """Typed port adapter over the canonical broker session-authentication RPC.

    The Worker service binding exposes the broker Worker entrypoint's methods
    directly (the same RPC surface the #3094 local-access truth source
    consumes). This adapter is the only translation between that surface and
    the typed port protocol: it forwards the caller-held session material,
    awaits the RPC result, and accepts only the exact closed canonical
    projection — every refusal, malformed answer, or extra material becomes
    ``None`` so the route fails closed.
    """

    configured = True

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def authenticate_device_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential_b64: str,
    ) -> dict[str, Any] | None:
        result = self._binding.authenticate_device_session(
            {
                "session_id": session_id,
                "binding_ref": binding_ref,
                "credential_b64": credential_b64,
            }
        )
        if result is not None and hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            return None
        return validate_authenticated_device_session(result.get("device_session"))


def build_desktop_device_session_authority_with_diagnostic(
    env: Any,
) -> tuple[Any | None, str | None]:
    """Compose the concrete authority from the trusted binding, or fail closed.

    Returns ``(authority, None)`` when the trusted boundary is present and
    compatible, otherwise ``(None, diagnostic)`` where the diagnostic is one
    fixed constant above. The caller keeps whatever fail-closed default the
    app factory already installed.
    """

    boundary = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if boundary is None:
        return None, DESKTOP_AUTH_DIAG_BINDING_ABSENT
    try:
        port = getattr(boundary, "authenticate_device_session")
    except Exception:
        # Even reading the port must not explode the composition root: a
        # hostile or broken boundary is just an incompatible one.
        return None, DESKTOP_AUTH_DIAG_PORT_INCOMPATIBLE
    if not callable(port):
        # A binding without the canonical session-authentication RPC cannot
        # serve this surface; no second authority may be invented for it.
        return None, DESKTOP_AUTH_DIAG_PORT_INCOMPATIBLE
    try:
        authority = BrokerAuthorityDeviceSessionAuthPort(boundary)
    except Exception:
        return None, DESKTOP_AUTH_DIAG_CONSTRUCTION_FAILED
    return authority, None


def build_desktop_device_session_authority(env: Any) -> Any | None:
    """Same fail-closed composition, without the diagnostic."""

    authority, _ = build_desktop_device_session_authority_with_diagnostic(env)
    return authority


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

TRUSTED_BOUNDARY = "worker:LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
CONSUMED_BROKER_API = "authenticate_device_session RPC (canonical broker Worker)"
COMPOSITION_INPUT_SOURCE = "trusted_worker_bindings_only"
FAIL_CLOSED_WHEN_BOUNDARY_ABSENT = True
MUTATION = False
PRODUCTION_MUTATION = False
SECOND_IDENTITY_AUTHORITY = 0
SECOND_SESSION_AUTHORITY = 0
SECOND_CREDENTIAL_VERIFIER = 0
SECOND_CONVERSATION_AUTHORITY = 0
BROWSER_PADIEM_SESSION_COOKIE_COPY = 0
DESKTOP_USER_SESSION_AUTHORITY = 0
CALLER_WORKSPACE_AUTHORITY = 0
SERVER_DERIVED_ACCOUNT_REF = True
SERVER_DERIVED_WORKSPACE_REF = True
RAW_DEVICE_CREDENTIAL_RETURNED = False
RAW_DEVICE_CREDENTIAL_LOGGED = False
HISTORY_STORE_WORKSPACE_DIMENSION = "owner_wide"
