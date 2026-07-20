"""FastAPI routes for Living Learning."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.ai import MockProvider
from app.ai.base import AIProvider
from app.config import get_settings
from app.db import get_connection
from app.pipeline import (
    LessonPipeline,
    PrerequisiteNotMetError,
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    RetryExhaustedError,
    ContentValidationError,
    AdaptationNotChangedError,
    ComprehensionRequiredError,
)
from app.repositories import (
    get_learner_by_id,
    get_lesson_by_id,
)


router = APIRouter(prefix="/api/v1", tags=["living-learning"])


def get_provider() -> AIProvider:
    return MockProvider()


def get_pipeline(
    request: Request,
    provider: Annotated[AIProvider, Depends(get_provider)],
) -> LessonPipeline:
    settings = request.app.state.settings
    conn = get_connection()
    return LessonPipeline(conn, provider, settings)


class CreateLearnerRequest(BaseModel):
    topic: str = Field(min_length=1)
    display_name: str = "학습자"
    target_duration_minutes: int = Field(default=10, ge=5, le=15)
    example_preference: str = "code_first"
    theory_density: str = "balanced"
    jargon_level: str = "simplified"
    review_question_count: int = Field(default=3, ge=1, le=10)


class CreateLearnerResponse(BaseModel):
    learner_id: str
    session_id: str
    curriculum_id: str


@router.post("/learners", response_model=CreateLearnerResponse)
def create_learner(
    request: CreateLearnerRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> CreateLearnerResponse:
    result = pipeline.create_learner_and_session(
        topic=request.topic,
        display_name=request.display_name,
        target_duration_minutes=request.target_duration_minutes,
        example_preference=request.example_preference,
        theory_density=request.theory_density,
        jargon_level=request.jargon_level,
        review_question_count=request.review_question_count,
    )
    return CreateLearnerResponse(
        learner_id=result["learner_id"],
        session_id=result["session_id"],
        curriculum_id=result["curriculum_id"],
    )


class StartLessonRequest(BaseModel):
    learner_id: str = Field(min_length=1)
    concept_id: str = Field(min_length=1)
    idempotency_key: str = ""


class StartLessonResponse(BaseModel):
    lesson_id: str


@router.post("/lessons", response_model=StartLessonResponse)
def start_lesson(
    request: StartLessonRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> StartLessonResponse:
    try:
        lesson_id = pipeline.start_first_lesson(
            learner_id=request.learner_id,
            concept_id=request.concept_id,
            idempotency_key=request.idempotency_key,
        )
        return StartLessonResponse(lesson_id=lesson_id)
    except PrerequisiteNotMetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "prerequisite_not_met", "missing": exc.missing},
        )
    except RetryExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "task": exc.task_type},
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )
    except ContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "content_validation_failed", "issues": exc.issues},
        )
    except AdaptationNotChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "adaptation_not_changed", "details": exc.details},
        )


class RecordComprehensionRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    understood: bool = True
    difficulty_rating: int = Field(default=3, ge=1, le=5)
    free_text: str = ""


class RecordComprehensionResponse(BaseModel):
    response_id: str
    comprehension_recorded: bool


@router.post("/comprehension", response_model=RecordComprehensionResponse)
def record_comprehension(
    request: RecordComprehensionRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> RecordComprehensionResponse:
    try:
        result = pipeline.record_comprehension(
            lesson_id=request.lesson_id,
            learner_id=request.learner_id,
            understood=request.understood,
            difficulty_rating=request.difficulty_rating,
            free_text=request.free_text,
        )
        return RecordComprehensionResponse(
            response_id=result["response_id"],
            comprehension_recorded=result["success"],
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_resource", "resource": "lesson"},
        )


class SubmitFeedbackRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    direction_choices: list[str] = Field(default_factory=list)
    free_text: str = ""
    idempotency_key: str = ""


class SubmitFeedbackResponse(BaseModel):
    feedback_id: str


@router.post("/feedback", response_model=SubmitFeedbackResponse)
def submit_feedback(
    request: SubmitFeedbackRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> SubmitFeedbackResponse:
    try:
        result = pipeline.record_feedback(
            lesson_id=request.lesson_id,
            learner_id=request.learner_id,
            direction_choices=request.direction_choices,
            free_text=request.free_text,
            idempotency_key=request.idempotency_key,
        )
        return SubmitFeedbackResponse(feedback_id=result["feedback_id"])
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_resource", "resource": "lesson"},
        )


class GenerateSecondLessonRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    comprehension_response_id: str = Field(min_length=1)
    feedback_id: str = Field(min_length=1)
    idempotency_key: str = ""


class GenerateSecondLessonResponse(BaseModel):
    lesson_id: str
    adaptation_verified: bool


@router.post("/lessons/second", response_model=GenerateSecondLessonResponse)
def generate_second_lesson(
    request: GenerateSecondLessonRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> GenerateSecondLessonResponse:
    try:
        result = pipeline.process_feedback_and_generate_second_lesson(
            lesson_id=request.lesson_id,
            learner_id=request.learner_id,
            comprehension_response_id=request.comprehension_response_id,
            feedback_id=request.feedback_id,
            idempotency_key=request.idempotency_key,
        )
        return GenerateSecondLessonResponse(
            lesson_id=result["lesson_id"],
            adaptation_verified=result["adaptation_verified"],
        )
    except ForeignFeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_feedback", "feedback_id": exc.feedback_id},
        )
    except FeedbackAlreadyAppliedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "feedback_already_applied", "feedback_id": exc.feedback_id},
        )
    except ComprehensionRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "comprehension_required", "message": exc.message},
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )
    except ContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "content_validation_failed", "issues": exc.issues},
        )
    except AdaptationNotChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "adaptation_not_changed", "details": exc.details},
        )


class CloseLessonRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)


class CloseLessonResponse(BaseModel):
    lesson_id: str
    status: str
    prompt_tokens: int
    completion_tokens: int


@router.post("/lessons/close", response_model=CloseLessonResponse)
def close_lesson(
    request: CloseLessonRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> CloseLessonResponse:
    try:
        result = pipeline.finalize_and_close(
            lesson_id=request.lesson_id,
            learner_id=request.learner_id,
        )
        return CloseLessonResponse(**result)
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_resource", "resource": "lesson"},
        )


class LearnerProgressRequest(BaseModel):
    learner_id: str = Field(min_length=1)


class LearnerProgressResponse(BaseModel):
    learner_id: str
    topic: str
    total_lessons: int
    total_feedback: int
    pending_review_lessons: int


@router.get("/learners/{learner_id}/progress", response_model=LearnerProgressResponse)
def get_learner_progress(
    learner_id: str,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> LearnerProgressResponse:
    result = pipeline.get_learner_progress(learner_id=learner_id)
    return LearnerProgressResponse(**result)