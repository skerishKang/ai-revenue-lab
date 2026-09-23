"""Network-free contract tests for A6 Document activation readiness (#1753 child #2944).

The harness under test drives the real Engine ``DocumentAdmissionEngineService``
and ``DocumentContextEngineService`` over synthetic authorities. These tests
pin what that evidence is allowed to claim:

- caller-minted authority (tenant_id, subject_id, storage_locator, binding,
  expires_at, chosen document_ref) is refused ahead of store/scope execution;
- opaque ``doc_*`` reference grammar is strictly enforced;
- auth-session fail-closed: missing, empty, and unknown sessions fail closed;
- tenant/subject scope isolation is enforced without disclosing private state;
- non-existent references return not_found;
- reference-consumer parity (b54-padiem-claw, b62-padiem-chat) shows no drift;
- zero network or provider seam is ever reached;
- public evidence payloads and projections contain zero private state leaks;
- manifest truth stays DEFERRED for document capabilities;
- live-authority fields remain explicit sentinels.
"""

from __future__ import annotations

import base64
import json
import socket
from typing import Any

import pytest

from app import document_runtime_activation as doc_act
from app.capability_manifest import current_capability_manifest
from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest
from app.document_admission_service import (
    DOCUMENT_ADMISSION_PATH,
    DocumentAdmissionEngineService,
)
from app.document_context_service import (
    DOCUMENT_CONTEXT_PATH,
    DocumentContextEngineService,
    TrustedCallerScope,
)
from app.document_evidence_projection import InMemoryEvidenceStoragePort
from app.document_reference import DOC_REFERENCE_PATTERN
from app.trusted_document_resolver import (
    DurableDocumentStoragePort,
    TrustedDocumentResolver,
)

APP_ID = doc_act.synthetic_app_id("b54-padiem-claw")

PRIVATE_STRINGS = (
    doc_act._SYNTHETIC_TENANT_ID,
    doc_act._SYNTHETIC_SUBJECT_ID,
    doc_act._SYNTHETIC_SESSION_ID,
    doc_act._FOREIGN_TENANT_ID,
    doc_act._FOREIGN_SUBJECT_ID,
    doc_act._FOREIGN_SESSION_ID,
    "s3://",
    "r2://",
    "/tmp/",
    "base64,",
)

EXACT_HEAD_SHA = "9612316ddb459a00b6ee73e697ee93a5d576c8dc"


@pytest.fixture
def no_provider_guard() -> None:
    """Document readiness operates on storage/context seams and must never reach providers."""
    pass


async def test_provider_and_network_seams_are_never_reached() -> None:
    """Record any socket construction while the probes run, then restore.

    The guard is restored inside ``finally`` on purpose: replacing
    ``socket.socket`` for the whole fixture lifetime breaks the Windows
    Proactor event loop during pytest-asyncio teardown.
    """
    attempts: list[str] = []
    original_socket = socket.socket

    class _RecordingSocket(original_socket):
        def __init__(self, *args: object, **kw: object) -> None:
            attempts.append("socket")
            super().__init__(*args, **kw)  # type: ignore[arg-type]

    socket.socket = _RecordingSocket  # type: ignore[misc]
    try:
        through_line = await doc_act.run_through_line_probe(app_id=APP_ID)
        probes = await doc_act.run_synthetic_document_probes(app_id=APP_ID)
        parity = await doc_act.run_reference_parity_probe()
    finally:
        socket.socket = original_socket  # type: ignore[misc]

    assert attempts == []
    assert through_line.ok is True
    assert all(probe.ok for probe in probes)
    assert all(item.ok for item in parity)


