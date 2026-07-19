from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.enums import FeedbackDirection
from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditionInput,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
    FeedbackInput,
    InputSegment,
    NextEditionPrompt,
    ParticipantPreferences,
    ProviderResult,
    ProviderUsage,
)


class TestParticipantPreferences:
    def test_defaults(self):
        p = ParticipantPreferences()
        assert p.tone == "calm_editorial"
        assert p.length == "standard"
        assert p.practicality == 0.5
        assert p.reflection == 0.5
        assert p.excluded_topics == []

    def test_practicality_bounds(self):
        with pytest.raises(ValidationError):
            ParticipantPreferences(practicality=-0.1)
        with pytest.raises(ValidationError):
            ParticipantPreferences(practicality=1.1)


class TestInputSegment:
    def test_valid(self):
        seg = InputSegment(
            segment_id="s001",
            text="some text",
            start_offset=0,
            end_offset=9,
        )
        assert seg.segment_id == "s001"

    def test_empty_segment_id(self):
        with pytest.raises(ValidationError):
            InputSegment(
                segment_id="",
                text="text",
                start_offset=0,
                end_offset=4,
            )

    def test_offset_reversed(self):
        with pytest.raises(ValueError):
            InputSegment(
                segment_id="s001",
                text="text",
                start_offset=10,
                end_offset=5,
            )


class TestEditionInput:
    def test_consent_required(self):
        with pytest.raises(ValidationError):
            EditionInput(
                participant_id="p1",
                input_id="i1",
                language="ko",
                raw_text="hello",
                submitted_at=datetime.now(timezone.utc),
                consent_confirmed=False,
            )

    def test_valid_with_consent(self):
        inp = EditionInput(
            participant_id="p1",
            input_id="i1",
            language="en",
            raw_text="hello world",
            submitted_at=datetime.now(timezone.utc),
            consent_confirmed=True,
        )
        assert inp.language == "en"


class TestInputSegmentUnique:
    def test_duplicate_ids(self):
        with pytest.raises(ValidationError):
            EditorialPlan(
                plan_version="v1",
                language="ko",
                central_theme="theme",
                reader_value="value",
                opening_intent="intro",
                sections=[
                    EditorialPlanSection(
                        section_id="s1",
                        working_title="A",
                        purpose="purpose",
                        source_segment_ids=["seg1"],
                    ),
                    EditorialPlanSection(
                        section_id="s1",
                        working_title="B",
                        purpose="purpose",
                        source_segment_ids=["seg2"],
                    ),
                ],
                highlighted_insight="insight",
            )


class TestEditorialPlan:
    def test_valid_plan(self):
        plan = EditorialPlan(
            plan_version="v1",
            language="ko",
            central_theme="theme",
            reader_value="value",
            opening_intent="intro",
            sections=[
                EditorialPlanSection(
                    section_id="s1",
                    working_title="Section 1",
                    purpose="purpose",
                    source_segment_ids=["seg1"],
                ),
                EditorialPlanSection(
                    section_id="s2",
                    working_title="Section 2",
                    purpose="purpose",
                    source_segment_ids=["seg2"],
                ),
            ],
            highlighted_insight="key insight",
        )
        assert len(plan.sections) == 2

    def test_too_few_sections(self):
        with pytest.raises(ValidationError):
            EditorialPlan(
                plan_version="v1",
                language="ko",
                central_theme="theme",
                reader_value="value",
                opening_intent="intro",
                sections=[
                    EditorialPlanSection(
                        section_id="s1",
                        working_title="A",
                        purpose="purpose",
                        source_segment_ids=["seg1"],
                    ),
                ],
                highlighted_insight="insight",
            )

    def test_too_many_sections(self):
        with pytest.raises(ValidationError):
            EditorialPlan(
                plan_version="v1",
                language="ko",
                central_theme="theme",
                reader_value="value",
                opening_intent="intro",
                sections=[
                    EditorialPlanSection(
                        section_id=f"s{i}",
                        working_title=f"Section {i}",
                        purpose="purpose",
                        source_segment_ids=[f"seg{i}"],
                    )
                    for i in range(5)
                ],
                highlighted_insight="insight",
            )

    def test_empty_source_segment_refs(self):
        with pytest.raises(ValidationError):
            EditorialPlanSection(
                section_id="s1",
                working_title="A",
                purpose="purpose",
                source_segment_ids=[],
            )


