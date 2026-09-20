"""Provider-neutral B14 candidate live-smoke contract (#2798).

Generalizes the Agnes-only bounded live-smoke pattern into a single shared
contract so that any future candidate can later receive a **separate**
single-use authority and perform exactly one bounded live acceptance run.

This module is deliberately inert: importing it, or invoking its default
entry point, never performs a live provider call. A live run requires an
explicitly supplied transport plus an explicitly supplied candidate id that
must appear in :data:`CANDIDATE_REGISTRY`.

Hard guarantees enforced here:

* explicit provider/model allowlist (no implicit or discovered candidates)
* exact model identity (provider_id / model_id / upstream_model)
* expected credential binding **name** only, never a value
* ``MAX_PROVIDER_CALLS = 1``
* ``RETRY = 0`` (no network retry loop of any kind)
* ``FALLBACK = 0`` (a non-matching response is a failure, not a fallback)
* actual response provider/model evidence is required to match
* latency evidence is recorded in bounded form
* HTTP / result classification with safe, bounded error codes
* secret values are never printed
* raw prompt/response private payload is never printed

Authority boundaries (see #2676):

* AUTO route selection is NOT used; the request pins an exact ``model``.
* B.AI Qwen3.8 is excluded from the allowlist.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# The scripts directory is not a package, so make the canonical served-version
# resolver importable whether this module runs directly or is loaded through
# importlib in a test. This gate deliberately reuses the canonical resolver
# rather than growing a fifth independent implementation (see #2451 / #2737).
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cloudflare_served_version import (  # noqa: E402
    ServedVersionReason,
    ServedVersionResolutionError,
    resolve_served_version_id,
)

# --------------------------------------------------------------------------
# Shared transport / response bounds (identical posture to the Agnes gate).
# --------------------------------------------------------------------------

B14_BASE_URL = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
HEALTH_PATH = "/api/pilot/health"
MODELS_PATH = "/api/pilot/models"
CHAT_PATH = "/api/pilot/v1/chat/completions"

REQUEST_TIMEOUT_SECONDS = 75
MAX_RESPONSE_BYTES = 1_048_576

# Bounded counters. These are contract constants, not tunables.
MAX_PROVIDER_CALLS = 1
RETRY = 0
FALLBACK = 0

# The AUTO lane must never back a candidate live acceptance.
AUTO_MODEL_ID = "b14/auto"
AUTO_ROUTE_USED = False

HttpTransport = Callable[[str, str, "dict[str, Any] | None"], tuple[int, bytes]]


@dataclass(frozen=True)
class CandidateSpec:
    """One explicitly allowlisted candidate.

    ``credential_binding`` is the **name** of the expected platform secret
    binding. Its value is never read, printed, or transmitted by this module.
    """

    candidate_id: str
    tier: str
    provider_id: str
    provider_name: str
    model_id: str
    upstream_model: str
    credential_binding: str
    expected_binding: str


# --------------------------------------------------------------------------
# Explicit candidate allowlist (#2798 authority correction).
#
# PLUS  : Agnes, SenseNova, Poolside, Motif, Mercury, Atria
# PRO   : GPT-5.6 Luna
# EXCLUDED: B.AI Qwen3.8 (deliberately absent — see _EXCLUDED_* below)
# --------------------------------------------------------------------------

_CANDIDATES: tuple[CandidateSpec, ...] = (
    CandidateSpec(
        candidate_id="agnes",
        tier="plus",
        provider_id="agnes-ai",
        provider_name="Agnes AI",
        model_id="agnes-ai/agnes-3.0-flash",
        upstream_model="agnes-3.0-flash",
        credential_binding="PADIEM_AGNES_API_KEY",
        expected_binding="PADIEM_AGNES_API_KEY",
    ),
    CandidateSpec(
        candidate_id="sensenova",
        tier="plus",
        provider_id="sensenova",
        provider_name="SenseNova",
        model_id="sensenova/sensenova-6.8-flash-lite",
        upstream_model="sensenova-6.8-flash-lite",
        credential_binding="PADIEM_SENSENOVA_API_KEY",
        expected_binding="PADIEM_SENSENOVA_API_KEY",
    ),
    CandidateSpec(
        candidate_id="poolside",
        tier="plus",
        provider_id="poolside",
        provider_name="Poolside",
        model_id="poolside/laguna-s-2.1",
        upstream_model="poolside/laguna-s-2.1",
        credential_binding="PADIEM_POOLSIDE_API_KEY",
        expected_binding="PADIEM_POOLSIDE_API_KEY",
    ),
    CandidateSpec(
        candidate_id="motif",
        tier="plus",
        provider_id="infron",
        provider_name="Infron",
        model_id="infron/motif/motif-3",
        upstream_model="motif/motif-3",
        credential_binding="PADIEM_INFRON_API_KEY",
        expected_binding="PADIEM_INFRON_API_KEY",
    ),
    CandidateSpec(
        candidate_id="mercury",
        tier="plus",
        provider_id="inception",
        provider_name="Inception",
        model_id="inception/mercury-2.5",
        upstream_model="mercury-2.5",
        credential_binding="PADIEM_INCEPTION_MERCURY_API_KEY",
        expected_binding="PADIEM_INCEPTION_MERCURY_API_KEY",
    ),
    CandidateSpec(
        candidate_id="atria",
        tier="plus",
        provider_id="atria",
        provider_name="Atria",
        model_id="atria/Atria-Dawn-Preview",
        upstream_model="Atria-Dawn-Preview",
        credential_binding="PADIEM_ATRIA_API_KEY",
        expected_binding="PADIEM_ATRIA_API_KEY",
    ),
    CandidateSpec(
        candidate_id="luna",
        tier="pro",
        provider_id="experiential",
        provider_name="Experiential Labs",
        model_id="experiential/gpt-5.6-luna",
        upstream_model="gpt-5.6-luna",
        credential_binding="PADIEM_EXLAB_API_KEY",
        expected_binding="PADIEM_EXLAB_API_KEY",
    ),
)

CANDIDATE_REGISTRY: dict[str, CandidateSpec] = {
    spec.candidate_id: spec for spec in _CANDIDATES
}

PLUS_CANDIDATE_IDS: tuple[str, ...] = tuple(
    spec.candidate_id for spec in _CANDIDATES if spec.tier == "plus"
)
PRO_CANDIDATE_IDS: tuple[str, ...] = tuple(
    spec.candidate_id for spec in _CANDIDATES if spec.tier == "pro"
)

# Explicitly excluded candidates. Absence from CANDIDATE_REGISTRY is the
# enforcement; this tuple documents the exclusion so a test can pin it.
EXCLUDED_CANDIDATE_IDS: tuple[str, ...] = ("b-ai-qwen3.8", "bai", "qwen")
_EXCLUDED_MODEL_IDS: frozenset[str] = frozenset({"b-ai/qwen3.8-flash"})


def candidate_ids() -> tuple[str, ...]:
    """Return every allowlisted candidate id, in registry order."""

    return tuple(CANDIDATE_REGISTRY)


def resolve_candidate(candidate_id: str) -> CandidateSpec:
    """Resolve an allowlisted candidate or fail closed.

    An unknown id, an excluded id, or the AUTO lane marker raises
    ``ValueError``. There is no implicit default candidate.
    """

    if candidate_id in EXCLUDED_CANDIDATE_IDS:
        raise ValueError("candidate_excluded")
    if candidate_id == AUTO_MODEL_ID:
        raise ValueError("auto_route_not_permitted")
    spec = CANDIDATE_REGISTRY.get(candidate_id)
    if spec is None:
        raise ValueError("candidate_not_allowlisted")
    if spec.model_id == AUTO_MODEL_ID or spec.model_id in _EXCLUDED_MODEL_IDS:
        raise ValueError("candidate_model_not_permitted")
    return spec


# --------------------------------------------------------------------------
# Bounded parsing / safe classification helpers.
# --------------------------------------------------------------------------


def _bounded_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("response_not_object")
    return value


def _request(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, bytes]:
    """Default transport. NOT reachable from a default invocation.

    It is only ever wired in when a caller explicitly asks for the real
    transport, which the workflow gate does only under an authorized
    single-use dispatch.
    """

    import urllib.error
    import urllib.request

    payload = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "padiem-b14-candidate-live-smoke/1.0",
    }
    if body is not None:
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{B14_BASE_URL}{path}",
        data=payload,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)


def canonical_chat_body(spec: CandidateSpec) -> dict[str, Any]:
    """Pin one exact manual route. The AUTO lane is never requested."""

    return {
        "model": spec.model_id,
        "messages": [
            {
                "role": "user",
                "content": "Production route smoke. Reply with the single word OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }


# --------------------------------------------------------------------------
# Closed safe error-code vocabulary (BLOCKER 2).
#
# Only these local, gate-owned codes may ever be projected to stdout. An
# upstream ``error.code`` is untrusted diagnostic input and is never echoed
# verbatim; anything outside this set becomes "unknown". "unparseable" is a
# local classification, not a provider value.
# --------------------------------------------------------------------------

SAFE_ENGINE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_request_error",
        "authentication_error",
        "permission_error",
        "not_found_error",
        "rate_limit_error",
        "quota_exceeded",
        "overloaded_error",
        "api_error",
        "timeout_error",
        "upstream_error",
        "no_safe_route",
        "provider_error",
        "unavailable",
        "unparseable",
        "unknown",
    }
)


def _safe_error_code(payload: dict[str, Any]) -> str:
    """Project an untrusted provider error onto a closed local vocabulary.

    ``error.code`` and ``error.message`` arrive from a provider/B14 response
    body and are therefore untrusted diagnostic input: an upstream can put a
    credential, a private prompt fragment, or any other secret in either field.
    Echoing the raw value would turn this gate into a disclosure channel, so
    only a value drawn from :data:`SAFE_ENGINE_ERROR_CODES` is projected; every
    other value -- including a well-formed but unrecognized code -- collapses to
    ``"unknown"``.

    ``unparseable`` is added locally when the body is not a JSON object at all.
    """

    error = payload.get("error")
    if not isinstance(error, dict):
        return "unknown"
    code = error.get("code")
    if not isinstance(code, str):
        return "unknown"
    return code if code in SAFE_ENGINE_ERROR_CODES else "unknown"


def _classify_latency(latency_ms: int) -> str:
    """Coarse, bounded latency bucket (no raw timing leak beyond evidence)."""

    if latency_ms < 0:
        return "unknown"
    if latency_ms < 2_000:
        return "fast"
    if latency_ms < 10_000:
        return "moderate"
    return "slow"


def _emit(candidate_id: str, key: str, value: str) -> None:
    """Emit one bounded evidence line for the given candidate."""

    print(f"{candidate_id.upper()}_{key}={value}")


def _emit_result(candidate_id: str, result: str) -> None:
    print(f"{candidate_id.upper()}_PRODUCTION_SMOKE={result}")


def _locks(provider_posts: int, retries: int) -> None:
    print(f"B14_CHAT_POST_COUNT={provider_posts}")
    print(f"NETWORK_RETRY_COUNT={retries}")
    print("RAW_RESPONSE_CONTENT_OUTPUT=0")
    print("PRIVATE_PAYLOAD_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print(f"MAX_PROVIDER_CALLS={MAX_PROVIDER_CALLS}")
    print(f"RETRY={RETRY}")
    print(f"FALLBACK={FALLBACK}")
    print(f"AUTO_ROUTE_USED={int(AUTO_ROUTE_USED)}")
    print("PRODUCTION_MUTATION=0")


# --------------------------------------------------------------------------
# The bounded run.
# --------------------------------------------------------------------------


def run(
    candidate_id: str,
    transport: HttpTransport | None = None,
) -> int:
    """Run exactly one bounded live acceptance for one allowlisted candidate.

    ``transport`` is required. When it is ``None`` the call fails closed
    **before any request is constructed**, which is what makes a default
    invocation unable to reach Production.
    """

    try:
        spec = resolve_candidate(candidate_id)
    except ValueError as exc:
        print(f"B14_CANDIDATE_LIVE_SMOKE=FAIL_{exc}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    cid = spec.candidate_id

    if transport is None:
        _emit_result(cid, "FAIL_TRANSPORT_NOT_AUTHORIZED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    provider_posts = 0
    network_retries = 0

    health_status, health_raw = transport("GET", HEALTH_PATH, None)
    if health_status != 200:
        _emit_result(cid, f"FAIL_HEALTH_HTTP_{health_status}")
        _locks(provider_posts, network_retries)
        return 1
    try:
        health = _bounded_json(health_raw)
    except ValueError as exc:
        _emit_result(cid, f"FAIL_HEALTH_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    business14 = health.get("business14")
    if not isinstance(business14, dict) or business14.get("provider_mode") != "live":
        _emit_result(cid, "FAIL_PROVIDER_MODE")
        _locks(provider_posts, network_retries)
        return 1

    providers = business14.get("providers")
    if not isinstance(providers, list):
        _emit_result(cid, "FAIL_PROVIDER_LIST")
        _locks(provider_posts, network_retries)
        return 1
    provider_entry = next(
        (
            item
            for item in providers
            if isinstance(item, dict) and item.get("id") == spec.provider_id
        ),
        None,
    )
    if not isinstance(provider_entry, dict) or provider_entry.get("registered") is not True:
        _emit_result(cid, "FAIL_PROVIDER_NOT_REGISTERED")
        _locks(provider_posts, network_retries)
        return 1
    if provider_entry.get("has_key") is not True:
        _emit_result(cid, "FAIL_CREDENTIAL_NOT_READY")
        _locks(provider_posts, network_retries)
        return 1
    _emit(cid, "PROVIDER_REGISTERED", "YES")
    _emit(cid, "CREDENTIAL_READY", "YES")
    _emit(cid, "EXPECTED_BINDING", spec.expected_binding)

    models_status, models_raw = transport("GET", MODELS_PATH, None)
    if models_status != 200:
        _emit_result(cid, f"FAIL_MODELS_HTTP_{models_status}")
        _locks(provider_posts, network_retries)
        return 1
    try:
        models = _bounded_json(models_raw)
    except ValueError as exc:
        _emit_result(cid, f"FAIL_MODELS_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    routes = models.get("registered_routes")
    if not isinstance(routes, list):
        _emit_result(cid, "FAIL_ROUTE_LIST")
        _locks(provider_posts, network_retries)
        return 1
    route = next(
        (
            item
            for item in routes
            if isinstance(item, dict) and item.get("id") == spec.model_id
        ),
        None,
    )
    if not isinstance(route, dict):
        _emit_result(cid, "FAIL_ROUTE_NOT_REGISTERED")
        _locks(provider_posts, network_retries)
        return 1
    if (
        route.get("provider_id") != spec.provider_id
        or route.get("upstream_model") != spec.upstream_model
    ):
        _emit_result(cid, "FAIL_ROUTE_IDENTITY")
        _locks(provider_posts, network_retries)
        return 1
    _emit(cid, "ROUTE_REGISTERED", "YES")
    _emit(cid, "EXACT_MODEL_IDENTITY", "PASS")

    provider_posts += 1
    started = time.monotonic()
    chat_status, chat_raw = transport("POST", CHAT_PATH, canonical_chat_body(spec))
    latency_ms = max(0, int((time.monotonic() - started) * 1000))

    if chat_status != 200:
        try:
            payload = _bounded_json(chat_raw)
            error_code = _safe_error_code(payload)
        except ValueError:
            error_code = "unparseable"
        _emit_result(cid, f"FAIL_CHAT_HTTP_{chat_status}")
        print(f"ENGINE_ERROR_CODE={error_code}")
        _locks(provider_posts, network_retries)
        return 1

    try:
        chat = _bounded_json(chat_raw)
    except ValueError as exc:
        _emit_result(cid, f"FAIL_CHAT_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    meta = chat.get("business14")
    if not isinstance(meta, dict):
        _emit_result(cid, "FAIL_METADATA_MISSING")
        _locks(provider_posts, network_retries)
        return 1

    checks = {
        "mode": meta.get("mode") == "live",
        "provider_mode": meta.get("provider_mode") == "live",
        "provider": meta.get("provider") == spec.provider_name,
        "selected_provider": meta.get("selected_provider") == spec.provider_name,
        "model_route": meta.get("model_route") == spec.model_id,
        "selected_model": meta.get("selected_model") == spec.model_id,
        "upstream_model": meta.get("upstream_model") == spec.upstream_model,
        "selected_upstream_model": meta.get("selected_upstream_model") == spec.upstream_model,
        "actual_response_model": meta.get("actual_response_model") == spec.upstream_model,
        "route_mode": meta.get("route_mode") == "manual",
        "fallback_used": meta.get("fallback_used") is False,
        "attempt_count": meta.get("attempt_count") == 1,
        "route_evidence_status": meta.get("route_evidence_status") == "live_verified",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        _emit_result(cid, "FAIL_ROUTE_METADATA")
        print("FAILED_METADATA_CHECKS=" + ",".join(sorted(failed)))
        _locks(provider_posts, network_retries)
        return 1

    choices = chat.get("choices")
    if (
        not isinstance(choices, list)
        or not choices
        or not isinstance(choices[0], dict)
        or not isinstance(choices[0].get("message"), dict)
        or not isinstance(choices[0]["message"].get("content"), str)
        or not choices[0]["message"]["content"].strip()
    ):
        _emit_result(cid, "FAIL_EMPTY_ANSWER")
        _locks(provider_posts, network_retries)
        return 1

    _emit_result(cid, "PASS")
    _emit(cid, "TIER", spec.tier)
    _emit(cid, "MODEL_ROUTE", spec.model_id)
    _emit(cid, "UPSTREAM_MODEL", spec.upstream_model)
    _emit(cid, "ACTUAL_RESPONSE_MODEL_EVIDENCE", "PASS")
    _emit(cid, "PROVIDER_MATCH", "YES")
    _emit(cid, "FALLBACK_USED", "NO")
    _emit(cid, "ATTEMPT_COUNT", "1")
    _emit(cid, "LATENCY_MS", str(latency_ms))
    _emit(cid, "LATENCY_CLASS", _classify_latency(latency_ms))
    _locks(provider_posts, network_retries)
    return 0


# --------------------------------------------------------------------------
# Served-version guard (BLOCKER 1).
#
# The canonical rule is NOT reimplemented here. The whole Cloudflare
# deployments envelope is handed to the shared canonical resolver
# (``cloudflare_served_version.resolve_served_version_id``), which enforces:
# a successful envelope, ``result.deployments[0]`` as the active deployment,
# exactly one version on it, ``traffic = 100``, and a safe ``version_id``.
#
# Scanning every deployment in history -- the shape this gate used before --
# lets a superseded deployment that once served 100% satisfy the guard. The
# canonical resolver refuses that by construction, so a historical match can
# never pass here.
# --------------------------------------------------------------------------


def resolve_active_served_version(payload: object) -> str:
    """Return the active served version id using the canonical resolver.

    Re-raises the resolver's own ``ServedVersionResolutionError`` (carrying its
    closed ``reason`` code) so the caller keeps a single failure vocabulary.
    """

    return resolve_served_version_id(payload)


def assert_served_version(payload: object, expected_version: str) -> str:
    """Return the served version id only when it equals ``expected_version``.

    Fails closed on an unresolvable envelope, on an unsafe id, and on any
    mismatch -- including the case where ``expected_version`` appears only in a
    non-active (historical) deployment.
    """

    served = resolve_served_version_id(payload)
    if served != expected_version:
        raise ServedVersionResolutionError(ServedVersionReason.VERSION_ID)
    return served


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Requires an explicit candidate id and an explicit authorization marker.
    Without both, this exits non-zero and never constructs a transport, so a
    bare default invocation cannot reach Production.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("B14_CANDIDATE_LIVE_SMOKE=FAIL_CANDIDATE_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1
    candidate_id = args[0]
    if "--authorized-live-run" not in args[1:]:
        print("B14_CANDIDATE_LIVE_SMOKE=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1
    return run(candidate_id, transport=_request)


if __name__ == "__main__":
    sys.exit(main())
