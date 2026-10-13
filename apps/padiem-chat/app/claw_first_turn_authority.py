"""#3933 S1 — B54-private first-turn trusted coding-context authority.

Source-only, default-OFF slice. This module lets the generic Claw route bind
a server-minted conversation reference to the canonical (product, owner,
subject, tenant, route scope) BEFORE any P01/Engine dispatch, without trusting
anything the browser sent and without widening any downstream contract.

Authority model (all server-derived, never browser-supplied):

* ``reserve_first_turn_grant`` mints one grant row per protected request and
  returns a closed ``B54VerifiedCodingContextV1``. The row insert is guarded
  by the partial unique index from migration 041
  (``idx_coding_grant_live_claim``): at most one LIVE (reserved/active,
  unexpired) grant exists per (user, correlation). Concurrent reserves elect
  exactly one winner; the loser attaches to the same row.
* A reservation NEVER authorizes a dispatch by itself. Only
  ``claim_first_turn_grant`` — one guarded compare-and-set statement
  (``reserved -> active``) — admits exactly one claimant. A lost claim means
  another attempt owns the dispatch; the caller must answer status-only
  (409) and must not dispatch again. This is why "INSERT OR IGNORE followed
  by an unguarded later read" is insufficient: the read result here never
  authorizes anything.
* ``complete`` / ``fail`` / ``revoke`` are guarded terminal transitions from
  explicit from-states. An uncertain dispatch (timeout/unknown error class)
  is deliberately left ``active`` until expiry: no automatic re-dispatch,
  ``status_*`` is the only read.
* ``cleanup_abandoned`` deletes only ``reserved`` + expired rows, only for
  the calling owner, bounded by LIMIT. Expiry itself already blocks reuse;
  cleanup is hygiene, not authority.
* ``B54VerifiedCodingContextV1`` is a private server-side projection. It is
  never serialized to the browser and never forwarded to P01/Engine/B14 in
  this slice (their admission contracts stay exactly as they are).

Fail-closed defaults: the route helper is a no-op unless the host sets
``app.state.claw_first_turn_grant_enabled`` to ``True`` AND composes
``app.state.claw_first_turn_grant_store``. Either missing means OFF.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from .history import validate_conversation_id

__all__ = [
    "B54_PRODUCT_ID",
    "B54VerifiedCodingContextV1",
    "CONTEXT_ISSUER",
    "CONTEXT_VERSION",
    "D1FirstTurnGrantStore",
    "FIRST_TURN_ROUTE_SCOPES",
    "FirstTurnAuthorityError",
    "FirstTurnGrantStore",
    "GRANT_CLEANUP_LIMIT",
    "GRANT_TTL_SECONDS",
    "STATE_ACTIVE",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_RESERVED",
    "STATE_REVOKED",
    "claim_first_turn_grant",
    "complete_first_turn_grant",
    "correlation_for",
    "fail_first_turn_grant",
    "first_turn_gate_enabled",
    "reserve_first_turn_grant",
]

B54_PRODUCT_ID = "b54-padiem-claw"
CONTEXT_VERSION = "b54-verified-coding-context.v1"
CONTEXT_ISSUER = "b54-first-turn-authority"
GRANT_TTL_SECONDS = 600
GRANT_CLEANUP_LIMIT = 20
# Closed route-scope allowlist: a new protected surface needs a reviewed
# code change, never a caller-supplied string.
FIRST_TURN_ROUTE_SCOPES = frozenset({"claw_general_execute"})

STATE_RESERVED = "reserved"
STATE_ACTIVE = "active"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_REVOKED = "revoked"
_LIVE_STATES = (STATE_RESERVED, STATE_ACTIVE)

_SUBJECT_RE = re.compile(r"^sub_[0-9a-f]{32}$")
_MAX_TENANT_CHARS = 128
_GRANT_ID_PREFIX = "cg_"


def _utcnow() -> datetime:
    """Single clock indirection so tests can pin time deterministically."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class FirstTurnAuthorityError(RuntimeError):
    """Bounded denial with a fixed public code; never carries internals."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class B54VerifiedCodingContextV1:
    """Private server-minted first-turn coding authority (S1, B54-only).

    Every field is derived server-side at reservation time: the canonical
    Control Plane subject/tenant, the product pinned by the route, and
    server-minted ids. No browser value may reach this constructor; the
    route passes only revalidated server state. The context never leaves
    the server in this slice.
    """

    version: str
    issuer: str
    product_id: str
    user_id: str
    subject_id: str
    tenant_id: str
    conversation_ref: str
    route_scope: str
    issued_at: str
    expires_at: str
    correlation_key: str
    grant_id: str

    def __post_init__(self) -> None:
        if self.version != CONTEXT_VERSION:
            raise ValueError("unsupported verified coding context version")
        if self.issuer != CONTEXT_ISSUER:
            raise ValueError("untrusted verified coding context issuer")
        if self.product_id != B54_PRODUCT_ID:
            raise ValueError("verified coding context is B54-only")
        if not isinstance(self.user_id, str) or not self.user_id:
            raise ValueError("verified coding context requires an owner")
        if _SUBJECT_RE.fullmatch(self.subject_id or "") is None:
            raise ValueError("verified coding context requires a canonical subject")
        if (
            not isinstance(self.tenant_id, str)
            or not self.tenant_id
            or len(self.tenant_id) > _MAX_TENANT_CHARS
        ):
            raise ValueError("verified coding context requires a tenant")
        if validate_conversation_id(self.conversation_ref) is None:
            raise ValueError("verified coding context requires a valid conversation ref")
        if self.route_scope not in FIRST_TURN_ROUTE_SCOPES:
            raise ValueError("verified coding context has an unreviewed route scope")
        if not isinstance(self.issued_at, str) or not isinstance(self.expires_at, str):
            raise ValueError("verified coding context requires an issue window")
        if not self.issued_at or not self.expires_at or self.expires_at <= self.issued_at:
            raise ValueError("verified coding context has an invalid issue window")
        if not isinstance(self.correlation_key, str) or not self.correlation_key:
            raise ValueError("verified coding context requires a correlation key")
        if not isinstance(self.grant_id, str) or not self.grant_id:
            raise ValueError("verified coding context requires a grant id")


def correlation_for(
    user_id: str, subject_id: str, tenant_id: str, product_id: str, route_scope: str
) -> str:
    """Server-derived idempotency key for one protected first turn.

    Deterministic per (owner, subject, tenant, product, scope): concurrent
    double submits attach to the same live grant, while a terminal
    (completed/failed/revoked) or expired grant frees the key for the next
    legitimate turn. No browser value participates.
    """
    seed = "|".join(
        ["first-turn-grant.v1", user_id, subject_id, tenant_id, product_id, route_scope]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class FirstTurnGrantStore(Protocol):
    async def insert_reserved(self, row: Mapping[str, Any]) -> dict[str, Any] | None: ...
    async def find_live(
        self, user_id: str, correlation_key: str, now_iso: str
    ) -> dict[str, Any] | None: ...
    async def claim(
        self, grant_id: str, user_id: str, subject_id: str, tenant_id: str, now_iso: str
    ) -> dict[str, Any] | None: ...
    async def settle(
        self,
        grant_id: str,
        user_id: str,
        to_state: str,
        now_iso: str,
        *,
        run_ref: str | None = None,
        saved_conversation_id: str | None = None,
        from_states: tuple[str, ...] = (STATE_ACTIVE,),
    ) -> dict[str, Any] | None: ...
    async def status_by_correlation(
        self, user_id: str, correlation_key: str
    ) -> dict[str, Any] | None: ...
    async def cleanup_abandoned(
        self, user_id: str, now_iso: str, limit: int
    ) -> int: ...


_GRANT_COLUMNS = (
    "id, user_id, subject_id, tenant_id, product_id, route_scope, "
    "conversation_ref, correlation_key, state, run_ref, "
    "saved_conversation_id, issued_at, expires_at, claimed_at, completed_at"
)


class D1FirstTurnGrantStore:
    """Cloudflare D1 adapter. All dynamic values use prepared binds.

    Atomicity comes from the database, not from read-then-write in Python:
    the partial unique index arbitrates concurrent reserves and every state
    transition is a single guarded UPDATE ... RETURNING statement.
    """

    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        row = await statement.first()
        return dict(row) if row is not None else None

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def insert_reserved(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        # INSERT OR IGNORE + RETURNING: on a live-key conflict nothing is
        # inserted and nothing is returned. The caller must NOT treat the
        # fallback read as authorization — only claim() authorizes.
        return await self._first(
            "INSERT OR IGNORE INTO claw_coding_conversation_grant "
            "(id, user_id, subject_id, tenant_id, product_id, route_scope, "
            "conversation_ref, correlation_key, state, issued_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?) "
            "RETURNING id",
            row["id"],
            row["user_id"],
            row["subject_id"],
            row["tenant_id"],
            row["product_id"],
            row["route_scope"],
            row["conversation_ref"],
            row["correlation_key"],
            row["issued_at"],
            row["expires_at"],
        )

    async def find_live(
        self, user_id: str, correlation_key: str, now_iso: str
    ) -> dict[str, Any] | None:
        return await self._first(
            f"SELECT {_GRANT_COLUMNS} FROM claw_coding_conversation_grant "
            "WHERE user_id=? AND correlation_key=? "
            "AND state IN ('reserved','active') AND expires_at>?",
            user_id,
            correlation_key,
            now_iso,
        )

    async def claim(
        self, grant_id: str, user_id: str, subject_id: str, tenant_id: str, now_iso: str
    ) -> dict[str, Any] | None:
        # THE atomic claim: exactly one compare-and-set may succeed. The
        # subject/tenant are re-matched so a session change between reserve
        # and claim fails closed instead of dispatching stale authority.
        return await self._first(
            "UPDATE claw_coding_conversation_grant "
            "SET state='active', claimed_at=? "
            "WHERE id=? AND user_id=? AND subject_id=? AND tenant_id=? "
            "AND state='reserved' AND expires_at>? "
            "RETURNING id",
            now_iso,
            grant_id,
            user_id,
            subject_id,
            tenant_id,
            now_iso,
        )

    async def settle(
        self,
        grant_id: str,
        user_id: str,
        to_state: str,
        now_iso: str,
        *,
        run_ref: str | None = None,
        saved_conversation_id: str | None = None,
        from_states: tuple[str, ...] = (STATE_ACTIVE,),
    ) -> dict[str, Any] | None:
        if to_state not in (STATE_COMPLETED, STATE_FAILED, STATE_REVOKED):
            raise ValueError("settle targets a terminal state only")
        allowed = [s for s in from_states if s in (STATE_RESERVED, STATE_ACTIVE)]
        if not allowed:
            raise ValueError("settle requires a live from-state")
        placeholders = ",".join("?" for _ in allowed)
        return await self._first(
            "UPDATE claw_coding_conversation_grant "
            "SET state=?, completed_at=?, run_ref=?, saved_conversation_id=? "
            f"WHERE id=? AND user_id=? AND state IN ({placeholders}) "
            "RETURNING id",
            to_state,
            now_iso,
            run_ref,
            saved_conversation_id,
            grant_id,
            user_id,
            *allowed,
        )

    async def status_by_correlation(
        self, user_id: str, correlation_key: str
    ) -> dict[str, Any] | None:
        # Status-only read: no state change, usable after an uncertain
        # dispatch without authorizing anything.
        return await self._first(
            f"SELECT {_GRANT_COLUMNS} FROM claw_coding_conversation_grant "
            "WHERE user_id=? AND correlation_key=? "
            "ORDER BY issued_at DESC, rowid DESC LIMIT 1",
            user_id,
            correlation_key,
        )

    async def cleanup_abandoned(
        self, user_id: str, now_iso: str, limit: int
    ) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("cleanup limit must be a positive bound")
        statement = self.db.prepare(
            "SELECT id FROM claw_coding_conversation_grant "
            "WHERE user_id=? AND state='reserved' AND expires_at<=? "
            "ORDER BY expires_at ASC LIMIT ?"
        ).bind(user_id, now_iso, limit)
        rows = await statement.run()
        ids = [row["id"] for row in (rows.results or [])]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        await self._run(
            f"DELETE FROM claw_coding_conversation_grant WHERE id IN ({placeholders})",
            *ids,
        )
        check = self.db.prepare(
            f"SELECT id FROM claw_coding_conversation_grant WHERE id IN ({placeholders})"
        ).bind(*ids)
        leftovers = await check.run()
        leftover_ids = {
            row["id"] for row in (leftovers.results or []) if isinstance(row, dict)
        }
        return len(ids) - len(leftover_ids & set(ids))


class InMemoryFirstTurnGrantStore:
    """Network-free store for bounded deployments and conformance tests.

    Same reservation semantics as the D1 store: single live grant per
    (user, correlation), guarded compare-and-set transitions, status-only
    reads, owner-scoped bounded cleanup. Each public method performs its
    check-and-set with no await in between, so concurrent asyncio tasks
    cannot interleave inside the critical section. (Thread-level races are
    arbitrated by the D1 partial unique index in production; cover them
    there, not here.)
    """

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    @staticmethod
    def _live(row: dict[str, Any], now_iso: str) -> bool:
        return row["state"] in _LIVE_STATES and row["expires_at"] > now_iso

    async def insert_reserved(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        record = dict(row)
        record["state"] = STATE_RESERVED
        for existing in self._rows.values():
            if (
                existing["user_id"] == record["user_id"]
                and existing["correlation_key"] == record["correlation_key"]
                and existing["state"] in _LIVE_STATES
            ):
                return None
        self._seq += 1
        record["_seq"] = self._seq
        record.setdefault("run_ref", None)
        record.setdefault("saved_conversation_id", None)
        record.setdefault("claimed_at", None)
        record.setdefault("completed_at", None)
        self._rows[record["id"]] = record
        return {"id": record["id"]}

    async def find_live(
        self, user_id: str, correlation_key: str, now_iso: str
    ) -> dict[str, Any] | None:
        for record in self._rows.values():
            if (
                record["user_id"] == user_id
                and record["correlation_key"] == correlation_key
                and self._live(record, now_iso)
            ):
                return {k: v for k, v in record.items() if not k.startswith("_")}
        return None

    async def claim(
        self, grant_id: str, user_id: str, subject_id: str, tenant_id: str, now_iso: str
    ) -> dict[str, Any] | None:
        record = self._rows.get(grant_id)
        if record is None:
            return None
        if (
            record["user_id"] != user_id
            or record["subject_id"] != subject_id
            or record["tenant_id"] != tenant_id
            or record["state"] != STATE_RESERVED
            or not record["expires_at"] > now_iso
        ):
            return None
        record["state"] = STATE_ACTIVE
        record["claimed_at"] = now_iso
        return {"id": grant_id}

    async def settle(
        self,
        grant_id: str,
        user_id: str,
        to_state: str,
        now_iso: str,
        *,
        run_ref: str | None = None,
        saved_conversation_id: str | None = None,
        from_states: tuple[str, ...] = (STATE_ACTIVE,),
    ) -> dict[str, Any] | None:
        if to_state not in (STATE_COMPLETED, STATE_FAILED, STATE_REVOKED):
            raise ValueError("settle targets a terminal state only")
        allowed = [s for s in from_states if s in (STATE_RESERVED, STATE_ACTIVE)]
        if not allowed:
            raise ValueError("settle requires a live from-state")
        record = self._rows.get(grant_id)
        if record is None or record["user_id"] != user_id:
            return None
        if record["state"] not in allowed:
            return None
        record["state"] = to_state
        record["completed_at"] = now_iso
        if run_ref is not None:
            record["run_ref"] = run_ref
        if saved_conversation_id is not None:
            record["saved_conversation_id"] = saved_conversation_id
        return {"id": grant_id}

    async def status_by_correlation(
        self, user_id: str, correlation_key: str
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for record in self._rows.values():
            if record["user_id"] != user_id:
                continue
            if record["correlation_key"] != correlation_key:
                continue
            if best is None or (record["issued_at"], record["_seq"]) > (
                best["issued_at"],
                best["_seq"],
            ):
                best = record
        if best is None:
            return None
        return {k: v for k, v in best.items() if not k.startswith("_")}

    async def cleanup_abandoned(
        self, user_id: str, now_iso: str, limit: int
    ) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("cleanup limit must be a positive bound")
        doomed = [
            grant_id
            for grant_id, record in sorted(
                self._rows.items(), key=lambda item: item[1]["expires_at"]
            )
            if record["user_id"] == user_id
            and record["state"] == STATE_RESERVED
            and not record["expires_at"] > now_iso
        ][:limit]
        for grant_id in doomed:
            del self._rows[grant_id]
        return len(doomed)


def first_turn_gate_enabled(app_state: Any) -> bool:
    """True only when the host explicitly enabled the S1 gate."""
    return getattr(app_state, "claw_first_turn_grant_enabled", False) is True


def _context_from_row(row: Mapping[str, Any]) -> B54VerifiedCodingContextV1:
    return B54VerifiedCodingContextV1(
        version=CONTEXT_VERSION,
        issuer=CONTEXT_ISSUER,
        product_id=str(row["product_id"]),
        user_id=str(row["user_id"]),
        subject_id=str(row["subject_id"]),
        tenant_id=str(row["tenant_id"]),
        conversation_ref=str(row["conversation_ref"]),
        route_scope=str(row["route_scope"]),
        issued_at=str(row["issued_at"]),
        expires_at=str(row["expires_at"]),
        correlation_key=str(row["correlation_key"]),
        grant_id=str(row["id"]),
    )


async def reserve_first_turn_grant(
    request: Any,
    *,
    user_id: str | None,
    subject_id: str | None,
    tenant_id: str | None,
    route_scope: str,
) -> B54VerifiedCodingContextV1 | None:
    """Reserve the durable first-turn grant, or return None when OFF.

    Raises FirstTurnAuthorityError on any denial. The returned context is
    reserved but UNCLAIMED: it never authorizes a dispatch by itself.
    """
    if not first_turn_gate_enabled(request.app.state):
        return None
    if not isinstance(user_id, str) or not user_id:
        raise FirstTurnAuthorityError(
            403,
            "canonical_b54_session_unavailable",
            "인증된 Claw 실행 권한을 확인할 수 없습니다.",
        )
    if _SUBJECT_RE.fullmatch(subject_id or "") is None:
        raise FirstTurnAuthorityError(
            403,
            "canonical_b54_session_unavailable",
            "인증된 Claw 실행 권한을 확인할 수 없습니다.",
        )
    if (
        not isinstance(tenant_id, str)
        or not tenant_id
        or len(tenant_id) > _MAX_TENANT_CHARS
    ):
        # First turn included: a missing canonical tenant fails closed
        # pre-quota, never compensated by a browser-supplied workspace id.
        raise FirstTurnAuthorityError(
            403, "workspace_scope_unavailable", "대화 작업 공간을 확인할 수 없습니다."
        )
    if route_scope not in FIRST_TURN_ROUTE_SCOPES:
        raise ValueError("unreviewed first-turn route scope")
    store = getattr(request.app.state, "claw_first_turn_grant_store", None)
    if store is None:
        raise FirstTurnAuthorityError(
            503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."
        )
    issued = _iso(_utcnow())
    expires = _iso(_utcnow() + timedelta(seconds=GRANT_TTL_SECONDS))
    correlation = correlation_for(
        user_id, subject_id, tenant_id, B54_PRODUCT_ID, route_scope
    )
    # Bounded orphan hygiene on the reserve path; never blocks the reserve.
    try:
        await store.cleanup_abandoned(user_id, issued, GRANT_CLEANUP_LIMIT)
    except Exception:
        pass
    grant_id = _GRANT_ID_PREFIX + uuid.uuid4().hex
    conversation_ref = "chat_" + uuid.uuid4().hex
    if validate_conversation_id(conversation_ref) is None:
        raise FirstTurnAuthorityError(
            503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."
        )
    try:
        row = await store.insert_reserved(
            {
                "id": grant_id,
                "user_id": user_id,
                "subject_id": subject_id,
                "tenant_id": tenant_id,
                "product_id": B54_PRODUCT_ID,
                "route_scope": route_scope,
                "conversation_ref": conversation_ref,
                "correlation_key": correlation,
                "issued_at": issued,
                "expires_at": expires,
            }
        )
    except Exception as exc:
        raise FirstTurnAuthorityError(
            503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."
        ) from exc
    if row is None:
        # Another attempt owns the live key: attach only when every binding
        # matches, otherwise deny. The attach never authorizes a dispatch;
        # only claim() does.
        try:
            existing = await store.find_live(user_id, correlation, issued)
        except Exception as exc:
            raise FirstTurnAuthorityError(
                503,
                "first_turn_grant_unavailable",
                "대화 권한 저장소를 사용할 수 없습니다.",
            ) from exc
        if existing is None:
            raise FirstTurnAuthorityError(
                503,
                "first_turn_grant_unavailable",
                "대화 권한 저장소를 사용할 수 없습니다.",
            )
        for key, expected in (
            ("subject_id", subject_id),
            ("tenant_id", tenant_id),
            ("product_id", B54_PRODUCT_ID),
            ("route_scope", route_scope),
        ):
            if existing.get(key) != expected:
                raise FirstTurnAuthorityError(
                    403,
                    "first_turn_grant_unavailable",
                    "대화 권한을 확인할 수 없습니다.",
                )
        return _context_from_row(existing)
    return _context_from_row(
        {
            "id": grant_id,
            "user_id": user_id,
            "subject_id": subject_id,
            "tenant_id": tenant_id,
            "product_id": B54_PRODUCT_ID,
            "route_scope": route_scope,
            "conversation_ref": conversation_ref,
            "correlation_key": correlation,
            "issued_at": issued,
            "expires_at": expires,
        }
    )


async def claim_first_turn_grant(store: Any, context: B54VerifiedCodingContextV1) -> bool:
    """Atomically claim the grant for dispatch. Exactly one claim may win.

    Returns False when another attempt owns the dispatch (caller must answer
    status-only). Raises FirstTurnAuthorityError(503) when the store itself
    is unavailable or fails, so a storage outage can never look like a lost
    race.
    """
    if store is None:
        raise FirstTurnAuthorityError(
            503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."
        )
    try:
        row = await store.claim(
            context.grant_id,
            context.user_id,
            context.subject_id,
            context.tenant_id,
            _iso(_utcnow()),
        )
    except Exception as exc:
        raise FirstTurnAuthorityError(
            503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."
        ) from exc
    return row is not None


async def complete_first_turn_grant(
    request: Any,
    context: B54VerifiedCodingContextV1 | None,
    *,
    run_ref: str | None,
    saved_conversation_id: str | None,
) -> None:
    """Link the grant to its verified outcome. Best-effort provenance only."""
    if context is None:
        return
    store = getattr(request.app.state, "claw_first_turn_grant_store", None)
    if store is None:
        return
    try:
        await store.settle(
            context.grant_id,
            context.user_id,
            STATE_COMPLETED,
            _iso(_utcnow()),
            run_ref=run_ref,
            saved_conversation_id=saved_conversation_id,
        )
    except Exception:
        pass


async def fail_first_turn_grant(
    request: Any, context: B54VerifiedCodingContextV1 | None
) -> None:
    """Terminally fail a claimed grant after PROVEN non-dispatch only.

    Call only when the failure is proven to have happened before any
    Engine/P01 transport attempt (mirrors the quota-refund rule). Ambiguous
    outcomes must leave the grant active until expiry.
    """
    if context is None:
        return
    store = getattr(request.app.state, "claw_first_turn_grant_store", None)
    if store is None:
        return
    try:
        await store.settle(
            context.grant_id, context.user_id, STATE_FAILED, _iso(_utcnow())
        )
    except Exception:
        pass
