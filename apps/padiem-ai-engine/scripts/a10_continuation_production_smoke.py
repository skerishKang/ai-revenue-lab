"""WO-9 PR-A A10 approval-continuation production fail-closed smoke (#1966).

Runs against the PRODUCTION Engine (default https://engine.padiem.net) with the
product-owned smoke caller credential (PADIEM_ENGINE_SMOKE_CALLER_ID/_SECRET,
allowed_app_ids=["b54-padiem-claw"]). Standard library only.

Measured production state on main 08e914e5 (WO-9 evidence, see
docs/operations/P01_ENGINE_APPROVAL_CONTINUATION_ACTIVATION_v1.md):
  - orchestration orchestration_service.resume_payload / cancel_payload exist,
    wired to ORCHESTRATE_RESUME_PATH / ORCHESTRATE_CANCEL_PATH;
  - Production ENGINE_CONTINUATION D1 binding is present, so resume/cancel
    read the EXPLICIT D1 store (no in-memory fallback);
  - health capabilities orchestration_resume / orchestration_cancel == "available";
  - BUT no production pause producer exists (tool_binding_resolver=None ->
    the plan bridge is not wired), so no real pause -> resume can ever happen
    in Production: BLOCKER_C1 stays OPEN and approval_continuation stays
    DEFERRED. Manifest flip is gated on A3 (#2010) + one real prod
    pause -> resume, in a SEPARATE PR. This script never flips anything.

Steps (all probes are REJECTED at parse/resolve, before any claim/mutation):
  S0  GET  /internal/v1/health                    -> 200, capabilities
      orchestration_resume == "available" AND orchestration_cancel == "available".
  S1  POST /internal/v1/orchestrate/resume        -> 409 invalid_continuation
      for a well-formed but never-issued continuation_ref
      (cont_a10_smoke_<RUN_ID>). 503 continuation_store_unavailable is an
      explicit FAIL (store unexpectedly unbound).
  S2  POST /internal/v1/orchestrate/cancel        -> 409 invalid_continuation
      for the same never-issued continuation_ref.
  S3  POST /internal/v1/orchestrate/resume with app_id="b62"
      -> 4xx service_app_not_authorized / service_authentication_failed:
      cross-app isolation fires in the worker auth layer BEFORE payload logic.
  S4  POST /internal/v1/orchestrate/resume with continuation_ref="not-a-ref"
      (fails _parse_continuation_ref: not starting with "cont_")
      -> 409 invalid_continuation.

Honesty rules: the script exits non-zero on any failed assertion and prints
the raw failure output; the final PASS line is printed only when every step
passed. REAL_PROVIDER_CALLS is 0 by construction (no orchestrate call) and
ROWS_WRITTEN is 0 by construction (every probe is rejected before the first
continuation-store mutation: resolve fails, claim is never reached).

The request bodies are MINIMAL on purpose: {"app_id", "continuation_ref"}
only. No orchestration payload, no verified-approval material, no agent plan
is ever transmitted — this probe can never pause, resume, or cancel a real
continuation.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "https://engine.padiem.net").rstrip("/")
CALLER_ID = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_ID", "")
CALLER_SECRET = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_SECRET", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

HEALTH_PATH = "/internal/v1/health"
RESUME_PATH = "/internal/v1/orchestrate/resume"
CANCEL_PATH = "/internal/v1/orchestrate/cancel"
SMOKE_APP_ID = "b54-padiem-claw"
FOREIGN_APP_ID = "b62"
REF = f"cont_a10_smoke_{GITHUB_RUN_ID}"
MALFORMED_REF = "not-a-ref"
REQUEST_TIMEOUT_SECONDS = 60

ISOLATION_CODES = {"service_app_not_authorized", "service_authentication_failed"}

_failures: list[str] = []


def _fail(step: str, message: str, raw: Any = None) -> None:
    _failures.append(f"{step}: {message}")
    print(f"[{step}] FAIL: {message}", file=sys.stderr)
    if raw is not None:
        print(f"[{step}] RAW: {raw}", file=sys.stderr)


def _require_env() -> bool:
    if not CALLER_ID or not CALLER_SECRET:
        print("SMOKE=SKIPPED_MISSING_SECRET", file=sys.stderr)
        return False
    return True


def _identity_headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a10-smoke/1.0 (+github-actions)",
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


def _minimal_resume_cancel_body(app_id: str, continuation_ref: str) -> dict[str, Any]:
    # Deliberately minimal: allowed-field sets accept app_id + continuation_ref
    # alone, so nothing else can leak into a mutation path.
    return {"app_id": app_id, "continuation_ref": continuation_ref}


def s0_health() -> None:
    status, body = _request(method="GET", path=HEALTH_PATH)
    if status != 200:
        _fail("S0", f"health status {status} != 200", body)
        return
    if not isinstance(body, dict):
        _fail("S0", "health body is not an object", body)
        return
    capabilities = body.get("capabilities")
    if not isinstance(capabilities, dict):
        _fail("S0", "health capabilities missing", body)
        return
    for key in ("orchestration_resume", "orchestration_cancel"):
        if capabilities.get(key) != "available":
            _fail("S0", f"capabilities.{key}={capabilities.get(key)!r} != 'available'")
    if _failures:
        return
    print("[S0] health OK: orchestration_resume=available, orchestration_cancel=available")


def _expect_invalid_continuation(step: str, *, path: str, body: dict[str, Any]) -> bool:
    """POST a never-issued (or malformed) ref; only 409 invalid_continuation passes.

    503 continuation_store_unavailable is an explicit FAIL: it means the
    Production D1 store binding the WO-9 gate depends on is gone.
    """
    status, response = _request(method="POST", path=path, body=body)
    code = _error_code(response)
    if status == 503 and code == "continuation_store_unavailable":
        _fail(step, "continuation store unexpectedly unavailable in Production (STORE_BOUND violated)", response)
        return False
    if status != 409:
        _fail(step, f"fail-closed status {status} != 409", response)
        return False
    if code != "invalid_continuation":
        _fail(step, f"error code {code!r} != 'invalid_continuation'", response)
        return False
    return True


def s1_resume_unknown_ref_is_rejected() -> None:
    body = _minimal_resume_cancel_body(SMOKE_APP_ID, REF)
    if _expect_invalid_continuation("S1", path=RESUME_PATH, body=body):
        print(f"[S1] resume fail-closed OK: 409 invalid_continuation for never-issued {REF!r}")


def s2_cancel_unknown_ref_is_rejected() -> None:
    body = _minimal_resume_cancel_body(SMOKE_APP_ID, REF)
    if _expect_invalid_continuation("S2", path=CANCEL_PATH, body=body):
        print(f"[S2] cancel fail-closed OK: 409 invalid_continuation for never-issued {REF!r}")


def s3_cross_app_isolation() -> None:
    body = _minimal_resume_cancel_body(FOREIGN_APP_ID, REF)
    status, response = _request(method="POST", path=RESUME_PATH, body=body)
    if not 400 <= status < 500:
        _fail("S3", f"cross-app probe status {status} not 4xx", response)
        return
    code = _error_code(response)
    if code not in ISOLATION_CODES:
        _fail("S3", f"error code {code!r} not in accepted isolation codes", response)
        return
    print(f"[S3] cross-app isolation OK: {status} {code}")


def s4_malformed_ref_is_rejected() -> None:
    body = _minimal_resume_cancel_body(SMOKE_APP_ID, MALFORMED_REF)
    if _expect_invalid_continuation("S4", path=RESUME_PATH, body=body):
        print(f"[S4] malformed-ref OK: 409 invalid_continuation for {MALFORMED_REF!r}")


def main() -> int:
    if not _require_env():
        return 1

    s0_health()
    if _failures:
        print("A10_CONTINUATION_SMOKE=FAIL (S0 gate)", file=sys.stderr)
        return 1

    s1_resume_unknown_ref_is_rejected()
    s2_cancel_unknown_ref_is_rejected()
    s3_cross_app_isolation()
    s4_malformed_ref_is_rejected()

    if _failures:
        print(f"A10_CONTINUATION_SMOKE=FAIL ({len(_failures)} failures) — see raw output above", file=sys.stderr)
        return 1

    print(
        "A10_CONTINUATION_SMOKE=PASS REAL_PROVIDER_CALLS=0 ROWS_WRITTEN=0 "
        "STORE_BOUND=PASS FAIL_CLOSED_RESUME=PASS FAIL_CLOSED_CANCEL=PASS "
        "CROSS_APP=PASS BLOCKER_C1=OPEN"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
