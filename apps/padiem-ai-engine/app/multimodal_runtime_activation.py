"""A6 File/Document/Multimodal provider-free activation-readiness harness (#1971 A6-S1).

This is a *source-only* readiness surface. It drives the real Engine multimodal
execute and streaming services over synthetic, network-free authorities so three
claims can be evidenced without touching Production:

* execute and streaming enforce the same authority outcome class;
* a reference-consumer-shaped ``app_id`` cannot mint tenant, subject, storage,
  path, remote-URL or data-URL authority from the request wire;
* the opaque ``attachment_ref`` contract does not drift per consumer.

The harness reuses the accepted authorities already composed in Production —
``MultimodalAttachmentEngineService`` / ``MultimodalStreamingEngineService``,
``require_opaque_attachment_ref`` and ``TrustedCallerScope`` — and stands in
only for the two deployment-owned inputs (the scoped image byte store and the
Control Plane session scope authority). No storage resolver, persistence
authority or provider runtime is created here.

It deliberately does not know, and never claims, the deployed version, the
served bindings or a rollback target: those fields carry the
``UNRESOLVED_FOR_LIVE_AUTHORITY`` sentinel. ``contract_manifest`` state is read,
never written; the paired test pins the A6 DEFERRED posture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus, UsageMetadata
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.streaming_runtime import StreamingExecutionEvent

from app.attachment_byte_store import ImageByteStoreError, StoredImageRecord
from app.contract_manifest import current_engine_contract_manifest
from app.document_context_service import TrustedCallerScope
from app.multimodal_attachment_service import (
    MULTIMODAL_EXECUTE_PATH,
    MULTIMODAL_STREAM_PATH,
    MultimodalAttachmentEngineService,
    MultimodalStreamingEngineService,
)
from app.service import ServiceResponse

MULTIMODAL_DEPLOYMENT_TARGET = "Cloudflare Workers (padiem-ai-engine)"
MULTIMODAL_MUTATION_SCOPE = "A6 source-only readiness harness; no Production authority"
UNRESOLVED_FOR_LIVE_AUTHORITY = "UNRESOLVED_FOR_LIVE_AUTHORITY"

# A6 reuses the established Engine reference-consumer labels, in the same order
# the accepted A5 harness pins them: ``b54-padiem-claw`` and ``b62-padiem-chat``.
# No new product or consumer identity is introduced here. The synthetic app IDs
# derived from these labels stay source-only evidence identities and do not claim
# Production app registration.
MULTIMODAL_REFERENCE_CONSUMERS = ("b54-padiem-claw", "b62-padiem-chat")

_A6_FEATURE_IDS = (
    "multimodal_completed_run",
    "multimodal_streaming_run",
    "attachment_admission",
    "document_admission",
    "document_projection",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

_SYNTHETIC_TENANT_ID = "tenant-a6-synthetic"
_SYNTHETIC_SUBJECT_ID = "subject-a6-synthetic"
_SYNTHETIC_SESSION_ID = "session-a6-synthetic"
_VALID_REF = "att_" + "a6" * 8 + "01"
_FOREIGN_REF = "att_" + "fe" * 8 + "01"
_MEDIA_TYPE = "image/png"
_SYNTHETIC_PNG = b"\x89PNG\r\n\x1a\n" + b"a6-synthetic-payload"
_MINTED_AT = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class MultimodalProbeResult:
    case: str
    ok: bool
    error_code: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {"case": self.case, "ok": self.ok, "error_code": self.error_code}


@dataclass(frozen=True, slots=True)
class ExecuteStreamParityResult:
    case: str
    ok: bool
    execute_outcome: str
    stream_outcome: str
    execute_error_code: str | None
    stream_error_code: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "ok": self.ok,
            "execute_outcome": self.execute_outcome,
            "stream_outcome": self.stream_outcome,
            "execute_error_code": self.execute_error_code,
            "stream_error_code": self.stream_error_code,
        }


@dataclass(frozen=True, slots=True)
class MultimodalReferenceParityResult:
    consumer: str
    app_id: str
    ok: bool
    error_code: str | None
    finding: str
    rejected_cases: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "app_id": self.app_id,
            "ok": self.ok,
            "error_code": self.error_code,
            "finding": self.finding,
            "rejected_cases": list(self.rejected_cases),
        }


@dataclass(frozen=True, slots=True)
class MultimodalActivationEvidence:
    current_main: str
    reference_consumers: tuple[str, ...]
    synthetic_cases: tuple[MultimodalProbeResult, ...]
    execute_stream_parity: tuple[ExecuteStreamParityResult, ...]
    reference_parity: tuple[MultimodalReferenceParityResult, ...]
    manifest_state: Mapping[str, str]
    deployment_target: str = MULTIMODAL_DEPLOYMENT_TARGET
    real_provider_call_count: int = 0
    real_user_data: int = 0
    mutation_scope: str = MULTIMODAL_MUTATION_SCOPE
    final_disposition: str = "PENDING_PRODUCTION_AUTHORIZATION"
    current_deployed_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    rollback_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    served_bindings: str = UNRESOLVED_FOR_LIVE_AUTHORITY

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_main": self.current_main,
            "deployment_target": self.deployment_target,
            "reference_consumers": list(self.reference_consumers),
            "synthetic_cases": [case.to_public_dict() for case in self.synthetic_cases],
            "execute_stream_parity": [
                item.to_public_dict() for item in self.execute_stream_parity
            ],
            "reference_parity": [
                item.to_public_dict() for item in self.reference_parity
            ],
            "manifest_state": dict(self.manifest_state),
            "real_provider_call_count": self.real_provider_call_count,
            "real_user_data": self.real_user_data,
            "mutation_scope": self.mutation_scope,
            "final_disposition": self.final_disposition,
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "served_bindings": self.served_bindings,
        }


class SyntheticImageByteStore:
    """Synthetic stand-in for the deployment-owned scoped image byte store.

    Holds exactly one in-scope attachment and one attachment owned by a foreign
    scope, over deterministic bytes. It never reaches D1 and never persists
    anything; private storage state stays inside this object so a zero-leak
    boundary can be proven.
    """

    def __init__(self, *, app_id: str) -> None:
        self._app_id = app_id
        self.fetches: list[dict[str, str]] = []

    async def fetch_image(
        self,
        *,
        attachment_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> tuple[StoredImageRecord, bytes]:
        self.fetches.append({"attachment_ref": attachment_ref, "app_id": app_id})
        if attachment_ref == _FOREIGN_REF:
            # Owned by another tenant/subject: the real scoped store answers
            # unauthorized without disclosing whether the reference exists.
            raise ImageByteStoreError(
                "unauthorized",
                "Image attachment scope does not match the caller.",
                status_code=403,
            )
        if attachment_ref != _VALID_REF:
            raise ImageByteStoreError(
                "not_found", "Image attachment is not available.", status_code=404
            )
        record = StoredImageRecord(
            attachment_ref=_VALID_REF,
            app_id=self._app_id,
            tenant_id=_SYNTHETIC_TENANT_ID,
            subject_id=_SYNTHETIC_SUBJECT_ID,
            media_type=_MEDIA_TYPE,
            byte_size=len(_SYNTHETIC_PNG),
            created_at=_MINTED_AT,
            expires_at=_MINTED_AT + timedelta(hours=1),
        )
        return record, _SYNTHETIC_PNG


class SyntheticSessionScopeAuthority:
    """Synthetic stand-in for the Control Plane auth-session scope authority.

    The trusted scope triple is minted from the authenticated session only. A
    request body can never select tenant or subject, and an unknown session
    yields no scope at all.
    """

    def __init__(self, *, app_id: str) -> None:
        self._app_id = app_id
        self.mints: list[dict[str, str]] = []

    async def scope_for_request(
        self, *, app_id: str, auth_session_id: str
    ) -> TrustedCallerScope:
        self.mints.append({"app_id": app_id, "auth_session_id": auth_session_id})
        if auth_session_id != _SYNTHETIC_SESSION_ID:
            raise ValueError("unknown auth session")
        return TrustedCallerScope(
            app_id=self._app_id,
            subject_id=_SYNTHETIC_SUBJECT_ID,
            tenant_id=_SYNTHETIC_TENANT_ID,
        )


class SyntheticMultimodalRuntime:
    """Stands in for the B14-backed multimodal runtime and records the seam.

    ``runtime_calls`` counts invocations of *this synthetic* seam, not provider
    calls: the harness never constructs ``MultimodalExecutionRuntime`` and never
    builds a B14 transport, so ``real_provider_call_count`` stays 0 and the
    paired test pins that with an import-level guard.
    """

    def __init__(self, *, app_id: str) -> None:
        self._app_id = app_id
        self.runtime_calls = 0
        self.requests: list[Any] = []

    def _route(self) -> B14RouteMetadata:
        return B14RouteMetadata(
            selected_provider="synthetic-provider",
            selected_model="synthetic/model",
            actual_response_model="synthetic/model",
            attempt_count=1,
            fallback_used=False,
        )

    def _metadata(self, status: RunStatus) -> RunMetadata:
        return RunMetadata(
            trace_id="trace-a6-synthetic",
            app_id=self._app_id,
            agent_id="a6-image-agent",
            session_id=_SYNTHETIC_SESSION_ID,
            status=status,
            provider="synthetic-provider",
            model="synthetic/model",
            duration_ms=1,
            usage=UsageMetadata(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    def _result(self) -> ExecutionResult:
        self.runtime_calls += 1
        return ExecutionResult(
            answer="a6-synthetic",
            route=self._route(),
            metadata=self._metadata(RunStatus.COMPLETED),
        )

    async def run(self, request: Any) -> ExecutionResult:
        self.requests.append(request)
        return self._result()

    def stream(self, request: Any):
        self.requests.append(request)

        async def _events():
            # The accepted streaming contract requires one running progress
            # event and one terminal event that carries the answer only.
            self.runtime_calls += 1
            yield StreamingExecutionEvent(
                delta_content="a6-synthetic",
                answer=None,
                finish_reason=None,
                route=self._route(),
                metadata=self._metadata(RunStatus.MODEL_RUNNING),
            )
            yield StreamingExecutionEvent(
                delta_content=None,
                answer="a6-synthetic",
                finish_reason="stop",
                route=self._route(),
                metadata=self._metadata(RunStatus.COMPLETED),
                done=True,
            )

        return _events()


@dataclass(frozen=True, slots=True)
class _A6Fixture:
    app_id: str
    store: SyntheticImageByteStore
    authority: SyntheticSessionScopeAuthority
    runtime: SyntheticMultimodalRuntime
    execute: MultimodalAttachmentEngineService
    streaming: MultimodalStreamingEngineService


def synthetic_app_id(consumer: str) -> str:
    """Return the bounded source-only evidence identity for one consumer."""

    app_id = f"{consumer}-a6-parity"
    if not _ID_RE.fullmatch(app_id):
        raise ValueError("A6 reference consumer label is not a safe identifier")
    return app_id


def _fixture(app_id: str) -> _A6Fixture:
    store = SyntheticImageByteStore(app_id=app_id)
    authority = SyntheticSessionScopeAuthority(app_id=app_id)
    runtime = SyntheticMultimodalRuntime(app_id=app_id)
    return _A6Fixture(
        app_id=app_id,
        store=store,
        authority=authority,
        runtime=runtime,
        execute=MultimodalAttachmentEngineService(
            runtime_factory=lambda _app_id: runtime,
            image_byte_store=store,
            scope_authority=authority,
        ),
        streaming=MultimodalStreamingEngineService(
            runtime_factory=lambda _app_id: runtime,
            image_byte_store=store,
            scope_authority=authority,
        ),
    )


def valid_payload(app_id: str, ref: str = _VALID_REF) -> dict[str, Any]:
    """The accepted reference-only wire shape for one synthetic consumer."""

    return {
        "app_id": app_id,
        "agent": {
            "id": "a6-image-agent",
            "title": "A6 synthetic image agent",
            "description": "Bounded image description assistant.",
            "system_instruction": "Describe the image carefully.",
            "task_type": "general",
            "optimize_for": "korean",
            "max_tokens": 64,
            "required_capabilities": ["chat", "image"],
            "model_policy": {
                "model": "b14/auto",
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        },
        "messages": [{"role": "user", "content": "synthetic a6 probe"}],
        "attachment_ref": ref,
        "session_id": _SYNTHETIC_SESSION_ID,
        "trace_id": "trace-a6-synthetic",
    }


# Each rejected case: (case, payload mutation, expected safe error code).
# ``None`` for the stream code means "must equal the execute code" is asserted
# separately by the parity probe, so a per-route drift cannot be hidden.
_REJECTED_CASES: tuple[tuple[str, Any, str], ...] = (
    ("caller_tenant_id_rejected", ("tenant_id", _SYNTHETIC_TENANT_ID), "invalid_request"),
    ("caller_subject_id_rejected", ("subject_id", _SYNTHETIC_SUBJECT_ID), "invalid_request"),
    (
        "caller_storage_authority_rejected",
        ("storage_locator", "s3://padiem-private-attachments/a6/obj-1"),
        "invalid_request",
    ),
    ("attachment_url_rejected", ("attachment_url", "https://evil.example/x.png"), "invalid_request"),
    (
        "local_path_ref_rejected",
        ("attachment_ref", "/tmp/a6-cat.png"),
        "invalid_attachment_reference",
    ),
    (
        "windows_path_ref_rejected",
        ("attachment_ref", "C:\\Users\\me\\a6-cat.png"),
        "invalid_attachment_reference",
    ),
    (
        "remote_url_ref_rejected",
        ("attachment_ref", "https://example.com/a6-cat.png"),
        "invalid_attachment_reference",
    ),
    (
        "storage_scheme_ref_rejected",
        ("attachment_ref", "r2://a6-bucket/key"),
        "invalid_attachment_reference",
    ),
    (
        "data_url_ref_rejected",
        ("attachment_ref", "data:image/png;base64,iVBORw0KGgo="),
        "invalid_attachment_reference",
    ),
    ("non_opaque_ref_rejected", ("attachment_ref", "att_short"), "invalid_attachment_reference"),
    ("credential_shaped_ref_rejected", ("attachment_ref", "AKIAEXAMPLECREDENTIAL1750"), "invalid_attachment_reference"),
)

_CROSS_SCOPE_CASE = ("cross_scope_attachment_rejected", _FOREIGN_REF)
# Two distinct fail-closed shapes: the wire omits the session entirely, and the
# wire carries an empty session. They are refused at different layers, so they
# are separate cases rather than one collapsed assertion.
_MISSING_SESSION_CASE = "missing_session_fails_closed"
_EMPTY_SESSION_CASE = "empty_session_fails_closed"


def _payload_with(app_id: str, mutation: Any) -> dict[str, Any]:
    payload = valid_payload(app_id)
    key, value = mutation
    payload[key] = value
    return payload


def _error_code(response: Any) -> str | None:
    if not isinstance(response, ServiceResponse):
        return None
    body = response.body if isinstance(response.body, Mapping) else {}
    error = body.get("error")
    return error.get("code") if isinstance(error, Mapping) else None


def _status(response: Any) -> int | None:
    return getattr(response, "status_code", None)


def _authority_outcome(response: Any) -> tuple[str, str | None]:
    """Normalize a route answer to one authority outcome class.

    Execute answers with a ``ServiceResponse`` envelope while streaming answers
    with a ``PreparedStream`` once it has accepted the request, so comparing raw
    status codes across the two routes would report drift that is only an
    envelope difference. Both routes resolve attachment authority *eagerly*, so
    the accepted-versus-rejected class and its safe code are directly comparable.
    """

    code = _error_code(response)
    if code is not None:
        return ("rejected", code)
    if isinstance(response, ServiceResponse):
        return ("accepted", None) if response.status_code == 200 else ("rejected", "unexpected_status")
    return ("accepted", None)


async def _run_execute(fixture: _A6Fixture, payload: dict[str, Any]) -> Any:
    return await fixture.execute.handle(
        method="POST",
        path=MULTIMODAL_EXECUTE_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


async def _run_stream(fixture: _A6Fixture, payload: dict[str, Any]) -> Any:
    return await fixture.streaming.prepare(
        method="POST",
        path=MULTIMODAL_STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


async def run_synthetic_probes(*, app_id: str) -> tuple[MultimodalProbeResult, ...]:
    """Drive cases A-K for one synthetic consumer identity, provider-free."""

    results: list[MultimodalProbeResult] = []

    # A. valid trusted attachment shape reaches the authority seam and completes.
    fixture = _fixture(app_id)
    execute_response = await _run_execute(fixture, valid_payload(app_id))
    stream_prepared = await _run_stream(fixture, valid_payload(app_id))
    happy_ok = (
        _status(execute_response) == 200
        and _error_code(execute_response) is None
        and not isinstance(stream_prepared, ServiceResponse)
        and _status(stream_prepared) is None
        and len(fixture.store.fetches) == 2
        and len(fixture.authority.mints) == 2
        and fixture.runtime.runtime_calls == 2
    )
    results.append(
        MultimodalProbeResult(
            case="valid_trusted_attachment_shape_reaches_authority_seam",
            ok=happy_ok,
            error_code=_error_code(execute_response),
        )
    )

    # A2. the resolved bytes never ride back out as a caller-visible locator.
    projected = json.dumps(
        getattr(execute_response, "body", {}), sort_keys=True, default=str
    )
    leak_free = not any(
        needle in projected
        for needle in (
            _SYNTHETIC_TENANT_ID,
            _SYNTHETIC_SUBJECT_ID,
            "s3://",
            "r2://",
            "/tmp/",
            "base64,",
        )
    )
    results.append(
        MultimodalProbeResult(
            case="public_response_projects_no_private_state",
            ok=leak_free,
            error_code=None if leak_free else "unsafe_public_evidence",
        )
    )

    # B-I. every caller-minted authority shape is refused on both routes.
    for case, mutation, expected in _REJECTED_CASES:
        probe = _fixture(app_id)
        payload = _payload_with(app_id, mutation)
        execute_error = _error_code(await _run_execute(probe, payload))
        stream_error = _error_code(await _run_stream(probe, payload))
        touched_store = len(probe.store.fetches) + len(probe.authority.mints)
        results.append(
            MultimodalProbeResult(
                case=case,
                ok=(
                    execute_error == expected
                    and stream_error == expected
                    and touched_store == 0
                ),
                error_code=execute_error,
            )
        )

    # J. no authenticated session means no minted scope: fail closed, both routes.
    missing_session = _fixture(app_id)
    payload = valid_payload(app_id)
    payload.pop("session_id")
    execute_error = _error_code(await _run_execute(missing_session, payload))
    stream_error = _error_code(await _run_stream(missing_session, payload))
    results.append(
        MultimodalProbeResult(
            case=_MISSING_SESSION_CASE,
            ok=(
                execute_error == "attachment_resolver_unavailable"
                and stream_error == "attachment_resolver_unavailable"
                and len(missing_session.store.fetches) == 0
                and len(missing_session.authority.mints) == 0
            ),
            error_code=execute_error,
        )
    )

    # J2. an empty session id is refused at the wire contract, before any scope
    # authority is consulted, on both routes.
    empty_session = _fixture(app_id)
    payload = {**valid_payload(app_id), "session_id": ""}
    execute_error = _error_code(await _run_execute(empty_session, payload))
    stream_error = _error_code(await _run_stream(empty_session, payload))
    results.append(
        MultimodalProbeResult(
            case=_EMPTY_SESSION_CASE,
            ok=(
                execute_error == "invalid_request"
                and stream_error == "invalid_request"
                and len(empty_session.store.fetches) == 0
            ),
            error_code=execute_error,
        )
    )

    # K. an attachment owned by a foreign scope is refused on both routes.
    cross_scope = _fixture(app_id)
    payload = valid_payload(app_id, _FOREIGN_REF)
    execute_error = _error_code(await _run_execute(cross_scope, payload))
    stream_error = _error_code(await _run_stream(cross_scope, payload))
    results.append(
        MultimodalProbeResult(
            case=_CROSS_SCOPE_CASE[0],
            ok=(
                execute_error == "attachment_scope_mismatch"
                and execute_error == stream_error
            ),
            error_code=execute_error,
        )
    )
    return tuple(results)


async def run_execute_stream_parity_probe(
    *, app_id: str
) -> tuple[ExecuteStreamParityResult, ...]:
    """Case L: both routes must answer the same authority outcome class."""

    cases: list[tuple[str, dict[str, Any]]] = [
        ("valid_trusted_attachment_shape_reaches_authority_seam", valid_payload(app_id))
    ]
    for case, mutation, _expected in _REJECTED_CASES:
        cases.append((case, _payload_with(app_id, mutation)))
    cases.append((_MISSING_SESSION_CASE, {k: v for k, v in valid_payload(app_id).items() if k != "session_id"}))
    cases.append((_EMPTY_SESSION_CASE, {**valid_payload(app_id), "session_id": ""}))
    cases.append(
        (
            _CROSS_SCOPE_CASE[0],
            valid_payload(app_id, _CROSS_SCOPE_CASE[1]),
        )
    )

    results: list[ExecuteStreamParityResult] = []
    for case, payload in cases:
        fixture = _fixture(app_id)
        execute_outcome = _authority_outcome(await _run_execute(fixture, payload))
        stream_outcome = _authority_outcome(await _run_stream(fixture, payload))
        results.append(
            ExecuteStreamParityResult(
                case=case,
                ok=execute_outcome == stream_outcome,
                execute_outcome=execute_outcome[0],
                stream_outcome=stream_outcome[0],
                execute_error_code=execute_outcome[1],
                stream_error_code=stream_outcome[1],
            )
        )
    return tuple(results)


async def run_reference_parity_probe(
    consumers: tuple[str, ...] = MULTIMODAL_REFERENCE_CONSUMERS,
) -> tuple[MultimodalReferenceParityResult, ...]:
    """Run the full rejection set per reference consumer; drift is a failure."""

    results: list[MultimodalReferenceParityResult] = []
    for consumer in consumers:
        app_id = synthetic_app_id(consumer)
        probes = await run_synthetic_probes(app_id=app_id)
        parity = await run_execute_stream_parity_probe(app_id=app_id)
        rejected = tuple(
            probe.case for probe in probes if probe.case.endswith("_rejected") and probe.ok
        )
        failed = [probe for probe in probes if not probe.ok]
        failed_parity = [item for item in parity if not item.ok]
        if failed:
            results.append(
                MultimodalReferenceParityResult(
                    consumer=consumer,
                    app_id=app_id,
                    ok=False,
                    error_code=failed[0].error_code or "synthetic_probe_failed",
                    finding=f"A6 synthetic probe failed: {failed[0].case}",
                    rejected_cases=rejected,
                )
            )
            continue
        if failed_parity:
            results.append(
                MultimodalReferenceParityResult(
                    consumer=consumer,
                    app_id=app_id,
                    ok=False,
                    error_code="execute_stream_parity_drift",
                    finding=f"A6 execute/stream drift: {failed_parity[0].case}",
                    rejected_cases=rejected,
                )
            )
            continue
        results.append(
            MultimodalReferenceParityResult(
                consumer=consumer,
                app_id=app_id,
                ok=True,
                error_code=None,
                finding=(
                    "bounded A6 reference contract completed and caller-minted "
                    "authority was rejected on execute and stream"
                ),
                rejected_cases=rejected,
            )
        )
    return tuple(results)


def a6_manifest_state() -> dict[str, str]:
    """Read the A6 posture straight from the accepted contract manifest."""

    manifest = current_engine_contract_manifest()
    return {
        feature_id: manifest.feature_state(feature_id).value
        for feature_id in _A6_FEATURE_IDS
    }


async def evaluate_multimodal_readiness(
    *, current_main: str
) -> MultimodalActivationEvidence:
    if not isinstance(current_main, str) or not re.fullmatch(
        r"[0-9a-f]{40}", current_main
    ):
        raise ValueError("current_main must be a full commit sha")
    probe_app_id = synthetic_app_id(MULTIMODAL_REFERENCE_CONSUMERS[0])
    synthetic_cases = await run_synthetic_probes(app_id=probe_app_id)
    parity = await run_execute_stream_parity_probe(app_id=probe_app_id)
    reference_parity = await run_reference_parity_probe()
    return MultimodalActivationEvidence(
        current_main=current_main,
        reference_consumers=MULTIMODAL_REFERENCE_CONSUMERS,
        synthetic_cases=synthetic_cases,
        execute_stream_parity=parity,
        reference_parity=reference_parity,
        manifest_state=a6_manifest_state(),
    )
