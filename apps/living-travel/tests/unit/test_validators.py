"""Unit tests for Living Travel validators."""

import json
from pathlib import Path

import pytest

from app.domain.enums import InformationClass
from app.domain.models import (
    EditionContent,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
    InformationItem,
)
from app.pipeline.errors import MarkupError
from app.pipeline.markup import check_unsafe_markup, reject_if_unsafe
from app.pipeline.validators import (
    validate_draft_against_plan,
    validate_edition_content,
    validate_feedback_references,
    validate_information_class_metadata,
    validate_item_ids_unique,
    validate_plan,
    validate_section_ids_unique,
    validate_source_references,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _make_content(data: dict) -> EditionContent:
    return EditionContent.model_validate(data)


def _make_content_unvalidated(data: dict) -> EditionContent:
    return EditionContent.model_construct(**data)


def _make_content_with_dup_sections() -> EditionContent:
    s1 = EditionSection(section_id="sec_dup", title="첫 번째", narrative="A")
    s2 = EditionSection(section_id="sec_dup", title="두 번째", narrative="B")
    c = EditionContent.model_construct(
        content_version="1.0",
        publication_title="T",
        edition_title="T",
        destination="B",
        trip_frame="2박",
        editorial_opening="T",
        sections=[s1, s2],
        applied_feedback=[],
        next_edition_prompt="",
        provenance_note="",
    )
    return c


class TestMarkupRejection:
    def test_clean_text_passes(self):
        assert check_unsafe_markup("부산은 한국 제2의 도시입니다.") == []

    def test_script_tag_detected(self):
        violations = check_unsafe_markup("<script>alert('xss')</script>")
        assert len(violations) > 0

    def test_event_handler_detected(self):
        violations = check_unsafe_markup('onclick="alert(1)"')
        assert len(violations) > 0

    def test_javascript_url_detected(self):
        violations = check_unsafe_markup("javascript:void(0)")
        assert len(violations) > 0

    def test_reject_if_unsafe_raises(self):
        with pytest.raises(MarkupError):
            reject_if_unsafe("<script>alert(1)</script>")

    def test_reject_if_unsafe_clean(self):
        reject_if_unsafe("부산 해운대 해수욕장")


class TestSectionIdsUnique:
    def test_unique_passes(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        errors = validate_section_ids_unique(content)
        assert errors == []

    def test_duplicate_detected(self):
        content = _make_content_with_dup_sections()
        errors = validate_section_ids_unique(content)
        assert len(errors) > 0
        assert "Duplicate" in errors[0]


class TestItemIdsUnique:
    def test_unique_passes(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        errors = validate_item_ids_unique(content)
        assert errors == []


class TestSourceReferences:
    def test_valid_references(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        valid = {"src_gukje_market", "src_busan_tourism", "src_haegyeolri"}
        errors = validate_source_references(content, valid)
        assert errors == []

    def test_unknown_reference(self):
        content = _make_content(
            _load_fixture("adversarial_payloads.json")["adversarial_unknown_source"]
        )
        valid = {"src_busan_tourism", "src_gukje_market"}
        errors = validate_source_references(content, valid)
        assert len(errors) > 0
        assert "Unknown source reference" in errors[0]


class TestInformationClassMetadata:
    def test_time_sensitive_with_metadata(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        errors = validate_information_class_metadata(content)
        assert errors == []

    def test_time_sensitive_missing_date(self):
        data = _load_fixture("adversarial_payloads.json")["adversarial_time_sensitive_no_date"]
        content = _make_content(data)
        errors = validate_information_class_metadata(content)
        assert len(errors) > 0
        assert "as_of_date" in errors[0]

    def test_time_sensitive_missing_verify(self):
        item = InformationItem(
            item_id="i1",
            information_class=InformationClass.time_sensitive,
            as_of_date="2026-07-20",
            source_ref="src1",
            verify_before_use=False,
        )
        section = EditionSection(
            section_id="s1", title="T", narrative="N", items=[item]
        )
        content = EditionContent(
            publication_title="T",
            edition_title="T",
            destination="B",
            trip_frame="2박",
            editorial_opening="T",
            sections=[section],
        )
        errors = validate_information_class_metadata(content)
        assert len(errors) > 0
        assert "verify_before_use" in errors[0]


class TestFeedbackReferences:
    def test_valid_feedback(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        errors = validate_feedback_references(content, ["sec_morning_gukje"])
        assert errors == []

    def test_unknown_feedback_ref(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        errors = validate_feedback_references(content, ["sec_nonexistent"])
        assert len(errors) > 0
        assert "unknown section" in errors[0]


class TestValidatePlan:
    def test_valid_plan(self):
        plan = EditorialPlan(
            central_theme="부산 산책",
            sections=[
                EditorialPlanSection(
                    section_id="s1", title="아침", description="조용한 아침"
                )
            ],
        )
        errors = validate_plan(plan)
        assert errors == []

    def test_empty_theme_detected(self):
        plan = EditorialPlan.model_construct(
            plan_version="1.0", language="ko", central_theme="  ", sections=[]
        )
        errors = validate_plan(plan)
        assert len(errors) > 0


class TestValidateDraftAgainstPlan:
    def test_matching_plan(self):
        data = _load_fixture("source_bundle.json")["first_edition_fixture"]
        content = _make_content(data)
        plan = EditorialPlan(
            central_theme="부산",
            sections=[
                EditorialPlanSection(
                    section_id=s["section_id"], title=s["title"], description=s["narrative"][:50]
                )
                for s in data["sections"]
            ],
        )
        errors = validate_draft_against_plan(content, plan)
        assert errors == []

    def test_missing_section(self):
        data = _load_fixture("source_bundle.json")["first_edition_fixture"]
        content = _make_content(data)
        plan = EditorialPlan(
            central_theme="부산",
            sections=[
                EditorialPlanSection(
                    section_id="sec_nonexistent", title="X", description="X"
                )
            ],
        )
        errors = validate_draft_against_plan(content, plan)
        assert len(errors) > 0


class TestValidateEditionContent:
    def test_full_validation(self):
        content = _make_content(_load_fixture("source_bundle.json")["first_edition_fixture"])
        valid = {"src_gukje_market", "src_busan_tourism", "src_haegyeolri"}
        errors = validate_edition_content(content, valid_source_ids=valid)
        assert errors == []

    def test_full_validation_with_adversarial(self):
        content = _make_content_with_dup_sections()
        errors = validate_edition_content(content)
        assert len(errors) > 0
