"""Unit tests for Living Travel domain models."""

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    InformationClass,
    SourceConfidence,
    TripContext,
    FeedbackDirection,
    CostClass,
    ProviderErrorCategory,
    PilotEvidenceType,
)
from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
    FeedbackInput,
    InformationItem,
    PilotEvidence,
    ProviderResult,
    SourceItem,
    TravelerProfile,
)


class TestTravelerProfile:
    def test_valid_profile(self):
        p = TravelerProfile(destination="부산")
        assert p.destination == "부산"
        assert p.trip_duration_nights == 2
        assert p.trip_context == TripContext.solo

    def test_empty_destination_rejected(self):
        with pytest.raises(ValidationError):
            TravelerProfile(destination="")

    def test_trip_duration_bounds(self):
        p = TravelerProfile(destination="부산", trip_duration_nights=1)
        assert p.trip_duration_nights == 1
        with pytest.raises(ValidationError):
            TravelerProfile(destination="부산", trip_duration_nights=0)
        with pytest.raises(ValidationError):
            TravelerProfile(destination="부산", trip_duration_nights=31)


class TestInformationItem:
    def test_inspiration_no_date_needed(self):
        item = InformationItem(
            item_id="i1", information_class=InformationClass.inspiration
        )
        assert item.verify_before_use is False

    def test_time_sensitive_defaults(self):
        item = InformationItem(
            item_id="i1",
            information_class=InformationClass.time_sensitive,
            as_of_date="2026-07-20",
            source_ref="src1",
            confidence=SourceConfidence.approximate,
            verify_before_use=True,
        )
        assert item.as_of_date == "2026-07-20"
        assert item.verify_before_use is True


class TestEditionContent:
    def test_valid_content(self):
        c = EditionContent(
            publication_title="테스트",
            edition_title="테스트 에디션",
            destination="부산",
            trip_frame="2박",
            editorial_opening="테스트",
        )
        assert c.publication_title == "테스트"

    def test_duplicate_section_ids_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate section IDs"):
            EditionContent(
                publication_title="테스트",
                edition_title="테스트",
                destination="부산",
                trip_frame="2박",
                editorial_opening="테스트",
                sections=[
                    EditionSection(section_id="s1", title="A", narrative="a"),
                    EditionSection(section_id="s1", title="B", narrative="b"),
                ],
            )


class TestEditorialPlan:
    def test_valid_plan(self):
        plan = EditorialPlan(
            central_theme="부산 동네 산책",
            sections=[
                EditorialPlanSection(
                    section_id="s1", title="아침", description="조용한 아침"
                )
            ],
        )
        assert plan.central_theme == "부산 동네 산책"


class TestProviderResult:
    def test_success_result(self):
        r = ProviderResult(provider="mock", model="mock-fixture", success=True)
        assert r.success is True
        assert r.cost_class == CostClass.free

    def test_error_result(self):
        r = ProviderResult(
            provider="mock",
            model="mock-error",
            success=False,
            error_category=ProviderErrorCategory.provider_error,
            error_message="fail",
        )
        assert r.success is False


class TestSourceItem:
    def test_valid_source(self):
        s = SourceItem(
            source_id="s1",
            source_url="https://example.com",
            publisher="테스트",
            source_type="tourism_authority",
            destination="부산",
            category="overview",
        )
        assert s.source_id == "s1"
        assert s.confidence == SourceConfidence.approximate


class TestFeedbackInput:
    def test_valid_feedback(self):
        f = FeedbackInput(
            edition_id="ed1",
            direction=[FeedbackDirection.quieter_places, FeedbackDirection.slower_pace],
        )
        assert len(f.direction) == 2


class TestPilotEvidence:
    def test_free_sample(self):
        pe = PilotEvidence(
            evidence_type=PilotEvidenceType.free_sample,
            traveler_id="t1",
            edition_id="e1",
            offer_description="무료 샘플",
        )
        assert pe.price_krw == 0
        assert pe.evidence_type == PilotEvidenceType.free_sample

    def test_paid_edition(self):
        pe = PilotEvidence(
            evidence_type=PilotEvidenceType.paid_edition,
            traveler_id="t1",
            edition_id="e1",
            offer_description="3회 에디션",
            price_krw=4900,
        )
        assert pe.price_krw == 4900
