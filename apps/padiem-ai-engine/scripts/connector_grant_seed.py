"""WO-10 ACT-1: connector grant seed/revoke/list script (D1 references only).

Inserts, revokes, or lists Gmail connector grant REFERENCES (no credential
material) in the `padiem_engine_connector_grants` D1 table through
`wrangler d1 execute`. Credential values (client_id, client_secret, refresh_token)
are never accepted as arguments and never read here.

Values are validated against the same rules the Engine Gmail grant seam uses
(`apps/padiem-ai-engine/app/connector_bindings.py` + `gmail_tool_binding`):
- `app_id` must equal `GMAIL_REFERENCE_APP_ID` and match the canonical identifier
  charset (no quotes, whitespace, semicolons);
- `agent_id` must equal `GMAIL_MAIL_READER_AGENT_ID` and match the canonical
  agent-id grammar;
- `binding_ref` / `actor_ref` must match the canonical identifier charset;
- `scopes` must be the Gmail readonly scope (Core token `gmail.readonly` or the
  exact provider URL `https://www.googleapis.com/auth/gmail.readonly`; the Core
  token is what gets stored, mirroring `connector_grants_d1.py`).

Invalid input exits code 2 before any D1 call. Default run (no `--execute`)
prints the SQL for review (dry-run).
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

# Reuse the Engine's canonical identifiers (contract: "import 재사용 가능하면
# import"). Make `app` importable when the script is run directly from the repo
# root (`python apps/padiem-ai-engine/scripts/connector_grant_seed.py`) or from
# inside `apps/padiem-ai-engine`. Standard library only beyond this.
if __package__ in (None, ""):
    _ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]
    if str(_ENGINE_ROOT) not in sys.path:
        sys.path.insert(0, str(_ENGINE_ROOT))

from app.connector_bindings import (
    GMAIL_CONNECTOR_ID,
    GMAIL_MAIL_READER_AGENT_ID,
    GMAIL_REFERENCE_APP_ID,
)

# Canonical identifier charset — same as `app/tool_projection.py:_IDENTIFIER_RE`.
# No quotes, whitespace, semicolons can pass, so SQL injection is impossible
# after validation.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Canonical agent-id grammar — same as `app/tool_projection.py:_CANONICAL_AGENT_ID_RE`.
_AGENT_ID_RE = re.compile(
    r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)

_CORE_GMAIL_READONLY_SCOPE = "gmail.readonly"
_PROVIDER_GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_ALLOWED_SCOPES = (_CORE_GMAIL_READONLY_SCOPE, _PROVIDER_GMAIL_READONLY_SCOPE)

# connector_id is a constant per contract: connector:google:gmail@1
_CONNECTOR_ID = GMAIL_CONNECTOR_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_args(args: argparse.Namespace) -> list[str]:
    """Return a list of validation errors (empty when valid)."""
    errors: list[str] = []
    if args.app_id != GMAIL_REFERENCE_APP_ID:
        errors.append(f"app_id must equal GMAIL_REFERENCE_APP_ID {GMAIL_REFERENCE_APP_ID!r}")
    elif not _IDENTIFIER_RE.match(args.app_id):
        errors.append("app_id contains characters outside the trusted identifier charset (no quotes, whitespace, semicolons)")
    if args.agent_id != GMAIL_MAIL_READER_AGENT_ID:
        errors.append(f"agent_id must equal GMAIL_MAIL_READER_AGENT_ID {GMAIL_MAIL_READER_AGENT_ID!r}")
    elif not _AGENT_ID_RE.match(args.agent_id):
        errors.append("agent_id does not match the canonical agent-id grammar")
    if not _IDENTIFIER_RE.match(args.binding_ref):
        errors.append("binding_ref contains characters outside the trusted identifier charset (no quotes, whitespace, semicolons)")
    if not _IDENTIFIER_RE.match(args.actor_ref):
        errors.append("actor_ref contains characters outside the trusted identifier charset (no quotes, whitespace, semicolons)")
    unknown_scopes = [s for s in args.scopes if s not in _ALLOWED_SCOPES]
    if unknown_scopes:
        errors.append(f"scopes must be one of {_ALLOWED_SCOPES!r}; got {unknown_scopes!r}")
    return errors


def _normalized_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    """Store the Core auth-scope token (mirrors connector_grants_d1.py loads)."""
    return tuple(
        _CORE_GMAIL_READONLY_SCOPE if s == _PROVIDER_GMAIL_READONLY_SCOPE else s
        for s in scopes
    )


def build_seed_sql(args: argparse.Namespace) -> str:
    scopes_json = json.dumps(list(_normalized_scopes(args.scopes)), separators=(",", ":"))
    now = _now_iso()
    row = (
        f"'{args.app_id}', '{args.agent_id}', '{_CONNECTOR_ID}', "
        f"'{args.binding_ref}', '{args.actor_ref}', '{scopes_json}', 1, "
        f"'{now}', '{now}'"
    )
    return (
        "INSERT INTO padiem_engine_connector_grants "
        "(app_id, canonical_agent_id, connector_id, binding_ref, actor_ref, "
        "granted_scopes_json, active, created_at, updated_at) VALUES ("
        f"{row}) ON CONFLICT(app_id, connector_id) DO UPDATE SET active=1, "
        "binding_ref=excluded.binding_ref, actor_ref=excluded.actor_ref, "
        "granted_scopes_json=excluded.granted_scopes_json, updated_at=excluded.updated_at;"
    )


def build_revoke_sql(args: argparse.Namespace) -> str:
    now = _now_iso()
    return (
        "UPDATE padiem_engine_connector_grants SET active=0, "
        f"updated_at='{now}' WHERE app_id='{args.app_id}' "
        f"AND connector_id='{_CONNECTOR_ID}';"
    )


def build_list_sql() -> str:
    return (
        "SELECT app_id, canonical_agent_id, binding_ref, actor_ref, active "
        "FROM padiem_engine_connector_grants;"
    )


def run_d1(sql: str) -> int:
    """Execute one D1 statement through wrangler. No credential material args."""
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
    parser.add_argument("--app-id", default=GMAIL_REFERENCE_APP_ID)
    parser.add_argument("--agent-id", default=GMAIL_MAIL_READER_AGENT_ID)
    parser.add_argument("--binding-ref", default="bind:b54-padiem-claw:claw_mail_reader")
    parser.add_argument("--actor-ref", default="actor:b54-padiem-claw:claw_mail_reader")
    parser.add_argument("--scopes", nargs="*", default=[_PROVIDER_GMAIL_READONLY_SCOPE])
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"connector_grant_seed: {error}", file=sys.stderr)
        return 2

    if args.action == "seed":
        sql = build_seed_sql(args)
    elif args.action == "revoke":
        sql = build_revoke_sql(args)
    else:
        sql = build_list_sql()

    if not args.execute:
        print(sql)
        return 0
    return run_d1(sql)


if __name__ == "__main__":
    sys.exit(main())