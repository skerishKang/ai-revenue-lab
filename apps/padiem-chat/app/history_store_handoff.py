"""승인 인계 (Q구역, #7813 H4).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 승인 인계 기록·조회·청구·
확정·소비이다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는
`app/history.py`가 `D1HistoryStore`를 조합으로 다시 내보낸다.
"""
from __future__ import annotations

import uuid
from typing import Any

from .history_errors import HistoryConflict, HistoryError
from .history_ids import _handoff_expired, _handoff_id, _handoff_trusted_request_json, _parse_handoff_expiry, validate_conversation_id
from .history_store_core import StoreCore
from .history_text import _now_iso
from .workspace_storage import _safe_identifier


class ApprovalHandoffStore(StoreCore):
    """승인 인계 (Q구역)."""

    async def record_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        continuation_ref: str,
        pause_id: str,
        pause_expires_at: str,
        trusted_request: dict[str, Any],
        workspace_id: str | None = None,
        conversation_id: str | None = None,
        p01_run_id: str | None = None,
    ) -> None:
        """Persist one owner-scoped approval handoff under the history owner (#2956).

        Exact replay of the same owner+run identity is idempotent. A conflicting
        continuation_ref / pause_id / trusted request for the same owner+run
        fails closed with ``HistoryConflict``. Cross-owner reads never disclose
        existence because every statement is owner-scoped by ``user_id``.

        #2961: one already-consumed row may be replaced, because a second Engine
        approval pause for the same Claw run is a new continuation generation and
        must never reuse the decided identity. An active row still conflicts.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(continuation_ref, str) or not continuation_ref:
            raise HistoryError("continuation_ref is required")
        if not isinstance(pause_id, str) or not pause_id:
            raise HistoryError("pause_id is required")
        if not isinstance(pause_expires_at, str) or not pause_expires_at:
            raise HistoryError("pause_expires_at is required")
        if _parse_handoff_expiry(pause_expires_at) is None:
            raise HistoryError("pause_expires_at must be a timezone-aware ISO-8601 timestamp")
        if conversation_id is not None:
            conversation_id = validate_conversation_id(conversation_id)
        if workspace_id is not None:
            workspace_id = _safe_identifier("workspace_id", workspace_id)
        # #2961: the Engine-issued P01 run identity is optional at write time so
        # a #2956-era caller stays valid, but a handoff written without it can
        # never be consumed: the decision boundary fails closed instead.
        if p01_run_id is not None:
            p01_run_id = _safe_identifier("p01_run_id", p01_run_id)
        encoded, fingerprint = _handoff_trusted_request_json(trusted_request)
        existing = await self._first(
            "SELECT id, continuation_ref, pause_id, pause_expires_at, trusted_request_fingerprint, "
            "workspace_id, conversation_id, p01_run_id, consumed_at "
            "FROM claw_approval_handoff WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )
        if existing is not None:
            if (
                str(existing.get("continuation_ref")) == continuation_ref
                and str(existing.get("pause_id")) == pause_id
                and str(existing.get("pause_expires_at")) == pause_expires_at
                and str(existing.get("trusted_request_fingerprint")) == fingerprint
                and existing.get("workspace_id") == workspace_id
                and existing.get("conversation_id") == conversation_id
                and existing.get("p01_run_id") == p01_run_id
            ):
                return
            consumed_at = existing.get("consumed_at")
            if consumed_at is None or str(consumed_at).startswith("decision_claim:"):
                # An in-flight Engine decision is not an already-consumed
                # generation. Never replace its pause while dispatch is unknown.
                raise HistoryConflict(
                    f"claw approval handoff for run {run_id} already exists with a different identity"
                )
            # Guard the generation transition against a simultaneous new
            # claim or competing pause replacement (no stale SELECT -> write).
            replaced = await self._first(
                "UPDATE claw_approval_handoff SET workspace_id=?, conversation_id=?, continuation_ref=?, "
                "pause_id=?, pause_expires_at=?, trusted_request_json=?, trusted_request_fingerprint=?, "
                "p01_run_id=?, consumed_at=NULL WHERE id=? AND consumed_at=? RETURNING id",
                workspace_id, conversation_id, continuation_ref,
                pause_id, pause_expires_at, encoded, fingerprint, p01_run_id,
                str(existing.get("id")), str(consumed_at),
            )
            if replaced is None:
                raise HistoryConflict(
                    f"claw approval handoff for run {run_id} changed during replacement"
                )
            return
        await self._run(
            "INSERT INTO claw_approval_handoff (id, user_id, run_id, workspace_id, conversation_id, "
            "continuation_ref, pause_id, pause_expires_at, trusted_request_json, trusted_request_fingerprint, "
            "p01_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _handoff_id(), user_id, run_id, workspace_id, conversation_id,
            continuation_ref, pause_id, pause_expires_at, encoded, fingerprint,
            p01_run_id, _now_iso(),
        )

    async def load_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Load one owner+run handoff; cross-scope and expired rows are non-disclosing.

        A foreign owner or foreign workspace returns ``None`` (never an existence
        oracle). An expired pause is unusable and also returns ``None``. A
        consumed handoff (#2961) is never returned, so a decided pause cannot be
        replayed.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(run_id, str) or not run_id:
            return None
        if workspace_id is not None:
            scoped = _safe_identifier("workspace_id", workspace_id)
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, p01_run_id, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND workspace_id=? "
                "AND consumed_at IS NULL",
                user_id, run_id, scoped,
            )
        else:
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, p01_run_id, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND consumed_at IS NULL",
                user_id, run_id,
            )
        if row is None:
            return None
        if _handoff_expired(row.get("pause_expires_at")):
            return None
        try:
            import json

            trusted = json.loads(str(row.get("trusted_request_json") or "{}"))
        except (TypeError, ValueError):
            return None
        if not isinstance(trusted, dict):
            return None
        try:
            _encoded, recomputed_fingerprint = _handoff_trusted_request_json(trusted)
        except HistoryError:
            return None
        stored_fingerprint = str(row.get("trusted_request_fingerprint") or "")
        if not stored_fingerprint or recomputed_fingerprint != stored_fingerprint:
            return None
        conversation_id = row.get("conversation_id")
        return {
            "user_id": str(row.get("user_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "workspace_id": row.get("workspace_id"),
            "conversation_id": conversation_id,
            "continuation_ref": str(row.get("continuation_ref") or ""),
            "pause_id": str(row.get("pause_id") or ""),
            "pause_expires_at": str(row.get("pause_expires_at") or ""),
            "trusted_request": trusted,
            "trusted_request_fingerprint": str(row.get("trusted_request_fingerprint") or ""),
            "p01_run_id": row.get("p01_run_id"),
            "created_at": str(row.get("created_at") or ""),
        }

    async def claim_claw_approval_handoff(
        self,
        *,
        user_id: str,
        run_id: str,
        workspace_id: str | None,
        continuation_ref: str,
        pause_id: str,
        trusted_request_fingerprint: str,
    ) -> str | None:
        """Atomically elect exactly one Engine decision dispatcher (#3936).

        The existing consumed_at column holds a server-minted in-flight claim;
        NULL means available, a decision_claim: token means potentially sent,
        and a normal timestamp means conclusively consumed. An ambiguous
        Engine outcome stays claimed: retrying could duplicate a side effect.
        """
        if not isinstance(user_id, str) or not user_id or not isinstance(run_id, str) or not run_id:
            return None
        if not all(isinstance(v, str) and v for v in
                   (continuation_ref, pause_id, trusted_request_fingerprint)):
            return None
        token = "decision_claim:" + uuid.uuid4().hex
        sql = (
            "UPDATE claw_approval_handoff SET consumed_at=? "
            "WHERE user_id=? AND run_id=? AND continuation_ref=? AND pause_id=? "
            "AND trusted_request_fingerprint=? AND consumed_at IS NULL "
            "AND julianday(pause_expires_at) > julianday('now') "
        )
        params: list[Any] = [token, user_id, run_id, continuation_ref, pause_id,
                             trusted_request_fingerprint]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        # SQLite / Cloudflare D1 execute the CAS and RETURNING in one statement.
        # No read-before-update check, local process lock or follow-up SELECT
        # can elect the winning dispatcher across multiple Workers.
        row = await self._first(sql + "RETURNING id", *params)
        return token if row is not None else None

    async def release_claw_approval_claim(
        self, *, user_id: str, run_id: str, workspace_id: str | None,
        claim_token: str,
    ) -> bool:
        """Release ONLY a proven NOT_DISPATCHED claim, guarded against ABA."""
        if not isinstance(claim_token, str) or not claim_token.startswith("decision_claim:"):
            return False
        sql = ("UPDATE claw_approval_handoff SET consumed_at=NULL "
               "WHERE user_id=? AND run_id=? AND consumed_at=? ")
        params: list[Any] = [user_id, run_id, claim_token]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        return await self._first(sql + "RETURNING id", *params) is not None

    async def finalize_claw_approval_claim(
        self, *, user_id: str, run_id: str, workspace_id: str | None,
        claim_token: str,
    ) -> bool:
        """Finalize a claimed handoff only after verified Engine resolution."""
        if not isinstance(claim_token, str) or not claim_token.startswith("decision_claim:"):
            return False
        sql = ("UPDATE claw_approval_handoff SET consumed_at=? "
               "WHERE user_id=? AND run_id=? AND consumed_at=? ")
        params: list[Any] = [_now_iso(), user_id, run_id, claim_token]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        return await self._first(sql + "RETURNING id", *params) is not None

    async def consume_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        workspace_id: str | None = None,
    ) -> bool:
        """Mark one owner+run handoff unusable after the Engine proved consumption (#2961).

        One bounded ``consumed_at`` marker under the existing history owner: no
        new store, no claim token, no Engine state. Scoped by owner (and
        workspace when supplied) so a caller can never consume another owner's
        handoff, and never overwrites an already-consumed row.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        columns = "SELECT id FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND consumed_at IS NULL"
        values: list[Any] = [user_id, run_id]
        if workspace_id is not None:
            values.append(_safe_identifier("workspace_id", workspace_id))
            columns += " AND workspace_id=?"
        else:
            # An unscoped consume must not become a cross-workspace write.
            columns += " AND workspace_id IS NULL"
        owned = await self._first(columns, *values)
        if owned is None:
            return False
        await self._run(
            "UPDATE claw_approval_handoff SET consumed_at=? WHERE id=?",
            _now_iso(), str(owned.get("id")),
        )
        return True
