"""Generation service orchestrator for Living Travel."""

from __future__ import annotations

import json
import sqlite3

from app.ai.base import AIProvider
from app.domain.enums import (
    EditionGenerationStatus,
    InformationClass,
    SourceConfidence,
)
from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditorialPlan,
    EditionSection,
    InformationItem,
    ProviderResult,
)
from app.edition_repository import (
    create_edition,
    update_edition_content,
    update_edition_generation_status,
)
from app.feedback_repository import (
    get_unapplied_feedback_for_traveler,
    mark_feedback_applied,
)
from app.generation_run_repository import create_generation_run
from app.pipeline.errors import PipelineError
from app.pipeline.markup import reject_if_unsafe
from app.pipeline.prompts import (
    DRAFT_PROMPT_VERSION,
    PLAN_PROMPT_VERSION,
    build_draft_prompt,
    build_plan_prompt,
)
from app.pipeline.validators import (
    validate_draft_against_plan,
    validate_edition_content,
    validate_plan,
)


class GenerationService:
    MAX_RETRIES = 3

    def __init__(self, conn: sqlite3.Connection, provider: AIProvider) -> None:
        self.conn = conn
        self.provider = provider

    def generate_first_edition(
        self,
        *,
        traveler_id: str,
        input_id: str | None = None,
        traveler_preferences: dict,
        source_items: list[dict],
        source_ids: set[str],
    ) -> EditionContent:
        edition = create_edition(
            self.conn,
            traveler_id=traveler_id,
            edition_number=1,
            input_id=input_id,
        )
        update_edition_generation_status(
            self.conn, edition.id, EditionGenerationStatus.generation_pending
        )

        plan_content = self._generate_plan(
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            edition_id=edition.id,
        )

        content = self._generate_draft(
            plan=plan_content,
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            edition_id=edition.id,
        )

        errors = validate_edition_content(content, valid_source_ids=source_ids)
        if errors:
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_failed
            )
            raise PipelineError("Validation failed: " + "; ".join(errors))

        for section in content.sections:
            reject_if_unsafe(section.narrative)

        update_edition_content(self.conn, edition.id, content.model_dump())
        update_edition_generation_status(
            self.conn, edition.id, EditionGenerationStatus.pending_review
        )

        return content

    def generate_second_edition(
        self,
        *,
        traveler_id: str,
        prior_edition: EditionContent,
        traveler_preferences: dict,
        source_items: list[dict],
        source_ids: set[str],
    ) -> EditionContent:
        feedback_records = get_unapplied_feedback_for_traveler(self.conn, traveler_id)
        applied_feedback_list: list[dict] = []
        for fb in feedback_records:
            applied_feedback_list.append(
                {
                    "feedback_id": fb.id,
                    "direction": fb.direction_choices,
                    "free_text": fb.free_text,
                }
            )

        editions = [
            e
            for e in __import__(
                "app.edition_repository", fromlist=["get_editions_by_traveler"]
            ).get_editions_by_traveler(self.conn, traveler_id)
        ]
        next_number = max(e.edition_number for e in editions) + 1 if editions else 2

        edition = create_edition(
            self.conn,
            traveler_id=traveler_id,
            edition_number=next_number,
            prior_edition_id=editions[-1].id if editions else None,
        )
        update_edition_generation_status(
            self.conn, edition.id, EditionGenerationStatus.generation_pending
        )

        plan_content = self._generate_plan(
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            edition_id=edition.id,
            applied_feedback=applied_feedback_list,
        )

        prior_summary = self._edition_summary(prior_edition)

        content = self._generate_draft(
            plan=plan_content,
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            edition_id=edition.id,
            applied_feedback=applied_feedback_list,
            prior_edition_summary=prior_summary,
        )

        errors = validate_edition_content(content, valid_source_ids=source_ids)
        if errors:
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_failed
            )
            raise PipelineError("Validation failed: " + "; ".join(errors))

        for section in content.sections:
            reject_if_unsafe(section.narrative)

        update_edition_content(self.conn, edition.id, content.model_dump())
        update_edition_generation_status(
            self.conn, edition.id, EditionGenerationStatus.pending_review
        )

        for fb in feedback_records:
            mark_feedback_applied(self.conn, fb.id)

        return content

    def _generate_plan(
        self,
        *,
        traveler_preferences: dict,
        source_items: list[dict],
        edition_id: str,
        applied_feedback: list[dict] | None = None,
    ) -> EditorialPlan:
        system, user = build_plan_prompt(
            traveler_preferences=traveler_preferences,
            source_summaries=source_items,
        )

        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_plan_{attempt}"
            result = self.provider.generate_structured(
                task_name="editorial_plan",
                system_prompt=system,
                user_payload={"prompt": user, "applied_feedback": applied_feedback or []},
                response_schema=EditorialPlan,
                request_id=request_id,
            )
            self._record_run(
                result, "editorial_plan", PLAN_PROMPT_VERSION, edition_id
            )
            if result.success:
                plan = EditorialPlan.model_validate(result.payload)
                plan_errors = validate_plan(plan)
                if not plan_errors:
                    return plan
            if attempt == self.MAX_RETRIES - 1:
                raise PipelineError(
                    f"Plan generation failed after {self.MAX_RETRIES} attempts"
                )

        raise PipelineError("Plan generation exhausted retries")

    def _generate_draft(
        self,
        *,
        plan: EditorialPlan,
        traveler_preferences: dict,
        source_items: list[dict],
        edition_id: str,
        applied_feedback: list[dict] | None = None,
        prior_edition_summary: str = "",
    ) -> EditionContent:
        system, user = build_draft_prompt(
            plan=plan.model_dump(),
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            applied_feedback=applied_feedback,
            prior_edition_summary=prior_edition_summary,
        )

        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_draft_{attempt}"
            result = self.provider.generate_structured(
                task_name="edition_draft",
                system_prompt=system,
                user_payload={"prompt": user},
                response_schema=EditionContent,
                request_id=request_id,
            )
            self._record_run(
                result, "edition_draft", DRAFT_PROMPT_VERSION, edition_id
            )
            if result.success:
                content = EditionContent.model_validate(result.payload)
                draft_errors = validate_draft_against_plan(content, plan)
                if not draft_errors:
                    return content
            if attempt == self.MAX_RETRIES - 1:
                raise PipelineError(
                    f"Draft generation failed after {self.MAX_RETRIES} attempts"
                )

        raise PipelineError("Draft generation exhausted retries")

    def _record_run(
        self,
        result: ProviderResult,
        task_type: str,
        prompt_version: str,
        edition_id: str,
    ) -> None:
        create_generation_run(
            self.conn,
            task_type=task_type,
            provider=result.provider,
            advertised_model=result.model,
            cost_class=result.cost_class,
            prompt_version=prompt_version,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            error_category=result.error_category or "",
            error_message=result.error_message,
            edition_id=edition_id,
            success=result.success,
        )

    def _edition_summary(self, content: EditionContent) -> str:
        parts = [content.edition_title, content.editorial_opening]
        for s in content.sections:
            parts.append(f"{s.title}: {s.narrative[:100]}")
        return " | ".join(parts)
