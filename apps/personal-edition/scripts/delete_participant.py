#!/usr/bin/env python3
import argparse
import sys

from app.config import settings
from app.db import apply_migrations, get_connection
from app import participant_repository as repo


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soft-delete a participant and revoke token access"
    )
    parser.add_argument("participant_id", help="Participant identifier to delete")
    parser.add_argument(
        "--database",
        default=settings.database_path,
        help=f"Database path (default: {settings.database_path})",
    )
    args = parser.parse_args()

    conn = get_connection(args.database)
    try:
        apply_migrations(conn, "migrations")
        deleted = repo.delete_participant(conn, args.participant_id)
        if deleted:
            print(f"Participant '{args.participant_id}' deleted successfully.")
            print("Token access has been revoked.")
            return 0
        else:
            print(
                f"Participant '{args.participant_id}' not found "
                "or already deleted.",
                file=sys.stderr,
            )
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
