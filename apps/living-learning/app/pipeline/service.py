"""Living Learning pipeline service with atomic transactions."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from app.domain.models import (
    AdaptationDecision,
    ComprehensionResponse,
    Feedback,
    LessonContent,
    LessonPlan,
    LessonPlanSection,
    ProviderResult,
)
from app.repositories import (
    check_idempotency_key,
    close_lesson,
    create_curriculum,
    create_feedback,
    create_generation_run,
    create_learner,
    create_lesson,
    create_pilot_evidence,
    create_exercise,
    get_concept_by_id,
    get_feedback_by_id,
    get_feedback_by_lesson,
    get_learner_by_id,
    get_lesson_by_id,
    get_lessons_by_learner,
    get_unapplied_feedback_for_lesson,
    is_feedback_applied,
    is_feedback_for_learner,
    mark_feedback_applied,
    record_comprehension_response,
    record_exercise_response,
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
)
from app.pipeline.prompts import (
    ADAPTED_LESSON_PROMPT,
    EXERCISE_PROMPT,
    LESSON_CONTENT_PROMPT,
    LESSON_PLAN_PROMPT,
)

if TYPE_CHECKING:
    from app.ai.base import AIProvider

MAX_RETRIES = 3


class LessonPipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: AIProvider,
    ) -> None:
        self.conn = conn
        self.provider = provider

    def create_learner_and_session(
        self,
        topic: str,
        **preferences,
    ) -> tuple[str, str]:
        from app.repositories import create_curriculum, create_concept, upsert_mastery

        learner = create_learner(self.conn, topic=topic, **preferences)
        curricula = create_curriculum(self.conn, topic=topic)

        concept_map = {
            "변수": ("variables", ["변수", "값"]),
            "값": ("values", ["값"]),
            "간단한 조건문": ("conditionals", ["변수", "값"]),
            "Python 예제": ("python_example", ["변수", "값", "간단한 조건문"]),
        }

        for korean_name, (eng_name, prereqs) in concept_map.items():
            concept = create_concept(
                self.conn,
                curriculum_id=curricula.id,
                name=eng_name,
                description=f"Initial concept: {korean_name}",
                prerequisites=[],
                sequence_order=len(concept_map) - 1,
            )
            upsert_mastery(self.conn, learner_id=learner.id, concept_id=concept.id)

        return learner.id, curricula.id

    def start_first_lesson(
        self,
        learner_id: str,
        concept_id: str,
        idempotency_key: str = "",
    ) -> str:
        existing = check_idempotency_key(self.conn, idempotency_key) if idempotency_key else None
        if existing:
            return existing.lesson_id

        valid, missing = validate_prerequisites(self.conn, concept_id, learner_id)
        if not valid:
            raise PrerequisiteNotMetError(concept_id, missing)

        lesson = create_lesson(
            self.conn,
            learner_id=learner_id,
            concept_id=concept_id,
            lesson_number=1,
            generation_status="generation_pending",
        )

        if idempotency_key:
            store_idempotency_key(self.conn, idempotency_key, lesson.id)

        self._generate_lesson_plan(lesson.id, learner_id, concept_id)

        return lesson.id

    def _generate_lesson_plan(
        self,
        lesson_id: str,
        learner_id: str,
        concept_id: str,
        attempt: int = 0,
    ) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, concept_id)

        if not learner or not concept:
            raise GenerationError("Learner or concept not found")

        prompt = LESSON_PLAN_PROMPT.format(
            topic=learner.topic,
            concept_name=concept.name,
            example_preference=learner.example_preference,
            theory_density=learner.theory_density,
            jargon_level=learner.jargon_level,
            review_question_count=learner.review_question_count,
        )

        system_prompt = "You are a Korean AI/Python instructor. Output valid JSON only."

        try:
            result = self.provider.generate_structured(
                task_name="lesson_plan",
                system_prompt=system_prompt,
                user_payload={},
                response_schema=LessonPlan,
                request_id=f"plan_{lesson_id}_{attempt}",
            )
        except Exception as exc:
            if attempt >= MAX_RETRIES - 1:
                update_lesson_status(
                    self.conn, lesson_id,
                    generation_status="generation_failed",
                )
                create_generation_run(
                    self.conn,
                    task_type="lesson_plan",
                    lesson_id=lesson_id,
                    success=False,
                    error_message=str(exc),
                )
                raise RetryExhaustedError("lesson_plan", attempt + 1) from exc
            return self._generate_lesson_plan(
                lesson_id, learner_id, concept_id, attempt + 1
            )

        create_generation_run(
            self.conn,
            task_type="lesson_plan",
            provider=result.provider,
            advertised_model=result.model,
            cost_class=result.cost_class,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            lesson_id=lesson_id,
            success=result.success,
            error_category=result.error_category if not result.success else "",
            error_message=result.error_message if not result.success else "",
        )

        if result.success and result.payload:
            plan_data = json.dumps(result.payload, ensure_ascii=False)
            update_lesson_status(
                self.conn, lesson_id,
                lesson_plan_json=plan_data,
                generation_status="pending_review",
            )

    def record_feedback(
        self,
        lesson_id: str,
        learner_id: str,
        direction_choices: list[str],
        free_text: str = "",
        idempotency_key: str = "",
    ) -> str:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        existing_key = check_idempotency_key(self.conn, idempotency_key) if idempotency_key else None
        if existing_key:
            return existing_key.lesson_id

        feedback = create_feedback(
            self.conn,
            lesson_id=lesson_id,
            learner_id=learner_id,
            lesson_generation=lesson.lesson_number,
            direction_choices=direction_choices,
            free_text=free_text,
        )

        if idempotency_key:
            store_idempotency_key(self.conn, idempotency_key, lesson_id)

        return feedback.id

    def process_feedback_and_generate_second_lesson(
        self,
        feedback_id: str,
        learner_id: str,
        idempotency_key: str = "",
    ) -> str:
        feedback = get_feedback_by_id(self.conn, feedback_id)
        if not feedback:
            raise GenerationError("Feedback not found")

        if not is_feedback_for_learner(self.conn, feedback_id, learner_id):
            raise ForeignFeedbackError(feedback_id, learner_id)

        if is_feedback_applied(self.conn, feedback_id):
            raise FeedbackAlreadyAppliedError(feedback_id)

        original_lesson = get_lesson_by_id(self.conn, feedback.lesson_id)
        if not original_lesson:
            raise GenerationError("Original lesson not found")

        existing_key = check_idempotency_key(self.conn, idempotency_key) if idempotency_key else None
        if existing_key:
            return existing_key.lesson_id

        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, original_lesson.concept_id)

        new_lesson = create_lesson(
            self.conn,
            learner_id=learner_id,
            concept_id=original_lesson.concept_id,
            lesson_number=original_lesson.lesson_number + 1,
            prior_lesson_id=original_lesson.id,
            generation_status="generation_pending",
        )

        if idempotency_key:
            store_idempotency_key(self.conn, idempotency_key, new_lesson.id)

        self._generate_adapted_lesson(
            new_lesson.id,
            learner_id,
            concept,
            original_lesson.lesson_plan_json,
            feedback,
        )

        mark_feedback_applied(
            self.conn,
            feedback_id,
            new_lesson.id,
            applied_status="applied_to_second",
        )

        return new_lesson.id

    def _generate_adapted_lesson(
        self,
        lesson_id: str,
        learner_id: str,
        concept,
        original_plan_json: str,
        feedback,
        attempt: int = 0,
    ) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")

        plan_data = json.loads(original_plan_json) if original_plan_json else {}

        prompt_vars = {
            "original_plan": json.dumps(plan_data, ensure_ascii=False),
            "direction_choices": ", ".join(feedback.direction_choices),
            "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
        }
        prompt = ADAPTED_LESSON_PROMPT.format(**prompt_vars)

        try:
            result = self.provider.generate_structured(
                task_name="adapted_lesson",
                system_prompt="You are a Korean AI/Python instructor. Output valid JSON only.",
                user_payload={},
                response_schema=LessonPlan,
                request_id=f"adapt_{lesson_id}_{attempt}",
            )
        except Exception as exc:
            if attempt >= MAX_RETRIES - 1:
                update_lesson_status(
                    self.conn, lesson_id,
                    generation_status="generation_failed",
                )
                raise RetryExhaustedError("adapted_lesson", attempt + 1) from exc
            return self._generate_adapted_lesson(
                lesson_id, learner_id, concept, original_plan_json, feedback, attempt + 1
            )

        create_generation_run(
            self.conn,
            task_type="adapted_lesson",
            provider=result.provider,
            advertised_model=result.model,
            cost_class=result.cost_class,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            lesson_id=lesson_id,
            success=result.success,
            error_category=result.error_category if not result.success else "",
            error_message=result.error_message if not result.success else "",
        )

        if result.success and result.payload:
            plan_data = json.dumps(result.payload, ensure_ascii=False)
            adaptation_summary = f"Adapted based on: {', '.join(feedback.direction_choices)}"
            update_lesson_status(
                self.conn, lesson_id,
                lesson_plan_json=plan_data,
                adaptation_summary=adaptation_summary,
                generation_status="pending_review",
            )

    def record_comprehension(
        self,
        lesson_id: str,
        learner_id: str,
        understood: bool,
        difficulty_rating: int = 3,
        free_text: str = "",
    ) -> str:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        resp = record_comprehension_response(
            self.conn,
            lesson_id=lesson_id,
            learner_id=learner_id,
            understood=understood,
            difficulty_rating=difficulty_rating,
            free_text=free_text,
        )
        return resp.id

    def finalize_and_close(
        self,
        lesson_id: str,
    ) -> dict:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")

        close_lesson(self.conn, lesson_id)

        prompt_tokens, completion_tokens = sum_tokens_by_lesson(self.conn, lesson_id)

        create_pilot_evidence(
            self.conn,
            learner_id=lesson.learner_id,
            lesson_id=lesson_id,
            evidence_type="pilot_complete",
            offer_description=f"Completed lesson {lesson_id}",
        )

        return {
            "lesson_id": lesson_id,
            "status": "closed",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    def get_learner_progress(
        self,
        learner_id: str,
    ) -> dict:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")

        lessons = get_lessons_by_learner(self.conn, learner_id)
        all_feedback = []
        for lesson in lessons:
            fb = get_feedback_by_lesson(self.conn, lesson.id)
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