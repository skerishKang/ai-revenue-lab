"""WO-10 A11 Gmail tool_runtime production smoke (#2010, ACT-2 hardened).

Runs against the PRODUCTION Engine (default https://engine.padiem.net) with the
product-owned smoke caller credential (PADIEM_ENGINE_SMOKE_CALLER_ID/_SECRET or
CALLER_ID/CALLER_SECRET, allowed_app_ids=["b54-padiem-claw"]). Standard library
only. The script takes no CLI arguments at all, so no provider token, refresh
credential, client secret or any other credential value can ever be supplied to
it, and no secret value is ever printed.

What it proves
--------------
Every probe carries an OVERSIZED ``arguments`` object (larger than the bounded
Core argument ceiling, ``MAX_TOOL_ARGUMENT_BYTES`` = 65536). Inside the Engine
the argument-size bound is enforced AFTER these steps:

  1. route admission (worker ``allowed_paths``);
  2. ``_resolve_binding(app_id)``      -> 503 tool_runtime_unavailable;
  3. ``binding.resolve_authority()``   -> 403 tool_agent_not_bound;
  4. ``binding.resolve_tool(tool_id)`` -> 403 tool_not_registered;
  5. argument-size bound               -> 400 tool_arguments_too_large;
  6. Core ``ToolRuntime.execute``      -> (never reached: provider call).

So a 400 ``tool_arguments_too_large`` is a POSITIVE proof that the route is
wired, the tool runtime is bound, the canonical Gmail Agent is authorized, and
the canonical Gmail Tool is registered — while the provider is never called.
REAL_PROVIDER_CALLS=0, ROWS_WRITTEN=0 and D1_MUTATION=0 hold by construction:
this script never seeds a grant, never mutates D1, never flips the capability
manifest and never dispatches a workflow.

Steps
-----
  S0  GET  /internal/v1/health -> 200; records (never asserts) the
      ``tool_runtime`` capability and whether TOOL_EXECUTE_PATH is advertised.
  S1  POST /internal/v1/tools/execute canonical Gmail tool + canonical Agent
      -> classified honestly (see below).
  S2  POST /internal/v1/tools/execute with an UNREGISTERED tool id -> the
      trusted registry must reject it (403 tool_not_registered) whenever S1
      proved the runtime is live; otherwise it must stay consistent with S1.
  S3  POST /internal/v1/tools/execute with app_id="b62" -> 4xx cross-app
      isolation fires in the worker auth layer before any tool logic.

Honest classification
---------------------
  ROUTE_UNAVAILABLE   404 not_found            route absent from the deployed
                                               build — FAIL: the Tool routes are
                                               wired in Engine source since
                                               ACT-2, so a 404 can only mean a
                                               stale deploy (never DEFERRED)
  RUNTIME_UNAVAILABLE 503 tool_runtime_unavailable / connector_grants_unavailable
  TOOL_NOT_ALLOWED    403 tool_not_registered / tool_agent_not_bound /
                           tool_authorization_mismatch / tool_not_allowed /
                           tool_agent_mismatch / tool_owner_mismatch /
                           tool_auth_scope_missing /
                           tool_external_authorization_required
  TOOL_CONTRACT_LIVE  400 tool_arguments_too_large / invalid_tool_arguments
  INVALID_REQUEST     4xx invalid_request / invalid_tool_request / ...
  UPSTREAM_UNEXPECTED other 5xx
  UNEXPECTED          anything else (including 200: a smoke probe must never
                      reach the provider)

Verdicts
--------
  A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS                       (exit 0)
  A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED REASON=...        (exit 0)
  A11_GMAIL_TOOL_RUNTIME_SMOKE=SKIPPED_MISSING_SECRET     (exit 1)
  A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL                       (exit 1)

DEFERRED is NOT a fake PASS: since the ACT-2 route activation it is the honest,
machine-readable record that the route is admitted but production has not
reached the credential/authorization state yet (runtime unbound, or tool/agent
not authorized). It never blocks the deploy gate. The former route-not-wired
DEFERRED tolerance was removed in ACT-2: with the routes wired in source, a
404 is contradictory production behaviour and FAILs. FAIL
is reserved for contradictory or unexpected production behaviour and does fail
the gate.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "https://engine.padiem.net").rstrip("/")
CALLER_ID = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_ID") or os.environ.get("CALLER_ID", "")
CALLER_SECRET = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_SECRET") or os.environ.get("CALLER_SECRET", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

HEALTH_PATH = "/internal/v1/health"
TOOL_EXECUTE_PATH = "/internal/v1/tools/execute"

SMOKE_APP_ID = "b54-padiem-claw"
FOREIGN_APP_ID = "b62"
GMAIL_AGENT_ID = "agent:padiem:claw_mail_reader@1"
GMAIL_TOOL_ID = "tool:google:gmail.search_messages@1"
UNREGISTERED_TOOL_ID = "tool:google:gmail.a11_smoke_unregistered@1"
REQUEST_TIMEOUT_SECONDS = 60

# Oversized argument payload: strictly greater than MAX_TOOL_ARGUMENT_BYTES
# (65536) so the Engine's argument-size bound fires, and small enough to stay
# under the worker request-body ceiling (128 KiB).
OVERSIZED_ARGUMENT = "a11-smoke-" + ("0" * 70_000)

ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"
RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
TOOL_CONTRACT_LIVE = "TOOL_CONTRACT_LIVE"
INVALID_REQUEST = "INVALID_REQUEST"
UPSTREAM_UNEXPECTED = "UPSTREAM_UNEXPECTED"
UNEXPECTED = "UNEXPECTED"

_ROUTE_NOT_FOUND_CODES = frozenset({"not_found"})
_RUNTIME_UNAVAILABLE_CODES = frozenset(
    {"tool_runtime_unavailable", "connector_grants_unavailable"}
)
_TOOL_NOT_ALLOWED_CODES = frozenset(
    {
        "tool_not_registered",
        "tool_agent_not_bound",
        "tool_authorization_mismatch",
        "tool_not_allowed",
        "tool_agent_mismatch",
        "tool_owner_mismatch",
        "tool_auth_scope_missing",
        "tool_external_authorization_required",
    }
)
_TOOL_CONTRACT_LIVE_CODES = frozenset({"tool_arguments_too_large", "invalid_tool_arguments"})
_INVALID_REQUEST_CODES = frozenset(
    {
        "invalid_request",
        "invalid_tool_request",
        "invalid_json",
        "unsupported_media_type",
        "method_not_allowed",
        "request_too_large",
        "provider_tool_wire_rejected",
        "caller_minted_tool_authority_rejected",
    }
)

ZERO_SIDE_EFFECT_TOKENS = "REAL_PROVIDER_CALLS=0 ROWS_WRITTEN=0 D1_MUTATION=0"

_failures: list[str] = []


def _fail(step: str, message: str, raw: Any = None) -> None:
    _failures.append(f"{step}: {message}")
    print(f"[{step}] FAIL: {message}", file=sys.stderr)
    if raw is not None:
        print(f"[{step}] RAW: {raw}", file=sys.stderr)


def _require_env() -> bool:
    if not CALLER_ID or not CALLER_SECRET:
        print("A11_GMAIL_TOOL_RUNTIME_SMOKE=SKIPPED_MISSING_SECRET", file=sys.stderr)
        print("SMOKE=SKIPPED_MISSING_SECRET", file=sys.stderr)
        return False
    return True


def _identity_headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a11-smoke/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
        "Content-Type": "application/json",
    }


def _request(
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | str]:
    url = f"{ENGINE_BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=_identity_headers())
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:  # network failure is a step failure, never a pass
        raise RuntimeError(f"request to {url} failed: {exc}") from exc
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _error_code(body: dict[str, Any] | str) -> str | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def classify(status: int, code: str | None) -> str:
    """Map one tool-route response onto an honest A11 classification."""
    if status == 404 and code in _ROUTE_NOT_FOUND_CODES:
        return ROUTE_UNAVAILABLE
    if status == 503 and code in _RUNTIME_UNAVAILABLE_CODES:
        return RUNTIME_UNAVAILABLE
    if status == 403 and code in _TOOL_NOT_ALLOWED_CODES:
        return TOOL_NOT_ALLOWED
    if status == 400 and code in _TOOL_CONTRACT_LIVE_CODES:
        return TOOL_CONTRACT_LIVE
    if 400 <= status < 500 and code in _INVALID_REQUEST_CODES:
        return INVALID_REQUEST
    if status >= 500:
        return UPSTREAM_UNEXPECTED
    return UNEXPECTED


def _execute_probe(app_id: str, tool_id: str) -> tuple[int, dict[str, Any] | str]:
    """POST one bounded tool-execution probe.

    Only the four allowed wire fields are sent (app_id, agent_id, tool_id,
    arguments). ``arguments`` is deliberately oversized so the Engine rejects
    the invocation at its argument-size bound — after binding, Agent authority
    and Tool registry resolution, but before any provider call.
    """
    body = {
        "app_id": app_id,
        "agent_id": GMAIL_AGENT_ID,
        "tool_id": tool_id,
        "arguments": {"query": OVERSIZED_ARGUMENT},
    }
    return _request(method="POST", path=TOOL_EXECUTE_PATH, body=body)


def s0_health() -> None:
    status, body = _request(method="GET", path=HEALTH_PATH)
    if status != 200:
        _fail("S0", f"health status {status} != 200", body)
        return
    if not isinstance(body, dict):
        _fail("S0", "health body is not an object", body)
        return
    capabilities = body.get("capabilities")
    capability = capabilities.get("tool_runtime") if isinstance(capabilities, dict) else None
    endpoints = body.get("endpoints") or []
    paths = {str(e.get("path")) for e in endpoints if isinstance(e, dict)}
    advertised = TOOL_EXECUTE_PATH in paths
    # Recorded, never asserted: the capability manifest stays DEFERRED until
    # the D43 credential/authorization gate, and the route is admitted in
    # source regardless of whether health advertises it.
    print(f"[S0] health OK: capabilities.tool_runtime={capability!r} {TOOL_EXECUTE_PATH}_advertised={advertised}")


def s1_canonical_gmail_probe() -> str:
    status, body = _execute_probe(SMOKE_APP_ID, GMAIL_TOOL_ID)
    code = _error_code(body)
    verdict = classify(status, code)
    print(f"[S1] canonical Gmail probe: status={status} code={code!r} -> {verdict}")
    if verdict == TOOL_CONTRACT_LIVE:
        print(
            "[S1] tool contract live: route wired, runtime bound, Agent authorized, "
            "Gmail tool registered — provider never called"
        )
        return verdict
    if verdict == ROUTE_UNAVAILABLE:
        # ACT-2 removed the ACT-1 DEFERRED tolerance: the Tool routes are
        # admitted in Engine source, so a 404 can only mean the deployed
        # build predates route admission. A stale deploy is a gate failure.
        _fail(
            "S1",
            "404 not_found — the Tool routes are wired in Engine source since "
            "ACT-2; a 404 means the deployed build predates route admission",
            body,
        )
        return verdict
    if verdict in (RUNTIME_UNAVAILABLE, TOOL_NOT_ALLOWED):
        print(f"[S1] route admitted, credential/authorization activation incomplete, "
              f"recorded honestly as {verdict}")
        return verdict
    if verdict == UNEXPECTED and 200 <= status < 300:
        _fail("S1", f"tool executed (status {status}) — a smoke probe must never reach the provider", body)
    else:
        _fail("S1", f"unexpected classification {verdict} (status={status}, code={code!r})", body)
    return verdict


def s2_unregistered_tool_probe(s1_verdict: str) -> None:
    status, body = _execute_probe(SMOKE_APP_ID, UNREGISTERED_TOOL_ID)
    code = _error_code(body)
    verdict = classify(status, code)
    if s1_verdict == TOOL_CONTRACT_LIVE:
        if code != "tool_not_registered" or verdict != TOOL_NOT_ALLOWED:
            _fail("S2", f"trusted registry did not reject an unregistered tool (status={status}, code={code!r})", body)
            return
        print("[S2] registry authority OK: unregistered tool rejected 403 tool_not_registered")
        return
    if verdict != s1_verdict:
        _fail("S2", f"probe inconsistent with S1 ({s1_verdict}): status={status}, code={code!r}", body)
        return
    print(f"[S2] consistent with S1: {verdict}")


def s3_cross_app_isolation() -> None:
    status, body = _execute_probe(FOREIGN_APP_ID, GMAIL_TOOL_ID)
    if not 400 <= status < 500:
        _fail("S3", f"cross-app probe status {status} not 4xx", body)
        return
    print(f"[S3] cross-app isolation OK: {status} {_error_code(body)!r}")


def main() -> int:
    if not _require_env():
        return 1

    s0_health()
    if _failures:
        print("A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL (S0 gate)", file=sys.stderr)
        return 1

    s1_verdict = s1_canonical_gmail_probe()
    route_available = s1_verdict != ROUTE_UNAVAILABLE
    # S2/S3 only make sense once S1 proved the route is admitted: with a dead
    # route every probe would just repeat the same 404, and after an
    # contradictory S1 no further probe should be sent at all.
    if route_available and not _failures:
        s2_unregistered_tool_probe(s1_verdict)
        s3_cross_app_isolation()

    if _failures:
        print(
            f"A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL ({len(_failures)} failures) — see raw output above",
            file=sys.stderr,
        )
        return 1

    if s1_verdict == TOOL_CONTRACT_LIVE:
        print(
            "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS "
            f"{ZERO_SIDE_EFFECT_TOKENS} ROUTE_AVAILABLE=1 "
            "TOOL_REGISTRY_LIVE=PASS AGENT_BOUND=PASS CROSS_APP=PASS"
        )
        return 0

    if s1_verdict == RUNTIME_UNAVAILABLE:
        reason = "TOOL_RUNTIME_UNAVAILABLE"
    else:
        reason = "TOOL_NOT_ALLOWED"

    # Reaching this line means the route was admitted (a 404 FAILs in S1), so
    # the DEFERRED record always carries ROUTE_WIRED=1: only the credential /
    # authorization activation state is deferred.
    print(
        f"A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED REASON={reason} "
        f"ROUTE_AVAILABLE={1 if route_available else 0} "
        f"ACTIVATION=ROUTE_WIRED_CREDENTIAL_PENDING {ZERO_SIDE_EFFECT_TOKENS} "
        f"CLASSIFICATION={s1_verdict}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
