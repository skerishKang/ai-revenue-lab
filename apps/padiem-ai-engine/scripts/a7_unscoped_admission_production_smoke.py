"""A7 Production fail-closed smoke for an unscoped app-level orchestration.

After #3300/#3298, Engine orchestration is user-entitlement gated. This probe
intentionally sends NO subject_id and therefore represents the app-level
ACCOUNT subject that the frozen MVP policy does not authorize.

PASS means the live A7 path rejected the request before Core/provider dispatch.
It is deliberately NOT an idempotency/orchestration success smoke and must
never be used as evidence that authenticated-user orchestration is live.
A separate authenticated A7 canary owns that proof.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


ENGINE_BASE_URL = os.environ.get(
    "ENGINE_BASE_URL",
    "https://engine.padiem.net",
).rstrip("/")
CALLER_ID = os.environ.get("CALLER_ID", "")
CALLER_SECRET = os.environ.get("CALLER_SECRET", "")
REQUEST_TIMEOUT_SECONDS = 30

HEALTH_PATH = "/internal/v1/health"
ORCHESTRATE_PATH = "/internal/v1/orchestrate"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a7-unscoped-smoke/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    data = (
        json.dumps(body, separators=(",", ":")).encode("utf-8")
        if body is not None
        else None
    )
    request = urllib.request.Request(
        f"{ENGINE_BASE_URL}{path}",
        data=data,
        method=method,
        headers=_headers(),
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        status = exc.code
    except Exception as exc:
        raise RuntimeError(
            "A7 Production smoke transport failed"
        ) from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    return status, decoded if isinstance(decoded, dict) else None


def _payload() -> dict[str, Any]:
    """Contract-valid orchestration request with subject_id deliberately absent.

    The agent id must satisfy the Padiem AI Core ``AgentProfile`` identifier
    contract (``agent:<owner>:<name>``). The earlier ``@1`` version suffix
    belongs to the AgentDefinition / agent_plan grammar, NOT to AgentProfile,
    so the probe failed ordinary request validation with ``400
    invalid_request`` *before* the A7 admission seam was ever consulted —
    which meant the smoke proved nothing about admission. With a
    contract-valid agent id and ``subject_id`` still intentionally omitted,
    the request reaches A7 admission unscoped and must be rejected there,
    before any Core/provider dispatch.
    """

    return {
        "app_id": "b54-padiem-claw",
        "agent": {
            "id": "agent:padiem:a7_unscoped_probe",
            "title": "A7 unscoped admission probe",
            "description": "Must stop at authenticated-user entitlement gate",
            "system_instruction": "This instruction must never reach a provider.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 8,
            "required_capabilities": [],
            "model_policy": {
                "model": "a7/no-provider-expected",
            },
        },
        "messages": [
            {
                "role": "user",
                "content": "This request must be rejected before execution.",
            }
        ],
        "trace_id": "a7_unscoped_production_smoke",
        "execution_context": {
            "trace_id": "a7_unscoped_production_smoke",
            "timeout_seconds": 10.0,
        },
        "max_retries": 0,
        "require_evidence": False,
        "require_verification": False,
    }


def main() -> int:
    if not CALLER_ID or not CALLER_SECRET:
        print(
            "A7_UNSCOPED_ADMISSION_SMOKE=SKIPPED_MISSING_SECRET",
            file=sys.stderr,
        )
        return 2

    health_status, health = _request(
        "GET",
        HEALTH_PATH,
    )
    if health_status != 200 or not isinstance(
        health,
        dict,
    ):
        print(
            "A7_UNSCOPED_ADMISSION_SMOKE=FAIL_HEALTH",
            file=sys.stderr,
        )
        return 1

    endpoints = health.get("endpoints")
    if not isinstance(endpoints, list) or not any(
        isinstance(item, dict)
        and item.get("path") == ORCHESTRATE_PATH
        for item in endpoints
    ):
        print(
            "A7_UNSCOPED_ADMISSION_SMOKE=FAIL_ROUTE",
            file=sys.stderr,
        )
        return 1

    status, body = _request(
        "POST",
        ORCHESTRATE_PATH,
        _payload(),
    )
    error = (
        body.get("error")
        if isinstance(body, dict)
        else None
    )
    code = (
        error.get("code")
        if isinstance(error, dict)
        else None
    )

    if status != 503 or code != "entitlement_unavailable":
        print(
            "A7_UNSCOPED_ADMISSION_SMOKE=FAIL_UNEXPECTED_VERDICT",
            file=sys.stderr,
        )
        print(
            f"HTTP_STATUS={status}",
            file=sys.stderr,
        )
        print(
            f"ERROR_CODE={code if isinstance(code, str) else 'NONE'}",
            file=sys.stderr,
        )
        return 1

    print("A7_UNSCOPED_ADMISSION_SMOKE=PASS")
    print("EXPECTED_AUTH_GATE=PASS")
    print("SUBJECT_ID_SENT=0")
    print("ACCOUNT_LEVEL_ALLOW_EXPECTED=NO")
    print("REAL_PROVIDER_CALLS=0")
    print("D1_USAGE_RESERVATION_WRITES=0")
    print("AUTHENTICATED_USER_LIVE_PROOF=NOT_CLAIMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
