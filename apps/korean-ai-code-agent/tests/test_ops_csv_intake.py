from __future__ import annotations

import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.ops_communications import AttachmentMetadata
from kagent.ops_csv_intake import (
    CSV_AUTO_PROMOTION_SUPPORTED,
    CSV_FORMULA_EXECUTION_SUPPORTED,
    CSV_TRUSTED_CUSTOMER_BINDING_SUPPORTED,
    StrictCsvCommercialRequestAdapter,
)
from kagent.ops_intake import FieldReviewStatus, IntakeSource, IntakeSourceKind, promote_candidate


def source() -> IntakeSource:
    payload = b"fixture"
    return IntakeSource(
        source_id="source_csv_1",
        workspace_id="ws_1",
        kind=IntakeSourceKind.CSV,
        attachment=AttachmentMetadata(
            attachment_id="attachment_csv_1",
            file_name="request.csv",
            mime_type="text/csv",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        ),
    )


VALID = """title,requested_delivery_date,line_id,description,quantity,unit
9월 모터 주문,2026-09-20,line_1,모터 A,2,EA
9월 모터 주문,2026-09-20,line_2,모터 B,3.5,EA
"""


class StrictCsvIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = StrictCsvCommercialRequestAdapter()

    def test_valid_csv_becomes_unreviewed_candidate_not_business_record(self):
        result = self.adapter.parse(source=source(), text=VALID, candidate_id="candidate_csv_1")
        candidate = result.candidate
        self.assertEqual(result.data_row_count, 2)
        self.assertEqual(candidate.source.kind, IntakeSourceKind.CSV)
        self.assertFalse(candidate.trusted_execution_input)
        self.assertFalse(candidate.ready_for_promotion)
        self.assertIsNone(candidate.trusted_customer_id)
        self.assertFalse(result.trusted_business_data_created)
        self.assertEqual(candidate.title.review_status, FieldReviewStatus.UNREVIEWED)
        self.assertEqual(candidate.line_candidates[0].quantity.raw_value, "2")
        with self.assertRaises(ContractError):
            promote_candidate(candidate, request_id="request_1")
        self.assertFalse(CSV_FORMULA_EXECUTION_SUPPORTED)
        self.assertFalse(CSV_AUTO_PROMOTION_SUPPORTED)
        self.assertFalse(CSV_TRUSTED_CUSTOMER_BINDING_SUPPORTED)

    def test_every_field_has_row_column_provenance(self):
        candidate = self.adapter.parse(
            source=source(),
            text=VALID,
            candidate_id="candidate_csv_provenance",
        ).candidate
        self.assertEqual(candidate.title.source_locator, "csv:line:2:title")
        first = candidate.line_candidates[0]
        self.assertEqual(first.description.source_locator, "csv:line:2:description")
        self.assertEqual(first.quantity.source_locator, "csv:line:2:quantity")
        self.assertEqual(first.unit.source_locator, "csv:line:2:unit")
        second = candidate.line_candidates[1]
        self.assertEqual(second.description.source_locator, "csv:line:3:description")

    def test_utf8_bom_header_is_accepted(self):
        result = self.adapter.parse(
            source=source(),
            text="\ufeff" + VALID,
            candidate_id="candidate_csv_bom",
        )
        self.assertEqual(result.data_row_count, 2)

    def test_source_kind_and_mime_are_exact(self):
        wrong_kind = IntakeSource(
            source_id="source_xlsx",
            workspace_id="ws_1",
            kind=IntakeSourceKind.XLSX,
            attachment=source().attachment,
        )
        with self.assertRaises(ContractError):
            self.adapter.parse(source=wrong_kind, text=VALID, candidate_id="candidate_wrong_kind")
        attachment = source().attachment
        assert attachment is not None
        wrong_mime = IntakeSource(
            source_id="source_wrong_mime",
            workspace_id="ws_1",
            kind=IntakeSourceKind.CSV,
            attachment=AttachmentMetadata(
                attachment_id="attachment_wrong_mime",
                file_name="request.csv",
                mime_type="text/plain",
                size_bytes=attachment.size_bytes,
                sha256=attachment.sha256,
            ),
        )
        with self.assertRaises(ContractError):
            self.adapter.parse(source=wrong_mime, text=VALID, candidate_id="candidate_wrong_mime")

    def test_missing_extra_and_duplicate_headers_fail_closed(self):
        missing = "title,requested_delivery_date,line_id,description,quantity\nA,,1,Item,1\n"
        extra = "title,requested_delivery_date,line_id,description,quantity,unit,price\nA,,1,Item,1,EA,100\n"
        duplicate = "title,title,line_id,description,quantity,unit\nA,A,1,Item,1,EA\n"
        for text in (missing, extra, duplicate):
            with self.subTest(text=text.splitlines()[0]):
                with self.assertRaises(ContractError):
                    self.adapter.parse(source=source(), text=text, candidate_id="candidate_bad_header")

    def test_extra_row_column_and_malformed_csv_fail_closed(self):
        extra_column = "title,requested_delivery_date,line_id,description,quantity,unit\nA,,1,Item,1,EA,unexpected\n"
        malformed = 'title,requested_delivery_date,line_id,description,quantity,unit\nA,,1,"unterminated,1,EA\n'
        with self.assertRaises(ContractError):
            self.adapter.parse(source=source(), text=extra_column, candidate_id="candidate_extra")
        with self.assertRaises(ContractError):
            self.adapter.parse(source=source(), text=malformed, candidate_id="candidate_malformed")

    def test_duplicate_line_ids_and_request_field_drift_fail_closed(self):
        duplicate = """title,requested_delivery_date,line_id,description,quantity,unit
A,2026-09-20,line_1,Item A,1,EA
A,2026-09-20,line_1,Item B,1,EA
"""
        title_drift = """title,requested_delivery_date,line_id,description,quantity,unit
A,2026-09-20,line_1,Item A,1,EA
B,2026-09-20,line_2,Item B,1,EA
"""
        date_drift = """title,requested_delivery_date,line_id,description,quantity,unit
A,2026-09-20,line_1,Item A,1,EA
A,2026-09-21,line_2,Item B,1,EA
"""
        for text in (duplicate, title_drift, date_drift):
            with self.assertRaises(ContractError):
                self.adapter.parse(source=source(), text=text, candidate_id="candidate_drift")

    def test_formula_like_cells_are_rejected_and_never_executed(self):
        cases = (
            "=HYPERLINK(\"https://example.invalid\")",
            "+SUM(1,2)",
            "@cmd",
            "-10",
        )
        for value in cases:
            text = (
                "title,requested_delivery_date,line_id,description,quantity,unit\n"
                f'A,,line_1,"{value}",1,EA\n'
            )
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    self.adapter.parse(source=source(), text=text, candidate_id="candidate_formula")
        formula_quantity = "title,requested_delivery_date,line_id,description,quantity,unit\nA,,line_1,Item,=1+1,EA\n"
        with self.assertRaises(ContractError):
            self.adapter.parse(source=source(), text=formula_quantity, candidate_id="candidate_formula_qty")

    def test_quantity_must_be_positive_finite_decimal_without_binary_float(self):
        for value in ("0", "-1", "NaN", "Infinity", "1.1234567", "abc"):
            text = (
                "title,requested_delivery_date,line_id,description,quantity,unit\n"
                f"A,,line_1,Item,{value},EA\n"
            )
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    self.adapter.parse(source=source(), text=text, candidate_id="candidate_qty")

    def test_row_bound_is_enforced(self):
        rows = ["title,requested_delivery_date,line_id,description,quantity,unit"]
        rows.extend(f"A,,line_{index},Item {index},1,EA" for index in range(201))
        with self.assertRaises(ContractError):
            self.adapter.parse(
                source=source(),
                text="\n".join(rows) + "\n",
                candidate_id="candidate_too_many_rows",
            )


if __name__ == "__main__":
    unittest.main()
