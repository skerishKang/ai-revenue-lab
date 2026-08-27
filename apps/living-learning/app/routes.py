"""FastAPI routes for Living Learning."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.ai.base import AIProvider
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
    LearnerInactiveError,
    UnsafeContentError,
    NonRetryableError,
    ConflictingAnswerError,
)
from app.repositories import (
    get_learner_by_id,
    get_lesson_by_id,
)


router = APIRouter(prefix="/api/v1", tags=["living-learning"])
_ResultT = TypeVar("_ResultT")


def get_provider_from_state(request: Request) -> AIProvider:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "provider_not_configured"},
        )
    return provider


class RequestPipelineRunner:
    """Run one pipeline operation with thread-owned SQLite connection lifetime.

    FastAPI may evaluate sync dependencies and sync endpoints on different
    worker threads. The dependency therefore carries only a connection factory;
    it never creates a SQLite object. ``run`` is called from the endpoint worker
    and owns create -> use -> close in that single thread.
    """

    def __init__(
        self,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
        provider: AIProvider,
        settings: object,
    ) -> None:
        if not callable(connection_factory):
            raise ValueError("connection_factory must be callable")
        self._connection_factory = connection_factory
        self._provider = provider
        self._settings = settings

    def run(self, operation: Callable[[LessonPipeline], _ResultT]) -> _ResultT:
        if not callable(operation):
            raise ValueError("operation must be callable")
        conn = self._connection_factory()
        try:
            return operation(LessonPipeline(conn, self._provider, self._settings))
        finally:
            try:
                conn.close()
            except Exception:
                pass


def get_pipeline(
    request: Request,
    provider: Annotated[AIProvider, Depends(get_provider_from_state)],
) -> RequestPipelineRunner:
    connection_factory = getattr(request.app.state, "get_connection", None)
    if not callable(connection_factory):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "database_not_configured"},
        )
    return RequestPipelineRunner(
        connection_factory=connection_factory,
        provider=provider,
        settings=request.app.state.settings,
    )


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
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> CreateLearnerResponse:
    result = pipeline.run(
        lambda runtime: runtime.create_learner_and_session(
            topic=request.topic,
            display_name=request.display_name,
            target_duration_minutes=request.target_duration_minutes,
            example_preference=request.example_preference,
            theory_density=request.theory_density,
            jargon_level=request.jargon_level,
            review_question_count=request.review_question_count,
        )
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
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> StartLessonResponse:
    try:
        lesson_id = pipeline.run(
            lambda runtime: runtime.start_first_lesson(
                learner_id=request.learner_id,
                concept_id=request.concept_id,
                idempotency_key=request.idempotency_key,
            )
        )
        return StartLessonResponse(lesson_id=lesson_id)
    except PrerequisiteNotMetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "prerequisite_not_met", "missing": exc.missing},
        )
    except RetryExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "task": exc.task_type},
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except NonRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except ContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "content_validation_failed", "issues": exc.issues},
        )
    except AdaptationNotChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "adaptation_not_changed", "details": exc.details},
        )
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "unsafe_content", "issues": exc.issues},
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
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> RecordComprehensionResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.record_comprehension(
                lesson_id=request.lesson_id,
                learner_id=request.learner_id,
                understood=request.understood,
                difficulty_rating=request.difficulty_rating,
                free_text=request.free_text,
            )
        )
        return RecordComprehensionResponse(
            response_id=result["response_id"],
            comprehension_recorded=result["success"],
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_resource", "resource": "lesson"},
        )
    except LearnerInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "learner_inactive", "learner_id": exc.learner_id, "status": exc.status},
        )


class SubmitFeedbackRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    direction_choices: list[str] = Field(default_factory=list)
    free_text: str = ""
    idempotency_key: str = ""


class SubmitFeedbackResponse(BaseModel):
    feedback_id: str
    is_duplicate: bool = False


@router.post("/feedback", response_model=SubmitFeedbackResponse)
def submit_feedback(
    request: SubmitFeedbackRequest,
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> SubmitFeedbackResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.record_feedback(
                lesson_id=request.lesson_id,
                learner_id=request.learner_id,
                direction_choices=request.direction_choices,
                free_text=request.free_text,
                idempotency_key=request.idempotency_key,
            )
        )
        return SubmitFeedbackResponse(
            feedback_id=result["feedback_id"],
            is_duplicate=result.get("is_duplicate", False),
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_feedback"},
        )
    except LearnerInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "learner_inactive", "learner_id": exc.learner_id, "status": exc.status},
        )


class SecondLessonRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    comprehension_response_id: str = Field(min_length=1)
    feedback_id: str = Field(min_length=1)
    idempotency_key: str = ""


class SecondLessonResponse(BaseModel):
    lesson_id: str
    adaptation_verified: bool


@router.post("/lessons/second", response_model=SecondLessonResponse)
def start_second_lesson(
    request: SecondLessonRequest,
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> SecondLessonResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.process_feedback_and_generate_second_lesson(
                lesson_id=request.lesson_id,
                learner_id=request.learner_id,
                comprehension_response_id=request.comprehension_response_id,
                feedback_id=request.feedback_id,
                idempotency_key=request.idempotency_key,
            )
        )
        return SecondLessonResponse(
            lesson_id=result["lesson_id"],
            adaptation_verified=result.get("adaptation_verified", False),
        )
    except ComprehensionRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "comprehension_required"},
        )
    except FeedbackAlreadyAppliedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "feedback_already_applied"},
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except RetryExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "generation_failed", "task": exc.task_type},
        )
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "unsafe_content", "issues": exc.issues},
        )
    except AdaptationNotChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "adaptation_not_changed", "details": exc.details},
        )
    except NonRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "non_retryable_error", "message": str(exc)},
        )


class FinalizeLessonRequest(BaseModel):
    lesson_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)


class FinalizeLessonResponse(BaseModel):
    lesson_id: str
    status: str
    prompt_tokens: int
    completion_tokens: int


@router.post("/lessons/finalize", response_model=FinalizeLessonResponse)
def finalize_lesson(
    request: FinalizeLessonRequest,
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> FinalizeLessonResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.finalize_and_close(
                lesson_id=request.lesson_id,
                learner_id=request.learner_id,
            )
        )
        return FinalizeLessonResponse(
            lesson_id=result["lesson_id"],
            status=result["status"],
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
        )
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except ForeignFeedbackError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_lesson"},
        )


class LearnerProgressResponse(BaseModel):
    learner_id: str
    topic: str
    total_lessons: int
    total_feedback: int
    pending_review_lessons: int


@router.get("/learners/{learner_id}/progress", response_model=LearnerProgressResponse)
def get_learner_progress(
    learner_id: str,
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> LearnerProgressResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.get_learner_progress(learner_id=learner_id)
        )
        return LearnerProgressResponse(**result)
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except LearnerInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "learner_inactive", "learner_id": exc.learner_id, "status": exc.status},
        )


class AnswerExerciseRequest(BaseModel):
    exercise_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    idempotency_key: str = ""


class AnswerExerciseResponse(BaseModel):
    response_id: str
    is_correct: bool
    is_duplicate: bool


@router.post("/exercises/answer", response_model=AnswerExerciseResponse)
def answer_exercise(
    request: AnswerExerciseRequest,
    pipeline: Annotated[RequestPipelineRunner, Depends(get_pipeline)],
) -> AnswerExerciseResponse:
    try:
        result = pipeline.run(
            lambda runtime: runtime.answer_exercise(
                exercise_id=request.exercise_id,
                learner_id=request.learner_id,
                answer=request.answer,
                idempotency_key=request.idempotency_key,
            )
        )
        return AnswerExerciseResponse(**result)
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        )
    except ConflictingAnswerError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "conflicting_answer"},
        )
    except ForeignFeedbackError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "foreign_lesson"},
        )