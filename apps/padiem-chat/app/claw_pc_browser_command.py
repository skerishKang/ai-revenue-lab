"""#3782 PC browser lane: one browser step as a single-line console command.

The Owner's decision on #3782 was a **dedicated lane**. The file lane keeps its
seven ops and its granted-root resolution; the browser never borrows either and
adds nothing to ``_PC_FILES_OPS``. A browser step is dispatched on its own signed
endpoint and carries exactly one of four ops:

    browser_open        open one public URL in the work profile
    browser_read        title / body text / links of the page
    browser_screenshot  exactly one capture, saved on the PC
    browser_act         one click or type by visible text or role+name

The command is ONE line, for the reason already measured on these machines and
written down in the file write step: the connected PC serves one console script
through stdin, and a script carrying a newline never completes there. The JSON
request is base64 so a page URL, a quote or a Korean title can never change what
the PC receives, and the PC's answer is the child's own single JSON document.

No cookie, password, ``localStorage`` value or script has a field here: the
request is a closed shape, and anything else is refused before a command exists.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from padiem_ai_core.web_runtime import normalize_public_url

#: The closed op set of this lane. These four words never appear in the file
#: lane's op set, so a claim that admits one lane cannot address the other.
PC_BROWSER_OPS = (
    "browser_open",
    "browser_read",
    "browser_screenshot",
    "browser_act",
)
PC_BROWSER_CLAIMED_OPS = frozenset(PC_BROWSER_OPS)
PC_BROWSER_MAX_URL_CHARS = 2048
PC_BROWSER_MAX_ARGUMENT_CHARS = 4096
#: The child is `kagent.pc_browser_child`: the same reviewed import path the
#: document parser child uses, so the module resolves on a paired PC.
PC_BROWSER_CHILD_MODULE = "kagent.pc_browser_child"

#: Which keys each op may carry. `browser_open` takes the URL; a read or a
#: capture takes nothing; `browser_act` takes the one action it may perform.
_OP_KEYS = {
    "browser_open": frozenset({"url"}),
    "browser_read": frozenset(),
    "browser_screenshot": frozenset(),
    "browser_act": frozenset({"action", "text", "role", "name", "value"}),
}


class PcBrowserCommandError(ValueError):
    """A refused browser step; the caller answers with a bounded code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ps_literal(value: str) -> str:
    """One single-quoted PowerShell literal; the only escape is a doubled quote."""
    return "'" + value.replace("'", "''") + "'"


def _public_url(value: Any) -> str:
    """The canonical public-URL contract decides; this lane never re-implements it.

    Loopback, private, ``file:`` and ``javascript:`` addresses are refused by
    ``padiem_ai_core.web_runtime.normalize_public_url``, the same authority the
    PC browser tools already use, so the two can never disagree.
    """
    if not isinstance(value, str) or not value or len(value) > PC_BROWSER_MAX_URL_CHARS:
        raise PcBrowserCommandError("browser_url_invalid", "A public page address is required")
    try:
        return normalize_public_url(value)
    except ValueError as exc:
        raise PcBrowserCommandError(
            "browser_url_invalid", "A public page address is required",
        ) from exc


def browser_arguments(op: Any, arguments: Any) -> dict[str, str]:
    """The closed argument shape of one op, or a refusal.

    ``None`` stands for "no arguments". Nothing else may reach the PC: an
    unknown key is refused rather than dropped, so a cookie or a script cannot
    be smuggled beside a real argument.
    """
    if op not in _OP_KEYS:
        raise PcBrowserCommandError("browser_action_unsupported", "Unknown browser op")
    if arguments is None:
        data: dict[str, Any] = {}
    elif isinstance(arguments, dict):
        data = dict(arguments)
    else:
        raise PcBrowserCommandError("browser_action_unsupported", "Browser arguments are invalid")
    if set(data) != _OP_KEYS[op]:
        # `browser_act` names a subset: a click needs no value, a type does.
        if not (op == "browser_act" and set(data) <= _OP_KEYS[op]):
            raise PcBrowserCommandError("browser_action_unsupported", "Browser arguments are invalid")
    for key, value in data.items():
        if value is None:
            data.pop(key)
            continue
        if not isinstance(value, str):
            raise PcBrowserCommandError("browser_action_unsupported", "Browser arguments are invalid")
        if key != "value" and not value:
            raise PcBrowserCommandError("browser_action_unsupported", "Browser arguments are invalid")
        if len(value) > PC_BROWSER_MAX_ARGUMENT_CHARS:
            raise PcBrowserCommandError("browser_action_unsupported", "Browser arguments are invalid")
    if op == "browser_open":
        data["url"] = _public_url(data.get("url"))
    if op == "browser_act":
        if data.get("action") not in {"click", "type"}:
            raise PcBrowserCommandError("browser_action_unsupported", "Only click and type are supported")
        if not (data.get("text") or data.get("name")):
            raise PcBrowserCommandError(
                "browser_action_unsupported", "A visible text or a role and name is required",
            )
        if data["action"] == "type" and not data.get("value"):
            raise PcBrowserCommandError("browser_action_unsupported", "Typing needs the text to enter")
    return {key: value for key, value in data.items() if isinstance(value, str)}


