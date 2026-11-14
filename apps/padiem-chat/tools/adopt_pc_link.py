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


def _load_state() -> tuple[Any, Any]:
    os.environ.setdefault("PADIEM_CHAT_CPYTHON_HOST", "1")
    from app.local_cpython import build_app

    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        app = build_app()
    finally:
        sys.stdout = saved_stdout
    store = getattr(app.state, "pc_device_pairing_store", None)
    presence = getattr(app.state, "mesh_device_presence_store", None)
    if store is None or presence is None:
        raise ToolError("PC_PAIRING_UNAVAILABLE")
    return store, presence


def _require_db(store: Any) -> Any:
    db = getattr(store, "db", None)
    if db is None:
        # The queue-backed store has no local DB to search by label. Production
        # defaults to D1; refuse rather than guess.
        raise ToolError("PC_PAIRING_QUEUE_BACKEND_UNSUPPORTED")
    return db


async def _device_id_for_label(store: Any, label: str) -> str | None:
    db = _require_db(store)
    statement = db.prepare(
        "SELECT DISTINCT mesh_node_id FROM pc_device_links "
        "WHERE label = ? AND state = 'active' AND paused_at IS NULL"
    )
    rows = await statement.bind(label).all()
    found = [
        row["mesh_node_id"]
        for row in rows
        if isinstance(row, dict) and row.get("mesh_node_id")
    ]
    if not found:
        return None
    if len(found) > 1:
        raise ToolError("PC_AMBIGUOUS")
    return found[0]


async def _count_linked_accounts(store: Any, device_id: str) -> int:
    db = _require_db(store)
    statement = db.prepare(
        "SELECT COUNT(DISTINCT user_id) AS n FROM pc_device_links "
        "WHERE mesh_node_id = ? AND state = 'active' AND paused_at IS NULL"
    )
    row = await statement.bind(device_id).first()
    if not isinstance(row, dict):
        return 0
    try:
        return int(row.get("n") or 0)
    except (TypeError, ValueError):
        return 0


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