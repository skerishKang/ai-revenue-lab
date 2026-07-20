"""Tests for deterministic editorial-plan and edition-draft validation."""

import pytest

from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
    InputSegment,
    NextEditionPrompt,
)
from app.pipeline.errors import (
    DraftValidationError,
    PlanValidationError,
)
from app.pipeline.validators import (
    collect_visible_fields,
    validate_draft,
    validate_plan,
)

_KNOWN_SEGMENTS = [
    InputSegment(segment_id="s001", text="First segment content.", start_offset=0, end_offset=22),
    InputSegment(segment_id="s002", text="Second segment content.", start_offset=22, end_offset=46),
]


def _make_first_plan():
    return EditorialPlan(
        plan_version="v1",
        language="ko",
        central_theme="theme",
        reader_value="value",
        opening_intent="intro",
        sections=[
            EditorialPlanSection(
                section_id="section-1",
                working_title="Section 1",
                purpose="purpose",
                source_segment_ids=["s001"],
            ),
            EditorialPlanSection(
                section_id="section-2",
                working_title="Section 2",
                purpose="purpose",
                source_segment_ids=["s002"],
            ),
        ],
        highlighted_insight="insight",
    )


def _make_first_draft():
    return EditionContent(
        content_version="v1",
        language="ko",
        publication_title="Title",
        edition_title="Edition 1",
        deck="A deck",
        opening="This is a sufficiently long opening paragraph for testing purposes.",
        sections=[
            EditionSection(
                section_id="section-1",
                title="Section 1 Title",
                paragraphs=["First paragraph of section one."],
                source_segment_ids=["s001"],
            ),
            EditionSection(
                section_id="section-2",
                title="Section 2 Title",
                paragraphs=["First paragraph of section two."],
                source_segment_ids=["s002"],
            ),
        ],
        highlighted_insight="Key insight.",
        provenance_note="This edition was created from material supplied by the reader.",
    )


