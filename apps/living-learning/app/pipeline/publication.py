"""Canonical publication validation (validation-before-publication).

A lesson may only move ``publication_state`` from ``pending`` to ``published``
if it passes the full canonical validation gate. This is the single authority
used by the operator approve transaction; the learner read-time validation is a
defense-in-depth backstop, not the primary gate.

Checks:
  * LessonPlan Pydantic schema
  * LessonContent Pydantic schema
  * every code example AST + expected-output consistency
  * every inline section code snippet AST safety
  * review-answer grounding (taught material only)
  * privacy / markup / credential screen
  * feedback-specific material adaptation (second+ lessons must pass; first
    lesson is ``not_applicable``)
"""

from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel

from app.domain.models import LessonContent, LessonPlan
from app.pipeline.validation import (
    is_answer_grounded,
    validate_code_examples,
    validate_material_adaptation,
    validate_safe_content,
)

PASSED = "passed"
FAILED = "failed"
NOT_APPLICABLE = "not_applicable"


class PublicationValidationResult(BaseModel):
    lesson_plan_schema: str
    lesson_content_schema: str
    ast_safety: str
    answer_grounding: str
    adaptation_materiality: str
    privacy_markup: str
    lineage_integrity: str

    @property
    def publishable(self) -> bool:
        """All mandatory dimensions must pass.

        ``adaptation_materiality`` may be ``not_applicable`` for a first lesson
        (no prior lesson to differ from); every other dimension — including
        ``lineage_integrity`` — must be ``passed``.
        """
        mandatory = [
            self.lesson_plan_schema,
            self.lesson_content_schema,
            self.ast_safety,
            self.answer_grounding,
            self.privacy_markup,
            self.lineage_integrity,
        ]
        if not all(v == PASSED for v in mandatory):
            return False
        return self.adaptation_materiality in (PASSED, NOT_APPLICABLE)


def _schema_status(model: type[BaseModel], payload: dict) -> str:
    try:
        model.model_validate(payload)
        return PASSED
    except Exception:
        return FAILED


def validate_for_publication(conn: sqlite3.Connection, lesson) -> PublicationValidationResult:
    """Run the canonical publication gate against a lesson's stored content."""
    try:
        plan = json.loads(lesson.lesson_plan_json or "{}")
    except (ValueError, TypeError):
        plan = {}
    try:
        content = json.loads(lesson.lesson_content_json or "{}")
    except (ValueError, TypeError):
        content = {}

    lesson_plan_schema = _schema_status(LessonPlan, plan)
    lesson_content_schema = _schema_status(LessonContent, content)

    # AST safety: code examples (with expected output) + inline section snippets.
    # Malformed content (e.g. sections not a list) fails closed rather than
    # crashing the validator.
    try:
        ast_ok = not validate_code_examples(content)
    except Exception:
        ast_ok = False
    ast_safety = PASSED if ast_ok else FAILED

    # Answer grounding.
    try:
        grounding_ok = all(
            is_answer_grounded(q.get("correct_answer", ""), content)
            for q in content.get("review_questions", [])
            if isinstance(q, dict)
        )
    except Exception:
        grounding_ok = False
    answer_grounding = PASSED if grounding_ok else FAILED

    # Privacy / markup / credential screen over the whole content payload.
    try:
        privacy_ok = not validate_safe_content(json.dumps(content, ensure_ascii=False))
    except Exception:
        privacy_ok = False
    privacy_markup = PASSED if privacy_ok else FAILED

    # Feedback-specific material adaptation.
    adaptation_materiality = _adaptation_materiality(conn, lesson, plan, content)

    # Lineage integrity: the lesson's stored provenance must be internally
    # consistent (first-lesson vs second-lesson contracts).
    lineage_integrity = _lineage_integrity(conn, lesson)

    return PublicationValidationResult(
        lesson_plan_schema=lesson_plan_schema,
        lesson_content_schema=lesson_content_schema,
        ast_safety=ast_safety,
        answer_grounding=answer_grounding,
        adaptation_materiality=adaptation_materiality,
        privacy_markup=privacy_markup,
        lineage_integrity=lineage_integrity,
    )


