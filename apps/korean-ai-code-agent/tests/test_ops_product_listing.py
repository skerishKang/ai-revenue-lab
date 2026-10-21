from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from kagent.contracts import ContractError
from kagent.ops_intake import ExtractionOrigin, FieldReviewStatus
from kagent.ops_product_listing import (
    COLUMN_TO_ATTRIBUTE,
    INTERNAL_ONLY_ATTRIBUTES,
    SUPPLIER_COLUMNS,
    ProductAttribute,
    apply_review,
    build_browser_fill_plan,
    build_candidate_record,
    build_detail_html,
    check_image_policy,
    merge_research_notes,
    parse_image_manifest,
    parse_supplier_csv,
    project_channel_draft,
    run_product_listing_pilot,
)
from kagent.ops_product_listing_channels import (
    CHANNEL_PROFILES,
    COUPANG_PROFILE,
    ELEVENST_PROFILE,
    NAVER_SMART_STORE_PROFILE,
    OWN_MALL_PROFILE,
)

SAMPLE_ROW = {
    "상품명": "데모 USB-C 알루미늄 노트북 스탠드",
    "모델명": "DEMO-STD-001",
    "브랜드": "DemoBrand",
    "제조사": "데모제조 주식회사",
    "카테고리": "디지털/가전 > 노트북 액세서리",
    "카테고리코드": "DEMO-100201",
    "색상": "무광 실버",
    "사이즈": "12.9인치 전용",
    "소재": "알루미늄 합금",
    "무게kg": "0.42",
    "가로mm": "212",
    "세로mm": "168",
    "높이mm": "18",
    "단위": "개",
    "판매가": "32900",
    "정가": "39900",
    "재고수량": "120",
    "최소주문수량": "1",
    "품번": "DEMO-STD-001-SLV",
    "원산지": "국내 제조",
    "보증기간": "12개월 제조사 보증",
    "부가세구분": "Y",
    "미성년자구매": "N",
    "배송비유형": "무료배송",
    "배송비": "0",
    "발송예정일": "2",
    "반품교환정책": "미개봉 상태 기준 7일 이내 반품 가능",
    "요약설명": "",
    "상세설명": "",
    "검색어": "노트북 스탠드, USB-C 랭징 스테이션",
    "태그": "",
    "대표이미지": "demo-main-01.png|1200x1200|482130|데모 대표 이미지",
    "추가이미지": "demo-detail-01.png|1200x1200|351004|데모 상세 이미지",
    "공급사": "데모공급사(샘플·내부용)",
    "공급가": "18500",
}


def supplier_csv_text(row: dict[str, str] | None = None) -> str:
    values = dict(SAMPLE_ROW)
    if row:
        values.update(row)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(SUPPLIER_COLUMNS), lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow(values)
    return buffer.getvalue()


def sample_record():
    rows = parse_supplier_csv(supplier_csv_text())
    return build_candidate_record(
        rows[0],
        product_id="pilot-product-001",
        source_ref="supplier-file",
        locator_prefix="supplier:row1",
    )


class SupplierIntakeTests(unittest.TestCase):
    def test_exact_header_set_is_required(self):
        with self.assertRaises(ContractError):
            parse_supplier_csv("상품명,모델명\n데모,DEMO-1\n")

    def test_spreadsheet_formula_cell_is_refused(self):
        text = supplier_csv_text({"판매가": "=1+1"})
        with self.assertRaises(ContractError):
            parse_supplier_csv(text)

    def test_nul_byte_is_refused(self):
        with self.assertRaises(ContractError):
            parse_supplier_csv(supplier_csv_text().replace("DemoBrand", "Demo\x00Brand"))

    def test_empty_supplier_file_is_refused(self):
        with self.assertRaises(ContractError):
            parse_supplier_csv("")

    def test_parsed_fields_stay_unreviewed(self):
        record = sample_record()
        product_name = record.fields[ProductAttribute.PRODUCT_NAME]
        self.assertEqual(product_name.review_status, FieldReviewStatus.UNREVIEWED)
        self.assertFalse(product_name.trusted_business_value)
        self.assertEqual(product_name.origin, ExtractionOrigin.RULE)

    def test_option_summary_is_derived_from_option_columns(self):
        record = sample_record()
        summary = record.value(ProductAttribute.OPTION_SUMMARY)
        self.assertIn("색상=무광 실버", summary)
        self.assertIn("사이즈=12.9인치 전용", summary)