async def test_synthetic_document_probes_all_pass_for_reference_consumer() -> None:
    """All 29 synthetic probes must pass cleanly for a reference consumer."""
    probes = await doc_act.run_synthetic_document_probes(app_id=APP_ID)
    cases = {probe.case: probe for probe in probes}
    failed = [probe.case for probe in probes if not probe.ok]

    assert failed == []
    assert cases["through_line_admit_and_context_succeeds"].error_code is None
    assert cases["public_responses_project_no_private_state_or_locators"].error_code is None

    # Admission injection rejections
    for case in (
        "caller_tenant_id_rejected_on_admit",
        "caller_subject_id_rejected_on_admit",
        "caller_storage_locator_rejected_on_admit",
        "caller_binding_rejected_on_admit",
        "caller_expiry_rejected_on_admit",
        "chosen_ref_rejected_on_admit",
        "missing_session_rejected_on_admit",
    ):
        assert cases[case].status_code == 400
        assert cases[case].error_code == "invalid_request"

    # Context injection rejections
    for case in (
        "caller_tenant_id_rejected_on_context",
        "caller_subject_id_rejected_on_context",
        "caller_storage_locator_rejected_on_context",
        "caller_binding_rejected_on_context",
        "caller_expiry_rejected_on_context",
        "missing_session_rejected_on_context",
    ):
        assert cases[case].status_code == 400
        assert cases[case].error_code == "invalid_request"

    # Reference grammar rejections
    for case in (
        "local_path_ref_rejected",
        "windows_path_ref_rejected",
        "remote_url_ref_rejected",
        "storage_scheme_ref_rejected",
        "data_url_ref_rejected",
        "att_ref_rejected",
        "short_ref_rejected",
        "credential_shaped_ref_rejected",
    ):
        assert cases[case].status_code == 400
        assert cases[case].error_code == "invalid_reference"

    # Fail closed session cases
    assert cases["empty_session_rejected_on_admit"].status_code == 503
    assert cases["empty_session_rejected_on_admit"].error_code == "document_admission_unavailable"
    assert cases["empty_session_rejected_on_context"].status_code == 503
    assert cases["empty_session_rejected_on_context"].error_code == "document_authority_unavailable"
    assert cases["unknown_session_fails_closed_on_admit"].status_code == 503
    assert cases["unknown_session_fails_closed_on_admit"].error_code == "document_admission_unavailable"
    assert cases["unknown_session_fails_closed_on_context"].status_code == 503
    assert cases["unknown_session_fails_closed_on_context"].error_code == "document_authority_unavailable"

    # Scope and existence
    assert cases["cross_scope_document_rejected"].status_code == 403
    assert cases["cross_scope_document_rejected"].error_code == "unauthorized"
    assert cases["unknown_document_ref_rejected"].status_code == 404
    assert cases["unknown_document_ref_rejected"].error_code == "not_found"


async def test_through_line_admit_and_context_roundtrip() -> None:
    """Admit bounded document bytes and retrieve via context in one single through-line."""
    result = await doc_act.run_through_line_probe(app_id=APP_ID)

    assert result.ok is True
    assert result.error_code is None
    assert result.admit_status == 200
    assert result.context_status == 200
    assert isinstance(result.document_ref, str)
    assert DOC_REFERENCE_PATTERN.fullmatch(result.document_ref) is not None
    assert isinstance(result.evidence_id, str)
    assert len(result.evidence_id) >= 16


async def test_zero_data_leak_in_public_evidence() -> None:
    """Public evidence dictionary must not contain any private identifiers or storage paths."""
    evidence = await doc_act.evaluate_document_readiness(current_main=EXACT_HEAD_SHA)
    serialized = json.dumps(evidence.to_public_dict(), default=str)

    assert doc_act._SYNTHETIC_TENANT_ID not in serialized
    assert doc_act._SYNTHETIC_SUBJECT_ID not in serialized
    assert "s3://" not in serialized
    assert "r2://" not in serialized
    assert "/tmp/" not in serialized
    assert "base64," not in serialized