def _adaptation_materiality(conn: sqlite3.Connection, lesson, adapted_plan: dict, adapted_content: dict) -> str:
    """First lesson => not_applicable; later lessons must be materially adapted.

    Uses ONLY the exact feedback stored on the current lesson (no fallback to a
    prior lesson's signal). If the current lesson has no source feedback, the
    direction set is empty and materiality fails.
    """
    if not lesson.prior_lesson_id:
        return NOT_APPLICABLE

    prior_row = conn.execute(
        "SELECT lesson_plan_json, lesson_content_json FROM lessons WHERE id = ?",
        (lesson.prior_lesson_id,),
    ).fetchone()
    if prior_row is None:
        return FAILED
    try:
        prior_plan = json.loads(prior_row["lesson_plan_json"] or "{}")
    except (ValueError, TypeError):
        prior_plan = {}
    try:
        prior_content = json.loads(prior_row["lesson_content_json"] or "{}")
    except (ValueError, TypeError):
        prior_content = {}

    # Direction choices come ONLY from the exact feedback that drove THIS lesson.
    direction_choices: list[str] = []
    if lesson.source_feedback_id:
        fb = conn.execute(
            "SELECT direction_choices FROM feedback WHERE id = ?", (lesson.source_feedback_id,)
        ).fetchone()
        if fb:
            try:
                direction_choices = json.loads(fb["direction_choices"] or "[]")
            except (ValueError, TypeError):
                direction_choices = []

    reasons = validate_material_adaptation(
        prior_plan, prior_content, adapted_plan, adapted_content, direction_choices
    )
    return PASSED if not reasons else FAILED


def _lineage_integrity(conn: sqlite3.Connection, lesson) -> str:
    """Validate the lesson's stored provenance is internally consistent.

    First lesson (lesson_number == 1):
      prior_lesson_id IS NULL, source_feedback_id IS NULL,
      source_comprehension_response_id IS NULL; and if a diagnostic snapshot is
      referenced, its learner matches.

    Second+ lesson (lesson_number > 1):
      prior_lesson_id, source_feedback_id, source_comprehension_response_id all
      present and consistent (prior lesson exists with matching learner/concept/
      number and is published/closed; feedback belongs to the prior lesson and
      learner, is applied to this lesson, has canonical non-empty directions;
      comprehension belongs to the prior lesson and learner; diagnostic snapshot
      learner matches).

    Any contradiction => failed (no substitution from other rows).
    """
    from app.pipeline.validation import CANONICAL_DIRECTIONS

    # Diagnostic snapshot learner match (applies to any lesson that references one).
    if lesson.source_diagnostic_snapshot_id:
        snap = conn.execute(
            "SELECT learner_id FROM diagnostic_snapshots WHERE id = ?",
            (lesson.source_diagnostic_snapshot_id,),
        ).fetchone()
        if snap is None or snap["learner_id"] != lesson.learner_id:
            return FAILED

    if lesson.lesson_number == 1:
        # First lesson must have no generation lineage.
        if lesson.prior_lesson_id:
            return FAILED
        if lesson.source_feedback_id:
            return FAILED
        if lesson.source_comprehension_response_id:
            return FAILED
        return PASSED

    # Second+ lesson: all three provenance ids must be present.
    if not lesson.prior_lesson_id:
        return FAILED
    if not lesson.source_feedback_id:
        return FAILED
    if not lesson.source_comprehension_response_id:
        return FAILED

    # Prior lesson contract.
    prior = conn.execute(
        "SELECT learner_id, concept_id, lesson_number, publication_state FROM lessons WHERE id = ?",
        (lesson.prior_lesson_id,),
    ).fetchone()
    if prior is None:
        return FAILED
    if prior["learner_id"] != lesson.learner_id:
        return FAILED
    if prior["concept_id"] != lesson.concept_id:
        return FAILED
    if prior["lesson_number"] != lesson.lesson_number - 1:
        return FAILED
    if prior["publication_state"] not in ("published", "closed"):
        return FAILED

    # Feedback contract.
    fb = conn.execute(
        "SELECT id, lesson_id, learner_id, lesson_generation, applied_status, applied_to_lesson_id, direction_choices "
        "FROM feedback WHERE id = ?",
        (lesson.source_feedback_id,),
    ).fetchone()
    if fb is None:
        return FAILED
    if fb["lesson_id"] != lesson.prior_lesson_id:
        return FAILED
    if fb["learner_id"] != lesson.learner_id:
        return FAILED
    if fb["lesson_generation"] != prior["lesson_number"]:
        return FAILED
    if fb["applied_status"] != "applied_to_second":
        return FAILED
    if fb["applied_to_lesson_id"] != lesson.id:
        return FAILED
    try:
        directions = json.loads(fb["direction_choices"] or "[]")
    except (ValueError, TypeError):
        return FAILED
    if not directions:
        return FAILED
    if not all(d in CANONICAL_DIRECTIONS for d in directions):
        return FAILED

    # Comprehension contract.
    comp = conn.execute(
        "SELECT id, lesson_id, learner_id FROM comprehension_responses WHERE id = ?",
        (lesson.source_comprehension_response_id,),
    ).fetchone()
    if comp is None:
        return FAILED
    if comp["lesson_id"] != lesson.prior_lesson_id:
        return FAILED
    if comp["learner_id"] != lesson.learner_id:
        return FAILED

    return PASSED
