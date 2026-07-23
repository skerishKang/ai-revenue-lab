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
    snapshot_recorded: bool
    initial_difficulty: str


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


class ReviewActionRequest(BaseModel):
    note: str = Field(default="", max_length=MAX_FREE_TEXT)


class ReviewActionResponse(BaseModel):
    lesson_id: str
    generation_status: str