class TestValidatePlan:
    def test_valid_first_edition_plan(self):
        plan = _make_first_plan()
        validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_non_editorial_plan_raises(self):
        with pytest.raises(PlanValidationError, match="EditorialPlan"):
            validate_plan("not a plan", segments=_KNOWN_SEGMENTS, is_follow_up=False)  # type: ignore

    def test_empty_segments_raises(self):
        plan = _make_first_plan()
        with pytest.raises(PlanValidationError, match="non-empty"):
            validate_plan(plan, segments=[], is_follow_up=False)

    def test_too_few_sections(self):
        plan = _make_first_plan()
        plan.sections = plan.sections[:1]
        with pytest.raises(PlanValidationError, match="between 2 and 4"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_too_many_sections(self):
        plan = _make_first_plan()
        plan.sections = [
            EditorialPlanSection(
                section_id=f"s{i}",
                working_title=f"S{i}",
                purpose="p",
                source_segment_ids=["s001"],
            )
            for i in range(5)
        ]
        with pytest.raises(PlanValidationError, match="between 2 and 4"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_duplicate_section_id(self):
        plan = _make_first_plan()
        plan.sections = [
            EditorialPlanSection(
                section_id="dup",
                working_title="A",
                purpose="p",
                source_segment_ids=["s001"],
            ),
            EditorialPlanSection(
                section_id="dup",
                working_title="B",
                purpose="p",
                source_segment_ids=["s002"],
            ),
        ]
        with pytest.raises(PlanValidationError, match="duplicate section_id"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_empty_source_segment_ids(self):
        plan = _make_first_plan()
        plan.sections[0].source_segment_ids = []
        with pytest.raises(PlanValidationError, match="references no segments"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_unknown_segment_reference(self):
        plan = _make_first_plan()
        plan.sections[0].source_segment_ids = ["s999"]
        with pytest.raises(PlanValidationError, match="unknown segment"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_first_edition_with_prior_references_raises(self):
        plan = _make_first_plan()
        plan.continuity = {"prior_edition_references": ["e1"]}
        with pytest.raises(PlanValidationError, match="must not reference"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_first_edition_with_applied_feedback_raises(self):
        plan = _make_first_plan()
        plan.continuity = {"applied_feedback": {"feedback_id": "fb1"}}
        with pytest.raises(PlanValidationError, match="must not claim"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_first_edition_with_feedback_action_raises(self):
        plan = _make_first_plan()
        plan.sections[0].feedback_action = "expand"
        with pytest.raises(PlanValidationError, match="must not carry"):
            validate_plan(plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_follow_up_missing_feedback_action_raises(self):
        plan = _make_first_plan()
        plan.continuity = {
            "applied_feedback": {"feedback_id": "fb1"},
        }
        with pytest.raises(PlanValidationError, match="must identify"):
            validate_plan(
                plan, segments=_KNOWN_SEGMENTS, is_follow_up=True, feedback_id="fb1"
            )

    def test_follow_up_missing_applied_feedback_raises(self):
        plan = _make_first_plan()
        plan.sections[0].feedback_action = "expand"
        with pytest.raises(PlanValidationError, match="must carry"):
            validate_plan(
                plan, segments=_KNOWN_SEGMENTS, is_follow_up=True, feedback_id="fb1"
            )

    def test_follow_up_mismatched_feedback_id_raises(self):
        plan = _make_first_plan()
        plan.sections[0].feedback_action = "expand"
        plan.continuity = {
            "applied_feedback": {"feedback_id": "fb2"},
        }
        with pytest.raises(PlanValidationError, match="mismatched"):
            validate_plan(
                plan, segments=_KNOWN_SEGMENTS, is_follow_up=True, feedback_id="fb1"
            )

    def test_valid_follow_up_plan(self):
        plan = _make_first_plan()
        plan.sections[0].feedback_action = "more_reflective: expand"
        plan.continuity = {
            "prior_edition_references": ["e1"],
            "applied_feedback": {"feedback_id": "fb1", "direction": "more_reflective"},
        }
        validate_plan(
            plan, segments=_KNOWN_SEGMENTS, is_follow_up=True, feedback_id="fb1"
        )


class TestValidateDraft:
    def test_valid_first_edition_draft(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_non_edition_content_raises(self):
        plan = _make_first_plan()
        with pytest.raises(DraftValidationError, match="EditionContent"):
            validate_draft("not a draft", plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)  # type: ignore

    def test_non_editorial_plan_raises(self):
        draft = _make_first_draft()
        with pytest.raises(DraftValidationError, match="plan must be"):
            validate_draft(draft, plan="not a plan", segments=_KNOWN_SEGMENTS, is_follow_up=False)  # type: ignore

    def test_empty_segments_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        with pytest.raises(DraftValidationError, match="non-empty"):
            validate_draft(draft, plan=plan, segments=[], is_follow_up=False)

    def test_too_few_sections(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections = draft.sections[:1]
        with pytest.raises(DraftValidationError, match="between 2 and 4"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_too_many_sections(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections = [
            EditionSection(
                section_id=f"sec{i}",
                title=f"S{i}",
                paragraphs=["P1"],
                source_segment_ids=["s001"],
            )
            for i in range(5)
        ]
        with pytest.raises(DraftValidationError, match="between 2 and 4"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_missing_provenance_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.provenance_note = ""
        with pytest.raises(DraftValidationError, match="provenance_note"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_duplicate_section_id(self):
        plan = _make_first_plan()
        plan.sections = [
            EditorialPlanSection(
                section_id="dup",
                working_title="A",
                purpose="p",
                source_segment_ids=["s001"],
            ),
            EditorialPlanSection(
                section_id="section-2",
                working_title="B",
                purpose="p",
                source_segment_ids=["s002"],
            ),
        ]
        draft = _make_first_draft()
        draft.sections = [
            EditionSection(
                section_id="dup",
                title="Dup",
                paragraphs=["P1"],
                source_segment_ids=["s001"],
            ),
            EditionSection(
                section_id="dup",
                title="Dup2",
                paragraphs=["P2"],
                source_segment_ids=["s002"],
            ),
        ]
        with pytest.raises(DraftValidationError, match="duplicate section_id"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_draft_section_not_in_plan(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections[0].section_id = "unknown-section"
        with pytest.raises(DraftValidationError, match="not in the accepted plan"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_missing_plan_section_in_draft(self):
        plan = _make_first_plan()
        plan.sections = [
            EditorialPlanSection(
                section_id="section-1",
                working_title="S1",
                purpose="p",
                source_segment_ids=["s001"],
            ),
            EditorialPlanSection(
                section_id="section-2",
                working_title="S2",
                purpose="p",
                source_segment_ids=["s002"],
            ),
            EditorialPlanSection(
                section_id="section-3",
                working_title="S3",
                purpose="p",
                source_segment_ids=["s001"],
            ),
        ]
        draft = _make_first_draft()
        draft.sections = [
            EditionSection(
                section_id="section-1",
                title="S1",
                paragraphs=["P1"],
                source_segment_ids=["s001"],
            ),
            EditionSection(
                section_id="section-2",
                title="S2",
                paragraphs=["P1"],
                source_segment_ids=["s002"],
            ),
        ]
        with pytest.raises(DraftValidationError, match="missing plan sections"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_unknown_segment_reference(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections[0].source_segment_ids = ["s999"]
        with pytest.raises(DraftValidationError, match="unknown segment"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_empty_source_segment_ids(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections[0].source_segment_ids = []
        with pytest.raises(DraftValidationError, match="references no segments"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_exceeds_paragraph_limit(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections[0].paragraphs = ["P1", "P2", "P3", "P4", "P5"]
        with pytest.raises(DraftValidationError, match="paragraph limit"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_oversized_paragraph(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.sections[0].paragraphs = ["x" * 1500]
        with pytest.raises(DraftValidationError, match="oversized paragraph"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_opening_too_short(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.opening = "Short."
        with pytest.raises(DraftValidationError, match="too short"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_first_edition_with_continuity_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.continuity_note = "This continues from a prior edition"
        with pytest.raises(DraftValidationError, match="must not claim"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_first_edition_with_applied_feedback_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.applied_feedback = AppliedFeedback(
            feedback_id="fb1",
            action="expanded",
            affected_section_ids=["section-1"],
            evidence="evidence",
        )
        with pytest.raises(DraftValidationError, match="must not claim"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_valid_follow_up_draft(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.continuity_note = "Continuing from edition 1."
        draft.applied_feedback = AppliedFeedback(
            feedback_id="fb1",
            action="Expanded section 1",
            affected_section_ids=["section-1"],
            evidence="Section 1 now has more depth.",
        )
        validate_draft(
            draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=True,
            feedback_id="fb1",
        )

    def test_follow_up_missing_applied_feedback_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.continuity_note = "Continuing."
        with pytest.raises(DraftValidationError, match="must contain"):
            validate_draft(
                draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=True,
                feedback_id="fb1",
            )

    def test_follow_up_mismatched_feedback_id_raises(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.continuity_note = "Continuing."
        draft.applied_feedback = AppliedFeedback(
            feedback_id="fb2",
            action="expanded",
            affected_section_ids=["section-1"],
            evidence="evidence",
        )
        with pytest.raises(DraftValidationError, match="mismatched"):
            validate_draft(
                draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=True,
                feedback_id="fb1",
            )

    def test_applied_feedback_unknown_affected_section(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.continuity_note = "Continuing."
        draft.applied_feedback = AppliedFeedback(
            feedback_id="fb1",
            action="expanded",
            affected_section_ids=["nonexistent-section"],
            evidence="evidence",
        )
        with pytest.raises(DraftValidationError, match="unknown affected"):
            validate_draft(
                draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=True,
                feedback_id="fb1",
            )

    def test_publication_title_too_long(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.publication_title = "x" * 81
        with pytest.raises(DraftValidationError, match="exceeds"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_deck_too_long(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        draft.deck = "x" * 181
        with pytest.raises(DraftValidationError, match="exceeds"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)

    def test_next_edition_prompt_question_too_long(self):
        plan = _make_first_plan()
        draft = _make_first_draft()
        from pydantic import BaseModel
        draft.next_edition_prompt = NextEditionPrompt.model_construct(question="x" * 201)
        with pytest.raises(DraftValidationError, match="exceeds"):
            validate_draft(draft, plan=plan, segments=_KNOWN_SEGMENTS, is_follow_up=False)


class TestCollectVisibleFields:
    def test_returns_expected_fields(self):
        draft = _make_first_draft()
        fields = collect_visible_fields(draft)
        assert "publication_title" in fields
        assert "edition_title" in fields
        assert "deck" in fields
        assert "opening" in fields
        assert "highlighted_insight" in fields
        assert "provenance_note" in fields
        assert "section.section-1.title" in fields
        assert "section.section-1.paragraphs" in fields
        assert "section.section-2.title" in fields
        assert "section.section-2.paragraphs" in fields

    def test_continuity_note_included_when_set(self):
        draft = _make_first_draft()
        draft.continuity_note = "Continuing."
        fields = collect_visible_fields(draft)
        assert fields.get("continuity_note") == "Continuing."

    def test_applied_feedback_included_when_set(self):
        draft = _make_first_draft()
        draft.applied_feedback = AppliedFeedback(
            feedback_id="fb1",
            action="expanded",
            affected_section_ids=["section-1"],
            evidence="evidence text",
        )
        fields = collect_visible_fields(draft)
        assert fields.get("applied_feedback.action") == "expanded"
        assert fields.get("applied_feedback.evidence") == "evidence text"

    def test_next_edition_prompt_included(self):
        draft = _make_first_draft()
        draft.next_edition_prompt = NextEditionPrompt(
            question="What do you think?",
            choices=["Yes", "No"],
        )
        fields = collect_visible_fields(draft)
        assert "next_edition_prompt.question" in fields
        assert "next_edition_prompt.choices" in fields

    def test_paragraphs_joined_with_newline(self):
        draft = _make_first_draft()
        draft.sections[0].paragraphs = ["Para one", "Para two"]
        fields = collect_visible_fields(draft)
        assert "\n" in fields["section.section-1.paragraphs"]
