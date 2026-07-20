"""Domain models for Living Learning."""

from __future__ import annotations

from typing import Annotated
from pydantic import BaseModel, Field, StringConstraints, field_validator


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SyntheticLearnerProfile(BaseModel):
    learner_id: NonEmptyStr
    display_name: str = "학습자"
    preferred_language: str = "ko"
    topic: NonEmptyStr
    target_duration_minutes: int = Field(ge=5, le=15, default=10)
    pacing_feedback_style: str = "moderate"
    example_preference: str = "code_first"
    theory_density: str = "balanced"
    review_question_count: int = Field(ge=1, le=10, default=3)
    jargon_level: str = "simplified"
    interests: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    status: str = "active"


class LearnerSession(BaseModel):
    session_id: NonEmptyStr
    learner_id: NonEmptyStr
    curriculum_id: NonEmptyStr
    current_lesson_sequence: int = 0
    last_activity_at: str = ""
    created_at: str = ""


class Curriculum(BaseModel):
    curriculum_id: NonEmptyStr
    topic: NonEmptyStr
    version: str = "1.0"
    description: str = ""
    concepts: list[NonEmptyStr] = Field(default_factory=list)


class Concept(BaseModel):
    concept_id: NonEmptyStr
    curriculum_id: NonEmptyStr
    name: NonEmptyStr
    description: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    sequence_order: int = 0


class LessonPlan(BaseModel):
    lesson_id: str = ""
    concept_id: str = ""
    title: NonEmptyStr
    duration_minutes: int = Field(ge=5, le=15, default=10)
    sections: list[LessonPlanSection] = Field(default_factory=list)
    plan_version: str = "1.0"


class LessonPlanSection(BaseModel):
    section_id: NonEmptyStr
    title: NonEmptyStr
    description: str = ""
    emphasis: str = ""


class Lesson(BaseModel):
    lesson_id: NonEmptyStr
    learner_id: NonEmptyStr
    concept_id: NonEmptyStr
    lesson_number: int = 1
    prior_lesson_id: str = ""
    generation_status: str = "input_received"
    publication_state: str = "pending"
    lesson_plan_json: str = "{}"
    lesson_content_json: str = "{}"
    adaptation_summary: str = ""
    created_at: str = ""
    updated_at: str = ""


class LessonContent(BaseModel):
    content_version: str = "1.0"
    title: NonEmptyStr
    sections: list[LessonContentSection] = Field(default_factory=list)
    review_questions: list[str] = Field(default_factory=list)
    code_examples: list[CodeExample] = Field(default_factory=list)
    applied_feedback: list[AppliedFeedbackItem] = Field(default_factory=list)
    adaptation_notes: str = ""

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, v: list[LessonContentSection]) -> list[LessonContentSection]:
        ids = [s.section_id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate section IDs")
        return v


class LessonContentSection(BaseModel):
    section_id: NonEmptyStr
    title: NonEmptyStr
    content: str = ""
    includes_code: bool = False
    code_snippet: str = ""


class CodeExample(BaseModel):
    example_id: NonEmptyStr
    language: str = "python"
    code: NonEmptyStr
    explanation: str = ""
    expected_output: str = ""


class AppliedFeedbackItem(BaseModel):
    feedback_id: NonEmptyStr
    requested_change: NonEmptyStr
    actual_action: str = ""
    evidence: str = ""


class Exercise(BaseModel):
    exercise_id: NonEmptyStr
    lesson_id: NonEmptyStr
    question: NonEmptyStr
    options: list[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = "easy"


class ExerciseResponse(BaseModel):
    response_id: NonEmptyStr
    exercise_id: NonEmptyStr
    learner_id: NonEmptyStr
    selected_answer: str = ""
    is_correct: bool = False
    responded_at: str = ""


class ComprehensionResponse(BaseModel):
    lesson_id: NonEmptyStr
    learner_id: NonEmptyStr
    understood: bool
    difficulty_rating: int = Field(ge=1, le=5, default=3)
    free_text: str = ""
    response_id: str = ""


class Feedback(BaseModel):
    feedback_id: NonEmptyStr
    lesson_id: NonEmptyStr
    learner_id: NonEmptyStr
    lesson_generation: int = 1
    direction: list[str] = Field(default_factory=list)
    applied_status: str = "not_applied"
    free_text: str = ""
    applied_to_lesson_id: str = ""
    created_at: str = ""

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: list[str]) -> list[str]:
        valid_directions = {
            "reduce_theory",
            "more_examples",
            "code_first",
            "slower_pace",
            "more_review",
            "simplify_jargon",
        }
        for d in v:
            if d not in valid_directions:
                raise ValueError(f"Invalid direction: {d}")
        return v


class LearnerMastery(BaseModel):
    mastery_id: NonEmptyStr
    learner_id: NonEmptyStr
    concept_id: NonEmptyStr
    mastery_level: str = "unknown"
    practice_count: int = 0
    correct_count: int = 0
    last_practiced_at: str = ""
    updated_at: str = ""


class AdaptationDecision(BaseModel):
    adaptation_id: NonEmptyStr
    lesson_id: NonEmptyStr
    feedback_id: NonEmptyStr
    original_lesson_plan_json: str = ""
    adapted_lesson_plan_json: str = ""
    adaptation_type: list[str] = Field(default_factory=list)
    applied: bool = False


class GenerationRun(BaseModel):
    run_id: NonEmptyStr
    task_type: NonEmptyStr
    provider: str = "unknown"
    advertised_model: str = ""
    cost_class: str = "free"
    prompt_version: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error_category: str = ""
    error_message: str = ""
    lesson_id: str = ""
    success: bool = True
    created_at: str = ""


class ProviderResult(BaseModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    cost_class: str = "free"
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    payload: dict = Field(default_factory=dict)
    success: bool = True
    error_category: str = ""
    error_message: str = ""


class PilotEvidence(BaseModel):
    evidence_id: NonEmptyStr
    evidence_type: str = "free_sample"
    learner_id: NonEmptyStr
    lesson_id: NonEmptyStr
    offer_description: str = ""
    consent_recorded: bool = False
    created_at: str = ""


class FeedbackRecord(BaseModel):
    feedback_id: NonEmptyStr
    lesson_id: NonEmptyStr
    learner_id: NonEmptyStr
    direction_choices: list[str] = Field(default_factory=list)
    free_text: str = ""
    lesson_generation: int = 1
    applied_status: str = "not_applied"
    applied_to_lesson_id: str = ""
    created_at: str = ""