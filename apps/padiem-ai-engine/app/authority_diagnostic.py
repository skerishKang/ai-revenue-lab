"""Runtime-internal content-blind caller-authority diagnostic (#2439 rework).

Why the Engine runtime hosts this diagnostic
--------------------------------------------
The #2439 investigation narrowed the live 401 ``service_authentication_failed``
to two surviving candidates, both of which fail inside
``identity_enforcement._build_registry_authority_from_env`` before any caller
is selected: a malformed V1 base registry, or a base that already contains the
overlay caller id (``duplicate_service_caller``). Both map to the same 401 for
every non-health caller. Deciding between them requires the content of the two
registry payloads, and the Cloudflare control plane never returns
``secret_text`` plaintext: the worker-secret GET API exposes NAME/TYPE bindings
only. The single place those payloads legitimately exist as values is inside
the Engine runtime, as the very environment bindings the request path reads.
This module therefore answers the classification question from inside that
boundary and exposes exactly one closed six-fact projection.

Registry independence is the whole point
----------------------------------------
The diagnostic must keep answering even when the caller registry itself is the
broken component, so it is deliberately NOT authenticated through the caller
registry. It is gated by a dedicated high-entropy operator token
(``PADIEM_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN``) that is independent of the
registry, and it never touches storage, service composition, or
``authenticate_request``. While the token binding is absent or unusable the
route fails closed with 503, so the diagnostic surface does not exist until an
operator provisions it, and it is never advertised by the health route list.

Content-blind closed output
---------------------------
Requests never carry registry or credential values, and responses are closed
before serialization: parse verdicts reuse the production parsers verbatim
(``OK``/``INVALID``); the positive-detection fields use a bounded structural
scan (fixed key paths, string equality against the known constant) so they
stay honest even when a strict parse fails. No credential, credential hash,
credential length, allowed app id, unrelated caller id, raw JSON, or derived
fingerprint can be emitted: an out-of-vocabulary value fails closed inside the
result object on every output surface, the same closed-projection discipline
as :mod:`app.auth_boundary_diagnostic` (#2445/#2447/#2449).
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from typing import Any

from app.identity_enforcement import (
    CALLER_REGISTRY_V1_ENV,
    CALLER_REGISTRY_V1_OVERLAY_ENV,
    parse_caller_registry_v1,
    parse_caller_registry_v1_overlay,
)
from app.service_identity import MAX_ENGINE_CALLERS

AUTHORITY_DIAGNOSTIC_PATH = "/internal/v1/diagnostics/caller-authority"
DIAGNOSTIC_TOKEN_ENV = "PADIEM_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN"
DIAGNOSTIC_TOKEN_HEADER = "x-padiem-engine-authority-diagnostic-token"

# Operator-token bounds: the server-side token must carry real entropy, and
# every comparison is bounded work regardless of what a client presents.
MIN_DIAGNOSTIC_TOKEN_BYTES = 32
MAX_DIAGNOSTIC_TOKEN_BYTES = 512

# The single overlay caller this diagnostic exists to classify. This identifier
# is already public repository constant material (P01 contract, #2375/#2402).
EXPECTED_OVERLAY_CALLER_ID = "b54-kagent"

CLOSED_FIELDS = (
    "BASE_PARSE",
    "OVERLAY_PARSE",
    "BASE_CONTAINS_B54_KAGENT",
    "DUPLICATE_CALLER_ID",
    "BASE_CALLER_COUNT",
    "OVERLAY_CALLER_ID_MATCH",
)

OUTPUT_KEYS = (
    "ok",
    *CLOSED_FIELDS,
    "SECRET_VALUE_OUTPUT",
    "RAW_REGISTRY_JSON_OUTPUT",
    "PRODUCTION_MUTATION",
)

_PARSE_VOCAB = frozenset({"OK", "INVALID"})
_FLAG_VOCAB = frozenset({"YES", "NO"})
_COUNT_VOCAB = frozenset(str(count) for count in range(MAX_ENGINE_CALLERS + 1))

_VOCAB_BY_KEY: dict[str, frozenset[str]] = {
    "BASE_PARSE": _PARSE_VOCAB,
    "OVERLAY_PARSE": _PARSE_VOCAB,
    "BASE_CONTAINS_B54_KAGENT": _FLAG_VOCAB,
    "DUPLICATE_CALLER_ID": _FLAG_VOCAB,
    "BASE_CALLER_COUNT": _COUNT_VOCAB,
    "OVERLAY_CALLER_ID_MATCH": _FLAG_VOCAB,
}


class AuthorityDiagnosticError(RuntimeError):
    """Invariant violation inside the diagnostic projection.

    Error messages reference only key names and static text — never a stored
    or supplied value — so an exception can not carry registry content out of
    the module.
    """


def _parse_verdict(raw: Any, parser: Any) -> str:
    """Mirror the production fail-closed parse: OK only if it fully validates."""
    if not isinstance(raw, str) or not raw.strip():
        return "INVALID"
    try:
        parser(raw)
    except Exception:
        # ServiceIdentityError carries static messages, but no exception text
        # is ever allowed near the output channel, so it is dropped entirely.
        return "INVALID"
    return "OK"


def _structural_ids(raw: Any, container_key: str, many: bool) -> list[str]:
    """Caller ids under one fixed key path, without any validation.

    Returns an empty list on any structural deviation. Bounded work: at most
    ``2 * MAX_ENGINE_CALLERS`` entries are ever touched. Ids are used for
    equality checks in memory only and are never emitted.
    """
    if not isinstance(raw, str):
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        return []
    if not isinstance(payload, dict):
        return []
    container = payload.get(container_key)
    entries = container if many else (container if isinstance(container, dict) else None)
    if entries is None:
        return []
    if many and not isinstance(entries, list):
        return []
    candidates = entries[: 2 * MAX_ENGINE_CALLERS] if many else [entries]
    ids: list[str] = []
    for entry in candidates:
        if isinstance(entry, dict):
            caller_id = entry.get("caller_id")
            if isinstance(caller_id, str):
                ids.append(caller_id)
    return ids


def classify_authority_payloads(base_raw: Any, overlay_raw: Any) -> dict[str, str]:
    """Produce the closed six-field classification entirely in memory."""
    base_ids = _structural_ids(base_raw, container_key="callers", many=True)
    overlay_ids = _structural_ids(overlay_raw, container_key="caller", many=False)
    overlay_id = overlay_ids[0] if overlay_ids else ""
    return {
        "BASE_PARSE": _parse_verdict(base_raw, parse_caller_registry_v1),
        "OVERLAY_PARSE": _parse_verdict(overlay_raw, parse_caller_registry_v1_overlay),
        "BASE_CONTAINS_B54_KAGENT": (
            "YES" if EXPECTED_OVERLAY_CALLER_ID in base_ids else "NO"
        ),
        "DUPLICATE_CALLER_ID": (
            "YES" if overlay_id and overlay_id in base_ids else "NO"
        ),
        "BASE_CALLER_COUNT": str(min(len(base_ids), MAX_ENGINE_CALLERS)),
        "OVERLAY_CALLER_ID_MATCH": (
            "YES" if overlay_id == EXPECTED_OVERLAY_CALLER_ID else "NO"
        ),
    }


class AuthorityDiagnosticResult(Mapping):
    """A diagnostic projection that is closed and immutable after construction.

    Read-only :class:`~collections.abc.Mapping` over exactly the six
    :data:`CLOSED_FIELDS`. The backing state is an immutable ``tuple``,
    attribute mutation/deletion is blocked, and every value is re-validated
    against its key's closed vocabulary on each output surface, so no
    arbitrary string can be stored in — or read out of — a result.
    """

    __slots__ = ("_values",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping) or set(data) != set(CLOSED_FIELDS):
            raise AuthorityDiagnosticError(
                "diagnostic result vocabulary is not exact"
            )
        validated: list[str] = []
        for key in CLOSED_FIELDS:
            value = data[key]
            if not isinstance(value, str) or value not in _VOCAB_BY_KEY[key]:
                raise AuthorityDiagnosticError(
                    f"{key} is outside the closed diagnostic vocabulary"
                )
            validated.append(value)
        object.__setattr__(self, "_values", tuple(validated))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("AuthorityDiagnosticResult is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("AuthorityDiagnosticResult is immutable")

    @staticmethod
    def _index(key: str) -> int:
        try:
            return CLOSED_FIELDS.index(key)
        except ValueError:
            raise KeyError(key) from None

    def _validated_at(self, index: int) -> str:
        key = CLOSED_FIELDS[index]
        value = self._values[index]
        if not isinstance(value, str) or value not in _VOCAB_BY_KEY[key]:
            raise AuthorityDiagnosticError(
                f"{key} is outside the closed diagnostic vocabulary"
            )
        return value

    def __getitem__(self, key: str) -> str:
        return self._validated_at(self._index(key))

    def __iter__(self):
        return iter(CLOSED_FIELDS)

    def __len__(self) -> int:
        return len(CLOSED_FIELDS)

    def __repr__(self) -> str:
        rendered = ", ".join(
            f"{key}={self._validated_at(index)}"
            for index, key in enumerate(CLOSED_FIELDS)
        )
        return f"AuthorityDiagnosticResult({rendered})"

    def as_dict(self) -> dict[str, str]:
        return {
            key: self._validated_at(index)
            for index, key in enumerate(CLOSED_FIELDS)
        }


def authority_diagnostic_from_env(env: Any) -> AuthorityDiagnosticResult:
    """Classify the runtime's own registry bindings into the closed result."""
    base_raw = getattr(env, CALLER_REGISTRY_V1_ENV, None)
    overlay_raw = getattr(env, CALLER_REGISTRY_V1_OVERLAY_ENV, None)
    return AuthorityDiagnosticResult(
        classify_authority_payloads(base_raw, overlay_raw)
    )


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
            "metadata": None,
        },
    }


