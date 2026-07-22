#!/usr/bin/env python3
import argparse
import sys

from app.config import settings
from app.db import apply_migrations, get_connection
from app import participant_repository as repo


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision a new participant and print the one-time token"
    )
    parser.add_argument("participant_id", help="Unique participant identifier")
    parser.add_argument("display_name", help="Human-readable display name")
    parser.add_argument(
        "--language",
        choices=["ko", "en"],
        default="ko",
        help="Preferred language (default: ko)",
    )
    parser.add_argument(
        "--database",
        default=settings.database_path,
        help=f"Database path (default: {settings.database_path})",
    )
    args = parser.parse_args()

    conn = get_connection(args.database)
    try:
        apply_migrations(conn, "migrations")
        result = repo.create_participant(
            conn,
            participant_id=args.participant_id,
            display_name=args.display_name,
            preferred_language=args.language,
        )
        print(f"Participant created: {result.participant.id}")
        print(f"Display name: {result.participant.display_name}")
        print(f"Language: {result.participant.preferred_language}")
        print(f"Status: {result.participant.status}")
        print(f"Created at: {result.participant.created_at}")
        print()
        print("ONE-TIME TOKEN (store securely, will not be shown again):")
        print(result.one_time_token)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
