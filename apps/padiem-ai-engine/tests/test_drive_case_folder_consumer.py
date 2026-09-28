"""Engine Drive case-folder consumer bridge tests (#3178, parent #3138).

Network-free and credential-free. Composes the real canonical authorities
(Core case-folder gate -> #2741 scoped document byte store -> trusted resolver
-> context/evidence projections) and proves two invariants:

1. ordering — a denied authorization or a denied Drive envelope never reaches
   document admission or evidence retention;
2. the Drive envelope trust boundary — every envelope claim (mime,
   classification, operation, export mime) is derived from the authorized
   resource MIME and must match, so a Mapping cannot self-assert evidence
   admission.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib

import pytest

from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveTrustedAncestryProof,
)

from app.document_byte_store import InMemoryDocumentByteStore, ScopedDocumentByteStore
from app.document_context_service import TrustedCallerScope
from app.document_evidence_projection import InMemoryEvidenceStoragePort
from app.drive_case_folder_consumer import (
    ADMIT_PUBLIC_ROUTE,
    DriveCaseFolderConsumerError,
    bridge_case_folder_drive_text,
    drive_case_folder_consumer_snapshot,
)
from app.drive_case_folder_scope_projection import EngineDriveCaseFolderScopeError
from app.trusted_document_resolver import (
    DurableDocumentStoragePort,
    TrustedDocumentResolver,
)

BINDING = "bind:drive_legal_case"
CASE_FOLDER = "case_folder_001"
INSIDE_FILE = "file_inside_003"
OUTSIDE_FILE = "file_outside_999"
SHARED_DRIVE = "shared_drive_009"
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
PDF_MIME = "application/pdf"
HTML_MIME = "text/html"

APP_ID = "app_legal"
SUBJECT_ID = "subject_1"
TENANT_ID = "tenant_1"

CONTENT = "제1조 (목적) 이 계약은 ...\n제2조 (기간) ..."

DIRECT_OPERATION = "files.get.media"
EXPORT_OPERATION = "files.export"


def run(coro):
    return asyncio.run(coro)


# --- recording doubles (real canonical behaviour + call counting) ----------


class RecordingDocumentStore(ScopedDocumentByteStore):
    """The real canonical store with an admit counter."""

    def __init__(self, *, port) -> None:
        super().__init__(port=port)
        self.admit_calls = 0

    async def admit_document(self, **kwargs):  # type: ignore[override]
        self.admit_calls += 1
        return await super().admit_document(**kwargs)


class RecordingEvidenceStore(InMemoryEvidenceStoragePort):
    """The real in-memory evidence port with a store counter."""

    def __init__(self) -> None:
        super().__init__()
        self.store_calls = 0

    def store(self, projection):  # type: ignore[override]
        self.store_calls += 1
        return super().store(projection)


class Harness:
    def __init__(self) -> None:
        self.store = RecordingDocumentStore(port=InMemoryDocumentByteStore())
        self.resolver = TrustedDocumentResolver(
            storage=DurableDocumentStoragePort(store=self.store)
        )
        self.evidence = RecordingEvidenceStore()
        self.caller_scope = TrustedCallerScope(
            app_id=APP_ID, subject_id=SUBJECT_ID, tenant_id=TENANT_ID
        )

    def bridge(self, *, scope, resource, envelope, ancestry=None, **overrides):
        kwargs = {
            "scope": scope,
            "resource": resource,
            "drive_content_result": envelope,
            "caller_scope": self.caller_scope,
            "document_store": self.store,
            "document_resolver": self.resolver,
            "evidence_storage": self.evidence,
            "ancestry": ancestry,
        }
        kwargs.update(overrides)
        return run(bridge_case_folder_drive_text(**kwargs))

    def assert_no_store_interaction(self) -> None:
        assert self.store.admit_calls == 0
        assert self.evidence.store_calls == 0


# --- fixtures --------------------------------------------------------------


def my_drive_scope(**overrides) -> DriveCaseFolderScope:
    kwargs: dict[str, object] = {"binding_ref": BINDING, "selected_folder_id": CASE_FOLDER}
    kwargs.update(overrides)
    return DriveCaseFolderScope(**kwargs)  # type: ignore[arg-type]


def drive_resource(resource_id: str = INSIDE_FILE, **overrides) -> DriveCaseResource:
    kwargs: dict[str, object] = {
        "binding_ref": BINDING,
        "resource_id": resource_id,
        "mime_type": "text/plain",
    }
    kwargs.update(overrides)
    return DriveCaseResource(**kwargs)  # type: ignore[arg-type]


def inside_ancestry(resource_id: str = INSIDE_FILE) -> DriveTrustedAncestryProof:
    return DriveTrustedAncestryProof(
        binding_ref=BINDING, resource_id=resource_id, ancestor_folder_ids=(CASE_FOLDER,)
    )


def drive_envelope(
    *,
    file_id: str = INSIDE_FILE,
    mime_type: str = "text/plain",
    content: str = CONTENT,
    classification: str = "text_read",
    operation: str = DIRECT_OPERATION,
    provider: str = "google_drive",
    result_status: str = "OK",
    content_truncated: bool = False,
    shared_drive_id: str | None = None,
    shortcut_target_id: str | None = None,
    name: str = "contract.txt",
    export_mime_type: str | None = None,
    projection_present: bool = True,
) -> dict:
    """Canonical Core Drive READ content envelope."""

    projection = {
        "file_id": file_id,
        "name": name,
        "mime_type": mime_type,
        "space_kind": "shared_drive" if shared_drive_id else "my_drive",
        "shared_drive_id": shared_drive_id,
        "size_bytes": len(content),
        "web_view_link": None,
        "version_evidence": {
            "version": 7,
            "modified_time": "2026-09-01T00:00:00+00:00",
            "md5_checksum": "a" * 32,
            "sha256_checksum": None,
            "head_revision_id": "rev_1",
            "resource_key": None,
        },
        "shortcut_target_id": shortcut_target_id,
        "shortcut_target_mime_type": None,
        "shortcut_escape": False,
        "content_ingested": False,
        "binary_auto_ingested": False,
        "trashed": False,
        "drive_content_trusted": False,
        "raw_credentials_present": False,
    }
    envelope = {
        "provider": provider,
        "operation": operation,
        "result_status": result_status,
        "resource_classification": classification,
        "export_mime_type": export_mime_type,
        "content": content,
        "content_truncated": content_truncated,
        "content_chars": len(content),
        "drive_content_trusted": False,
        "raw_credentials_present": False,
    }
    if projection_present:
        envelope["projection"] = projection
    return envelope


# --- 1. happy paths: canonical direct text + canonical Google-native export --


def test_canonical_direct_text_envelope_is_admitted() -> None:
    harness = Harness()
    result = harness.bridge(
        scope=my_drive_scope(),
        resource=drive_resource(),
        envelope=drive_envelope(),
        ancestry=inside_ancestry(),
    )
    assert harness.store.admit_calls == 1
    assert harness.evidence.store_calls == 1
    assert result.document_ref.startswith("doc_")
    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["source"] == {"source_type": "drive", "content_trusted": False}
    assert payload["document"]["media_type"] == "text/plain"
    assert "제1조" in payload["document"]["truncated_text_preview"]
    assert payload["evidence"]["evidence_id"] == result.evidence_id


def test_canonical_google_native_export_envelope_is_admitted() -> None:
    harness = Harness()
    result = harness.bridge(
        scope=my_drive_scope(),
        resource=drive_resource(mime_type=GOOGLE_DOC_MIME),
        envelope=drive_envelope(
            mime_type=GOOGLE_DOC_MIME,
            classification="google_native_export",
            operation=EXPORT_OPERATION,
            export_mime_type="text/plain",
            name="contract-doc.txt",
        ),
        ancestry=inside_ancestry(),
    )
    assert harness.store.admit_calls == 1
    assert harness.evidence.store_calls == 1
    # the admitted document media came from the canonical export mime
    assert result.context_projection.media_type == "text/plain"
    assert result.provenance["drive_resource_classification"] == "google_native_export"


def test_success_retains_internal_provenance_linkage() -> None:
    harness = Harness()
    result = harness.bridge(
        scope=my_drive_scope(),
        resource=drive_resource(),
        envelope=drive_envelope(),
        ancestry=inside_ancestry(),
    )
    provenance = result.provenance
    assert provenance["source_type"] == "drive"
    assert provenance["case_folder_scope_ref"] == f"case-folder:{CASE_FOLDER}"
    assert provenance["drive_resource_ref"] == INSIDE_FILE
    assert provenance["drive_binding_ref"] == BINDING
    assert provenance["drive_resource_mime_type"] == "text/plain"
    assert provenance["canonical_document_ref"] == result.document_ref
    assert provenance["canonical_evidence_id"] == result.evidence_id
    assert provenance["authorization_decision"] == "allow"
    assert provenance["drive_resource_version_evidence"]["version"] == 7
    assert provenance["page_or_section"] == "UNAVAILABLE"
    assert provenance["exact_locator_available"] is False
    assert provenance["complete_document"] is True


# --- 2. authorization denial happens before any store interaction ----------


def test_out_of_scope_drive_resource_is_denied_before_admission() -> None:
    harness = Harness()
    with pytest.raises(EngineDriveCaseFolderScopeError, match="out_of_scope"):
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(OUTSIDE_FILE),
            envelope=drive_envelope(file_id=OUTSIDE_FILE),
        )
    harness.assert_no_store_interaction()


def test_binding_mismatch_is_denied_before_admission() -> None:
    harness = Harness()
    with pytest.raises(EngineDriveCaseFolderScopeError, match="binding_mismatch"):
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(binding_ref="bind:other"),
            envelope=drive_envelope(),
        )
    harness.assert_no_store_interaction()


def test_trashed_resource_is_denied_before_admission() -> None:
    harness = Harness()
    with pytest.raises(EngineDriveCaseFolderScopeError, match="trashed"):
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(trashed=True),
            envelope=drive_envelope(),
        )
    harness.assert_no_store_interaction()


def test_non_shortcut_target_laundering_is_denied_before_admission() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(shortcut_target_id=OUTSIDE_FILE),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "shortcut_content_not_eligible"
    harness.assert_no_store_interaction()


def test_shortcut_resource_in_scope_is_denied_before_admission() -> None:
    harness = Harness()
    shortcut = drive_resource(
        "shortcut_1", mime_type=GOOGLE_SHORTCUT_MIME, shortcut_target_id=OUTSIDE_FILE
    )
    with pytest.raises(EngineDriveCaseFolderScopeError, match="shortcut_target_required"):
        harness.bridge(
            scope=my_drive_scope(),
            resource=shortcut,
            envelope=drive_envelope(file_id="shortcut_1"),
            ancestry=inside_ancestry("shortcut_1"),
        )
    harness.assert_no_store_interaction()


# --- 3. Drive envelope trust boundary (MIME / classification / operation) --


def test_projection_mime_resource_mime_mismatch_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type="text/plain"),
            envelope=drive_envelope(mime_type="text/csv"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "projection_mime_resource_mismatch"
    harness.assert_no_store_interaction()


def test_binary_resource_forged_text_classification_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=PDF_MIME),
            envelope=drive_envelope(mime_type=PDF_MIME, classification="text_read"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "ineligible_drive_content"
    harness.assert_no_store_interaction()


def test_binary_resource_with_text_media_override_is_denied() -> None:
    harness = Harness()
    # no free media override exists anymore
    assert "media_type" not in inspect.signature(bridge_case_folder_drive_text).parameters
    # and a binary resource cannot be relabeled even with a text-looking envelope
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=PDF_MIME),
            envelope=drive_envelope(
                mime_type=PDF_MIME,
                classification="text_read",
                export_mime_type="text/plain",
                name="contract.pdf",
            ),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "ineligible_drive_content"
    harness.assert_no_store_interaction()


def test_unsupported_textual_mime_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=HTML_MIME),
            envelope=drive_envelope(mime_type=HTML_MIME, name="page.html"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "unsupported_text_media_type"
    harness.assert_no_store_interaction()


def test_text_read_with_files_export_operation_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(operation=EXPORT_OPERATION, export_mime_type="text/plain"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_operation_mismatch"
    harness.assert_no_store_interaction()


def test_google_native_with_files_get_media_operation_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=GOOGLE_DOC_MIME),
            envelope=drive_envelope(
                mime_type=GOOGLE_DOC_MIME,
                classification="google_native_export",
                operation=DIRECT_OPERATION,
                export_mime_type="text/plain",
            ),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_operation_mismatch"
    harness.assert_no_store_interaction()


def test_google_native_wrong_export_mime_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=GOOGLE_DOC_MIME),
            envelope=drive_envelope(
                mime_type=GOOGLE_DOC_MIME,
                classification="google_native_export",
                operation=EXPORT_OPERATION,
                export_mime_type="text/csv",
            ),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_export_mime_mismatch"
    harness.assert_no_store_interaction()


def test_binary_resource_claiming_native_export_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(mime_type=PDF_MIME),
            envelope=drive_envelope(
                mime_type=PDF_MIME,
                classification="google_native_export",
                operation=EXPORT_OPERATION,
                export_mime_type="text/plain",
            ),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "ineligible_drive_content"
    harness.assert_no_store_interaction()


# --- 4. remaining envelope denials (still before the store) ---------------


def test_drive_envelope_resource_id_mismatch_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(file_id=OUTSIDE_FILE),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_resource_id_mismatch"
    harness.assert_no_store_interaction()


def test_empty_drive_content_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(content="   "),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "empty_drive_content"
    assert harness.store.admit_calls == 0


def test_truncated_drive_content_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(content_truncated=True),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "truncated_drive_content"
    harness.assert_no_store_interaction()


def test_bounded_envelope_overflow_marker_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope={
                "provider": "google_drive",
                "operation": "files.get.media",
                "result_status": "REVIEW_REQUIRED",
                "truncated": True,
                "reason": "bounded Drive projection exceeded the Core tool output bound",
                "result_sha256": "b" * 64,
            },
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_content_not_complete"
    assert harness.store.admit_calls == 0


def test_wrong_provider_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(provider="onedrive"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "wrong_provider"
    assert harness.store.admit_calls == 0


def test_malformed_envelope_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(projection_present=False),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "malformed_drive_envelope"
    assert harness.store.admit_calls == 0


def test_shared_drive_identity_mismatch_is_denied() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(shared_drive_id=SHARED_DRIVE),
            resource=drive_resource(shared_drive_id=SHARED_DRIVE),
            envelope=drive_envelope(shared_drive_id="shared_drive_777"),
            ancestry=inside_ancestry(),
        )
    assert excinfo.value.code == "drive_shared_drive_mismatch"
    assert harness.store.admit_calls == 0


def test_shared_drive_happy_path_is_admitted() -> None:
    harness = Harness()
    result = harness.bridge(
        scope=my_drive_scope(shared_drive_id=SHARED_DRIVE),
        resource=drive_resource(shared_drive_id=SHARED_DRIVE),
        envelope=drive_envelope(shared_drive_id=SHARED_DRIVE),
        ancestry=inside_ancestry(),
    )
    assert harness.store.admit_calls == 1
    assert result.document_ref.startswith("doc_")


# --- 5. caller-supplied authority is never accepted ------------------------


def test_caller_supplied_allow_decision_has_no_authority() -> None:
    harness = Harness()
    envelope = drive_envelope(file_id=OUTSIDE_FILE)
    envelope["allowed"] = True
    envelope["decision"] = "allow"
    envelope["binding_ref"] = BINDING
    envelope["tenant_id"] = TENANT_ID
    with pytest.raises(EngineDriveCaseFolderScopeError):
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(OUTSIDE_FILE),
            envelope=envelope,
        )
    harness.assert_no_store_interaction()


def test_bridge_signature_exposes_no_caller_authority_fields() -> None:
    params = set(inspect.signature(bridge_case_folder_drive_text).parameters)
    for forbidden in (
        "decision",
        "allowed",
        "folder_id",
        "binding_ref",
        "tenant_id",
        "subject_id",
        "allowed_file_ids",
        "ancestor_folder_ids",
        "media_type",
        "export_mime_type",
    ):
        assert forbidden not in params


def test_caller_json_scope_object_is_rejected() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(),
            ancestry=inside_ancestry(),
            caller_scope={"app_id": APP_ID, "subject_id": SUBJECT_ID, "tenant_id": TENANT_ID},
        )
    assert excinfo.value.code == "invalid_trusted_scope"
    assert harness.store.admit_calls == 0


def test_untrusted_ancestry_type_is_rejected() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(),
            ancestry={"ancestor_folder_ids": [CASE_FOLDER]},
        )
    assert excinfo.value.code == "invalid_ancestry"
    assert harness.store.admit_calls == 0


def test_missing_evidence_storage_fails_closed() -> None:
    harness = Harness()
    with pytest.raises(DriveCaseFolderConsumerError) as excinfo:
        harness.bridge(
            scope=my_drive_scope(),
            resource=drive_resource(),
            envelope=drive_envelope(),
            ancestry=inside_ancestry(),
            evidence_storage=None,
        )
    assert excinfo.value.code == "evidence_storage_unavailable"
    assert harness.store.admit_calls == 0


# --- 6. public surface leaks nothing --------------------------------------


def test_public_projection_and_repr_leak_no_internal_refs() -> None:
    harness = Harness()
    result = harness.bridge(
        scope=my_drive_scope(),
        resource=drive_resource(),
        envelope=drive_envelope(),
        ancestry=inside_ancestry(),
    )
    rendered = repr(result)
    public = result.to_dict()

    for secret in (result.document_ref, BINDING, INSIDE_FILE, CASE_FOLDER, TENANT_ID, SUBJECT_ID):
        assert secret not in rendered
        assert secret not in repr(public)
    assert "evidence://" not in rendered
    assert "storage_locator" not in str(public)
    assert public["source"]["content_trusted"] is False


# --- 7. source-level posture ----------------------------------------------


def test_bridge_source_reuses_canonical_authorities_only() -> None:
    base = pathlib.Path(__file__).resolve().parents[1]
    source = (base / "app" / "drive_case_folder_consumer.py").read_text(encoding="utf-8")

    for required in (
        "from app.document_byte_store import ScopedDocumentByteStore",
        "from app.context_evidence_bridge import att_to_context_evidence",
        "from app.drive_case_folder_scope_projection import admit_case_folder_resource",
        "from app.trusted_document_resolver import",
        "from app.document_context_projection import",
        "from app.document_evidence_projection import EvidenceStorageProjection",
        "from padiem_ai_core.drive_capability import (",
        "export_mime_for",
        "is_textual_mime",
        "DriveResourceClassification",
    ):
        assert required in source, f"bridge must reuse canonical authority: {required}"

    for forbidden in (
        "project_case_folder_decision",
        "LegalEvidenceStore",
        "B67ContextProjection",
        "DriveLegalEvidenceModel",
        "import httpx",
        "import requests",
        "urllib.request",
        "socket",
        "refresh_token",
        "client_secret",
        "access_token",
        "FastAPI",
        "Starlette",
    ):
        assert forbidden not in source, f"bridge must not add a second authority: {forbidden}"


def test_snapshot_posture_is_source_only() -> None:
    snapshot = drive_case_folder_consumer_snapshot()
    assert snapshot["gate_before_document_admission"] is True
    assert snapshot["projection_mime_bound_to_resource"] is True
    assert snapshot["classification_derived_from_canonical_mime"] is True
    assert snapshot["operation_bound_to_classification"] is True
    assert snapshot["export_mime_bound_to_resource"] is True
    assert snapshot["media_type_override_authority"] is False
    assert snapshot["reuses_canonical_document_store"] is True
    assert snapshot["reuses_canonical_evidence_storage"] is True
    assert snapshot["second_drive_runtime"] is False
    assert snapshot["second_document_pipeline"] is False
    assert snapshot["second_evidence_model"] is False
    assert snapshot["public_route"] is False
    assert ADMIT_PUBLIC_ROUTE is False
    assert snapshot["live_provider_calls"] == 0
    assert snapshot["live_ancestry_resolver"] is False
