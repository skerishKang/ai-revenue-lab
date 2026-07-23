"""Portal-ready /api/v1 routes for Living Learning.

These routes sit behind the identity/membership boundary (see ``auth.py``). The
learner id always comes from the verified product membership — never from client
input — and operator endpoints require the operator role. Private responses are
marked ``no-store``/``noindex`` by the security middleware in the factory.

Domain logic is delegated to ``LessonPipeline`` and the repositories; nothing is
reimplemented inside the route handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.auth import Principal, get_principal, require_learner, require_operator
from app.api import schemas
from app.identity import FIREBASE_ISSUER
from app.pipeline import (
    AdaptationNotChangedError,
    ComprehensionRequiredError,
    ConcurrentOperationError,
    ContentValidationError,
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    LearnerInactiveError,
    LessonPipeline,
    NonRetryableError,
    OperationTerminalError,
    PrerequisiteNotMetError,
    RetryExhaustedError,
    UnsafeContentError,
)
from app.repositories import (
    get_adaptation_decisions_for_lesson,
    get_lesson_by_id,
    get_lessons_by_learner,
)

router = APIRouter(prefix="/api/v1", tags=["portal"])

PORTAL_CONTRACT_VERSION = "v1"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def _conn(request: Request):
    if not hasattr(request.app.state, "get_connection"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="unavailable")
    return request.app.state.get_connection()


def get_learner_pipeline(
    request: Request,
    principal: Principal = Depends(require_learner),
) -> LessonPipeline:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="unavailable")
    conn = _conn(request)
    try:
        yield LessonPipeline(conn, provider, request.app.state.settings)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _map_pipeline_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (PrerequisiteNotMetError, ComprehensionRequiredError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unprocessable")
    if isinstance(exc, FeedbackAlreadyAppliedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conflict")
    if isinstance(exc, (ForeignFeedbackError,)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if isinstance(exc, (ConcurrentOperationError, OperationTerminalError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conflict")
    if isinstance(exc, (RetryExhaustedError,)):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="generation_failed")
    if isinstance(exc, (UnsafeContentError, ContentValidationError, AdaptationNotChangedError, NonRetryableError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="validation_failed")
    if isinstance(exc, (LearnerInactiveError, GenerationError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unprocessable")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="error")


def _first_concept_id(conn, learner_id: str) -> str:
    row = conn.execute(
        "SELECT c.id FROM concepts c "
        "JOIN learner_sessions s ON s.curriculum_id = c.curriculum_id "
        "WHERE s.learner_id = ? ORDER BY c.sequence_order LIMIT 1",
        (learner_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="no_curriculum")
    return row[0]


def _lesson_by_sequence(conn, learner_id: str, sequence: int):
    lessons = get_lessons_by_learner(conn, learner_id)
    for lesson in lessons:
        if lesson.lesson_number == sequence:
            return lesson
    return None


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------
@router.get("/health", response_model=schemas.HealthResponse)
def health(request: Request) -> schemas.HealthResponse:
    settings = request.app.state.settings
    provider = getattr(request.app.state, "provider", None)
    ai_provider = getattr(provider, "provider_type", "unknown") if provider else "unknown"
    ai_model = getattr(provider, "model", "unknown") if provider else "unknown"
    return schemas.HealthResponse(
        status="ok",
        database_backend="sqlite",
        identity_provider="fake",
        ai_provider=ai_provider,
        ai_model=ai_model,
        portal_contract_version=PORTAL_CONTRACT_VERSION,
    )


@router.get("/me", response_model=schemas.MeResponse)
def me(principal: Principal = Depends(get_principal)) -> schemas.MeResponse:
    role = "operator" if principal.is_operator else ("learner" if principal.is_learner else "none")
    return schemas.MeResponse(
        provider="firebase",
        role=role,
        learner_id=principal.learner_id,
        revoked=False,
    )


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------
@router.get("/learning/home", response_model=schemas.LearningHomeResponse)
def learning_home(
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.LearningHomeResponse:
    try:
        progress = pipeline.get_learner_progress(principal.learner_id)
    except (GenerationError, LearnerInactiveError) as exc:
        raise _map_pipeline_error(exc)
    return schemas.LearningHomeResponse(
        learner_id=principal.learner_id,
        topic=progress["topic"],
        total_lessons=progress["total_lessons"],
        pending_review_lessons=progress["pending_review_lessons"],
        next_recommendation="conditionals",
    )


@router.post("/goals", response_model=schemas.GoalResponse)
def record_goal(
    body: schemas.GoalRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.GoalResponse:
    from app.repositories import update_learner_preferences

    conn = _conn_from_pipeline(pipeline)
    update_learner_preferences(conn, principal.learner_id, topic=body.goal, commit=True)
    return schemas.GoalResponse(learner_id=principal.learner_id, goal=body.goal, recorded=True)


@router.post("/diagnostics", response_model=schemas.DiagnosticResponse)
def record_diagnostic(
    body: schemas.DiagnosticRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.DiagnosticResponse:
    from app.repositories import update_learner_preferences

    conn = _conn_from_pipeline(pipeline)
    update_learner_preferences(
        conn,
        principal.learner_id,
        example_preference=body.explanation_preference,
        theory_density=body.theory_practice_balance,
        commit=True,
    )
    difficulty = "intro_1" if body.coding_experience == "none" else "intro_2"
    return schemas.DiagnosticResponse(
        learner_id=principal.learner_id, snapshot_recorded=True, initial_difficulty=difficulty
    )


@router.get("/lessons/{sequence}", response_model=schemas.LessonResponse)
def get_lesson(
    sequence: int,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.LessonResponse:
    conn = _conn_from_pipeline(pipeline)
    lesson = _lesson_by_sequence(conn, principal.learner_id, sequence)
    if lesson is None and sequence == 1:
        # Generate the first lesson on demand for the learner's first concept.
        concept_id = _first_concept_id(conn, principal.learner_id)
        try:
            lesson_id = pipeline.start_first_lesson(principal.learner_id, concept_id)
        except Exception as exc:
            raise _map_pipeline_error(exc)
        lesson = get_lesson_by_id(conn, lesson_id)
    if lesson is None or lesson.learner_id != principal.learner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return schemas.LessonResponse(
        lesson_id=lesson.id,
        learner_id=lesson.learner_id,
        concept_id=lesson.concept_id,
        lesson_number=lesson.lesson_number,
        generation_status=lesson.generation_status,
        adaptation_summary=lesson.adaptation_summary,
    )


@router.post("/lessons/{sequence}/responses", response_model=schemas.LessonResponseResult)
def record_response(
    sequence: int,
    body: schemas.LessonResponseRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.LessonResponseResult:
    conn = _conn_from_pipeline(pipeline)
    lesson = _lesson_by_sequence(conn, principal.learner_id, sequence)
    if lesson is None or lesson.learner_id != principal.learner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        result = pipeline.record_comprehension(
            lesson.id,
            principal.learner_id,
            understood=body.understood,
            difficulty_rating=body.difficulty_rating,
            free_text=body.free_text,
        )
    except Exception as exc:
        raise _map_pipeline_error(exc)
    return schemas.LessonResponseResult(response_id=result["response_id"], recorded=result["success"])


@router.post("/lessons/{sequence}/feedback", response_model=schemas.LessonFeedbackResult)
def record_feedback(
    sequence: int,
    body: schemas.LessonFeedbackRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.LessonFeedbackResult:
    for direction in body.direction_choices:
        if direction not in schemas.VALID_DIRECTIONS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unprocessable")
    conn = _conn_from_pipeline(pipeline)
    lesson = _lesson_by_sequence(conn, principal.learner_id, sequence)
    if lesson is None or lesson.learner_id != principal.learner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        result = pipeline.record_feedback(
            lesson.id,
            principal.learner_id,
            direction_choices=body.direction_choices,
            free_text=body.free_text,
            idempotency_key=body.idempotency_key,
        )
    except Exception as exc:
        raise _map_pipeline_error(exc)
    return schemas.LessonFeedbackResult(
        feedback_id=result["feedback_id"], is_duplicate=result.get("is_duplicate", False)
    )


@router.get("/adaptations/{sequence}", response_model=schemas.AdaptationsResponse)
def get_adaptations(
    sequence: int,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.AdaptationsResponse:
    conn = _conn_from_pipeline(pipeline)
    lesson = _lesson_by_sequence(conn, principal.learner_id, sequence)
    if lesson is None or lesson.learner_id != principal.learner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    decisions = get_adaptation_decisions_for_lesson(conn, lesson.id)
    return schemas.AdaptationsResponse(
        lesson_id=lesson.id,
        decisions=[
            schemas.AdaptationDecisionView(
                dimension=d.dimension,
                before_value=d.before_value,
                after_value=d.after_value,
                reason=d.reason,
                signal_type=d.signal_type,
            )
            for d in decisions
        ],
    )


@router.get("/progress", response_model=schemas.ProgressResponse)
def get_progress(
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.ProgressResponse:
    try:
        progress = pipeline.get_learner_progress(principal.learner_id)
    except (GenerationError, LearnerInactiveError) as exc:
        raise _map_pipeline_error(exc)
    return schemas.ProgressResponse(
        learner_id=principal.learner_id,
        topic=progress["topic"],
        total_lessons=progress["total_lessons"],
        total_feedback=progress["total_feedback"],
        pending_review_lessons=progress["pending_review_lessons"],
    )


# ---------------------------------------------------------------------------
# Operator review
# ---------------------------------------------------------------------------
@router.get("/operator/review", response_model=schemas.ReviewListResponse)
def operator_review_list(
    request: Request,
    principal: Principal = Depends(require_operator),
) -> schemas.ReviewListResponse:
    conn = _conn(request)
    try:
        rows = conn.execute(
            "SELECT id, learner_id, concept_id, lesson_number, generation_status "
            "FROM lessons WHERE generation_status = 'pending_review' ORDER BY created_at"
        ).fetchall()
    finally:
        _safe_close(conn)
    return schemas.ReviewListResponse(
        pending=[
            schemas.ReviewListItem(
                lesson_id=r["id"],
                learner_id=r["learner_id"],
                concept_id=r["concept_id"],
                lesson_number=r["lesson_number"],
                generation_status=r["generation_status"],
            )
            for r in rows
        ]
    )


@router.get("/operator/review/{lesson_id}", response_model=schemas.ReviewDetailResponse)
def operator_review_detail(
    lesson_id: str,
    request: Request,
    principal: Principal = Depends(require_operator),
) -> schemas.ReviewDetailResponse:
    conn = _conn(request)
    try:
        lesson = get_lesson_by_id(conn, lesson_id)
    finally:
        _safe_close(conn)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return schemas.ReviewDetailResponse(
        lesson_id=lesson.id,
        learner_id=lesson.learner_id,
        concept_id=lesson.concept_id,
        lesson_number=lesson.lesson_number,
        generation_status=lesson.generation_status,
        adaptation_summary=lesson.adaptation_summary,
    )


@router.post("/operator/review/{lesson_id}/approve", response_model=schemas.ReviewActionResponse)
def operator_approve(
    lesson_id: str,
    body: schemas.ReviewActionRequest,
    request: Request,
    principal: Principal = Depends(require_operator),
) -> schemas.ReviewActionResponse:
    return _set_review_status(request, lesson_id, "published")


@router.post("/operator/review/{lesson_id}/reject", response_model=schemas.ReviewActionResponse)
def operator_reject(
    lesson_id: str,
    body: schemas.ReviewActionRequest,
    request: Request,
    principal: Principal = Depends(require_operator),
) -> schemas.ReviewActionResponse:
    return _set_review_status(request, lesson_id, "rejected")


def _set_review_status(request: Request, lesson_id: str, new_status: str) -> schemas.ReviewActionResponse:
    from app.repositories import update_lesson_status

    conn = _conn(request)
    try:
        lesson = get_lesson_by_id(conn, lesson_id)
        if lesson is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        update_lesson_status(conn, lesson_id, new_status, commit=True)
    finally:
        _safe_close(conn)
    return schemas.ReviewActionResponse(lesson_id=lesson_id, generation_status=new_status)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _conn_from_pipeline(pipeline: LessonPipeline):
    return pipeline.conn


def _safe_close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
