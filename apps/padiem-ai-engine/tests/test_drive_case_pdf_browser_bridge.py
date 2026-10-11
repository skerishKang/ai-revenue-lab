from __future__ import annotations

import hashlib

import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.evidence_citation import project_grounded_citations
from padiem_ai_core.evidence_graph import (
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    EvidenceClaim,
    evidence_graph,
)
from padiem_ai_core.retrieval import evidence_from_retrieved_item

from app.drive_case_pdf_browser_bridge import (
    B67_CANONICAL_MAX_PAGES,
    BrowserPdfBridgeError,
    browser_pdf_drive_bridge_snapshot,
    review_browser_pdf_extraction,
)


PDF_BYTES = b"%PDF-1.7\nexact browser source bytes\n%%EOF"
SOURCE_SHA = hashlib.sha256(PDF_BYTES).hexdigest()


def source(*, version=7, modified_time="2026-10-01T00:00:00Z") -> DriveFileProjection:
    return DriveFileProjection(
        file_id="file_pdf_001",
        name="brief.pdf",
        mime_type="application/pdf",
        version=version,
        modified_time=modified_time,
        size_bytes=len(PDF_BYTES),
    )


def extraction(texts=("page one", "", "page three")) -> dict:
    pages = [
        {
            "page_number": index,
            "text": text,
            "text_chars": len(text),
            "native_text": bool(text),
        }
        for index, text in enumerate(texts, start=1)
    ]
    missing = [page["page_number"] for page in pages if not page["native_text"]]
    state = "none" if len(missing) == len(pages) else ("all" if not missing else "mixed")
    return {
        "ok": True,
        "contract_version": "b67-browser-pdf-extraction.v1",
        "parser": "pdfjs-dist",
        "parser_version": "6.3.289",
        "source_sha256": SOURCE_SHA,
        "page_count": len(pages),
        "pages": pages,
        "total_text_chars": sum(len(text) for text in texts),
        "native_text_state": state,
        "ocr_candidate_pages": missing,
    }


def test_review_mints_exact_page_segments_and_current_drive_retrieval() -> None:
    review = review_browser_pdf_extraction(
        extraction=extraction(),
        current_source=source(),
        current_pdf_bytes=PDF_BYTES,
    )

    assert review.page_count == 3
    assert review.blank_page_count == 1
    assert [segment.locator.value for segment in review.segments] == ["1", "3"]
    assert [segment.order for segment in review.segments] == [0, 2]
    assert [item.document_locator.value for item in review.retrieved_items] == ["1", "3"]
    assert all(item.source_ref == "drive:file_pdf_001" for item in review.retrieved_items)

    public = review.safe_dict()
    assert public["source_freshness"] == "current"
    assert "file_id" not in public
    assert "source_ref" not in str(public)
    assert public["segments"][1]["locator"] == {
        "kind": "page",
        "value": "3",
        "precision": "exact",
    }


def test_long_page_is_split_for_retrieval_without_relabeling_page() -> None:
    text = "A" * 7000
    review = review_browser_pdf_extraction(
        extraction=extraction((text,)),
        current_source=source(),
        current_pdf_bytes=PDF_BYTES,
    )
    assert len(review.segments) == 1
    assert len(review.retrieved_items) == 2
    assert {item.document_locator.value for item in review.retrieved_items} == {"1"}
    assert "".join(item.content for item in review.retrieved_items) == text


