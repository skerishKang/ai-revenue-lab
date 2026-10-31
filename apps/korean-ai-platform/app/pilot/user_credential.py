"""Request-scoped caller credentials on the B14 chat lanes (#5824 PR-3a).

Chat's BYOK registration (#5887) verifies a customer's own provider key, and
the bridge (#5905) hands that key to the Engine lane for one request. It arrives
inside the B14 request body as ``user_credential_ref``: a JSON document with
``provider``, ``endpoint``, ``model`` and ``key``. The credential therefore
travels with the request and nowhere else. It is not stored, not cached, not
written to the ledger, and not reachable from a log line or an error message.

How this lane differs from the platform catalog lane
----------------------------------------------------
- the pool credential plane is never consulted: no provider secret is resolved,
  no roster is built, and no owner-tier candidate is substituted;
- one provider, one key, one physical attempt. A provider failure is returned
  with the same ``upstream_*`` code the platform adapter maps it to, and B14
  does not try anything else afterwards;
- the caller names a provider and presents the endpoint it registered. B14 dials
  its OWN fixed address for that provider, so a body can never steer a request
  to a host the platform has not approved (the same invariant the platform
  adapter holds for server-owned credentials);
- only the wires B14 already speaks are served here: an OpenAI-compatible
  ``chat/completions`` endpoint and Google's. An ``anthropic-messages`` style key
  is refused with a stable code, and the caller keeps its existing direct path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.pilot.errors import (
    InvalidUserCredential,
    PilotNotConfigured,
    PlaceholderKeyRejected,
    UnsupportedUserCredentialEndpoint,
    UnsupportedUserCredentialWire,
)
from app.pilot.platform_secrets import (
    CredentialSource,
    get_platform_provider,
    _looks_like_placeholder,
    _validate_origin,
)

#: The field names a request may carry the credential under. ``user_credential_ref``
#: is what the Engine bridge writes; ``user_credential`` is the body-level name
#: of the same object shape. Both are read-only request fields.
USER_CREDENTIAL_FIELDS = ("user_credential_ref", "user_credential")

_OPENAI_CHAT_WIRE = "openai-chat"
_GOOGLE_WIRE = "google"

# B14's own grammar for these two values is what the ledger column can store
# (call_ledger._ID_RE / _clean_text), so a credential that cannot be recorded is
# refused here rather than at the write boundary.
_UPSTREAM_MODEL_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class _FixedTarget:
    """One provider B14 can serve with a caller's own key.

    ``accepted_endpoints`` is the official base-origin set #5887 registers for
    this provider. It is an assertion of intent that the caller must match, not
    a URL B14 dials: the address actually used is the fixed one below, or the
    origin of the platform spec named by ``platform_provider_id``.
    """

    provider_id: str
    wire: str
    accepted_endpoints: tuple[str, ...]
    origin: str = ""
    platform_provider_id: str = ""


_TARGETS = (
    _FixedTarget(
        provider_id="openai", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://api.openai.com/v1",),
        origin="https://api.openai.com/v1",
    ),
    _FixedTarget(
        provider_id="deepseek", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://api.deepseek.com",),
        origin="https://api.deepseek.com",
    ),
    _FixedTarget(
        provider_id="groq", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://api.groq.com/openai/v1",),
        origin="https://api.groq.com/openai/v1",
    ),
    _FixedTarget(
        provider_id="xai", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://api.x.ai/v1",),
        origin="https://api.x.ai/v1",
    ),
    _FixedTarget(
        provider_id="perplexity", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://api.perplexity.ai",),
        origin="https://api.perplexity.ai",
    ),
    _FixedTarget(
        provider_id="huggingface", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://router.huggingface.co/v1",),
        origin="https://router.huggingface.co/v1",
    ),
    _FixedTarget(
        provider_id="openrouter", wire=_OPENAI_CHAT_WIRE,
        accepted_endpoints=("https://openrouter.ai/api/v1",),
        origin="https://openrouter.ai/api/v1",
    ),
    # Google's customer keys are issued for the generateContent surface, while
    # B14's registered Google spec points at the same host's OpenAI-compatible
    # endpoint. Either spelling of the official origin is accepted; the dial
    # target stays the registered one, so B14 owns the address.
    _FixedTarget(
        provider_id="google", wire=_GOOGLE_WIRE,
        accepted_endpoints=(
            "https://generativelanguage.googleapis.com/v1beta",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        platform_provider_id="google",
    ),
)

# The Chat side labels a Gemini credential ``gemini``; B14's own provider id is
# ``google``. Both names reach the same fixed target and the same ledger label.
_ALIASES = {"gemini": "google"}


def _build_targets() -> dict[str, _FixedTarget]:
    by_provider = {target.provider_id: target for target in _TARGETS}
    for alias, canonical in _ALIASES.items():
        by_provider[alias] = by_provider[canonical]
    return by_provider


_BY_PROVIDER = _build_targets()


@dataclass(frozen=True)
class UserCredential:
    """One caller-owned key, resolved to the fixed route B14 will use for it."""

    provider_id: str
    upstream_model: str
    origin: str
    allowed_hosts: tuple[str, ...]
    wire: str
    #: Memory-only. Never rendered, never logged, never stored.
    key: str = field(repr=False)

    def __repr__(self) -> str:
        return (
            f"UserCredential(provider={self.provider_id!r}, "
            f"model={self.upstream_model!r}, key=<redacted>)"
        )

    def __str__(self) -> str:
        return repr(self)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.origin.rstrip('/')}/chat/completions"


def _decode_document(value: Any) -> dict[str, Any]:
    """Accept the bridge's JSON string and the equivalent body object."""
    if isinstance(value, Mapping):
        document: Any = dict(value)
    elif isinstance(value, str):
        try:
            document = json.loads(value)
        except (ValueError, UnicodeDecodeError):
            # A parse fault is reported as a shape problem only. The cause is
            # dropped on purpose: an attached exception could quote the body
            # that carried the key.
            raise InvalidUserCredential() from None
    else:
        raise InvalidUserCredential()
    if not isinstance(document, dict):
        raise InvalidUserCredential()
    return document


