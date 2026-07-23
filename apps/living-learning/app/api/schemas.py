"""Pydantic request/response schemas for the /api/v1 boundary.

All free-text and list fields are bounded so payload size is constrained at the
schema layer (no separate body-size middleware is required). Responses use
explicit field allowlists — never raw object dumps or raw HTML.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_SHORT_TEXT = 200
MAX_FREE_TEXT = 2000
MAX_LIST_ITEMS = 20

VALID_DIRECTIONS = {
    "reduce_theory",
    "more_examples",
    "code_first",
    "slower_pace",
    "more_review",
    "simplify_jargon",
}


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    database_backend: str
    identity_provider: str
    ai_provider: str
    ai_model: str
    portal_contract_version: str


class MeResponse(BaseModel):
    provider: str
    role: str
    learner_id: str | None
    revoked: bool


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------
class GoalRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=MAX_SHORT_TEXT)


class GoalResponse(BaseModel):
    learner_id: str
    goal_id: str
    goal: str
    recorded: bool


class DiagnosticRequest(BaseModel):
    coding_experience: str = Field(default="none", max_length=MAX_SHORT_TEXT)
    explanation_preference: str = Field(default="balanced", max_length=MAX_SHORT_TEXT)
    daily_minutes: int = Field(default=10, ge=5, le=60)
    theory_practice_balance: str = Field(default="balanced", max_length=MAX_SHORT_TEXT)
    confidence: str = Field(default="low", max_length=MAX_SHORT_TEXT)


class DiagnosticResponse(BaseModel):
    learner_id: str
    snapshot_id: str
    snapshot_recorded: bool
    derived_difficulty: str


class LearningHomeResponse(BaseModel):
    learner_id: str
    topic: str
    total_lessons: int
    pending_review_lessons: int
    next_recommendation: str


class LessonResponse(BaseModel):
    lesson_id: str
    learner_id: str
    concept_id: str
    lesson_number: int
    generation_status: str
    adaptation_summary: str


class LessonResponseRequest(BaseModel):
    understood: bool = True
    difficulty_rating: int = Field(default=3, ge=1, le=5)
    free_text: str = Field(default="", max_length=MAX_FREE_TEXT)
    idempotency_key: str = Field(default="", max_length=MAX_SHORT_TEXT)


class LessonResponseResult(BaseModel):
    response_id: str
    recorded: bool


class LessonFeedbackRequest(BaseModel):
    direction_choices: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    free_text: str = Field(default="", max_length=MAX_FREE_TEXT)
    idempotency_key: str = Field(default="", max_length=MAX_SHORT_TEXT)


class LessonFeedbackResult(BaseModel):
    feedback_id: str
    is_duplicate: bool


class AdaptationDecisionView(BaseModel):
    dimension: str
    before_value: str
    after_value: str
    reason: str
    signal_type: str


class AdaptationsResponse(BaseModel):
    lesson_id: str
    decisions: list[AdaptationDecisionView]


class ProgressResponse(BaseModel):
    learner_id: str
    topic: str
    total_lessons: int
    total_feedback: int
    pending_review_lessons: int


# ---------------------------------------------------------------------------
# Operator review
# ---------------------------------------------------------------------------
class ReviewListItem(BaseModel):
    lesson_id: str
    learner_id: str
    concept_id: str
    lesson_number: int
    generation_status: str


class ReviewListResponse(BaseModel):
    pending: list[ReviewListItem]


class ReviewDetailResponse(BaseModel):
    lesson_id: str
    learner_id: str
    concept_id: str
    lesson_number: int
    generation_status: str
    adaptation_summary: str


# ---------------------------------------------------------------------------
# Operator review detail: full structured payload for human review.
# Includes expected answers/rationale and validation internals (operator-only;
# never exposed on learner-facing routes).
# ---------------------------------------------------------------------------
class OperatorSectionView(BaseModel):
    section_id: str
    title: str
    content: str
    includes_code: bool = False
    code_snippet: str = ""


class OperatorCodeExampleView(BaseModel):
    example_id: str
    language: str
    code: str
    expected_output: str
    explanation: str


class OperatorTermView(BaseModel):
    term: str
    definition: str


class OperatorReviewQuestionView(BaseModel):
    question: str
    correct_answer: str
    explanation: str


class InstructionalPlanView(BaseModel):
    objective: str
    section_order: list[str]
    difficulty: str
    example_count: int
    review_question_count: int
    feedback_actions: list[str]


class OperatorLessonContentView(BaseModel):
    sections: list[OperatorSectionView]
    code_examples: list[OperatorCodeExampleView]
    term_definitions: list[OperatorTermView]
    review_questions: list[OperatorReviewQuestionView]


class AdaptationMaterialChangeView(BaseModel):
    dimension: str
    before_value: str
    after_value: str
    reason: str


class FeedbackSignalView(BaseModel):
    feedback_id: str
    direction_choices: list[str]
    free_text: str
    lesson_generation: int


class ComprehensionSignalView(BaseModel):
    response_id: str
    understood: bool
    difficulty_rating: int
    free_text: str


class AdaptationView(BaseModel):
    prior_lesson_id: str | None
    feedback_signal: FeedbackSignalView | None
    comprehension_signal: ComprehensionSignalView | None
    material_changes: list[AdaptationMaterialChangeView]


class ValidationReportView(BaseModel):
    lesson_plan_schema: str
    content_schema: str
    ast_safety: str
    answer_grounding: str
    adaptation_materiality: str
    privacy_markup: str
    lineage_integrity: str
    publishable: bool


class TaskAccountingView(BaseModel):
    task_type: str
    provider: str
    model: str
    provider_call_count: int
    retry_count: int
    latency_ms_total: float
    input_tokens_total: int | None
    output_tokens_total: int | None
    final_validation_result: str


class GenerationEvidenceView(BaseModel):
    provider_call_count: int
    retry_count: int
    latency_ms_total: float
    input_tokens_total: int | None
    output_tokens_total: int | None
    tasks: list[TaskAccountingView]


class OperatorReviewDetailResponse(BaseModel):
    lesson_id: str
    learner_id: str
    concept_id: str
    lesson_number: int
    generation_status: str
    publication_state: str
    source_diagnostic_snapshot_id: str | None
    source_feedback_id: str | None
    source_comprehension_response_id: str | None
    instructional_plan: InstructionalPlanView
    lesson_content: OperatorLessonContentView
    adaptation: AdaptationView
    validation: ValidationReportView
    generation_evidence: GenerationEvidenceView


class ReviewActionRequest(BaseModel):
    reason: str = Field(default="", max_length=MAX_FREE_TEXT)


class ReviewActionResponse(BaseModel):
    lesson_id: str
    publication_state: str


# ---------------------------------------------------------------------------
# Published lesson delivery (validated structure, not raw JSON)
# ---------------------------------------------------------------------------
class SectionView(BaseModel):
    section_id: str
    title: str
    content: str
    includes_code: bool = False


class CodeExampleView(BaseModel):
    example_id: str
    language: str
    code: str
    explanation: str


class TermDefinitionView(BaseModel):
    term: str
    definition: str


class ExerciseView(BaseModel):
    exercise_id: str
    question: str
    difficulty: str


class PublishedLessonResponse(BaseModel):
    lesson_id: str
    lesson_number: int
    objective: str
    sections: list[SectionView]
    code_examples: list[CodeExampleView]
    term_definitions: list[TermDefinitionView]
    exercises: list[ExerciseView]
    adaptation_note: str


# ---------------------------------------------------------------------------
# Operator-driven generation (review-before-delivery)
# ---------------------------------------------------------------------------
class OperatorGenerateFirstRequest(BaseModel):
    concept_id: str = Field(default="", max_length=MAX_SHORT_TEXT)
    idempotency_key: str = Field(default="", max_length=MAX_SHORT_TEXT)


class OperatorGenerateNextRequest(BaseModel):
    comprehension_response_id: str = Field(min_length=1, max_length=MAX_SHORT_TEXT)
    feedback_id: str = Field(min_length=1, max_length=MAX_SHORT_TEXT)
    idempotency_key: str = Field(default="", max_length=MAX_SHORT_TEXT)


class OperatorGenerateResponse(BaseModel):
    lesson_id: str
    generation_status: str
    publication_state: str
