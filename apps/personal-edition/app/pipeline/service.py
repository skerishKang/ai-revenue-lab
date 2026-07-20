"""Provider-neutral generation service orchestrating the Phase 3 pipeline.

This service ties together segmentation, the AIProvider boundary, deterministic
plan/draft validation, grounding, markup rejection, bounded retry, normalized
provider-error handling, generation-run accounting, and durable pending_review
persistence. It does NOT auto-publish or auto-reject.

Pipeline stages (PERSONAL_EDITION_MVP_ARCHITECTURE.md section 9):

1. Normalize and segment the participant input deterministically.
2. Call the provider for an editorial plan (bounded retry).
3. Validate the plan against the known segments and continuity rules.
4. Call the provider for an edition draft (bounded retry), passing the accepted
   plan and segments.
5. Validate the draft (structure, references, continuity, grounding, markup).
6. Persist a new edition only after all validation passes, then durably mark
   any applied feedback.

Transaction ownership policy (PERSONAL_EDITION_MVP_ARCHITECTURE.md section 12):
repositories control commit/rollback and require an idle connection. The
service issues each repository write on an idle connection and never calls
conn.commit() or conn.rollback() directly. A failure before durable completion
leaves the prior edition untouched and feedback unapplied.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app import generation_run_repository as gr_repo
from app import input_repository as input_repo
from app import participant_repository as pt_repo
from app.ai.base import AIProvider
from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import (
    EditionContent,
    EditorialPlan,
    InputSegment,
    ParticipantPreferences,
)
from app.pipeline import grounding as grounding_mod
from app.pipeline import markup as markup_mod
from app.pipeline import prompts
from app.pipeline import validators
from app.pipeline.errors import (
    NOT_ATTEMPTED,
    PROVIDER_FAILED,
    PipelineError,
    PlanValidationError,
    DraftValidationError,
    ProviderCallError,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    is_retryable,
    safe_error_message,
)
from app.pipeline.segmentation import segment_text

DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs for a single generation run (first or follow-up edition)."""

    participant_id: str
    input_id: str
    is_follow_up: bool = False
    prior_edition_id: str | None = None
    feedback_id: str | None = None
    feedback_directions: tuple[str, ...] = ()
    feedback_free_text: str | None = None
    prior_edition_summary: dict[str, Any] | None = None
    prohibited_inferences: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageOutcome:
    """Result of one provider call stage, recorded in generation-run accounting."""

    success: bool
    validation_status: str
    retry_count: int
    payload: dict[str, Any] | None = None
    error_category: str | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    """Final outcome of a generation run."""

    edition_id: str | None
    plan_run: StageOutcome
    draft_run: StageOutcome
    succeeded: bool

    @property
    def validation_status(self) -> str:
        if not self.succeeded:
            return VALIDATION_FAILED
        return VALIDATION_PASSED


def _new_request_id() -> str:
    return str(uuid.uuid4())


def _segment_list(segments: list[InputSegment]) -> list[dict[str, Any]]:
    return [
        {
            "segment_id": s.segment_id,
            "start_offset": s.start_offset,
            "end_offset": s.end_offset,
            "text": s.text,
        }
        for s in segments
    ]


