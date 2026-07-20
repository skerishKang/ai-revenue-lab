"""FastAPI routes for Living Learning."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection
from app.pipeline import (
    LessonPipeline,
    PrerequisiteNotMetError,
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    RetryExhaustedError,
)
from app.ai import MockProvider


router = APIRouter(prefix="/api/v1", tags=["living-learning"])


def get_pipeline() -> LessonPipeline:
    conn = get_connection()
    provider = MockProvider()
    return LessonPipeline(conn, provider)


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
    curriculum_id: str


@router.post("/learners", response_model=CreateLearnerResponse)
def create_learner(
    request: CreateLearnerRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> CreateLearnerResponse:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic=request.topic,
        display_name=request.display_name,
        target_duration_minutes=request.target_duration_minutes,
        example_preference=request.example_preference,
        theory_density=request.theory_density,
        jargon_level=request.jargon_level,
        review_question_count=request.review_question_count,
    )
    return CreateLearnerResponse(learner_id=learner_id, curriculum_id=curriculum_id)


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
        feedback_id = pipeline.record_feedback(
            lesson_id=request.lesson_id,
            learner_id=request.learner_id,
            direction_choices=request.direction_choices,
            free_text=request.free_text,
            idempotency_key=request.idempotency_key,
        )
        return SubmitFeedbackResponse(feedback_id=feedback_id)
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )


class GenerateSecondLessonRequest(BaseModel):
    feedback_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    idempotency_key: str = ""


class GenerateSecondLessonResponse(BaseModel):
    lesson_id: str


@router.post("/lessons/second", response_model=GenerateSecondLessonResponse)
def generate_second_lesson(
    request: GenerateSecondLessonRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> GenerateSecondLessonResponse:
    try:
        lesson_id = pipeline.process_feedback_and_generate_second_lesson(
            feedback_id=request.feedback_id,
            learner_id=request.learner_id,
            idempotency_key=request.idempotency_key,
        )
        return GenerateSecondLessonResponse(lesson_id=lesson_id)
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
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        )


class RecordComprehensionRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    understood: bool = True
    difficulty_rating: int = Field(default=3, ge=1, le=5)
    free_text: str = ""


class RecordComprehensionResponse(BaseModel):
    response_id: str


@router.post("/comprehension", response_model=RecordComprehensionResponse)
def record_comprehension(
    request: RecordComprehensionRequest,
    pipeline: Annotated[LessonPipeline, Depends(get_pipeline)],
) -> RecordComprehensionResponse:
    response_id = pipeline.record_comprehension(
        lesson_id=request.lesson_id,
        learner_id=request.learner_id,
        understood=request.understood,
        difficulty_rating=request.difficulty_rating,
        free_text=request.free_text,
    )
    return RecordComprehensionResponse(response_id=response_id)


class CloseLessonRequest(BaseModel):
    lesson_id: str = Field(min_length=1)


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
    result = pipeline.finalize_and_close(lesson_id=request.lesson_id)
    return CloseLessonResponse(**result)


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