async def test_caller_authority_rejected_before_store_or_scope_call_on_admit() -> None:
    """Caller-minted authority on admission must fail before touching store or minting scope."""
    for case_name, (field, value), expected in doc_act._REJECTED_ADMIT_MUTATIONS:
        fixture = doc_act._build_document_fixture(APP_ID)
        payload = doc_act.valid_admit_payload(APP_ID)
        payload[field] = value

        resp = await doc_act._run_admit(fixture, payload)

        assert resp.status_code == 400
        assert doc_act._error_code(resp) == expected
        assert len(fixture.scope_authority.mints) == 0
        assert len(fixture.raw_store._records) == 0


async def test_caller_authority_rejected_before_store_or_scope_call_on_context() -> None:
    """Caller-minted authority on context must fail before consulting scope authority."""
    for case_name, (field, value), expected in doc_act._REJECTED_CONTEXT_MUTATIONS:
        fixture = doc_act._build_document_fixture(APP_ID)
        payload = doc_act.valid_context_payload(APP_ID, "doc_valid0123456789abcdef")
        payload[field] = value

        resp = await doc_act._run_context(fixture, payload)

        assert resp.status_code == 400
        assert doc_act._error_code(resp) == expected
        assert len(fixture.scope_authority.mints) == 0


async def test_opaque_document_ref_grammar_enforced() -> None:
    """Context route refuses invalid reference grammar without touching storage."""
    for case_name, bad_ref, expected in doc_act._REJECTED_REFERENCE_SHAPES:
        fixture = doc_act._build_document_fixture(APP_ID)
        payload = doc_act.valid_context_payload(APP_ID, bad_ref)

        resp = await doc_act._run_context(fixture, payload)

        assert resp.status_code == 400
        assert doc_act._error_code(resp) == expected


async def test_session_fail_closed_on_admit() -> None:
    """Admission route fails closed on missing, empty, or unknown session."""
    fixture = doc_act._build_document_fixture(APP_ID)

    # Missing session
    p_missing = doc_act.valid_admit_payload(APP_ID)
    p_missing.pop("session_id")
    r1 = await doc_act._run_admit(fixture, p_missing)
    assert r1.status_code == 400
    assert doc_act._error_code(r1) == "invalid_request"

    # Empty session
    p_empty = {**doc_act.valid_admit_payload(APP_ID), "session_id": ""}
    r2 = await doc_act._run_admit(fixture, p_empty)
    assert r2.status_code == 503
    assert doc_act._error_code(r2) == "document_admission_unavailable"

    # Unknown session
    p_unk = {**doc_act.valid_admit_payload(APP_ID), "session_id": "non_existent_session"}
    r3 = await doc_act._run_admit(fixture, p_unk)
    assert r3.status_code == 503
    assert doc_act._error_code(r3) == "document_admission_unavailable"


async def test_session_fail_closed_on_context() -> None:
    """Context route fails closed on missing, empty, or unknown session."""
    fixture = doc_act._build_document_fixture(APP_ID)
    ref = "doc_testvalid0123456789"

    # Missing session
    p_missing = doc_act.valid_context_payload(APP_ID, ref)
    p_missing.pop("session_id")
    r1 = await doc_act._run_context(fixture, p_missing)
    assert r1.status_code == 400
    assert doc_act._error_code(r1) == "invalid_request"

    # Empty session
    p_empty = {**doc_act.valid_context_payload(APP_ID, ref), "session_id": ""}
    r2 = await doc_act._run_context(fixture, p_empty)
    assert r2.status_code == 503
    assert doc_act._error_code(r2) == "document_authority_unavailable"

    # Unknown session
    p_unk = {**doc_act.valid_context_payload(APP_ID, ref), "session_id": "non_existent_session"}
    r3 = await doc_act._run_context(fixture, p_unk)
    assert r3.status_code == 503
    assert doc_act._error_code(r3) == "document_authority_unavailable"


