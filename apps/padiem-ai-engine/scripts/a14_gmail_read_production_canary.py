"""Bounded one-shot Gmail READ canary for Production Engine.

This runner performs exactly one Engine tool-execution POST and has no
canary-layer network retry. It never calls Gmail directly, never prints the raw
Engine response, and never accepts app/agent/tool identifiers from argv or
environment.

The canonical Gmail port may retry the provider GET once after a provider 401
by requesting a fresh Control Plane access lease. Therefore the Engine-side
canary budget is one POST, while the Gmail provider READ budget is at most two
GETs. The actual provider GET count is intentionally not inferred from the
Engine public response.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

ENGINE_BASE_URL = "https://engine.padiem.net"
TOOL_EXECUTE_PATH = "/internal/v1/tools/execute"
CALLER_ID = "b54-p01-overlay-20260914-a1"
CREDENTIAL_ENV = "PADIEM_ENGINE_GMAIL_CANARY_CREDENTIAL"
APP_ID = "b54-padiem-claw"
AGENT_ID = "agent:padiem:claw_mail_reader@1"
TOOL_ID = "tool:google:gmail.search_messages@1"
CANARY_QUERY = 'subject:"__PADIEM_GMAIL_READ_CANARY_NONMATCH_20260919__"'
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESULT_ITEMS = 10
PROVIDER_READ_BUDGET_MAX = 2

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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


def canonical_request_body() -> dict[str, Any]:
    return {
        "app_id": APP_ID,
        "agent_id": AGENT_ID,
        "tool_id": TOOL_ID,
        "arguments": {"query": CANARY_QUERY},
    }


def _headers(credential: str) -> dict[str, str]:
    if not isinstance(credential, str) or not credential:
        raise ValueError("missing caller credential")
    return {
        "User-Agent": "padiem-gmail-read-canary/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": credential,
        "Content-Type": "application/json",
    }


def _http_post_once(body: dict[str, Any], credential: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"{ENGINE_BASE_URL}{TOOL_EXECUTE_PATH}",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers=_headers(credential),
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


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


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def classify_success(payload: Any) -> tuple[int, str, bool]:
    """Return (item_count, pagination_state, engine_output_truncated).

    Message/thread references are inspected only for type/bounds and are never
    printed or returned. Search is the least-invasive Gmail READ surface: it
    does not fetch message bodies or attachments.
    """
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise ValueError("noncanonical success envelope")
    tool = payload.get("tool")
    if not isinstance(tool, Mapping):
        raise ValueError("missing tool envelope")
    if tool.get("status") != "completed" or tool.get("canonical_tool_id") != TOOL_ID:
        raise ValueError("unexpected tool identity or state")

    output_truncated = tool.get("output_truncated")
    if not isinstance(output_truncated, bool):
        raise ValueError("missing output truncation fact")

    output = tool.get("output")
    if not isinstance(output, Mapping):
        raise ValueError("missing bounded Gmail output")
    if output.get("provider") != "gmail" or output.get("operation") != "messages.list":
        raise ValueError("unexpected provider operation")
    if output.get("query") != CANARY_QUERY:
        raise ValueError("unexpected Gmail search query")
    if output.get("result_status") not in {"OK", "UNKNOWN", "REVIEW_REQUIRED"}:
        raise ValueError("unexpected Gmail result status")

    messages = output.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_RESULT_ITEMS:
        raise ValueError("Gmail result list is not bounded")
    for item in messages:
        if not isinstance(item, Mapping):
            raise ValueError("Gmail result item is not an object")
        if set(item) - {"message_id", "thread_id"}:
            raise ValueError("Gmail search result contains unexpected fields")
        message_id = item.get("message_id")
        thread_id = item.get("thread_id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("Gmail message reference is invalid")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Gmail thread reference is invalid")

    item_count = len(messages)
    declared_count = output.get("result_count")
    if isinstance(declared_count, int) and not isinstance(declared_count, bool):
        if declared_count != item_count:
            raise ValueError("Gmail result count mismatch")
    elif not (output_truncated and declared_count is None):
        raise ValueError("missing Gmail result count")

    more = output.get("more_results_available")
    if isinstance(more, bool):
        pagination_state = "YES" if more else "NO"
    elif output_truncated and more is None:
        pagination_state = "UNKNOWN_DUE_TO_ENGINE_BOUND"
    else:
        raise ValueError("missing Gmail pagination fact")

    page_followed = output.get("page_followed")
    if page_followed is not False and not (output_truncated and page_followed is None):
        raise ValueError("unexpected pagination follow")

    content_trusted = output.get("mail_content_trusted")
    if content_trusted is not False and not (output_truncated and content_trusted is None):
        raise ValueError("unexpected Gmail trust projection")

    credential_projection = output.get("raw_credentials_present")
    if credential_projection not in (False, "[redacted]") and not (
        output_truncated and credential_projection is None
    ):
        raise ValueError("unexpected credential projection")

    forbidden_content_keys = {
        "projection",
        "body",
        "body_segments",
        "subject",
        "from_address",
        "to_addresses",
        "attachments",
        "filename",
        "raw_attachment_bytes_present",
    }
    if forbidden_content_keys.intersection(output):
        raise ValueError("message content unexpectedly present in search result")

    return item_count, pagination_state, output_truncated


def run(
    credential: str,
    *,
    transport: Callable[[dict[str, Any], str], tuple[int, bytes]] = _http_post_once,
) -> int:
    post_count = 0
    try:
        body = canonical_request_body()
        post_count += 1
        status, raw = transport(body, credential)
    except Exception:
        print("GMAIL_READ_CANARY=FAIL_NETWORK")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("GMAIL_READ_CANARY=FAIL_ENGINE_RESPONSE")
        print(f"ENGINE_TOOL_EXECUTE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        item_count, pagination_state, output_truncated = classify_success(payload)
    except ValueError:
        print("GMAIL_READ_CANARY=FAIL_NONCANONICAL_SUCCESS")
        print("ENGINE_TOOL_EXECUTE_HTTP=200")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("GMAIL_READ_CANARY=PASS")
    print("ENGINE_TOOL_EXECUTE_HTTP=200")
    print("ENGINE_TOOL_RESULT=PASS")
    print(f"GMAIL_RESULT_ITEM_COUNT={item_count}")
    print("GMAIL_RESULT_BOUNDED=YES")
    print(f"GMAIL_MORE_RESULTS_AVAILABLE={pagination_state}")
    print(f"ENGINE_OUTPUT_TRUNCATED={'YES' if output_truncated else 'NO'}")
    print("ACCOUNT_IDENTITY_AMBIGUOUS=YES")
    print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print(f"GMAIL_PROVIDER_READ_BUDGET_MAX={PROVIDER_READ_BUDGET_MAX}")
    print("GMAIL_PROVIDER_READ_ACTUAL=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print("RAW_MESSAGE_ID_OUTPUT=0")
    print("RAW_THREAD_ID_OUTPUT=0")
    print("RAW_SUBJECT_OUTPUT=0")
    print("RAW_FROM_OUTPUT=0")
    print("RAW_TO_OUTPUT=0")
    print("RAW_BODY_OUTPUT=0")
    print("RAW_ATTACHMENT_OUTPUT=0")
    print("RAW_BINDING_REF_OUTPUT=0")
    print("RAW_ACTOR_REF_OUTPUT=0")
    print("PROVIDER_CREDENTIAL_OUTPUT=0")
    print("GMAIL_WRITE=0")
    print("GMAIL_DRAFT=0")
    print("GMAIL_SEND=0")
    print("OAUTH_CONNECT=0")
    print("OAUTH_CALLBACK=0")
    print("GMAIL_GRANT_SEED=0")
    print("D1_MUTATION=0")
    print("ENGINE_DEPLOY=0")
    print("B14_DEPLOY=0")
    print("SECRET_MUTATION=0")
    return 0


def main() -> int:
    credential = os.environ.get(CREDENTIAL_ENV, "")
    if not credential:
        print("GMAIL_READ_CANARY=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(credential)


if __name__ == "__main__":
    raise SystemExit(main())