def _provider_call_with_retry(
    *,
    provider: AIProvider,
    task_name: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    response_schema: type,
    max_retries: int,
    prompt_version: str,
    conn,
    participant_id: str,
    run_kind: str,
) -> tuple[Any | None, StageOutcome]:
    """Call the provider with bounded retry and record accounting per attempt.

    Returns (validated_model_or_None, stage_outcome). On exhaustion the outcome
    is a failure and the model is None.
    """
    last_error_category: ProviderErrorCategory | None = None
    last_error_message: str | None = None
    attempts = 0

    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        request_id = _new_request_id()
        try:
            result = provider.generate_structured(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                request_id=request_id,
            )
        except Exception as exc:
            category = ProviderErrorCategory.UNKNOWN
            last_error_category = category
            last_error_message = safe_error_message(category, str(exc))
            run = _record_run(
                conn,
                participant_id,
                task_name,
                provider,
                prompt_version,
                success=False,
                validation_status=PROVIDER_FAILED,
                retry_count=attempt,
                error_category=category,
                error_message=last_error_message,
            )
            _ = run
            if not is_retryable(category) or attempt >= max_retries:
                return None, StageOutcome(
                    success=False,
                    validation_status=PROVIDER_FAILED,
                    retry_count=attempt,
                    error_category=category,
                    error_message=last_error_message,
                )
            continue

        if result.success and result.payload is not None:
            try:
                validated = response_schema.model_validate(result.payload)
            except Exception as exc:
                last_error_category = ProviderErrorCategory.SCHEMA_MISMATCH
                last_error_message = safe_error_message(
                    last_error_category, str(exc)
                )
                _record_run(
                    conn,
                    participant_id,
                    task_name,
                    provider,
                    prompt_version,
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=attempt,
                    error_category=last_error_category,
                    error_message=last_error_message,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
                if attempt >= max_retries:
                    return None, StageOutcome(
                        success=False,
                        validation_status=VALIDATION_FAILED,
                        retry_count=attempt,
                        error_category=last_error_category,
                        error_message=last_error_message,
                    )
                continue

            _record_run(
                conn,
                participant_id,
                task_name,
                provider,
                prompt_version,
                success=True,
                validation_status=VALIDATION_PASSED,
                retry_count=attempt,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )
            return validated, StageOutcome(
                success=True,
                validation_status=VALIDATION_PASSED,
                retry_count=attempt,
                payload=result.payload,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )

        last_error_category = result.error_category or ProviderErrorCategory.UNKNOWN
        last_error_message = safe_error_message(
            last_error_category, result.error_message
        )
        _record_run(
            conn,
            participant_id,
            task_name,
            provider,
            prompt_version,
            success=False,
            validation_status=PROVIDER_FAILED,
            retry_count=attempt,
            error_category=last_error_category,
            error_message=last_error_message,
            input_tokens=result.usage.input_tokens if result.usage else None,
            output_tokens=result.usage.output_tokens if result.usage else None,
        )
        if not is_retryable(last_error_category) or attempt >= max_retries:
            return None, StageOutcome(
                success=False,
                validation_status=PROVIDER_FAILED,
                retry_count=attempt,
                error_category=last_error_category,
                error_message=last_error_message,
            )

    return None, StageOutcome(
        success=False,
        validation_status=PROVIDER_FAILED,
        retry_count=max_retries,
        error_category=last_error_category,
        error_message=last_error_message or "provider retries exhausted",
    )


def _record_run(
    conn,
    participant_id: str,
    task_type: str,
    provider: AIProvider,
    prompt_version: str,
    *,
    success: bool,
    validation_status: str,
    retry_count: int,
    error_category: ProviderErrorCategory | None = None,
    error_message: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
):
    """Create and finalize a generation_run row for one provider attempt."""
    run = gr_repo.create_generation_run(
        conn,
        task_type=task_type,
        provider=_provider_name(provider),
        advertised_model=_provider_model(provider),
        cost_class=CostClass.FREE.value,
        prompt_version=prompt_version,
    )
    gr_repo.update_generation_run(
        conn,
        run.id,
        completed_at=None,
        success=1 if success else 0,
        validation_status=validation_status,
        retry_count=retry_count,
        error_category=(
            error_category.value if error_category is not None else None
        ),
        error_message=error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return run


def _provider_name(provider: AIProvider) -> str:
    name = getattr(provider, "provider", None)
    if isinstance(name, str) and name:
        return name
    return provider.__class__.__name__.lower()


def _provider_model(provider: AIProvider) -> str:
    model = getattr(provider, "model", None)
    if isinstance(model, str) and model:
        return model
    return "unknown"


class GenerationService:
    """Orchestrates the full Phase 3 generation pipeline.

    The service is stateless apart from its collaborators (provider, retry
    budget). Each call to :meth:`generate_edition` performs a complete
    plan -> draft -> validate -> persist run.
    """

    def __init__(
        self,
        *,
        provider: AIProvider,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._provider = provider
        self._max_retries = max_retries

    def generate_edition(
        self,
        conn,
        *,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Run the full pipeline for one edition (first or follow-up)."""
        # Stage 1: load and validate the participant + input before any
        # provider call. Invalid input fails before any provider call.
        participant = pt_repo.get_participant_by_id(conn, request.participant_id)
        if participant is None or participant.status != "active":
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("participant not active"),
                draft_run=_failed_outcome("participant not active"),
                succeeded=False,
            )

        input_record = input_repo.get_input_by_id(conn, request.input_id)
        if input_record is None:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("input not found"),
                draft_run=_failed_outcome("input not found"),
                succeeded=False,
            )
        if input_record.participant_id != request.participant_id:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("input belongs to another participant"),
                draft_run=_failed_outcome("input belongs to another participant"),
                succeeded=False,
            )
        if input_record.deleted_at is not None:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("input is deleted"),
                draft_run=_failed_outcome("input is deleted"),
                succeeded=False,
            )
        if input_record.consent_confirmed != 1:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("consent not confirmed"),
                draft_run=_failed_outcome("consent not confirmed"),
                succeeded=False,
            )

        language = participant.preferred_language
        preferences = ParticipantPreferences()

        segments = segment_text(
            input_record.normalized_text or input_record.raw_text
        )

        prohibited_inferences = list(request.prohibited_inferences)

        # Stage 2: editorial plan (bounded retry).
        plan_system = prompts.build_plan_system_prompt(language)
        plan_payload = prompts.build_plan_user_payload(
            participant_id=request.participant_id,
            segments=segments,
            preferences=preferences,
            language=language,
            is_follow_up=request.is_follow_up,
            feedback_id=request.feedback_id,
            feedback_directions=list(request.feedback_directions),
            feedback_free_text=request.feedback_free_text,
            prior_edition_summary=request.prior_edition_summary,
            prohibited_inferences=prohibited_inferences,
        )

        plan, plan_outcome = _provider_call_with_retry(
            provider=self._provider,
            task_name=prompts.TASK_EDITORIAL_PLAN,
            system_prompt=plan_system,
            user_payload=plan_payload,
            response_schema=EditorialPlan,
            max_retries=self._max_retries,
            prompt_version=prompts.PLAN_PROMPT_VERSION,
            conn=conn,
            participant_id=request.participant_id,
            run_kind="plan",
        )

        if plan is None:
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=_failed_outcome("plan stage failed"),
                succeeded=False,
            )

        # Stage 3: validate the plan.
        try:
            validators.validate_plan(
                plan,
                segments=segments,
                is_follow_up=request.is_follow_up,
                feedback_id=request.feedback_id,
            )
        except PlanValidationError as exc:
            _record_validation_failure(
                conn,
                request.participant_id,
                prompts.TASK_EDITORIAL_PLAN,
                prompts.PLAN_PROMPT_VERSION,
                str(exc),
                self._provider,
            )
            return GenerationResult(
                edition_id=None,
                plan_run=StageOutcome(
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=plan_outcome.retry_count,
                    error_category="validation_failed",
                    error_message=str(exc),
                ),
                draft_run=_failed_outcome("plan validation failed"),
                succeeded=False,
            )

        # Stage 4: edition draft (bounded retry).
        draft_system = prompts.build_draft_system_prompt(language)
        draft_payload = prompts.build_draft_user_payload(
            participant_id=request.participant_id,
            segments=segments,
            plan=plan,
            language=language,
            is_follow_up=request.is_follow_up,
            feedback_id=request.feedback_id,
            prohibited_inferences=prohibited_inferences,
        )

        draft, draft_outcome = _provider_call_with_retry(
            provider=self._provider,
            task_name=prompts.TASK_EDITION_DRAFT,
            system_prompt=draft_system,
            user_payload=draft_payload,
            response_schema=EditionContent,
            max_retries=self._max_retries,
            prompt_version=prompts.DRAFT_PROMPT_VERSION,
            conn=conn,
            participant_id=request.participant_id,
            run_kind="draft",
        )

        if draft is None:
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=draft_outcome,
                succeeded=False,
            )

        # Stage 5: validate the draft (structure, references, continuity,
        # grounding, markup).
        try:
            validators.validate_draft(
                draft,
                plan=plan,
                segments=segments,
                is_follow_up=request.is_follow_up,
                feedback_id=request.feedback_id,
            )
            visible_fields = validators.collect_visible_fields(draft)
            markup_mod.check_payload(draft.model_dump())
            policy = grounding_mod.GroundingPolicy(
                prohibited_tokens=frozenset(prohibited_inferences)
                if prohibited_inferences
                else frozenset()
            )
            grounding_mod.check_grounding(
                policy=policy,
                visible_fields=visible_fields,
            )
        except (DraftValidationError, markup_mod.UnsafeMarkupError,
                grounding_mod.GroundingError) as exc:
            _record_validation_failure(
                conn,
                request.participant_id,
                prompts.TASK_EDITION_DRAFT,
                prompts.DRAFT_PROMPT_VERSION,
                str(exc),
                self._provider,
            )
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=StageOutcome(
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=draft_outcome.retry_count,
                    error_category="validation_failed",
                    error_message=str(exc),
                ),
                succeeded=False,
            )

        # Stage 6: persist a new edition only after complete validation.
        edition_number = self._next_edition_number(conn, request.participant_id)
        structured_content = draft.model_dump_json()
        rendered_title = draft.edition_title

        new_edition = ed_repo.create_edition(
            conn,
            participant_id=request.participant_id,
            edition_number=edition_number,
            prior_edition_id=request.prior_edition_id,
            input_id=request.input_id,
            structured_content=structured_content,
            rendered_title=rendered_title,
        )

        # Feedback is marked applied only after the new valid edition is
        # durably stored.
        if request.is_follow_up and request.feedback_id is not None:
            fb_repo.mark_feedback_applied(conn, request.feedback_id)

        return GenerationResult(
            edition_id=new_edition.id,
            plan_run=plan_outcome,
            draft_run=draft_outcome,
            succeeded=True,
        )

    def _next_edition_number(self, conn, participant_id: str) -> int:
        existing = ed_repo.get_editions_by_participant(conn, participant_id)
        if not existing:
            return 1
        return max(e.edition_number for e in existing) + 1


def _failed_outcome(message: str) -> StageOutcome:
    return StageOutcome(
        success=False,
        validation_status=NOT_ATTEMPTED,
        retry_count=0,
        error_category="not_attempted",
        error_message=message,
    )


def _record_validation_failure(
    conn,
    participant_id: str,
    task_type: str,
    prompt_version: str,
    message: str,
    provider: AIProvider,
) -> None:
    _record_run(
        conn,
        participant_id,
        task_type,
        provider,
        prompt_version,
        success=False,
        validation_status=VALIDATION_FAILED,
        retry_count=0,
        error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
        error_message=safe_error_message(
            ProviderErrorCategory.SCHEMA_MISMATCH, message
        ),
    )
