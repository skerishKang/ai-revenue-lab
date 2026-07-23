"""Operator review workflow: CAS state transitions + audit trail.

Generation and publication are separate concerns:

* ``generation_status`` — lifecycle of content generation (``pending_review``,
  ``generation_failed``, ...).
* ``publication_state`` — delivery gate (``pending`` → ``published``/``rejected``).

Approve/reject are atomic compare-and-set transitions guarded on
``generation_status='pending_review' AND publication_state='pending'``. Exactly
one concurrent reviewer wins; the loser (and any re-transition of an already
decided lesson) gets ``ReviewStateConflictError``. The state change and the
audit row are written in one transaction.
"""

from __future__ import annotations

import json
import secrets
import sqlite3

from app.pipeline.errors import NotPublishableError, ReviewStateConflictError
from app.repositories.lesson_repository import LessonRecord, _row_to_record


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _transition(
    conn: sqlite3.Connection,
    lesson_id: str,
    target_publication_state: str,
    action: str,
    external_identity_id: str,
    reason: str,
    *,
    validate: bool = False,
) -> LessonRecord:
    """Atomically transition publication_state and record an audit event.

    Sequence (one transaction):
        BEGIN IMMEDIATE
        -> confirm lesson row exists
        -> confirm generation_status='pending_review' AND publication_state='pending'
        -> (approve only) run canonical publication validation; abort if not publishable
        -> publication_state CAS
        -> audit insert
        -> COMMIT

    CAS: only a lesson that is ``pending_review`` and still ``pending`` moves.
    ``rowcount != 1`` => conflict (already decided, not generated, or a
    concurrent reviewer won). On validation failure the state stays ``pending``
    and no audit row is written.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if row is None:
            raise ReviewStateConflictError(lesson_id)
        if row["generation_status"] != "pending_review" or row["publication_state"] != "pending":
            raise ReviewStateConflictError(lesson_id)

        if validate:
            from app.pipeline.publication import validate_for_publication

            result = validate_for_publication(conn, _row_to_record(row))
            if not result.publishable:
                raise NotPublishableError(lesson_id, result)

        rc = conn.execute(
            "UPDATE lessons SET publication_state = ?, updated_at = ? "
            "WHERE id = ? AND generation_status = 'pending_review' AND publication_state = 'pending'",
            (target_publication_state, _utcnow(), lesson_id),
        ).rowcount
        if rc != 1:
            raise ReviewStateConflictError(lesson_id)

        conn.execute(
            "INSERT INTO lesson_review_events (id, lesson_id, external_identity_id, action, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"rev_{secrets.token_urlsafe(16)}",
                lesson_id,
                external_identity_id,
                action,
                reason,
                _utcnow(),
            ),
        )
        row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        conn.commit()
        return _row_to_record(row)
    except Exception:
        conn.rollback()
        raise


def approve_lesson(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    external_identity_id: str,
    reason: str = "",
) -> LessonRecord:
    # Approve enforces the canonical publication validation gate.
    return _transition(
        conn, lesson_id, "published", "approved", external_identity_id, reason, validate=True
    )


def reject_lesson(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    external_identity_id: str,
    reason: str = "",
) -> LessonRecord:
    # Reject is allowed even for content that fails validation.
    return _transition(
        conn, lesson_id, "rejected", "rejected", external_identity_id, reason, validate=False
    )


def get_review_events(conn: sqlite3.Connection, lesson_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM lesson_review_events WHERE lesson_id = ? ORDER BY created_at",
        (lesson_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Structured review detail (operator-only).
# ---------------------------------------------------------------------------
def _validation_status(ok: bool) -> str:
    return "passed" if ok else "failed"


def _validation_report(conn: sqlite3.Connection, lesson: LessonRecord) -> dict:
    """Canonical publication validation report (same gate approve enforces).

    Reports pass/fail per contract dimension plus the overall ``publishable``
    verdict. No internal rule text or raw prompts are included — only outcome
    labels.
    """
    from app.pipeline.publication import validate_for_publication

    result = validate_for_publication(conn, lesson)
    return {
        "lesson_plan_schema": result.lesson_plan_schema,
        "content_schema": result.lesson_content_schema,
        "ast_safety": result.ast_safety,
        "answer_grounding": result.answer_grounding,
        "adaptation_materiality": result.adaptation_materiality,
        "privacy_markup": result.privacy_markup,
        "lineage_integrity": result.lineage_integrity,
        "publishable": result.publishable,
    }


def _generation_evidence(conn: sqlite3.Connection, lesson_id: str) -> dict:
    """Provider accounting with exact call/retry semantics and task breakdown.

    ``provider_call_count`` is the total number of provider calls; ``retry_count``
    is the sum over tasks of ``MAX(attempt_number) - 1`` (NOT calls - 1, since a
    lesson generation has multiple tasks). Provider/model are reported per task
    so differences between tasks are not hidden.
    """
    from app.repositories.generation_run_repository import (
        compute_accounting,
        compute_task_breakdown,
    )

    # generation_runs are keyed by attempt_group "<lesson_id>:first|second".
    rows = conn.execute(
        "SELECT DISTINCT attempt_group_id FROM generation_runs WHERE lesson_id = ?",
        (lesson_id,),
    ).fetchall()
    groups = [r["attempt_group_id"] for r in rows]

    total_calls = 0
    total_retries = 0
    total_latency = 0.0
    all_inputs: list[int] = []
    all_outputs: list[int] = []
    tasks: list[dict] = []
    for group in groups:
        accounting = compute_accounting(conn, group)
        if accounting is None:
            continue
        total_calls += accounting.provider_call_count
        total_retries += accounting.retry_count
        total_latency += accounting.latency_ms_total
        if accounting.input_tokens_total is not None:
            all_inputs.append(accounting.input_tokens_total)
        if accounting.output_tokens_total is not None:
            all_outputs.append(accounting.output_tokens_total)
        for t in compute_task_breakdown(conn, group):
            tasks.append(
                {
                    "task_type": t.task_type,
                    "provider": t.provider,
                    "model": t.model,
                    "provider_call_count": t.provider_call_count,
                    "retry_count": t.retry_count,
                    "latency_ms_total": t.latency_ms_total,
                    "input_tokens_total": t.input_tokens_total,
                    "output_tokens_total": t.output_tokens_total,
                    "final_validation_result": t.final_validation_result,
                }
            )

    return {
        "provider_call_count": total_calls,
        "retry_count": total_retries,
        "latency_ms_total": total_latency,
        "input_tokens_total": sum(all_inputs) if all_inputs else None,
        "output_tokens_total": sum(all_outputs) if all_outputs else None,
        "tasks": tasks,
    }


def build_review_detail(conn: sqlite3.Connection, lesson: LessonRecord) -> dict:
    """Assemble the full structured payload an operator needs to review a lesson."""
    try:
        plan = json.loads(lesson.lesson_plan_json or "{}")
    except (ValueError, TypeError):
        plan = {}
    try:
        content = json.loads(lesson.lesson_content_json or "{}")
    except (ValueError, TypeError):
        content = {}

    sections = [
        {
            "section_id": s.get("section_id", ""),
            "title": s.get("title", ""),
            "content": s.get("content", ""),
            "includes_code": bool(s.get("includes_code", False)),
            "code_snippet": s.get("code_snippet", ""),
        }
        for s in content.get("sections", [])
    ]
    code_examples = [
        {
            "example_id": e.get("example_id", ""),
            "language": e.get("language", "python"),
            "code": e.get("code", ""),
            "expected_output": e.get("expected_output", ""),
            "explanation": e.get("explanation", ""),
        }
        for e in content.get("code_examples", [])
    ]
    term_definitions = [
        {"term": t.get("term", ""), "definition": t.get("definition", "")}
        for t in content.get("term_definitions", [])
        if isinstance(t, dict)
    ]
    review_questions = [
        {
            "question": q.get("question", ""),
            "correct_answer": q.get("correct_answer", ""),
            "explanation": q.get("explanation", ""),
        }
        for q in content.get("review_questions", [])
    ]

    # Diagnostic provenance difficulty (if a snapshot drove this lesson).
    difficulty = ""
    if lesson.source_diagnostic_snapshot_id:
        snap = conn.execute(
            "SELECT derived_difficulty FROM diagnostic_snapshots WHERE id = ?",
            (lesson.source_diagnostic_snapshot_id,),
        ).fetchone()
        if snap:
            difficulty = snap["derived_difficulty"]

    instructional_plan = {
        "objective": plan.get("title", content.get("title", "")),
        "section_order": [s.get("section_id", "") for s in plan.get("sections", [])],
        "difficulty": difficulty,
        "example_count": len(code_examples),
        "review_question_count": plan.get("review_question_count", len(review_questions)),
        "feedback_actions": list(plan.get("applied_feedback", content.get("applied_feedback", []))),
    }

    # Adaptation signals — built from the EXACT generation-input provenance
    # stored on the lesson (never a "latest row" arbitrary pick).
    decisions = conn.execute(
        "SELECT dimension, before_value, after_value, reason, signal_type, signal_reference_id "
        "FROM adaptation_decisions WHERE next_lesson_id = ? ORDER BY created_at",
        (lesson.id,),
    ).fetchall()
    material_changes = [
        {
            "dimension": d["dimension"],
            "before_value": d["before_value"],
            "after_value": d["after_value"],
            "reason": d["reason"],
        }
        for d in decisions
    ]

    feedback_signal = _feedback_signal(conn, lesson.source_feedback_id)
    comprehension_signal = _comprehension_signal(conn, lesson.source_comprehension_response_id)

    adaptation = {
        "prior_lesson_id": lesson.prior_lesson_id or None,
        "feedback_signal": feedback_signal,
        "comprehension_signal": comprehension_signal,
        "material_changes": material_changes,
    }

    return {
        "lesson_id": lesson.id,
        "learner_id": lesson.learner_id,
        "concept_id": lesson.concept_id,
        "lesson_number": lesson.lesson_number,
        "generation_status": lesson.generation_status,
        "publication_state": lesson.publication_state,
        "source_diagnostic_snapshot_id": lesson.source_diagnostic_snapshot_id,
        "source_feedback_id": lesson.source_feedback_id,
        "source_comprehension_response_id": lesson.source_comprehension_response_id,
        "instructional_plan": instructional_plan,
        "lesson_content": {
            "sections": sections,
            "code_examples": code_examples,
            "term_definitions": term_definitions,
            "review_questions": review_questions,
        },
        "adaptation": adaptation,
        "validation": _validation_report(conn, lesson),
        "generation_evidence": _generation_evidence(conn, lesson.id),
    }


def _bounded(text: str | None, limit: int = 500) -> str:
    return (text or "")[:limit]


def _feedback_signal(conn: sqlite3.Connection, feedback_id: str | None) -> dict | None:
    """Structured feedback signal from the exact feedback that drove generation."""
    if not feedback_id:
        return None
    row = conn.execute(
        "SELECT id, direction_choices, free_text, lesson_generation FROM feedback WHERE id = ?",
        (feedback_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        direction_choices = json.loads(row["direction_choices"] or "[]")
    except (ValueError, TypeError):
        direction_choices = []
    return {
        "feedback_id": row["id"],
        "direction_choices": direction_choices,
        "free_text": _bounded(row["free_text"]),
        "lesson_generation": row["lesson_generation"],
    }


def _comprehension_signal(conn: sqlite3.Connection, response_id: str | None) -> dict | None:
    """Structured comprehension signal from the exact response used in generation."""
    if not response_id:
        return None
    row = conn.execute(
        "SELECT id, understood, difficulty_rating, free_text FROM comprehension_responses WHERE id = ?",
        (response_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "response_id": row["id"],
        "understood": bool(row["understood"]),
        "difficulty_rating": row["difficulty_rating"],
        "free_text": _bounded(row["free_text"]),
    }
