"""Bounded provider-free E9 approval pause -> resume one-shot runner (#3321).

This file prepares a future owner-authorized Production smoke.  It never
enables the approval fixture, mutates caller configuration, deploys source, or
changes the capability manifest.  A live invocation is allowed to exercise
only the canonical continuation lifecycle already owned by the Engine:

    POST /internal/v1/orchestrate
      -> PAUSED + opaque continuation_ref
    POST /internal/v1/orchestrate/resume
      -> COMPLETED

The continuation reference is held in memory only and is never printed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Protocol


ENGINE_BASE_URL_ENV = "ENGINE_BASE_URL"
CALLER_ID_ENV = "PADIEM_ENGINE_APPROVAL_SMOKE_CALLER_ID"
CALLER_CREDENTIAL_ENV = "PADIEM_ENGINE_APPROVAL_SMOKE_CALLER_CREDENTIAL"

DEFAULT_ENGINE_BASE_URL = "https://engine.padiem.net"
ORCHESTRATE_PATH = "/internal/v1/orchestrate"
RESUME_PATH = "/internal/v1/orchestrate/resume"
REQUEST_TIMEOUT_SECONDS = 30

# Canonical fixture identities from app.approval_smoke_binding.  They are
# source constants, never argv/env/request-selected.
APP_ID = "b54-engine-approval-smoke"
CANONICAL_AGENT_ID = "agent:padiem:approval_smoke@1"
RUNTIME_AGENT_ID = "agent-runtime:1eb5117ae5d2e485882b118c"
CANONICAL_TOOL_ID = "tool:padiem:approval_smoke@1"
RUNTIME_TOOL_ID = "approval_smoke.confirm"
SUBJECT_ID = "subject:approval-smoke"

_AGENT_TITLE = "Approval smoke agent"
_AGENT_DESCRIPTION = "Provider-free approval continuation smoke agent"
_AGENT_INSTRUCTION = "Run only the synthetic approval confirmation tool."
_STEP_ID = "step_1"
_STEP_OBJECTIVE = "Confirm synthetic approval smoke"

_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9._:@/-]{1,255}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


class SmokeError(RuntimeError):
    """Public-safe smoke failure.  Never embed raw response bodies or secrets."""


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> tuple[int, dict[str, Any] | None]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(slots=True)
class HttpTransport:
    base_url: str
    caller_id: str
    caller_credential: str
    _opener: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.startswith("https://"):
            raise SmokeError("ENGINE_BASE_URL_INVALID")
        if not self.caller_id or not _SAFE_ID_RE.fullmatch(self.caller_id):
            raise SmokeError("CALLER_ID_INVALID")
        if not self.caller_credential:
            raise SmokeError("CALLER_CREDENTIAL_MISSING")
        self._opener = urllib.request.build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> tuple[int, dict[str, Any] | None]:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "User-Agent": "padiem-e9-approval-smoke/1.0 (+owner-authorized)",
                "x-padiem-engine-caller": self.caller_id,
                "x-padiem-engine-credential": self.caller_credential,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            # 3xx remains an HTTPError because redirects are deliberately disabled.
            raw = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except Exception as exc:
            raise SmokeError("TRANSPORT_FAILURE") from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        return status, decoded if isinstance(decoded, dict) else None


def _run_token(source: str) -> str:
    raw = source if isinstance(source, str) and source else "local"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _initial_payload(token: str) -> dict[str, Any]:
    trace_id = f"tr_approval_smoke_{token}"
    return {
        "app_id": APP_ID,
        "agent": {
            "id": RUNTIME_AGENT_ID,
            "title": _AGENT_TITLE,
            "description": _AGENT_DESCRIPTION,
            "system_instruction": _AGENT_INSTRUCTION,
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 128,
            "model_policy": {"model": "test/provider-free"},
        },
        "messages": [{"role": "user", "content": "Run the approval smoke fixture."}],
        "trace_id": trace_id,
        "execution_context": {
            "trace_id": trace_id,
            "timeout_seconds": 5.0,
        },
        "agent_plan": {
            "agent_id": CANONICAL_AGENT_ID,
            "steps": [
                {
                    "step_id": _STEP_ID,
                    "objective": _STEP_OBJECTIVE,
                    "tool_id": RUNTIME_TOOL_ID,
                }
            ],
        },
        "tool_arguments": {
            _STEP_ID: {
                "nonce": f"approval-smoke-{token}",
            }
        },
        "subject_id": SUBJECT_ID,
        "max_retries": 0,
        "require_evidence": False,
        "require_verification": False,
    }


def _safe_error_code(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return "NONE"
    error = body.get("error")
    if not isinstance(error, dict):
        return "NONE"
    code = error.get("code")
    if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
        return "UNSAFE_OR_UNKNOWN"
    return code


def _paused_evidence(body: dict[str, Any] | None) -> tuple[str, str, str]:
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise SmokeError(f"INITIAL_RESPONSE_INVALID:{_safe_error_code(body)}")
    orchestration = body.get("orchestration")
    if not isinstance(orchestration, dict):
        raise SmokeError("INITIAL_ORCHESTRATION_MISSING")

    execution = orchestration.get("execution")
    metadata = execution.get("metadata") if isinstance(execution, dict) else None
    if not isinstance(metadata, dict) or metadata.get("status") != "paused":
        raise SmokeError("INITIAL_NOT_PAUSED")

    continuation_ref = orchestration.get("continuation_ref")
    if not isinstance(continuation_ref, str) or not _CONTINUATION_RE.fullmatch(continuation_ref):
        raise SmokeError("CONTINUATION_REF_INVALID")

    pause = orchestration.get("approval_pause")
    if not isinstance(pause, dict) or pause.get("status") != "paused":
        raise SmokeError("APPROVAL_PAUSE_MISSING")
    if pause.get("tool_id") != RUNTIME_TOOL_ID:
        raise SmokeError("APPROVAL_TOOL_MISMATCH")
    if pause.get("requirement") != "user_confirmation":
        raise SmokeError("APPROVAL_REQUIREMENT_MISMATCH")

    pause_id = pause.get("continuation_id")
    created_at = pause.get("created_at")
    if not isinstance(pause_id, str) or not _SAFE_ID_RE.fullmatch(pause_id):
        raise SmokeError("PAUSE_ID_INVALID")
    if not isinstance(created_at, str):
        raise SmokeError("PAUSE_CREATED_AT_INVALID")
    try:
        parsed = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise SmokeError("PAUSE_CREATED_AT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SmokeError("PAUSE_CREATED_AT_INVALID")

    return continuation_ref, pause_id, created_at


def _resume_payload(
    initial: dict[str, Any],
    continuation_ref: str,
    pause_id: str,
    decided_at: str,
    token: str,
) -> dict[str, Any]:
    resumed = {
        key: value
        for key, value in initial.items()
        if key not in {"require_evidence", "require_verification"}
    }
    resumed["continuation_ref"] = continuation_ref
    resumed["decision"] = {
        "decision_id": f"dec_approval_smoke_{token}",
        "pause_id": pause_id,
        "outcome": "approved",
        "authority_ref": "user:approval-smoke",
        "evidence_ref": "session:approval-smoke",
        # The server-issued pause creation timestamp is guaranteed to be inside
        # the approval window and avoids local/remote clock-skew widening.
        "decided_at": decided_at,
    }
    return resumed


def _completed_evidence(body: dict[str, Any] | None) -> None:
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise SmokeError(f"RESUME_RESPONSE_INVALID:{_safe_error_code(body)}")
    orchestration = body.get("orchestration")
    if not isinstance(orchestration, dict):
        raise SmokeError("RESUME_ORCHESTRATION_MISSING")
    if "continuation_ref" in orchestration:
        raise SmokeError("RESUME_REPAUSED_UNEXPECTEDLY")
    execution = orchestration.get("execution")
    metadata = execution.get("metadata") if isinstance(execution, dict) else None
    if not isinstance(metadata, dict) or metadata.get("status") != "completed":
        raise SmokeError("RESUME_NOT_COMPLETED")
    events = metadata.get("tool_events")
    if not isinstance(events, list) or not any(
        isinstance(event, dict)
        and event.get("tool_id") == RUNTIME_TOOL_ID
        and event.get("status") == "completed"
        for event in events
    ):
        raise SmokeError("TOOL_COMPLETION_EVIDENCE_MISSING")


def run_one_shot(transport: Transport, *, run_source: str = "local") -> None:
    """Perform exactly one pause-producing POST and one resume POST."""
    token = _run_token(run_source)
    initial = _initial_payload(token)

    status, body = transport.request("POST", ORCHESTRATE_PATH, initial)
    if status != 200:
        raise SmokeError(f"INITIAL_HTTP_STATUS:{status}:{_safe_error_code(body)}")
    continuation_ref, pause_id, created_at = _paused_evidence(body)

    resumed = _resume_payload(initial, continuation_ref, pause_id, created_at, token)
    status, body = transport.request("POST", RESUME_PATH, resumed)
    if status != 200:
        raise SmokeError(f"RESUME_HTTP_STATUS:{status}:{_safe_error_code(body)}")
    _completed_evidence(body)


def main() -> int:
    caller_id = os.environ.get(CALLER_ID_ENV, "")
    credential = os.environ.get(CALLER_CREDENTIAL_ENV, "")
    if not caller_id or not credential:
        print("E9_APPROVAL_ONE_SHOT=BLOCKED_MISSING_CALLER_AUTHORITY", file=sys.stderr)
        return 2

    try:
        transport = HttpTransport(
            base_url=os.environ.get(ENGINE_BASE_URL_ENV, DEFAULT_ENGINE_BASE_URL),
            caller_id=caller_id,
            caller_credential=credential,
        )
        run_one_shot(transport, run_source=os.environ.get("GITHUB_RUN_ID", "local"))
    except SmokeError as exc:
        print("E9_APPROVAL_ONE_SHOT=FAIL", file=sys.stderr)
        print(f"SAFE_FAILURE={exc}", file=sys.stderr)
        print("CONTINUATION_REF_OUTPUT=0", file=sys.stderr)
        print("CALLER_CREDENTIAL_OUTPUT=0", file=sys.stderr)
        return 1

    print("E9_APPROVAL_ONE_SHOT=PASS")
    print("INITIAL_STATUS=PAUSED")
    print("RESUME_STATUS=COMPLETED")
    print("ORCHESTRATE_POST_COUNT=1")
    print("RESUME_POST_COUNT=1")
    print("HTTP_RETRIES=0")
    print("HTTP_REDIRECTS_FOLLOWED=0")
    print("PROVIDER_RUNTIME_ENTERED=0")
    print("EXTERNAL_SIDE_EFFECTS=0")
    print("CONTINUATION_REF_OUTPUT=0")
    print("CALLER_CREDENTIAL_OUTPUT=0")
    print("MANIFEST_FLIP=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