class ResearchMergeTests(unittest.TestCase):
    def test_research_never_overwrites_a_supplier_value(self):
        record = sample_record()
        merged = merge_research_notes(
            record, {"product_name": "다른 이름", "product_summary": "요약"}
        )
        self.assertEqual(
            merged.value(ProductAttribute.PRODUCT_NAME),
            "데모 USB-C 알루미늄 노트북 스탠드",
        )
        self.assertEqual(merged.value(ProductAttribute.PRODUCT_SUMMARY), "요약")

    def test_research_source_is_kept_in_the_locator(self):
        record = sample_record()
        merged = merge_research_notes(
            record,
            {
                "product_summary": {
                    "value": "요약",
                    "source": "https://example.invalid/demo",
                }
            },
        )
        field_value = merged.fields[ProductAttribute.PRODUCT_SUMMARY]
        self.assertEqual(field_value.origin, ExtractionOrigin.MODEL)
        self.assertIn("https://example.invalid/demo", field_value.source_locator)

    def test_research_cannot_carry_internal_commercial_attributes(self):
        record = sample_record()
        with self.assertRaises(ContractError):
            merge_research_notes(record, {"supply_cost": "1"})

    def test_unknown_research_attribute_is_refused(self):
        record = sample_record()
        with self.assertRaises(ContractError):
            merge_research_notes(record, {"not_an_attribute": "x"})


class ReviewTests(unittest.TestCase):
    def test_confirmed_field_becomes_trusted(self):
        record = sample_record()
        reviewed, events = apply_review(
            record, {"product_name": {"status": "confirmed"}}
        )
        self.assertTrue(
            reviewed.fields[ProductAttribute.PRODUCT_NAME].trusted_business_value
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind.value, "extraction_field_confirmed")

    def test_corrected_field_uses_the_human_value(self):
        record = sample_record()
        reviewed, events = apply_review(
            record,
            {"product_name": {"status": "corrected", "value": "수정된 상품명"}},
        )
        self.assertEqual(reviewed.value(ProductAttribute.PRODUCT_NAME), "수정된 상품명")
        self.assertEqual(events[0].kind.value, "extraction_field_corrected")

    def test_correction_without_a_value_is_refused(self):
        record = sample_record()
        with self.assertRaises(ContractError):
            apply_review(record, {"product_name": {"status": "corrected"}})

    def test_review_of_an_unknown_field_is_refused(self):
        record = sample_record()
        with self.assertRaises(ContractError):
            apply_review(record, {"not_a_field": {"status": "confirmed"}})

    def test_two_review_rounds_on_one_field_keep_distinct_event_ids(self):
        record = sample_record()
        _, first = apply_review(
            record, {"brand": {"status": "confirmed"}}, round_index=1
        )
        _, second = apply_review(
            record, {"brand": {"status": "confirmed"}}, round_index=2
        )
        self.assertNotEqual(first[0].event_id, second[0].event_id)