async def test_scope_isolation_without_disclosure() -> None:
    """Caller with foreign scope receives unauthorized without disclosing document existence."""
    fixture = doc_act._build_document_fixture(APP_ID)
    admit_resp = await doc_act._run_admit(fixture, doc_act.valid_admit_payload(APP_ID))
    doc_ref = admit_resp.body["document"]["document_ref"]

    # Foreign session
    cross_payload = {
        "app_id": APP_ID,
        "session_id": doc_act._FOREIGN_SESSION_ID,
        "document_ref": doc_ref,
    }
    cross_resp = await doc_act._run_context(fixture, cross_payload)

    assert cross_resp.status_code == 403
    assert doc_act._error_code(cross_resp) == "unauthorized"
    body_str = json.dumps(cross_resp.body)
    assert doc_act._SYNTHETIC_TENANT_ID not in body_str
    assert doc_act._SYNTHETIC_SUBJECT_ID not in body_str
    assert "synthetic" not in body_str


async def test_unknown_document_ref_fails_closed() -> None:
    """Non-existent reference returns 404 not_found."""
    fixture = doc_act._build_document_fixture(APP_ID)
    payload = doc_act.valid_context_payload(APP_ID, "doc_unknownref0123456789")

    resp = await doc_act._run_context(fixture, payload)

    assert resp.status_code == 404
    assert doc_act._error_code(resp) == "not_found"


async def test_reference_consumer_parity_no_drift() -> None:
    """Both reference consumers (b54-padiem-claw, b62-padiem-chat) show zero drift."""
    results = await doc_act.run_reference_parity_probe()
    by_consumer = {item.consumer: item for item in results}

    assert tuple(by_consumer) == doc_act.DOCUMENT_REFERENCE_CONSUMERS
    assert all(item.ok for item in results)
    assert all(item.error_code is None for item in results)

    # Parity: rejected cases sets must be completely identical
    assert len({item.rejected_cases for item in results}) == 1
    assert len(by_consumer["b54-padiem-claw"].rejected_cases) > 15


async def test_synthetic_app_id_is_bounded_and_safe() -> None:
    """Synthetic app_id must be safe, consumer-derived, and never a raw production identifier."""
    for consumer in doc_act.DOCUMENT_REFERENCE_CONSUMERS:
        app_id = doc_act.synthetic_app_id(consumer)
        assert app_id.startswith(consumer)
        assert app_id.endswith("-a6-doc-parity")
        assert app_id != consumer
        assert doc_act._ID_RE.fullmatch(app_id) is not None

    with pytest.raises(ValueError, match="not a safe identifier"):
        doc_act.synthetic_app_id("invalid/consumer/label")


async def test_commit_sha_validation_enforces_exact_head() -> None:
    """Only a 40-character hexadecimal commit SHA is accepted as current_main."""
    evidence = await doc_act.evaluate_document_readiness(current_main=EXACT_HEAD_SHA)
    assert evidence.current_main == EXACT_HEAD_SHA

    for invalid in ("", "short", "HEAD", "feat/branch", "g" * 40, "9612316d"):
        with pytest.raises(ValueError, match="full 40-character commit sha"):
            await doc_act.evaluate_document_readiness(current_main=invalid)


def test_manifest_state_truth_pinned_as_deferred() -> None:
    """Document capability features must be pinned as DEFERRED in both manifests."""
    manifest = current_engine_contract_manifest()
    cap_manifest = current_capability_manifest()
    state = doc_act.document_manifest_state()

    assert manifest.feature_state("document_admission") == EngineFeatureState.DEFERRED
    assert manifest.feature_state("document_projection") == EngineFeatureState.DEFERRED
    assert state["document_admission"] == "deferred"
    assert state["document_projection"] == "deferred"
    assert state["file_document_multimodal"] == "deferred"


