"""Wire-level enforcement for first-party Padiem AI Engine callers.

The contract is server-side only: callers identify themselves with a bounded
caller id plus a high-entropy credential kept in deployment secret storage.
The request body remains the source of the requested ``app_id``; identity
verification binds that app to the authenticated caller before execution.

Deployment configuration supports the following authorities:

- ``PADIEM_ENGINE_CALLER_REGISTRY_V1``: a versioned, secret-backed,
  bounded multi-caller registry payload. When configured it is the only
  caller authority; a malformed or blank payload fails closed and never
  falls back to the legacy configuration.
- ``PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY``: an optional additive
  single-caller overlay. It is strictly additive to the V1 base but remains an
  independently bounded authority at authentication time, so the base registry
  keeps its original capacity. It can neither shadow, replace, nor widen any
  base caller. If the overlay is configured while the V1 base is absent the
  composition fails closed.
- the legacy one-caller trio (``PADIEM_ENGINE_CALLER_ID``,
  ``PADIEM_ENGINE_CALLER_SECRET``, ``PADIEM_ENGINE_ALLOWED_APPS``):
  authoritative only while the V1 registry variable is genuinely absent,
  preserving existing deployment behavior unchanged.

A bounded retirement policy (``RETIRED_CALLER_IDS``) additionally denies a
small, explicit set of caller ids at the wire boundary. It exists because an
opaque Base V1 payload may still carry a live entry for a caller that has been
retired; the payload stays authoritative and is never rewritten, so the id is
denied at authentication time instead. The deny runs after the overlay branch
and before Base-registry fallback, fails closed with the existing public-safe
``service_authentication_failed`` error, and never introduces an alias,
fallback, shadowing, or id remapping.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
CALLER_REGISTRY_V1_OVERLAY_ENV = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"

# Bounded retirement policy for the legacy shared Claw caller (#2525).
#
# The opaque Base V1 authority may still contain an entry for this id and that
# payload must neither be rewritten nor reconstructed, so the caller is retired
# at the authentication boundary instead of in the authority. A request that
# presents a retired caller id fails closed with the same public-safe
# ``service_authentication_failed`` error as any other unauthenticated caller.
#
# The set is deliberately closed to exactly the one known legacy id; widening it
# requires separate authorization and evidence. No alias, fallback, shadowing,
# or id remapping is introduced here, and the guard reads no credential material.
RETIRED_CALLER_IDS = frozenset({"b54-kagent"})

# Bounded serialized registry input. A registry legally packed to the
# generic contract limits (64 callers, 32 app ids and a 512-byte credential
# each) stays well below this cap, so the bound only rejects absurd
# deployment payloads before any parsing or credential digesting happens.
MAX_CALLER_REGISTRY_V1_BYTES = 524288

_CALLER_REGISTRY_V1_TOP_LEVEL_KEYS = frozenset({"version", "callers"})
_CALLER_REGISTRY_V1_ENTRY_KEYS = frozenset(
    {"caller_id", "credential", "allowed_app_ids"}
)

_CALLER_REGISTRY_V1_OVERLAY_TOP_LEVEL_KEYS = frozenset({"version", "caller"})


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


def parse_caller_registry_v1_overlay(raw: str) -> TrustedEngineCaller:
    """Parse the optional additive single-caller overlay payload.

    The overlay uses the same canonical caller entry contract as the V1 base
    (``caller_id``, ``credential``, ``allowed_app_ids``) and converts
    its credential with the existing ``caller_secret_digest`` contract. Every
    failure raises ``ServiceIdentityError`` (fail closed), and safe error
    messages never contain payload fragments or credential plaintext.
    """

    if not isinstance(raw, str):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay must be a JSON string",
        )
    if len(raw.encode("utf-8")) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay exceeds the bounded input size",
        )

    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay is not valid JSON",
        ) from None

    if not isinstance(payload, dict) or set(payload.keys()) != _CALLER_REGISTRY_V1_OVERLAY_TOP_LEVEL_KEYS:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay must contain exactly version and caller",
        )

    version = payload["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != CALLER_REGISTRY_V1_VERSION
    ):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay version is unsupported",
        )

    entry = payload["caller"]
    if not isinstance(entry, dict) or set(entry.keys()) != _CALLER_REGISTRY_V1_ENTRY_KEYS:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay caller must contain exactly caller_id, credential, and allowed_app_ids",
        )
    allowed_app_ids = entry["allowed_app_ids"]
    if not isinstance(allowed_app_ids, list):
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay allowed_app_ids must be a JSON array",
        )
    return TrustedEngineCaller(
        caller_id=entry["caller_id"],
        allowed_app_ids=tuple(allowed_app_ids),
        credential_sha256=caller_secret_digest(entry["credential"]),
    )


def _build_registry_authority_from_env(
    env: Any,
) -> tuple[EngineCallerRegistry | None, TrustedEngineCaller | None]:
    """Build the base registry plus an independently bounded overlay caller.

    The base V1 registry keeps its original 1..MAX_ENGINE_CALLERS capacity.
    The overlay is never materialized into that registry, so a fully valid
    64-caller opaque base remains valid when the one-caller overlay is present.
    Duplicate caller IDs are rejected before either authority is usable.

    The authority is deliberately rebuilt on every call. See the module-level
    ``#2542`` note below for why no sound memoization of this value is possible
    under the no-plaintext / no-content-surrogate constraint; correctness of the
    authentication authority is preferred over any per-request speedup.
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
        base_registry = parse_caller_registry_v1(registry_raw)

        overlay_raw = getattr(env, CALLER_REGISTRY_V1_OVERLAY_ENV, None)
        if overlay_raw is None:
            return base_registry, None
        if not isinstance(overlay_raw, str):
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry overlay must be a JSON string",
            )
        if not overlay_raw.strip():
            raise ServiceIdentityError(
                "invalid_caller_registry",
                "Padiem AI Engine caller registry overlay is configured but blank",
            )

        overlay_caller = parse_caller_registry_v1_overlay(overlay_raw)
        if any(
            caller.caller_id == overlay_caller.caller_id
            for caller in base_registry.callers
        ):
            raise ServiceIdentityError(
                "duplicate_service_caller",
                "caller registry overlay must not duplicate a base caller ID",
            )
        return base_registry, overlay_caller

    if getattr(env, CALLER_REGISTRY_V1_OVERLAY_ENV, None) is not None:
        raise ServiceIdentityError(
            "invalid_caller_registry",
            "Padiem AI Engine caller registry overlay requires the V1 base registry",
        )

    caller_id = _text(getattr(env, CALLER_ID_ENV, None)).strip()
    secret = _text(getattr(env, CALLER_SECRET_ENV, None))
    allowed_raw = _text(getattr(env, CALLER_ALLOWED_APPS_ENV, None)).strip()

    if not caller_id and not secret and not allowed_raw:
        return None, None
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
    return EngineCallerRegistry(callers=(caller,)), None


