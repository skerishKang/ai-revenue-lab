#!/usr/bin/env python3
"""Change one feedback's status, operator reply, AI-tester flag, or site
administrator assignments from COM2.

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

    # site feedback administrator designation/removal (central administrator
    # only). The target account comes from the account behind one Chat
    # feedback or an explicit account id; the value is never printed.
    sudo -u root /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --site-admin-add miraen-home --feedback-id fb_<32hex>
    sudo -u root /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --site-admin-remove miraen-home --account usr_<32hex> --apply

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
SITE_FEEDBACK_ID = re.compile(r"sf_[0-9a-f]{32}\Z")
ACCOUNT_ID = re.compile(r"usr_[0-9a-f]{32}\Z")
SITE_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
STATUSES = frozenset({"new", "reviewing", "fixed", "deferred"})
REPLY_CHARS = 4000
MEMO_CHARS = 2000


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
    if state is None:
        raise ToolError("FEEDBACK_STORE_UNAVAILABLE")
    return state


async def run_feedback(store, feedback_id, *, status=None, reply=None, ai_tester=None, memo=None, apply=False):
    if not FEEDBACK_ID.fullmatch(feedback_id) and not SITE_FEEDBACK_ID.fullmatch(feedback_id):
        raise ToolError("FEEDBACK_ID_INVALID")
    if status is not None and status not in STATUSES:
        raise ToolError("STATUS_INVALID")
    if SITE_FEEDBACK_ID.fullmatch(feedback_id):
        if reply is not None or ai_tester is not None:
            raise ToolError("NOT_APPLICABLE")
        if memo is not None and (not isinstance(memo, str) or len(memo) > MEMO_CHARS
                                 or any(ord(c) < 32 and c not in '\n\r\t' for c in memo)
                                 or any(0xD800 <= ord(c) <= 0xDFFF for c in memo)):
            raise ToolError("MEMO_INVALID")
        if status is None and memo is None:
            raise ToolError("NOTHING_TO_DO")
        record = await store.get_record(feedback_id)
        if record is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
        lines = [f"feedback={feedback_id}", f"site={getattr(record, 'site', '')}",
                 f"status={getattr(record, 'status', '')}",
                 f"memo={'set' if getattr(record, 'ops_memo', None) else 'unset'}"]
        if not apply:
            lines.append("ok=true")
            return {"lines": lines, "error": None}
        if status is not None:
            updated = await store.set_status(feedback_id, status)
            if updated is None:
                return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
        if memo is not None:
            updated = await store.set_ops_memo(feedback_id, memo)
            if updated is None:
                return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
        record = await store.get_record(feedback_id)
        lines = [f"feedback={feedback_id}",
                 f"site={getattr(record, 'site', '') if record is not None else ''}",
                 f"status={getattr(record, 'status', status) if record is not None else status}",
                 f"memo={'set' if getattr(record, 'ops_memo', None) else 'unset'}"]
        lines.append("ok=true")
        return {"lines": lines, "error": None}
    if memo is not None:
        raise ToolError("NOT_APPLICABLE")
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


async def run_site_admin(authorizer, feedback_store, action, site, *,
                         feedback_id=None, account=None, apply=False):
    """Designate or remove one site feedback administrator.

    The target account is resolved from the account behind one Chat feedback
    or an explicit account id and is never printed; lines carry flags and
    counts only. Preview (default) writes nothing.
    """
    if action not in ("add", "remove"):
        raise ToolError("ACTION_INVALID")
    if not isinstance(site, str) or SITE_KEY.fullmatch(site) is None:
        raise ToolError("SITE_INVALID")
    from app.site_feedback_store import SITE_KEYS
    if site not in SITE_KEYS:
        raise ToolError("SITE_INVALID")
    if (feedback_id is None) == (account is None):
        raise ToolError("TARGET_CONFLICT" if feedback_id is not None else "TARGET_MISSING")
    if feedback_id is not None:
        if not FEEDBACK_ID.fullmatch(feedback_id):
            raise ToolError("FEEDBACK_ID_INVALID")
        if feedback_store is None:
            raise ToolError("FEEDBACK_STORE_UNAVAILABLE")
        record = await feedback_store.get_record(feedback_id)
        target = getattr(record, "user_id", None) if record is not None else None
        if not isinstance(target, str) or not target:
            return {"lines": [f"feedback={feedback_id}", "target=missing", "ok=false"],
                    "error": "FEEDBACK_NOT_FOUND"}
        source = "feedback"
    else:
        if not ACCOUNT_ID.fullmatch(account):
            raise ToolError("ACCOUNT_INVALID")
        target, source = account, "account"
    assigned = await authorizer.is_site_admin(user_id=target, site=site)
    lines = ([f"feedback={feedback_id}"] if feedback_id is not None else []) + [
        f"site={site}", f"action={action}", f"target={source}",
        f"before={'yes' if assigned else 'no'}"]
    error = None
    if action == "add":
        if assigned:
            result = "already"
        elif not apply:
            result = "ready"
        else:
            result = await authorizer.assign(user_id=target, site=site)
            if result == "missing":
                result, error = "account-missing", "USER_NOT_FOUND"
        lines.append(f"after={'yes' if result in ('assigned', 'already') else 'no'}")
    else:
        if not assigned:
            result = "not-assigned"
        elif not apply:
            result = "ready"
        else:
            result = await authorizer.unassign(user_id=target, site=site)
        lines.append(f"after={'no' if result in ('removed', 'not-assigned') else 'yes'}")
    sites_now = await authorizer.sites_for(user_id=target)
    lines.append(f"result={result}")
    lines.append(f"sites={len(sites_now)}")
    lines.append("ok=true")
    return {"lines": lines, "error": error}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback-id")
    parser.add_argument("--account")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--reply")
    parser.add_argument("--ai-tester", choices=("on", "off"))
    parser.add_argument("--memo")
    parser.add_argument("--site", action="store_true")
    parser.add_argument("--site-admin-add", dest="site_admin_add")
    parser.add_argument("--site-admin-remove", dest="site_admin_remove")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        ai_tester = None if args.ai_tester is None else args.ai_tester == "on"
        if args.site_admin_add is not None and args.site_admin_remove is not None:
            raise ToolError("ACTION_CONFLICT")
        site_admin_action = None
        if args.site_admin_add is not None:
            site_admin_action = ("add", args.site_admin_add)
        elif args.site_admin_remove is not None:
            site_admin_action = ("remove", args.site_admin_remove)
        if site_admin_action is not None:
            if (args.status is not None or args.reply is not None
                    or ai_tester is not None or args.memo is not None or args.site):
                raise ToolError("NOT_APPLICABLE")
        else:
            if not args.feedback_id:
                raise ToolError("FEEDBACK_ID_REQUIRED")
            if args.status is None and args.reply is None and ai_tester is None and args.memo is None:
                raise ToolError("NOTHING_TO_DO")
            if args.site and (args.reply is not None or ai_tester is not None):
                raise ToolError("NOT_APPLICABLE")
            if not args.site and args.memo is not None:
                raise ToolError("NOT_APPLICABLE")
        _assert_root()
        _load_env_file(CHAT_ENV_PATH)
        _use_deployed_tree()
        _become_service_user()
        state = _load_state()
        if site_admin_action is not None:
            authorizer = getattr(state, "site_feedback_admin_authorizer", None)
            if authorizer is None:
                raise ToolError("SITE_ADMIN_STORE_UNAVAILABLE")
            result = asyncio.run(run_site_admin(
                authorizer, getattr(state, "feedback_store", None),
                site_admin_action[0], site_admin_action[1],
                feedback_id=args.feedback_id, account=args.account, apply=args.apply))
        else:
            store = getattr(state, "site_feedback_store", None) if args.site else getattr(state, "feedback_store", state)
            if store is None:
                raise ToolError("SITE_FEEDBACK_STORE_UNAVAILABLE" if args.site else "FEEDBACK_STORE_UNAVAILABLE")
            result = asyncio.run(run_feedback(
                store, args.feedback_id, status=args.status,
                reply=None if args.site else args.reply,
                ai_tester=None if args.site else ai_tester,
                memo=args.memo if args.site else None,
                apply=args.apply))
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