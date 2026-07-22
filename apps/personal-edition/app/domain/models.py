from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.enums import (
    CostClass,
    FeedbackDirection,
    Language,
    ProviderErrorCategory,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
QuestionStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ParticipantPreferences(BaseModel):
    tone: str = "calm_editorial"
    length: str = "standard"
    practicality: float = Field(default=0.5, ge=0.0, le=1.0)
    reflection: float = Field(default=0.5, ge=0.0, le=1.0)
    excluded_topics: list[str] = Field(default_factory=list)


class InputSegment(BaseModel):
    segment_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    @model_validator(mode="after")
    def check_offsets(self):
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        return self


class EditionInput(BaseModel):
    participant_id: str
    input_id: str
    language: Language
    raw_text: str = Field(min_length=1)
    submitted_at: datetime
    consent_confirmed: bool = Field(..., strict=True)

    @field_validator("consent_confirmed")
    @classmethod
    def consent_must_be_true(cls, v):
        if v is not True:
            raise ValueError("consent_confirmed must be True")
        return v


class FeedbackInput(BaseModel):
    edition_id: str
    direction: list[FeedbackDirection] = Field(min_length=1)
    selected_section_id: str | None = None
    free_text: str | None = Field(default=None, max_length=2000)
    tone_override: str | None = None
    length_override: str | None = None
    submitted_at: datetime


class AppliedFeedback(BaseModel):
    feedback_id: str
    action: str = Field(min_length=1)
    affected_section_ids: list[NonEmptyStr] = Field(min_length=1)
    evidence: str = Field(min_length=1)


class EditorialPlanSection(BaseModel):
    section_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    working_title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    source_segment_ids: list[NonEmptyStr] = Field(min_length=1)
    allowed_interpretations: list[str] = Field(default_factory=list)
    prohibited_inferences: list[str] = Field(default_factory=list)
    feedback_action: str | None = None


class EditorialPlan(BaseModel):
    plan_version: str
    language: Language
    central_theme: str = Field(min_length=1)
    reader_value: str = Field(min_length=1)
    opening_intent: str = Field(min_length=1)
    sections: list[EditorialPlanSection] = Field(min_length=2, max_length=4)
    continuity: dict = Field(default_factory=dict)
    uncertain_or_excluded_material: list[str] = Field(default_factory=list)
    highlighted_insight: str = Field(min_length=1)
    next_edition_prompt: str | None = None

    @model_validator(mode="after")
    def check_unique_section_ids(self):
        ids = [s.section_id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section_id values must be unique")
        return self


class EditionSection(BaseModel):
    section_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1)
    paragraphs: list[NonEmptyStr] = Field(min_length=1)
    source_segment_ids: list[NonEmptyStr] = Field(min_length=1)
    contains_interpretation: bool = False


class NextEditionPrompt(BaseModel):
    question: QuestionStr
    choices: list[str] = Field(default_factory=list)


class EditionContent(BaseModel):
    content_version: str
    language: Language
    publication_title: str
    edition_title: str
    deck: str
    opening: str = Field(min_length=1)
    sections: list[EditionSection] = Field(min_length=2, max_length=4)
    highlighted_insight: str = Field(min_length=1)
    continuity_note: str | None = None
    applied_feedback: AppliedFeedback | None = None
    next_edition_prompt: NextEditionPrompt | None = None
    provenance_note: NonEmptyStr = (
        "This edition was created from material supplied by the reader."
    )

    @model_validator(mode="after")
    def check_unique_section_ids(self):
        ids = [s.section_id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section_id values must be unique")
        return self


class ProviderUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(BaseModel):
    provider: str
    advertised_model: str
    cost_class: CostClass = CostClass.FREE
    latency_seconds: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    payload: dict | None = None
    request_id: str | None = None
    error_category: ProviderErrorCategory | None = None
    error_message: str | None = None
    success: bool = False
