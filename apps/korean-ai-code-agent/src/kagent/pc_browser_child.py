"""#3782 — one PC browser step as a child process (JSON in, JSON out).

The Windows resident already runs bounded child programs for document work.
This is the browser lane's equivalent: the parent passes exactly one request on
stdin and receives exactly one JSON document on stdout. Nothing else is read
from the console, so a Korean page title or a browser warning on stderr cannot
corrupt the answer.

Request:  {"tool_id": "claw.pc.browser_open", "arguments": {...}}
Answer:   {"ok": true, "result": {...}}  or  {"ok": false, "code": ...}
"""
from __future__ import annotations

import json
import sys
import uuid

from .contracts import ContractError
from .pc_browser_tools import (
    BROWSER_ACT_TOOL_ID,
    BROWSER_OPEN_TOOL_ID,
    BROWSER_READ_TOOL_ID,
    BROWSER_SCREENSHOT_TOOL_ID,
    PcBrowserError,
    PcBrowserSession,
    read_stored,
    validate_arguments,
)


def _refused(code: str) -> dict[str, str]:
    return {"ok": "false", "code": code}


def run(request: object, *, session: PcBrowserSession | None = None) -> dict[str, object]:
    if not isinstance(request, dict):
        return _refused("browser_internal_error")
    tool_id = request.get("tool_id")
    arguments = request.get("arguments", {})
    owns_session = session is None
    active = session or PcBrowserSession()
    try:
        if tool_id == "claw.pc.browser_read_output":
            data = validate_arguments(BROWSER_OPEN_TOOL_ID, {})
            del data
            return {"ok": "true", "result": read_stored(
                str(arguments.get("handle", "")),
                int(arguments.get("offset", 0)),
                int(arguments.get("length", 0)),
            )}
        data = validate_arguments(str(tool_id), arguments)
        if tool_id == BROWSER_OPEN_TOOL_ID:
            result = active.open(str(data.get("url", "")))
        elif tool_id == BROWSER_READ_TOOL_ID:
            result = active.read()
        elif tool_id == BROWSER_SCREENSHOT_TOOL_ID:
            result = active.screenshot()
        elif tool_id == BROWSER_ACT_TOOL_ID:
            result = active.act(
                action=str(data.get("action", "")),
                text=data.get("text"),
                role=data.get("role"),
                name=data.get("name"),
                value=data.get("value"),
            )
        else:
            return _refused("browser_action_unsupported")
        return {"ok": "true", "result": result}
    except PcBrowserError as exc:
        return _refused(exc.code)
    except (ContractError, ValueError, TypeError):
        return _refused("browser_internal_error")
    finally:
        if owns_session:
            active.close()


def main(argv: list[str] | None = None) -> int:
    del argv
    raw = sys.stdin.read(1_000_000)
    request_id = uuid.uuid4().hex
    try:
        request = json.loads(raw) if raw.strip() else {}
    except ValueError:
        request = None
    answer = run(request)
    answer["request_id"] = request_id
    sys.stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
    sys.stdout.flush()
    return 0 if answer.get("ok") == "true" else 1


if __name__ == "__main__":
    raise SystemExit(main())