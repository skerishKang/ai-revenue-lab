"""#3782 Broker-original Engine D1 admission join, asynchronous and source-only.

TWO independent first-party authorities are mandatory:
  (1) Broker's existing server-owned admitted command -> Engine continuation
      association, recorded independently of user/browser/model input.
  (2) Engine's authenticated original-run reader over CONSUMED original D1
      continuation + current unrevoked user-approved P01 receipt.

A typed association fixture, app-id, or caller-supplied continuation ref alone
is NOT proof of either authority. No Worker entrypoint, registration API,
browser execution or production dependency composition is installed.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_engine_p01_bridge import BrokerEngineP01Join, _ref, _sha, _utc

BROKER_ORIGINAL_ENGINE_ASYNC_SOURCE_WIRED = False


@dataclass(frozen=True, slots=True)
class ServerOwnedBrokerOriginalRunAssociation:
    """Trusted association recorded by the canonical Broker/Engine producer.

    The association resolver MUST independently verify provenance against the
    original admitted command and may NOT construct this from a fetch body.
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

    def __post_init__(self) -> None:
        for k in (
            "command_ref", "binding_ref", "request_id", "run_ref",
            "admission_ref", "revision_ref", "engine_app_id",
            "engine_continuation_ref",
        ):
            _ref(getattr(self, k), k)
        _sha(self.broker_request_fingerprint, "broker_request_fingerprint")

    def assert_matches(self, scope: BrowserControlCommandTakeCorrelation) -> None:
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("original canonical Broker scope required")
        for field, value in (
            ("command_ref", self.command_ref),
            ("binding_ref", self.binding_ref),
            ("request_id", self.request_id),
            ("run_ref", self.run_ref),
            ("request_fingerprint", self.broker_request_fingerprint),
            ("admission_ref", self.admission_ref),
            ("revision_ref", self.revision_ref),
        ):
            if getattr(scope, field) != value:
                raise ValueError("untrusted Broker-to-original-Engine association")


class TrustedOriginalRunAssociationPort(Protocol):
    def resolve_for_admitted_command(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> ServerOwnedBrokerOriginalRunAssociation: ...


class AuthenticatedEngineOriginalReadClient(Protocol):
    app_id: str

    async def read_browser_control_original_admission(
        self, *, continuation_ref: str,
    ) -> dict[str, str]: ...


class SourceOnlyAsyncBrokerOriginalEngineAdmission:
    """Join Broker's pre-existing association to authenticated original Engine D1.

    Async I/O completes OUTSIDE Durable Object transactionSync; the runtime
    rechecks the canonical live command, evidence and device before its CAS.
    """

    def __init__(
        self, *,
        association_port: TrustedOriginalRunAssociationPort,
        engine_client: AuthenticatedEngineOriginalReadClient,
    ) -> None:
        if (
            not callable(getattr(association_port, "resolve_for_admitted_command", None))
            or type(getattr(engine_client, "app_id", None)) is not str
            or not callable(
                getattr(engine_client, "read_browser_control_original_admission", None)
            )
        ):
            raise ValueError("independent Broker run association and authenticated Engine client required")
        self._association = association_port
        self._engine = engine_client

    async def resolve_original_admission_async(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> BrokerEngineP01Join:
        current = _utc(now, "now")
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("live admitted Broker command required")
        association = self._association.resolve_for_admitted_command(
            scope=scope, now=current,
        )
        if type(association) is not ServerOwnedBrokerOriginalRunAssociation:
            raise ValueError("independently recorded original Engine association absent")
        association.assert_matches(scope)
        if association.engine_app_id != self._engine.app_id:
            raise ValueError("Engine caller app does not own original continuation")
        response = self._engine.read_browser_control_original_admission(
            continuation_ref=association.engine_continuation_ref,
        )
        if not inspect.isawaitable(response):
            raise ValueError("original Engine admission requires authenticated asynchronous I/O")
        original = await response
        required = {
            "app_id", "continuation_ref", "user_subject_id",
            "original_request_fingerprint", "original_admission_decision_id",
            "run_id", "invocation_sha256", "user_approval_evidence_ref",
        }
        if type(original) is not dict or set(original) != required:
            raise ValueError("no closed independently verified original Engine admission")
        try:
            if (
                original["app_id"] != association.engine_app_id
                or original["continuation_ref"] != association.engine_continuation_ref
                or original["user_subject_id"] != scope.owner_ref
            ):
                raise ValueError("wrong Engine subject or original continuation")
            joined = BrokerEngineP01Join(
                command_ref=association.command_ref,
                binding_ref=association.binding_ref,
                request_id=association.request_id,
                run_ref=association.run_ref,
                broker_request_fingerprint=association.broker_request_fingerprint,
                admission_ref=association.admission_ref,
                revision_ref=association.revision_ref,
                engine_app_id=_ref(original["app_id"], "engine_app_id"),
                engine_continuation_ref=_ref(original["continuation_ref"], "continuation_ref"),
                engine_run_id=_ref(original["run_id"], "engine_run_id"),
                engine_user_subject_id=_ref(original["user_subject_id"], "subject_id"),
                engine_request_sha256=_sha(
                    original["original_request_fingerprint"], "engine_request_sha256",
                ),
                engine_original_admission_decision_id=_ref(
                    original["original_admission_decision_id"], "original_decision_id",
                ),
                browser_invocation_sha256=_sha(
                    original["invocation_sha256"], "invocation_sha256",
                ),
                user_p01_evidence_ref=_ref(
                    original["user_approval_evidence_ref"], "user_approval_evidence_ref",
                ),
            )
            joined.assert_matches(scope)
            return joined
        except (KeyError, TypeError, ValueError):
            raise ValueError("original Engine admission does not match Broker authority") from None
