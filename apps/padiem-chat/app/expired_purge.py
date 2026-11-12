"""Periodic deletion of expired one-shot rows (expired-data purge, stage 1).

The targets are only the rows whose whole meaning dies with their deadline:
sign-in handoffs, reset tokens, pairing codes, approval handoffs, dispatch
receipts, OAuth states. Attachment/bookAI records, PC work records, audit and
consent ledgers keep their own retention — the owner has not decided those
retention periods yet, so this module never touches them.

Conversations are a separate, decided retention (#7388): the owner deletes a
conversation, the row is marked and disappears from every product surface, and
``app.conversation_purge`` deletes the messages, the row and the R2 originals
once the 30-day window closes. That pass is the second one this daily run makes;
it is not a table in ``PURGE_TARGETS`` because it needs three stores in one
transaction, not a single-table column cutoff.

Repositories that already delete their own expired rows are not purged twice
here: ``claw_coding_conversation_grant`` is cleaned by its own store
(claw_first_turn_authority.cleanup_abandoned / release_expired), and
``oracle_mesh_dispatch`` is documented as never deleted by the application
(migration 047: expired or consumed rows stay fail-closed for replay
protection).

The table list below is explicit, never inferred from the schema. Adding a
table to it is a reviewed decision, not a discovery.

Two storage lanes reuse the existing access layer (``prepare().bind().run()``
on a D1 binding): the COM2 host runs this module against the local SQLite file
through ``d1_sqlite.SqliteD1``, and a D1 deployment can hand the same function
its binding without a second SQL dialect.

Each table sheds at most one batch per run so a large backlog decays over
several daily ticks instead of locking the database once for a long single
DELETE. The result names only tables and row counts: never a row's content and
never a row identifier.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .conversation_purge import retention_days_from_env as conversation_retention_days_from_env
from .local_cron import _entry_mode

STATUS_PREFIX = "CHAT_EXPIRED_PURGE="

DEFAULT_GRACE_DAYS = 7
DEFAULT_BATCH = 1000

GRACE_DAYS_ENV = "PADIEM_CHAT_EXPIRED_PURGE_GRACE_DAYS"
BATCH_ENV = "PADIEM_CHAT_EXPIRED_PURGE_BATCH"


@dataclass(frozen=True)
class PurgeTarget:
    """One explicit purge decision from the stage-1 survey.

    ``column_kind`` selects the comparison value: every TEXT deadline column in
    this list stores a fixed-width UTC ISO string, so a lexicographic
    comparison with the same fixed-width cutoff is order-correct. The single
    epoch column (``claw_github_oauth_states``, migration 046) stores
    ``int(time.time())`` seconds, compared against an epoch cutoff.
    """

    table: str
    column: str
    column_kind: str  # "text" | "epoch_seconds"
    # A surviving receipt may still cite the row. Those receipts are audit
    # shaped and their foreign keys are NO ACTION, so shedding a cited parent
    # either fails the statement or orphans evidence: the pair is left alone
    # until the receipt's own retention is decided.
    key_column: str | None = None
    referenced_by: tuple[tuple[str, str], ...] = ()


# Stage-1 survey (docs/operations/EXPIRED_PURGE_20261103.md): one-shot data
# whose deadline already passed. Deliberately absent from this list:
# claw_coding_conversation_grant (self-cleaning store), oracle_mesh_dispatch
# (never deleted by the application), every audit/consent/identity/connection
# table, and conversations/messages (decided separately, #7388: the marked-row
# pass in app.conversation_purge, which must remove messages and R2 originals
# with the row instead of shedding a single table by column cutoff).
PURGE_TARGETS: tuple[PurgeTarget, ...] = (
    PurgeTarget("claw_approval_handoff", "pause_expires_at", "text"),
    PurgeTarget("claw_github_oauth_states", "expires_at", "epoch_seconds"),
    PurgeTarget(
        "claw_web_xlsx_p01_requests", "pause_expires_at", "text",
        key_column="request_ref",
        referenced_by=(("claw_web_xlsx_p01_decision_receipts", "request_ref"),),
    ),
    PurgeTarget("claw_web_xlsx_quote_write_pauses", "pause_expires_at", "text"),
    PurgeTarget(
        "claw_web_xlsx_selections", "expires_at", "text",
        key_column="selection_ref",
        referenced_by=(("claw_web_xlsx_quote_edit_receipts", "selection_ref"),),
    ),
    PurgeTarget("lovetree_login_handoffs", "expires_at", "text"),
    PurgeTarget("orchestration_continuations", "expires_at", "text"),
    PurgeTarget("padiem_android_auth_handoffs", "expires_at", "text"),
    PurgeTarget("padiem_mcp_approvals", "expires_at", "text"),
    PurgeTarget("padiem_mcp_oauth_codes", "expires_at", "text"),
    PurgeTarget("password_reset_tokens", "expires_at", "text"),
    PurgeTarget("pc_pairing_codes", "expires_at", "text"),
)


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def grace_days_from_env(env: dict[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    return _positive_int(source.get(GRACE_DAYS_ENV), DEFAULT_GRACE_DAYS)


def batch_size_from_env(env: dict[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    return _positive_int(source.get(BATCH_ENV), DEFAULT_BATCH)


def _cutoff_values(now: datetime, grace_days: int) -> dict[str, Any]:
    """The same deadline rendered once per column kind, UTC only."""
    deadline = now.astimezone(timezone.utc) - timedelta(days=grace_days)
    return {
        "text": deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "epoch_seconds": int(deadline.timestamp()),
    }


async def _table_exists(binding: Any, table: str) -> bool:
    """One bounded existence check against the shared schema table.

    An environment that has not received its migration yet skips that table
    instead of failing the whole daily pass; a present table whose DELETE then
    fails is a real storage fault and still raises.
    """
    row = await binding.prepare(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?"
    ).bind(table).first()
    return row is not None


async def purge_expired_rows(
    binding: Any,
    *,
    grace_days: int = DEFAULT_GRACE_DAYS,
    batch_size: int = DEFAULT_BATCH,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Shed one bounded batch of expired rows per target table.

    Returns ``{table: rows}`` — rows deleted, or rows a dry run would delete.
    A table the database does not have (an older environment that has not
    received its migration yet) is reported as ``0`` rows, never created, never
    retried in a loop. No row content and no row identifier is returned.
    """
    if grace_days < 0:
        raise ValueError("grace_days must not be negative")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    cutoffs = _cutoff_values(now or datetime.now(timezone.utc), grace_days)
    result: dict[str, int] = {}
    for target in PURGE_TARGETS:
        if not await _table_exists(binding, target.table):
            result[target.table] = 0
            continue
        cutoff = cutoffs[target.column_kind]
        # A receipt that still cites the row keeps it: the guard runs in both
        # modes, so a dry run counts exactly what a real pass would shed.
        source = f"{target.table} AS s" if target.referenced_by else target.table
        qualifier = "s" if target.referenced_by else target.table
        guard = "".join(
            f" AND NOT EXISTS (SELECT 1 FROM {child} AS c"
            f" WHERE c.{child_column} = s.{target.key_column})"
            for child, child_column in target.referenced_by
        )
        where = (
            f"{qualifier}.{target.column} IS NOT NULL"
            f" AND {qualifier}.{target.column} < ?{guard}"
        )
        if dry_run:
            row = await binding.prepare(
                f"SELECT COUNT(*) AS n FROM {source} WHERE {where}"
            ).bind(cutoff).first()
            result[target.table] = int(row["n"]) if row and row.get("n") is not None else 0
            continue
        # The inner LIMIT keeps every DELETE short: one batch per table per run,
        # so the writer lock is held for a bounded number of rows, not a backlog.
        outcome = await binding.prepare(
            f"DELETE FROM {target.table} WHERE rowid IN ("
            f"SELECT rowid FROM {source} WHERE {where} LIMIT ?)"
        ).bind(cutoff, batch_size).run()
        changes = (outcome.get("meta") or {}).get("changes") if isinstance(outcome, dict) else None
        result[target.table] = int(changes) if changes is not None else 0
    return result