class TestFeedbackInput:
    def test_unknown_direction(self):
        with pytest.raises(ValidationError):
            FeedbackInput(
                edition_id="e1",
                direction=["invalid_direction"],
                submitted_at=datetime.now(timezone.utc),
            )

    def test_valid_direction(self):
        fb = FeedbackInput(
            edition_id="e1",
            direction=[FeedbackDirection.MORE_REFLECTIVE],
            submitted_at=datetime.now(timezone.utc),
        )
        assert FeedbackDirection.MORE_REFLECTIVE in fb.direction


class TestEditionContent:
    def test_valid_content(self):
        content = EditionContent(
            content_version="v1",
            language="ko",
            publication_title="My Letter",
            edition_title="Edition 1",
            deck="A deck",
            opening="Opening paragraph.",
            sections=[
                EditionSection(
                    section_id="sec1",
                    title="First Section",
                    paragraphs=["Para one.", "Para two."],
                    source_segment_ids=["s001"],
                ),
                EditionSection(
                    section_id="sec2",
                    title="Second Section",
                    paragraphs=["Para one."],
                    source_segment_ids=["s002"],
                ),
            ],
            highlighted_insight="The insight.",
            provenance_note="This edition was created from material supplied by the reader.",
        )
        assert len(content.sections) == 2
        assert content.provenance_note is not None

    def test_too_few_sections(self):
        with pytest.raises(ValidationError):
            EditionContent(
                content_version="v1",
                language="ko",
                publication_title="T",
                edition_title="E1",
                deck="D",
                opening="O",
                sections=[
                    EditionSection(
                        section_id="sec1",
                        title="S1",
                        paragraphs=["P1"],
                        source_segment_ids=["s001"],
                    ),
                ],
                highlighted_insight="I",
            )

    def test_duplicate_section_ids(self):
        with pytest.raises(ValidationError):
            EditionContent(
                content_version="v1",
                language="ko",
                publication_title="T",
                edition_title="E1",
                deck="D",
                opening="O",
                sections=[
                    EditionSection(
                        section_id="dup",
                        title="S1",
                        paragraphs=["P1"],
                        source_segment_ids=["s001"],
                    ),
                    EditionSection(
                        section_id="dup",
                        title="S2",
                        paragraphs=["P2"],
                        source_segment_ids=["s002"],
                    ),
                ],
                highlighted_insight="I",
            )

    def test_nonempty_source_references(self):
        with pytest.raises(ValidationError):
            EditionSection(
                section_id="sec1",
                title="S1",
                paragraphs=["P1"],
                source_segment_ids=[],
            )

    def test_empty_paragraphs(self):
        with pytest.raises(ValidationError):
            EditionSection(
                section_id="sec1",
                title="S1",
                paragraphs=[],
                source_segment_ids=["s001"],
            )


class TestProviderMetrics:
    def test_negative_retry(self):
        with pytest.raises(ValidationError):
            ProviderResult(
                provider="mock",
                advertised_model="m",
                retry_count=-1,
            )

    def test_negative_latency(self):
        with pytest.raises(ValidationError):
            ProviderResult(
                provider="mock",
                advertised_model="m",
                latency_seconds=-0.5,
            )

    def test_negative_tokens(self):
        with pytest.raises(ValidationError):
            ProviderUsage(input_tokens=-1)

    def test_valid_usage(self):
        usage = ProviderUsage(input_tokens=10, output_tokens=20, total_tokens=30)
        assert usage.total_tokens == 30


class TestAppliedFeedback:
    def test_valid(self):
        af = AppliedFeedback(
            feedback_id="fb1",
            action="Expanded section on X",
            affected_section_ids=["s1"],
            evidence="Section now contains new analysis.",
        )
        assert af.feedback_id == "fb1"

    def test_empty_action(self):
        with pytest.raises(ValidationError):
            AppliedFeedback(
                feedback_id="fb1",
                action="",
                affected_section_ids=["s1"],
                evidence="Evidence",
            )

    def test_empty_affected_sections(self):
        with pytest.raises(ValidationError):
            AppliedFeedback(
                feedback_id="fb1",
                action="Action",
                affected_section_ids=[],
                evidence="Evidence",
            )


class TestNextEditionPrompt:
    def test_max_length(self):
        with pytest.raises(ValidationError):
            NextEditionPrompt(question="x" * 201)