def build_registry_from_env(env: Any) -> EngineCallerRegistry | None:
    """Build the canonical base/legacy registry from deployment configuration.

    When V1 plus the additive overlay are configured, this function deliberately
    returns only the independently valid base V1 registry. The overlay is parsed
    and duplicate-checked by the shared authority builder, then authenticated
    separately by :func:`authenticate_request`. This preserves the established
    64-caller capacity of the opaque base without redefining that contract.
    """

    registry, _overlay_caller = _build_registry_authority_from_env(env)
    return registry


# Why the caller-registry authority is NOT memoized (#2542).
#
# #2542 asked us to remove the per-request rebuild of the base/overlay
# authority. An earlier revision of this file added an isolate-lifetime memo
# keyed by ``weakref(env)`` plus the object ``id`` of the raw V1 base/overlay
# binding values. A security review rejected that design as ABA-unsafe at an
# authentication boundary, and this note records why no sound replacement key
# exists under the agreed constraints, so the correct disposition is to rebuild
# on every call (CENTRAL options B/C: correctness over hit rate; a zero
# production hit rate is acceptable until a safe runtime identity primitive is
# proven).
#
# Constraints (non-negotiable): the memo may not retain the raw registry or
# overlay plaintext, and may not retain any content-derived surrogate (hash,
# digest, fingerprint, length, prefix, suffix, or excerpt). Invalidation must
# therefore rest on a runtime identity primitive that provably cannot ABA within
# the cache lifetime.
#
# Impossibility argument for the binding values:
#   * The authoritative inputs are ``str`` deployment bindings. A CPython ``str``
#     cannot be weak-referenced, so the only identity handle available for it is
#     ``id(str)``.
#   * ``id`` is only unique among *live* objects. If a binding is reassigned, the
#     previous ``str`` becomes collectable; once collected, CPython is free to
#     allocate a *different* ``str`` at the same address. A subsequent read then
#     reports an ``id`` that matches the memo for content that was never built.
#   * Concrete stale-hit sequence: build at address X; reassign the binding to a
#     value at address Y (freeing X's object on a later read that already missed
#     and rebuilt); reassign again to a new value that CPython places back at the
#     freed address X. If no authentication happens between the two reassignments,
#     the next read returns a live ``str`` at X whose ``id`` equals the retained
#     ``base_id``, producing a false hit that serves the wrong authority. Nothing
#     about immutable content prevents this: the reused address can carry a
#     different payload, and the memo cannot observe the difference without either
#     holding the ``str`` (plaintext) or comparing it (surrogate) — both forbidden.
#   * Keying on the env *container* alone (``weakref(env)``) is itself ABA-safe,
#     but it cannot detect a binding reassignment *within* one still-live env, so
#     it would stale-hit on any mutable/synthetic env and fails the required
#     regression that reassignment must never produce a stale authority.
#
# The env weak reference and the parsed authority can be tracked safely; the
# binding ``str`` values cannot be tracked safely without violating the
# no-plaintext / no-surrogate rules. Because the authority depends on exactly
# those untrackable values, no sound memo exists, and a wrong-but-plausible key
# is strictly worse than none at an authentication boundary.
#
# If a future runtime exposes a provably immutable or versioned authority token
# (CENTRAL option A) — a value whose identity cannot be recycled across a
# differing payload — the memo can be reintroduced keyed on that token. Until
# then this module rebuilds the authority per call, which is behavior- and
# fail-closed-identical to the pre-#2542 builder.


def authenticate_request(
    *,
    env: Any,
    headers: Mapping[str, Any] | None,
    requested_app_id: str,
) -> None:
    """Fail closed unless the request authenticates as a registered caller."""

    registry, overlay_caller = _build_registry_authority_from_env(env)
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

    if overlay_caller is not None and caller_id == overlay_caller.caller_id:
        authenticate_engine_caller(
            registry=EngineCallerRegistry(callers=(overlay_caller,)),
            caller_id=caller_id,
            credential=credential,
            requested_app_id=requested_app_id,
        )
        return

    # Retired legacy callers are denied here, immediately before the Base
    # registry fallback: the caller/credential presence check and the canonical
    # Overlay branch above still run first, the malformed-authority and
    # duplicate-caller guards already ran inside
    # ``_build_registry_authority_from_env``, and unrelated Base callers keep the
    # unchanged fallback path below. The error is the existing public-safe
    # authentication failure, so the wire response stays enumeration-safe and
    # does not distinguish a retired id from an unknown caller or a bad
    # credential. The opaque Base payload itself is never touched.
    if caller_id in RETIRED_CALLER_IDS:
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
