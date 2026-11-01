"""#3782 step 1 — the PC browser-use lane executed on the connected PC.

Four bounded tools the web model may select. The PC executes them through the
pinned Playwright MCP server as a *private child process*; the general MCP
catalogue is never forwarded to a model, and no second agent loop or model
router exists here (B14 stays the only model selector).

    claw.pc.browser_open        open one public URL in the work profile
    claw.pc.browser_read        title / body text / links of the current page
    claw.pc.browser_screenshot  exactly one screenshot, saved on the PC
    claw.pc.browser_act         click or type by visible text or role+name

Authority boundary:

* the URL policy is the canonical public-URL contract
  (``padiem_ai_core.web_runtime.normalize_public_url``) — this module does not
  re-implement or weaken it;
* the browser profile is a dedicated work profile. The representative's own
  Chrome profile is never attached, and cookies, passwords, ``localStorage``
  and form values are refused by construction (no field exists for them);
* ``javascript_evaluate``, file upload/download, multi-tab switching and raw
  DOM export are not in the action vocabulary;
* login, payment, posting, sending and submitting are **not executed**. The
  tool returns ``needs_confirmation`` with a plain question so the ordinary
  conversation asks first.

Large output: page text above the inline budget is stored under a handle and
returned with ``read_output`` compatible bounds, so a long page never has to
fit into one model turn.
"""

from __future__ import annotations

from collections.abc import Mapping
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urljoin
import uuid

from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.web_runtime import normalize_public_url

PREFIX = "claw.pc."
BROWSER_OPEN_TOOL_ID = PREFIX + "browser_open"
BROWSER_READ_TOOL_ID = PREFIX + "browser_read"
BROWSER_SCREENSHOT_TOOL_ID = PREFIX + "browser_screenshot"
BROWSER_ACT_TOOL_ID = PREFIX + "browser_act"

BROWSER_TOOL_IDS = frozenset({
    BROWSER_OPEN_TOOL_ID, BROWSER_READ_TOOL_ID,
    BROWSER_SCREENSHOT_TOOL_ID, BROWSER_ACT_TOOL_ID,
})
BROWSER_CANONICAL_IDS = {
    tool_id: "tool:padiem:" + tool_id.removeprefix(PREFIX).replace("_", "-") + "@1"
    for tool_id in BROWSER_TOOL_IDS
}

MCP_PACKAGE = "@playwright/mcp@0.0.83"
MCP_PROTOCOL_VERSION = "2024-11-05"
MAX_INLINE_TEXT = 8192
MAX_LINKS = 50
MCP_CALL_TIMEOUT_SECONDS = 120
_PROFILE_DIR_NAME = "browser-work-profile"

#: Actions whose effect leaves the machine or cannot be undone. They are
#: reported back as a question instead of being executed.
CONFIRM_NAME_PATTERNS = (
    "login", "log in", "sign in", "signin", "로그인",
    "payment", "pay", "checkout", "purchase", "buy", "결제", "구매",
    "post", "publish", "게시", "올리기", "등록",
    "send", "submit", "보내기", "발송", "전송", "제출",
    "delete", "remove", "삭제",
)
_CONFIRM_RE = re.compile("|".join(re.escape(word) for word in CONFIRM_NAME_PATTERNS), re.IGNORECASE)
_SECRET_TARGET_RE = re.compile(
    r"password|passphrase|비밀번호|암호|cookie|쿠키|localstorage|"
    r"\b(?:access[ _-]*|session[ _-]*|bearer[ _-]*|auth[ _-]*)?token\b|토큰|"
    r"\bapi[ _-]*key\b|API\s*키", re.IGNORECASE,
)
_SNAPSHOT_LINE = re.compile(
    r"^\s*-\s*(?P<role>[\w-]+)"
    r"(?:\s+\"(?P<name>[^\"]*)\")?"
    r".*?\[ref=(?P<ref>e\d+)\]"
    r"(?:\s+\[[^\]]*\])*"
    r"(?::\s*(?P<text>.*))?$"
)
_PAGE_TITLE = re.compile(r"^-\s*Page Title:\s*(?P<title>.+?)\s*$", re.MULTILINE)
_PAGE_URL = re.compile(r"^-\s*Page URL:\s*(?P<url>\S+)\s*$", re.MULTILINE)
_URL_LINE = re.compile(r"^\s*-\s*/url:\s*(?P<url>\S+)\s*$")
_HANDLE = re.compile(r"^[0-9a-f]{64}$")


