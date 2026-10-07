"""Bounded one-shot Slack conversations.list READ canary for Production Engine (#2951).

This runner performs exactly one Engine tool-execution POST and has no network
retry. It never calls Slack directly, never prints the raw Engine response, and
never accepts app/agent/tool identifiers from argv or environment.

``conversations.list`` (canonical id ``tool:slack:channel.list@1``) is the least
invasive Slack READ surface available to the canonical grant: it returns bounded
metadata only for the server-derived allowed channels (channel id, name and
privacy flags) and never returns message, thread, user, file or credential
content. The canary inspects the result only for its bounded length and count
consistency; no channel id, name or privacy value is printed or returned.

Slack's Web API is POST-based, and the canonical Slack port
(``app/slack_port_httpx.py``) performs exactly one provider POST per tool
execution with no provider retry, so the Engine-side canary budget is one POST
and the provider READ budget is at most one POST, capped by the port's own
1 MB response bound. The actual provider POST count is intentionally not
inferred from the Engine public response.
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
CREDENTIAL_ENV = "PADIEM_ENGINE_SLACK_CANARY_CREDENTIAL"
APP_ID = "b54-padiem-claw-slack"
AGENT_ID = "agent:padiem:claw_slack_reader@1"
TOOL_ID = "tool:slack:channel.list@1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESULT_ITEMS = 128
PROVIDER_READ_BUDGET_MAX = 1
SLACK_PROVIDER_RESPONSE_BYTES_MAX = 1_000_000

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
        "User-Agent": "padiem-slack-read-canary/1.0 (+github-actions)",
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
    """Return (channel_count, result_status, engine_output_truncated).

    The channel metadata list is inspected only for its bounded length; no
    channel id, name or privacy value is printed or returned. Engine's generic
    redactor deliberately turns secret-shaped fields such as
    ``bot_token_present`` into ``[redacted]``, and its node bound can replace
    fields that occur after the channel list with ``None`` while preserving the
    bounded list length. Those canonical redaction behaviours are accepted only
    when the corresponding truncation fact is consistent.
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
        raise ValueError("missing bounded Slack output")
    if output.get("provider") != "slack":
        raise ValueError("unexpected provider")
    if output.get("operation") != "slack.list_channels":
        raise ValueError("unexpected provider operation")

    result_status = output.get("result_status")
    if result_status == "REVIEW_REQUIRED":
        # Core replaced an oversized projection with a bounded marker instead of
        # leaking provider output. The canary must not accept that as evidence.
        raise ValueError("Slack projection exceeded the Core tool output bound")
    if result_status != "OK":
        raise ValueError("unexpected Slack result status")

    channels = output.get("channels")
    if not isinstance(channels, list) or len(channels) > MAX_RESULT_ITEMS:
        raise ValueError("Slack channel result list is not bounded")
    item_count = len(channels)

    declared_count = output.get("channel_count")
    if isinstance(declared_count, int) and not isinstance(declared_count, bool):
        if declared_count != item_count:
            raise ValueError("Slack channel result count mismatch")
    elif not (output_truncated and declared_count is None):
        raise ValueError("missing Slack channel count")

    for flag in (
        "whole_workspace_dump",
        "private_channel_access_implicit",
        "slack_content_trusted",
        "mints_approval_authority",
        "write_capability_granted",
    ):
        value = output.get(flag)
        if value is False:
            continue
        if output_truncated and value is None:
            continue
        raise ValueError(f"unexpected Slack safety projection: {flag}")

    credential_projection = output.get("bot_token_present")
    if credential_projection not in (False, "[redacted]") and not (
        output_truncated and credential_projection is None
    ):
        raise ValueError("unexpected bot token projection")

    forbidden_identity_keys = {
        "messages",
        "message_count",
        "message_content_present",
        "history",
        "replies",
        "reply_count",
        "thread_ts",
        "users",
        "files",
        "workspace",
        "team_id",
        "team_name",
        "bot_user_id",
        "send",
        "post",
        "webhook",
        "events",
    }
    if forbidden_identity_keys.intersection(output):
        raise ValueError("non-conversations.list material unexpectedly present in read result")
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
        print("SLACK_READ_LIVE_CANARY=FAIL_NETWORK")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("SLACK_READ_LIVE_CANARY=FAIL_ENGINE_RESPONSE")
        print(f"ENGINE_TOOL_EXECUTE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        item_count, result_status, output_truncated = classify_success(payload)
    except ValueError:
        print("SLACK_READ_LIVE_CANARY=FAIL_NONCANONICAL_SUCCESS")
        print("ENGINE_TOOL_EXECUTE_HTTP=200")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("SLACK_READ_LIVE_CANARY=PASS")
    print("ENGINE_TOOL_EXECUTE_HTTP=200")
    print("ENGINE_TOOL_RESULT=PASS")
    print(f"SLACK_RESULT_ITEM_COUNT={item_count}")
    print("SLACK_RESULT_BOUNDED=YES")
    print(f"SLACK_RESULT_STATUS={result_status}")
    print(f"ENGINE_OUTPUT_TRUNCATED={'YES' if output_truncated else 'NO'}")
    print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print("LIVE_PROVIDER_CALLS=1")
    print("REAL_PROVIDER_CALLS=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print(f"SLACK_PROVIDER_READ_BUDGET_MAX={PROVIDER_READ_BUDGET_MAX}")
    print("SLACK_PROVIDER_READ_ACTUAL=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print(f"SLACK_PROVIDER_RESPONSE_BYTES_MAX={SLACK_PROVIDER_RESPONSE_BYTES_MAX}")
    print("SLACK_CONVERSATIONS_LIST_BOUNDED=YES")
    print("RAW_CHANNEL_ID_OUTPUT=0")
    print("RAW_CHANNEL_NAME_OUTPUT=0")
    print("RAW_CHANNEL_PRIVACY_OUTPUT=0")
    print("RAW_MESSAGE_OUTPUT=0")
    print("RAW_USER_OUTPUT=0")
    print("RAW_FILE_OUTPUT=0")
    print("RAW_TEAM_ID_OUTPUT=0")
    print("RAW_BOT_TOKEN_OUTPUT=0")
    print("RAW_BINDING_REF_OUTPUT=0")
    print("RAW_ACTOR_REF_OUTPUT=0")
    print("PROVIDER_CREDENTIAL_OUTPUT=0")
    print("SLACK_SEND=0")
    print("SLACK_POST_MESSAGE=0")
    print("SLACK_REPLY_THREAD=0")
    print("SLACK_UPDATE_MESSAGE=0")
    print("SLACK_UPLOAD_FILE=0")
    print("SLACK_WRITE=0")
    print("SLACK_EVENTS_INGRESS=0")
    print("WEBHOOK_MUTATION=0")
    print("SLACK_BOT_TOKEN_PROVISIONING=0")
    print("SLACK_ALLOWED_CHANNEL_CONFIG=0")
    print("SLACK_GRANT_SEED=0")
    print("D1_MUTATION=0")
    print("ENGINE_DEPLOY=0")
    print("B14_DEPLOY=0")
    print("SECRET_MUTATION=0")
    return 0


def main() -> int:
    credential = os.environ.get(CREDENTIAL_ENV, "")
    if not credential:
        print("SLACK_READ_LIVE_CANARY=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(credential)


if __name__ == "__main__":
    raise SystemExit(main())