class ChannelProjectionTests(unittest.TestCase):
    def test_missing_required_field_is_an_error(self):
        record = sample_record()
        record = type(record)(
            product_id=record.product_id,
            source_ref=record.source_ref,
            fields={
                key: value
                for key, value in record.fields.items()
                if key is not ProductAttribute.BRAND
            },
        )
        draft = project_channel_draft(record, COUPANG_PROFILE)
        codes = {issue.code for issue in draft.error_issues}
        self.assertIn("missing_required_field", codes)
        self.assertFalse(draft.ready_for_entry)

    def test_overlong_value_is_an_error(self):
        record = sample_record()
        long_name = "가" * 200
        reviewed, _ = apply_review(
            record, {"product_name": {"status": "corrected", "value": long_name}}
        )
        draft = project_channel_draft(reviewed, NAVER_SMART_STORE_PROFILE)
        codes = {issue.code for issue in draft.error_issues}
        self.assertIn("value_too_long", codes)

    def test_non_numeric_price_is_an_error(self):
        record = sample_record()
        reviewed, _ = apply_review(
            record, {"sale_price": {"status": "corrected", "value": "가격문의"}}
        )
        draft = project_channel_draft(reviewed, COUPANG_PROFILE)
        codes = {issue.code for issue in draft.error_issues}
        self.assertIn("value_not_numeric", codes)

    def test_enum_value_outside_the_allowed_list_is_an_error(self):
        record = sample_record()
        reviewed, _ = apply_review(
            record, {"shipping_fee_type": {"status": "corrected", "value": "무료배송비"}}
        )
        draft = project_channel_draft(reviewed, COUPANG_PROFILE)
        codes = {issue.code for issue in draft.error_issues}
        self.assertIn("value_not_allowed", codes)

    def test_internal_only_attributes_never_reach_a_channel_draft(self):
        record = sample_record()
        rendered = json.dumps(
            [
                project_channel_draft(record, profile).safe_dict()
                for profile in CHANNEL_PROFILES
            ],
            ensure_ascii=False,
        )
        self.assertNotIn("18500", rendered)
        self.assertNotIn("데모공급사", rendered)
        for attribute in INTERNAL_ONLY_ATTRIBUTES:
            self.assertNotIn(attribute.value, rendered)

    def test_every_profile_records_its_public_source(self):
        for profile in CHANNEL_PROFILES:
            self.assertTrue(profile.source_urls)
            self.assertTrue(profile.source_checked_on)


class ImagePolicyTests(unittest.TestCase):
    def test_manifest_parsing_requires_the_full_entry_shape(self):
        with self.assertRaises(ContractError):
            parse_image_manifest("only-a-name")

    def test_small_image_is_an_error_for_elevenst(self):
        entries = parse_image_manifest("small.png|300x300|1000|설명")
        issues = check_image_policy(entries, ELEVENST_PROFILE)
        codes = {issue.code for issue in issues}
        self.assertIn("image_too_small", codes)

    def test_non_square_image_is_an_error_for_elevenst(self):
        entries = parse_image_manifest("wide.png|1200x600|1000|설명")
        issues = check_image_policy(entries, ELEVENST_PROFILE)
        codes = {issue.code for issue in issues}
        self.assertIn("image_not_square", codes)

    def test_disallowed_extension_is_an_error(self):
        entries = parse_image_manifest("main.tiff|1200x1200|1000|설명")
        issues = check_image_policy(entries, COUPANG_PROFILE)
        codes = {issue.code for issue in issues}
        self.assertIn("image_format_not_allowed", codes)

    def test_oversized_image_is_an_error(self):
        entries = parse_image_manifest("big.png|1200x1200|9000000|설명")
        issues = check_image_policy(entries, COUPANG_PROFILE)
        codes = {issue.code for issue in issues}
        self.assertIn("image_too_large", codes)

    def test_missing_image_is_an_error(self):
        issues = check_image_policy((), OWN_MALL_PROFILE)
        codes = {issue.code for issue in issues}
        self.assertIn("missing_main_image", codes)


