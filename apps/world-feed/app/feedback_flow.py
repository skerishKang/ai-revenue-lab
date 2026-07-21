"""Feedback persist and second-brief ownership checks."""

from __future__ import annotations

from app.brief_pipeline import generate_brief, load_brief_signature
from app.domain.enums import BriefSequence, GenerationTaskType
from app.domain.models import FeedbackInput
from app.errors import (
    AlreadyAppliedFeedbackError,
    FirstBriefMissingError,
    ForeignFeedbackError,
    IdempotencyConflictError,
    MismatchedPriorBriefError,
)
from app.repositories import brief_repository, feedback_repository, reader_repository
from app.repositories.common import NotFoundError


def apply_feedback(conn, feedback: FeedbackInput):
    existing = feedback_repository.get_feedback_by_idempotency_key(
        conn, feedback.idempotency_key
    )
    if existing is not None:
        same = (
            existing.reader_id == feedback.reader_id
            and existing.prior_brief_id == feedback.prior_brief_id
            and existing.action == feedback.action.value
        )
        if not same:
            raise IdempotencyConflictError(
                "idempotency key already binds different feedback resources"
            )
        return existing
    if feedback.prior_brief_id is not None:
        prior = brief_repository.get_brief_by_id(conn, feedback.prior_brief_id)
        if prior is None:
            raise MismatchedPriorBriefError("referenced prior brief does not exist")
        if prior.reader_id != feedback.reader_id:
            raise MismatchedPriorBriefError(
                "referenced prior brief belongs to a different reader"
            )
        if prior.sequence != BriefSequence.FIRST.value:
            raise MismatchedPriorBriefError(
                "referenced prior brief is not the first brief"
            )
    return feedback_repository.persist_feedback(conn, feedback)


def generate_second_brief(service, conn, reader_id: str, *, feedback_idempotency_key: str):
    reader = reader_repository.require_active_reader(conn, reader_id)
    feedback = feedback_repository.get_feedback_by_idempotency_key(
        conn, feedback_idempotency_key
    )
    if feedback is None:
        raise NotFoundError(f"feedback not found: {feedback_idempotency_key}")
    if feedback.reader_id != reader_id:
        raise ForeignFeedbackError("feedback belongs to a different reader")
    if feedback.applied_to_brief_id is not None:
        raise AlreadyAppliedFeedbackError("feedback has already been applied")

    first_brief = brief_repository.get_latest_by_reader_sequence(
        conn, reader_id, BriefSequence.FIRST.value
    )
    if first_brief is None:
        raise FirstBriefMissingError("no first brief exists for this reader")
    if feedback.prior_brief_id is None:
        raise MismatchedPriorBriefError("feedback must reference a prior first brief")
    prior_brief = brief_repository.get_brief_by_id(conn, feedback.prior_brief_id)
    if prior_brief is None:
        raise MismatchedPriorBriefError("referenced prior brief does not exist")
    if prior_brief.reader_id != reader_id:
        raise MismatchedPriorBriefError(
            "referenced prior brief belongs to a different reader"
        )
    if prior_brief.sequence != BriefSequence.FIRST.value:
        raise MismatchedPriorBriefError(
            "referenced prior brief is not the first brief"
        )
    if prior_brief.id != first_brief.id:
        raise MismatchedPriorBriefError(
            "feedback prior_brief_id must match the reader's current first brief"
        )
    return generate_brief(
        provider=service.provider,
        settings=service.settings,
        conn=conn,
        reader=reader,
        sequence=BriefSequence.SECOND,
        task_type=GenerationTaskType.GENERATE_SECOND_MICROBRIEF,
        feedback=feedback,
        prior_signature=load_brief_signature(conn, prior_brief.id),
    )
