"""Living Travel admin CLI.

Provides explicit, audited operator authorization bootstrap. Operator status is
NEVER derived from email, domain, or Firebase account existence — it is granted
only by an explicit identity mapping created here.

Usage:
    python -m app.admin bind-operator --firebase-uid <uid>

The Firebase UID is accepted as an argument but is never echoed to stdout, logs,
or any persisted report; only a generic confirmation is printed. The internal
operator_id is a random token unrelated to the UID.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from app import external_identity_repository as eid_repo
from app.db import apply_migrations, get_connection
from app.firebase import PROVIDER_FIREBASE


def bind_operator(firebase_uid: str) -> int:
    if not firebase_uid:
        print("error: --firebase-uid is required", file=sys.stderr)
        return 2
    apply_migrations()
    conn = get_connection()
    try:
        identity = eid_repo.ensure_identity(
            conn, PROVIDER_FIREBASE, firebase_uid, principal_type="operator", commit=False
        )
        if identity.traveler_id is not None:
            conn.rollback()
            print("error: identity already bound to a traveler", file=sys.stderr)
            return 1
        if identity.is_revoked:
            conn.rollback()
            print("error: identity is revoked", file=sys.stderr)
            return 1
        if identity.operator_id is not None:
            conn.rollback()
            print("Operator identity bound.")
            return 0
        operator_id = f"op_{secrets.token_urlsafe(16)}"
        result = eid_repo.link_operator(conn, identity.id, operator_id, commit=False)
        if result is None:
            conn.rollback()
            print("error: could not bind operator", file=sys.stderr)
            return 1
        conn.commit()
    except Exception:
        conn.rollback()
        print("error: could not bind operator", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print("Operator identity bound.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind-operator", help="Bind a Firebase UID as operator")
    bind.add_argument("--firebase-uid", required=True)
    args = parser.parse_args(argv)
    if args.command == "bind-operator":
        return bind_operator(args.firebase_uid)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
