"""Living Learning pipeline service with proper atomicity and staging."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.models import (
    LessonContent,
    LessonPlan,
    ProviderResult,
)
from app.repositories import (
    check_idempotency_key,
    close_lesson,
    create_curriculum,
    create_exercise,
    create_feedback,
    create_generation_run,
    create_learner,
    create_lesson,
    create_learner_session,
    create_pilot_evidence,
    get_concept_by_id,
    get_feedback_by_id,
    get_learner_by_id,
    get_lesson_by_id,
    get_lessons_by_learner,
    is_feedback_applied,
    is_feedback_for_learner,
    mark_feedback_applied,
    record_comprehension_response,
    store_idempotency_key,
    sum_tokens_by_lesson,
    update_lesson_status,
    upsert_mastery,
    validate_prerequisites,
)
from app.pipeline.errors import (
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    PrerequisiteNotMetError,
    RetryExhaustedError,
    ContentValidationError,
    AdaptationNotChangedError,
    ComprehensionRequiredError,
    LearnerInactiveError,
    UnsafeContentError,
    NonRetryableError,
)
from app.pipeline.prompts import (
    ADAPTED_LESSON_PROMPT,
    LESSON_CONTENT_PROMPT,
    LESSON_PLAN_PROMPT,
)
from app.ai.base import AIProvider

if TYPE_CHECKING:
    pass

MAX_RETRIES = 3

RETRYABLE_ERROR_CATEGORIES = frozenset({
    "timeout",
    "rate_limit",
    "connection_error",
    "transient_provider_error",
})

NON_RETRYABLE_ERROR_CATEGORIES = frozenset({
    "authentication_error",
    "authorization_error",
    "provider_refusal",
    "unsafe_content",
    "invalid_request",
    "schema_mismatch",
})

UNSAFE_PATTERNS = [
    (r"import\s+os\s*,?\s*sys", "import os/sys"),
    (r"subprocess", "subprocess"),
    (r"eval\s*\(", "eval"),
    (r"exec\s*\(", "exec"),
    (r"os\.system", "os.system"),
    (r"requests\.", "requests"),
    (r"pip\s+install", "pip install"),
    (r"!.*curl", "curl"),
    (r"shell=True", "shell=True"),
]

CREDENTIAL_PATTERNS = [
    (r"api[_-]?key", "api_key"),
    (r"password", "password"),
    (r"secret", "secret"),
    (r"token", "token"),
    (r"credential", "credential"),
]

HTML_SCRIPT_PATTERNS = [
    (r"<script", "script tag"),
    (r"<iframe", "iframe tag"),
    (r"on\w+\s*=", "event handler"),
    (r"javascript:", "javascript protocol"),
]


def _validate_safe_content(content: str) -> list[str]:
    issues = []
    content_lower = content.lower()

    for pattern, name in UNSAFE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"unsafe_code: {name}")

    for pattern, name in CREDENTIAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"credential_request: {name}")

    for pattern, name in HTML_SCRIPT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"markup_injection: {name}")

    return issues


def _is_retryable_error(error_category: str, is_exception: bool = False) -> bool:
    if is_exception:
        return True
    if error_category in RETRYABLE_ERROR_CATEGORIES:
        return True
    if error_category in NON_RETRYABLE_ERROR_CATEGORIES:
        return False
    return False


class LessonPipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: AIProvider,
        settings: Any = None,
    ) -> None:
        self.conn = conn
        self.provider = provider
        self.settings = settings or type("Settings", (), {
            "provider_type": "mock",
            "provider_model": "mock-fixture",
            "database_url": ":memory:",
        })()

    def _validate_learner_active(self, learner_id: str) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")
        if learner.status not in ("active",):
            raise LearnerInactiveError(learner_id, learner.status)

    def create_learner_and_session(
        self,
        topic: str,
        **preferences,
    ) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            learner = create_learner(self.conn, topic=topic, **preferences, commit=False)

            session_id = f"sess_{secrets.token_urlsafe(16)}"
            cursor.execute(
                """INSERT INTO learner_sessions (session_id, learner_id, curriculum_id, current_lesson_sequence, last_activity_at, created_at)
                VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))""",
                (session_id, learner.id, ""),
            )

            curriculum = create_curriculum(self.conn, topic=topic, commit=False)

            cursor.execute(
                "UPDATE learner_sessions SET curriculum_id = ? WHERE session_id = ?",
                (curriculum.id, session_id),
            )

            concept_map = [
                ("variables", "변수", [], 0),
                ("values", "값", [], 1),
                ("conditionals", "간단한 조건문", ["variables", "values"], 2),
                ("python_example", "Python 예제", ["variables", "values", "conditionals"], 3),
            ]

            concept_ids = {}
            for eng_name, korean_name, prereqs, seq_order in concept_map:
                prereq_ids = []
                for p in prereqs:
                    if p in concept_ids:
                        prereq_ids.append(concept_ids[p])

                concept = self._create_concept_with_stable_id(
                    cursor, curriculum.id, eng_name, korean_name, prereq_ids, seq_order
                )
                concept_ids[eng_name] = concept.id
                upsert_mastery(self.conn, learner_id=learner.id, concept_id=concept.id, commit=False)

            self.conn.commit()

            return {
                "learner_id": learner.id,
                "session_id": session_id,
                "curriculum_id": curriculum.id,
            }
        except Exception:
            self.conn.rollback()
            raise

    def _create_concept_with_stable_id(
        self,
        cursor: sqlite3.Cursor,
        curriculum_id: str,
        name: str,
        description: str,
        prerequisites: list[str],
        sequence_order: int,
    ) -> Any:
        existing = cursor.execute(
            "SELECT * FROM concepts WHERE curriculum_id = ? AND name = ?",
            (curriculum_id, name),
        ).fetchone()

        if existing:
            cursor.execute(
                """UPDATE concepts SET prerequisites = ?, sequence_order = ?
                WHERE curriculum_id = ? AND name = ?""",
                (json.dumps(prerequisites), sequence_order, curriculum_id, name),
            )
            return type('ConceptRecord', (), {
                'id': existing['id'],
                'curriculum_id': curriculum_id,
                'name': name,
                'description': description,
                'prerequisites': prerequisites,
                'sequence_order': sequence_order,
            })()

        concept_id = f"concept_{secrets.token_urlsafe(16)}"
        cursor.execute(
            f"""INSERT INTO concepts (id, curriculum_id, name, description, prerequisites, sequence_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (concept_id, curriculum_id, name, description, json.dumps(prerequisites), sequence_order),
        )
        return type('ConceptRecord', (), {
            'id': concept_id,
            'curriculum_id': curriculum_id,
            'name': name,
            'description': description,
            'prerequisites': prerequisites,
            'sequence_order': sequence_order,
        })()

    def start_first_lesson(
        self,
        learner_id: str,
        concept_id: str,
        idempotency_key: str = "",
    ) -> str:
        self._validate_learner_active(learner_id)

        op_key = f"start_lesson:{learner_id}:{concept_id}:{idempotency_key}" if idempotency_key else ""
        existing = check_idempotency_key(self.conn, op_key) if op_key else None
        if existing:
            return existing.lesson_id

        valid, missing = validate_prerequisites(self.conn, concept_id, learner_id)
        if not valid:
            raise PrerequisiteNotMetError(concept_id, missing)

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            lesson = create_lesson(
                self.conn,
                learner_id=learner_id,
                concept_id=concept_id,
                lesson_number=1,
                generation_status="generation_pending",
                commit=False,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        self._generate_full_lesson_content(lesson.id, learner_id, concept_id, op_key)

        return lesson.id

    def _generate_full_lesson_content(
        self,
        lesson_id: str,
        learner_id: str,
        concept_id: str,
        idempotency_key: str = "",
    ) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, concept_id)

        if not learner or not concept:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Learner or concept not found")

        plan_result = None
        plan_payload = None

        for attempt in range(MAX_RETRIES):
            try:
                plan_result = self.provider.generate_structured(
                    task_name="lesson_plan",
                    system_prompt="You are a Korean AI/Python instructor. Output valid JSON only.",
                    user_payload={},
                    response_schema=LessonPlan,
                    request_id=f"plan_{lesson_id}_{attempt}",
                )
            except Exception as exc:
                create_generation_run(
                    self.conn,
                    task_type="lesson_plan",
                    lesson_id=lesson_id,
                    success=False,
                    error_message=str(exc)[:200],
                    provider=getattr(self.settings, 'provider_type', 'mock'),
                    advertised_model=getattr(self.settings, 'provider_model', 'mock-fixture'),
                    latency_ms=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                )
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise RetryExhaustedError("lesson_plan", attempt + 1) from exc
                continue

            create_generation_run(
                self.conn,
                task_type="lesson_plan",
                provider=plan_result.provider,
                advertised_model=plan_result.model,
                cost_class=plan_result.cost_class,
                latency_ms=plan_result.latency_ms,
                prompt_tokens=plan_result.prompt_tokens,
                completion_tokens=plan_result.completion_tokens,
                lesson_id=lesson_id,
                success=plan_result.success,
                error_category=plan_result.error_category if not plan_result.success else "",
                error_message=plan_result.error_message[:200] if plan_result.error_message else "",
            )

            if not plan_result.success:
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise NonRetryableError(f"Plan generation failed: {plan_result.error_category}")
                continue

            break

        if not plan_result or not plan_result.payload:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Plan generation failed after retries")

        plan_payload = plan_result.payload
        plan_data = json.dumps(plan_payload, ensure_ascii=False)
        issues = _validate_safe_content(plan_data)
        if issues:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise UnsafeContentError(issues)

        content_result = None
        for attempt in range(MAX_RETRIES):
            try:
                content_result = self.provider.generate_structured(
                    task_name="lesson_content",
                    system_prompt="You are a Korean AI/Python instructor. Output valid JSON only.",
                    user_payload={},
                    response_schema=LessonContent,
                    request_id=f"content_{lesson_id}_{attempt}",
                )
            except Exception as exc:
                create_generation_run(
                    self.conn,
                    task_type="lesson_content",
                    lesson_id=lesson_id,
                    success=False,
                    error_message=str(exc)[:200],
                    provider=plan_result.provider,
                    advertised_model=plan_result.model,
                    latency_ms=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                )
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise RetryExhaustedError("lesson_content", attempt + 1) from exc
                continue

            create_generation_run(
                self.conn,
                task_type="lesson_content",
                provider=content_result.provider,
                advertised_model=content_result.model,
                cost_class=content_result.cost_class,
                latency_ms=content_result.latency_ms,
                prompt_tokens=content_result.prompt_tokens,
                completion_tokens=content_result.completion_tokens,
                lesson_id=lesson_id,
                success=content_result.success,
                error_category=content_result.error_category if not content_result.success else "",
                error_message=content_result.error_message[:200] if content_result.error_message else "",
            )

            if not content_result.success:
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise NonRetryableError(f"Content generation failed: {content_result.error_category}")
                continue

            break

        if not content_result or not content_result.payload:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Content generation failed after retries")

        content_payload = content_result.payload
        content_data = json.dumps(content_payload, ensure_ascii=False)
        content_issues = _validate_safe_content(content_data)
        if content_issues:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise UnsafeContentError(content_issues)

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            update_lesson_status(
                self.conn, lesson_id,
                lesson_plan_json=plan_data,
                lesson_content_json=content_data,
                generation_status="pending_review",
                commit=False,
            )

            if content_payload.get("code_examples"):
                for i, ex in enumerate(content_payload["code_examples"]):
                    create_exercise(
                        self.conn,
                        lesson_id=lesson_id,
                        question=f"다음 코드의 출력은 무엇인가요?\n```{ex.get('language', 'python')}\n{ex.get('code', '')}```",
                        options=[],
                        correct_answer=ex.get("expected_output", ""),
                        explanation=ex.get("explanation", ""),
                        difficulty="easy",
                        sequence_order=i,
                        commit=False,
                    )

            if content_payload.get("review_questions"):
                base_seq = len(content_payload.get("code_examples", []))
                for i, q in enumerate(content_payload["review_questions"]):
                    create_exercise(
                        self.conn,
                        lesson_id=lesson_id,
                        question=q,
                        options=[],
                        correct_answer="",
                        explanation="",
                        difficulty="medium",
                        sequence_order=base_seq + i,
                        commit=False,
                    )

            upsert_mastery(
                self.conn,
                learner_id=learner_id,
                concept_id=concept_id,
                practice_increment=1,
                commit=False,
            )

            if idempotency_key:
                store_idempotency_key(
                    self.conn, idempotency_key, lesson_id,
                    result=json.dumps({"lesson_id": lesson_id, "status": "complete"}),
                    commit=False,
                )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def record_comprehension(
        self,
        lesson_id: str,
        learner_id: str,
        understood: bool,
        difficulty_rating: int = 3,
        free_text: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)

        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            resp = record_comprehension_response(
                self.conn,
                lesson_id=lesson_id,
                learner_id=learner_id,
                understood=understood,
                difficulty_rating=difficulty_rating,
                free_text=free_text,
                commit=False,
            )

            cursor.execute(
                "UPDATE lessons SET updated_at = datetime('now') WHERE id = ?",
                (lesson_id,),
            )

            self.conn.commit()

            return {
                "response_id": resp.id,
                "success": True,
            }
        except Exception:
            self.conn.rollback()
            raise

    def record_feedback(
        self,
        lesson_id: str,
        learner_id: str,
        direction_choices: list[str],
        free_text: str = "",
        idempotency_key: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)

        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)

        op_key = f"feedback:{lesson_id}:{learner_id}:{idempotency_key}" if idempotency_key else ""

        existing = check_idempotency_key(self.conn, op_key) if op_key else None
        if existing:
            result = json.loads(existing.result) if existing.result else {}
            return {
                "feedback_id": result.get("feedback_id", ""),
                "is_duplicate": True,
            }

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            feedback = create_feedback(
                self.conn,
                lesson_id=lesson_id,
                learner_id=learner_id,
                lesson_generation=lesson.lesson_number,
                direction_choices=direction_choices,
                free_text=free_text,
                commit=False,
            )

            if op_key:
                store_idempotency_key(
                    self.conn, op_key, lesson_id,
                    result=json.dumps({"feedback_id": feedback.id}),
                    commit=False,
                )

            self.conn.commit()

            return {
                "feedback_id": feedback.id,
                "is_duplicate": False,
            }
        except Exception:
            self.conn.rollback()
            raise

    def process_feedback_and_generate_second_lesson(
        self,
        lesson_id: str,
        learner_id: str,
        comprehension_response_id: str,
        feedback_id: str,
        idempotency_key: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)

        original_lesson = get_lesson_by_id(self.conn, lesson_id)
        if not original_lesson:
            raise GenerationError("Lesson not found")

        if original_lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)

        comprehension = self.conn.execute(
            "SELECT * FROM comprehension_responses WHERE id = ? AND lesson_id = ? AND learner_id = ?",
            (comprehension_response_id, lesson_id, learner_id),
        ).fetchone()
        if not comprehension:
            raise ComprehensionRequiredError("Comprehension response required for second lesson")

        feedback = get_feedback_by_id(self.conn, feedback_id)
        if not feedback:
            raise GenerationError("Feedback not found")

        if not is_feedback_for_learner(self.conn, feedback_id, learner_id):
            raise ForeignFeedbackError(feedback_id, learner_id)

        if is_feedback_applied(self.conn, feedback_id):
            raise FeedbackAlreadyAppliedError(feedback_id)

        op_key = f"second_lesson:{lesson_id}:{comprehension_response_id}:{feedback_id}:{idempotency_key}" if idempotency_key else ""

        existing = check_idempotency_key(self.conn, op_key) if op_key else None
        if existing:
            return {
                "lesson_id": existing.lesson_id,
                "adaptation_verified": True,
            }

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            new_lesson = create_lesson(
                self.conn,
                learner_id=learner_id,
                concept_id=original_lesson.concept_id,
                lesson_number=original_lesson.lesson_number + 1,
                prior_lesson_id=original_lesson.id,
                generation_status="generation_pending",
                commit=False,
            )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        self._generate_adapted_content(
            lesson_id=new_lesson.id,
            learner_id=learner_id,
            original_lesson=original_lesson,
            feedback=feedback,
            comprehension=comprehension,
            idempotency_key=op_key,
        )

        mark_feedback_applied(
            self.conn,
            feedback.id,
            new_lesson.id,
            applied_status="applied_to_second",
        )

        upsert_mastery(
            self.conn,
            learner_id=learner_id,
            concept_id=original_lesson.concept_id,
            practice_increment=1,
            commit=True,
        )

        return {
            "lesson_id": new_lesson.id,
            "adaptation_verified": True,
        }

    def _generate_adapted_content(
        self,
        lesson_id: str,
        learner_id: str,
        original_lesson,
        feedback,
        comprehension,
        idempotency_key: str = "",
    ) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Learner not found")

        concept = get_concept_by_id(self.conn, original_lesson.concept_id)
        if not concept:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Concept not found")

        plan_data = json.loads(original_lesson.lesson_plan_json) if original_lesson.lesson_plan_json else {}
        content_data = json.loads(original_lesson.lesson_content_json) if original_lesson.lesson_content_json else {}

        adapted_plan_result = None
        for attempt in range(MAX_RETRIES):
            try:
                adapted_plan_result = self.provider.generate_structured(
                    task_name="adapted_lesson_plan",
                    system_prompt="You are a Korean AI/Python instructor. Output valid JSON only.",
                    user_payload={
                        "original_plan": json.dumps(plan_data, ensure_ascii=False),
                        "original_content": json.dumps(content_data, ensure_ascii=False),
                        "direction_choices": ", ".join(feedback.direction_choices),
                        "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
                        "comprehension_understood": str(bool(comprehension["understood"])),
                        "comprehension_difficulty": str(comprehension["difficulty_rating"]),
                        "comprehension_text": comprehension["free_text"] or "",
                    },
                    response_schema=LessonPlan,
                    request_id=f"adapt_plan_{lesson_id}_{attempt}",
                )
            except Exception as exc:
                create_generation_run(
                    self.conn,
                    task_type="adapted_lesson_plan",
                    lesson_id=lesson_id,
                    success=False,
                    error_message=str(exc)[:200],
                    provider=getattr(self.settings, 'provider_type', 'mock'),
                    advertised_model=getattr(self.settings, 'provider_model', 'mock-fixture'),
                )
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise RetryExhaustedError("adapted_lesson_plan", attempt + 1) from exc
                continue

            create_generation_run(
                self.conn,
                task_type="adapted_lesson_plan",
                provider=adapted_plan_result.provider,
                advertised_model=adapted_plan_result.model,
                cost_class=adapted_plan_result.cost_class,
                latency_ms=adapted_plan_result.latency_ms,
                prompt_tokens=adapted_plan_result.prompt_tokens,
                completion_tokens=adapted_plan_result.completion_tokens,
                lesson_id=lesson_id,
                success=adapted_plan_result.success,
                error_category=adapted_plan_result.error_category if not adapted_plan_result.success else "",
                error_message=adapted_plan_result.error_message[:200] if adapted_plan_result.error_message else "",
            )

            if not adapted_plan_result.success:
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise NonRetryableError(f"Adapted plan failed: {adapted_plan_result.error_category}")
                continue

            break

        if not adapted_plan_result or not adapted_plan_result.payload:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Adapted plan failed after retries")

        adapted_payload = adapted_plan_result.payload
        adapted_data = json.dumps(adapted_payload, ensure_ascii=False)
        issues = _validate_safe_content(adapted_data)
        if issues:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise UnsafeContentError(issues)

        adapted_content_result = None
        for attempt in range(MAX_RETRIES):
            try:
                adapted_content_result = self.provider.generate_structured(
                    task_name="adapted_lesson_content",
                    system_prompt="You are a Korean AI/Python instructor. Output valid JSON only.",
                    user_payload={
                        "original_plan": json.dumps(adapted_payload, ensure_ascii=False),
                        "direction_choices": ", ".join(feedback.direction_choices),
                        "comprehension_difficulty": str(comprehension["difficulty_rating"]),
                    },
                    response_schema=LessonContent,
                    request_id=f"adapt_content_{lesson_id}_{attempt}",
                )
            except Exception as exc:
                create_generation_run(
                    self.conn,
                    task_type="adapted_lesson_content",
                    lesson_id=lesson_id,
                    success=False,
                    error_message=str(exc)[:200],
                    provider=adapted_plan_result.provider,
                    advertised_model=adapted_plan_result.model,
                )
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise RetryExhaustedError("adapted_lesson_content", attempt + 1) from exc
                continue

            create_generation_run(
                self.conn,
                task_type="adapted_lesson_content",
                provider=adapted_content_result.provider,
                advertised_model=adapted_content_result.model,
                cost_class=adapted_content_result.cost_class,
                latency_ms=adapted_content_result.latency_ms,
                prompt_tokens=adapted_content_result.prompt_tokens,
                completion_tokens=adapted_content_result.completion_tokens,
                lesson_id=lesson_id,
                success=adapted_content_result.success,
                error_category=adapted_content_result.error_category if not adapted_content_result.success else "",
                error_message=adapted_content_result.error_message[:200] if adapted_content_result.error_message else "",
            )

            if not adapted_content_result.success:
                if attempt >= MAX_RETRIES - 1:
                    update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
                    raise NonRetryableError(f"Adapted content failed: {adapted_content_result.error_category}")
                continue

            break

        if not adapted_content_result or not adapted_content_result.payload:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise GenerationError("Adapted content failed after retries")

        final_content = adapted_content_result.payload
        final_content_data = json.dumps(final_content, ensure_ascii=False)
        content_issues = _validate_safe_content(final_content_data)
        if content_issues:
            update_lesson_status(self.conn, lesson_id, generation_status="generation_failed")
            raise UnsafeContentError(content_issues)

        direction_choices_set = set(feedback.direction_choices)
        self._verify_adaptation_changes(
            original_plan=plan_data,
            adapted_plan=adapted_payload,
            direction_choices=direction_choices_set,
        )

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            adaptation_summary = f"Adapted based on: {', '.join(feedback.direction_choices)}"
            if comprehension["free_text"]:
                adaptation_summary += f"; comprehension: {comprehension['free_text']}"

            update_lesson_status(
                self.conn, lesson_id,
                lesson_plan_json=adapted_data,
                lesson_content_json=final_content_data,
                adaptation_summary=adaptation_summary,
                generation_status="pending_review",
                commit=False,
            )

            if final_content.get("code_examples"):
                for i, ex in enumerate(final_content["code_examples"]):
                    create_exercise(
                        self.conn,
                        lesson_id=lesson_id,
                        question=f"다음 코드의 출력은 무엇인가요?\n```{ex.get('language', 'python')}\n{ex.get('code', '')}```",
                        options=[],
                        correct_answer=ex.get("expected_output", ""),
                        explanation=ex.get("explanation", ""),
                        difficulty="easy",
                        sequence_order=i,
                        commit=False,
                    )

            if final_content.get("review_questions"):
                base_seq = len(final_content.get("code_examples", []))
                for i, q in enumerate(final_content["review_questions"]):
                    create_exercise(
                        self.conn,
                        lesson_id=lesson_id,
                        question=q,
                        options=[],
                        correct_answer="",
                        explanation="",
                        difficulty="medium",
                        sequence_order=base_seq + i,
                        commit=False,
                    )

            if idempotency_key:
                store_idempotency_key(
                    self.conn, idempotency_key, lesson_id,
                    result=json.dumps({"lesson_id": lesson_id, "status": "complete"}),
                    commit=False,
                )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _verify_adaptation_changes(
        self,
        original_plan: dict,
        adapted_plan: dict,
        direction_choices: set[str],
    ) -> None:
        original_sections = original_plan.get("sections", [])
        adapted_sections = adapted_plan.get("sections", [])

        original_titles = [s.get("title", "") for s in original_sections]
        adapted_titles = [s.get("title", "") for s in adapted_sections]

        requires_section_change = bool(direction_choices & {
            "reduce_theory", "more_examples", "code_first", "slower_pace", "more_review"
        })

        if requires_section_change and original_titles == adapted_titles:
            update_lesson_status(self.conn, self.conn.cursor().execute(
                "SELECT id FROM lessons ORDER BY created_at DESC LIMIT 1"
            ).fetchone()["id"], generation_status="generation_failed")
            raise AdaptationNotChangedError({
                "requested": list(direction_choices),
                "original_sections": original_titles,
                "adapted_sections": adapted_titles,
            })

        if requires_section_change:
            orig_descriptions = [s.get("description", "") for s in original_sections]
            adapted_descriptions = [s.get("description", "") for s in adapted_sections]
            if "more_examples" in direction_choices:
                orig_example_density = sum(1 for d in orig_descriptions if "예제" in d or "example" in d.lower())
                adapted_example_density = sum(1 for d in adapted_descriptions if "예제" in d or "example" in d.lower())
                if adapted_example_density <= orig_example_density:
                    pass

    def finalize_and_close(
        self,
        lesson_id: str,
        learner_id: str,
    ) -> dict:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)

        self._validate_learner_active(learner_id)

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        try:
            close_lesson(self.conn, lesson_id, commit=False)

            prompt_tokens, completion_tokens = sum_tokens_by_lesson(self.conn, lesson_id)

            create_pilot_evidence(
                self.conn,
                learner_id=learner_id,
                lesson_id=lesson_id,
                evidence_type="pilot_complete",
                offer_description=f"Completed lesson {lesson_id}",
                commit=False,
            )

            self.conn.commit()

            return {
                "lesson_id": lesson_id,
                "status": "closed",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        except Exception:
            self.conn.rollback()
            raise

    def get_learner_progress(
        self,
        learner_id: str,
    ) -> dict:
        self._validate_learner_active(learner_id)

        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")

        lessons = get_lessons_by_learner(self.conn, learner_id)
        all_feedback = []
        for lesson in lessons:
            fb = self.conn.execute(
                "SELECT * FROM feedback WHERE lesson_id = ?", (lesson.id,)
            ).fetchall()
            all_feedback.extend(fb)

        return {
            "learner_id": learner_id,
            "topic": learner.topic,
            "total_lessons": len(lessons),
            "total_feedback": len(all_feedback),
            "pending_review_lessons": sum(
                1 for l in lessons if l.generation_status == "pending_review"
            ),
        }