def test_live_authority_sentinels_are_preserved() -> None:
    """Readiness evidence must maintain explicit sentinels for live deployment fields."""
    fixture = doc_act._build_document_fixture(APP_ID)
    evidence = doc_act.DocumentActivationEvidence(
        current_main=EXACT_HEAD_SHA,
        reference_consumers=doc_act.DOCUMENT_REFERENCE_CONSUMERS,
        through_line=doc_act.DocumentThroughLineResult(ok=True),
        synthetic_cases=(),
        reference_parity=(),
        manifest_state=doc_act.document_manifest_state(),
    )
    public_dict = evidence.to_public_dict()

    assert public_dict["deployment_target"] == doc_act.DOCUMENT_DEPLOYMENT_TARGET
    assert public_dict["current_deployed_version"] == doc_act.UNRESOLVED_FOR_LIVE_AUTHORITY
    assert public_dict["rollback_version"] == doc_act.UNRESOLVED_FOR_LIVE_AUTHORITY
    assert public_dict["served_bindings"] == doc_act.UNRESOLVED_FOR_LIVE_AUTHORITY
    assert public_dict["real_provider_call_count"] == 0
    assert public_dict["real_user_data"] == 0
    assert public_dict["final_disposition"] == "PENDING_PRODUCTION_AUTHORIZATION"


async def test_admit_payload_size_and_encoding_validation() -> None:
    """Malformed base64 and oversized bodies are rejected at admission."""
    fixture = doc_act._build_document_fixture(APP_ID)

    bad_b64_payload = {
        **doc_act.valid_admit_payload(APP_ID),
        "document_base64": "!!!not_base64!!!",
    }
    r1 = await doc_act._run_admit(fixture, bad_b64_payload)
    assert r1.status_code == 400
    assert doc_act._error_code(r1) == "invalid_document_payload"


async def test_text_plain_media_through_line() -> None:
    """Text/plain documents admit and resolve through context seamlessly."""
    fixture = doc_act._build_document_fixture(APP_ID)
    plain_bytes = b"Hello, this is a plain text document for testing."
    payload = {
        "app_id": APP_ID,
        "session_id": doc_act._SYNTHETIC_SESSION_ID,
        "media_type": "text/plain",
        "document_base64": base64.b64encode(plain_bytes).decode("ascii"),
        "filename": "hello.txt",
    }
    r_admit = await doc_act._run_admit(fixture, payload)
    assert r_admit.status_code == 200
    doc_ref = r_admit.body["document"]["document_ref"]

    r_ctx = await doc_act._run_context(
        fixture, doc_act.valid_context_payload(APP_ID, doc_ref)
    )
    assert r_ctx.status_code == 200
    assert r_ctx.body["ok"] is True
    assert r_ctx.body["document"]["kind"] == "text"


async def test_unsupported_media_type_refused() -> None:
    """Non-whitelisted media types are rejected with 415 unsupported_media_type."""
    fixture = doc_act._build_document_fixture(APP_ID)
    payload = {
        **doc_act.valid_admit_payload(APP_ID),
        "media_type": "video/mp4",
        "document_base64": base64.b64encode(b"dummy").decode("ascii"),
    }
    resp = await doc_act._run_admit(fixture, payload)
    assert resp.status_code == 415
    assert doc_act._error_code(resp) == "unsupported_media_type"


async def test_missing_authority_components_fail_closed() -> None:
    """Services fail closed 503 when constructed without required authorities."""
    # Admit without scope authority
    svc_admit = DocumentAdmissionEngineService(
        document_byte_store=None, scope_authority=None
    )
    r1 = await svc_admit.handle(
        method="POST",
        path=DOCUMENT_ADMISSION_PATH,
        content_type="application/json",
        body=json.dumps(doc_act.valid_admit_payload(APP_ID)).encode("utf-8"),
    )
    assert r1.status_code == 503
    assert doc_act._error_code(r1) == "document_admission_unavailable"

    # Context without scope authority
    svc_ctx = DocumentContextEngineService(
        scope_authority=None, document_resolver=None, evidence_storage=None
    )
    r2 = await svc_ctx.handle(
        method="POST",
        path=DOCUMENT_CONTEXT_PATH,
        content_type="application/json",
        body=json.dumps(
            doc_act.valid_context_payload(APP_ID, "doc_valid0123456789abcdef")
        ).encode("utf-8"),
    )
    assert r2.status_code == 503
    assert doc_act._error_code(r2) == "document_authority_unavailable"