class BrowserFillPlanTests(unittest.TestCase):
    def test_plan_only_uses_actions_the_product_classifies(self):
        record = sample_record()
        draft = project_channel_draft(record, COUPANG_PROFILE)
        plan = build_browser_fill_plan(draft, COUPANG_PROFILE)
        self.assertTrue(plan.steps)
        for step in plan.steps:
            self.assertIn(
                step.classification,
                {"lease_eligible", "step_up_required", "prohibited", "out_of_scope"},
            )

    def test_image_upload_and_submit_stay_human_steps(self):
        record = sample_record()
        draft = project_channel_draft(record, COUPANG_PROFILE)
        plan = build_browser_fill_plan(draft, COUPANG_PROFILE)
        actions = {step.action: step for step in plan.steps}
        self.assertTrue(actions["upload"].requires_human)
        self.assertTrue(actions["submit"].requires_human)
        self.assertEqual(actions["upload"].classification, "step_up_required")
        self.assertEqual(actions["submit"].classification, "step_up_required")

    def test_typing_actions_are_the_automatable_part(self):
        record = sample_record()
        draft = project_channel_draft(record, COUPANG_PROFILE)
        plan = build_browser_fill_plan(draft, COUPANG_PROFILE)
        self.assertTrue(plan.automatable_steps)
        for step in plan.automatable_steps:
            self.assertEqual(step.action, "type")
            self.assertEqual(step.classification, "lease_eligible")


class DetailHtmlTests(unittest.TestCase):
    def test_supplier_text_is_escaped_in_the_generated_description(self):
        record = merge_research_notes(
            sample_record(), {"product_summary": "요약"}
        )
        reviewed, _ = apply_review(
            record,
            {
                "product_summary": {
                    "status": "corrected",
                    "value": "<script>alert(1)</script>",
                }
            },
        )
        html = build_detail_html(reviewed)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class PilotRunTests(unittest.TestCase):
    def _clock(self):
        moments = iter(
            [
                datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 21, 9, 6, tzinfo=timezone.utc),
                datetime(2026, 10, 21, 9, 11, tzinfo=timezone.utc),
                datetime(2026, 10, 21, 9, 13, tzinfo=timezone.utc),
            ]
        )
        return lambda: next(moments)

    def _run(self, **kwargs):
        rows = parse_supplier_csv(supplier_csv_text())
        return run_product_listing_pilot(
            supplier_rows=rows,
            research_notes={"product_summary": "요약"},
            profiles=CHANNEL_PROFILES,
            product_id="pilot-product-001",
            source_ref="supplier-file",
            clock=self._clock(),
            **kwargs,
        )

    def test_run_produces_measured_milestones(self):
        result = self._run()
        self.assertEqual(result.measurement.milestone_minutes["intake_to_research_minutes"], "6")
        self.assertEqual(result.measurement.milestone_minutes["intake_to_draft_minutes"], "11")
        self.assertEqual(result.measurement.milestone_minutes["total_minutes"], "13")

    def test_estimated_baseline_never_becomes_a_measured_comparison(self):
        result = self._run(baseline_manual_minutes=Decimal("45"))
        self.assertTrue(result.measurement.baseline_is_estimated)
        self.assertEqual(result.measurement.baseline_estimated_minutes, "45")
        self.assertFalse(result.measurement.measured_comparison_available)

    def test_review_produces_a_correction_rate(self):
        result = self._run(
            reviews=[
                {
                    "product_name": {"status": "corrected", "value": "수정된 상품명"},
                    "brand": {"status": "confirmed"},
                }
            ]
        )
        self.assertEqual(result.measurement.correction_rate, "50")

    def test_unreviewed_run_produces_no_correction_rate(self):
        result = self._run()
        self.assertIsNone(result.measurement.correction_rate)

    def test_internal_attributes_do_not_count_as_unresolved(self):
        result = self._run()
        for attribute in INTERNAL_ONLY_ATTRIBUTES:
            self.assertIn(
                attribute,
                result.record.fields,
            )
        self.assertNotIn(
            ProductAttribute.SUPPLY_COST.value,
            [
                field_id
                for field_id, meta in result.record.safe_dict()["fields"].items()
                if meta["trusted_business_value"]
            ],
        )

    def test_a_correction_that_changes_the_description_needs_a_second_review(self):
        result = self._run(
            reviews=[
                {"model_name": {"status": "corrected", "value": "DEMO-STD-999"}}
            ]
        )
        description_field = result.record.fields[ProductAttribute.DETAIL_HTML]
        self.assertEqual(
            description_field.review_status, FieldReviewStatus.UNREVIEWED
        )
        self.assertIn("DEMO-STD-999", result.description_html)

    def test_a_second_review_round_can_confirm_the_regenerated_description(self):
        first = self._run(
            reviews=[
                {"model_name": {"status": "corrected", "value": "DEMO-STD-999"}}
            ]
        )
        second = self._run(
            reviews=[
                {"model_name": {"status": "corrected", "value": "DEMO-STD-999"}},
                {"detail_html": {"status": "confirmed"}},
            ]
        )
        self.assertEqual(
            second.record.unresolved_field_count,
            first.record.unresolved_field_count - 1,
        )
        self.assertEqual(
            second.record.fields[ProductAttribute.DETAIL_HTML].review_status,
            FieldReviewStatus.CONFIRMED,
        )

    def test_every_channel_draft_is_produced_with_a_source(self):
        result = self._run()
        self.assertEqual(len(result.drafts), len(CHANNEL_PROFILES))
        for draft in result.drafts:
            self.assertTrue(draft.source_urls)
            self.assertFalse(draft.ready_for_entry)

    def test_run_never_writes_a_supply_cost_into_a_draft(self):
        result = self._run()
        rendered = json.dumps(
            [draft.safe_dict() for draft in result.drafts], ensure_ascii=False
        )
        self.assertNotIn("18500", rendered)

    def test_review_checklist_and_follow_ups_are_populated(self):
        result = self._run()
        self.assertTrue(result.review_checklist)
        self.assertTrue(result.follow_ups)

    def test_a_multi_product_supplier_file_is_refused(self):
        rows = parse_supplier_csv(supplier_csv_text())
        with self.assertRaises(ContractError):
            run_product_listing_pilot(
                supplier_rows=rows + rows,
                research_notes={},
                profiles=CHANNEL_PROFILES,
            )

    def test_internal_attribute_map_has_no_channel_source(self):
        for attribute in INTERNAL_ONLY_ATTRIBUTES:
            for profile in CHANNEL_PROFILES:
                for spec in profile.fields:
                    self.assertIsNot(spec.source, attribute)


