#!/usr/bin/env python3
"""Manual pilot operations recording for Personal Edition.

Provides concise operator documentation and safe local records for:
- participant invitation and consent confirmation
- one free sample edition
- offer of seven subsequent editions for KRW 4,900
- manual recording of payment evidence without storing payer identity
- correction time, engagement, feedback, AI cost, infrastructure cost,
  and revenue fields
- deletion/revocation workflow

No payment integration, email automation, public signup, or actual
participant data is created by this script.

Usage:
    python -m scripts.pilot_ops record   --participant PID --edition EID
    python -m scripts.pilot_ops status   --participant PID
    python -m scripts.pilot_ops evidence  --output PATH
    python -m scripts.pilot_ops delete   --participant PID
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from app.db import apply_migrations, get_connection


def _create_pilot_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pilot_records (
            id TEXT PRIMARY KEY,
            participant_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            edition_id TEXT,
            record_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _record(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    record_type: str,
    edition_id: str | None,
    data: dict[str, Any],
) -> str:
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        "INSERT INTO pilot_records (id, participant_id, record_type, edition_id, "
        "record_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (record_id, participant_id, record_type, edition_id,
         json.dumps(data, ensure_ascii=False), now),
    )
    conn.commit()
    return record_id


def record_invitation(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    contact_method: str = "manual",
    consent_confirmed: bool = False,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="invitation",
        edition_id=None,
        data={
            "contact_method": contact_method,
            "consent_confirmed": consent_confirmed,
            "notes": notes,
        },
    )


def record_sample_edition(
    conn: sqlite3.Connection,
    participant_id: str,
    edition_id: str,
    *,
    edition_number: int = 1,
    is_free: bool = True,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="sample_edition",
        edition_id=edition_id,
        data={
            "edition_number": edition_number,
            "is_free": is_free,
            "notes": notes,
        },
    )


def record_offer(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    editions_count: int = 7,
    price_krw: int = 4900,
    offer_date: str | None = None,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="offer",
        edition_id=None,
        data={
            "editions_count": editions_count,
            "price_krw": price_krw,
            "offer_date": offer_date or datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        },
    )


def record_payment_evidence(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    amount_krw: int,
    payment_method: str,
    payment_date: str | None = None,
    evidence_description: str = "",
    notes: str = "",
) -> str:
    """Record payment evidence without storing payer identity or sensitive
    payment details."""
    return _record(
        conn,
        participant_id=participant_id,
        record_type="payment_evidence",
        edition_id=None,
        data={
            "amount_krw": amount_krw,
            "payment_method": payment_method,
            "payment_date": payment_date or datetime.now(timezone.utc).isoformat(),
            "evidence_description": evidence_description,
            "notes": notes,
        },
    )


def record_correction(
    conn: sqlite3.Connection,
    participant_id: str,
    edition_id: str,
    *,
    correction_minutes: float,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="correction",
        edition_id=edition_id,
        data={
            "correction_minutes": correction_minutes,
            "notes": notes,
        },
    )


def record_engagement(
    conn: sqlite3.Connection,
    participant_id: str,
    edition_id: str,
    *,
    feedback_text: str | None = None,
    engagement_signal: str = "",
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="engagement",
        edition_id=edition_id,
        data={
            "feedback_text": feedback_text,
            "engagement_signal": engagement_signal,
            "notes": notes,
        },
    )


def record_costs(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    ai_cost_krw: float = 0.0,
    infrastructure_cost_krw: float = 0.0,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="costs",
        edition_id=None,
        data={
            "ai_cost_krw": ai_cost_krw,
            "infrastructure_cost_krw": infrastructure_cost_krw,
            "notes": notes,
        },
    )


def record_revenue(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    revenue_krw: float = 0.0,
    notes: str = "",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="revenue",
        edition_id=None,
        data={
            "revenue_krw": revenue_krw,
            "notes": notes,
        },
    )


def record_deletion(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    reason: str = "",
    requested_by: str = "operator",
) -> str:
    return _record(
        conn,
        participant_id=participant_id,
        record_type="deletion_request",
        edition_id=None,
        data={
            "reason": reason,
            "requested_by": requested_by,
        },
    )


def get_participant_records(
    conn: sqlite3.Connection,
    participant_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, participant_id, record_type, edition_id, record_json, "
        "created_at FROM pilot_records WHERE participant_id = ? "
        "ORDER BY created_at",
        (participant_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "participant_id": r["participant_id"],
            "record_type": r["record_type"],
            "edition_id": r["edition_id"],
            "record": json.loads(r["record_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def export_pilot_evidence(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, participant_id, record_type, edition_id, record_json, "
        "created_at FROM pilot_records ORDER BY created_at"
    ).fetchall()
    records = [
        {
            "id": r["id"],
            "participant_id": r["participant_id"],
            "record_type": r["record_type"],
            "edition_id": r["edition_id"],
            "record": json.loads(r["record_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    participants = list({r["participant_id"] for r in records})
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "participants": participants,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Personal Edition pilot operations"
    )
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="Record a pilot event")
    rec.add_argument("--participant", required=True)
    rec.add_argument("--type", required=True,
                     choices=["invitation", "sample_edition", "offer",
                              "payment_evidence", "correction", "engagement",
                              "costs", "revenue", "deletion_request"])
    rec.add_argument("--edition", default=None)
    rec.add_argument("--data", default="{}", help="JSON data for the record")
    rec.add_argument("--db", default="var/pilot.db")

    stat = sub.add_parser("status", help="Show participant records")
    stat.add_argument("--participant", required=True)
    stat.add_argument("--db", default="var/pilot.db")

    ev = sub.add_parser("evidence", help="Export all pilot evidence")
    ev.add_argument("--output", required=True)
    ev.add_argument("--db", default="var/pilot.db")

    dl = sub.add_parser("delete", help="Record deletion request")
    dl.add_argument("--participant", required=True)
    dl.add_argument("--reason", default="")
    dl.add_argument("--db", default="var/pilot.db")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    db_path = args.db
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = get_connection(db_path)
    migrations_dir = str(_DIR / "migrations")
    apply_migrations(conn, migrations_dir)
    _create_pilot_table(conn)

    if args.command == "record":
        data = json.loads(args.data)
        if args.type == "invitation":
            rid = record_invitation(
                conn, args.participant,
                contact_method=data.get("contact_method", "manual"),
                consent_confirmed=data.get("consent_confirmed", False),
                notes=data.get("notes", ""),
            )
        elif args.type == "sample_edition":
            if not args.edition:
                print("error: --edition required for sample_edition", file=sys.stderr)
                sys.exit(1)
            rid = record_sample_edition(
                conn, args.participant, args.edition,
                edition_number=data.get("edition_number", 1),
                is_free=data.get("is_free", True),
                notes=data.get("notes", ""),
            )
        elif args.type == "offer":
            rid = record_offer(
                conn, args.participant,
                editions_count=data.get("editions_count", 7),
                price_krw=data.get("price_krw", 4900),
                offer_date=data.get("offer_date"),
                notes=data.get("notes", ""),
            )
        elif args.type == "payment_evidence":
            rid = record_payment_evidence(
                conn, args.participant,
                amount_krw=data.get("amount_krw", 0),
                payment_method=data.get("payment_method", "manual"),
                payment_date=data.get("payment_date"),
                evidence_description=data.get("evidence_description", ""),
                notes=data.get("notes", ""),
            )
        elif args.type == "correction":
            if not args.edition:
                print("error: --edition required for correction", file=sys.stderr)
                sys.exit(1)
            rid = record_correction(
                conn, args.participant, args.edition,
                correction_minutes=data.get("correction_minutes", 0),
                notes=data.get("notes", ""),
            )
        elif args.type == "engagement":
            if not args.edition:
                print("error: --edition required for engagement", file=sys.stderr)
                sys.exit(1)
            rid = record_engagement(
                conn, args.participant, args.edition,
                feedback_text=data.get("feedback_text"),
                engagement_signal=data.get("engagement_signal", ""),
                notes=data.get("notes", ""),
            )
        elif args.type == "costs":
            rid = record_costs(
                conn, args.participant,
                ai_cost_krw=data.get("ai_cost_krw", 0),
                infrastructure_cost_krw=data.get("infrastructure_cost_krw", 0),
                notes=data.get("notes", ""),
            )
        elif args.type == "revenue":
            rid = record_revenue(
                conn, args.participant,
                revenue_krw=data.get("revenue_krw", 0),
                notes=data.get("notes", ""),
            )
        elif args.type == "deletion_request":
            rid = record_deletion(
                conn, args.participant,
                reason=data.get("reason", ""),
                requested_by=data.get("requested_by", "operator"),
            )
        print(f"recorded: {rid}")

    elif args.command == "status":
        records = get_participant_records(conn, args.participant)
        if not records:
            print(f"No records found for participant {args.participant}")
        else:
            print(f"Records for {args.participant}: {len(records)}")
            for r in records:
                print(f"  [{r['created_at']}] {r['record_type']}: {json.dumps(r['record'], ensure_ascii=False)}")

    elif args.command == "evidence":
        evidence = export_pilot_evidence(conn)
        Path(args.output).write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Evidence exported to {args.output} ({evidence['total_records']} records)")

    elif args.command == "delete":
        rid = record_deletion(conn, args.participant, reason=args.reason)
        print(f"deletion request recorded: {rid}")

    conn.close()


if __name__ == "__main__":
    main()
