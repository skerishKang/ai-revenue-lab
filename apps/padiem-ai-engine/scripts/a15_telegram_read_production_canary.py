"""Bounded one-shot Telegram getMe READ canary for Production Engine (#2712).

This runner performs exactly one Engine tool-execution POST and has no
canary-layer network retry. It never calls Telegram directly, never prints the
raw Engine response, and never accepts app/agent/tool identifiers from argv or
environment.

getMe is the least-invasive Telegram surface: it reads only the connected
bot's own bounded projection (bot_id/username/first_name shape only) and
returns no chat, message, or credential content. The canary verifies identity
presence as booleans and structure; no bot_id/username/name value is printed.

The Engine port exposes only the reviewed readonly path, so the Engine-side
canary budget is one POST and the provider READ budget is exactly one GET.
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
CREDENTIAL_ENV = "PADIEM_ENGINE_TELEGRAM_CANARY_CREDENTIAL"
APP_ID = "b54-padiem-claw-telegram"
AGENT_ID = "agent:padiem:claw_telegram_reader@1"
TOOL_ID = "tool:telegram:bot.get_bot_info@1"
REQUEST_TIMEOUT_SECONDS = 60
PROVIDER_READ_BUDGET_MAX = 1

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BOT_ID_RE = re.compile(r"^[0-9]{1,64}$")
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


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
        "arguments": {},
    }


def _headers(credential: str) -> dict[str, str]:
    if not isinstance(credential, str) or not credential:
        raise ValueError("missing caller credential")
    return {
        "User-Agent": "padiem-telegram-read-canary/1.0 (+github-actions)",
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


def _safe_projection_fact(value: Any) -> bool:
    """Engine projection fact survived redaction.

    The public tool-output projection replaces values under secret-shaped keys
    (token/credential/...) with the canonical ``[redacted]`` marker; only a
    non-false value of any other kind is meaningful for the canary.
    """

    return value is False or value == "[redacted]"


def _bot_identity_shape(bot: Mapping[str, Any]) -> bool:
    """Bot identity shape is valid; values are never returned or printed."""
    bot_id = bot.get("bot_id")
    username = bot.get("username")
    first_name = bot.get("first_name")
    if not isinstance(bot_id, str) or _BOT_ID_RE.fullmatch(bot_id) is None:
        return False
    if not isinstance(username, str) or _USERNAME_RE.fullmatch(username.lstrip("@")) is None:
        return False
    if not isinstance(first_name, str) or not first_name.strip() or len(first_name) > 512:
        return False
    if bot.get("is_bot") is not True:
        return False
    if bot.get("personal_account") is not False:
        return False
    if not _safe_projection_fact(bot.get("bot_token_present")):
        return False
    return True


def classify_success(payload: Any) -> tuple[bool, bool]:
    """Return (bot_identity_present, engine_output_truncated)."""
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
        raise ValueError("missing bounded Telegram output")
    if output.get("provider") != "telegram":
        raise ValueError("unexpected provider")
    if output.get("operation") != "telegram.get_bot_info":
        raise ValueError("unexpected provider operation")
    if output.get("result_status") != "OK":
        raise ValueError("unexpected Telegram result status")

    bot = output.get("bot")
    if not isinstance(bot, Mapping) or not _bot_identity_shape(bot):
        raise ValueError("Telegram bot identity projection invalid")

    if output.get("telegram_content_trusted") is not False:
        raise ValueError("unexpected Telegram trust projection")
    if not _safe_projection_fact(output.get("bot_token_present")):
        raise ValueError("unexpected bot token projection")
    if output.get("mints_approval_authority") is not False:
        raise ValueError("unexpected approval authority projection")
    if output.get("write_capability_granted") is not False:
        raise ValueError("unexpected write capability projection")

    credential_projection = output.get("raw_credentials_present")
    if credential_projection not in (False, "[redacted]") and not (
        output_truncated and credential_projection is None
    ):
        raise ValueError("unexpected credential projection")

    forbidden_identity_keys = {
        "projection",
        "chat",
        "chat_id",
        "chat_type",
        "title",
        "messages",
        "message_content_present",
        "updates",
        "webhook",
        "send",
        "edit",
    }
    if forbidden_identity_keys.intersection(output):
        raise ValueError("non-getMe material unexpectedly present in read result")

    return True, output_truncated


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
        print("TELEGRAM_READ_CANARY=FAIL_NETWORK")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    payload = _parse_json(raw)
    if status != 200:
        print("TELEGRAM_READ_CANARY=FAIL_ENGINE_RESPONSE")
        print(f"ENGINE_TOOL_EXECUTE_HTTP={status}")
        print(f"ENGINE_ERROR_CODE={_safe_error_code(payload)}")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    try:
        _, output_truncated = classify_success(payload)
    except ValueError:
        print("TELEGRAM_READ_CANARY=FAIL_NONCANONICAL_SUCCESS")
        print("ENGINE_TOOL_EXECUTE_HTTP=200")
        print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    print("TELEGRAM_READ_CANARY=PASS")
    print("ENGINE_TOOL_EXECUTE_HTTP=200")
    print("ENGINE_TOOL_RESULT=PASS")
    print("TELEGRAM_BOT_IDENTITY_PRESENT=YES")
    print("TELEGRAM_BOT_IDENTITY_VALUE_OUTPUT=0")
    print("TELEGRAM_GETME_BOUNDED=YES")
    print(f"ENGINE_OUTPUT_TRUNCATED={'YES' if output_truncated else 'NO'}")
    print(f"ENGINE_TOOL_EXECUTE_POST_COUNT={post_count}")
    print("NETWORK_RETRY_COUNT=0")
    print(f"TELEGRAM_PROVIDER_READ_BUDGET_MAX={PROVIDER_READ_BUDGET_MAX}")
    print("TELEGRAM_PROVIDER_READ_ACTUAL=UNOBSERVABLE_FROM_ENGINE_BOUNDARY")
    print("RAW_BOT_ID_OUTPUT=0")
    print("RAW_BOT_USERNAME_OUTPUT=0")
    print("RAW_BOT_NAME_OUTPUT=0")
    print("RAW_CHAT_ID_OUTPUT=0")
    print("RAW_BINDING_REF_OUTPUT=0")
    print("RAW_ACTOR_REF_OUTPUT=0")
    print("PROVIDER_CREDENTIAL_OUTPUT=0")
    print("TELEGRAM_SEND=0")
    print("TELEGRAM_EDIT=0")
    print("TELEGRAM_CALLBACK_WRITE=0")
    print("WEBHOOK_MUTATION=0")
    print("TELEGRAM_GRANT_SEED=0")
    print("D1_MUTATION=0")
    print("ENGINE_DEPLOY=0")
    print("SECRET_MUTATION=0")
    return 0


def main() -> int:
    credential = os.environ.get(CREDENTIAL_ENV, "")
    if not credential:
        print("TELEGRAM_READ_CANARY=SKIPPED_MISSING_CREDENTIAL", file=sys.stderr)
        return 1
    return run(credential)


if __name__ == "__main__":
    raise SystemExit(main())