def _text(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str):
        raise InvalidUserCredential()
    return value.strip()


def _resolve(target: _FixedTarget) -> tuple[str, tuple[str, ...]]:
    if not target.platform_provider_id:
        origin = target.origin
        hosts = (origin.split("//", 1)[1].split("/", 1)[0].lower(),)
        _validate_origin(origin, hosts)
        return origin, hosts
    spec = get_platform_provider(target.platform_provider_id)
    if spec is None or not spec.enabled:
        raise PilotNotConfigured("Requested model credential is not configured.")
    if spec.credential_source is not CredentialSource.PLATFORM_SECRET:
        # The fixed address is reusable; the server-owned binding is not.
        raise PilotNotConfigured("Requested model credential is not configured.")
    return spec.base_origin, spec.allowed_hosts


def parse_credential(value: Any) -> UserCredential:
    """Validate one credential document and resolve it to a fixed B14 route."""
    document = _decode_document(value)
    provider = _text(document, "provider").lower()
    endpoint = _text(document, "endpoint")
    model = _text(document, "model")
    key = _text(document, "key")

    if not provider or not endpoint or not model or not key:
        raise InvalidUserCredential()
    if not _PROVIDER_ID_RE.match(provider):
        raise UnsupportedUserCredentialWire()
    if not _UPSTREAM_MODEL_RE.match(model):
        raise InvalidUserCredential()
    if _looks_like_placeholder(key):
        raise PlaceholderKeyRejected()

    target = _BY_PROVIDER.get(provider)
    if target is None:
        # Includes the anthropic-messages family: its key is valid, this route
        # is not, and the caller keeps its own direct path.
        raise UnsupportedUserCredentialWire()
    canonical = {_e.rstrip("/") for _e in target.accepted_endpoints}
    if endpoint.rstrip("/") not in canonical:
        raise UnsupportedUserCredentialEndpoint()

    origin, allowed_hosts = _resolve(target)
    return UserCredential(
        provider_id=target.provider_id, upstream_model=model, origin=origin,
        allowed_hosts=allowed_hosts, wire=target.wire, key=key,
    )


def has_credential(raw: Any) -> bool:
    """Presence only, without decoding: the value is never read for a log."""
    return isinstance(raw, Mapping) and any(name in raw for name in USER_CREDENTIAL_FIELDS)


def credential_from_body(raw: Any) -> UserCredential | None:
    """Return the request's credential, or None when the request carries none."""
    if not isinstance(raw, Mapping):
        return None
    for name in USER_CREDENTIAL_FIELDS:
        if name in raw:
            return parse_credential(raw[name])
    return None
