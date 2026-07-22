"""Domain models for Living Travel."""

from __future__ import annotations

from typing import Annotated
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.domain.enums import (
    CostClass,
    FeedbackDirection,
    InformationClass,
    PilotEvidenceType,
    ProviderErrorCategory,
    SourceConfidence,
    TripContext,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TravelerProfile(BaseModel):
    destination: NonEmptyStr
    trip_duration_nights: int = Field(ge=1, le=30, default=2)
    trip_context: TripContext = TripContext.solo
    budget_tendency: str = "moderate"
    pace_preference: str = "comfortable"
    interests: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    tone_preference: str = "calm"
    length_preference: str = "medium"


class SourceItem(BaseModel):
    source_id: NonEmptyStr
    source_url: NonEmptyStr
    publisher: NonEmptyStr
    source_type: NonEmptyStr
    original_language: str = "ko"
    publication_date: str = ""
    access_date: str = ""
    destination: NonEmptyStr
    locality: str = ""
    category: NonEmptyStr
    claims: list[str] = Field(default_factory=list)
    confidence: SourceConfidence = SourceConfidence.approximate
    state: str = "single_source"
    verification_notes: str = ""


class EditionTravelInput(BaseModel):
    traveler_id: NonEmptyStr
    raw_text: NonEmptyStr
    destination: NonEmptyStr
    trip_duration_nights: int = Field(ge=1, le=30, default=2)
    consent_confirmed: bool


class InformationItem(BaseModel):
    item_id: NonEmptyStr
    information_class: InformationClass
    as_of_date: str = ""
    source_ref: str = ""
    confidence: SourceConfidence = SourceConfidence.approximate
    verify_before_use: bool = False


class EditionSection(BaseModel):
    section_id: NonEmptyStr
    title: NonEmptyStr
    narrative: NonEmptyStr
    items: list[InformationItem] = Field(default_factory=list)


class AppliedFeedback(BaseModel):
    feedback_id: NonEmptyStr
    requested_change: NonEmptyStr
    actual_action: NonEmptyStr
    affected_section_ids: list[str] = Field(default_factory=list)
    evidence: str = ""
    unfulfilled_reason: str = ""


class EditionContent(BaseModel):
    content_version: str = "1.0"
    publication_title: NonEmptyStr
    edition_title: NonEmptyStr
    destination: NonEmptyStr
    trip_frame: NonEmptyStr
    editorial_opening: NonEmptyStr
    sections: list[EditionSection] = Field(default_factory=list)
    applied_feedback: list[AppliedFeedback] = Field(default_factory=list)
    next_edition_prompt: str = ""
    provenance_note: str = ""

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, v: list[EditionSection]) -> list[EditionSection]:
        ids = [s.section_id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate section IDs")
        return v


class EditorialPlan(BaseModel):
    plan_version: str = "1.0"
    language: str = "ko"
    central_theme: NonEmptyStr
    sections: list[EditorialPlanSection] = Field(default_factory=list)
    continuity: str = ""
    highlighted_insight: str = ""


class EditorialPlanSection(BaseModel):
    section_id: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    emphasis: str = ""


class FeedbackInput(BaseModel):
    edition_id: NonEmptyStr
    direction: list[FeedbackDirection] = Field(default_factory=list)
    selected_section_id: str = ""
    free_text: str = ""


class ProviderResult(BaseModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    cost_class: CostClass = CostClass.free
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    payload: dict = Field(default_factory=dict)
    success: bool = True
    error_category: ProviderErrorCategory | None = None
    error_message: str = ""


class PilotEvidence(BaseModel):
    evidence_type: PilotEvidenceType
    traveler_id: NonEmptyStr
    edition_id: NonEmptyStr
    offer_description: NonEmptyStr
    price_krw: int = 0
    consent_recorded: bool = False
    payment_evidence: str = ""