def _full_key_deleter(bucket: Any):
    """Delete stored full originals, tolerating an absent object.

    The rows are already committed at this point, so a failed object delete is a
    leaked object, never a restored conversation. It is reported by count only
    when it succeeds; the retention pass never turns a storage hiccup into a
    red daily unit.
    """

    async def delete(keys: list[str]) -> None:
        for key in keys:
            try:
                result = bucket.delete(key)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass

    return delete


def _cleanup_ports(environ: dict[str, str], objects_dir):
    """The external stores the timer can reach, composed from the host environment."""
    from .account_cleanup_pending import CleanupPorts
    from .local_r2 import ThreadedLocalDiskR2

    google = None
    origin = str(environ.get("PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN", "") or "").strip()
    secret = str(environ.get("PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET", "") or "").strip()
    if origin and secret:
        from .connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
        from .local_service_bridge import HttpRpcBinding

        google = CloudflareGoogleOAuthWorkspaceTruth(HttpRpcBinding(origin, secret))
    file_lane = None
    lane_origin = str(environ.get("PADIEM_CHAT_FILE_LANE_ORIGIN", "") or "").strip()
    lane_secret = str(environ.get("PADIEM_CHAT_FILE_LANE_TICKET_SECRET", "") or "").strip()
    if lane_origin and lane_secret:
        from .file_lane import FileLaneClient

        file_lane = FileLaneClient(lane_origin, lane_secret)
    return CleanupPorts(
        bucket=ThreadedLocalDiskR2(objects_dir), google=google, file_lane=file_lane,
        # Without lane settings the timer cannot tell "no lane" from "not
        # configured here"; it leaves those items for the serving host.
        file_lane_absent_is_done=False,
    )