def _header_value(headers: Any, name: str) -> Any:
    if headers is None:
        return None
    try:
        return headers.get(name)
    except Exception:
        return None


def _token_bytes(value: Any) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return None


def diagnostic_response(
    env: Any, method: Any, headers: Any
) -> tuple[int, dict[str, Any]]:
    """Authorize and answer one content-blind diagnostic request.

    Returns a ``(status, body)`` pair with a closed body in every branch. The
    operator token is compared in constant time; a wrong, missing, or
    oversized presentation is indistinguishable from the caller path's 401
    envelope and never reveals whether the registry itself is healthy.
    """
    if str(method or "").upper() != "GET":
        return 405, _error("method_not_allowed", "Method not allowed.")
    server_token = _token_bytes(getattr(env, DIAGNOSTIC_TOKEN_ENV, None))
    if (
        server_token is None
        or not MIN_DIAGNOSTIC_TOKEN_BYTES <= len(server_token) <= MAX_DIAGNOSTIC_TOKEN_BYTES
    ):
        return 503, _error(
            "authority_diagnostic_unavailable",
            "Authority diagnostic is not configured.",
        )
    presented_token = _token_bytes(_header_value(headers, DIAGNOSTIC_TOKEN_HEADER))
    if presented_token is None or len(presented_token) > MAX_DIAGNOSTIC_TOKEN_BYTES:
        return 401, _error(
            "authority_diagnostic_unauthorized",
            "Diagnostic authorization is invalid.",
        )
    if not hmac.compare_digest(presented_token, server_token):
        return 401, _error(
            "authority_diagnostic_unauthorized",
            "Diagnostic authorization is invalid.",
        )
    result = authority_diagnostic_from_env(env)
    body: dict[str, Any] = {"ok": True}
    body.update(result.as_dict())
    body["SECRET_VALUE_OUTPUT"] = "0"
    body["RAW_REGISTRY_JSON_OUTPUT"] = "0"
    body["PRODUCTION_MUTATION"] = "0"
    return 200, body