def browser_envelope(op: str, *, page_url: str | None, arguments: dict[str, str] | None = None) -> dict[str, Any]:
    """The one JSON document the PC child reads.

    ``page_url`` is server-derived, never model text: the Engine remembers the
    page its own ``browser_open`` returned, so a read, a capture or an act lands
    on that page even though every step is its own console process.
    """
    if op not in PC_BROWSER_OPS:
        raise PcBrowserCommandError("browser_action_unsupported", "Unknown browser op")
    data = browser_arguments(op, arguments)
    envelope: dict[str, Any] = {"tool_id": "claw.pc." + op, "arguments": data}
    if op == "browser_open":
        # The open op carries its own address; no remembered page is involved.
        envelope.pop("url", None)
    else:
        if page_url is None:
            raise PcBrowserCommandError(
                "browser_not_running", "No page is open on this PC yet",
            )
        envelope["url"] = _public_url(page_url)
    return envelope


def pc_browser_command(op: str, *, page_url: str | None = None,
                       arguments: dict[str, str] | None = None) -> str:
    """Build the one-line browser step for the paired PC.

    The shape mirrors the review-parser step already proven on these machines:
    find the interpreter, feed it one JSON document on stdin, keep the child's
    own answer. The request rides as base64 so no quoting rule can alter it.
    """
    envelope = browser_envelope(op, page_url=page_url, arguments=arguments)
    encoded = base64.b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    ).decode("ascii")
    unavailable = json.dumps({"ok": "false", "code": "browser_unavailable"})
    not_running = json.dumps({"ok": "false", "code": "browser_not_running"})
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        "$py=Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1;"
        "if($py -eq $null){" + _ps_literal(unavailable) + "}"
        "else{"
        "$req=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(" + _ps_literal(encoded) + "));"
        "$out=@($req | & $py.Source -P -m " + PC_BROWSER_CHILD_MODULE + " 2>$null);"
        "if($out -eq $null){" + _ps_literal(not_running) + "}else{($out -join '')}"
        "}"
    )


def browser_scope_claim(claim: Any) -> bool:
    """Whether a signed claim admits the browser lane and nothing else.

    The lane is its own ceiling: the admitted scope must be ``browser`` and every
    named op must be one of the four browser ops. A files claim can never reach
    this lane, and a browser claim can never reach a file.
    """
    if not isinstance(claim, dict):
        return False
    if set(claim) != {"version", "requested", "admitted", "source", "ops"}:
        return False
    if type(claim["version"]) is not int or claim["version"] != 1:
        return False
    if claim["requested"] != "browser" or claim["admitted"] != "browser":
        return False
    if claim["source"] not in ("declared", "decision"):
        return False
    ops = claim["ops"]
    if not isinstance(ops, list) or not ops or len(set(ops)) != len(ops):
        return False
    return all(isinstance(op, str) and op in PC_BROWSER_CLAIMED_OPS for op in ops)


__all__ = [
    "PC_BROWSER_CLAIMED_OPS",
    "PC_BROWSER_OPS",
    "PcBrowserCommandError",
    "browser_arguments",
    "browser_envelope",
    "browser_scope_claim",
    "pc_browser_command",
]
