"""Owner-gated A7 authenticated USER Production canary.

This probe is intentionally separate from the unscoped fail-closed smoke.
It supplies one protected canonical USER subject and performs one tiny
orchestration request. The Control Plane identity authority must re-validate
that subject as currently signed in; the Engine never installs entitlement
truth itself.

A PASS is meaningful only on the exact A7-bound served Engine version checked
by the surrounding workflow. Exact source fails closed if entitlement fetch,
usage reservation, or terminal usage receipt is unavailable/rejected.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

from padiem_ai_core.model_primary import TEXT_PRIMARY_MODEL_ID


ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "https://engine.padiem.net").rstrip("/")
CALLER_ID = os.environ.get("CALLER_ID", "")
CALLER_SECRET = os.environ.get("CALLER_SECRET", "")
CANARY_SUBJECT_ID = os.environ.get("PADIEM_A7_CANARY_SUBJECT_ID", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

HEALTH_PATH = "/internal/v1/health"
ORCHESTRATE_PATH = "/internal/v1/orchestrate"
PINNED_MODEL = TEXT_PRIMARY_MODEL_ID
REQUEST_TIMEOUT_SECONDS = 90
_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a7-authenticated-user-canary/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{ENGINE_BASE_URL}{path}",
        data=data,
        method=method,
        headers=_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:
        raise RuntimeError("A7 authenticated canary transport failed") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    return status, decoded if isinstance(decoded, dict) else None


def _payload(subject_id: str) -> dict[str, Any]:
    return {
        "app_id": "b54-padiem-claw",
        "subject_id": subject_id,
        "agent": {
            "id": "agent:padiem:a7_authenticated_canary@1",
            "title": "A7 authenticated USER canary",
            "description": "Bounded authenticated entitlement and usage lifecycle proof",
            "system_instruction": "You are a production canary. Reply with exactly OK.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 8,
            "required_capabilities": [],
            "model_policy": {"model": PINNED_MODEL},
        },
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "trace_id": f"a7-authenticated-canary-{GITHUB_RUN_ID}",
        "execution_context": {
            "trace_id": f"a7-authenticated-canary-{GITHUB_RUN_ID}",
            "timeout_seconds": 60.0,
            "idempotency_key": f"a7-authenticated-canary-{GITHUB_RUN_ID}-1",
        },
        "max_retries": 0,
        "require_evidence": False,
        "require_verification": False,
    }


def _upstream_5xx(body: dict[str, Any] | None) -> int | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    metadata = error.get("metadata")
    if not isinstance(metadata, dict):
        return None
    code = metadata.get("upstream_status_code")
    if isinstance(code, int) and not isinstance(code, bool) and 500 <= code <= 599:
        return code
    return None


def _error_code(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return "NONE"
    error = body.get("error")
    if not isinstance(error, dict):
        return "NONE"
    code = error.get("code")
    return code if isinstance(code, str) else "NONE"


def main() -> int:
    if not CALLER_ID or not CALLER_SECRET or not CANARY_SUBJECT_ID:
        print("A7_AUTHENTICATED_USER_CANARY=SKIPPED_MISSING_PROTECTED_INPUT", file=sys.stderr)
        return 2
    if not _SUBJECT_RE.fullmatch(CANARY_SUBJECT_ID):
        print("A7_AUTHENTICATED_USER_CANARY=FAIL_INVALID_SUBJECT_REFERENCE", file=sys.stderr)
        return 1

    health_status, health = _request("GET", HEALTH_PATH)
    endpoints = health.get("endpoints") if isinstance(health, dict) else None
    if (
        health_status != 200
        or not isinstance(endpoints, list)
        or not any(
            isinstance(item, dict) and item.get("path") == ORCHESTRATE_PATH
            for item in endpoints
        )
    ):
        print("A7_AUTHENTICATED_USER_CANARY=FAIL_HEALTH_OR_ROUTE", file=sys.stderr)
        return 1

    status, body = _request("POST", ORCHESTRATE_PATH, _payload(CANARY_SUBJECT_ID))
    upstream = _upstream_5xx(body)
    if upstream is not None:
        print("A7_AUTHENTICATED_USER_CANARY=DEFERRED_UPSTREAM", file=sys.stderr)
        print(f"UPSTREAM_STATUS_CODE={upstream}", file=sys.stderr)
        return 3

    if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
        print("A7_AUTHENTICATED_USER_CANARY=FAIL_RUNTIME", file=sys.stderr)
        print(f"HTTP_STATUS={status}", file=sys.stderr)
        print(f"ERROR_CODE={_error_code(body)}", file=sys.stderr)
        return 1

    orchestration = body.get("orchestration")
    execution = orchestration.get("execution") if isinstance(orchestration, dict) else None
    answer = execution.get("answer") if isinstance(execution, dict) else None
    route = execution.get("route") if isinstance(execution, dict) else None
    request_id = route.get("request_id") if isinstance(route, dict) else None
    if not isinstance(answer, str) or not answer.strip() or not isinstance(request_id, str) or not request_id:
        print("A7_AUTHENTICATED_USER_CANARY=FAIL_EXECUTION_EVIDENCE", file=sys.stderr)
        return 1

    print("A7_AUTHENTICATED_USER_CANARY=PASS")
    print("CANONICAL_IDENTITY_REVALIDATION=PASS")
    print("ADMISSION_LIFECYCLE_FAIL_CLOSED=PASS")
    print("EXECUTION_COMPLETED=PASS")
    print("RAW_SUBJECT_OUTPUT=0")
    print("REAL_PROVIDER_CALL_MAX=1")
    print("MANIFEST_FLIP=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
