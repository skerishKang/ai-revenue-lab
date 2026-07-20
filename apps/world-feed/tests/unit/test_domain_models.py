import pytest
from pydantic import ValidationError

from app.domain.enums import Category, Language, SourceState, SourceTier
from app.domain.models import (
    BriefContent,
    BriefItem,
    FeedbackInput,
    ReaderProfileInput,
    SourceCard,
)


def _base_card(**overrides):
    data = dict(
        source_id="src-1",
        country="Vietnam",
        locality="Hanoi",
        original_language=Language.KO,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        publisher_name="Pub",
        organization_type="tourism_authority",
        canonical_url="https://example.invalid/x",
        publication_timestamp="2026-01-01T00:00:00Z",
        access_timestamp="2026-01-02T00:00:00Z",
        title="Title",
        text_extract="Extract",
        category=Category.PLACE_CULTURE,
        media_rights_state="clear",
        source_state=SourceState.SINGLE_SOURCE,
        canonical_key="ev-1",
        checksum="cs-1",
        synthetic_flag=True,
    )
    data.update(overrides)
    return SourceCard(**data)


class TestSourceCardValidation:
    def test_accepts_valid_synthetic_card(self):
        card = _base_card()
        assert card.source_id == "src-1"
        assert card.synthetic_flag is True

    def test_rejects_unsafe_markup_in_title(self):
        with pytest.raises(ValidationError):
            _base_card(title="<script>alert(1)</script>")

    def test_rejects_unsafe_markup_in_extract(self):
        with pytest.raises(ValidationError):
            _base_card(text_extract="<img src=x onerror=alert(1)>")

    def test_rejects_malformed_publication_timestamp(self):
        with pytest.raises(ValidationError):
            _base_card(publication_timestamp="2026-01-01")

    def test_rejects_non_synthetic(self):
        with pytest.raises(ValidationError):
            _base_card(synthetic_flag=False)

    def test_rejects_unknown_source_tier(self):
        with pytest.raises(ValidationError):
            _base_card(source_tier="dark_web")

    def test_rejects_invalid_source_id_pattern(self):
        with pytest.raises(ValidationError):
            _base_card(source_id="bad id!")


class TestBriefContent:
    def test_rejects_duplicate_event_citation(self):
        with pytest.raises(ValidationError):
            BriefContent(
                brief_title="t",
                deck="d",
                items=[
                    BriefItem(
                        event_id="e1",
                        headline="h",
                        explanation="x",
                        source_ids=["s"],
                    ),
                    BriefItem(
                        event_id="e1",
                        headline="h2",
                        explanation="y",
                        source_ids=["s"],
                    ),
                ],
            )


class TestFeedbackAndReader:
    def test_feedback_requires_idempotency_key(self):
        with pytest.raises(ValidationError):
            FeedbackInput(
                feedback_id="f1",
                reader_id="r1",
                idempotency_key="",
                action="increase_culture_neighborhood",
            )

    def test_reader_pattern(self):
        r = ReaderProfileInput(
            reader_id="r1", display_name="R", preferences={"interests": ["place_culture"]}
        )
        assert r.reader_id == "r1"