def test_canonical_locator_survives_retrieval_evidence_graph_and_citation() -> None:
    review = review_browser_pdf_extraction(
        extraction=extraction(("termination argument",)),
        current_source=source(),
        current_pdf_bytes=PDF_BYTES,
    )
    item = review.retrieved_items[0]
    evidence = evidence_from_retrieved_item(
        item,
        evidence_id="src_page_1",
        retrieved_at="2026-10-07T00:00:00Z",
    )
    assert isinstance(evidence, Evidence)
    graph = evidence_graph(
        sources=[evidence],
        claims=[
            EvidenceClaim(
                id="claim_page_1",
                text="The brief contains the argument.",
                derivation=ClaimDerivation.OBSERVED,
            )
        ],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_page_1",
                evidence_id="src_page_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )
    citation = project_grounded_citations(graph, "claim_page_1").citations[0]
    assert citation.source_ref == "drive:file_pdf_001"
    assert citation.document_locator.value == "1"
    assert citation.document_locator.precision.value == "exact"


def test_changed_drive_bytes_fail_closed_before_any_locator_can_be_reused() -> None:
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=extraction(),
            current_source=DriveFileProjection(
                file_id="file_pdf_001",
                name="brief.pdf",
                mime_type="application/pdf",
                version=8,
                modified_time="2026-10-02T00:00:00Z",
                size_bytes=len(b"%PDF-1.7\nchanged source bytes!!!\n%%EOF"),
            ),
            current_pdf_bytes=b"%PDF-1.7\nchanged source bytes!!!\n%%EOF",
        )
    assert exc.value.code == "browser_pdf_source_changed"
    assert exc.value.status_code == 409


def test_missing_drive_version_evidence_is_unverifiable_not_current() -> None:
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=extraction(),
            current_source=source(version=None, modified_time=None),
            current_pdf_bytes=PDF_BYTES,
        )
    assert exc.value.code == "unverifiable_drive_index"


def test_wrong_browser_extraction_contract_version_fails_closed() -> None:
    payload = extraction()
    payload["contract_version"] = "b67-browser-pdf-extraction.v0"
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=payload,
            current_source=source(),
            current_pdf_bytes=PDF_BYTES,
        )
    assert exc.value.code == "browser_pdf_contract_version_mismatch"


def test_browser_cannot_submit_source_ref_locator_or_freshness_authority() -> None:
    forged = extraction()
    forged["source_ref"] = "drive:attacker"
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=forged,
            current_source=source(),
            current_pdf_bytes=PDF_BYTES,
        )
    assert exc.value.code == "browser_pdf_extraction_invalid"


def test_browser_512_page_success_is_rejected_at_core_80_page_boundary_without_truncation() -> None:
    payload = extraction(tuple("x" for _ in range(B67_CANONICAL_MAX_PAGES + 1)))
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=payload,
            current_source=source(),
            current_pdf_bytes=PDF_BYTES,
        )
    assert exc.value.code == "browser_pdf_page_bound_exceeds_core"
    assert exc.value.status_code == 413


def test_browser_40k_page_text_is_rejected_at_core_16k_text_boundary() -> None:
    payload = extraction(("x" * 16001,))
    with pytest.raises(BrowserPdfBridgeError) as exc:
        review_browser_pdf_extraction(
            extraction=payload,
            current_source=source(),
            current_pdf_bytes=PDF_BYTES,
        )
    assert exc.value.code == "browser_pdf_page_text_exceeds_core"
    assert exc.value.status_code == 413


def test_bridge_snapshot_makes_bound_mismatch_and_authority_posture_explicit() -> None:
    snap = browser_pdf_drive_bridge_snapshot()
    assert snap["browser_parser_max_pages"] == 512
    assert snap["canonical_max_pages"] == 80
    assert snap["browser_parser_max_page_chars"] == 40000
    assert snap["canonical_max_page_chars"] == 16000
    assert snap["page_bound_widened"] is False
    assert snap["silent_truncation"] is False
    assert snap["browser_drive_authority"] is False
    assert snap["caller_source_ref_authority"] is False
    assert snap["caller_locator_authority"] is False
    assert snap["server_reacquires_current_pdf"] is True
    assert snap["source_bytes_sha256_bound"] is True
    assert snap["current_freshness_required"] is True
    assert snap["second_evidence_authority"] is False
    assert snap["production_mutation"] is False
