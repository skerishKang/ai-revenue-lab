"""Account-deletion work outside the Chat database (#7557).

The deletion batch removes the account's rows atomically, but four kinds of
data live elsewhere and used to be swept best-effort or not at all:

* ``r2_key``    — one private object whose key a metadata row named
  (claw documents, B66 quote assets and templates) or that is derived from the
  account (the MCP browser-continuity object);
* ``r2_prefix`` — every object under a per-account prefix: the full message
  originals and PC screenshots of each conversation
  (``claw-model-context/v1/<conversation>/``), chat attachments
  (``chat-attachments/<user>/``), project originals (``projects/<user>/``),
  document-conversion outputs (``documents/<user>/``) and certified B66
  bundles (``b66/certified-quote-bundles/<saved skill>/``);
* ``google_workspace`` — every Google connector grant of the account's
  workspace: revoked at Google and deleted from the OAuth authority;
* ``file_lane`` — the account's COM2 file-lane directory.

ORDER
    1. ``collect_cleanup_targets`` reads the targets BEFORE the batch, because
       the rows are the index (a conversation's prefix is unknowable once its
       row is gone). Nothing is capped: every target becomes an item.
    2. ``pending_insert_statements`` joins the deletion batch, so the items are
       committed in the same transaction that deletes the rows. Either both
       happen or neither does.
    3. ``drain`` runs right after the batch, inside the request, Google first.
       A finished item is deleted. A failed item stays with ``attempts`` + 1
       and is retried by the daily purge run (``app.expired_purge``) and by
       the next drain. Every handler is idempotent: an object or grant that is
       already gone is a finished item. #7605: the request path passes a
       ``deadline`` and a ``call_timeout`` so a slow external store cannot
       hold the withdrawal response; whatever the budget does not cover stays
       pending for the next pass.

The caller reports ``pending`` > 0 to the user instead of pretending the
deletion is complete. The account itself is already gone at that point, so a
failing external store can never leave the account half-deleted and blocked.

Only kinds, counts and outcomes are ever logged — never a key, a target, a
user id or a workspace reference.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .history import _rows_from_result

LOG = logging.getLogger("padiem_chat.account_cleanup")

KIND_R2_KEY = "r2_key"
KIND_R2_PREFIX = "r2_prefix"
KIND_GOOGLE_WORKSPACE = "google_workspace"
KIND_FILE_LANE = "file_lane"
# #7604: the common account was deleted (remove_product_link succeeded) but
# the shared-login complete call failed. The target is the canonical subject
# id only; the drain retries the shared-login finish (prepare → complete).
KIND_SHARED_ACCOUNT_COMPLETE = "shared_account_complete"
KINDS = (
    KIND_GOOGLE_WORKSPACE, KIND_R2_KEY, KIND_R2_PREFIX, KIND_FILE_LANE,
    KIND_SHARED_ACCOUNT_COMPLETE,
)

TABLE = "account_deletion_cleanup_pending"

#: Metadata tables whose rows name one private object of the account.
OBJECT_KEY_TABLES: tuple[str, ...] = (
    "claw_document_metadata",
    "b66_quote_asset",
    "b66_template_source",
)

CONTEXT_PREFIX = "claw-model-context/v1/"
ATTACHMENT_PREFIX = "chat-attachments/"
PROJECT_PREFIX = "projects/"
DOCUMENT_PREFIX = "documents/"
CERTIFIED_BUNDLE_PREFIX = "b66/certified-quote-bundles/"

#: One drain call handles at most this many items; the rest wait for the next.
DRAIN_BATCH = 500
#: Prefix deletion lists and deletes page by page; this bounds one prefix per pass.
_PREFIX_ROUNDS = 50


def item_id(kind: str, target: str) -> str:
    return hashlib.sha256(f"{kind}\n{target}".encode("utf-8")).hexdigest()


def _plain_segment(value: Any) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value in (".", "..")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        return None
    return value


async def _table_exists(db: Any, table: str) -> bool:
    found = await db.prepare(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?"
    ).bind(table).first()
    return found is not None


async def _column_values(db: Any, sql: str, *params: Any, column: str) -> list[str]:
    result = await db.prepare(sql).bind(*params).run()
    values: list[str] = []
    for row in _rows_from_result(result):
        value = row.get(column) if isinstance(row, dict) else None
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    return values


def _browser_context_key(owner_id: str, token_id: str, device_id: str) -> str:
    """The exact key ``mcp_browser_context`` writes, from its own function."""
    from .mcp_browser_context import _key

    return _key({"owner_id": owner_id, "token_id": token_id, "device_id": device_id})


def _scope_devices(raw: Any) -> list[str]:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else None
    except ValueError:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("devices") or parsed.get("device_ids")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str) and item]


async def _browser_context_keys(db: Any, user_id: str) -> list[str]:
    """Every browser-continuity object this account can have written.

    The object key hashes (owner, token, device); a token may be pointed at
    any of the owner's PCs, so every recorded device is paired with every
    token. Deleting a key that was never written is harmless.
    """
    if not await _table_exists(db, "padiem_mcp_tokens"):
        return []
    tokens = await _column_values(
        db, "SELECT id FROM padiem_mcp_tokens WHERE user_id = ?", user_id, column="id")
    if not tokens:
        return []
    devices = await _column_values(
        db, "SELECT device_id FROM padiem_mcp_tokens WHERE user_id = ?", user_id,
        column="device_id")
    try:
        scopes = await _column_values(
            db, "SELECT device_scope_json FROM padiem_mcp_tokens WHERE user_id = ?"
            " AND device_scope_json IS NOT NULL", user_id, column="device_scope_json")
    except Exception as exc:  # a host before migration 100 has no scope column
        if "no such column" not in str(exc):
            raise
        scopes = []
    for raw in scopes:
        devices.extend(device for device in _scope_devices(raw) if device not in devices)
    # The device id an MCP principal carries is the PC link's mesh node id.
    for table, column in (
        ("padiem_mcp_audit", "device_id"),
        ("padiem_mcp_approvals", "device_id"),
        ("pc_device_links", "mesh_node_id"),
    ):
        if await _table_exists(db, table):
            for device in await _column_values(
                db, f"SELECT DISTINCT {column} AS device_id FROM {table} WHERE user_id = ?",
                user_id, column="device_id",
            ):
                if device not in devices:
                    devices.append(device)
    return [
        _browser_context_key(user_id, token, device)
        for token in tokens for device in devices
    ]


async def collect_cleanup_targets(
    db: Any, user_id: str, *, google_workspace_ref: str | None = None,
) -> list[tuple[str, str]]:
    """Every external item of this account, read before the deletion batch.

    A missing table contributes nothing (a host behind that migration has no
    such data); any other read failure is raised, so a half-read inventory is
    never committed as if it were complete.
    """
    owner = _plain_segment(user_id)
    if owner is None:
        raise ValueError("account id is not a plain identifier")
    targets: list[tuple[str, str]] = []

    def add(kind: str, target: str) -> None:
        pair = (kind, target)
        if pair not in targets:
            targets.append(pair)

    if isinstance(google_workspace_ref, str) and google_workspace_ref:
        add(KIND_GOOGLE_WORKSPACE, google_workspace_ref)
    for table in OBJECT_KEY_TABLES:
        if await _table_exists(db, table):
            for key in await _column_values(
                db, f"SELECT object_key FROM {table} WHERE user_id = ?", user_id,
                column="object_key",
            ):
                add(KIND_R2_KEY, key)
    if await _table_exists(db, "conversations"):
        for conversation_id in await _column_values(
            db, "SELECT id FROM conversations WHERE user_id = ?", user_id, column="id",
            # No deleted_at filter on purpose: the account deletion erases the
            # 30-day retention copies of marked conversations now (#7388).
        ):
            segment = _plain_segment(conversation_id)
            if segment is not None:
                add(KIND_R2_PREFIX, CONTEXT_PREFIX + segment + "/")
    for key in await _browser_context_keys(db, user_id):
        add(KIND_R2_KEY, key)
    add(KIND_R2_PREFIX, ATTACHMENT_PREFIX + owner + "/")
    add(KIND_R2_PREFIX, PROJECT_PREFIX + owner + "/")
    add(KIND_R2_PREFIX, DOCUMENT_PREFIX + owner + "/")
    if await _table_exists(db, "b66_saved_quote_skill"):
        for row_id in await _column_values(
            db, "SELECT id FROM b66_saved_quote_skill WHERE user_id = ?", user_id, column="id",
        ):
            segment = _plain_segment(row_id)
            if segment is not None:
                add(KIND_R2_PREFIX, CERTIFIED_BUNDLE_PREFIX + segment + "/")
    add(KIND_FILE_LANE, owner)
    return targets


def pending_insert_statements(db: Any, targets: Iterable[tuple[str, str]], *, now: str) -> list:
    """Statements that join the deletion batch; a re-run never duplicates an item."""
    return [
        db.prepare(
            f"INSERT INTO {TABLE} (item_id, kind, target, created_at, attempts)"
            " VALUES (?,?,?,?,0) ON CONFLICT(item_id) DO NOTHING"
        ).bind(item_id(kind, target), kind, target, now)
        for kind, target in targets
    ]


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _listing_keys(listing: Any) -> tuple[list[str], bool]:
    objects = getattr(listing, "objects", None)
    truncated = getattr(listing, "truncated", False)
    if objects is None and isinstance(listing, dict):
        objects, truncated = listing.get("objects"), listing.get("truncated", False)
    keys: list[str] = []
    for item in objects or ():
        key = getattr(item, "key", None)
        if key is None and isinstance(item, dict):
            key = item.get("key")
        if isinstance(key, str) and key:
            keys.append(key)
    return keys, bool(truncated)


async def _delete_prefix(bucket: Any, prefix: str) -> bool:
    """Delete every object under ``prefix``; ``True`` once the prefix is empty."""
    lister = getattr(bucket, "list", None)
    if not callable(lister):
        raise RuntimeError("object store cannot list a prefix")
    for _ in range(_PREFIX_ROUNDS):
        keys, _truncated = _listing_keys(await _maybe(lister({"prefix": prefix, "limit": 1000})))
        if not keys:
            tidy = getattr(bucket, "remove_empty_prefix", None)
            if callable(tidy):
                await _maybe(tidy(prefix))
            return True
        for key in keys:
            if not key.startswith(prefix):
                raise RuntimeError("object store listed a key outside the prefix")
            await _maybe(bucket.delete(key))
    # Still not empty after the bounded rounds: the next pass continues.
    return False


class CleanupPorts:
    """The external stores one drain may reach. ``None`` means "not reachable here"."""

    def __init__(self, *, bucket: Any = None, google: Any = None,
                 file_lane: Any = None, file_lane_absent_is_done: bool = False,
                 shared_account_finish: Any = None):
        self.bucket = bucket
        self.google = google
        self.file_lane = file_lane
        self.file_lane_absent_is_done = file_lane_absent_is_done
        # #7604: async callable(subject_id) -> bool for the shared-login finish
        # (prepare → complete). None means the lane cannot reach padiem-auth.
        self.shared_account_finish = shared_account_finish


async def _handle(kind: str, target: str, ports: CleanupPorts) -> bool | None:
    """``True`` done, ``False`` failed (retry), ``None`` store not reachable here."""
    if kind == KIND_GOOGLE_WORKSPACE:
        purge = getattr(ports.google, "purge_workspace_credentials", None)
        if not callable(purge):
            return None
        result = await _maybe(purge(workspace_ref=target))
        remaining = result.get("remaining") if isinstance(result, dict) else None
        return remaining == 0
    if kind == KIND_R2_KEY:
        if ports.bucket is None:
            return None
        await _maybe(ports.bucket.delete(target))
        return True
    if kind == KIND_R2_PREFIX:
        if ports.bucket is None:
            return None
        return await _delete_prefix(ports.bucket, target)
    if kind == KIND_FILE_LANE:
        client = ports.file_lane
        if client is None or not getattr(client, "ready", False):
            # The serving host knows whether a lane exists; without one there
            # is no directory to purge. A timer run without lane settings
            # cannot tell, so it leaves the item for the serving host.
            return True if ports.file_lane_absent_is_done else None
        await _maybe(client.purge_user(target))
        return True
    if kind == KIND_SHARED_ACCOUNT_COMPLETE:
        finish = getattr(ports, "shared_account_finish", None)
        if not callable(finish):
            # The shared-login RPC is not reachable from this lane: the item
            # stays for a run whose environment names the RPC secret.
            return None
        # padiem-auth answers {ok: true, deleted: true} both for a fresh
        # finalize and for an already-finalized account, so one success shape
        # covers "already done" (see the worker's complete handler).
        await _maybe(finish(target))
        return True
    return False


async def drain(
    db: Any,
    ports: CleanupPorts,
    *,
    item_ids: Iterable[str] | None = None,
    limit: int = DRAIN_BATCH,
    now: datetime | None = None,
    deadline: float | None = None,
    call_timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, int]:
    """Run pending items; returns ``{"done", "failed", "waiting", "pending"}`` counts.

    ``item_ids`` narrows the pass to one deletion's items (the request path);
    without it the oldest items run first (the timer path). ``pending`` is what
    is still left for these items after the pass.

    #7605: ``deadline`` is a ``time.monotonic()`` reading after which no new
    item is started — the rest stay pending for the next pass, so a request
    that called this answers within its budget. ``call_timeout`` caps one
    external call; a call cut by it counts as a failed attempt (the item stays
    idempotent for the retry). Both are off by default: the timer path keeps
    its batch-count bound only. ``clock`` exists so tests can move time
    without sleeping.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    wanted = list(dict.fromkeys(item_ids)) if item_ids is not None else None
    rows: list[dict[str, Any]] = []
    if wanted is not None:
        for start in range(0, len(wanted), 100):
            chunk = wanted[start:start + 100]
            marks = ",".join("?" for _ in chunk)
            result = await db.prepare(
                f"SELECT item_id, kind, target FROM {TABLE} WHERE item_id IN ({marks})"
            ).bind(*chunk).run()
            rows.extend(_rows_from_result(result))
    else:
        result = await db.prepare(
            f"SELECT item_id, kind, target FROM {TABLE} ORDER BY created_at, item_id LIMIT ?"
        ).bind(int(limit)).run()
        rows.extend(_rows_from_result(result))
    order = {kind: index for index, kind in enumerate(KINDS)}
    rows.sort(key=lambda row: order.get(row.get("kind"), len(KINDS)))
    counts = {"done": 0, "failed": 0, "waiting": 0}
    for row in rows[: max(int(limit), 0)]:
        kind, target, ident = row.get("kind"), row.get("target"), row.get("item_id")
        if not isinstance(kind, str) or not isinstance(target, str) or not isinstance(ident, str):
            continue
        if deadline is not None and clock() >= deadline:
            # The budget is spent; the rest of these items stay pending for
            # the next pass (the daily purge run continues them).
            break
        try:
            if call_timeout is not None:
                outcome = await asyncio.wait_for(_handle(kind, target, ports), call_timeout)
            else:
                outcome = await _handle(kind, target, ports)
        except Exception:
            # A call the budget cut is a failed attempt like any other: the
            # row stays, ``attempts`` goes up, the retry is idempotent.
            outcome = False
        if outcome is True:
            await db.prepare(f"DELETE FROM {TABLE} WHERE item_id = ?").bind(ident).run()
            counts["done"] += 1
        elif outcome is False:
            await db.prepare(
                f"UPDATE {TABLE} SET attempts = attempts + 1, last_attempt_at = ? WHERE item_id = ?"
            ).bind(stamp, ident).run()
            counts["failed"] += 1
        else:
            counts["waiting"] += 1
    if wanted is not None:
        left = 0
        for start in range(0, len(wanted), 100):
            chunk = wanted[start:start + 100]
            marks = ",".join("?" for _ in chunk)
            row = await db.prepare(
                f"SELECT COUNT(*) AS n FROM {TABLE} WHERE item_id IN ({marks})"
            ).bind(*chunk).first()
            left += int((row or {}).get("n") or 0) if isinstance(row, dict) else 0
    else:
        row = await db.prepare(f"SELECT COUNT(*) AS n FROM {TABLE}").first()
        left = int((row or {}).get("n") or 0) if isinstance(row, dict) else 0
    counts["pending"] = left
    LOG.info(
        "account_cleanup done=%d failed=%d waiting=%d pending=%d",
        counts["done"], counts["failed"], counts["waiting"], counts["pending"],
    )
    return counts
