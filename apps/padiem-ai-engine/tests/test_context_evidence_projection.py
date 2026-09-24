"""E5B-S3 context/evidence projection tests (#1750), async durable seam (#2741).

Covers the S3 projection matrix over its evolved E8C-B form: the bridge runs
one async resolve through the durable document store, context stays bounded,
evidence stays full-retention behind engine ids, reprs stay redaction-safe
and the S1/S2 canaries stay byte-identical.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.context_evidence_bridge import (
    att_to_context_evidence,
    project_to_context,
    project_to_evidence,
)
from app.document_context_projection import ContextTruncationPolicy, ContextWindowProjection
from app.document_byte_store import (
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
    StoredDocumentRecord,
)
from app.document_evidence_projection import (
    EvidenceStoragePort,
    EvidenceStorageProjection,
    InMemoryEvidenceStoragePort,
)
from app.trusted_document_resolver import (
    DurableDocumentStoragePort,
    DocumentResolutionError,
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
# Canary hashes re-pinned at #2012 HWPX Core change (PR #2033).
# Re-pinned again at #2824-S3A, which changed the OOXML unsafe-path fixture only
# (PR #2861). Core *source* pins below are deliberately unchanged: that slice
# added no Core process authority.
# Re-pinned a third time at #2966 (PR #2969), which factors the Core HWPX
# archive-and-XML walk so a structured decoder and the flat reader share one
# parse. That is a Core *source* change to document_normalization.py, so its pin
# and its fixture pin move; document_semantics.py is untouched and stays pinned
# at the E5B-S1 digest. No Core process, network or filesystem authority was
# added by that slice.
# Re-pinned a fourth time at #2979, which adds the Core package-preserving
# mutation authority. That slice exposes a raw-member accessor and the gate's
# own member-name predicate from document_normalization.py, so its pin moves;
# the other three pins are unchanged. It adds no Core process, network or
# filesystem authority: every archive walk still runs through the one gate, and
# the mutator owns no archive or XML primitive of its own.
# Re-pinned for #3019's bounded table facts. The archive/XML authority and its
# gate stay singular; only private fact retention in the same parse changed.
PINNED_SHA256 = {
    CORE_PACKAGE / "document_normalization.py": "60f80fd6dd7601eb6ab284458d27cf79b253a683bac2919696740c66e05dbcfe",
    CORE_PACKAGE / "document_semantics.py": "a9cb2284d538c38aa5e08eb0e0ea4ff792922ae8ce58514e09228288ac57be85",
    CORE_TESTS / "test_document_semantics.py": "650ca215c9842b6bb4d45faed6707749c3cf2a7c008bb18fc4a567b0487fa7e5",
    CORE_TESTS / "test_document_normalization.py": "ba88eb112d5855751ba4316013daef60095e574ed8bb13441c479ad0cc70da5e",
}

REF = "doc_s3doc0000000000b"
LEGACY_IMAGE_REF = "att_s3doc0000000000b"  # the exact pre-#2741 fixture namespace
LOCATOR = "opaque-blob-locator-88"
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}
BODY_SHORT = "quarterly revenue projections for beta-corp"
BODY_LONG = "".join("line %04d revenue figure beta-corp\n" % index for index in range(400))
T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
assert len(BODY_LONG) > 12_000


def _meta(body: str, **overrides: object) -> ResolvedDocumentMeta:
    values: dict[str, object] = {
        "media_type": "text/plain",
        "name": "report.txt",
        "byte_size": len(body.encode("utf-8")),
        "app_id": SCOPE["app_id"],
        "subject_id": SCOPE["subject_id"],
        "tenant_id": SCOPE["tenant_id"],
    }
    values.update(overrides)
    return ResolvedDocumentMeta(**values)  # type: ignore[arg-type]


def _resolver(body: str = BODY_SHORT) -> TrustedDocumentResolver:
    async def bind() -> TrustedDocumentResolver:
        port = InMemoryDocumentByteStore()
        raw = body.encode("utf-8")
        await port.put(
            StoredDocumentRecord(
                document_ref=REF,
                app_id=SCOPE["app_id"],
                tenant_id=SCOPE["tenant_id"],
                subject_id=SCOPE["subject_id"],
                media_type="text/plain",
                name="report.txt",
                byte_size=len(raw),
                created_at=T0,
                expires_at=T0 + timedelta(hours=24),
            ),
            raw,
        )
        return TrustedDocumentResolver(
            storage=DurableDocumentStoragePort(
                ScopedDocumentByteStore(port=port, clock=lambda: T0)
            )
        )

    return asyncio.run(bind())


def _bridge(resolver: TrustedDocumentResolver, ref: object = REF, **kwargs: object):
    return asyncio.run(att_to_context_evidence(resolver, ref, **SCOPE, **kwargs))  # type: ignore[arg-type]


def _multi_segment_document(count: int) -> NormalizedDocument:
    segments = tuple(
        DocumentSegment(
            text=f"seg{index:02d} content",
            order=index,
            locator=DocumentLocator(
                kind=LocatorKind.PARAGRAPH,
                value=f"paragraph:{index + 1}",
                precision=LocatorPrecision.EXACT,
            ),
        )
        for index in range(count)
    )
    text = "\n".join(segment.text for segment in segments)
    return NormalizedDocument(
        name="multi.txt",
        media_type="text/plain",
        text=text,
        byte_size=len(text.encode("utf-8")),
        segments=segments,
    )


# --- A: happy path through-line -------------------------------------------


def test_a_valid_reference_yields_both_projections() -> None:
    context, evidence = _bridge(_resolver())
    assert isinstance(context, ContextWindowProjection)
    assert isinstance(evidence, EvidenceStorageProjection)
    assert context.content_trust_class == "untrusted_reference_data"
    assert evidence.normalized_document.text == BODY_SHORT


# --- B: context never carries the full body ----------------------------------


def test_b_context_projection_omits_full_body() -> None:
    context, _ = _bridge(_resolver(BODY_LONG), context_max_text_chars=4000)
    surfaces = repr(context) + str(context.to_dict())
    assert context.text_chars == len(BODY_LONG)
    assert context.byte_size == len(BODY_LONG.encode("utf-8"))
    assert BODY_LONG not in surfaces
    assert context.truncated_text_preview == BODY_LONG[:4000] + f"... [truncated {len(BODY_LONG) - 4000} chars]"


def test_c_context_segment_cap_drops_tail_but_reports_honest_origins() -> None:
    document = _multi_segment_document(40)
    context = project_to_context(document, max_text_chars=len(document.text), max_segments=25)
    assert context.segment_count == 40  # honest original count preserved


# --- D: context truncation policy -------------------------------------------


def test_d_truncation_marker_shape_and_guards() -> None:
    text = "abcdefghij" * 50
    assert ContextTruncationPolicy.truncate_text(text, 1_000) == text
    cut = ContextTruncationPolicy.truncate_text(text, 50)
    assert cut == text[:50] + "... [truncated 450 chars]"
    with pytest.raises(ValueError):
        ContextTruncationPolicy.truncate_text(text, 0)
    with pytest.raises(ValueError):
        ContextTruncationPolicy.truncate_text(b"bytes", 5)  # type: ignore[arg-type]


def test_e_context_projection_from_bridge_keeps_original_projection_contract() -> None:
    context, _ = _bridge(_resolver())
    as_dict = context.to_dict()
    assert set(as_dict) >= {"kind", "truncated_text_preview", "content_trust_class", "text_chars"}
    assert as_dict["text_chars"] == len(BODY_SHORT)
    assert as_dict["truncated_text_preview"] == BODY_SHORT


# --- F/G: evidence projection ------------------------------------------------


def test_f_evidence_projection_keeps_full_document_and_locator() -> None:
    document = _multi_segment_document(3)
    evidence = project_to_evidence(REF, document, _meta(document.text), f"evidence://{REF}")
    assert evidence.att_ref == REF
    assert evidence.storage_locator == f"evidence://{REF}"
    assert evidence.normalized_document.text == document.text
    assert evidence.document_locator.kind is LocatorKind.PARAGRAPH


def test_g_evidence_projection_rejects_image_namespace_reference() -> None:
    document = _multi_segment_document(2)
    # cross-namespace refusal: an att_* reference can never even be retained.
    with pytest.raises(DocumentResolutionError) as info:
        project_to_evidence(LEGACY_IMAGE_REF, document, _meta(document.text), "evidence://" + LEGACY_IMAGE_REF)
    assert info.value.code == "invalid_reference"


def test_h_evidence_projection_rejects_foreign_locator_object_or_short_token() -> None:
    document = _multi_segment_document(2)
    with pytest.raises((ValueError, DocumentResolutionError)):
        project_to_evidence(REF, document, _meta(document.text), object())  # type: ignore[arg-type]
    with pytest.raises((ValueError, DocumentResolutionError)):
        project_to_evidence("doc_" + "z" * 11, document, _meta(document.text), f"evidence://{REF}")
    with pytest.raises((ValueError, DocumentResolutionError)):
        project_to_evidence(REF, "not-a-document", _meta(document.text), f"evidence://{REF}")  # type: ignore[arg-type]


# --- I: evidence projection reprs / public dict redaction --------------------


def test_i_evidence_repr_and_public_dict_hide_private_state() -> None:
    document = _multi_segment_document(2)
    evidence = project_to_evidence(REF, document, _meta(document.text), f"evidence://{document.text}")
    surfaces = [repr(evidence)]
    combined = " ".join(surfaces).lower()
    for forbidden in (REF, LOCATOR, f"evidence://", SCOPE["app_id"], SCOPE["subject_id"], SCOPE["tenant_id"]):
        assert forbidden.lower() not in combined


# --- J: in-memory evidence port ----------------------------------------------


def test_j_evidence_port_store_retrieve_and_duplicate_rejection() -> None:
    document = _multi_segment_document(2)
    port: EvidenceStoragePort = InMemoryEvidenceStoragePort()
    evidence = project_to_evidence(REF, document, _meta(document.text), f"evidence://{REF}")
    stored = port.store(evidence)
    assert 16 <= len(stored) <= 64
    assert port.retrieve(stored).normalized_document.text == document.text
    with pytest.raises(ValueError):
        port.store(evidence)


# --- K: bridge single-resolve + failure propagation ---------------------------


def test_k_bridge_propagates_store_failures_without_projections() -> None:
    resolver = _resolver()
    with pytest.raises(DocumentResolutionError) as unknown:
        _bridge(resolver, "doc_neverminted000000000")
    assert unknown.value.code == "not_found"
    with pytest.raises(DocumentResolutionError) as bad:
        _bridge(resolver, LEGACY_IMAGE_REF)
    assert bad.value.code == "invalid_reference"


def test_l_bridge_unauthorized_scope_never_projects() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(
            att_to_context_evidence(_resolver(), REF, app_id=SCOPE["app_id"], subject_id=SCOPE["subject_id"], tenant_id="tenant.evil")
        )
    assert info.value.code == "unauthorized"


def test_m_s3_stays_off_the_storage_write_path() -> None:
    # Projections never touch any real storage: only ports passed in do.
    document = _multi_segment_document(2)
    evidence = project_to_evidence(REF, document, _meta(document.text), f"evidence://{REF}")
    assert evidence.created_at.tzinfo is not None and evidence.created_at >= T0
    port = InMemoryEvidenceStoragePort()
    stored = port.store(evidence)
    assert port.retrieve(stored) is not None


# --- N: end-to-end durability through the bridge ------------------------------


def test_n_bridge_full_pipeline_retains_and_reads_back() -> None:
    port = InMemoryEvidenceStoragePort()
    _context, evidence = _bridge(_resolver(BODY_LONG), context_max_text_chars=4000, evidence_storage=port)
    kept = port.retrieve(evidence.evidence_id)
    assert kept.normalized_document.text == BODY_LONG


# --- O: no optional extraction dependency at S3 import ------------------------


def test_o_context_bridge_imports_stay_dependency_light() -> None:
    import app.context_evidence_bridge as bridge

    source = Path(bridge.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^(import|from)\s+(pypdf|openpyxl|workers)", source, re.MULTILINE)


# --- P/Q/R: canaries ----------------------------------------------------------


def test_p_projection_serialization_is_json_safe() -> None:
    context, _ = _bridge(_resolver(BODY_LONG), context_max_text_chars=200)
    dumped = json.dumps(context.to_dict())
    assert REF not in dumped
    assert "evidence://" not in dumped


@pytest.mark.parametrize("path, expected", list(PINNED_SHA256.items()))
def test_qr_canaries_keep_frozen_sources_byte_identical(path: Path, expected: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected
    assert path.exists()
