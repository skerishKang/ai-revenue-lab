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
    get_editions_by_traveler,
    update_edition_content,
    update_edition_generation_status,
)
from app.feedback_repository import (
    get_unapplied_feedback_for_traveler,
    mark_feedback_applied,
)
from app.generation_run_repository import create_generation_run
from app.pipeline.errors import PipelineError
from app.pipeline.markup import reject_all_content_fields
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
from app.traveler_repository import is_traveler_active


class GenerationService:
    MAX_RETRIES = 3

    def __init__(self, conn: sqlite3.Connection, provider: AIProvider) -> None:
        self.conn = conn
        self.provider = provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_first_edition(
        self,
        *,
        traveler_id: str,
        input_id: str | None = None,
        traveler_preferences: dict,
        source_items: list[dict],
        source_ids: set[str],
        source_states: dict[str, str] | None = None,
    ) -> EditionContent:
        if not is_traveler_active(self.conn, traveler_id):
            raise PipelineError("Traveler is inactive or deleted")

        self.conn.execute("SAVEPOINT sp_first")
        try:
            edition = create_edition(
                self.conn,
                traveler_id=traveler_id,
                edition_number=1,
                input_id=input_id,
                commit=False,
            )
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_pending,
                commit=False,
            )

            plan_content, plan_runs = self._generate_plan(
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
            )

            content, draft_runs = self._generate_draft(
                plan=plan_content,
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
            )

            # Record ALL generation runs (including retries/failures) for accounting
            self._record_run_batch(plan_runs + draft_runs, edition.id, commit=False)

            errors = validate_edition_content(
                content, valid_source_ids=source_ids, source_states=source_states,
            )
            if errors:
                raise PipelineError("Validation failed: " + "; ".join(errors))

            reject_all_content_fields(content)

            update_edition_content(self.conn, edition.id, content.model_dump(), commit=False)
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.pending_review,
                commit=False,
            )
            self.conn.execute("RELEASE SAVEPOINT sp_first")
            self.conn.commit()
            return content
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT sp_first")
            raise

    def generate_second_edition(
        self,
        *,
        traveler_id: str,
        prior_edition: EditionContent,
        traveler_preferences: dict,
        source_items: list[dict],
        source_ids: set[str],
        source_states: dict[str, str] | None = None,
    ) -> EditionContent:
        if not is_traveler_active(self.conn, traveler_id):
            raise PipelineError("Traveler is inactive or deleted")

        feedback_records = get_unapplied_feedback_for_traveler(self.conn, traveler_id)
        if not feedback_records:
            raise PipelineError("No unapplied feedback for traveler")

        applied_feedback_list: list[dict] = []
        for fb in feedback_records:
            applied_feedback_list.append(
                {
                    "feedback_id": fb.id,
                    "direction": fb.direction_choices,
                    "free_text": fb.free_text,
                }
            )

        editions = get_editions_by_traveler(self.conn, traveler_id)
        if not editions:
            raise PipelineError("No prior editions found for traveler")

        prior_edition_record = editions[-1]
        next_number = prior_edition_record.edition_number + 1

        self.conn.execute("SAVEPOINT sp_second")
        try:
            edition = create_edition(
                self.conn,
                traveler_id=traveler_id,
                edition_number=next_number,
                prior_edition_id=prior_edition_record.id,
                commit=False,
            )
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_pending,
                commit=False,
            )

            plan_content, plan_runs = self._generate_plan(
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                applied_feedback=applied_feedback_list,
            )

            prior_summary = self._edition_summary(prior_edition)

            content, draft_runs = self._generate_draft(
                plan=plan_content,
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                applied_feedback=applied_feedback_list,
                prior_edition_summary=prior_summary,
            )

            # Record ALL generation runs (including retries/failures) for accounting
            self._record_run_batch(plan_runs + draft_runs, edition.id, commit=False)

            errors = validate_edition_content(
                content, valid_source_ids=source_ids, source_states=source_states,
            )
            if errors:
                raise PipelineError("Validation failed: " + "; ".join(errors))

            reject_all_content_fields(content)

            update_edition_content(self.conn, edition.id, content.model_dump(), commit=False)
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.pending_review,
                commit=False,
            )
            for fb in feedback_records:
                mark_feedback_applied(self.conn, fb.id, commit=False)
            self.conn.execute("RELEASE SAVEPOINT sp_second")
            self.conn.commit()
            return content
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT sp_second")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_plan(
        self,
        *,
        traveler_preferences: dict,
        source_items: list[dict],
        edition_id: str,
        applied_feedback: list[dict] | None = None,
    ) -> tuple[EditorialPlan, list[tuple[ProviderResult, str]]]:
        system, user = build_plan_prompt(
            traveler_preferences=traveler_preferences,
            source_summaries=source_items,
        )

        runs: list[tuple[ProviderResult, str]] = []
        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_plan_{attempt}"
            result = self.provider.generate_structured(
                task_name="editorial_plan",
                system_prompt=system,
                user_payload={"prompt": user, "applied_feedback": applied_feedback or []},
                response_schema=EditorialPlan,
                request_id=request_id,
            )
            runs.append((result, PLAN_PROMPT_VERSION))
            if result.success:
                plan = EditorialPlan.model_validate(result.payload)
                plan_errors = validate_plan(plan)
                if not plan_errors:
                    return plan, runs
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
    ) -> tuple[EditionContent, list[tuple[ProviderResult, str]]]:
        system, user = build_draft_prompt(
            plan=plan.model_dump(),
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            applied_feedback=applied_feedback,
            prior_edition_summary=prior_edition_summary,
        )

        runs: list[tuple[ProviderResult, str]] = []
        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_draft_{attempt}"
            result = self.provider.generate_structured(
                task_name="edition_draft",
                system_prompt=system,
                user_payload={"prompt": user},
                response_schema=EditionContent,
                request_id=request_id,
            )
            runs.append((result, DRAFT_PROMPT_VERSION))
            if result.success:
                content = EditionContent.model_validate(result.payload)
                draft_errors = validate_draft_against_plan(content, plan)
                if not draft_errors:
                    return content, runs
            if attempt == self.MAX_RETRIES - 1:
                raise PipelineError(
                    f"Draft generation failed after {self.MAX_RETRIES} attempts"
                )

        raise PipelineError("Draft generation exhausted retries")

    def _record_run_batch(
        self,
        runs: list[tuple[ProviderResult, str]],
        edition_id: str,
        *,
        commit: bool = True,
    ) -> None:
        """Record all generation runs from a batch (including retries/failures)."""
        for result, prompt_version in runs:
            create_generation_run(
                self.conn,
                task_type="editorial_plan" if prompt_version == PLAN_PROMPT_VERSION else "edition_draft",
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
                commit=commit,
            )

    def _edition_summary(self, content: EditionContent) -> str:
        parts = [content.edition_title, content.editorial_opening]
        for s in content.sections:
            parts.append(f"{s.title}: {s.narrative[:100]}")
        return " | ".join(parts)
