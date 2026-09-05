"""E5B-S3 context/evidence projection tests (#1750).

Acceptance matrix A–R: two-destination projection invariants (body-free
context vs full-retention evidence), truncation policy, in-memory evidence
port, the att_* through-line and the zero-mutation canaries for Core, B62
and the S2 resolver.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

import pytest

from app.context_evidence_bridge import (
    att_to_context_evidence,
    project_to_context,
    project_to_evidence,
)
from app.document_context_projection import (
    ContextTruncationPolicy,
    ContextWindowProjection,
)
from app.document_evidence_projection import (
    EvidenceStoragePort,
    EvidenceStorageProjection,
    InMemoryEvidenceStoragePort,
)
from app.trusted_document_resolver import (
    DocumentResolutionError,
    InMemoryStoragePort,
    ResolvedDocumentMeta,
    TrustedDocumentResolver,
)
from padiem_ai_core.document_semantics import (
    DocumentLocator,
    DocumentSegment,
    LocatorKind,
    LocatorPrecision,
)
from padiem_ai_core.document_normalization import NormalizedDocument

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_APP = REPO_ROOT / "apps" / "padiem-ai-engine" / "app"
CORE_PACKAGE = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core"
CORE_TESTS = REPO_ROOT / "packages" / "padiem-ai-core" / "tests"

# Canary hashes pinned at the S1/S2 merge revisions (main @ 2afd3264, S2 @ 9162e18).
PINNED_SHA256 = {
    CORE_PACKAGE / "document_normalization.py": "2f0620895ecec53a895f9496a46965ca1cbe3536b896ce2e8dc0d076d1fe4934",
    CORE_PACKAGE / "document_semantics.py": "b74628623ebaeddd3caab4be317562d204b798e945088e990830c1ee270fa8f5",
    CORE_TESTS / "test_document_semantics.py": "cf21bd3999348d1d34b18fbb9863a6fe8ec93840f6990bdbf52eeb79fce7c8f5",
    CORE_TESTS / "test_document_normalization.py": "5c7e9166fb2ffd015a307da4a7e653acf24c10e44684f3e8df2d70122660b9ff",
    ENGINE_APP / "trusted_document_resolver.py": "aba9daa8ed134d8475cc65061a4c5903e29d72cdda31638a47535d350cb80b8b",
}

REF = "att_s3doc000000000b"
LOCATOR = "opaque-blob-locator-88"
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}
BODY_SHORT = "quarterly revenue projections for beta-corp"
BODY_LONG = "".join("line %04d revenue figure beta-corp\n" % index for index in range(400))
assert len(BODY_LONG) > 12_000


def _meta(body: str, media_type: str = "text/plain", name: str = "report.txt") -> ResolvedDocumentMeta:
    return ResolvedDocumentMeta(
        media_type=media_type,
        name=name,
        byte_size=len(body.encode("utf-8")),
        app_id=SCOPE["app_id"],
        subject_id=SCOPE["subject_id"],
        tenant_id=SCOPE["tenant_id"],
    )


def _resolver(body: str = BODY_SHORT) -> TrustedDocumentResolver:
    storage = InMemoryStoragePort()
    raw = body.encode("utf-8")
    storage.store(LOCATOR, raw, _meta(body))
    resolver = TrustedDocumentResolver(storage=storage)
    resolver.register(REF, LOCATOR)
    return resolver


def _multi_segment_document(count: int) -> NormalizedDocument:
    segments = tuple(
        DocumentSegment(text=f"seg{index:02d} content", order=index)
        for index in range(count)
    )
    return NormalizedDocument(
        name="multi.txt",
        media_type="text/plain",
        text="\n".join(segment.text for segment in segments),
        byte_size=len("\n".join(segment.text for segment in segments).encode("utf-8")),
        source_kind="text",
        segments=segments,
    )


# --- A: happy path through-line -------------------------------------------


def test_a_valid_reference_yields_both_projections() -> None:
    context, evidence = att_to_context_evidence(_resolver(), REF, **SCOPE)
    assert isinstance(context, ContextWindowProjection)
    assert isinstance(evidence, EvidenceStorageProjection)
    assert context.content_trust_class == "untrusted_reference_data"
    assert evidence.normalized_document.text == BODY_SHORT


# --- B: context never carries the full body ----------------------------------


def test_b_context_projection_omits_full_body() -> None:
    context, _ = att_to_context_evidence(
        _resolver(BODY_LONG), REF, **SCOPE, context_max_text_chars=4000
    )
    surfaces = repr(context) + str(context.to_dict())
    assert context.text_chars == len(BODY_LONG)
    assert BODY_LONG not in surfaces
    preview = context.truncated_text_preview or ""
    assert len(preview) < len(BODY_LONG)
    assert "[truncated" in preview


# --- C: context carries no DocumentLocator ----------------------------------


def test_c_context_projection_has_no_locator_surface() -> None:
    context = project_to_context(_multi_segment_document(3))
    combined = (repr(context) + str(context.to_dict())).lower()
    assert "locator" not in combined
    assert "paragraph" not in combined
    assert "section:" not in combined
    assert "DocumentLocator" not in combined


# --- D: context carries no att_* / storage / scope ---------------------------


def test_d_context_projection_leaks_no_reference_storage_or_scope() -> None:
    context, _ = att_to_context_evidence(_resolver(), REF, **SCOPE)
    combined = repr(context) + str(context.to_dict())
    for forbidden in (REF, "att_", LOCATOR, "evidence://", *SCOPE.values()):
        assert forbidden not in combined


# --- E/H: evidence preserves full body; context only preview -----------------


def test_h_long_document_produces_truncated_preview() -> None:
    context, evidence = att_to_context_evidence(
        _resolver(BODY_LONG), REF, **SCOPE, context_max_text_chars=4000
    )
    assert context.truncated_text_preview is not None
    assert context.truncated_text_preview.startswith(BODY_LONG[:4000])
    assert context.truncated_text_preview.endswith("[truncated %d chars]" % (len(BODY_LONG) - 4000))
    assert BODY_LONG in evidence.normalized_document.segments[0].text
    assert evidence.normalized_document.text_chars == len(BODY_LONG)


# --- E (locator provenance) / F / G: evidence contents ----------------------


def _evidence(document: NormalizedDocument, body: str) -> EvidenceStorageProjection:
    return project_to_evidence(REF, document, _meta(body), f"evidence://{REF}")


def test_e_evidence_kepts_full_segments_and_provenance() -> None:
    document = _multi_segment_document(4)
    evidence = _evidence(document, document.text)
    assert evidence.normalized_document.segment_count == 4
    assert [segment.text for segment in evidence.normalized_document.segments] == [
        f"seg{index:02d} content" for index in range(4)
    ]


def test_f_evidence_carries_a_document_locator() -> None:
    document = _multi_segment_document(2)
    located = NormalizedDocument(
        name="located.txt",
        media_type="text/plain",
        text="alpha body text",
        byte_size=15,
        source_kind="text",
        segments=(
            DocumentSegment(
                text="alpha body text",
                order=0,
                locator=DocumentLocator(kind=LocatorKind.PARAGRAPH, value="paragraph:3", precision=LocatorPrecision.EXACT),
            ),
        ),
    )
    assert isinstance(_evidence(document, document.text).document_locator, DocumentLocator)
    locator = _evidence(located, located.text).document_locator
    assert locator.kind is LocatorKind.PARAGRAPH
    assert locator.value == "paragraph:3"


def test_g_evidence_retains_internal_att_reference() -> None:
    context, evidence = att_to_context_evidence(_resolver(), REF, **SCOPE)
    assert evidence.att_ref == REF  # internal only; never projected outward
    assert REF not in context.to_dict().values()


# --- I: segment budget produces warning + truncation ------------------------


def test_i_segment_overflow_logs_warning_and_truncates_preview(caplog) -> None:
    document = _multi_segment_document(25)
    with caplog.at_level("WARNING", logger="padiem.engine.document_context_projection"):
        context = project_to_context(document, max_text_chars=4000, max_segments=10)
    assert any("segment" in record.message.lower() for record in caplog.records)
    preview = context.truncated_text_preview or ""
    assert "seg09 content" in preview
    assert "seg10 content" not in preview
    assert context.segment_count == 25  # honest original count preserved


# --- J: truncation policy ----------------------------------------------------


def test_j_truncate_text_prefix_and_marker() -> None:
    text = "abcdefghij" * 10
    assert ContextTruncationPolicy.truncate_text(text, 1_000) == text
    cut = ContextTruncationPolicy.truncate_text(text, 50)
    assert cut.startswith(text[:50])
    assert cut.endswith(f"... [truncated {len(text) - 50} chars]")
    with pytest.raises(ValueError):
        ContextTruncationPolicy.truncate_text(text, 0)
    with pytest.raises(ValueError):
        ContextTruncationPolicy(max_text_chars=0)
    with pytest.raises(ValueError):
        ContextTruncationPolicy(strategy="summary")


# --- K: in-memory evidence port ---------------------------------------------


def test_k_evidence_port_store_and_retrieve() -> None:
    document = _multi_segment_document(2)
    evidence = project_to_evidence(REF, document, _meta(document.text), f"evidence://{REF}")
    port: EvidenceStoragePort = InMemoryEvidenceStoragePort()
    stored_id = port.store(evidence)
    assert stored_id == evidence.evidence_id
    assert port.retrieve(stored_id) is evidence
    with pytest.raises(KeyError):
        port.retrieve("deadbeefdeadbeefdeadbeef")
    with pytest.raises(ValueError):
        port.store(evidence)


# --- L: full pipeline with evidence retention --------------------------------


def test_l_full_pipeline_stores_retrievable_evidence() -> None:
    resolver = _resolver(BODY_LONG)
    port = InMemoryEvidenceStoragePort()
    context, evidence = att_to_context_evidence(
        resolver, REF, **SCOPE, context_max_text_chars=4000, context_max_segments=10,
        evidence_storage=port,
    )
    assert port.retrieve(evidence.evidence_id).normalized_document.text == BODY_LONG
    assert context.byte_size == len(BODY_LONG.encode("utf-8"))
    assert evidence.created_at.tzinfo is not None


def test_l2_pipeline_rejects_bad_reference() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        att_to_context_evidence(_resolver(), "att_x", **SCOPE)
    assert info.value.code == "invalid_reference"


def test_l3_pipeline_rejects_unauthorized_scope() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        att_to_context_evidence(_resolver(), REF, **{**SCOPE, "tenant_id": "tenant.zzz"})
    assert info.value.code == "unauthorized"


# --- M: no optional extraction dependencies at import ------------------------


def test_m_s3_modules_import_without_pypdf_or_openpyxl() -> None:
    import app.context_evidence_bridge as bridge
    import app.document_context_projection as context_module
    import app.document_evidence_projection as evidence_module

    for module in (bridge, context_module, evidence_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not re.search(r"^(import|from)\s+(pypdf|openpyxl)", source, re.MULTILINE)


# --- N/O: reprs are redaction-safe -------------------------------------------


def test_n_context_repr_exposes_only_bounded_metadata() -> None:
    context, _ = att_to_context_evidence(_resolver(BODY_LONG), REF, **SCOPE, context_max_text_chars=200)
    combined = repr(context)
    for forbidden in (REF, LOCATOR, "evidence://", *SCOPE.values()):
        assert forbidden not in combined
    assert BODY_LONG not in combined


def test_o_evidence_repr_redacts_internal_references_and_storage() -> None:
    context, evidence = att_to_context_evidence(_resolver(), REF, **SCOPE)
    combined = repr(evidence)
    assert "att_s3doc" not in combined
    assert REF not in combined
    assert LOCATOR not in combined
    assert "evidence://" not in combined
    assert BODY_SHORT not in combined
    assert evidence.evidence_id in combined
    assert "redacted" in combined


# --- P/Q/R: zero-mutation canaries --------------------------------------------


@pytest.mark.parametrize("path, expected", list(PINNED_SHA256.items()))
def test_pqr_frozen_sources_are_unmodified(path: Path, expected: str) -> None:
    assert path.exists(), f"expected frozen file to exist: {path}"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, f"{path.name} drifted from its pinned base revision"
