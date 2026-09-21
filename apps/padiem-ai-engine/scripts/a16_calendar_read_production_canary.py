"""Bounded one-shot Google Calendar READ canary for Production Engine (#2010).

This runner performs exactly one Engine tool-execution POST and has no network
retry. It never calls Google directly, never prints the raw Engine response,
and never accepts app/agent/tool identifiers from argv or environment.

The canonical Calendar port may retry the provider GET once after a provider 401
by requesting a fresh Control Plane access lease. Therefore the Engine-side
canary budget is one POST, while the provider READ budget is at most two GETs.
The actual provider GET count is intentionally not inferred from the Engine
public response.

The canary reads only ``calendar.list_calendars`` (bounded calendar metadata for
the server-derived allowed calendars). No event content is requested and no
Calendar write/create/update/delete/respond authority exists anywhere in this
module.
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
CREDENTIAL_ENV = "PADIEM_ENGINE_CALENDAR_CANARY_CREDENTIAL"
APP_ID = "b54-padiem-claw-calendar"
AGENT_ID = "agent:padiem:claw_calendar_reader@1"
TOOL_ID = "tool:google:calendar.list@1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESULT_ITEMS = 128
PROVIDER_READ_BUDGET_MAX = 2

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def canonical_request_body() -> dict[str, Any]:
    return {
        "app_id": APP_ID,
        "agent_id": AGENT_ID,
        "tool_id": TOOL_ID,
        "arguments": {},
    }


def _headers(credential: str) -> dict[str, str]:
    if not isinstance(credential, str) or not credential:
        raise ValueError("missing caller credential")
    return {
        "User-Agent": "padiem-calendar-read-canary/1.0 (+github-actions)",
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
    """Return (calendar_count, result_status, engine_output_truncated).

    The calendar metadata list is inspected only for its bounded length; no
    calendar id, name or timezone value is printed or returned. Engine's generic
    redactor deliberately turns secret-shaped fields such as
    ``raw_credentials_present`` into ``[redacted]``, and its node bound can
    replace fields that occur after the calendar list with ``None`` while
    preserving the bounded list length. Those canonical redaction behaviours are
    accepted only when the corresponding truncation fact is consistent.
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
        raise ValueError("missing bounded Calendar output")
    if output.get("provider") != "google_calendar":
        raise ValueError("unexpected provider")
    if output.get("operation") != "calendar.list_calendars":
        raise ValueError("unexpected provider operation")

    result_status = output.get("result_status")
    if result_status == "REVIEW_REQUIRED":
        # Core replaced an oversized projection with a bounded marker instead of
        # leaking provider output. The canary must not accept that as evidence.
        raise ValueError("Calendar projection exceeded the Core tool output bound")
    if result_status != "OK":
        raise ValueError("unexpected Calendar result status")

    calendars = output.get("calendars")
    if not isinstance(calendars, list) or len(calendars) > MAX_RESULT_ITEMS:
        raise ValueError("Calendar result list is not bounded")
    item_count = len(calendars)

    declared_count = output.get("calendar_count")
    if isinstance(declared_count, int) and not isinstance(declared_count, bool):
        if declared_count != item_count:
            raise ValueError("Calendar result count mismatch")
    elif not (output_truncated and declared_count is None):
        raise ValueError("missing Calendar result count")

    for flag in (
        "whole_account_dump",
        "event_content_trusted",
        "oauth_token_present",
        "mints_approval_authority",
        "write_capability_granted",
    ):
        value = output.get(flag)
        if value is False:
            continue
        if output_truncated and value is None:
            continue
        raise ValueError(f"unexpected Calendar safety projection: {flag}")

    credential_projection = output.get("raw_credentials_present")
    if credential_projection not in (False, "[redacted]") and not (
        output_truncated and credential_projection is None
    ):
        raise ValueError("unexpected credential projection")

    if "items" in output:
        raise ValueError("raw provider items unexpectedly present")
    return item_count, result_status, output_truncated


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
        print("CALENDAR_READ_CANARY=FAIL_NETWORK")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("CALENDAR_READ_CANARY=FAIL_ENGINE_RESPONSE")
        print(f"ENGINE_TOOL_EXECUTE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        item_count, result_status, output_truncated = classify_success(payload)
    except ValueError:
        print("CALENDAR_READ_CANARY=FAIL_NONCANONICAL_SUCCESS")
        print("ENGINE_TOOL_EXECUTE_HTTP=200")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("CALENDAR_READ_CANARY=PASS")
    print("ENGINE_TOOL_EXECUTE_HTTP=200")
    print("ENGINE_TOOL_RESULT=PASS")
    print(f"CALENDAR_RESULT_ITEM_COUNT={item_count}")
    print("CALENDAR_RESULT_BOUNDED=YES")
    print(f"CALENDAR_RESULT_STATUS={result_status}")
    print(f"ENGINE_OUTPUT_TRUNCATED={'YES' if output_truncated else 'NO'}")
    print("ACCOUNT_IDENTITY_AMBIGUOUS=YES")
    print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print(f"CALENDAR_PROVIDER_READ_BUDGET_MAX={PROVIDER_READ_BUDGET_MAX}")
    print("CALENDAR_PROVIDER_READ_ACTUAL=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print("RAW_CALENDAR_ID_OUTPUT=0")
    print("RAW_CALENDAR_NAME_OUTPUT=0")
    print("RAW_CALENDAR_TIMEZONE_OUTPUT=0")
    print("RAW_EVENT_ID_OUTPUT=0")
    print("RAW_SUMMARY_OUTPUT=0")
    print("RAW_DESCRIPTION_OUTPUT=0")
    print("RAW_ATTENDEE_OUTPUT=0")
    print("RAW_LOCATION_OUTPUT=0")
    print("RAW_BINDING_REF_OUTPUT=0")
    print("RAW_ACTOR_REF_OUTPUT=0")
    print("PROVIDER_CREDENTIAL_OUTPUT=0")
    print("CALENDAR_WRITE=0")
    print("CALENDAR_CREATE=0")
    print("CALENDAR_UPDATE=0")
    print("CALENDAR_DELETE=0")
    print("CALENDAR_RESPOND=0")
    print("OAUTH_CONNECT=0")
    print("OAUTH_CALLBACK=0")
    print("CALENDAR_ALLOWLIST_MUTATION=0")
    print("CALENDAR_GRANT_SEED=0")
    print("D1_MUTATION=0")
    print("ENGINE_DEPLOY=0")
    print("B14_DEPLOY=0")
    print("SECRET_MUTATION=0")
    return 0


def main() -> int:
    credential = os.environ.get(CREDENTIAL_ENV, "")
    if not credential:
        print("CALENDAR_READ_CANARY=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(credential)


if __name__ == "__main__":
    raise SystemExit(main())
