from __future__ import annotations

from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_communications import AttachmentMetadata
from kagent.ops_intake import (
    CommercialRequestIntakeCandidate,
    ExtractedField,
    ExtractionOrigin,
    FieldReviewStatus,
    IntakeLineCandidate,
    IntakeSource,
    IntakeSourceKind,
    UnconfiguredDocumentExtractionPort,
    promote_candidate,
)


class IntakeTests(unittest.TestCase):
    def attachment(self):
        return AttachmentMetadata(
            attachment_id="att_1",
            file_name="quote.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="a" * 64,
        )

    def source(self):
        return IntakeSource(
            source_id="source_1",
            workspace_id="ws_1",
            kind=IntakeSourceKind.PDF,
            attachment=self.attachment(),
        )

    def field(self, field_id, value, *, status=FieldReviewStatus.CONFIRMED, confidence="0.95", corrected=None):
        return ExtractedField(
            field_id=field_id,
            raw_value=value,
            confidence=Decimal(confidence),
            origin=ExtractionOrigin.MODEL,
            source_locator=f"page1:{field_id}",
            review_status=status,
            corrected_value=corrected,
        )

    def candidate(self, *, title_status=FieldReviewStatus.CONFIRMED, quantity_status=FieldReviewStatus.CONFIRMED, trusted_customer_id="customer_1"):
        return CommercialRequestIntakeCandidate(
            candidate_id="cand_1",
            workspace_id="ws_1",
            source=self.source(),
            version=1,
            title=self.field("title", "9월 구매 요청", status=title_status),
            requested_delivery_date=self.field("delivery", "2026-09-30"),
            line_candidates=(
                IntakeLineCandidate(
                    line_candidate_id="line_1",
                    description=self.field("desc_1", "모터"),
                    quantity=self.field("qty_1", "2", status=quantity_status),
                    unit=self.field("unit_1", "EA"),
                ),
            ),
            trusted_customer_id=trusted_customer_id,
        )

    def test_document_source_is_bound_to_content_hash(self):
        source = self.source()
        self.assertEqual(source.immutable_content_ref, "sha256:" + "a" * 64)

    def test_low_confidence_does_not_become_trusted_automatically(self):
        field = ExtractedField(
            field_id="qty",
            raw_value="20",
            confidence=Decimal("0.99"),
            origin=ExtractionOrigin.MODEL,
            source_locator="page1:row2",
            review_status=FieldReviewStatus.UNREVIEWED,
        )
        self.assertFalse(field.trusted_business_value)
        self.assertIsNone(field.resolved_value)

    def test_unreviewed_field_blocks_promotion(self):
        candidate = self.candidate(quantity_status=FieldReviewStatus.UNREVIEWED)
        self.assertFalse(candidate.ready_for_promotion)
        with self.assertRaisesRegex(ContractError, "unresolved"):
            promote_candidate(candidate, request_id="req_1")

    def test_trusted_customer_binding_is_required(self):
        candidate = self.candidate(trusted_customer_id=None)
        self.assertFalse(candidate.ready_for_promotion)
        with self.assertRaises(ContractError):
            promote_candidate(candidate, request_id="req_1")

    def test_corrected_value_is_promoted_not_raw_value(self):
        corrected_quantity = ExtractedField(
            field_id="qty_1",
            raw_value="200",
            confidence=Decimal("0.55"),
            origin=ExtractionOrigin.OCR,
            source_locator="page1:row2",
            review_status=FieldReviewStatus.CORRECTED,
            corrected_value="20",
        )
        candidate = CommercialRequestIntakeCandidate(
            candidate_id="cand_1",
            workspace_id="ws_1",
            source=self.source(),
            version=1,
            title=self.field("title", "9월 구매 요청"),
            requested_delivery_date=self.field("delivery", "2026-09-30"),
            line_candidates=(
                IntakeLineCandidate(
                    line_candidate_id="line_1",
                    description=self.field("desc_1", "모터"),
                    quantity=corrected_quantity,
                    unit=self.field("unit_1", "EA"),
                ),
            ),
            trusted_customer_id="customer_1",
        )
        request = promote_candidate(candidate, request_id="req_1")
        self.assertEqual(request.line_items[0].quantity, Decimal("20"))

    def test_unknown_field_blocks_promotion(self):
        unknown = ExtractedField(
            field_id="title",
            raw_value=None,
            confidence=Decimal("0.1"),
            origin=ExtractionOrigin.MODEL,
            source_locator="page1:title",
            review_status=FieldReviewStatus.UNKNOWN,
        )
        candidate = CommercialRequestIntakeCandidate(
            candidate_id="cand_1",
            workspace_id="ws_1",
            source=self.source(),
            version=1,
            title=unknown,
            requested_delivery_date=None,
            line_candidates=(
                IntakeLineCandidate(
                    line_candidate_id="line_1",
                    description=self.field("desc_1", "모터"),
                    quantity=self.field("qty_1", "2"),
                    unit=self.field("unit_1", "EA"),
                ),
            ),
            trusted_customer_id="customer_1",
        )
        self.assertGreater(candidate.unresolved_field_count, 0)
        self.assertFalse(candidate.ready_for_promotion)

    def test_promoted_request_uses_reviewed_iso_date(self):
        request = promote_candidate(self.candidate(), request_id="req_1")
        self.assertEqual(request.customer_id, "customer_1")
        self.assertEqual(request.requested_delivery_date.isoformat(), "2026-09-30")
        self.assertEqual(request.title, "9월 구매 요청")

    def test_invalid_reviewed_date_fails_closed(self):
        candidate = CommercialRequestIntakeCandidate(
            candidate_id="cand_1",
            workspace_id="ws_1",
            source=self.source(),
            version=1,
            title=self.field("title", "9월 구매 요청"),
            requested_delivery_date=self.field("delivery", "09/30/2026"),
            line_candidates=(
                IntakeLineCandidate(
                    line_candidate_id="line_1",
                    description=self.field("desc_1", "모터"),
                    quantity=self.field("qty_1", "2"),
                    unit=self.field("unit_1", "EA"),
                ),
            ),
            trusted_customer_id="customer_1",
        )
        with self.assertRaisesRegex(ContractError, "ISO"):
            promote_candidate(candidate, request_id="req_1")

    def test_candidate_is_never_trusted_execution_input(self):
        candidate = self.candidate()
        self.assertFalse(candidate.trusted_execution_input)
        self.assertFalse(candidate.safe_dict()["trusted_execution_input"])

    def test_cross_workspace_source_is_rejected(self):
        other_source = IntakeSource(
            source_id="source_2",
            workspace_id="ws_2",
            kind=IntakeSourceKind.PDF,
            attachment=self.attachment(),
        )
        with self.assertRaises(ContractError):
            CommercialRequestIntakeCandidate(
                candidate_id="cand_1",
                workspace_id="ws_1",
                source=other_source,
                version=1,
                title=self.field("title", "x"),
                requested_delivery_date=None,
                line_candidates=(
                    IntakeLineCandidate(
                        line_candidate_id="line_1",
                        description=self.field("desc_1", "모터"),
                        quantity=self.field("qty_1", "1"),
                        unit=self.field("unit_1", "EA"),
                    ),
                ),
                trusted_customer_id="customer_1",
            )

    def test_unconfigured_extractor_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "not configured"):
            UnconfiguredDocumentExtractionPort().extract(self.source())

    def test_binary_float_confidence_is_rejected(self):
        with self.assertRaises(ContractError):
            ExtractedField(
                field_id="qty",
                raw_value="2",
                confidence=0.9,  # type: ignore[arg-type]
                origin=ExtractionOrigin.MODEL,
                source_locator="page1:qty",
            )


if __name__ == "__main__":
    unittest.main()
