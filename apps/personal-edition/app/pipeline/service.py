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

import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app import generation_run_repository as gr_repo
from app import input_repository as input_repo
from app import participant_repository as pt_repo
from app.db_runtime import SqliteRuntimeConnection
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


def count_words(text: str, language: str) -> int:
    """Deterministic language-aware word count.

    For English: whitespace-delimited tokens.
    For Korean: each non-whitespace, non-punctuation character counts as one
    word-equivalent (Korean lacks reliable whitespace word boundaries).
    """
    if language == "ko":
        count = 0
        for ch in text:
            if ch.isspace() or unicodedata.category(ch).startswith("P"):
                continue
            count += 1
        return count
    return len(text.split())


MIN_INPUT_WORDS = 500
MAX_INPUT_WORDS = 5000


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs for a single generation run (first or follow-up edition)."""

    participant_id: str
    input_id: str
    is_follow_up: bool = False
    prior_edition_id: str | None = None
    feedback_id: str | None = None
    prohibited_inferences: tuple[str, ...] = ()
    allow_short_sample: bool = False


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
    completed_at: str | None = None
    latency_seconds: float | None = None
    provider: str | None = None
    model: str | None = None
    cost_class: str | None = None
    run_id: str | None = None


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


@dataclass(frozen=True)
class RepairRequest:
    """Provider-neutral contract for a validator-feedback repair call.

    The corrupted candidate plus privacy-safe, normalized validator findings
    and a concise repair instruction are sent to the same configured provider
    that produced the original candidate. No raw private participant input is
    included.

    ``allowed_segment_ids`` and ``allowed_plan_section_ids`` form the
    privacy-safe reference universe: only these IDs (never segment text,
    participant input, or profile fields) may appear in the repaired draft.
    They are supplied in deterministic sorted order and must be non-empty. The
    repaired draft is rejected if it references any id outside these sets.

    Both sets are required and fail closed at construction: a repair request
    without an authoritative reference universe is rejected rather than silently
    skipping reference-universe enforcement.
    """

    participant_id: str
    input_id: str
    corrupted_candidate: dict[str, Any]
    validator_findings: list[dict[str, Any]]
    repair_instruction: str
    correlation_id: str
    attempt_id: str
    prohibited_inferences: tuple[str, ...] = ()
    allowed_segment_ids: tuple[str, ...] = ()
    allowed_plan_section_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.allowed_segment_ids:
            raise ValueError(
                "RepairRequest.allowed_segment_ids must be a non-empty "
                "authoritative reference universe"
            )
        if not self.allowed_plan_section_ids:
            raise ValueError(
                "RepairRequest.allowed_plan_section_ids must be a non-empty "
                "authoritative reference universe"
            )


@dataclass(frozen=True)
class RepairOutcome:
    """Result of a single repair provider call plus deterministic validation."""

    succeeded: bool
    validation_status: str
    content: EditionContent | None
    error_category: str | None
    error_message: str | None
    retry_count: int
    input_tokens: int | None
    output_tokens: int | None
    latency_seconds: float | None
    provider: str | None
    model: str | None
    cost_class: str | None
    run_id: str | None


@dataclass(frozen=True)
class RepairCandidate:
    """A successfully generated (pre-corruption) candidate with its context."""

    succeeded: bool
    content: EditionContent | None
    plan: EditorialPlan | None
    segments: list[InputSegment]
    plan_outcome: StageOutcome
    draft_outcome: StageOutcome


def _new_request_id() -> str:
    return str(uuid.uuid4())


def _now_utc() -> str:
    return pt_repo._now_utc_iso()


def _parse_utc_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")


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
) -> tuple[Any | None, StageOutcome]:
    """Call the provider with bounded retry and record one accounting row per stage.

    Returns (validated_model_or_None, stage_outcome). On exhaustion the outcome
    is a failure and the model is None. A single generation_run row is created
    and updated to cover the entire stage, including deterministic validation
    failures.
    """
    started_at = _now_utc()

    last_error_category: ProviderErrorCategory | None = None
    last_error_message: str | None = None
    last_result = None
    last_validated = None
    validation_status = PROVIDER_FAILED
    input_tokens: int | None = None
    output_tokens: int | None = None

    for attempt in range(max_retries + 1):
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
            last_error_category = ProviderErrorCategory.UNKNOWN
            last_error_message = safe_error_message(
                last_error_category, str(exc)
            )
            last_result = None
            if not is_retryable(last_error_category) or attempt >= max_retries:
                break
            continue

        last_result = result
        if result.usage:
            if result.usage.input_tokens is not None:
                input_tokens = (input_tokens or 0) + result.usage.input_tokens
            if result.usage.output_tokens is not None:
                output_tokens = (output_tokens or 0) + result.usage.output_tokens

        if result.success and result.payload is not None:
            try:
                validated = response_schema.model_validate(result.payload)
                last_validated = validated
                validation_status = VALIDATION_PASSED
                last_error_category = None
                last_error_message = None
                break
            except Exception as exc:
                last_error_category = ProviderErrorCategory.SCHEMA_MISMATCH
                last_error_message = safe_error_message(
                    last_error_category, str(exc)
                )
                validation_status = VALIDATION_FAILED
                if attempt >= max_retries:
                    break
                continue

        last_error_category = result.error_category or ProviderErrorCategory.UNKNOWN
        last_error_message = safe_error_message(
            last_error_category, result.error_message
        )
        validation_status = PROVIDER_FAILED
        if not is_retryable(last_error_category) or attempt >= max_retries:
            break

    completed_at = _now_utc()
    latency = (
        _parse_utc_iso(completed_at) - _parse_utc_iso(started_at)
    ).total_seconds()

    success = last_validated is not None and validation_status == VALIDATION_PASSED
    retry_count = attempt

    provider_name = _provider_name(provider)
    model_name = _provider_model(provider)
    cost_class_value = CostClass.FREE.value
    if last_result is not None:
        cost_class_value = last_result.cost_class.value

    run = gr_repo.create_generation_run(
        SqliteRuntimeConnection(conn),
        task_type=task_name,
        provider=provider_name,
        advertised_model=model_name,
        cost_class=cost_class_value,
        prompt_version=prompt_version,
        started_at=started_at,
    )

    gr_repo.update_generation_run(
        SqliteRuntimeConnection(conn),
        run.id,
        completed_at=completed_at,
        latency_seconds=latency,
        success=1 if success else 0,
        validation_status=validation_status,
        retry_count=retry_count,
        error_category=(
            last_error_category.value if last_error_category is not None else None
        ),
        error_message=last_error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return last_validated, StageOutcome(
        success=success,
        validation_status=validation_status,
        retry_count=retry_count,
        payload=(
            last_result.payload if last_result is not None and last_result.success
            else None
        ),
        error_category=(
            last_error_category.value if last_error_category is not None else None
        ),
        error_message=last_error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        completed_at=completed_at,
        latency_seconds=latency,
        provider=provider_name,
        model=model_name,
        cost_class=cost_class_value,
        run_id=run.id,
    )


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

        input_text = input_record.normalized_text or input_record.raw_text
        language = participant.preferred_language
        word_count = count_words(input_text, language)
        if word_count < MIN_INPUT_WORDS and not request.allow_short_sample:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("input too short"),
                draft_run=_failed_outcome("input too short"),
                succeeded=False,
            )
        if word_count > MAX_INPUT_WORDS:
            return GenerationResult(
                edition_id=None,
                plan_run=_failed_outcome("input too long"),
                draft_run=_failed_outcome("input too long"),
                succeeded=False,
            )

        preferences = ParticipantPreferences()
        segments = segment_text(input_text)
        prohibited_inferences = list(request.prohibited_inferences)

        feedback_directions: list[str] = []
        feedback_free_text: str | None = None
        prior_edition_summary: dict[str, Any] | None = None

        if request.is_follow_up:
            if request.prior_edition_id is None:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "prior_edition_id is required for follow-up"
                    ),
                    draft_run=_failed_outcome(
                        "prior_edition_id is required for follow-up"
                    ),
                    succeeded=False,
                )

            prior_edition = ed_repo.get_edition_by_id(
                conn, request.prior_edition_id
            )
            if prior_edition is None:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome("prior edition not found"),
                    draft_run=_failed_outcome("prior edition not found"),
                    succeeded=False,
                )
            if prior_edition.participant_id != request.participant_id:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "prior edition belongs to another participant"
                    ),
                    draft_run=_failed_outcome(
                        "prior edition belongs to another participant"
                    ),
                    succeeded=False,
                )
            if (
                prior_edition.generation_status != "pending_review"
                or prior_edition.publication_state != "published"
            ):
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "prior edition is not in the required state"
                    ),
                    draft_run=_failed_outcome(
                        "prior edition is not in the required state"
                    ),
                    succeeded=False,
                )

            if request.feedback_id is None:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "feedback_id is required for follow-up"
                    ),
                    draft_run=_failed_outcome(
                        "feedback_id is required for follow-up"
                    ),
                    succeeded=False,
                )

            feedback_record = fb_repo.get_feedback_by_id(
                conn, request.feedback_id
            )
            if feedback_record is None:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome("feedback not found"),
                    draft_run=_failed_outcome("feedback not found"),
                    succeeded=False,
                )
            if feedback_record.participant_id != request.participant_id:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "feedback belongs to another participant"
                    ),
                    draft_run=_failed_outcome(
                        "feedback belongs to another participant"
                    ),
                    succeeded=False,
                )
            if feedback_record.edition_id != request.prior_edition_id:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome(
                        "feedback does not match prior edition"
                    ),
                    draft_run=_failed_outcome(
                        "feedback does not match prior edition"
                    ),
                    succeeded=False,
                )
            if feedback_record.applied_to_next_edition != 0:
                return GenerationResult(
                    edition_id=None,
                    plan_run=_failed_outcome("feedback has already been applied"),
                    draft_run=_failed_outcome(
                        "feedback has already been applied"
                    ),
                    succeeded=False,
                )

            feedback_directions = json.loads(
                feedback_record.direction_choices
            )
            feedback_free_text = feedback_record.free_text

            if prior_edition.structured_content:
                try:
                    prior_edition_summary = json.loads(
                        prior_edition.structured_content
                    )
                except (json.JSONDecodeError, TypeError):
                    prior_edition_summary = None

        plan_system = prompts.build_plan_system_prompt(language)
        plan_payload = prompts.build_plan_user_payload(
            participant_id=request.participant_id,
            segments=segments,
            preferences=preferences,
            language=language,
            is_follow_up=request.is_follow_up,
            feedback_id=request.feedback_id,
            feedback_directions=feedback_directions,
            feedback_free_text=feedback_free_text,
            prior_edition_summary=(
                prior_edition_summary if request.is_follow_up else None
            ),
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
        )

        if plan is None:
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=_failed_outcome("plan stage failed"),
                succeeded=False,
            )

        try:
            validators.validate_plan(
                plan,
                segments=segments,
                is_follow_up=request.is_follow_up,
                feedback_id=request.feedback_id,
            )
        except PlanValidationError as exc:
            if plan_outcome.run_id is not None:
                gr_repo.update_generation_run(
                    SqliteRuntimeConnection(conn),
                    plan_outcome.run_id,
                    success=0,
                    validation_status=VALIDATION_FAILED,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                    ),
                )
            return GenerationResult(
                edition_id=None,
                plan_run=StageOutcome(
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=plan_outcome.retry_count,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                    ),
                    completed_at=plan_outcome.completed_at,
                    latency_seconds=plan_outcome.latency_seconds,
                    provider=plan_outcome.provider,
                    model=plan_outcome.model,
                    cost_class=plan_outcome.cost_class,
                    run_id=plan_outcome.run_id,
                ),
                draft_run=_failed_outcome("plan validation failed"),
                succeeded=False,
            )

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
        )

        if draft is None:
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=draft_outcome,
                succeeded=False,
            )

        try:
            validators.validate_draft_full(
                draft,
                plan=plan,
                segments=segments,
                is_follow_up=request.is_follow_up,
                feedback_id=request.feedback_id,
                prohibited_inferences=prohibited_inferences,
            )
        except validators.DETERMINISTIC_VALIDATION_ERRORS as exc:
            if draft_outcome.run_id is not None:
                gr_repo.update_generation_run(
                    SqliteRuntimeConnection(conn),
                    draft_outcome.run_id,
                    success=0,
                    validation_status=VALIDATION_FAILED,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                    ),
                )
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=StageOutcome(
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=draft_outcome.retry_count,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                    ),
                    completed_at=draft_outcome.completed_at,
                    latency_seconds=draft_outcome.latency_seconds,
                    provider=draft_outcome.provider,
                    model=draft_outcome.model,
                    cost_class=draft_outcome.cost_class,
                    run_id=draft_outcome.run_id,
                ),
                succeeded=False,
            )

        edition_number = self._next_edition_number(conn, request.participant_id)
        structured_content = draft.model_dump_json()
        rendered_title = draft.edition_title

        try:
            if request.is_follow_up and request.feedback_id is not None:
                new_edition = ed_repo.create_edition_with_feedback_applied(
                    SqliteRuntimeConnection(conn),
                    participant_id=request.participant_id,
                    edition_number=edition_number,
                    prior_edition_id=request.prior_edition_id,
                    input_id=request.input_id,
                    structured_content=structured_content,
                    rendered_title=rendered_title,
                    feedback_id=request.feedback_id,
                )
            else:
                new_edition = ed_repo.create_edition(
                    SqliteRuntimeConnection(conn),
                    participant_id=request.participant_id,
                    edition_number=edition_number,
                    prior_edition_id=request.prior_edition_id,
                    input_id=request.input_id,
                    structured_content=structured_content,
                    rendered_title=rendered_title,
                )
        except Exception:
            if draft_outcome.run_id is not None:
                gr_repo.update_generation_run(
                    SqliteRuntimeConnection(conn),
                    draft_outcome.run_id,
                    success=0,
                    validation_status=VALIDATION_FAILED,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH,
                        "persistence failed",
                    ),
                )
            return GenerationResult(
                edition_id=None,
                plan_run=plan_outcome,
                draft_run=StageOutcome(
                    success=False,
                    validation_status=VALIDATION_FAILED,
                    retry_count=draft_outcome.retry_count,
                    error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    error_message=safe_error_message(
                        ProviderErrorCategory.SCHEMA_MISMATCH,
                        "persistence failed",
                    ),
                    completed_at=draft_outcome.completed_at,
                    latency_seconds=draft_outcome.latency_seconds,
                    provider=draft_outcome.provider,
                    model=draft_outcome.model,
                    cost_class=draft_outcome.cost_class,
                    run_id=draft_outcome.run_id,
                ),
                succeeded=False,
            )

        return GenerationResult(
            edition_id=new_edition.id,
            plan_run=plan_outcome,
            draft_run=draft_outcome,
            succeeded=True,
        )

    def generate_repair_candidate(
        self,
        conn,
        *,
        request: GenerationRequest,
    ) -> RepairCandidate:
        """Produce one candidate edition for the repair benchmark.

        Runs the standard plan -> draft -> validate pipeline (without persisting
        an edition) and returns the resulting EditionContent together with the
        plan and segments required to later validate a corrupted/repair copy.
        Accounting for the two provider calls is recorded via the repository as
        usual; the benchmark harness is responsible for persisting benchmark
        rows.
        """
        participant = pt_repo.get_participant_by_id(conn, request.participant_id)
        if participant is None or participant.status != "active":
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("participant not active"),
                draft_outcome=_failed_outcome("participant not active"),
            )

        input_record = input_repo.get_input_by_id(conn, request.input_id)
        if input_record is None:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("input not found"),
                draft_outcome=_failed_outcome("input not found"),
            )
        if input_record.participant_id != request.participant_id:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("input belongs to another participant"),
                draft_outcome=_failed_outcome("input belongs to another participant"),
            )
        if input_record.deleted_at is not None:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("input is deleted"),
                draft_outcome=_failed_outcome("input is deleted"),
            )
        if input_record.consent_confirmed != 1:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("consent not confirmed"),
                draft_outcome=_failed_outcome("consent not confirmed"),
            )

        input_text = input_record.normalized_text or input_record.raw_text
        language = participant.preferred_language
        word_count = count_words(input_text, language)
        if word_count < MIN_INPUT_WORDS and not request.allow_short_sample:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("input too short"),
                draft_outcome=_failed_outcome("input too short"),
            )
        if word_count > MAX_INPUT_WORDS:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=[],
                plan_outcome=_failed_outcome("input too long"),
                draft_outcome=_failed_outcome("input too long"),
            )

        preferences = ParticipantPreferences()
        segments = segment_text(input_text)
        prohibited_inferences = list(request.prohibited_inferences)

        plan_system = prompts.build_plan_system_prompt(language)
        plan_payload = prompts.build_plan_user_payload(
            participant_id=request.participant_id,
            segments=segments,
            preferences=preferences,
            language=language,
            is_follow_up=False,
            feedback_id=None,
            feedback_directions=[],
            feedback_free_text=None,
            prior_edition_summary=None,
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
        )

        if plan is None:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=None,
                segments=segments,
                plan_outcome=plan_outcome,
                draft_outcome=_failed_outcome("plan stage failed"),
            )

        try:
            validators.validate_plan(
                plan,
                segments=segments,
                is_follow_up=False,
                feedback_id=None,
            )
        except PlanValidationError as exc:
            _mark_run_validation_failed(conn, plan_outcome.run_id, exc)
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=plan,
                segments=segments,
                plan_outcome=_deterministic_failure_stage(plan_outcome, exc),
                draft_outcome=_failed_outcome("plan validation failed"),
            )

        draft_system = prompts.build_draft_system_prompt(language)
        draft_payload = prompts.build_draft_user_payload(
            participant_id=request.participant_id,
            segments=segments,
            plan=plan,
            language=language,
            is_follow_up=False,
            feedback_id=None,
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
        )

        if draft is None:
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=plan,
                segments=segments,
                plan_outcome=plan_outcome,
                draft_outcome=draft_outcome,
            )

        try:
            validators.validate_draft_full(
                draft,
                plan=plan,
                segments=segments,
                is_follow_up=False,
                feedback_id=None,
                prohibited_inferences=prohibited_inferences,
            )
        except validators.DETERMINISTIC_VALIDATION_ERRORS as exc:
            _mark_run_validation_failed(conn, draft_outcome.run_id, exc)
            return RepairCandidate(
                succeeded=False,
                content=None,
                plan=plan,
                segments=segments,
                plan_outcome=plan_outcome,
                draft_outcome=_deterministic_failure_stage(draft_outcome, exc),
            )

        return RepairCandidate(
            succeeded=True,
            content=draft,
            plan=plan,
            segments=segments,
            plan_outcome=plan_outcome,
            draft_outcome=draft_outcome,
        )

    def repair_edition(
        self,
        conn,
        *,
        repair_request: RepairRequest,
        plan: EditorialPlan,
        segments: list[InputSegment],
    ) -> RepairOutcome:
        """Send a privacy-safe repair request to the same provider instance.

        The provider receives the corrupted candidate, normalized validator
        findings, a concise repair instruction, and correlation/attempt
        identifiers. The repaired candidate is validated deterministically
        against the original plan and segments. No raw private participant
        input is transmitted.
        """
        participant = pt_repo.get_participant_by_id(
            conn, repair_request.participant_id
        )
        language = participant.preferred_language if participant else "ko"

        system_prompt = prompts.build_repair_system_prompt(language)
        user_payload = prompts.build_repair_user_payload(
            corrupted_candidate=repair_request.corrupted_candidate,
            validator_findings=repair_request.validator_findings,
            repair_instruction=repair_request.repair_instruction,
            correlation_id=repair_request.correlation_id,
            attempt_id=repair_request.attempt_id,
            prohibited_inferences=list(repair_request.prohibited_inferences),
            allowed_segment_ids=repair_request.allowed_segment_ids,
            allowed_plan_section_ids=repair_request.allowed_plan_section_ids,
            language=language,
        )

        validated, outcome = _provider_call_with_retry(
            provider=self._provider,
            task_name=prompts.TASK_EDITION_REPAIR,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_schema=EditionContent,
            max_retries=self._max_retries,
            prompt_version=prompts.REPAIR_PROMPT_VERSION,
            conn=conn,
            participant_id=repair_request.participant_id,
        )

        if validated is None:
            return RepairOutcome(
                succeeded=False,
                validation_status=outcome.validation_status or PROVIDER_FAILED,
                content=None,
                error_category=outcome.error_category,
                error_message=outcome.error_message,
                retry_count=outcome.retry_count,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                latency_seconds=outcome.latency_seconds,
                provider=outcome.provider,
                model=outcome.model,
                cost_class=outcome.cost_class,
                run_id=outcome.run_id,
            )

        try:
            validators.validate_draft_full(
                validated,
                plan=plan,
                segments=segments,
                is_follow_up=False,
                feedback_id=None,
                prohibited_inferences=list(repair_request.prohibited_inferences),
            )
            _assert_allowed_reference_universe(
                validated,
                repair_request.allowed_segment_ids,
                repair_request.allowed_plan_section_ids,
            )
        except validators.DETERMINISTIC_VALIDATION_ERRORS as exc:
            _mark_run_validation_failed(conn, outcome.run_id, exc)
            return RepairOutcome(
                succeeded=False,
                validation_status=VALIDATION_FAILED,
                content=None,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                error_message=safe_error_message(
                    ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                ),
                retry_count=outcome.retry_count,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                latency_seconds=outcome.latency_seconds,
                provider=outcome.provider,
                model=outcome.model,
                cost_class=outcome.cost_class,
                run_id=outcome.run_id,
            )

        return RepairOutcome(
            succeeded=True,
            validation_status=VALIDATION_PASSED,
            content=validated,
            error_category=None,
            error_message=None,
            retry_count=outcome.retry_count,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_seconds=outcome.latency_seconds,
            provider=outcome.provider,
            model=outcome.model,
            cost_class=outcome.cost_class,
            run_id=outcome.run_id,
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


def _deterministic_failure_stage(
    base_outcome: StageOutcome, exc: Exception
) -> StageOutcome:
    """Build a failed StageOutcome mirroring a deterministic validation error.

    The returned outcome carries ``validation_status=VALIDATION_FAILED`` and a
    privacy-safe error category/message so it can never be mistaken for a
    provider failure. It preserves the underlying provider accounting.
    """
    return StageOutcome(
        success=False,
        validation_status=VALIDATION_FAILED,
        retry_count=base_outcome.retry_count,
        error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
        error_message=safe_error_message(
            ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
        ),
        completed_at=base_outcome.completed_at,
        latency_seconds=base_outcome.latency_seconds,
        provider=base_outcome.provider,
        model=base_outcome.model,
        cost_class=base_outcome.cost_class,
        run_id=base_outcome.run_id,
    )


def _mark_run_validation_failed(
    conn, run_id: str | None, exc: Exception
) -> None:
    """Persist a deterministic validation failure on the exact run row.

    Called whenever deterministic validation fails after a provider call that
    already succeeded at the schema level: candidate plan validation, candidate
    draft validation, markup failure, grounding failure, and repair validation
    failure. The returned outcome and this row must never disagree.
    """
    if run_id is None:
        return
    gr_repo.update_generation_run(
        SqliteRuntimeConnection(conn),
        run_id,
        success=0,
        validation_status=VALIDATION_FAILED,
        error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
        error_message=safe_error_message(
            ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
        ),
    )


def _assert_allowed_reference_universe(
    draft: EditionContent,
    allowed_segment_ids: tuple[str, ...],
    allowed_plan_section_ids: tuple[str, ...],
) -> None:
    """Reject a repaired draft that references ids outside the allowed sets.

    The repair request supplies the authoritative, privacy-safe reference
    universe (segment ids and plan section ids only). A repaired draft must
    reference only those ids; an id outside the set is an invented or leaked
    reference and must be rejected deterministically. Both sets are required to
    be non-empty (enforced at ``RepairRequest`` construction); enforcement is
    never skipped, so a missing reference universe fails closed.
    """
    if not allowed_segment_ids or not allowed_plan_section_ids:
        raise DraftValidationError(
            "repair request did not supply a non-empty allowed reference universe"
        )
    allowed_segments = frozenset(allowed_segment_ids)
    allowed_sections = frozenset(allowed_plan_section_ids)
    for section in draft.sections:
        for ref in section.source_segment_ids:
            if ref not in allowed_segments:
                raise DraftValidationError(
                    "repaired draft references segment id '"
                    + str(ref)
                    + "' which is outside the allowed reference universe"
                )
    for section in draft.sections:
        if section.section_id not in allowed_sections:
            raise DraftValidationError(
                "repaired draft section '"
                + str(section.section_id)
                + "' is outside the allowed reference universe"
            )
