"""Bounded Chat<->Engine auth-boundary equality diagnostic (#2445).

The latest Phase-A runtime reached the Engine and failed with
``engine_authentication_failed``. #2444 closed that question as
``AUTH_BOUNDARY_UNPROVEN`` because the served Chat credential
(``P01_ENGINE_CREDENTIAL``) and the Engine caller registry
(``PADIEM_ENGINE_CALLER_REGISTRY_V1``) are both ``secret_text`` bindings whose
values are unreadable from any Cloudflare control plane. The only place those
secrets exist in comparable form is inside the trusted Engine process, which
already resolves the live caller authority and already performs a constant-time
SHA-256 comparison in :func:`app.service_identity.authenticate_engine_caller`.

This module adds the smallest bounded primitive that reuses that exact trusted
comparison to answer the drift question, and returns a closed vocabulary of
non-secret booleans/enums. It deliberately:

- runs only inside a trusted server/operator boundary (it is not wired to any
  fetch route, so no browser/user can reach it and no persistent public
  diagnostic route exists);
- never emits a credential value, a raw digest/hash, a prefix/suffix, a length,
  or any other reusable credential material;
- fails closed on structurally malformed diagnostic input;
- resolves the caller authority through the same builder the live request path
  uses, so the diagnostic can never disagree with real authentication, and it
  changes no existing auth/quota/runtime semantics.

The credential-equivalence booleans are defined against the Engine's stored
authority for the requested caller:

- ``ENGINE_MATCH`` is TRUE when the operator-canonical credential authenticates
  against that stored authority;
- ``CHAT_MATCH`` is TRUE when the credential the served Chat currently presents
  authenticates against that same stored authority.
"""

from __future__ import annotations

import hmac
import re
from typing import Any

# Reuse the single live authority builder (base V1 + additive overlay + legacy
# trio dispatch) so this diagnostic can never diverge from real authentication.
from app.identity_enforcement import _build_registry_authority_from_env
from app.service_identity import (
    EngineCallerRegistry,
    ServiceIdentityError,
    TrustedEngineCaller,
    caller_secret_digest,
)

ENGINE_WORKER = "padiem-ai-engine"
CHAT_WORKER = "padiem-chat"

# Non-secret canonical identities for the B54/P01 Chat<->Engine boundary. These
# are configuration identifiers (already plain_text bindings), never secrets.
P01_APP_ID = "b54-padiem-claw"
P01_CHAT_CALLER_ID = "b54-kagent"

ABSENT = "ABSENT"
_TRUE = "TRUE"
_FALSE = "FALSE"

# The diagnostic returns exactly these keys and nothing else.
OUTPUT_KEYS = (
    "CHAT_SERVICE_TARGET",
    "CHAT_SERVICE_ENVIRONMENT",
    "CHAT_CALLER_ID",
    "CALLER_PRESENT",
    "APP_ALLOWED",
    "ENGINE_MATCH",
    "CHAT_MATCH",
)

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AuthBoundaryEvidenceError(RuntimeError):
    """Structurally malformed diagnostic input; fails closed without leaking."""


def _bool(value: bool) -> str:
    return _TRUE if value else _FALSE


def _bounded_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise AuthBoundaryEvidenceError(f"{name} must be a bounded safe identifier")
    return value


def _credential_matches(caller: TrustedEngineCaller, credential: Any) -> bool:
    """Constant-time equality of a supplied credential against the stored digest.

    The comparison mirrors :func:`authenticate_engine_caller` exactly: hash the
    supplied credential with the shared ``caller_secret_digest`` contract, then
    ``hmac.compare_digest`` against the stored digest. Nothing about the
    credential is returned. A credential that cannot be hashed (wrong type or
    out of the bounded length range) is reported identically to a mismatch so
    the boolean never becomes a length or content oracle.
    """

    if not isinstance(credential, (str, bytes)):
        return False
    try:
        supplied_digest = caller_secret_digest(credential)
    except ServiceIdentityError:
        return False
    return hmac.compare_digest(caller.credential_sha256, supplied_digest)


def _resolve_effective_caller(
    registry: EngineCallerRegistry | None,
    overlay_caller: TrustedEngineCaller | None,
    caller_id: str,
) -> TrustedEngineCaller | None:
    """Return the caller the live path would authenticate, or None.

    Mirrors :func:`app.identity_enforcement.authenticate_request`: an overlay
    caller wins for its own id, otherwise the base/legacy registry is consulted.
    """

    if overlay_caller is not None and overlay_caller.caller_id == caller_id:
        return overlay_caller
    if registry is not None:
        for caller in registry.callers:
            if caller.caller_id == caller_id:
                return caller
    return None


