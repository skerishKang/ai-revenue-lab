"""Cross-process receipt for one Claw execute per Idempotency-Key (#7543 S07).

``claw_routes`` keeps a process-local replay cache: the first request for a key
executes, and a duplicate replays its reply for 60 seconds. With more than one
worker process a duplicate that lands on another process misses that cache and
executes again. This store is the shared half of the same rule, kept in the
canonical Chat database:

* ``claim`` inserts a pending row with ``ON CONFLICT DO NOTHING``. Exactly one
  process gets the row back; that process executes.
* ``complete`` stores the reply in the claimed row for the replay window, so
  every other process answers the same bytes.
* ``release`` removes a pending claim whose execution raised, so a retry is not
  held back by a reply that will never arrive.

Expired rows are removed by the next claim, so the table holds only the last
minute of receipts plus abandoned claims within their lease. Every statement
selects on the signed-in owner id; the row is deleted with the account.

Every method raises on a store failure (missing table, locked database). The
route treats any failure as "no shared receipt" and keeps the process-local
behaviour it has without this store.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

RECEIPT_CLAIMED = "claimed"
RECEIPT_PENDING = "pending"
RECEIPT_DONE = "done"

#: How long an unfinished claim keeps other processes from executing the same
#: key. It has to outlast the slowest execute: a claim that lapsed while its
#: owner was still running would let a duplicate execute a second time. A
#: process that died mid-execute leaves its claim until this lease ends; the
#: browser mints a new key for the next click, so only duplicates of that one
#: dispatch are answered ``in progress`` meanwhile.
PENDING_LEASE_SECONDS = 600.0

#: Replies above this size are not stored; the claim is released instead and
#: the process-local cache remains the only replay source for that key.
MAX_RECEIPT_BODY_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class StoredReply:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...]
    #: Seconds left in the replay window when the row was read.
    remaining_seconds: float


@dataclass(frozen=True, slots=True)
class ReceiptClaim:
    #: ``claimed`` (this caller executes), ``pending`` (another caller is
    #: executing) or ``done`` (``reply`` carries the first caller's answer).
    status: str
    claim_id: str | None = None
    reply: StoredReply | None = None


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _decode_headers(raw: Any) -> tuple[tuple[str, str], ...]:
    decoded = json.loads(raw) if isinstance(raw, str) and raw else []
    if not isinstance(decoded, list):
        raise ValueError("claw_execute_receipt_headers_invalid")
    headers: list[tuple[str, str]] = []
    for pair in decoded:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(part, str) for part in pair)
        ):
            raise ValueError("claw_execute_receipt_headers_invalid")
        headers.append((pair[0], pair[1]))
    return tuple(headers)


class D1ClawExecuteReceiptStore:
    """Owner-scoped claim/reply rows in ``claw_execute_receipts`` (108)."""

    def __init__(self, db: Any, *, clock: Callable[[], float] = time.time) -> None:
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("D1 binding is required")
        self.db = db
        # Wall clock on purpose: the expiry is compared across processes.
        self._clock = clock

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _statement(self, sql: str, *values: Any) -> Any:
        return self.db.prepare(sql).bind(*values)

    async def claim(
        self,
        user_id: str,
        idempotency_key: str,
        *,
        lease_seconds: float = PENDING_LEASE_SECONDS,
    ) -> ReceiptClaim:
        """Take the key for this caller, or report who holds it."""

        if not user_id or not idempotency_key:
            raise ValueError("invalid_receipt_identity")
        now = self._now_ms()
        # The purge is what bounds the table, and it is also what frees a key
        # whose reply window or abandoned claim has ended.
        await self._statement(
            "DELETE FROM claw_execute_receipts WHERE expires_at_ms <= ?", now
        ).run()
        claim_id = uuid.uuid4().hex
        inserted = _row_to_dict(
            await self._statement(
                "INSERT INTO claw_execute_receipts "
                "(user_id, idempotency_key, claim_id, state, created_at_ms, expires_at_ms) "
                "VALUES (?, ?, ?, 'pending', ?, ?) "
                "ON CONFLICT(user_id, idempotency_key) DO NOTHING "
                "RETURNING claim_id",
                user_id,
                idempotency_key,
                claim_id,
                now,
                now + int(lease_seconds * 1000),
            ).first()
        )
        if inserted is not None and inserted.get("claim_id") == claim_id:
            return ReceiptClaim(RECEIPT_CLAIMED, claim_id=claim_id)
        current = await self.read(user_id, idempotency_key)
        # A refused insert followed by an absent row means the holder released
        # between the two statements. The caller's wait reads the row again and
        # reports "in progress" the way an in-process duplicate does when the
        # original ends without a reply.
        return current if current is not None else ReceiptClaim(RECEIPT_PENDING)

    async def read(self, user_id: str, idempotency_key: str) -> ReceiptClaim | None:
        """The live row for this key, or ``None`` when there is none."""

        row = _row_to_dict(
            await self._statement(
                "SELECT state, status_code, headers_json, response_body, expires_at_ms "
                "FROM claw_execute_receipts WHERE user_id = ? AND idempotency_key = ?",
                user_id,
                idempotency_key,
            ).first()
        )
        if row is None:
            return None
        remaining_ms = int(row.get("expires_at_ms") or 0) - self._now_ms()
        if remaining_ms <= 0:
            return None
        if row.get("state") != RECEIPT_DONE:
            return ReceiptClaim(RECEIPT_PENDING)
        body = row.get("response_body")
        if not isinstance(body, str):
            raise ValueError("claw_execute_receipt_body_invalid")
        return ReceiptClaim(
            RECEIPT_DONE,
            reply=StoredReply(
                status_code=int(row.get("status_code")),
                body=body.encode("utf-8"),
                headers=_decode_headers(row.get("headers_json")),
                remaining_seconds=remaining_ms / 1000,
            ),
        )

    async def complete(
        self,
        user_id: str,
        idempotency_key: str,
        claim_id: str,
        *,
        status_code: int,
        headers: tuple[tuple[str, str], ...],
        body: bytes,
        ttl_seconds: float,
    ) -> bool:
        """Store the reply in this caller's claim. ``False`` when not stored."""

        if len(body) > MAX_RECEIPT_BODY_BYTES:
            return False
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return False
        stored = _row_to_dict(
            await self._statement(
                "UPDATE claw_execute_receipts SET state = 'done', status_code = ?, "
                "headers_json = ?, response_body = ?, expires_at_ms = ? "
                "WHERE user_id = ? AND idempotency_key = ? AND claim_id = ? "
                "AND state = 'pending' RETURNING claim_id",
                int(status_code),
                json.dumps([list(pair) for pair in headers], ensure_ascii=False),
                text,
                self._now_ms() + int(ttl_seconds * 1000),
                user_id,
                idempotency_key,
                claim_id,
            ).first()
        )
        return stored is not None

    async def release(self, user_id: str, idempotency_key: str, claim_id: str) -> None:
        """Drop this caller's unfinished claim; a stored reply is never removed."""

        await self._statement(
            "DELETE FROM claw_execute_receipts WHERE user_id = ? "
            "AND idempotency_key = ? AND claim_id = ? AND state = 'pending'",
            user_id,
            idempotency_key,
            claim_id,
        ).run()


__all__ = [
    "D1ClawExecuteReceiptStore",
    "MAX_RECEIPT_BODY_BYTES",
    "PENDING_LEASE_SECONDS",
    "RECEIPT_CLAIMED",
    "RECEIPT_DONE",
    "RECEIPT_PENDING",
    "ReceiptClaim",
    "StoredReply",
]
