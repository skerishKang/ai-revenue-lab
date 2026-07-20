#!/usr/bin/env python3
import argparse
import json
import sys

from app.config import settings
from app.db import apply_migrations, get_connection
from app import participant_repository as repo
from app import input_repository as input_repo
from app import edition_repository as edition_repo
from app import feedback_repository as feedback_repo


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect participant records and related data"
    )
    parser.add_argument("participant_id", help="Participant identifier to inspect")
    parser.add_argument(
        "--database",
        default=settings.database_path,
        help=f"Database path (default: {settings.database_path})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output as JSON",
    )
    args = parser.parse_args()

    conn = get_connection(args.database)
    try:
        apply_migrations(conn, "migrations")

        participant = repo.get_participant_by_id(conn, args.participant_id)
        if participant is None:
            print(
                f"Participant '{args.participant_id}' not found.",
                file=sys.stderr,
            )
            return 1

        inputs = input_repo.get_inputs_by_participant(
            conn, args.participant_id
        )
        editions = edition_repo.get_editions_by_participant(
            conn, args.participant_id
        )

        all_feedback = []
        for ed in editions:
            fb = feedback_repo.get_feedback_by_edition(conn, ed.id)
            all_feedback.extend(fb)

        if args.as_json:
            data = {
                "participant": {
                    "id": participant.id,
                    "display_name": participant.display_name,
                    "preferred_language": participant.preferred_language,
                    "status": participant.status,
                    "created_at": participant.created_at,
                    "updated_at": participant.updated_at,
                    "deleted_at": participant.deleted_at,
                },
                "inputs": [
                    {
                        "id": i.id,
                        "sequence_number": i.sequence_number,
                        "raw_text": i.raw_text[:100],
                        "submitted_at": i.submitted_at,
                        "deleted_at": i.deleted_at,
                    }
                    for i in inputs
                ],
                "editions": [
                    {
                        "id": e.id,
                        "edition_number": e.edition_number,
                        "generation_status": e.generation_status,
                        "publication_state": e.publication_state,
                        "drafted_at": e.drafted_at,
                    }
                    for e in editions
                ],
                "feedback": [
                    {
                        "id": f.id,
                        "edition_id": f.edition_id,
                        "direction_choices": f.direction_choices,
                        "submitted_at": f.submitted_at,
                    }
                    for f in all_feedback
                ],
            }
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"Participant: {participant.id}")
            print(f"  Display name: {participant.display_name}")
            print(f"  Language: {participant.preferred_language}")
            print(f"  Status: {participant.status}")
            print(f"  Created: {participant.created_at}")
            if participant.deleted_at:
                print(f"  Deleted: {participant.deleted_at}")
            print()
            print(f"Inputs ({len(inputs)}):")
            for inp in inputs:
                print(
                    f"  [{inp.sequence_number}] {inp.id} "
                    f"({inp.submitted_at})"
                )
            print()
            print(f"Editions ({len(editions)}):")
            for ed in editions:
                print(
                    f"  [{ed.edition_number}] {ed.id} "
                    f"status={ed.generation_status} "
                    f"pub={ed.publication_state}"
                )
            print()
            print(f"Feedback ({len(all_feedback)}):")
            for fb in all_feedback:
                print(
                    f"  {fb.id} edition={fb.edition_id} "
                    f"dir={fb.direction_choices}"
                )

        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
