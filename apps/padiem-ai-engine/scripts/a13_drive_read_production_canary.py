"""Bounded one-shot Google Drive READ canary for Production Engine (#2648).

This runner performs exactly one Engine tool-execution POST and has no network
retry. It never calls Google directly, never prints the raw Engine response,
and never accepts app/agent/tool identifiers from argv or environment.

The canonical Drive port may retry the provider GET once after a provider 401 by
requesting a fresh Control Plane access lease. Therefore the Engine-side canary
budget is one POST, while the provider READ budget is at most two GETs. The
actual provider GET count is intentionally not inferred from the Engine public
response.
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
CREDENTIAL_ENV = "PADIEM_ENGINE_DRIVE_CANARY_CREDENTIAL"
APP_ID = "b54-padiem-claw-drive"
AGENT_ID = "agent:padiem:claw_drive_reader@1"
TOOL_ID = "tool:google:drive.list_recent_files@1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESULT_ITEMS = 25
PROVIDER_READ_BUDGET_MAX = 2

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
        "User-Agent": "padiem-drive-read-canary/1.0 (+github-actions)",
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

    The file metadata list is inspected only for its bounded length; no file
    value is printed or returned. Engine's generic redactor deliberately turns
    secret-shaped fields such as ``raw_credentials_present`` into ``[redacted]``.
    Its node bound can also replace fields that occur after the file list with
    ``None`` while preserving the bounded file-list length. Those two canonical
    redaction behaviours are accepted only when their corresponding truncation
    facts are consistent.
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
        raise ValueError("missing bounded Drive output")
    if output.get("provider") != "google_drive" or output.get("operation") != "files.list.recent":
        raise ValueError("unexpected provider operation")
    if output.get("result_status") not in {"OK", "UNKNOWN", "REVIEW_REQUIRED"}:
        raise ValueError("unexpected Drive result status")

    files = output.get("files")
    if not isinstance(files, list) or len(files) > MAX_RESULT_ITEMS:
        raise ValueError("Drive result list is not bounded")
    item_count = len(files)

    declared_count = output.get("result_count")
    if isinstance(declared_count, int) and not isinstance(declared_count, bool):
        if declared_count != item_count:
            raise ValueError("Drive result count mismatch")
    elif not (output_truncated and declared_count is None):
        raise ValueError("missing Drive result count")

    more = output.get("more_results_available")
    if isinstance(more, bool):
        pagination_state = "YES" if more else "NO"
    elif output_truncated and more is None:
        pagination_state = "UNKNOWN_DUE_TO_ENGINE_BOUND"
    else:
        raise ValueError("missing pagination fact")

    page_followed = output.get("page_followed")
    if page_followed is not False and not (output_truncated and page_followed is None):
        raise ValueError("unexpected pagination follow")

    credential_projection = output.get("raw_credentials_present")
    if credential_projection not in (False, "[redacted]") and not (
        output_truncated and credential_projection is None
    ):
        raise ValueError("unexpected credential projection")
    if "content" in output:
        raise ValueError("content unexpectedly present in list result")
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
        print("DRIVE_READ_CANARY=FAIL_NETWORK")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("DRIVE_READ_CANARY=FAIL_ENGINE_RESPONSE")
        print(f"ENGINE_TOOL_EXECUTE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        item_count, pagination_state, output_truncated = classify_success(payload)
    except ValueError:
        print("DRIVE_READ_CANARY=FAIL_NONCANONICAL_SUCCESS")
        print("ENGINE_TOOL_EXECUTE_HTTP=200")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("DRIVE_READ_CANARY=PASS")
    print("ENGINE_TOOL_EXECUTE_HTTP=200")
    print("ENGINE_TOOL_RESULT=PASS")
    print(f"DRIVE_RESULT_ITEM_COUNT={item_count}")
    print("DRIVE_RESULT_BOUNDED=YES")
    print(f"DRIVE_MORE_RESULTS_AVAILABLE={pagination_state}")
    print(f"ENGINE_OUTPUT_TRUNCATED={'YES' if output_truncated else 'NO'}")
    print("ACCOUNT_IDENTITY_AMBIGUOUS=YES")
    print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print(f"DRIVE_PROVIDER_READ_BUDGET_MAX={PROVIDER_READ_BUDGET_MAX}")
    print("DRIVE_PROVIDER_READ_ACTUAL=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print("RAW_FILENAME_OUTPUT=0")
    print("RAW_FILE_ID_OUTPUT=0")
    print("RAW_OWNER_OUTPUT=0")
    print("RAW_LINK_OUTPUT=0")
    print("RAW_FILE_CONTENT_OUTPUT=0")
    print("RAW_BINDING_REF_OUTPUT=0")
    print("RAW_ACTOR_REF_OUTPUT=0")
    print("PROVIDER_CREDENTIAL_OUTPUT=0")
    print("DRIVE_WRITE=0")
    print("OAUTH_CONNECT=0")
    print("OAUTH_CALLBACK=0")
    print("DRIVE_GRANT_SEED=0")
    print("D1_MUTATION=0")
    print("ENGINE_DEPLOY=0")
    print("SECRET_MUTATION=0")
    return 0


def main() -> int:
    credential = os.environ.get(CREDENTIAL_ENV, "")
    if not credential:
        print("DRIVE_READ_CANARY=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(credential)


if __name__ == "__main__":
    raise SystemExit(main())
