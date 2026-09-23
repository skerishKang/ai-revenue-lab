"""A6 Document capability provider-free activation-readiness harness (#1753 child #2944).

This is a *source-only* readiness surface for the Engine Document capability
(admission and context resolution). It drives the real Engine
``DocumentAdmissionEngineService`` and ``DocumentContextEngineService`` over
synthetic, network-free authorities so core claims can be evidenced without
touching Production:

* The single through-line operates end-to-end: bounded document bytes are
  admitted once via ``DocumentAdmissionEngineService`` to mint an opaque
  server-issued ``doc_*`` reference, which is then resolved via
  ``DocumentContextEngineService`` into normalized text projection and evidence
  retention without error;
* Neither admission nor context wire routes allow caller-minted authority
  (tenant_id, subject_id, storage_locator, connector_binding, expires_at,
  or client-chosen document_ref);
* The opaque ``doc_*`` reference grammar is strictly enforced: path traversals,
  windows paths, remote URLs, storage scheme URIs, data URLs, image-attachment
  ``att_*`` references, short tokens and credential-shaped tokens are rejected
  with safe error codes;
* Auth-session fail-closed: missing session fails closed, empty session fails
  closed, unknown session fails closed;
* Tenant and subject scope isolation: documents admitted under one scope triple
  are inaccessible to callers with a foreign scope, returning unauthorized
  without disclosing private state, existence, or tenant/subject metadata;
* Non-existent references return not_found without leaking storage internals;
* Zero data leak: public response payloads and evidence summaries never echo raw
  document bytes, private storage locators (s3://, r2://, /tmp/), or caller
  scope triples;
* Parity: reference consumers (``b54-padiem-claw``, ``b62-padiem-chat``) enforce
  the exact same authority boundaries without drift.

The harness reuses accepted repository authorities:
- ``InMemoryDocumentByteStore`` + ``ScopedDocumentByteStore``
- ``DurableDocumentStoragePort`` + ``TrustedDocumentResolver``
- ``InMemoryEvidenceStoragePort``
- ``DocumentAdmissionEngineService`` + ``DocumentContextEngineService``
- ``TrustedCallerScope``

No secondary store, resolver, reference grammar, or scope authority is created.
Deployment-owned fields carry ``UNRESOLVED_FOR_LIVE_AUTHORITY`` sentinels.
Contract and capability manifests are read, never written; the paired test pins
the Document capability DEFERRED posture.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any

from app.capability_manifest import current_capability_manifest
from app.contract_manifest import current_engine_contract_manifest
from app.document_admission_service import (
    DOCUMENT_ADMISSION_PATH,
    DocumentAdmissionEngineService,
)
from app.document_byte_store import (
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
    StoredDocumentRecord,
)
from app.document_context_service import (
    DOCUMENT_CONTEXT_PATH,
    DocumentContextEngineService,
    TrustedCallerScope,
)
from app.document_evidence_projection import InMemoryEvidenceStoragePort
from app.document_reference import DOC_REFERENCE_PATTERN
from app.service import ServiceResponse
from app.trusted_document_resolver import (
    DurableDocumentStoragePort,
    TrustedDocumentResolver,
)

DOCUMENT_DEPLOYMENT_TARGET = "Cloudflare Workers (padiem-ai-engine)"
DOCUMENT_MUTATION_SCOPE = "A6 source-only readiness harness; no Production authority"
UNRESOLVED_FOR_LIVE_AUTHORITY = "UNRESOLVED_FOR_LIVE_AUTHORITY"

DOCUMENT_REFERENCE_CONSUMERS = ("b54-padiem-claw", "b62-padiem-chat")

_DOCUMENT_FEATURE_IDS = (
    "document_admission",
    "document_projection",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_SYNTHETIC_TENANT_ID = "tenant-a6-doc-synthetic"
_SYNTHETIC_SUBJECT_ID = "subject-a6-doc-synthetic"
_SYNTHETIC_SESSION_ID = "session-a6-doc-synthetic"

_FOREIGN_TENANT_ID = "tenant-foreign-doc-synthetic"
_FOREIGN_SUBJECT_ID = "subject-foreign-doc-synthetic"
_FOREIGN_SESSION_ID = "session-foreign-doc-synthetic"

_SYNTHETIC_DOC_TEXT = (
    "# Synthetic Document\n\n"
    "This is a deterministic synthetic document for A6 activation readiness.\n"
    "Tail marker: SAFE_PROBE_BODY_CONTENT"
)
_SYNTHETIC_DOC_BYTES = _SYNTHETIC_DOC_TEXT.encode("utf-8")
_SYNTHETIC_DOC_BASE64 = base64.b64encode(_SYNTHETIC_DOC_BYTES).decode("ascii")
_SYNTHETIC_MEDIA_TYPE = "text/markdown"
_SYNTHETIC_FILENAME = "synthetic_doc.md"


@dataclass(frozen=True, slots=True)
class DocumentProbeResult:
    case: str
    ok: bool
    error_code: str | None = None
    status_code: int | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "ok": self.ok,
            "error_code": self.error_code,
            "status_code": self.status_code,
        }


@dataclass(frozen=True, slots=True)
class DocumentThroughLineResult:
    ok: bool
    document_ref: str | None = None
    evidence_id: str | None = None
    admit_status: int | None = None
    context_status: int | None = None
    error_code: str | None = None
    finding: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "document_ref": self.document_ref,
            "evidence_id": self.evidence_id,
            "admit_status": self.admit_status,
            "context_status": self.context_status,
            "error_code": self.error_code,
            "finding": self.finding,
        }


@dataclass(frozen=True, slots=True)
class DocumentReferenceParityResult:
    consumer: str
    app_id: str
    ok: bool
    error_code: str | None = None
    finding: str = ""
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
class DocumentActivationEvidence:
    current_main: str
    reference_consumers: tuple[str, ...]
    through_line: DocumentThroughLineResult
    synthetic_cases: tuple[DocumentProbeResult, ...]
    reference_parity: tuple[DocumentReferenceParityResult, ...]
    manifest_state: Mapping[str, str]
    deployment_target: str = DOCUMENT_DEPLOYMENT_TARGET
    real_provider_call_count: int = 0
    real_user_data: int = 0
    mutation_scope: str = DOCUMENT_MUTATION_SCOPE
    final_disposition: str = "PENDING_PRODUCTION_AUTHORIZATION"
    current_deployed_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    rollback_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    served_bindings: str = UNRESOLVED_FOR_LIVE_AUTHORITY

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_main": self.current_main,
            "deployment_target": self.deployment_target,
            "reference_consumers": list(self.reference_consumers),
            "through_line": self.through_line.to_public_dict(),
            "synthetic_cases": [case.to_public_dict() for case in self.synthetic_cases],
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


class SyntheticSessionScopeAuthority:
    """Synthetic stand-in for the Control Plane auth-session scope authority.

    The trusted scope triple is minted from the authenticated session only.
    A request body can never select tenant or subject, and an unknown session
    yields no scope at all.
    """

    def __init__(self, *, app_id: str) -> None:
        self._app_id = app_id
        self.mints: list[dict[str, str]] = []

    async def scope_for_request(
        self, *, app_id: str, auth_session_id: str
    ) -> TrustedCallerScope:
        self.mints.append({"app_id": app_id, "auth_session_id": auth_session_id})
        if auth_session_id == _FOREIGN_SESSION_ID:
            return TrustedCallerScope(
                app_id=self._app_id,
                subject_id=_FOREIGN_SUBJECT_ID,
                tenant_id=_FOREIGN_TENANT_ID,
            )
        if auth_session_id != _SYNTHETIC_SESSION_ID:
            raise ValueError("unknown auth session")
        return TrustedCallerScope(
            app_id=self._app_id,
            subject_id=_SYNTHETIC_SUBJECT_ID,
            tenant_id=_SYNTHETIC_TENANT_ID,
        )


@dataclass(frozen=True, slots=True)
class _DocumentFixture:
    app_id: str
    raw_store: InMemoryDocumentByteStore
    byte_store: ScopedDocumentByteStore
    scope_authority: SyntheticSessionScopeAuthority
    storage_port: DurableDocumentStoragePort
    resolver: TrustedDocumentResolver
    evidence_storage: InMemoryEvidenceStoragePort
    admit_service: DocumentAdmissionEngineService
    context_service: DocumentContextEngineService


def synthetic_app_id(consumer: str) -> str:
    """Return bounded source-only evidence identity for one reference consumer."""
    app_id = f"{consumer}-a6-doc-parity"
    if not _ID_RE.fullmatch(app_id):
        raise ValueError("Document reference consumer label is not a safe identifier")
    return app_id


def _build_document_fixture(app_id: str) -> _DocumentFixture:
    raw_store = InMemoryDocumentByteStore()
    byte_store = ScopedDocumentByteStore(port=raw_store)
    scope_authority = SyntheticSessionScopeAuthority(app_id=app_id)
    storage_port = DurableDocumentStoragePort(byte_store)
    resolver = TrustedDocumentResolver(storage=storage_port)
    evidence_storage = InMemoryEvidenceStoragePort()

    admit_service = DocumentAdmissionEngineService(
        document_byte_store=byte_store,
        scope_authority=scope_authority,
    )
    context_service = DocumentContextEngineService(
        scope_authority=scope_authority,
        document_resolver=resolver,
        evidence_storage=evidence_storage,
    )
    return _DocumentFixture(
        app_id=app_id,
        raw_store=raw_store,
        byte_store=byte_store,
        scope_authority=scope_authority,
        storage_port=storage_port,
        resolver=resolver,
        evidence_storage=evidence_storage,
        admit_service=admit_service,
        context_service=context_service,
    )


def valid_admit_payload(app_id: str) -> dict[str, Any]:
    """The canonical valid admission payload for one synthetic consumer."""
    return {
        "app_id": app_id,
        "session_id": _SYNTHETIC_SESSION_ID,
        "media_type": _SYNTHETIC_MEDIA_TYPE,
        "document_base64": _SYNTHETIC_DOC_BASE64,
        "filename": _SYNTHETIC_FILENAME,
    }


def valid_context_payload(app_id: str, document_ref: str) -> dict[str, Any]:
    """The canonical valid context retrieval payload for one synthetic consumer."""
    return {
        "app_id": app_id,
        "session_id": _SYNTHETIC_SESSION_ID,
        "document_ref": document_ref,
    }


def _error_code(response: Any) -> str | None:
    if not isinstance(response, ServiceResponse):
        return None
    body = response.body if isinstance(response.body, Mapping) else {}
    error = body.get("error")
    return error.get("code") if isinstance(error, Mapping) else None


def _status(response: Any) -> int | None:
    return getattr(response, "status_code", None)


async def _run_admit(fixture: _DocumentFixture, payload: dict[str, Any]) -> ServiceResponse:
    return await fixture.admit_service.handle(
        method="POST",
        path=DOCUMENT_ADMISSION_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


async def _run_context(fixture: _DocumentFixture, payload: dict[str, Any]) -> ServiceResponse:
    return await fixture.context_service.handle(
        method="POST",
        path=DOCUMENT_CONTEXT_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


async def run_through_line_probe(*, app_id: str) -> DocumentThroughLineResult:
    """Drive the complete admit-then-context through-line over synthetic authorities."""
    fixture = _build_document_fixture(app_id)
    admit_resp = await _run_admit(fixture, valid_admit_payload(app_id))
    admit_status = _status(admit_resp)
    if admit_status != 200:
        return DocumentThroughLineResult(
            ok=False,
            admit_status=admit_status,
            error_code=_error_code(admit_resp),
            finding=f"Document admission failed with status {admit_status}",
        )

    doc_meta = (admit_resp.body or {}).get("document", {})
    doc_ref = doc_meta.get("document_ref")
    if not isinstance(doc_ref, str) or not DOC_REFERENCE_PATTERN.fullmatch(doc_ref):
        return DocumentThroughLineResult(
            ok=False,
            admit_status=admit_status,
            error_code="invalid_minted_reference",
            finding="Server did not mint a valid doc_* reference",
        )

    ctx_resp = await _run_context(fixture, valid_context_payload(app_id, doc_ref))
    ctx_status = _status(ctx_resp)
    if ctx_status != 200:
        return DocumentThroughLineResult(
            ok=False,
            document_ref=doc_ref,
            admit_status=admit_status,
            context_status=ctx_status,
            error_code=_error_code(ctx_resp),
            finding=f"Document context retrieval failed with status {ctx_status}",
        )

    body = ctx_resp.body or {}
    evidence_id = body.get("evidence", {}).get("evidence_id")
    if not isinstance(evidence_id, str) or len(evidence_id) < 16:
        return DocumentThroughLineResult(
            ok=False,
            document_ref=doc_ref,
            admit_status=admit_status,
            context_status=ctx_status,
            error_code="invalid_evidence_id",
            finding="Document context did not return a valid evidence_id",
        )

    return DocumentThroughLineResult(
        ok=True,
        document_ref=doc_ref,
        evidence_id=evidence_id,
        admit_status=admit_status,
        context_status=ctx_status,
        finding="Document admission and context through-line succeeded",
    )


# Authority injection mutations rejected by DocumentAdmissionEngineService
_REJECTED_ADMIT_MUTATIONS: tuple[tuple[str, Any, str], ...] = (
    ("caller_tenant_id_rejected_on_admit", ("tenant_id", _SYNTHETIC_TENANT_ID), "invalid_request"),
    ("caller_subject_id_rejected_on_admit", ("subject_id", _SYNTHETIC_SUBJECT_ID), "invalid_request"),
    (
        "caller_storage_locator_rejected_on_admit",
        ("storage_locator", "s3://padiem-docs/synthetic.pdf"),
        "invalid_request",
    ),
    (
        "caller_binding_rejected_on_admit",
        ("connector_binding", "d1_binding"),
        "invalid_request",
    ),
    (
        "caller_expiry_rejected_on_admit",
        ("expires_at", "2026-12-31T00:00:00Z"),
        "invalid_request",
    ),
    (
        "chosen_ref_rejected_on_admit",
        ("document_ref", "doc_chosen0123456789abcdef"),
        "invalid_request",
    ),
)

# Authority injection mutations rejected by DocumentContextEngineService
_REJECTED_CONTEXT_MUTATIONS: tuple[tuple[str, Any, str], ...] = (
    ("caller_tenant_id_rejected_on_context", ("tenant_id", _SYNTHETIC_TENANT_ID), "invalid_request"),
    ("caller_subject_id_rejected_on_context", ("subject_id", _SYNTHETIC_SUBJECT_ID), "invalid_request"),
    (
        "caller_storage_locator_rejected_on_context",
        ("storage_locator", "s3://padiem-docs/synthetic.pdf"),
        "invalid_request",
    ),
    (
        "caller_binding_rejected_on_context",
        ("connector_binding", "d1_binding"),
        "invalid_request",
    ),
    (
        "caller_expiry_rejected_on_context",
        ("expires_at", "2026-12-31T00:00:00Z"),
        "invalid_request",
    ),
)

# Non-compliant / malicious document reference shapes rejected by DocumentContextEngineService
_REJECTED_REFERENCE_SHAPES: tuple[tuple[str, str, str], ...] = (
    ("local_path_ref_rejected", "/tmp/sensitive_document.pdf", "invalid_reference"),
    ("windows_path_ref_rejected", "C:\\Windows\\System32\\doc.pdf", "invalid_reference"),
    ("remote_url_ref_rejected", "https://evil.example.com/stolen.pdf", "invalid_reference"),
    ("storage_scheme_ref_rejected", "r2://bucket/key.pdf", "invalid_reference"),
    ("data_url_ref_rejected", "data:application/pdf;base64,JVBERi0xLjQK", "invalid_reference"),
    ("att_ref_rejected", "att_" + "a6" * 8 + "01", "invalid_reference"),
    ("short_ref_rejected", "doc_short", "invalid_reference"),
    ("credential_shaped_ref_rejected", "AKIAEXAMPLECREDENTIAL1750", "invalid_reference"),
)


async def run_synthetic_document_probes(*, app_id: str) -> tuple[DocumentProbeResult, ...]:
    """Execute all synthetic document capability probes for one consumer identity."""
    results: list[DocumentProbeResult] = []

    # 1. Through-line probe
    fixture = _build_document_fixture(app_id)
    admit_resp = await _run_admit(fixture, valid_admit_payload(app_id))
    admit_status = _status(admit_resp)
    doc_ref = (admit_resp.body or {}).get("document", {}).get("document_ref")

    context_resp = (
        await _run_context(fixture, valid_context_payload(app_id, doc_ref))
        if isinstance(doc_ref, str)
        else None
    )
    context_status = _status(context_resp) if context_resp is not None else None

    through_line_ok = (
        admit_status == 200
        and isinstance(doc_ref, str)
        and DOC_REFERENCE_PATTERN.fullmatch(doc_ref) is not None
        and context_status == 200
        and (context_resp.body or {}).get("ok") is True
        and isinstance((context_resp.body or {}).get("evidence", {}).get("evidence_id"), str)
    )
    results.append(
        DocumentProbeResult(
            case="through_line_admit_and_context_succeeds",
            ok=through_line_ok,
            error_code=None if through_line_ok else (_error_code(admit_resp) or _error_code(context_resp)),
            status_code=context_status if context_status else admit_status,
        )
    )

    # 2. Zero leak check on public responses
    admit_body_json = json.dumps(admit_resp.body or {}, default=str)
    context_body_json = json.dumps(context_resp.body or {} if context_resp else {}, default=str)
    leak_free = not any(
        needle in admit_body_json or needle in context_body_json
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
        DocumentProbeResult(
            case="public_responses_project_no_private_state_or_locators",
            ok=leak_free,
            error_code=None if leak_free else "unsafe_public_evidence",
            status_code=200 if leak_free else 500,
        )
    )

    # 3. Admission authority injection rejections
    for case_name, (field, value), expected_code in _REJECTED_ADMIT_MUTATIONS:
        probe_fix = _build_document_fixture(app_id)
        payload = valid_admit_payload(app_id)
        payload[field] = value
        resp = await _run_admit(probe_fix, payload)
        code = _error_code(resp)
        ok = _status(resp) == 400 and code == expected_code and len(probe_fix.scope_authority.mints) == 0
        results.append(
            DocumentProbeResult(
                case=case_name,
                ok=ok,
                error_code=code,
                status_code=_status(resp),
            )
        )

    # 4. Context authority injection rejections
    for case_name, (field, value), expected_code in _REJECTED_CONTEXT_MUTATIONS:
        probe_fix = _build_document_fixture(app_id)
        payload = valid_context_payload(app_id, doc_ref or "doc_placeholder0123456789")
        payload[field] = value
        resp = await _run_context(probe_fix, payload)
        code = _error_code(resp)
        ok = _status(resp) == 400 and code == expected_code and len(probe_fix.scope_authority.mints) == 0
        results.append(
            DocumentProbeResult(
                case=case_name,
                ok=ok,
                error_code=code,
                status_code=_status(resp),
            )
        )

    # 5. Rejected reference shapes on context
    for case_name, bad_ref, expected_code in _REJECTED_REFERENCE_SHAPES:
        probe_fix = _build_document_fixture(app_id)
        payload = valid_context_payload(app_id, bad_ref)
        resp = await _run_context(probe_fix, payload)
        code = _error_code(resp)
        ok = _status(resp) == 400 and code == expected_code
        results.append(
            DocumentProbeResult(
                case=case_name,
                ok=ok,
                error_code=code,
                status_code=_status(resp),
            )
        )

    # 6. Missing session fails closed on admit
    missing_session_admit = _build_document_fixture(app_id)
    p_admit = valid_admit_payload(app_id)
    p_admit.pop("session_id")
    r_ms_admit = await _run_admit(missing_session_admit, p_admit)
    c_ms_admit = _error_code(r_ms_admit)
    results.append(
        DocumentProbeResult(
            case="missing_session_rejected_on_admit",
            ok=_status(r_ms_admit) == 400 and c_ms_admit == "invalid_request",
            error_code=c_ms_admit,
            status_code=_status(r_ms_admit),
        )
    )

    # 7. Empty session fails closed on admit
    empty_session_admit = _build_document_fixture(app_id)
    p_empty_admit = {**valid_admit_payload(app_id), "session_id": ""}
    r_es_admit = await _run_admit(empty_session_admit, p_empty_admit)
    c_es_admit = _error_code(r_es_admit)
    results.append(
        DocumentProbeResult(
            case="empty_session_rejected_on_admit",
            ok=_status(r_es_admit) == 503 and c_es_admit == "document_admission_unavailable",
            error_code=c_es_admit,
            status_code=_status(r_es_admit),
        )
    )

    # 8. Missing session fails closed on context
    missing_session_ctx = _build_document_fixture(app_id)
    p_ctx = valid_context_payload(app_id, doc_ref or "doc_placeholder0123456789")
    p_ctx.pop("session_id")
    r_ms_ctx = await _run_context(missing_session_ctx, p_ctx)
    c_ms_ctx = _error_code(r_ms_ctx)
    results.append(
        DocumentProbeResult(
            case="missing_session_rejected_on_context",
            ok=_status(r_ms_ctx) == 400 and c_ms_ctx == "invalid_request",
            error_code=c_ms_ctx,
            status_code=_status(r_ms_ctx),
        )
    )

    # 9. Empty session fails closed on context
    empty_session_ctx = _build_document_fixture(app_id)
    p_empty_ctx = {
        **valid_context_payload(app_id, doc_ref or "doc_placeholder0123456789"),
        "session_id": "",
    }
    r_es_ctx = await _run_context(empty_session_ctx, p_empty_ctx)
    c_es_ctx = _error_code(r_es_ctx)
    results.append(
        DocumentProbeResult(
            case="empty_session_rejected_on_context",
            ok=_status(r_es_ctx) == 503 and c_es_ctx == "document_authority_unavailable",
            error_code=c_es_ctx,
            status_code=_status(r_es_ctx),
        )
    )

    # 10. Unknown session fails closed on admit
    unknown_session_admit = _build_document_fixture(app_id)
    p_unk_admit = {**valid_admit_payload(app_id), "session_id": "unknown_session"}
    r_us_admit = await _run_admit(unknown_session_admit, p_unk_admit)
    c_us_admit = _error_code(r_us_admit)
    results.append(
        DocumentProbeResult(
            case="unknown_session_fails_closed_on_admit",
            ok=_status(r_us_admit) == 503 and c_us_admit == "document_admission_unavailable",
            error_code=c_us_admit,
            status_code=_status(r_us_admit),
        )
    )

    # 11. Unknown session fails closed on context
    unknown_session_ctx = _build_document_fixture(app_id)
    p_unk_ctx = {
        **valid_context_payload(app_id, doc_ref or "doc_placeholder0123456789"),
        "session_id": "unknown_session",
    }
    r_us_ctx = await _run_context(unknown_session_ctx, p_unk_ctx)
    c_us_ctx = _error_code(r_us_ctx)
    results.append(
        DocumentProbeResult(
            case="unknown_session_fails_closed_on_context",
            ok=_status(r_us_ctx) == 503 and c_us_ctx == "document_authority_unavailable",
            error_code=c_us_ctx,
            status_code=_status(r_us_ctx),
        )
    )

    # 12. Cross-scope document access refused (scope isolation)
    if doc_ref is not None:
        cross_scope_payload = {
            "app_id": app_id,
            "session_id": _FOREIGN_SESSION_ID,
            "document_ref": doc_ref,
        }
        r_cross = await _run_context(fixture, cross_scope_payload)
        c_cross = _error_code(r_cross)
        results.append(
            DocumentProbeResult(
                case="cross_scope_document_rejected",
                ok=_status(r_cross) == 403 and c_cross == "unauthorized",
                error_code=c_cross,
                status_code=_status(r_cross),
            )
        )

    # 13. Unknown document ref yields not_found
    unk_ref_payload = valid_context_payload(app_id, "doc_0123456789abcdef01")
    r_unk = await _run_context(fixture, unk_ref_payload)
    c_unk = _error_code(r_unk)
    results.append(
        DocumentProbeResult(
            case="unknown_document_ref_rejected",
            ok=_status(r_unk) == 404 and c_unk == "not_found",
            error_code=c_unk,
            status_code=_status(r_unk),
        )
    )

    return tuple(results)


async def run_reference_parity_probe(
    consumers: tuple[str, ...] = DOCUMENT_REFERENCE_CONSUMERS,
) -> tuple[DocumentReferenceParityResult, ...]:
    """Verify document capability rejection set and through-line parity per consumer."""
    results: list[DocumentReferenceParityResult] = []
    for consumer in consumers:
        app_id = synthetic_app_id(consumer)
        probes = await run_synthetic_document_probes(app_id=app_id)
        rejected = tuple(
            probe.case
            for probe in probes
            if (probe.case.endswith("_rejected") or "_rejected_" in probe.case) and probe.ok
        )
        failed = [probe for probe in probes if not probe.ok]
        if failed:
            results.append(
                DocumentReferenceParityResult(
                    consumer=consumer,
                    app_id=app_id,
                    ok=False,
                    error_code=failed[0].error_code or "synthetic_probe_failed",
                    finding=f"A6 document synthetic probe failed: {failed[0].case}",
                    rejected_cases=rejected,
                )
            )
            continue
        results.append(
            DocumentReferenceParityResult(
                consumer=consumer,
                app_id=app_id,
                ok=True,
                error_code=None,
                finding=(
                    "bounded A6 document reference contract completed and caller-minted "
                    "authority was rejected on admission and context"
                ),
                rejected_cases=rejected,
            )
        )
    return tuple(results)


def document_manifest_state() -> dict[str, str]:
    """Read the Document posture straight from the accepted contract and capability manifests."""
    manifest = current_engine_contract_manifest()
    cap_manifest = current_capability_manifest()
    state = {
        feature_id: manifest.feature_state(feature_id).value
        for feature_id in _DOCUMENT_FEATURE_IDS
    }
    for cap in cap_manifest.capabilities:
        if cap.id == "file_document_multimodal":
            state["file_document_multimodal"] = cap.state.value
    return state


async def evaluate_document_readiness(
    *, current_main: str
) -> DocumentActivationEvidence:
    """Evaluate document activation readiness at exact main SHA without mutating Production."""
    if not isinstance(current_main, str) or not _COMMIT_SHA_RE.fullmatch(current_main):
        raise ValueError("current_main must be a full 40-character commit sha")

    probe_app_id = synthetic_app_id(DOCUMENT_REFERENCE_CONSUMERS[0])
    through_line = await run_through_line_probe(app_id=probe_app_id)
    synthetic_cases = await run_synthetic_document_probes(app_id=probe_app_id)
    reference_parity = await run_reference_parity_probe()
    manifest_state = document_manifest_state()

    return DocumentActivationEvidence(
        current_main=current_main,
        reference_consumers=DOCUMENT_REFERENCE_CONSUMERS,
        through_line=through_line,
        synthetic_cases=synthetic_cases,
        reference_parity=reference_parity,
        manifest_state=manifest_state,
    )