def run_auth_boundary_diagnostic(
    *,
    registry: EngineCallerRegistry | None,
    overlay_caller: TrustedEngineCaller | None,
    chat_service_target: Any,
    chat_service_environment: Any,
    chat_caller_id: Any,
    app_id: Any,
    canonical_credential: Any,
    chat_supplied_credential: Any,
) -> dict[str, str]:
    """Classify the Chat<->Engine auth boundary into the closed #2445 vocabulary.

    All secret material enters only as ``canonical_credential`` /
    ``chat_supplied_credential`` and is consumed by the constant-time compare;
    neither value, its digest, nor its length is ever returned. Malformed
    structural input raises :class:`AuthBoundaryEvidenceError` (fail closed).
    """

    target = _bounded_identifier("chat_service_target", chat_service_target)
    caller_id = _bounded_identifier("chat_caller_id", chat_caller_id)
    app = _bounded_identifier("app_id", app_id)

    if chat_service_environment is None or (
        isinstance(chat_service_environment, str) and not chat_service_environment.strip()
    ):
        environment = ABSENT
    else:
        environment = _bounded_identifier("chat_service_environment", chat_service_environment)

    if registry is not None and not isinstance(registry, EngineCallerRegistry):
        raise AuthBoundaryEvidenceError("registry must be an EngineCallerRegistry or None")
    if overlay_caller is not None and not isinstance(overlay_caller, TrustedEngineCaller):
        raise AuthBoundaryEvidenceError("overlay_caller must be a TrustedEngineCaller or None")
    if registry is None and overlay_caller is None:
        raise AuthBoundaryEvidenceError("no caller registry authority is available")

    effective = _resolve_effective_caller(registry, overlay_caller, caller_id)
    caller_present = effective is not None
    app_allowed = bool(caller_present and app in effective.allowed_app_ids)
    engine_match = bool(caller_present and _credential_matches(effective, canonical_credential))
    chat_match = bool(caller_present and _credential_matches(effective, chat_supplied_credential))

    return {
        "CHAT_SERVICE_TARGET": target,
        "CHAT_SERVICE_ENVIRONMENT": environment,
        "CHAT_CALLER_ID": caller_id,
        "CALLER_PRESENT": _bool(caller_present),
        "APP_ALLOWED": _bool(app_allowed),
        "ENGINE_MATCH": _bool(engine_match),
        "CHAT_MATCH": _bool(chat_match),
    }


def run_auth_boundary_diagnostic_from_env(
    env: Any,
    *,
    chat_service_target: Any,
    chat_service_environment: Any,
    chat_caller_id: Any,
    canonical_credential: Any,
    chat_supplied_credential: Any,
    app_id: Any = P01_APP_ID,
) -> dict[str, str]:
    """Resolve the live caller authority from ``env`` and run the diagnostic.

    A registry that fails to build is reported only through its safe error code
    (never a message fragment or payload), so a misconfigured authority fails
    closed without disclosure.
    """

    try:
        registry, overlay_caller = _build_registry_authority_from_env(env)
    except ServiceIdentityError as exc:
        raise AuthBoundaryEvidenceError(
            f"caller registry authority unavailable: {exc.code}"
        ) from None
    return run_auth_boundary_diagnostic(
        registry=registry,
        overlay_caller=overlay_caller,
        chat_service_target=chat_service_target,
        chat_service_environment=chat_service_environment,
        chat_caller_id=chat_caller_id,
        app_id=app_id,
        canonical_credential=canonical_credential,
        chat_supplied_credential=chat_supplied_credential,
    )


def render(result: dict[str, str]) -> str:
    """Render bounded ``KEY=VALUE`` lines plus non-disclosure safety markers."""

    if set(result) != set(OUTPUT_KEYS):
        raise AuthBoundaryEvidenceError("diagnostic result vocabulary is not exact")
    lines = [f"{key}={result[key]}" for key in OUTPUT_KEYS]
    lines.append("DIAGNOSTIC_ONLY=YES")
    lines.append("PUBLIC_DIAGNOSTIC_ROUTE=NONE")
    lines.append("SECRET_VALUE_OUTPUT=0")
    lines.append("SECRET_HASH_OUTPUT=0")
    lines.append("PRODUCTION_MUTATION=0")
    return "\n".join(lines)
