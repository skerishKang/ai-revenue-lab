#!/usr/bin/env python3
"""Change one feedback's status, operator reply, or AI-tester flag from COM2.

The browser route keeps the administrator session guard. This tool performs the
same bounded change directly against the Chat service's own store, so an
operator on COM2 does not need a browser session. It never prints the feedback
body, account value or reply text.

    # preview (default): current status, no write
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --feedback-id fb_<32hex> --status fixed

    # apply: set the status and add one operator reply
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --feedback-id fb_<32hex> --status fixed --reply "..." --apply

    # AI-tester display flag for the account behind one feedback
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --feedback-id fb_<32hex> --ai-tester on --apply

Root is required only to read the root-only Chat env file. The process drops to
the service user before the app opens its database. The reply is passed as an
argument and is never echoed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

DEPLOYED_ROOT = Path("/opt/padiem/chat-com2")
SERVICE_USER = "padiem-chat"
CHAT_ENV_PATH = Path("/opt/padiem/chat-com2/.env")
FEEDBACK_ID = re.compile(r"fb_[0-9a-f]{32}\Z")
STATUSES = frozenset({"new", "reviewing", "fixed", "deferred"})
REPLY_CHARS = 4000


class ToolError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _assert_root() -> None:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        raise ToolError("ROOT_REQUIRED")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        raise ToolError("CHAT_ENV_MISSING")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("export "):
                text = text[7:].lstrip()
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


def _use_deployed_tree(root: Path = DEPLOYED_ROOT) -> bool:
    if not (root / "app").is_dir():
        return False
    os.chdir(root)
    while str(root) in sys.path:
        sys.path.remove(str(root))
    sys.path.insert(0, str(root))
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    return True


def _become_service_user(name: str = SERVICE_USER) -> None:
    import pwd

    try:
        entry = pwd.getpwnam(name)
    except KeyError:
        raise ToolError("SERVICE_USER_MISSING") from None
    os.setgroups([])
    os.setgid(entry.pw_gid)
    os.setuid(entry.pw_uid)
    if os.geteuid() != entry.pw_uid:
        raise ToolError("SERVICE_USER_SWITCH_FAILED")


def _load_state():
    os.environ.setdefault("PADIEM_CHAT_CPYTHON_HOST", "1")
    from app.local_cpython import build_app

    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        app = build_app()
    finally:
        sys.stdout = saved_stdout
    inner = app
    for _ in range(8):
        if hasattr(inner, "state"):
            break
        nxt = getattr(inner, "app", None) or getattr(inner, "_app", None)
        if nxt is None or nxt is inner:
            break
        inner = nxt
    state = getattr(inner, "state", None)
    store = getattr(state, "feedback_store", None) if state is not None else None
    if store is None:
        raise ToolError("FEEDBACK_STORE_UNAVAILABLE")
    return store


async def run_feedback(store, feedback_id, *, status=None, reply=None, ai_tester=None, apply=False):
    if not FEEDBACK_ID.fullmatch(feedback_id):
        raise ToolError("FEEDBACK_ID_INVALID")
    if status is not None and status not in STATUSES:
        raise ToolError("STATUS_INVALID")
    if reply is not None and (not isinstance(reply, str) or not reply.strip() or len(reply) > REPLY_CHARS):
        raise ToolError("REPLY_INVALID")
    if ai_tester is not None and type(ai_tester) is not bool:
        raise ToolError("AI_TESTER_INVALID")
    if status is None and reply is None and ai_tester is None:
        raise ToolError("NOTHING_TO_DO")

    record = await store.get_record(feedback_id)
    if record is None:
        return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
    lines = [f"feedback={feedback_id}"]
    if status is not None or reply is not None:
        lines.append(f"status={record.status}")
    if ai_tester is not None:
        lines.append(f"ai_tester={'on' if bool(getattr(record, 'is_ai_tester', False)) else 'off'}")
    if not apply:
        lines.append("ok=true")
        return {"lines": lines, "error": None}

    if status is not None:
        updated = await store.set_status(feedback_id, status)
        if updated is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
    if reply is not None:
        reply_row = await store.add_reply(feedback_id, "ops", reply)
        if reply_row is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
    if ai_tester is not None:
        updated = await store.set_ai_tester(feedback_id, ai_tester)
        if updated is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}

    record = await store.get_record(feedback_id)
    lines = [f"feedback={feedback_id}"]
    if status is not None or reply is not None:
        lines.append(f"status={record.status if record is not None else status}")
    if ai_tester is not None:
        current = bool(getattr(record, "is_ai_tester", False)) if record is not None else ai_tester
        lines.append(f"ai_tester={'on' if current else 'off'}")
    lines.append("ok=true")
    return {"lines": lines, "error": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback-id", required=True)
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--reply")
    parser.add_argument("--ai-tester", choices=("on", "off"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        ai_tester = None if args.ai_tester is None else args.ai_tester == "on"
        if args.status is None and args.reply is None and ai_tester is None:
            raise ToolError("NOTHING_TO_DO")
        _assert_root()
        _load_env_file(CHAT_ENV_PATH)
        _use_deployed_tree()
        _become_service_user()
        store = _load_state()
        result = asyncio.run(run_feedback(
            store, args.feedback_id, status=args.status, reply=args.reply,
            ai_tester=ai_tester, apply=args.apply))
    except ToolError as exc:
        print("STOP " + exc.code)
        return 1
    except Exception:
        print("STOP FEEDBACK_OPS_REFUSED")
        return 1
    for line in result["lines"]:
        print(line)
    if result.get("error"):
        print("STOP " + result["error"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())