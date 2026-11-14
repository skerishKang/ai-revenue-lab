#!/usr/bin/env python3
"""Adopt a PC link onto the QA account from the COM2 host, without a browser.

The route (``/api/pc/pairings/adopt``) keeps the platform-admin session guard.
This tool performs the same after-guard adoption directly against the Chat
service's own SQLite/D1 store, so an operator on COM2 does not need a browser
session. It never prints the account id, mesh node id or token value.

    # preview (default): what would happen, no write
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/adopt_pc_link.py \
        --target-from-qa-env

    # apply: create the one (QA account, PC) link
    sudo -u root /opt/padiem/chat-com2/venv/bin/python \
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/adopt_pc_link.py \
        --target-from-qa-env --apply

The default PC label is ``K_lipvoice · 컴2``. The target account is read from
``/etc/padiem/qa-smoke.env`` (root 0600) - the same file
``provision_qa_smoke_account.ps1`` writes. The env file must exist, be root
owned and mode 600; the account value is never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

# On COM2 the running Chat service imports its code from the deployed tree
# (WorkingDirectory of padiem-chat-com2.service), which also carries the bundled
# packages such as padiem_control_plane. The ops checkout this script lives in
# does not, so the tool uses the deployed tree when it exists.
DEPLOYED_ROOT = Path("/opt/padiem/chat-com2")
SERVICE_USER = "padiem-chat"

QA_ENV_PATH = Path("/etc/padiem/qa-smoke.env")
CHAT_ENV_PATH = Path("/opt/padiem/chat-com2/.env")
QA_USERNAME_KEYS = ("B66_CGI_ALPHA_USERNAME", "QA_DEPLOY_USERNAME")
DEFAULT_PC_LABEL = "K_lipvoice · 컴2"


class ToolError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _assert_root() -> None:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        raise ToolError("ROOT_REQUIRED")


def _assert_env_metadata(mode: int, uid: int, size: int) -> None:
    if uid != 0:
        raise ToolError("QA_ENV_OWNER_NOT_ROOT")
    if stat.S_IMODE(mode) != 0o600:
        raise ToolError("QA_ENV_MODE_NOT_600")
    if size <= 0:
        raise ToolError("QA_ENV_EMPTY")


def _assert_env_file(path: Path) -> None:
    try:
        st = path.stat()
    except OSError:
        raise ToolError("QA_ENV_MISSING")
    if not stat.S_ISREG(st.st_mode):
        raise ToolError("QA_ENV_NOT_REGULAR")
    _assert_env_metadata(st.st_mode, st.st_uid, st.st_size)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("'\''", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _load_env_file(path: Path) -> None:
    """Load the Chat service's own env file into this process, without output.

    The values are the same ones the systemd unit passes to the Chat service.
    The file is root-only; this tool runs as root and never prints its content.
    """
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
            os.environ[key] = _unquote(value)


def _read_qa_username(path: Path) -> str:
    """Read only the QA username; the password line is never retained."""
    for key in QA_USERNAME_KEYS:
        pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=\s*(.*)$")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                match = pattern.match(line)
                if match:
                    value = _unquote(match.group(1))
                    if value:
                        return value
    raise ToolError("QA_ENV_USERNAME_MISSING")


def _use_deployed_tree(root: Path = DEPLOYED_ROOT) -> bool:
    """Import the app the same way the service does: from its deployed tree."""
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
    """Drop root before the app opens its database.

    Root is needed only to read the root-only QA file. The Chat database and its
    WAL/SHM files must stay owned by the service user, or the service can no
    longer write them.
    """
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


def _load_state() -> tuple[Any, Any]:
    os.environ.setdefault("PADIEM_CHAT_CPYTHON_HOST", "1")
    from app.local_cpython import build_app

    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        app = build_app()
    finally:
        sys.stdout = saved_stdout
    # build_app may return the Starlette app wrapped in raw ASGI middleware
    # (the write-freeze MaintenanceModeMiddleware keeps the inner app on ``app``
    # or ``_app``). Walk inward to the application that owns ``state``.
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
        raise ToolError("PC_PAIRING_UNAVAILABLE")
    store = getattr(state, "pc_device_pairing_store", None)
    presence = getattr(state, "mesh_device_presence_store", None)
    if store is None or presence is None:
        raise ToolError("PC_PAIRING_UNAVAILABLE")
    return store, presence


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _device_id_for_label(store: Any, label: str) -> str | None:
    """Find the one active node whose link carries ``label``.

    Uses only the pairing store's own methods, so it works the same on the D1
    store and on the queue-backed store production runs (#7701 follow-up): the
    active node list, the accounts behind each node, and each account's links.
    """
    found: set[str] = set()
    for device_id in await _maybe(store.list_active_device_ids()) or []:
        scope = await _maybe(store.device_scope(device_id=device_id))
        refs = (scope or {}).get("account_refs") or []
        for ref in refs:
            for link in await _maybe(store.links_for_owner(user_id=ref)) or []:
                if (isinstance(link, dict) and link.get("mesh_node_id") == device_id
                        and link.get("label") == label):
                    found.add(device_id)
    if not found:
        return None
    if len(found) > 1:
        raise ToolError("PC_AMBIGUOUS")
    return next(iter(found))


async def _count_linked_accounts(store: Any, device_id: str) -> int:
    scope = await _maybe(store.device_scope(device_id=device_id))
    refs = (scope or {}).get("account_refs") or []
    return len(set(refs))


async def _presence_ok(presence: Any, device_id: str) -> bool:
    record = presence.load(device_id=device_id)
    if inspect.isawaitable(record):
        record = await record
    return isinstance(record, dict) and bool(record.get("device_id"))


async def run_adopt(
    store: Any,
    presence: Any,
    *,
    pc_label: str,
    target_username: str,
    apply: bool = False,
    now: Any = None,
) -> dict[str, Any]:
    """Return the bounded report lines; never the identifiers themselves."""
    lines: list[str] = []
    device_id = await _device_id_for_label(store, pc_label)
    if not device_id:
        lines.append("PC_FOUND=no")
        return {"lines": lines, "error": "PC_NOT_FOUND"}
    lines.append("PC_FOUND=yes")

    if not await _presence_ok(presence, device_id):
        lines.append("PRESENCE=none")
        return {"lines": lines, "error": "PC_NOT_PRESENT"}
    lines.append("PRESENCE=ok")

    account_id = await store.resolve_account_ref(target=target_username)
    if not account_id:
        lines.append("TARGET_ACCOUNT=unknown")
        return {"lines": lines, "error": "TARGET_ACCOUNT_UNKNOWN"}
    lines.append("TARGET_ACCOUNT=found")

    existing = await store.link_for(user_id=account_id, mesh_node_id=device_id)
    total = await _count_linked_accounts(store, device_id)
    if existing:
        lines.append("EXISTING_LINK=yes")
        lines.append("OTHER_ACCOUNTS_KEPT=%d" % max(0, total - 1))
        lines.append("ALREADY_LINKED")
        return {"lines": lines, "error": None}

    lines.append("EXISTING_LINK=no")
    lines.append("OTHER_ACCOUNTS_KEPT=%d" % total)
    if not apply:
        return {"lines": lines, "error": None}

    from app.pc_pairing_adopt_service import adopt_pc_link

    await adopt_pc_link(
        store, presence, target=target_username, device_id=device_id,
        drives=[], now=now,
    )
    after = await _count_linked_accounts(store, device_id)
    lines[-1] = "OTHER_ACCOUNTS_KEPT=%d" % max(0, after - 1)
    lines.append("ADOPTED=1")
    return {"lines": lines, "error": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-label", default=DEFAULT_PC_LABEL)
    parser.add_argument("--target-from-qa-env", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        _assert_root()
        _load_env_file(CHAT_ENV_PATH)
        _assert_env_file(QA_ENV_PATH)
        target = _read_qa_username(QA_ENV_PATH)
        if _use_deployed_tree():
            _become_service_user()
        store, presence = _load_state()
        result = asyncio.run(run_adopt(
            store, presence, pc_label=args.pc_label,
            target_username=target, apply=args.apply,
        ))
    except ToolError as exc:
        print("STOP " + exc.code)
        return 1
    except Exception as exc:
        code = getattr(exc, "code", None)
        print("STOP " + (code if isinstance(code, str) and code.startswith("pc_pairing_")
                         else "PC_PAIRING_REFUSED"))
        return 1
    for line in result["lines"]:
        print(line)
    if result.get("error"):
        print("STOP " + result["error"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())