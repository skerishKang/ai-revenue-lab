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

from app.pipeline.errors import ReviewStateConflictError
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
) -> LessonRecord:
    """Atomically transition publication_state and record an audit event.

    CAS: only a lesson that is ``pending_review`` and still ``pending`` moves.
    ``rowcount != 1`` => conflict (already decided, not generated, or a
    concurrent reviewer won).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
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
    return _transition(conn, lesson_id, "published", "approved", external_identity_id, reason)


def reject_lesson(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    external_identity_id: str,
    reason: str = "",
) -> LessonRecord:
    return _transition(conn, lesson_id, "rejected", "rejected", external_identity_id, reason)


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


def _run_validation_report(conn: sqlite3.Connection, lesson: LessonRecord, content: dict, plan: dict) -> dict:
    """Re-run the deterministic validators against the stored content.

    Reports pass/fail per contract dimension. No internal rule text or raw
    prompts are included — only the outcome labels.
    """
    from app.domain.models import LessonContent
    from app.pipeline.code_safety import validate_code_output
    from app.pipeline.validation import is_answer_grounded, validate_safe_content

    # schema: Pydantic validation of the stored content.
    try:
        LessonContent.model_validate(content)
        schema_result = "passed"
    except Exception:
        schema_result = "failed"

    # AST safety: every code example and inline section snippet must be safe.
    ast_ok = True
    for ex in content.get("code_examples", []):
        if ex.get("code") and not validate_code_output(ex.get("code", ""), ex.get("expected_output", "")):
            ast_ok = False
    for s in content.get("sections", []):
        if s.get("includes_code") and s.get("code_snippet"):
            if not validate_code_output(s.get("code_snippet", ""), ""):
                ast_ok = False

    # answer grounding: each review answer must be justified by taught material.
    grounding_ok = all(
        is_answer_grounded(q.get("correct_answer", ""), content)
        for q in content.get("review_questions", [])
    )

    # adaptation materiality: only meaningful for a lesson with a prior lesson.
    if lesson.prior_lesson_id:
        prior = _row_to_record(
            conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson.prior_lesson_id,)).fetchone()
        )
        try:
            prior_content = json.loads(prior.lesson_content_json or "{}")
        except (ValueError, TypeError):
            prior_content = {}
        adaptation_result = _validation_status(content != prior_content)
    else:
        adaptation_result = "not_applicable"

    # privacy / markup: no unsafe code, credential requests, or markup injection.
    privacy_ok = not validate_safe_content(json.dumps(content, ensure_ascii=False))

    return {
        "content_schema": schema_result,
        "ast_safety": _validation_status(ast_ok),
        "answer_grounding": _validation_status(grounding_ok),
        "adaptation_materiality": adaptation_result,
        "privacy_markup": _validation_status(privacy_ok),
    }


def _generation_evidence(conn: sqlite3.Connection, lesson_id: str) -> dict:
    rows = conn.execute(
        "SELECT provider, advertised_model, latency_ms, prompt_tokens, completion_tokens "
        "FROM generation_runs WHERE lesson_id = ? ORDER BY attempt_number, created_at",
        (lesson_id,),
    ).fetchall()
    if not rows:
        return {
            "provider": "unknown",
            "model": "unknown",
            "attempts": 0,
            "retries": 0,
            "latency_ms_total": 0.0,
            "input_tokens_total": None,
            "output_tokens_total": None,
        }
    attempts = len(rows)
    latency_total = sum(r["latency_ms"] or 0.0 for r in rows)
    inputs = [r["prompt_tokens"] for r in rows if r["prompt_tokens"] is not None]
    outputs = [r["completion_tokens"] for r in rows if r["completion_tokens"] is not None]
    return {
        "provider": rows[0]["provider"] or "unknown",
        "model": rows[0]["advertised_model"] or "unknown",
        "attempts": attempts,
        "retries": max(0, attempts - 1),
        "latency_ms_total": latency_total,
        "input_tokens_total": sum(inputs) if inputs else None,
        "output_tokens_total": sum(outputs) if outputs else None,
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

    # Adaptation signals.
    feedback_signal = None
    comprehension_signal = None
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
    for d in decisions:
        if d["signal_type"] == "feedback" and feedback_signal is None:
            feedback_signal = d["signal_reference_id"]
    if lesson.prior_lesson_id:
        comp = conn.execute(
            "SELECT id FROM comprehension_responses WHERE lesson_id = ? ORDER BY responded_at DESC LIMIT 1",
            (lesson.prior_lesson_id,),
        ).fetchone()
        if comp:
            comprehension_signal = comp["id"]

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
        "instructional_plan": instructional_plan,
        "lesson_content": {
            "sections": sections,
            "code_examples": code_examples,
            "term_definitions": term_definitions,
            "review_questions": review_questions,
        },
        "adaptation": adaptation,
        "validation": _run_validation_report(conn, lesson, content, plan),
        "generation_evidence": _generation_evidence(conn, lesson.id),
    }
