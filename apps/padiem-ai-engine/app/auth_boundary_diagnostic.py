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

Closed, immutable output projection (independent-validation rework #2447/#2449)
-------------------------------------------------------------------------------
The projection is *closed and structurally immutable*, not merely filtered at
render time:

    INPUT MAY BE ARBITRARY -> internal classification -> OUTPUT MUST BE CLOSED

Arbitrary caller-supplied strings are mapped to a small fixed vocabulary before
they can reach any output path. The returned :class:`AuthBoundaryDiagnosticResult`
stores its values in an immutable tuple, blocks attribute mutation/deletion, and
re-validates every value against that key's closed vocabulary on *every* output
surface (``__getitem__``, ``as_dict``, ``repr``, ``render``). So neither ordinary
attribute access nor a deliberately forced state change can move a raw
credential, digest, digest fragment, or numeric length into the emitted output;
an invariant violation fails closed with static text that never echoes a value.

Canonical-caller fail-closed (#2449)
------------------------------------
This diagnostic is scoped to the canonical B54/P01 Claw caller ``b54-kagent``.
The caller id is classified first; authority is resolved only when the
classification is exactly ``b54-kagent``. An ``ABSENT`` or ``NONCANONICAL``
caller never resolves an arbitrary registry caller: ``CALLER_PRESENT``,
``APP_ALLOWED``, ``ENGINE_MATCH`` and ``CHAT_MATCH`` are all FALSE, while the
``NONCANONICAL`` classification is still reported so caller drift stays
distinguishable from absence.

The credential-equivalence booleans are defined against the Engine's stored
authority for the canonical caller:

- ``ENGINE_MATCH`` is TRUE when the operator-canonical credential authenticates
  against that stored authority;
- ``CHAT_MATCH`` is TRUE when the credential the served Chat currently presents
  authenticates against that same stored authority.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
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
NONCANONICAL = "NONCANONICAL"
_TRUE = "TRUE"
_FALSE = "FALSE"

# Closed, repository-grounded environment allowlist. These are the only Chat
# "service environment" literals that already appear in this repository's
# contracts (the kagent Cloudflare connector ``CloudflareEnvironment`` enum
# ``preview``/``production`` in
# ``apps/korean-ai-code-agent/src/kagent/cloudflare_connector.py`` and the
# Pages/deploy ``production``/``preview`` equality checks). No broader environment
# vocabulary is invented here: any value outside this set is classified
# ``NONCANONICAL`` and never echoed.
ENVIRONMENT_ALLOWLIST = frozenset({"production", "preview"})

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

# Closed output vocabulary per key. A value that is not in its key's set can
# never be stored in, read out of, or rendered from a result — including one
# that happens to match a generic identifier shape.
_TARGET_VOCAB = frozenset({ENGINE_WORKER, ABSENT, NONCANONICAL})
_CALLER_VOCAB = frozenset({P01_CHAT_CALLER_ID, ABSENT, NONCANONICAL})
_ENVIRONMENT_VOCAB = ENVIRONMENT_ALLOWLIST | frozenset({ABSENT, NONCANONICAL})
_BOOL_VOCAB = frozenset({_TRUE, _FALSE})

_VOCAB_BY_KEY: dict[str, frozenset[str]] = {
    "CHAT_SERVICE_TARGET": _TARGET_VOCAB,
    "CHAT_SERVICE_ENVIRONMENT": _ENVIRONMENT_VOCAB,
    "CHAT_CALLER_ID": _CALLER_VOCAB,
    "CALLER_PRESENT": _BOOL_VOCAB,
    "APP_ALLOWED": _BOOL_VOCAB,
    "ENGINE_MATCH": _BOOL_VOCAB,
    "CHAT_MATCH": _BOOL_VOCAB,
}


class AuthBoundaryEvidenceError(RuntimeError):
    """Structurally malformed diagnostic input; fails closed without leaking.

    Error messages reference only key names and static text — never a supplied
    or stored value — so an exception can not carry secret-shaped input out of
    the module.
    """


def _bool(value: bool) -> str:
    return _TRUE if value else _FALSE


def _closed_string(value: Any, allowed_exact: frozenset[str]) -> str:
    """Map arbitrary input to a closed category, never echoing the raw value.

    ``ABSENT`` for missing/blank, the canonical/allowlisted literal only when the
    input is exactly one of those known-safe constants, and ``NONCANONICAL`` for
    everything else (including well-formed but unexpected strings such as a
    credential, digest, or numeric length).
    """

    if not isinstance(value, str) or not value.strip():
        return ABSENT
    if value in allowed_exact:
        return value
    return NONCANONICAL


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


class AuthBoundaryDiagnosticResult(Mapping):
    """A diagnostic projection that is closed and immutable after construction.

    Read-only :class:`~collections.abc.Mapping` over exactly the seven #2445
    keys. The backing state is an immutable ``tuple`` (no reachable mutable
    container), attribute mutation/deletion is blocked, and every value is
    re-validated against its key's closed vocabulary on each output surface. A
    raw credential, digest, digest fragment, numeric length, or any other
    arbitrary string therefore can not be stored in — or read out of — a result
    through normal accessible object state, and a forced invariant violation
    fails closed instead of leaking.
    """

    __slots__ = ("_values",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping) or set(data) != set(OUTPUT_KEYS):
            raise AuthBoundaryEvidenceError("diagnostic result vocabulary is not exact")
        validated: list[str] = []
        for key in OUTPUT_KEYS:
            value = data[key]
            if not isinstance(value, str) or value not in _VOCAB_BY_KEY[key]:
                # Message names the key only, never the offending value.
                raise AuthBoundaryEvidenceError(
                    f"{key} is outside the closed diagnostic vocabulary"
                )
            validated.append(value)
        # Bypass the (now-blocking) __setattr__ only for the one-time init.
        object.__setattr__(self, "_values", tuple(validated))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("AuthBoundaryDiagnosticResult is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("AuthBoundaryDiagnosticResult is immutable")

    @staticmethod
    def _index(key: str) -> int:
        try:
            return OUTPUT_KEYS.index(key)
        except ValueError:
            raise KeyError(key) from None

    def _validated_at(self, index: int) -> str:
        key = OUTPUT_KEYS[index]
        value = self._values[index]
        if not isinstance(value, str) or value not in _VOCAB_BY_KEY[key]:
            raise AuthBoundaryEvidenceError(
                f"{key} is outside the closed diagnostic vocabulary"
            )
        return value

    def __getitem__(self, key: str) -> str:
        return self._validated_at(self._index(key))

    def __iter__(self):
        return iter(OUTPUT_KEYS)

    def __len__(self) -> int:
        return len(OUTPUT_KEYS)

    def __repr__(self) -> str:
        # Built only from re-validated closed values; a corrupted value fails
        # closed rather than becoming a secret-output oracle.
        rendered = ", ".join(
            f"{key}={self._validated_at(index)}" for index, key in enumerate(OUTPUT_KEYS)
        )
        return f"AuthBoundaryDiagnosticResult({rendered})"

    def as_dict(self) -> dict[str, str]:
        return {
            key: self._validated_at(index) for index, key in enumerate(OUTPUT_KEYS)
        }


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
) -> AuthBoundaryDiagnosticResult:
    """Classify the Chat<->Engine auth boundary into the closed #2445 vocabulary.

    All secret material enters only as ``canonical_credential`` /
    ``chat_supplied_credential`` and is consumed by the constant-time compare;
    neither value, its digest, nor its length is ever returned. The three string
    fields are classified to a closed vocabulary (never echoed), and the caller
    id is classified before any authority lookup so a non-canonical caller can
    never resolve a registry caller.
    """

    if registry is not None and not isinstance(registry, EngineCallerRegistry):
        raise AuthBoundaryEvidenceError("registry must be an EngineCallerRegistry or None")
    if overlay_caller is not None and not isinstance(overlay_caller, TrustedEngineCaller):
        raise AuthBoundaryEvidenceError("overlay_caller must be a TrustedEngineCaller or None")
    if registry is None and overlay_caller is None:
        raise AuthBoundaryEvidenceError("no caller registry authority is available")

    caller_class = _closed_string(chat_caller_id, frozenset({P01_CHAT_CALLER_ID}))

    # Fail-closed caller drift: only the canonical b54-kagent caller may resolve
    # an authority. ABSENT/NONCANONICAL never look up an arbitrary registry
    # caller; their booleans are all FALSE while the classification is reported.
    caller_present = False
    app_allowed = False
    engine_match = False
    chat_match = False
    if caller_class == P01_CHAT_CALLER_ID:
        effective = _resolve_effective_caller(registry, overlay_caller, caller_class)
        caller_present = effective is not None
        if caller_present:
            app_allowed = bool(isinstance(app_id, str) and app_id in effective.allowed_app_ids)
            engine_match = bool(_credential_matches(effective, canonical_credential))
            chat_match = bool(_credential_matches(effective, chat_supplied_credential))

    return AuthBoundaryDiagnosticResult(
        {
            "CHAT_SERVICE_TARGET": _closed_string(chat_service_target, frozenset({ENGINE_WORKER})),
            "CHAT_SERVICE_ENVIRONMENT": _closed_string(
                chat_service_environment, ENVIRONMENT_ALLOWLIST
            ),
            "CHAT_CALLER_ID": caller_class,
            "CALLER_PRESENT": _bool(caller_present),
            "APP_ALLOWED": _bool(app_allowed),
            "ENGINE_MATCH": _bool(engine_match),
            "CHAT_MATCH": _bool(chat_match),
        }
    )


def run_auth_boundary_diagnostic_from_env(
    env: Any,
    *,
    chat_service_target: Any,
    chat_service_environment: Any,
    chat_caller_id: Any,
    canonical_credential: Any,
    chat_supplied_credential: Any,
    app_id: Any = P01_APP_ID,
) -> AuthBoundaryDiagnosticResult:
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


def render(result: AuthBoundaryDiagnosticResult) -> str:
    """Render bounded ``KEY=VALUE`` lines plus non-disclosure safety markers.

    Only a closed :class:`AuthBoundaryDiagnosticResult` may be rendered; a raw
    dictionary is refused outright. Each line is read through the result's
    validating ``__getitem__``, so an invalid stored state fails closed instead
    of being emitted.
    """

    if not isinstance(result, AuthBoundaryDiagnosticResult):
        raise AuthBoundaryEvidenceError(
            "render requires a bounded AuthBoundaryDiagnosticResult"
        )
    lines = [f"{key}={result[key]}" for key in OUTPUT_KEYS]
    lines.append("DIAGNOSTIC_ONLY=YES")
    lines.append("PUBLIC_DIAGNOSTIC_ROUTE=NONE")
    lines.append("SECRET_VALUE_OUTPUT=0")
    lines.append("SECRET_HASH_OUTPUT=0")
    lines.append("SECRET_LENGTH_OUTPUT=0")
    lines.append("PRODUCTION_MUTATION=0")
    return "\n".join(lines)
