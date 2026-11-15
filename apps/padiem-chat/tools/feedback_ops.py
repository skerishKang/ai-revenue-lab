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

    # create one '새 소식' item (#7718 step 2). No user names are accepted or stored.
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --news-create --news-kind improved --news-title "..." --news-detail "..." --news-source none --apply

    # point one feedback at a news item number; usually together with --status fixed
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/feedback_ops.py \
        --feedback-id fb_<32hex> --news-link 12 --apply

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
STATUSES = frozenset({"new", "reviewing", "fixed", "deferred"})
NEWS_KINDS = frozenset({"improved", "fixed"})
NEWS_SOURCES = frozenset({"ai_tester", "user", "none"})
NEWS_TITLE_CHARS = 120
NEWS_DETAIL_CHARS = 1000
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


def _news_text_valid(value, limit):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(c) < 32 and c not in '\n\r\t' for c in value)
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


async def run_news_create(store, *, kind, title, detail, source, apply=False):
    """Create one news item. Output is the item number and success only."""
    if kind not in NEWS_KINDS:
        raise ToolError("NEWS_KIND_INVALID")
    if source not in NEWS_SOURCES:
        raise ToolError("NEWS_SOURCE_INVALID")
    if not _news_text_valid(title, NEWS_TITLE_CHARS):
        raise ToolError("NEWS_TITLE_INVALID")
    if not _news_text_valid(detail, NEWS_DETAIL_CHARS):
        raise ToolError("NEWS_DETAIL_INVALID")
    if not apply:
        return {"lines": ["news=pending", "ok=true"], "error": None}
    record = await store.create(kind, title, detail, source)
    if record is None:
        return {"lines": ["news=pending", "ok=false"], "error": "NEWS_STORE_REFUSED"}
    return {"lines": [f"news={record.number}", "ok=true"], "error": None}


async def run_news_link(news_store, feedback_store, feedback_id, number, *, status=None, apply=False):
    """Point one feedback at a news item, usually right after --status fixed."""
    if not FEEDBACK_ID.fullmatch(feedback_id):
        raise ToolError("FEEDBACK_ID_INVALID")
    if type(number) is not int or number < 1:
        raise ToolError("NEWS_LINK_INVALID")
    if status is not None and status not in STATUSES:
        raise ToolError("STATUS_INVALID")
    if not apply:
        record = await feedback_store.get_record(feedback_id)
        if record is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
        current = getattr(record, "news_number", None)
        lines = [f"feedback={feedback_id}"]
        if status is not None:
            lines.append(f"status={record.status}")
        lines.append(f"news={current if current is not None else 'none'}")
        lines.append("ok=true")
        return {"lines": lines, "error": None}
    if status is not None:
        updated = await feedback_store.set_status(feedback_id, status)
        if updated is None:
            return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
    if await news_store.get(number) is None:
        return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "NEWS_NOT_FOUND"}
    linked = await news_store.link_feedback(feedback_id, number)
    if not linked:
        return {"lines": [f"feedback={feedback_id}", "ok=false"], "error": "FEEDBACK_NOT_FOUND"}
    return {"lines": [f"feedback={feedback_id}", f"news={number}", "ok=true"], "error": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback-id")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--reply")
    parser.add_argument("--ai-tester", choices=("on", "off"))
    parser.add_argument("--memo")
    parser.add_argument("--site", action="store_true")
    parser.add_argument("--news-create", action="store_true")
    parser.add_argument("--news-kind", choices=sorted(NEWS_KINDS))
    parser.add_argument("--news-title")
    parser.add_argument("--news-detail")
    parser.add_argument("--news-source", choices=sorted(NEWS_SOURCES))
    parser.add_argument("--news-link", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        ai_tester = None if args.ai_tester is None else args.ai_tester == "on"
        if args.news_create:
            if (args.feedback_id is not None or args.status is not None or args.reply is not None
                    or ai_tester is not None or args.memo is not None or args.site
                    or args.news_link is not None):
                raise ToolError("NOT_APPLICABLE")
            _assert_root()
            _load_env_file(CHAT_ENV_PATH)
            _use_deployed_tree()
            _become_service_user()
            news_store = getattr(_load_state(), "news_store", None)
            if news_store is None:
                raise ToolError("NEWS_STORE_UNAVAILABLE")
            result = asyncio.run(run_news_create(
                news_store, kind=args.news_kind, title=args.news_title,
                detail=args.news_detail, source=args.news_source, apply=args.apply))
        elif args.news_link is not None:
            if (args.reply is not None or ai_tester is not None or args.memo is not None
                    or args.site or args.news_create):
                raise ToolError("NOT_APPLICABLE")
            if args.feedback_id is None:
                raise ToolError("FEEDBACK_ID_REQUIRED")
            _assert_root()
            _load_env_file(CHAT_ENV_PATH)
            _use_deployed_tree()
            _become_service_user()
            state = _load_state()
            news_store = getattr(state, "news_store", None)
            feedback_store = getattr(state, "feedback_store", state)
            if news_store is None:
                raise ToolError("NEWS_STORE_UNAVAILABLE")
            if feedback_store is None:
                raise ToolError("FEEDBACK_STORE_UNAVAILABLE")
            result = asyncio.run(run_news_link(
                news_store, feedback_store, args.feedback_id, args.news_link,
                status=args.status, apply=args.apply))
        else:
            if args.status is None and args.reply is None and ai_tester is None and args.memo is None:
                raise ToolError("NOTHING_TO_DO")
            if args.news_kind is not None or args.news_title is not None or args.news_detail is not None \
                    or args.news_source is not None:
                raise ToolError("NOT_APPLICABLE")
            if args.feedback_id is None:
                raise ToolError("FEEDBACK_ID_REQUIRED")
            if args.site and (args.reply is not None or ai_tester is not None):
                raise ToolError("NOT_APPLICABLE")
            if not args.site and args.memo is not None:
                raise ToolError("NOT_APPLICABLE")
            _assert_root()
            _load_env_file(CHAT_ENV_PATH)
            _use_deployed_tree()
            _become_service_user()
            state = _load_state()
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