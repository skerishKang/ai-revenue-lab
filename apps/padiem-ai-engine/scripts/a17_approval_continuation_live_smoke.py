"""Bounded one-shot real approval pause -> resume runner (#3321).

SOURCE ONLY until separately owner-authorized.  The future live run is allowed
to hit only the dedicated provider-free approval smoke fixture introduced by
#3317.  It performs exactly two Engine POSTs, has no retry, never follows
redirects, never calls a provider directly, and never prints raw responses,
credentials, continuation refs, pause ids or trace ids.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

ENGINE_BASE_URL = "https://engine.padiem.net"
ORCHESTRATE_PATH = "/internal/v1/orchestrate"
RESUME_PATH = "/internal/v1/orchestrate/resume"

CALLER_ID_ENV = "PADIEM_ENGINE_APPROVAL_SMOKE_CALLER_ID"
CALLER_SECRET_ENV = "PADIEM_ENGINE_APPROVAL_SMOKE_CALLER_SECRET"

APP_ID = "b54-engine-approval-smoke"
CANONICAL_AGENT_ID = "agent:padiem:approval_smoke@1"
RUNTIME_TOOL_ID = "approval_smoke.confirm"
AUTHORITY_REF = "actor:approval-smoke"
EVIDENCE_REF = "session:approval-smoke"

REQUEST_TIMEOUT_SECONDS = 60

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9._:-]{1,123}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _runtime_profile_id() -> str:
    digest = hashlib.sha256(CANONICAL_AGENT_ID.encode("utf-8")).hexdigest()[:24]
    return f"agent-runtime:{digest}"


def canonical_orchestrate_body(*, trace_id: str, nonce: str) -> dict[str, Any]:
    """Return the fixed provider-free smoke wire shape."""
    return {
        "app_id": APP_ID,
        "agent": {
            "id": _runtime_profile_id(),
            "title": "Approval smoke agent",
            "description": "Provider-free approval continuation smoke agent",
            "system_instruction": "Run only the synthetic approval confirmation tool.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 128,
            "model_policy": {"model": "test/provider-free"},
        },
        "messages": [
            {
                "role": "user",
                "content": "Run the bounded provider-free approval smoke.",
            }
        ],
        "trace_id": trace_id,
        "execution_context": {
            "trace_id": trace_id,
            "timeout_seconds": 15.0,
        },
        "agent_plan": {
            "agent_id": CANONICAL_AGENT_ID,
            "steps": [
                {
                    "step_id": "step_1",
                    "objective": "Confirm synthetic approval smoke",
                    "tool_id": RUNTIME_TOOL_ID,
                }
            ],
        },
        "tool_arguments": {
            "step_1": {
                "nonce": nonce,
            }
        },
        "subject_id": "subject:approval-smoke",
    }


def canonical_resume_body(
    initial: Mapping[str, Any],
    *,
    continuation_ref: str,
    pause_id: str,
    decision_id: str,
    decided_at: str,
) -> dict[str, Any]:
    """Project the initial request onto the canonical resume wire surface."""
    return {
        "app_id": initial["app_id"],
        "agent": initial["agent"],
        "messages": initial["messages"],
        "trace_id": initial["trace_id"],
        "execution_context": initial["execution_context"],
        "agent_plan": initial["agent_plan"],
        "tool_arguments": initial["tool_arguments"],
        "subject_id": initial["subject_id"],
        "continuation_ref": continuation_ref,
        "decision": {
            "decision_id": decision_id,
            "pause_id": pause_id,
            "outcome": "approved",
            "authority_ref": AUTHORITY_REF,
            "evidence_ref": EVIDENCE_REF,
            "decided_at": decided_at,
        },
    }


def _headers(caller_id: str, credential: str) -> dict[str, str]:
    if not isinstance(caller_id, str) or _SAFE_CODE_RE.fullmatch(caller_id) is None:
        raise ValueError("invalid caller id")
    if not isinstance(credential, str) or not credential:
        raise ValueError("missing caller credential")
    return {
        "User-Agent": "padiem-approval-continuation-smoke/1.0 (+github-actions)",
        "x-padiem-engine-caller": caller_id,
        "x-padiem-engine-credential": credential,
        "Content-Type": "application/json",
    }


def _http_post_once(
    path: str,
    body: Mapping[str, Any],
    caller_id: str,
    credential: str,
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"{ENGINE_BASE_URL}{path}",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers=_headers(caller_id, credential),
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _safe_error_code(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return "non_object_error"
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "missing_error_code"
    code = error.get("code")
    if not isinstance(code, str) or _SAFE_CODE_RE.fullmatch(code) is None:
        return "unsafe_error_code"
    return code


def _classify_pause(payload: Any, *, expected_trace_id: str) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise ValueError("noncanonical pause envelope")
    orch = payload.get("orchestration")
    if not isinstance(orch, Mapping):
        raise ValueError("missing orchestration envelope")
    execution = orch.get("execution")
    if not isinstance(execution, Mapping):
        raise ValueError("missing execution envelope")
    metadata = execution.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("status") != "paused":
        raise ValueError("execution did not pause")
    if metadata.get("provider") not in (None, "p01_agent_bridge"):
        raise ValueError("unexpected provider metadata on pause")
    route = execution.get("route")
    if not isinstance(route, Mapping):
        raise ValueError("missing route metadata")
    if route.get("selected_provider") != "p01_agent_bridge":
        raise ValueError("pause did not stay on provider-free agent bridge")
    if route.get("selected_model") != "bounded_agent_plan":
        raise ValueError("unexpected approval smoke route model")

    context = orch.get("context")
    if not isinstance(context, Mapping) or context.get("trace_id") != expected_trace_id:
        raise ValueError("trace identity drift")

    continuation_ref = orch.get("continuation_ref")
    if not isinstance(continuation_ref, str) or _CONTINUATION_RE.fullmatch(continuation_ref) is None:
        raise ValueError("invalid server continuation ref")

    pause = orch.get("approval_pause")
    if not isinstance(pause, Mapping):
        raise ValueError("missing approval pause")
    pause_id = pause.get("continuation_id")
    if not isinstance(pause_id, str) or _OPAQUE_ID_RE.fullmatch(pause_id) is None:
        raise ValueError("invalid approval pause id")
    if pause.get("tool_id") != RUNTIME_TOOL_ID:
        raise ValueError("unexpected paused tool")
    if pause.get("requirement") != "user_confirmation":
        raise ValueError("unexpected approval requirement")
    if pause.get("trace_id") != expected_trace_id:
        raise ValueError("pause trace identity drift")

    state = orch.get("continuation_state")
    if not isinstance(state, Mapping) or state.get("status") != "waiting_approval":
        raise ValueError("unexpected continuation state")

    return continuation_ref, pause_id


def _classify_resume(payload: Any, *, expected_trace_id: str) -> None:
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise ValueError("noncanonical resume envelope")
    orch = payload.get("orchestration")
    if not isinstance(orch, Mapping):
        raise ValueError("missing orchestration envelope")
    execution = orch.get("execution")
    if not isinstance(execution, Mapping):
        raise ValueError("missing execution envelope")
    metadata = execution.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("status") != "completed":
        raise ValueError("resumed execution did not complete")
    if metadata.get("provider") not in (None, "p01_agent_bridge"):
        raise ValueError("unexpected provider metadata on resume")
    route = execution.get("route")
    if not isinstance(route, Mapping):
        raise ValueError("missing resume route metadata")
    if route.get("selected_provider") != "p01_agent_bridge":
        raise ValueError("resume left provider-free agent bridge")
    if route.get("selected_model") != "bounded_agent_plan":
        raise ValueError("unexpected resumed route model")

    context = orch.get("context")
    if not isinstance(context, Mapping) or context.get("trace_id") != expected_trace_id:
        raise ValueError("resume trace identity drift")

    events = metadata.get("tool_events")
    if not isinstance(events, list):
        raise ValueError("missing tool events")
    if not any(
        isinstance(event, Mapping)
        and event.get("tool_id") == RUNTIME_TOOL_ID
        and event.get("status") == "completed"
        for event in events
    ):
        raise ValueError("approved tool did not complete")

    state = orch.get("continuation_state")
    if not isinstance(state, Mapping) or state.get("status") != "resumable":
        raise ValueError("unexpected resolved continuation state")


Transport = Callable[
    [str, Mapping[str, Any], str, str],
    tuple[int, bytes],
]


def run(
    caller_id: str,
    credential: str,
    *,
    transport: Transport = _http_post_once,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    token_hex: Callable[[int], str] = secrets.token_hex,
) -> int:
    orchestrate_posts = 0
    resume_posts = 0
    suffix = token_hex(8)
    trace_id = f"tr_approval_smoke_{suffix}"
    nonce = f"nonce-{suffix}"
    decision_id = f"dec_approval_smoke_{suffix}"

    initial = canonical_orchestrate_body(trace_id=trace_id, nonce=nonce)

    try:
        orchestrate_posts += 1
        status, raw = transport(
            ORCHESTRATE_PATH,
            initial,
            caller_id,
            credential,
        )
    except Exception:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_NETWORK_ORCHESTRATE")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_ORCHESTRATE")
        print(f"ORCHESTRATE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        continuation_ref, pause_id = _classify_pause(
            payload,
            expected_trace_id=trace_id,
        )
    except ValueError:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_NONCANONICAL_PAUSE")
        print("ORCHESTRATE_HTTP=200")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    decided_at = now().astimezone(timezone.utc).isoformat()
    resume_body = canonical_resume_body(
        initial,
        continuation_ref=continuation_ref,
        pause_id=pause_id,
        decision_id=decision_id,
        decided_at=decided_at,
    )

    try:
        resume_posts += 1
        status, raw = transport(
            RESUME_PATH,
            resume_body,
            caller_id,
            credential,
        )
    except Exception:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_NETWORK_RESUME")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_RESUME")
        print(f"RESUME_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        _classify_resume(payload, expected_trace_id=trace_id)
    except ValueError:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=FAIL_NONCANONICAL_RESUME")
        print("RESUME_HTTP=200")
        print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
        print(f"RESUME_POST_COUNT={resume_posts}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("APPROVAL_CONTINUATION_LIVE_SMOKE=PASS")
    print("PAUSE_PRODUCED=PASS")
    print("VERIFIED_APPROVED_RESUME=PASS")
    print("TOOL_COMPLETED=PASS")
    print("PROVIDER_PATH_ENTERED=NO")
    print(f"ORCHESTRATE_POST_COUNT={orchestrate_posts}")
    print(f"RESUME_POST_COUNT={resume_posts}")
    print("NETWORK_RETRY_COUNT=0")
    print("RAW_RESPONSE_OUTPUT=0")
    print("RAW_CONTINUATION_REF_OUTPUT=0")
    print("RAW_PAUSE_ID_OUTPUT=0")
    print("RAW_TRACE_ID_OUTPUT=0")
    print("CALLER_CREDENTIAL_OUTPUT=0")
    print("REAL_USER_DATA=0")
    print("EXTERNAL_SIDE_EFFECTS=0")
    print("CONTINUATION_STORE_MUTATION=BOUNDED_CANONICAL_LIFECYCLE")
    print("PROVIDER_CALLS=0")
    print("MANIFEST_FLIP=0")
    return 0


def main() -> int:
    caller_id = os.environ.get(CALLER_ID_ENV, "")
    credential = os.environ.get(CALLER_SECRET_ENV, "")
    if not caller_id or not credential:
        print("APPROVAL_CONTINUATION_LIVE_SMOKE=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(caller_id, credential)


if __name__ == "__main__":
    raise SystemExit(main())
