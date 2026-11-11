"""Account-deletion object storage cleanup (operations doc §3, 2026-11-11).

The withdrawal batch removes the D1 rows that reference private R2 objects,
but production D1 never enforces foreign keys and the objects themselves are
not rows: without this pass the bytes outlive the account. The key inventory
is collected BEFORE the batch (the rows are the index) and the deletes run
AFTER it, so a crash between the two leaves unreachable bytes for the later
batch sweep rather than a live reference to a deleted account.

Every statement here is per user prefix:

* ``claw_document_metadata`` — one row per claw R2 object (documents,
  web-office originals, workcopies, revisions), ``user_id`` since 080/080a;
* ``b66_quote_asset`` — quotation logo/stamp images in private R2;
* ``b66_template_source`` — uploaded quotation templates in private R2.

The file lane (COM2) keeps its own per-owner directory; its purge is a
separate signed request issued by :mod:`app.file_lane`, not an R2 delete.
"""
from __future__ import annotations

import inspect

from .history import _rows_from_result

#: Bounded sweep size. A withdrawn account's object count is far below this;
#: the bound exists so a pathological row never turns the withdrawal response
#: path into an unbounded loop.
_MAX_OBJECT_DELETIONS = 1000

#: The metadata tables that index this account's private R2 objects, each
#: holding ``object_key`` under the account key.
_OBJECT_KEY_TABLES: tuple[str, ...] = (
    "claw_document_metadata",
    "b66_quote_asset",
    "b66_template_source",
)


async def collect_account_object_keys(db, user_id: str) -> list[str]:
    """Object keys that name this account, read before the deletion batch.

    A missing metadata table contributes nothing (a host that has not applied
    the migration has no such objects); any other read failure is raised, so a
    half-inventoried sweep can never look complete.
    """
    keys: list[str] = []
    for table in _OBJECT_KEY_TABLES:
        exists = await db.prepare(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?"
        ).bind(table).first()
        if exists is None:
            continue
        result = await db.prepare(
            f"SELECT object_key FROM {table} WHERE user_id = ? LIMIT ?"
        ).bind(user_id, _MAX_OBJECT_DELETIONS - len(keys)).run()
        for row in _rows_from_result(result):
            value = row.get("object_key")
            if isinstance(value, str) and value:
                keys.append(value)
        if len(keys) >= _MAX_OBJECT_DELETIONS:
            break
    return keys


async def delete_account_objects(bucket, keys: list[str]) -> int:
    """Best-effort per-key delete of the collected objects; returns the count."""
    if bucket is None:
        return 0
    deleted = 0
    for key in keys[:_MAX_OBJECT_DELETIONS]:
        try:
            result = bucket.delete(key)
            if inspect.isawaitable(result):
                await result
            deleted += 1
        except Exception:
            # Unreachable bytes, not a live reference; the operations doc keeps
            # backup rotation as the bounded backstop. The withdrawal itself
            # never fails on this pass.
            continue
    return deleted
