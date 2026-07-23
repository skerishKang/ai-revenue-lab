"""Portal-ready /api/v1 routes for Living Learning.

These routes sit behind the identity/membership boundary (see ``auth.py``). The
learner id always comes from the verified product membership — never from client
input — and operator endpoints require the operator role.

Review-before-delivery: learners can only read lessons whose
``publication_state == 'published'``. Generation is an operator action and always
produces ``generation_status='pending_review'`` / ``publication_state='pending'``;
there is no automatic publication. Approve/reject are atomic CAS transitions with
an audit trail.

Domain logic is delegated to ``LessonPipeline``, ``review_service`` and the
repositories; nothing is reimplemented inside the route handlers.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.auth import Principal, get_principal, require_learner, require_operator
from app.api import schemas
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
from app.pipeline.errors import LostClaimOwnershipError, ReviewStateConflictError
from app.repositories import (
    get_adaptation_decisions_for_lesson,
    get_lesson_by_id,
    get_lessons_by_learner,
)
from app.review_service import approve_lesson, reject_lesson

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
        _safe_close(conn)


def get_operator_pipeline(
    request: Request,
    principal: Principal = Depends(require_operator),
) -> LessonPipeline:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="unavailable")
    conn = _conn(request)
    try:
        yield LessonPipeline(conn, provider, request.app.state.settings)
    finally:
        _safe_close(conn)


def _map_pipeline_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (PrerequisiteNotMetError, ComprehensionRequiredError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unprocessable")
    if isinstance(exc, FeedbackAlreadyAppliedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conflict")
    if isinstance(exc, (ForeignFeedbackError,)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if isinstance(exc, (ConcurrentOperationError, OperationTerminalError, LostClaimOwnershipError)):
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
    for lesson in get_lessons_by_learner(conn, learner_id):
        if lesson.lesson_number == sequence:
            return lesson
    return None


def _published_lesson_by_sequence(conn, learner_id: str, sequence: int):
    """Return the lesson only if it belongs to the learner AND is published."""
    lesson = _lesson_by_sequence(conn, learner_id, sequence)
    if lesson is None or lesson.learner_id != learner_id:
        return None
    if lesson.publication_state != "published":
        return None
    return lesson


def _build_published_lesson(conn, lesson) -> schemas.PublishedLessonResponse:
    """Serialize a published lesson into a validated structure.

    Deliberately omits internal prompts, provider payloads, expected answers and
    validation rules — only learner-facing teaching content is exposed.
    """
    try:
        content = json.loads(lesson.lesson_content_json or "{}")
    except (ValueError, TypeError):
        content = {}

    sections = [
        schemas.SectionView(
            section_id=s.get("section_id", ""),
            title=s.get("title", ""),
            content=s.get("content", ""),
            includes_code=bool(s.get("includes_code", False)),
        )
        for s in content.get("sections", [])
    ]
    code_examples = [
        schemas.CodeExampleView(
            example_id=e.get("example_id", ""),
            language=e.get("language", "python"),
            code=e.get("code", ""),
            explanation=e.get("explanation", ""),
        )
        for e in content.get("code_examples", [])
    ]
    raw_terms = content.get("term_definitions", [])
    term_definitions = [
        schemas.TermDefinitionView(term=t.get("term", ""), definition=t.get("definition", ""))
        for t in raw_terms
        if isinstance(t, dict)
    ]
    exercise_rows = conn.execute(
        "SELECT id, question, difficulty FROM exercises WHERE lesson_id = ? ORDER BY sequence_order",
        (lesson.id,),
    ).fetchall()
    exercises = [
        schemas.ExerciseView(exercise_id=r["id"], question=r["question"], difficulty=r["difficulty"])
        for r in exercise_rows
    ]
    return schemas.PublishedLessonResponse(
        lesson_id=lesson.id,
        lesson_number=lesson.lesson_number,
        objective=content.get("title", ""),
        sections=sections,
        code_examples=code_examples,
        term_definitions=term_definitions,
        exercises=exercises,
        adaptation_note=lesson.adaptation_summary,
    )


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------
@router.get("/health", response_model=schemas.HealthResponse)
def health(request: Request) -> schemas.HealthResponse:
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
    from app.repositories.history_repository import record_goal as persist_goal

    conn = _conn_from_pipeline(pipeline)
    conn.execute("BEGIN IMMEDIATE")
    try:
        goal = persist_goal(conn, learner_id=principal.learner_id, goal_text=body.goal, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return schemas.GoalResponse(
        learner_id=principal.learner_id, goal_id=goal.id, goal=goal.goal_text, recorded=True
    )


@router.post("/diagnostics", response_model=schemas.DiagnosticResponse)
def record_diagnostic(
    body: schemas.DiagnosticRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.DiagnosticResponse:
    from app.repositories import update_learner_preferences
    from app.repositories.history_repository import record_diagnostic_snapshot

    derived_difficulty = "intro_1" if body.coding_experience == "none" else "intro_2"
    conn = _conn_from_pipeline(pipeline)
    # Snapshot append + preference update in one transaction. The response only
    # reports success once the row is committed.
    conn.execute("BEGIN IMMEDIATE")
    try:
        snapshot = record_diagnostic_snapshot(
            conn,
            learner_id=principal.learner_id,
            coding_experience=body.coding_experience,
            explanation_preference=body.explanation_preference,
            theory_practice_balance=body.theory_practice_balance,
            derived_difficulty=derived_difficulty,
            commit=False,
        )
        update_learner_preferences(
            conn,
            principal.learner_id,
            example_preference=body.explanation_preference,
            theory_density=body.theory_practice_balance,
            commit=False,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return schemas.DiagnosticResponse(
        learner_id=principal.learner_id,
        snapshot_id=snapshot.id,
        snapshot_recorded=True,
        derived_difficulty=derived_difficulty,
    )


@router.get("/lessons/{sequence}", response_model=schemas.PublishedLessonResponse)
def get_lesson(
    sequence: int,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.PublishedLessonResponse:
    # Learners only see published lessons. A missing or not-yet-approved lesson
    # collapses to a generic 404 (no internal state leakage).
    conn = _conn_from_pipeline(pipeline)
    lesson = _published_lesson_by_sequence(conn, principal.learner_id, sequence)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return _build_published_lesson(conn, lesson)


def _require_published_lesson(conn, learner_id: str, sequence: int):
    lesson = _published_lesson_by_sequence(conn, learner_id, sequence)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return lesson


@router.post("/lessons/{sequence}/responses", response_model=schemas.LessonResponseResult)
def record_response(
    sequence: int,
    body: schemas.LessonResponseRequest,
    principal: Principal = Depends(require_learner),
    pipeline: LessonPipeline = Depends(get_learner_pipeline),
) -> schemas.LessonResponseResult:
    conn = _conn_from_pipeline(pipeline)
    lesson = _require_published_lesson(conn, principal.learner_id, sequence)
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
    lesson = _require_published_lesson(conn, principal.learner_id, sequence)
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
    lesson = _require_published_lesson(conn, principal.learner_id, sequence)
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
# Operator: generation (always pending_review, never auto-published)
# ---------------------------------------------------------------------------
@router.post(
    "/operator/learners/{learner_id}/lessons/first/generate",
    response_model=schemas.OperatorGenerateResponse,
)
def operator_generate_first(
    learner_id: str,
    body: schemas.OperatorGenerateFirstRequest,
    principal: Principal = Depends(require_operator),
    pipeline: LessonPipeline = Depends(get_operator_pipeline),
) -> schemas.OperatorGenerateResponse:
    conn = _conn_from_pipeline(pipeline)
    concept_id = body.concept_id or _first_concept_id(conn, learner_id)
    try:
        lesson_id = pipeline.start_first_lesson(
            learner_id, concept_id, idempotency_key=body.idempotency_key
        )
    except Exception as exc:
        raise _map_pipeline_error(exc)
    lesson = get_lesson_by_id(conn, lesson_id)
    return schemas.OperatorGenerateResponse(
        lesson_id=lesson_id,
        generation_status=lesson.generation_status,
        publication_state=lesson.publication_state,
    )


@router.post(
    "/operator/learners/{learner_id}/lessons/{prior_sequence}/next/generate",
    response_model=schemas.OperatorGenerateResponse,
)
def operator_generate_next(
    learner_id: str,
    prior_sequence: int,
    body: schemas.OperatorGenerateNextRequest,
    principal: Principal = Depends(require_operator),
    pipeline: LessonPipeline = Depends(get_operator_pipeline),
) -> schemas.OperatorGenerateResponse:
    conn = _conn_from_pipeline(pipeline)
    prior_lesson = _lesson_by_sequence(conn, learner_id, prior_sequence)
    if prior_lesson is None or prior_lesson.learner_id != learner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        result = pipeline.process_feedback_and_generate_second_lesson(
            prior_lesson.id,
            learner_id,
            body.comprehension_response_id,
            body.feedback_id,
            idempotency_key=body.idempotency_key,
        )
    except Exception as exc:
        raise _map_pipeline_error(exc)
    lesson = get_lesson_by_id(conn, result["lesson_id"])
    return schemas.OperatorGenerateResponse(
        lesson_id=result["lesson_id"],
        generation_status=lesson.generation_status,
        publication_state=lesson.publication_state,
    )


# ---------------------------------------------------------------------------
# Operator: review (CAS approve/reject + audit)
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
    return _review_action(request, lesson_id, principal.external_identity_id, body.reason, approve=True)


@router.post("/operator/review/{lesson_id}/reject", response_model=schemas.ReviewActionResponse)
def operator_reject(
    lesson_id: str,
    body: schemas.ReviewActionRequest,
    request: Request,
    principal: Principal = Depends(require_operator),
) -> schemas.ReviewActionResponse:
    return _review_action(request, lesson_id, principal.external_identity_id, body.reason, approve=False)


def _review_action(
    request: Request, lesson_id: str, external_identity_id: str, reason: str, *, approve: bool
) -> schemas.ReviewActionResponse:
    conn = _conn(request)
    try:
        if get_lesson_by_id(conn, lesson_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        try:
            if approve:
                lesson = approve_lesson(conn, lesson_id, external_identity_id=external_identity_id, reason=reason)
            else:
                lesson = reject_lesson(conn, lesson_id, external_identity_id=external_identity_id, reason=reason)
        except ReviewStateConflictError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="state_conflict")
    finally:
        _safe_close(conn)
    return schemas.ReviewActionResponse(lesson_id=lesson_id, publication_state=lesson.publication_state)


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
