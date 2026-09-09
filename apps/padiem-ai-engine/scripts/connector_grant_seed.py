"""Connector grant seed/revoke/list script for Engine D1 references only.

Supports the reviewed Gmail READ grant and Google Drive READ capability grant.
Credential material is never accepted as an argument and never read here.

Default connector is Gmail for backwards compatibility. Drive seeding is
fail-closed: the caller must provide the canonical OAuth ``binding_ref`` and
``actor_ref`` produced by the trusted connection flow, and the only accepted
Drive capability is ``read``. No mutation/write capability can be seeded.

Default run (no ``--execute``) prints SQL for review. ``--execute`` is a
separate Production mutation action and remains outside source/CI work.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Sequence

if __package__ in (None, ""):
    _ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]
    if str(_ENGINE_ROOT) not in sys.path:
        sys.path.insert(0, str(_ENGINE_ROOT))

from app.connector_bindings import (
    DRIVE_AGENT_ID,
    DRIVE_REFERENCE_APP_ID,
    GMAIL_CONNECTOR_ID,
    GMAIL_MAIL_READER_AGENT_ID,
    GMAIL_REFERENCE_APP_ID,
)
from padiem_ai_core.drive_capability import DRIVE_CONNECTOR_ID, DriveCapability

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_ID_RE = re.compile(
    r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)

_CORE_GMAIL_READONLY_SCOPE = "gmail.readonly"
_PROVIDER_GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_ALLOWED_GMAIL_SCOPES = (_CORE_GMAIL_READONLY_SCOPE, _PROVIDER_GMAIL_READONLY_SCOPE)
_ALLOWED_DRIVE_CAPABILITIES = (DriveCapability.READ.value,)

_DEFAULT_GMAIL_BINDING_REF = "bind:b54-padiem-claw:claw_mail_reader"
_DEFAULT_GMAIL_ACTOR_REF = "actor:b54-padiem-claw:claw_mail_reader"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connector_id(args: argparse.Namespace) -> str:
    return GMAIL_CONNECTOR_ID if args.connector == "gmail" else DRIVE_CONNECTOR_ID


def _expected_app_id(args: argparse.Namespace) -> str:
    return GMAIL_REFERENCE_APP_ID if args.connector == "gmail" else DRIVE_REFERENCE_APP_ID


def _expected_agent_id(args: argparse.Namespace) -> str:
    return GMAIL_MAIL_READER_AGENT_ID if args.connector == "gmail" else DRIVE_AGENT_ID


def _apply_connector_defaults(args: argparse.Namespace) -> None:
    if args.app_id is None:
        args.app_id = _expected_app_id(args)
    if args.agent_id is None:
        args.agent_id = _expected_agent_id(args)
    if args.connector == "gmail":
        if args.binding_ref is None:
            args.binding_ref = _DEFAULT_GMAIL_BINDING_REF
        if args.actor_ref is None:
            args.actor_ref = _DEFAULT_GMAIL_ACTOR_REF


def validate_args(args: argparse.Namespace) -> list[str]:
    """Return validation errors. Invalid input must fail before any D1 call."""
    errors: list[str] = []

    expected_app_id = _expected_app_id(args)
    expected_agent_id = _expected_agent_id(args)
    if args.app_id != expected_app_id:
        errors.append(f"app_id must equal the canonical {args.connector} app id {expected_app_id!r}")
    elif not _IDENTIFIER_RE.fullmatch(args.app_id):
        errors.append("app_id contains characters outside the trusted identifier charset")

    if args.agent_id != expected_agent_id:
        errors.append(f"agent_id must equal the canonical {args.connector} agent id {expected_agent_id!r}")
    elif not _AGENT_ID_RE.fullmatch(args.agent_id):
        errors.append("agent_id does not match the canonical agent-id grammar")

    if not isinstance(args.binding_ref, str) or not _IDENTIFIER_RE.fullmatch(args.binding_ref):
        if args.connector == "drive" and args.binding_ref is None:
            errors.append("Drive binding_ref is required and must come from the trusted OAuth connection")
        else:
            errors.append("binding_ref contains characters outside the trusted identifier charset")
    if not isinstance(args.actor_ref, str) or not _IDENTIFIER_RE.fullmatch(args.actor_ref):
        if args.connector == "drive" and args.actor_ref is None:
            errors.append("Drive actor_ref is required and must come from trusted server identity")
        else:
            errors.append("actor_ref contains characters outside the trusted identifier charset")

    if args.connector == "gmail":
        unknown_scopes = [scope for scope in args.scopes if scope not in _ALLOWED_GMAIL_SCOPES]
        if unknown_scopes:
            errors.append(f"scopes must be one of {_ALLOWED_GMAIL_SCOPES!r}; got {unknown_scopes!r}")
        if args.capabilities:
            errors.append("capabilities are not accepted for Gmail grants")
    else:
        if args.scopes:
            errors.append("scopes are not accepted for Drive grants; use --capabilities read")
        if tuple(args.capabilities) != _ALLOWED_DRIVE_CAPABILITIES:
            errors.append("Drive capabilities must be exactly ('read',); mutation/write is forbidden")

    return errors


def _normalized_gmail_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        _CORE_GMAIL_READONLY_SCOPE if scope == _PROVIDER_GMAIL_READONLY_SCOPE else scope
        for scope in scopes
    )


def build_seed_sql(args: argparse.Namespace) -> str:
    now = _now_iso()
    connector_id = _connector_id(args)
    if args.connector == "gmail":
        scopes_json = json.dumps(list(_normalized_gmail_scopes(args.scopes)), separators=(",", ":"))
        capabilities_json = "[]"
    else:
        scopes_json = "[]"
        capabilities_json = json.dumps(list(args.capabilities), separators=(",", ":"))

    row = (
        f"'{args.app_id}', '{args.agent_id}', '{connector_id}', "
        f"'{args.binding_ref}', '{args.actor_ref}', '{scopes_json}', "
        f"'{capabilities_json}', 1, '{now}', '{now}'"
    )
    return (
        "INSERT INTO padiem_engine_connector_grants "
        "(app_id, canonical_agent_id, connector_id, binding_ref, actor_ref, "
        "granted_scopes_json, granted_capabilities_json, active, created_at, updated_at) VALUES ("
        f"{row}) ON CONFLICT(app_id, connector_id) DO UPDATE SET active=1, "
        "binding_ref=excluded.binding_ref, actor_ref=excluded.actor_ref, "
        "granted_scopes_json=excluded.granted_scopes_json, "
        "granted_capabilities_json=excluded.granted_capabilities_json, "
        "updated_at=excluded.updated_at;"
    )


def build_revoke_sql(args: argparse.Namespace) -> str:
    now = _now_iso()
    return (
        "UPDATE padiem_engine_connector_grants SET active=0, "
        f"updated_at='{now}' WHERE app_id='{args.app_id}' "
        f"AND connector_id='{_connector_id(args)}';"
    )


def build_list_sql() -> str:
    return (
        "SELECT app_id, canonical_agent_id, connector_id, binding_ref, actor_ref, active "
        "FROM padiem_engine_connector_grants;"
    )


def run_d1(sql: str) -> int:
    """Execute one reviewed D1 statement through wrangler."""
    cmd = [
        "npx", "--yes", "wrangler@4", "d1", "execute", "padiem-engine",
        "--remote", "--json", "--command", sql,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--action", choices=("seed", "revoke", "list"), required=True)
    parser.add_argument("--connector", choices=("gmail", "drive"), default="gmail")
    parser.add_argument("--app-id", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--binding-ref", default=None)
    parser.add_argument("--actor-ref", default=None)
    parser.add_argument("--scopes", nargs="*", default=None)
    parser.add_argument("--capabilities", nargs="*", default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    _apply_connector_defaults(args)
    if args.scopes is None:
        args.scopes = [_PROVIDER_GMAIL_READONLY_SCOPE] if args.connector == "gmail" else []
    if args.capabilities is None:
        args.capabilities = [DriveCapability.READ.value] if args.connector == "drive" else []

    # List is read-only and does not require a connection-specific binding ref.
    if args.action == "list":
        sql = build_list_sql()
    else:
        errors = validate_args(args)
        if errors:
            for error in errors:
                print(f"connector_grant_seed: {error}", file=sys.stderr)
            return 2
        sql = build_seed_sql(args) if args.action == "seed" else build_revoke_sql(args)

    if not args.execute:
        print(sql)
        return 0
    return run_d1(sql)


if __name__ == "__main__":
    sys.exit(main())
