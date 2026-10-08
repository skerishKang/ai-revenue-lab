"""#3782: source-only, three-authority Broker <-> Engine browser P01 join.

The Engine's original execution fingerprint, Broker's session fingerprint,
and Core's browser.control ToolInvocation digest are DISTINCT identities.
Do not copy one into the other. This module issues NO P01 decision, creates NO
command, does NO network access, and has NO Worker/DO or device RPC entrypoint.

Production composition may ONLY inject server-owned live/authenticated ports:
(1) existing Broker admitted-command -> original Engine execution association,
(2) authenticated Engine D1 approved-receipt resolver, and
(3) current per-device local permission authority. Merely constructing typed
fixtures is NOT evidence of authentication; no product ports are wired here.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_browser_p01_source import (
    AuthenticatedBrowserControlP01Approval,
)

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
BROKER_ENGINE_BROWSER_P01_BRIDGE_WIRED = False


def _utc(value: datetime, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} requires timezone-aware time")
    return value.astimezone(timezone.utc)


def _ref(value: str, field: str) -> str:
    if type(value) is not str or not _REF.fullmatch(value):
        raise ValueError(f"{field} requires canonical safe identifier")
    return value


def _sha(value: str, field: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{field} requires lowercase SHA256")
    return value


@dataclass(frozen=True, slots=True)
class BrokerEngineP01Join:
    """Existing Broker command -> original Engine admitted run, server-owned.

    IMPORTANT: .engine_request_sha256 is NOT .broker_request_fingerprint.
    Its provenance must be independently checked by the admitted-command
    association owner; this type is NOT an admission token.
    """

    command_ref: str
    binding_ref: str
    request_id: str
    run_ref: str
    broker_request_fingerprint: str
    admission_ref: str
    revision_ref: str
    engine_app_id: str
    engine_continuation_ref: str
    engine_run_id: str
    engine_user_subject_id: str
    engine_request_sha256: str
    engine_original_admission_decision_id: str
    browser_invocation_sha256: str
    user_p01_evidence_ref: str

    def __post_init__(self) -> None:
        for name in (
            "command_ref", "binding_ref", "request_id", "run_ref",
            "admission_ref", "revision_ref", "engine_app_id",
            "engine_continuation_ref", "engine_run_id", "engine_user_subject_id",
            "engine_original_admission_decision_id", "user_p01_evidence_ref",
        ):
            _ref(getattr(self, name), name)
        for name in (
            "broker_request_fingerprint", "engine_request_sha256",
            "browser_invocation_sha256",
        ):
            _sha(getattr(self, name), name)

    def assert_matches(self, scope: BrowserControlCommandTakeCorrelation) -> None:
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("canonical live Broker command required")
        for key, expected in (
            ("command_ref", self.command_ref),
            ("binding_ref", self.binding_ref),
            ("request_id", self.request_id),
            ("run_ref", self.run_ref),
            ("request_fingerprint", self.broker_request_fingerprint),
            ("admission_ref", self.admission_ref),
            ("revision_ref", self.revision_ref),
            ("owner_ref", self.engine_user_subject_id),
        ):
            if getattr(scope, key) != expected:
                raise ValueError("Broker command does not match original Engine run mapping")


@dataclass(frozen=True, slots=True)
class EngineP01ReadQuery:
    """Exact Engine D1 resolve_admitted arguments, never a user payload."""

    app_id: str
    continuation_ref: str
    user_subject_id: str
    original_request_fingerprint: str
    original_admission_decision_id: str
    run_id: str
    invocation_sha256: str
    user_approval_evidence_ref: str


@dataclass(frozen=True, slots=True)
class AuthenticatedEngineP01ReceiptProjection:
    """Projection from authenticated current Engine D1 resolve_admitted."""

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


@dataclass(frozen=True, slots=True)
class CurrentLocalBrowserPermission:
    """Live permission from the existing device policy owner, NOT a grant."""

    binding_ref: str
    device_ref: str
    owner_ref: str
    workspace_ref: str
    result: str
    verified_at: datetime
    expires_at: datetime

    def assert_matches(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> None:
        if type(self) is not CurrentLocalBrowserPermission:
            raise ValueError("trusted current local permission required")
        moment = _utc(now, "now")
        if (
            self.binding_ref != scope.binding_ref
            or self.device_ref != scope.device_ref
            or self.owner_ref != scope.owner_ref
            or self.workspace_ref != scope.workspace_ref
            or self.result not in ("locally_allowed", "require_p01_approval")
            or _utc(self.verified_at, "local_verified_at") > moment
            or _utc(self.expires_at, "local_expires_at") <= moment
        ):
            raise ValueError("local browser permission revoked, stale or mismatched")


class BrokerEngineJoinPort(Protocol):
    def resolve_for_admitted_command(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> BrokerEngineP01Join: ...


class AuthenticatedEngineP01ReadPort(Protocol):
    def resolve_admitted(
        self, *, query: EngineP01ReadQuery, now: datetime,
    ) -> AuthenticatedEngineP01ReceiptProjection | None: ...


class CurrentLocalPermissionPort(Protocol):
    def resolve_current(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> CurrentLocalBrowserPermission: ...


class SourceOnlyBrokerEngineBrowserP01Bridge:
    """Adapts three independently authenticated owners to Broker's P01 seam.

    Synchronous by design (the Broker's current resolve_approved_command is
    synchronous); no asyncio.run, no network call or hidden fallback here.
    The later production service binding MUST provide an authenticated
    synchronous Engine read, preserve revocation semantics, and prove that the
    join is server-owned. No source is constructed in Broker Worker today.
    """

    def __init__(
        self, *, join_port: BrokerEngineJoinPort,
        engine_port: AuthenticatedEngineP01ReadPort,
        local_port: CurrentLocalPermissionPort,
    ) -> None:
        for port, method in (
            (join_port, "resolve_for_admitted_command"),
            (engine_port, "resolve_admitted"),
            (local_port, "resolve_current"),
        ):
            if not callable(getattr(port, method, None)):
                raise TypeError("all authenticated browser P01 authority ports required")
        self._join = join_port
        self._engine = engine_port
        self._local = local_port

    def resolve_approved_command(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> AuthenticatedBrowserControlP01Approval:
        current = _utc(now, "now")
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("live canonical Broker scope required")
        joined = self._join.resolve_for_admitted_command(scope=scope, now=current)
        if type(joined) is not BrokerEngineP01Join:
            raise ValueError("server-owned Broker-to-Engine mapping unavailable")
        joined.assert_matches(scope)
        query = EngineP01ReadQuery(
            app_id=joined.engine_app_id,
            continuation_ref=joined.engine_continuation_ref,
            user_subject_id=joined.engine_user_subject_id,
            original_request_fingerprint=joined.engine_request_sha256,
            original_admission_decision_id=joined.engine_original_admission_decision_id,
            run_id=joined.engine_run_id,
            invocation_sha256=joined.browser_invocation_sha256,
            user_approval_evidence_ref=joined.user_p01_evidence_ref,
        )
        receipt = self._engine.resolve_admitted(query=query, now=current)
        if type(receipt) is not AuthenticatedEngineP01ReceiptProjection:
            raise ValueError("current independently approved Engine P01 receipt missing")
        if (
            receipt.app_id != query.app_id
            or receipt.continuation_ref != query.continuation_ref
            or receipt.run_id != query.run_id
            or receipt.invocation_sha256 != query.invocation_sha256
            or receipt.evidence_ref != query.user_approval_evidence_ref
        ):
            raise ValueError("Engine P01 receipt is for another browser command")
        if (
            _utc(receipt.approved_at, "approved_at") > current
            or _utc(receipt.expires_at, "receipt_expires_at") <= current
        ):
            raise ValueError("Engine P01 receipt stale, expired or future")
        local = self._local.resolve_current(scope=scope, now=current)
        if type(local) is not CurrentLocalBrowserPermission:
            raise ValueError("authenticated current local permission unavailable")
        local.assert_matches(scope=scope, now=current)
        effective_expiry = min(
            _utc(receipt.expires_at, "receipt_expires_at"),
            _utc(local.expires_at, "local_expires_at"),
        )
        result = AuthenticatedBrowserControlP01Approval(
            command_ref=scope.command_ref,
            binding_ref=scope.binding_ref,
            request_id=scope.request_id,
            run_ref=scope.run_ref,
            request_fingerprint=scope.request_fingerprint,
            admission_ref=scope.admission_ref,
            revision_ref=scope.revision_ref,
            evidence_ref=receipt.evidence_ref,
            pause_ref=receipt.pause_id,
            decision_ref=receipt.decision_id,
            approval_tool_id="browser.control",
            approval_invocation_sha256=receipt.invocation_sha256,
            approval_scope=("browser.control",),
            decision_outcome="approved",
            local_permission_result=local.result,
            decided_at=receipt.approved_at,
            expires_at=effective_expiry,
        )
        result.assert_matches(
            scope=scope, expected_invocation_sha256=joined.browser_invocation_sha256,
            now=current,
        )
        return result


class AsyncEngineP01ReadPort(Protocol):
    async def resolve_admitted_async(
        self, *, query: EngineP01ReadQuery, now: datetime,
    ) -> AuthenticatedEngineP01ReceiptProjection | None: ...


class AuthenticatedAsyncEngineReceiptClientPort:
    """Adapter for the existing Engine first-party, signed service client.

    Never accepts a caller's decision/approval JSON or an arbitrary URL. The
    injected Engine client owns its fixed service transport + credential.
    An additional independent Broker command->original run association must
    still be provided to the bridge; a client instance itself is NOT a grant.
    """

    def __init__(self, *, engine_client: Any) -> None:
        if (
            type(getattr(engine_client, "app_id", None)) is not str
            or not callable(
                getattr(engine_client, "read_browser_control_broker_receipt", None)
            )
        ):
            raise ValueError("trusted internal Engine receipt reader required")
        self._client = engine_client

    async def resolve_admitted_async(
        self, *, query: EngineP01ReadQuery, now: datetime,
    ) -> AuthenticatedEngineP01ReceiptProjection | None:
        if type(query) is not EngineP01ReadQuery:
            raise ValueError("canonical original Engine admission required")
        current = _utc(now, "now")
        if self._client.app_id != query.app_id:
            raise ValueError("Broker Engine client app does not own original P01")
        result = self._client.read_browser_control_broker_receipt(
            continuation_ref=query.continuation_ref,
            user_subject_id=query.user_subject_id,
            original_request_fingerprint=query.original_request_fingerprint,
            original_admission_decision_id=query.original_admission_decision_id,
            run_id=query.run_id,
            invocation_sha256=query.invocation_sha256,
            user_approval_evidence_ref=query.user_approval_evidence_ref,
        )
        if not inspect.isawaitable(result):
            raise ValueError("Engine receipt transport must be asynchronous")
        row = await result
        if type(row) is not dict or set(row) != {
            "app_id", "continuation_ref", "pause_id", "decision_id",
            "evidence_ref", "authority_ref", "run_id", "invocation_sha256",
            "approved_at", "expires_at",
        }:
            raise ValueError("untrusted Engine P01 projection shape")
        try:
            projection = AuthenticatedEngineP01ReceiptProjection(
                app_id=_ref(row["app_id"], "app_id"),
                continuation_ref=_ref(row["continuation_ref"], "continuation_ref"),
                pause_id=_ref(row["pause_id"], "pause_id"),
                decision_id=_ref(row["decision_id"], "decision_id"),
                evidence_ref=_ref(row["evidence_ref"], "evidence_ref"),
                authority_ref=_ref(row["authority_ref"], "authority_ref"),
                run_id=_ref(row["run_id"], "run_id"),
                invocation_sha256=_sha(row["invocation_sha256"], "invocation_sha256"),
                approved_at=datetime.fromisoformat(row["approved_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )
            if (
                projection.app_id != query.app_id
                or projection.continuation_ref != query.continuation_ref
                or projection.run_id != query.run_id
                or projection.invocation_sha256 != query.invocation_sha256
                or projection.evidence_ref != query.user_approval_evidence_ref
                or _utc(projection.approved_at, "approved_at") > current
                or _utc(projection.expires_at, "expires_at") <= current
            ):
                raise ValueError("Engine P01 original-run projection mismatch")
            return projection
        except (KeyError, TypeError, ValueError):
            raise ValueError("Engine P01 original-run projection invalid") from None


class AsyncBrokerEngineBrowserP01Bridge:
    """Three-authority verified Browser P01 source for async Engine/Worker IO.

    The Broker owns the original admitted-command association; Engine owns its
    consumed-and-unrevoked P01 receipt; device owns fresh local permission.
    No wire endpoint, registration or Desktop grant is constructed here.
    The Broker's async registration/take path rechecks live DO state at CAS.
    """

    def __init__(
        self, *, join_port: BrokerEngineJoinPort,
        engine_port: AsyncEngineP01ReadPort,
        local_port: CurrentLocalPermissionPort,
    ) -> None:
        for port, method in (
            (join_port, "resolve_for_admitted_command"),
            (engine_port, "resolve_admitted_async"),
            (local_port, "resolve_current"),
        ):
            if not callable(getattr(port, method, None)):
                raise TypeError("three independent authentic browser P01 owner ports required")
        self._join = join_port
        self._engine = engine_port
        self._local = local_port

    async def resolve_approved_command_async(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> AuthenticatedBrowserControlP01Approval:
        moment = _utc(now, "now")
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("canonical original Broker browser command required")
        joined = self._join.resolve_for_admitted_command(scope=scope, now=moment)
        if type(joined) is not BrokerEngineP01Join:
            raise ValueError("server-owned original Broker-Engine join absent")
        joined.assert_matches(scope)
        query = EngineP01ReadQuery(
            app_id=joined.engine_app_id,
            continuation_ref=joined.engine_continuation_ref,
            user_subject_id=joined.engine_user_subject_id,
            original_request_fingerprint=joined.engine_request_sha256,
            original_admission_decision_id=joined.engine_original_admission_decision_id,
            run_id=joined.engine_run_id,
            invocation_sha256=joined.browser_invocation_sha256,
            user_approval_evidence_ref=joined.user_p01_evidence_ref,
        )
        result = self._engine.resolve_admitted_async(query=query, now=moment)
        if not inspect.isawaitable(result):
            raise ValueError("Engine source did not perform asynchronous authenticated read")
        receipt = await result
        if type(receipt) is not AuthenticatedEngineP01ReceiptProjection:
            raise ValueError("no authenticated Engine P01 receipt")
        if (
            receipt.app_id != query.app_id
            or receipt.continuation_ref != query.continuation_ref
            or receipt.run_id != query.run_id
            or receipt.invocation_sha256 != query.invocation_sha256
            or receipt.evidence_ref != query.user_approval_evidence_ref
            or _utc(receipt.approved_at, "approved_at") > moment
            or _utc(receipt.expires_at, "expires_at") <= moment
        ):
            raise ValueError("Engine P01 receipt does not belong to this original command")
        local = self._local.resolve_current(scope=scope, now=moment)
        if type(local) is not CurrentLocalBrowserPermission:
            raise ValueError("independent live Windows permission missing")
        local.assert_matches(scope=scope, now=moment)
        proof = AuthenticatedBrowserControlP01Approval(
            command_ref=scope.command_ref,
            binding_ref=scope.binding_ref,
            request_id=scope.request_id,
            run_ref=scope.run_ref,
            request_fingerprint=scope.request_fingerprint,
            admission_ref=scope.admission_ref,
            revision_ref=scope.revision_ref,
            evidence_ref=receipt.evidence_ref,
            pause_ref=receipt.pause_id,
            decision_ref=receipt.decision_id,
            approval_tool_id="browser.control",
            approval_invocation_sha256=receipt.invocation_sha256,
            approval_scope=("browser.control",),
            decision_outcome="approved",
            local_permission_result=local.result,
            decided_at=receipt.approved_at,
            expires_at=min(
                _utc(receipt.expires_at, "expires_at"),
                _utc(local.expires_at, "local_expires_at"),
            ),
        )
        proof.assert_matches(
            scope=scope, expected_invocation_sha256=joined.browser_invocation_sha256,
            now=moment,
        )
        return proof
