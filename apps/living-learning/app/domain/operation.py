"""Immutable operation identity for idempotent Learning Learning operations.

An ``OperationIdentity`` is a value object that canonically identifies a single
logical operation (first-lesson generation, feedback submission, second-lesson
generation, exercise answer). It produces a stable, collision-resistant
``operation_key`` used as the database-level idempotency key.

This removes the previous bug where operation keys were assembled ad-hoc from
raw string concatenation in the service layer (and where a ``op_key`` variable
was referenced out of scope). Every identity component is explicit and typed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


# Task types are a closed set so operation keys cannot be silently conflated
# across different operations that happen to share a client idempotency key.
TASK_FIRST_LESSON = "first_lesson_generation"
TASK_FEEDBACK = "feedback_submission"
TASK_SECOND_LESSON = "second_lesson_generation"
TASK_EXERCISE_ANSWER = "exercise_answer"

_TASK_TYPES = frozenset(
    {
        TASK_FIRST_LESSON,
        TASK_FEEDBACK,
        TASK_SECOND_LESSON,
        TASK_EXERCISE_ANSWER,
    }
)


@dataclass(frozen=True)
class OperationIdentity:
    """Immutable identity of one idempotent operation.

    All fields are part of the operation's identity. Two operations are the
    same iff every field matches. The ``client_idempotency_key`` is the
    caller-supplied key; the structural fields (learner, prior lesson,
    comprehension response, feedback) bind the key to a concrete resource so a
    reused client key cannot collide across different resources.
    """

    task_type: str
    learner_id: str
    client_idempotency_key: str
    prior_lesson_id: str = ""
    comprehension_response_id: str = ""
    feedback_id: str = ""
    exercise_id: str = ""

    def __post_init__(self) -> None:
        if self.task_type not in _TASK_TYPES:
            raise ValueError(f"unknown task_type: {self.task_type!r}")
        if not self.learner_id:
            raise ValueError("learner_id is required for an operation identity")
        if not self.client_idempotency_key:
            raise ValueError(
                "client_idempotency_key is required; callers that do not want "
                "idempotency should not build an OperationIdentity"
            )

    @property
    def operation_key(self) -> str:
        """Stable, length-bounded key used as the DB idempotency key.

        A SHA-256 digest over the canonical field tuple keeps the key bounded
        and free of any delimiter-injection from caller-supplied values, while
        the ``task_type`` prefix keeps keys human-inspectable in logs.
        """
        canonical = "|".join(
            [
                self.task_type,
                self.learner_id,
                self.prior_lesson_id,
                self.comprehension_response_id,
                self.feedback_id,
                self.exercise_id,
                self.client_idempotency_key,
            ]
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.task_type}:{digest}"

    @property
    def resource_id(self) -> str:
        """The primary resource this operation targets, for binding checks."""
        return (
            self.prior_lesson_id
            or self.exercise_id
            or self.feedback_id
            or self.learner_id
        )

    @property
    def fingerprint(self) -> str:
        """A fingerprint of the structural inputs (excludes the client key).

        Useful for detecting "same client key, different payload" conflicts.
        """
        canonical = "|".join(
            [
                self.task_type,
                self.learner_id,
                self.prior_lesson_id,
                self.comprehension_response_id,
                self.feedback_id,
                self.exercise_id,
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