class SupplierXlsxTests(unittest.TestCase):
    def test_xlsx_round_trip_through_the_core_parser(self):
        try:
            import openpyxl  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("openpyxl is not available in this lane")
        from kagent.ops_product_listing import parse_supplier_xlsx

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "상품자료"
        sheet.append(list(SUPPLIER_COLUMNS))
        sheet.append([SAMPLE_ROW[column] for column in SUPPLIER_COLUMNS])
        buffer = io.BytesIO()
        workbook.save(buffer)

        rows = parse_supplier_xlsx(buffer.getvalue(), name="supplier_products.xlsx")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["모델명"], "DEMO-STD-001")
        self.assertEqual(rows[0]["판매가"], "32900")


class ColumnMapTests(unittest.TestCase):
    def test_every_supplier_column_maps_to_one_attribute(self):
        self.assertEqual(len(COLUMN_TO_ATTRIBUTE), len(SUPPLIER_COLUMNS))
        self.assertEqual(len(set(COLUMN_TO_ATTRIBUTE.values())), len(SUPPLIER_COLUMNS))

    def test_supplier_columns_are_unique(self):
        self.assertEqual(len(set(SUPPLIER_COLUMNS)), len(SUPPLIER_COLUMNS))


if __name__ == "__main__":
    unittest.main()
