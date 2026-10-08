"""#3782: source-only durable Engine browser.control approval receipt.

This is *not* an approval issuer or bearer grant. The existing canonical
authenticated Engine approval verifier must supply the VerifiedApprovalDecision
after checking service identity; the actual Engine tool continuation must be
consumed before the record can be stored/read. Nothing is wired into Worker,
Broker, tool execution or a route until the genuine first-party producer exists.
No arguments, text, URL, credentials, provider output or browser action stored.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ContinuationStatus,
    VerifiedApprovalDecision,
    resolve_approval_pause,
)

TABLE = "padiem_engine_browser_control_p01_receipts"
CONTINUATIONS = "padiem_engine_continuations"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
ENGINE_BROWSER_CONTROL_P01_RECEIPT_PRODUCER_WIRED = False
ENGINE_BROWSER_CONTROL_P01_RECEIPT_READER_WIRED = False


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} requires timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _ref(value: str, name: str) -> str:
    if type(value) is not str or not _REF.fullmatch(value):
        raise ValueError(f"{name} must be a bounded safe identifier")
    return value


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass(frozen=True, slots=True)
class EngineApprovedBrowserControlP01Receipt:
    """Exact Engine-authenticated P01 fields. NOT executable authorization."""

    app_id: str
    continuation_ref: str
    pause_id: str
    decision_id: str
    evidence_ref: str
    authority_ref: str
    run_id: str
    invocation_sha256: str
    approved_at: datetime
    expires_at: datetime

    @classmethod
    def from_verified_engine_decision(
        cls, *,
        app_id: str,
        continuation_ref: str,
        pause: ApprovalPause,
        decision: VerifiedApprovalDecision,
        now: datetime,
    ) -> EngineApprovedBrowserControlP01Receipt:
        """Called ONLY AFTER the real authenticated Engine decision verifier.

        Caller must additionally prove completed Engine continuation in D1.
        An arbitrary VerifiedApprovalDecision instance is not a security proof.
        """
        if type(pause) is not ApprovalPause or type(decision) is not VerifiedApprovalDecision:
            raise ValueError("canonical Engine pause/verified decision required")
        current = _aware(now, "now")
        if (
            pause.tool_id != "browser.control"
            or pause.approval_scope != ("browser.control",)
            or decision.outcome is not ApprovalOutcome.APPROVED
            or decision.pause_id != pause.pause_id
            or type(pause.invocation_sha256) is not str
            or _SHA.fullmatch(pause.invocation_sha256) is None
            or resolve_approval_pause(pause, decision, now=current).status
            is not ContinuationStatus.RESUMABLE
        ):
            raise ValueError("Engine browser.control P01 decision is not approved and resumable")
        return cls(
            app_id=_ref(app_id, "app_id"),
            continuation_ref=_ref(continuation_ref, "continuation_ref"),
            pause_id=pause.pause_id,
            decision_id=decision.decision_id,
            evidence_ref=decision.evidence_ref,
            authority_ref=decision.authority_ref,
            run_id=pause.run_id,
            invocation_sha256=pause.invocation_sha256,
            approved_at=_aware(decision.decided_at, "approved_at"),
            expires_at=_aware(pause.expires_at, "expires_at"),
        )


class CloudflareD1BrowserControlP01ReceiptStore:
    """Source-only owner-scoped D1 continuation joined receipt authority.

    Both reads and writes require the canonical continuation to be CONSUMED,
    and compare pause_id/run_id/tool_id/invocation SHA to its immutable pause.
    This store never authenticates a caller, mints decisions or serves HTTP.
    The trusted Engine composition must enforce service identity.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("canonical D1 binding with prepare required")
        self._binding = binding

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    async def store_completed(
        self, receipt: EngineApprovedBrowserControlP01Receipt, *, now: datetime,
    ) -> None:
        """Fail closed: require actual consumed matching Engine continuation.

        No insert for active/claimed/denied/cancelled/missing/mismatched pause.
        Duplicate continuation or replay of the same decision fails closed.
        """
        if type(receipt) is not EngineApprovedBrowserControlP01Receipt:
            raise ValueError("typed verified Engine browser P01 receipt required")
        current = _aware(now, "now")
        if receipt.expires_at <= current or receipt.approved_at > current:
            raise ValueError("Engine browser P01 approval expired or is from the future")
        sql = (
            f"INSERT INTO {TABLE} (app_id,continuation_ref,pause_id,decision_id,"
            "evidence_ref,authority_ref,run_id,invocation_sha256,approved_at,expires_at) "
            "SELECT c.app_id,c.continuation_ref,?,?,?,?,?,?,?,? "
            f"FROM {CONTINUATIONS} c WHERE c.app_id=? AND c.continuation_ref=? "
            "AND c.state='consumed' AND json_extract(c.pause_json,'$.pause_id')=? "
            "AND json_extract(c.pause_json,'$.run_id')=? "
            "AND json_extract(c.pause_json,'$.tool_id')='browser.control' "
            "AND json_extract(c.pause_json,'$.invocation_sha256')=? "
            "AND json_array_length(json_extract(c.pause_json,'$.approval_scope'))=1 "
            "AND json_extract(c.pause_json,'$.approval_scope[0]')='browser.control' "
            "AND json_extract(c.pause_json,'$.expires_at')=?"
        )
        try:
            result = await self._run(
                sql, receipt.pause_id, receipt.decision_id, receipt.evidence_ref,
                receipt.authority_ref, receipt.run_id, receipt.invocation_sha256,
                receipt.approved_at.isoformat(), receipt.expires_at.isoformat(),
                receipt.app_id, receipt.continuation_ref, receipt.pause_id,
                receipt.run_id, receipt.invocation_sha256, receipt.expires_at.isoformat(),
            )
            changes = result.get("meta", {}).get("changes") if isinstance(result, Mapping) else None
            if changes != 1:
                raise ValueError("no matching consumed Engine browser.control continuation")
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - fail closed on unknown D1 transport failures
            raise ValueError("Engine browser.control receipt duplicate or unavailable") from None

    async def resolve_active(
        self, *, app_id: str, continuation_ref: str, now: datetime,
        admitted: AdmittedBrowserControlP01ReceiptQuery | None = None,
    ) -> EngineApprovedBrowserControlP01Receipt | None:
        """Return current evidence, optionally constrained to an exact original run.

        The extra original-admission conditions belong to the SAME D1 SELECT.
        A typed query does not authenticate the service invoking this method.
        """
        current = _aware(now, "now")
        extra_sql = ""
        extra_params: tuple[Any, ...] = ()
        if admitted is not None:
            if (
                type(admitted) is not AdmittedBrowserControlP01ReceiptQuery
                or admitted.app_id != app_id
                or admitted.continuation_ref != continuation_ref
            ):
                raise ValueError("canonical admitted Engine P01 query required")
            extra_sql = (
                " AND r.run_id=? AND r.invocation_sha256=? AND r.evidence_ref=? "
                "AND json_extract(c.execution_identity_json,'$.subject_id')=? "
                "AND json_extract(c.execution_identity_json,'$.request_fingerprint')=? "
                "AND json_extract(c.execution_identity_json,"
                "'$.original_admission_binding.app_id')=? "
                "AND json_extract(c.execution_identity_json,"
                "'$.original_admission_binding.subject_id')=? "
                "AND json_extract(c.execution_identity_json,"
                "'$.original_admission_binding.request_fingerprint')=? "
                "AND json_extract(c.execution_identity_json,"
                "'$.original_admission_binding.decision_id')=?"
            )
            extra_params = (
                admitted.run_id, admitted.invocation_sha256,
                admitted.user_approval_evidence_ref, admitted.user_subject_id,
                admitted.original_request_fingerprint, admitted.app_id,
                admitted.user_subject_id, admitted.original_request_fingerprint,
                admitted.original_admission_decision_id,
            )
        row = await self._first(
            f"SELECT r.app_id,r.continuation_ref,r.pause_id,r.decision_id,r.evidence_ref,"
            "r.authority_ref,r.run_id,r.invocation_sha256,r.approved_at,r.expires_at "
            f"FROM {TABLE} r JOIN {CONTINUATIONS} c "
            "ON c.app_id=r.app_id AND c.continuation_ref=r.continuation_ref "
            "WHERE r.app_id=? AND r.continuation_ref=? AND c.state='consumed' "
            "AND r.revoked_at IS NULL AND r.expires_at>? "
            "AND json_extract(c.pause_json,'$.pause_id')=r.pause_id "
            "AND json_extract(c.pause_json,'$.run_id')=r.run_id "
            "AND json_extract(c.pause_json,'$.invocation_sha256')=r.invocation_sha256 "
            "AND json_extract(c.pause_json,'$.tool_id')='browser.control' "
            "AND json_array_length(json_extract(c.pause_json,'$.approval_scope'))=1 "
            "AND json_extract(c.pause_json,'$.approval_scope[0]')='browser.control' "
            "AND json_extract(c.pause_json,'$.expires_at')=r.expires_at"
            + extra_sql,
            _ref(app_id, "app_id"), _ref(continuation_ref, "continuation_ref"),
            current.isoformat(), *extra_params,
        )
        if row is None:
            return None
        try:
            record = EngineApprovedBrowserControlP01Receipt(
                app_id=_ref(row["app_id"], "app_id"),
                continuation_ref=_ref(row["continuation_ref"], "continuation_ref"),
                pause_id=_ref(row["pause_id"], "pause_id"),
                decision_id=_ref(row["decision_id"], "decision_id"),
                evidence_ref=_ref(row["evidence_ref"], "evidence_ref"),
                authority_ref=_ref(row["authority_ref"], "authority_ref"),
                run_id=_ref(row["run_id"], "run_id"),
                invocation_sha256=row["invocation_sha256"],
                approved_at=_aware(datetime.fromisoformat(row["approved_at"]), "approved_at"),
                expires_at=_aware(datetime.fromisoformat(row["expires_at"]), "expires_at"),
            )
            if not _SHA.fullmatch(record.invocation_sha256) or record.approved_at > current:
                raise ValueError("invalid receipt")
            return record
        except (KeyError, TypeError, ValueError):
            raise ValueError("canonical Engine P01 receipt corrupted") from None

    async def resolve_admitted(
        self, *, query: AdmittedBrowserControlP01ReceiptQuery, now: datetime,
    ) -> EngineApprovedBrowserControlP01Receipt | None:
        """Read-only internal Broker-bridge candidate, never a bearer grant.

        Requires an explicitly supplied original Engine admission and the
        exact P01 invocation/evidence. The caller still MUST authenticate its
        service identity and the real per-command Broker/P01 relationship.
        """
        if type(query) is not AdmittedBrowserControlP01ReceiptQuery:
            raise ValueError("trusted original Engine admission correlation required")
        return await self.resolve_active(
            app_id=query.app_id,
            continuation_ref=query.continuation_ref,
            now=now,
            admitted=query,
        )

    async def revoke(
        self, *, app_id: str, continuation_ref: str, now: datetime,
    ) -> bool:
        """Monotonic server-owned revocation; never restores an expired receipt."""
        current = _aware(now, "now")
        result = await self._run(
            f"UPDATE {TABLE} SET revoked_at=? WHERE app_id=? AND continuation_ref=? "
            "AND revoked_at IS NULL AND expires_at>?",
            current.isoformat(), _ref(app_id, "app_id"),
            _ref(continuation_ref, "continuation_ref"), current.isoformat(),
        )
        return (
            isinstance(result, Mapping)
            and result.get("meta", {}).get("changes") == 1
        )

    async def commit_claimed_browser_approval(
        self, *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
        pause: ApprovalPause,
        decision: VerifiedApprovalDecision,
        now: datetime,
    ) -> EngineApprovedBrowserControlP01Receipt:
        """Atomic D1 claim -> CONSUMED + approved receipt, NO tool execution.

        Intended ONLY for a future service-identity authenticated first-party
        Engine owner that has ALREADY independently verified the decision.
        A caller-supplied decision instance is NOT authentication. This
        source method is NOT wired to Engine/Worker routes.

        The claim token is retained only BETWEEN these transaction statements
        (never outside the atomic D1 batch) to prohibit replay of consumed work.
        """
        if not callable(getattr(self._binding, "batch", None)):
            raise TypeError("atomic canonical D1 batch is required")
        token = _ref(claim_token, "claim_token")
        if not token.startswith("claim_"):
            raise ValueError("canonical Engine continuation claim required")
        receipt = EngineApprovedBrowserControlP01Receipt.from_verified_engine_decision(
            app_id=app_id, continuation_ref=continuation_ref,
            pause=pause, decision=decision, now=now,
        )
        moment = _aware(now, "now").isoformat()

        predicate = (
            "app_id=? AND continuation_ref=? "
            "AND json_extract(pause_json,'$.pause_id')=? "
            "AND json_extract(pause_json,'$.run_id')=? "
            "AND json_extract(pause_json,'$.invocation_sha256')=? "
            "AND json_extract(pause_json,'$.tool_id')='browser.control' "
            "AND json_array_length(json_extract(pause_json,'$.approval_scope'))=1 "
            "AND json_extract(pause_json,'$.approval_scope[0]')='browser.control' "
            "AND json_extract(pause_json,'$.expires_at')=?"
        )
        identity = (
            receipt.app_id, receipt.continuation_ref, receipt.pause_id,
            receipt.run_id, receipt.invocation_sha256, receipt.expires_at.isoformat(),
        )
        # Step 1: conditional CAS preserving claim inside this transaction.
        update = self._binding.prepare(
            f"UPDATE {CONTINUATIONS} SET state='consumed',updated_at=? "
            f"WHERE {predicate} AND state='claimed' "
            "AND claim_token=? AND expires_at>?"
        ).bind(moment, *identity, token, moment)
        # Step 2: an already-consumed row has a NULL claim_token, so cannot
        # produce a new receipt. Duplicate evidence aborts the whole D1 batch.
        insert = self._binding.prepare(
            f"INSERT INTO {TABLE} (app_id,continuation_ref,pause_id,decision_id,"
            "evidence_ref,authority_ref,run_id,invocation_sha256,approved_at,expires_at) "
            "SELECT c.app_id,c.continuation_ref,?,?,?,?,?,?,?,? "
            f"FROM {CONTINUATIONS} c WHERE c.app_id=? AND c.continuation_ref=? "
            "AND c.state='consumed' AND c.claim_token=? "
            "AND json_extract(c.pause_json,'$.pause_id')=? "
            "AND json_extract(c.pause_json,'$.run_id')=? "
            "AND json_extract(c.pause_json,'$.invocation_sha256')=? "
            "AND json_extract(c.pause_json,'$.tool_id')='browser.control' "
            "AND json_array_length(json_extract(c.pause_json,'$.approval_scope'))=1 "
            "AND json_extract(c.pause_json,'$.approval_scope[0]')='browser.control' "
            "AND json_extract(c.pause_json,'$.expires_at')=?"
        ).bind(
            receipt.pause_id, receipt.decision_id, receipt.evidence_ref,
            receipt.authority_ref, receipt.run_id, receipt.invocation_sha256,
            receipt.approved_at.isoformat(), receipt.expires_at.isoformat(),
            receipt.app_id, receipt.continuation_ref, token, receipt.pause_id,
            receipt.run_id, receipt.invocation_sha256, receipt.expires_at.isoformat(),
        )
        # Step 3: clear claim only when matching receipt exists.
        finish = self._binding.prepare(
            f"UPDATE {CONTINUATIONS} SET claim_token=NULL WHERE {predicate} "
            "AND state='consumed' AND claim_token=? "
            f"AND EXISTS (SELECT 1 FROM {TABLE} r "
            "WHERE r.app_id=? AND r.continuation_ref=? AND r.decision_id=? "
            "AND r.pause_id=? AND r.invocation_sha256=?)"
        ).bind(
            *identity, token, receipt.app_id, receipt.continuation_ref,
            receipt.decision_id, receipt.pause_id, receipt.invocation_sha256,
        )
        try:
            outcomes = await _maybe_await(self._binding.batch([update, insert, finish]))
        except Exception:  # noqa: BLE001 - D1 failure must never mint approval
            raise ValueError("atomic Engine P01 receipt commit failed") from None
        if (
            type(outcomes) is not list
            or len(outcomes) != 3
            or any(
                not isinstance(result, Mapping)
                or result.get("meta", {}).get("changes") != 1
                for result in outcomes
            )
        ):
            raise ValueError("atomic Engine P01 receipt claim not completed")
        return receipt



@dataclass(frozen=True, slots=True)
class AdmittedBrowserControlP01ReceiptQuery:
    """Private server-owned read correlation, NEVER accepted from client JSON.

    original_request_fingerprint is the *Engine admitted execution* SHA,
    not automatically the Broker command material/request fingerprint.
    A future first-party bridge must independently prove the relationship.
    """

    app_id: str
    continuation_ref: str
    user_subject_id: str
    original_request_fingerprint: str
    original_admission_decision_id: str
    run_id: str
    invocation_sha256: str
    user_approval_evidence_ref: str

    def __post_init__(self) -> None:
        for name in (
            "app_id", "continuation_ref", "user_subject_id",
            "original_admission_decision_id", "run_id",
            "user_approval_evidence_ref",
        ):
            _ref(getattr(self, name), name)
        for name in ("original_request_fingerprint", "invocation_sha256"):
            value = getattr(self, name)
            if type(value) is not str or _SHA.fullmatch(value) is None:
                raise ValueError(f"{name} requires lowercase canonical SHA256")