class PcBrowserError(RuntimeError):
    """A refused or failed PC browser step with a closed diagnostic code."""

    CODES = frozenset({
        "browser_unavailable", "browser_not_running", "browser_url_rejected",
        "browser_target_not_found", "browser_target_ambiguous",
        "browser_confirmation_required", "browser_action_unsupported",
        "browser_internal_error",
    })

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code if code in self.CODES else "browser_internal_error"


def work_profile_dir() -> Path:
    """The dedicated work profile. Never the representative's own Chrome."""
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(root) / "PadiemClaw" / _PROFILE_DIR_NAME


def output_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(root) / "PadiemClaw" / "browser-output"


def _mcp_command() -> list[str]:
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None:
        raise PcBrowserError("browser_unavailable", "PC browser use needs Node.js (npx) on this PC")
    backend = os.environ.get("PADIEM_PC_BROWSER_BACKEND", "chrome").strip() or "chrome"
    command = [
        npx, "-y", MCP_PACKAGE,
        "--headless",
        "--browser", backend,
        "--user-data-dir", str(work_profile_dir()),
        "--output-dir", str(output_dir()),
    ]
    return command


class PlaywrightMcpClient:
    """Minimal, private MCP stdio client for one pinned server process."""

    def __init__(self, command: list[str] | None = None) -> None:
        self._command = command or _mcp_command()
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._next_id = 0
        # The handshake runs inside _request, so the lock must be reentrant.
        self._lock = threading.RLock()

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        work_profile_dir().mkdir(parents=True, exist_ok=True)
        output_dir().mkdir(parents=True, exist_ok=True)
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=creation,
            )
        except OSError as exc:
            raise PcBrowserError("browser_unavailable", "The PC browser cannot start") from exc
        threading.Thread(target=self._pump, args=(self._process, self._lines), daemon=True).start()
        self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "padiem-kagent", "version": "1"},
        })
        self._notify("notifications/initialized")

    @staticmethod
    def _pump(process: subprocess.Popen[str], lines: queue.Queue[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put("")

    def _notify(self, method: str) -> None:
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self._process.stdin.flush()

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_process_handle()
            self._next_id += 1
            request_id = self._next_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
            assert self._process is not None and self._process.stdin is not None
            try:
                self._process.stdin.write(json.dumps(payload) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise PcBrowserError("browser_not_running", "The PC browser process is gone") from exc
            return self._await(request_id)

    def _ensure_process_handle(self) -> None:
        if self._process is None or self._process.poll() is not None:
            self._ensure_started()

    def _await(self, request_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + MCP_CALL_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PcBrowserError("browser_internal_error", "The PC browser did not answer in time")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise PcBrowserError("browser_internal_error", "The PC browser did not answer in time") from None
            if not line:
                raise PcBrowserError("browser_not_running", "The PC browser process stopped")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise PcBrowserError("browser_internal_error", "The PC browser refused the step")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": dict(arguments or {})})

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


def _text_of(result: Mapping[str, Any]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts = [item.get("text") for item in content
             if isinstance(item, dict) and isinstance(item.get("text"), str)]
    return "\n".join(parts)


def parse_snapshot(snapshot: str, *, preserve_body_text: bool = False) -> list[dict[str, str]]:
    """Accessibility nodes, bounded action labels, optionally full body text.

    Full read-only paragraph text is retained for the output handle. Interactive
    labels remain bounded and form values/raw DOM are never projected.
    """
    nodes: list[dict[str, str]] = []
    pending_url = ""
    for line in snapshot.splitlines():
        url_match = _URL_LINE.match(line)
        if url_match:
            pending_url = url_match.group("url")[:2048]
            if nodes and nodes[-1]["role"] == "link" and not nodes[-1]["url"]:
                nodes[-1]["url"] = pending_url
            pending_url = ""
            continue
        match = _SNAPSHOT_LINE.match(line)
        if not match:
            continue
        name = (match.group("name") or match.group("text") or "").strip()
        role = match.group("role")
        nodes.append({
            "role": role,
            "name": name if preserve_body_text and role not in _SKIP_ROLES else name[:1024],
            "ref": match.group("ref"),
            "url": "",
        })
    return nodes


def page_title(snapshot: str) -> str:
    match = _PAGE_TITLE.search(snapshot)
    return match.group("title")[:512] if match else ""


def _links(nodes: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"name": node["name"], "url": node["url"]}
            for node in nodes if node["role"] == "link"][:MAX_LINKS]


_SKIP_ROLES = frozenset({"link", "button", "textbox", "checkbox", "radio", "combobox", "tab"})


def _body_text(nodes: list[dict[str, str]]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for node in nodes:
        name = node["name"]
        if not name or name in seen or node["role"] in _SKIP_ROLES:
            continue
        seen.add(name)
        lines.append(name)
    return "\n".join(lines)


def store_text(text: str) -> dict[str, str]:
    """Bounded inline text, or a content-addressed handle for the long tail."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_INLINE_TEXT:
        return {"text": text, "truncated": "false"}
    handle = hashlib.sha256(encoded).hexdigest()
    directory = output_dir() / "pages"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / handle
    if not target.exists():
        target.write_bytes(encoded)
    return {"handle": handle, "bytes": str(len(encoded)), "truncated": "true",
            "preview": encoded[:MAX_INLINE_TEXT].decode("utf-8", "ignore")}


def read_stored(handle: str, offset: int, length: int) -> dict[str, str]:
    if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
        raise PcBrowserError("browser_target_not_found", "Unknown stored page handle")
    if type(offset) is not int or type(length) is not int or offset < 0 or not 0 < length <= 65536:
        raise PcBrowserError("browser_action_unsupported", "Stored page range is invalid")
    path = output_dir() / "pages" / handle
    if not path.is_file():
        raise PcBrowserError("browser_target_not_found", "Stored page handle is gone")
    with path.open("rb") as stream:
        stream.seek(offset)
        chunk = stream.read(length)
    return {"text": chunk.decode("utf-8", "replace")}


def needs_confirmation(*names: str) -> bool:
    return any(_CONFIRM_RE.search(name or "") for name in names)


def is_secret_target(target: str) -> bool:
    return bool(_SECRET_TARGET_RE.search(target or ""))


def confirmation_question(target: str, *, action: str | None = None,
                          url: str | None = None, value: str | None = None) -> str:
    if action == "type" and is_secret_target(target):
        return "비밀번호·쿠키 같은 비밀 정보는 브라우저 작업에서 입력할 수 없습니다. 다른 항목을 선택할까요?"
    if action in {"click", "type"} and isinstance(url, str):
        verb = "클릭" if action == "click" else "입력"
        detail = f" 입력할 내용: {value}" if action == "type" and isinstance(value, str) else ""
        return (f"{url} 페이지에서 '{target}' 항목에 {verb} 동작을 실행할까요?{detail} "
                "로그인·결제·게시·발송으로 이어질 수 있습니다.")
    return (f"'{target}'은(는) 로그인·결제·게시·발송처럼 되돌리기 어려운 동작으로 보입니다. "
            "지금 실행할까요? 원하시면 취소하고 다른 방법으로 진행하겠습니다.")


def _confirmation_matches(confirmation: Any, *, action: str,
                          target: str, url: str | None, value: str | None = None) -> bool:
    # This object is not a tool argument. Only the signed Engine -> Chat -> PC
    # envelope may supply it after an ordinary conversational confirmation.
    expected = {"action", "target", "url"} | ({"value"} if action == "type" else set())
    return (isinstance(confirmation, Mapping)
            and set(confirmation) == expected
            and confirmation["action"] == action
            and confirmation["target"] == target
            and confirmation["url"] == url
            and (action != "type" or confirmation["value"] == value))


def resolve_target(nodes: list[dict[str, str]], *, text: str | None,
                   role: str | None, name: str | None) -> dict[str, str]:
    """Find exactly one element by visible text or role+name."""
    if name:
        candidates = [node for node in nodes if node["name"] == name and (not role or node["role"] == role)]
    elif text:
        needle = text.strip().lower()
        candidates = [node for node in nodes if node["name"] and needle in node["name"].lower()
                      and (not role or node["role"] == role)]
    else:
        raise PcBrowserError("browser_action_unsupported", "A click or type needs a visible text or a role and name")
    if not candidates:
        raise PcBrowserError("browser_target_not_found", "No visible element matches that description")
    if len(candidates) > 1:
        exact = [node for node in candidates if node["name"].strip().lower() == (text or name or "").strip().lower()]
        if len(exact) != 1:
            raise PcBrowserError("browser_target_ambiguous", "More than one visible element matches that description")
        candidates = exact
    return candidates[0]


class PcBrowserSession:
    """One work profile, one pinned MCP child process, four bounded tools."""

    def __init__(self, client: PlaywrightMcpClient | None = None) -> None:
        self._client = client
        self._url: str | None = None

    @property
    def client(self) -> PlaywrightMcpClient:
        if self._client is None:
            self._client = PlaywrightMcpClient()
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._url = None

    def open(self, url: str) -> dict[str, Any]:
        try:
            normalized = normalize_public_url(url)
        except ValueError as exc:
            raise PcBrowserError("browser_url_rejected", "That address is not a public web page") from exc
        result = self.client.call_tool("browser_navigate", {"url": normalized})
        if result.get("isError"):
            raise PcBrowserError("browser_internal_error", "The page could not be opened")
        self._url = normalized
        snapshot = self._snapshot()
        nodes = parse_snapshot(snapshot)
        return {"state": "opened", "url": self._url,
                "title": page_title(snapshot) or _title(nodes), "elements": str(len(nodes))}

    def _snapshot(self) -> str:
        if self._url is None:
            raise PcBrowserError("browser_not_running", "No page is open yet")
        result = self.client.call_tool("browser_snapshot", {})
        if result.get("isError"):
            raise PcBrowserError("browser_internal_error", "The page could not be observed")
        text = _text_of(result)
        current = _PAGE_URL.search(text)
        if current is None:
            raise PcBrowserError("browser_internal_error", "The page could not be observed")
        try:
            self._url = normalize_public_url(current.group("url"))
        except ValueError as exc:
            raise PcBrowserError("browser_url_rejected", "That address is not a public web page") from exc
        # Keep the full page until store_text() creates a handle. Truncating
        # the raw snapshot here would make the stored source incomplete too.
        return text

    def read(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        nodes = parse_snapshot(snapshot, preserve_body_text=True)
        body = store_text(_body_text(nodes))
        payload: dict[str, Any] = {"state": "read", "url": self._url,
                                   "title": page_title(snapshot) or _title(nodes),
                                   "links": _links(nodes)}
        payload.update(body)
        return payload

    def screenshot(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        directory = output_dir()
        directory.mkdir(parents=True, exist_ok=True)
        filename = os.path.join(str(directory), "page-" + uuid.uuid4().hex + ".png")
        result = self.client.call_tool("browser_take_screenshot", {"filename": filename, "type": "png"})
        captured = Path(filename)
        if (result.get("isError") or not captured.is_file()
                or captured.resolve().parent != directory.resolve()):
            raise PcBrowserError("browser_internal_error", "The screenshot could not be saved")
        image = captured.read_bytes()
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PcBrowserError("browser_internal_error", "The screenshot could not be verified")
        return {"state": "captured", "url": self._url,
                "title": page_title(snapshot) or _title(parse_snapshot(snapshot)),
                "path": filename, "bytes": str(len(image)), "screenshots": "1",
                "capture": {"mime_type": "image/png", "data": base64.b64encode(image).decode("ascii"),
                            "sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}}

    def act(self, *, action: str, text: str | None = None, role: str | None = None,
            name: str | None = None, value: str | None = None,
            confirmation: Mapping[str, str] | None = None) -> dict[str, Any]:
        if action not in {"click", "type"}:
            raise PcBrowserError("browser_action_unsupported", "Only click and type are supported")
        snapshot = self._snapshot()
        nodes = parse_snapshot(snapshot)
        target = resolve_target(nodes, text=text, role=role, name=name)
        if action == "type" and is_secret_target(target["name"]):
            raise PcBrowserError("browser_action_unsupported", "Credential fields are not available to this tool")
        if target.get("url"):
            try:
                normalize_public_url(urljoin(self._url or "", target["url"]))
            except ValueError as exc:
                raise PcBrowserError("browser_url_rejected", "That address is not a public web page") from exc
        # A neutral label such as "Continue" does not make a checkout or
        # login action safe. The fresh PC observation may only make this
        # decision stricter; it never grants confirmation authority.
        if (needs_confirmation(target["name"], value or "", self._url or "", page_title(snapshot))
                and not _confirmation_matches(confirmation, action=action, target=target["name"], url=self._url, value=value)):
            return {"state": "needs_confirmation", "question": confirmation_question(
                        target["name"], action=action, url=self._url, value=value),
                    "target": target["name"], "action": action, "url": self._url,
                    "title": page_title(snapshot) or _title(nodes)}
        arguments: dict[str, Any] = {"target": target["ref"], "element": target["name"] or target["role"]}
        if action == "type":
            if not isinstance(value, str) or not value:
                raise PcBrowserError("browser_action_unsupported", "Typing needs the text to enter")
            arguments["text"] = value
        result = self.client.call_tool("browser_" + action, arguments)
        if result.get("isError"):
            raise PcBrowserError("browser_internal_error", "The page did not accept that action")
        after = self._snapshot()
        after_nodes = parse_snapshot(after)
        title = page_title(after) or _title(after_nodes)
        return {"state": "acted", "action": action, "target": target["name"] or target["role"],
                "url": self._url, "title": title, "verified": True,
                "observation": {"url": self._url, "title": title, "elements": len(after_nodes)}}


def _title(nodes: list[dict[str, str]]) -> str:
    for node in nodes:
        if node["role"] == "heading" and node["name"]:
            return node["name"]
    for node in nodes:
        if node["name"]:
            return node["name"]
    return ""


def validate_arguments(tool_id: str, arguments: Any) -> dict[str, Any]:
    """Strict, closed argument shapes. No field can carry a cookie or a script."""
    if not isinstance(tool_id, str) or tool_id not in BROWSER_TOOL_IDS or not isinstance(arguments, Mapping):
        raise PcBrowserError("browser_action_unsupported", "Unknown PC browser tool")
    data = dict(arguments)
    allowed = {
        BROWSER_OPEN_TOOL_ID: {"url"},
        BROWSER_READ_TOOL_ID: set(),
        BROWSER_SCREENSHOT_TOOL_ID: set(),
        BROWSER_ACT_TOOL_ID: {"action", "text", "role", "name", "value"},
    }[tool_id]
    if set(data) - allowed:
        raise PcBrowserError("browser_action_unsupported", "PC browser arguments are invalid")
    for key, value in data.items():
        if not isinstance(value, str) or not value or (key != "value" and not value.strip()):
            raise PcBrowserError("browser_action_unsupported", "PC browser arguments are invalid")
        if len(value) > (4000 if key == "value" else 2048):
            raise PcBrowserError("browser_action_unsupported", "PC browser arguments are invalid")
    if tool_id == BROWSER_OPEN_TOOL_ID:
        if set(data) != {"url"}:
            raise PcBrowserError("browser_url_rejected", "A public page address is required")
        try:
            normalize_public_url(data["url"])
        except ValueError as exc:
            raise PcBrowserError("browser_url_rejected", "A public page address is required") from exc
    if tool_id == BROWSER_ACT_TOOL_ID:
        if data.get("action") not in {"click", "type"}:
            raise PcBrowserError("browser_action_unsupported", "Only click and type are supported")
        if not (data.get("text") or data.get("name")):
            raise PcBrowserError("browser_action_unsupported", "A visible target is required")
        if data["action"] == "type" and not data.get("value"):
            raise PcBrowserError("browser_action_unsupported", "Typing needs the text to enter")
    return data


def tool_specs() -> tuple[ToolSpec, ...]:
    text = {"type": "string", "minLength": 1, "maxLength": 2048}
    specs = (
        (BROWSER_OPEN_TOOL_ID, "Browser open", "Open one public web page in the work browser profile.",
         {"url": {"type": "string", "minLength": 1, "maxLength": 2048}}, ["url"]),
        (BROWSER_READ_TOOL_ID, "Browser read",
         "Read the open page's title, body text and link list. Long text returns a handle.",
         {}, []),
        (BROWSER_SCREENSHOT_TOOL_ID, "Browser screenshot", "Capture one screenshot of the open page.",
         {}, []),
        (BROWSER_ACT_TOOL_ID, "Browser act",
         "Click or type on the open page using its visible text, or a role and name.",
         {"action": {"type": "string", "enum": ["click", "type"]}, "text": text,
          "role": text, "name": text, "value": {"type": "string", "maxLength": 4000}},
         ["action"]),
    )
    return tuple(ToolSpec(
        id=tool_id, title=title, description=description, owner="core",
        side_effect=ToolSideEffect.WRITE if tool_id == BROWSER_ACT_TOOL_ID else ToolSideEffect.READ,
        approval_policy=(ApprovalPolicy.EXTERNAL_AUTHORIZATION
                         if tool_id == BROWSER_ACT_TOOL_ID else ApprovalPolicy.NOT_REQUIRED),
        auth_scope=(tool_id,),
        input_schema={"type": "object", "properties": properties,
                      "required": required, "additionalProperties": False},
        output_contract={"type": "object"}, timeout_seconds=None,
    ) for tool_id, title, description, properties, required in specs)