async def _drain_account_cleanup(binding: Any, environ: dict[str, str], objects_dir, *,
                                 dry_run: bool) -> dict[str, int]:
    from .account_cleanup_pending import TABLE, drain

    if not await _table_exists(binding, TABLE):
        return {"done": 0, "pending": 0}
    if dry_run:
        row = await binding.prepare(f"SELECT COUNT(*) AS n FROM {TABLE}").first()
        return {"done": 0, "pending": int((row or {}).get("n") or 0)}
    ports = _cleanup_ports(environ, objects_dir)
    try:
        result = await drain(binding, ports)
    finally:
        google_binding = getattr(getattr(ports.google, "_binding", None), "aclose", None)
        if callable(google_binding):
            await google_binding()
    return {"done": result["done"], "pending": result["pending"]}


async def _run_once_async(environ: dict[str, str], *, dry_run: bool) -> str:
    """One guarded run: entry flags, one SQLite binding, two bounded passes."""
    _entry_mode(environ)  # same entry contract as app.local_cron
    grace_days = grace_days_from_env(environ)
    batch_size = batch_size_from_env(environ)
    conversation_retention_days = conversation_retention_days_from_env(environ)

    from .d1_sqlite import SqliteD1, connect
    from .local_cpython import local_data_dir

    # The host run owns its data directory the same way app.local_cpython's
    # composition does: an absent directory is created, not an error.
    data_dir = local_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(str(data_dir / "chat.sqlite3"))
    try:
        binding = SqliteD1(connection)
        counts = await purge_expired_rows(
            binding,
            grace_days=grace_days,
            batch_size=batch_size,
            dry_run=dry_run,
        )
        # #7388 second pass: conversations whose marked window has closed. The
        # R2 originals live in the same data directory the serving process uses.
        from .conversation_purge import (
            DEFAULT_BATCH as CONVERSATION_BATCH,
            purge_deleted_conversations,
        )
        from .local_r2 import ThreadedLocalDiskR2

        purged = await purge_deleted_conversations(
            binding,
            retention_days=conversation_retention_days,
            batch_size=CONVERSATION_BATCH,
            dry_run=dry_run,
            delete_full_keys=_full_key_deleter(
                ThreadedLocalDiskR2(data_dir / "objects")
            ),
        )
        # #7557 third pass: account-deletion work left over from a request
        # (an external store was down). Same data directory, plus the Google
        # OAuth and file-lane lanes when this host's environment names them.
        cleanup = await _drain_account_cleanup(
            binding, environ, data_dir / "objects", dry_run=dry_run,
        )
    finally:
        connection.close()
    counts["account_cleanup_done"] = cleanup["done"]
    counts["account_cleanup_pending"] = cleanup["pending"]
    counts["deleted_conversations"] = purged["conversations"]
    counts["deleted_messages"] = purged["messages"]
    counts["deleted_r2_keys"] = purged["r2_keys"]
    detail = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    mode = "dry_run" if dry_run else "ok"
    return f"{STATUS_PREFIX}{mode} detail={detail}"


def run_once(environ: dict[str, str] | None = None, *, dry_run: bool = False) -> str:
    """Evaluate one purge pass and return the stable status line.

    The entry condition matches ``app.local_cron`` exactly: this is a host
    timer command, so it refuses to run outside an explicit CPython host entry
    and states the reason instead of pretending to have run.
    """
    env = os.environ if environ is None else environ
    try:
        _entry_mode(env)
    except Exception:
        # A missing host flag is a bounded state, not a traceback on the
        # timer's stdout and never a claimed purge.
        return STATUS_PREFIX + "SKIPPED reason=cpython_host_entry_required"
    try:
        return asyncio.run(_run_once_async(env, dry_run=dry_run))
    except sqlite3.OperationalError:
        return STATUS_PREFIX + "STORAGE_ERROR reason=database_unavailable"
    except Exception:
        return STATUS_PREFIX + "ERROR reason=purge_failed"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in args
    remaining = [item for item in args if item != "--dry-run"]
    if remaining not in ([], ["--once"]):
        print(STATUS_PREFIX + "INVALID_ARGUMENT", flush=True)
        return 2
    status = run_once(dry_run=dry_run)
    print(status, flush=True)
    # The timer reads the exit status, not the line: 11-03 a pass that failed
    # left the oneshot Result=success because this always returned 0.
    if status.startswith(STATUS_PREFIX + "ok ") or status.startswith(
        STATUS_PREFIX + "dry_run "
    ):
        return 0
    if status.startswith(STATUS_PREFIX + "ERROR") or status.startswith(
        STATUS_PREFIX + "STORAGE_ERROR"
    ):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
