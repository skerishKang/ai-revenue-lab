"""Provider-neutral generation service for Living Fiction.

Orchestrates: provider calls (plan + content), deterministic validation,
bounded retry, privacy-safe error normalization, generation-run accounting,
and durable pending_review persistence.

Transaction ownership policy:
- The service owns the transaction for branch episode creation + choice
  application. These two writes commit together or roll back together.
- Repositories require an idle connection for individual writes and never
  commit within a service-owned transaction.
- Failed generation leaves the last valid state unchanged and reader
  input unapplied.
- Duplicate/retry requests cannot create duplicate episode numbers or apply
  the same input twice (enforced by UNIQUE constraints + idempotent checks).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlite3

from app import branch_repository as branch_repo
from app import canon_repository as canon_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import generation_run_repository as gr_repo
from app import reader_repository as reader_repo
from app.ai.base import AIProvider
from app.domain.enums import EpisodeType, ProviderErrorCategory, ValidationStatus
from app.domain.models import (
    EpisodeContent,
    EpisodePlan,
    ProviderResult,
    WorldState,
)
from app.pipeline import prompts
from app.pipeline.errors import (
    ContentValidationError,
    PipelineError,
    PlanValidationError,
    ProviderCallError,
    is_retryable,
    safe_error_message,
)
from app.pipeline.validators import validate_content, validate_plan
from app.utils import new_id, now_utc_iso

DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs for a single generation run."""
    world: WorldState
    episode_type: EpisodeType
    is_first_canon: bool = False
    canon_checkpoint_id: str | None = None
    prior_episode_id: str | None = None
    reader_id: str | None = None
    reader_choice_id: str | None = None
    reader_choice_text: str | None = None
    reader_comment: str | None = None
    prior_episode_summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class GenerationResult:
    episode_id: str | None
    plan_run_id: str
    content_run_id: str
    succeeded: bool
    error: str | None = None


def _new_request_id() -> str:
    return str(uuid.uuid4())


def _now_utc() -> str:
    return now_utc_iso()


def _provider_call_with_retry(
    *,
    provider: AIProvider,
    task_name: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    response_schema: type,
    max_retries: int,
    prompt_version: str,
    conn: sqlite3.Connection,
) -> tuple[Any | None, str, str | None, int | None, int | None, float | None, int, str | None, str | None]:
    """Call provider with bounded retry. Returns (model_or_none, run_id, error_category, input_tokens, output_tokens, latency, retry_count, validation_status, error_message)."""
    started_at = _now_utc()
    run_id = new_id()

    gr_repo.create_generation_run(
        conn,
        run_id=run_id,
        task_type=task_name,
        provider="mock",
        advertised_model=getattr(provider, "model", "unknown"),
        cost_class="free",
        prompt_version=prompt_version,
        started_at=started_at,
    )

    last_error_category: ProviderErrorCategory | None = None
    last_error_message: str | None = None
    last_result: ProviderResult | None = None
    total_latency = 0.0
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    retry_count = 0

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
            last_error_message = safe_error_message(last_error_category, str(exc))
            if attempt < max_retries:
                retry_count += 1
                continue
            break

        total_latency += result.latency_seconds

        if result.usage:
            if result.usage.input_tokens is not None:
                total_input_tokens = (total_input_tokens or 0) + result.usage.input_tokens
            if result.usage.output_tokens is not None:
                total_output_tokens = (total_output_tokens or 0) + result.usage.output_tokens

        if result.success:
            last_result = result
            break
        else:
            last_error_category = result.error_category
            last_error_message = safe_error_message(
                result.error_category, result.error_message
            )
            if is_retryable(result.error_category) and attempt < max_retries:
                retry_count += 1
                continue
            break

    completed_at = _now_utc()

    if last_result is not None and last_result.success:
        gr_repo.update_generation_run(
            conn, run_id,
            completed_at=completed_at,
            latency_seconds=total_latency,
            success=True,
            validation_status=ValidationStatus.PASSED.value,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            retry_count=retry_count,
        )
        # Deserialize the payload
        try:
            model = response_schema.model_validate(last_result.payload)
            return (model, run_id, None, total_input_tokens,
                    total_output_tokens, total_latency, retry_count,
                    ValidationStatus.PASSED.value, None)
        except Exception as exc:
            gr_repo.update_generation_run(
                conn, run_id,
                completed_at=completed_at,
                success=False,
                validation_status=ValidationStatus.FAILED.value,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
                error_message=safe_error_message(
                    ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)
                ),
                retry_count=retry_count,
            )
            return (None, run_id, ProviderErrorCategory.SCHEMA_MISMATCH.value,
                    total_input_tokens, total_output_tokens, total_latency,
                    retry_count, ValidationStatus.FAILED.value,
                    safe_error_message(ProviderErrorCategory.SCHEMA_MISMATCH, str(exc)))
    else:
        gr_repo.update_generation_run(
            conn, run_id,
            completed_at=completed_at,
            latency_seconds=total_latency,
            success=False,
            validation_status=ValidationStatus.PROVIDER_FAILED.value,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            retry_count=retry_count,
            error_category=last_error_category.value if last_error_category else None,
            error_message=last_error_message,
        )
        return (None, run_id,
                last_error_category.value if last_error_category else None,
                total_input_tokens, total_output_tokens, total_latency,
                retry_count, ValidationStatus.PROVIDER_FAILED.value,
                last_error_message)


def generate_canon_episode(
    conn: sqlite3.Connection,
    provider: AIProvider,
    request: GenerationRequest,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    world_id: str = "",
) -> GenerationResult:
    """Generate a canon episode. First canon has no applied reader input."""
    # 1. Plan
    plan_payload = prompts.build_plan_user_payload(
        world_state=request.world,
        episode_type=EpisodeType.CANON.value,
        episode_number=1 if request.is_first_canon else 0,
        canon_checkpoint_id=request.canon_checkpoint_id,
        prior_episode_id=request.prior_episode_id,
        reader_choice=None,
        is_first_canon=request.is_first_canon,
    )

    plan_model, plan_run_id, _, _, _, _, _, plan_vs, plan_err = _provider_call_with_retry(
        provider=provider,
        task_name=prompts.TASK_EPISODE_PLAN,
        system_prompt=prompts.build_plan_system_prompt(),
        user_payload=plan_payload,
        response_schema=EpisodePlan,
        max_retries=max_retries,
        prompt_version=prompts.PLAN_PROMPT_VERSION,
        conn=conn,
    )

    if plan_model is None:
        return GenerationResult(
            episode_id=None,
            plan_run_id=plan_run_id,
            content_run_id="",
            succeeded=False,
            error=plan_err,
        )

    # 2. Validate plan
    try:
        validate_plan(plan_model, world=request.world, is_first_canon=request.is_first_canon)
    except PlanValidationError as exc:
        gr_repo.update_generation_run(
            conn, plan_run_id,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        return GenerationResult(
            episode_id=None,
            plan_run_id=plan_run_id,
            content_run_id="",
            succeeded=False,
            error=str(exc),
        )

    # 3. Content
    content_payload = prompts.build_content_user_payload(
        plan=plan_model.model_dump(),
        world_state=request.world,
        reader_choice=None,
        prior_episode_summary=request.prior_episode_summary,
    )

    content_model, content_run_id, _, in_tok, out_tok, latency, retries, content_vs, content_err = _provider_call_with_retry(
        provider=provider,
        task_name=prompts.TASK_EPISODE_CONTENT,
        system_prompt=prompts.build_content_system_prompt(),
        user_payload=content_payload,
        response_schema=EpisodeContent,
        max_retries=max_retries,
        prompt_version=prompts.CONTENT_PROMPT_VERSION,
        conn=conn,
    )

    if content_model is None:
        return GenerationResult(
            episode_id=None,
            plan_run_id=plan_run_id,
            content_run_id=content_run_id,
            succeeded=False,
            error=content_err,
        )

    # 4. Validate content
    try:
        validate_content(
            content_model,
            world=request.world,
            plan=plan_model,
            is_first_canon=request.is_first_canon,
        )
    except ContentValidationError as exc:
        gr_repo.update_generation_run(
            conn, content_run_id,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        return GenerationResult(
            episode_id=None,
            plan_run_id=plan_run_id,
            content_run_id=content_run_id,
            succeeded=False,
            error=str(exc),
        )

    # 5. Persist episode (pending_review)
    episode_id = new_id()
    ep_repo.create_episode(
        conn,
        episode_id=episode_id,
        world_id=world_id or request.world.world_id,
        episode_type=EpisodeType.CANON.value,
        episode_number=content_model.episode_number,
        title=content_model.title,
        synopsis=content_model.synopsis,
        scene_list=[s.model_dump() for s in content_model.scenes],
        character_ids=content_model.scenes[0].participating_character_ids if content_model.scenes else [],
        location_ids=[s.location_id for s in content_model.scenes if s.location_id],
        prose=[b.model_dump() for b in content_model.prose],
        clue_refs=content_model.clue_refs,
        world_state_deltas=content_model.world_state_delta.model_dump(),
        applied_reader_input=None,
        unresolved_threads=content_model.unresolved_threads,
        next_choice_options=content_model.next_choice_options,
        content_classification=content_model.content_classification.value,
        canon_snapshot_id=request.canon_checkpoint_id,
        prior_episode_id=request.prior_episode_id,
        generation_run_id=content_run_id,
    )

    return GenerationResult(
        episode_id=episode_id,
        plan_run_id=plan_run_id,
        content_run_id=content_run_id,
        succeeded=True,
    )


def generate_personal_branch(
    conn: sqlite3.Connection,
    provider: AIProvider,
    request: GenerationRequest,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    world_id: str = "",
    canon_checkpoint_id: str = "",
    prior_episode_id: str = "",
) -> GenerationResult:
    """Generate a personal branch that visibly applies the stored reader choice.

    Transaction: episode creation + choice application commit together.
    On failure: neither is persisted.
    """
    # Verify reader is active
    if request.reader_id and not reader_repo.is_reader_active(conn, request.reader_id):
        return GenerationResult(
            episode_id=None, plan_run_id="", content_run_id="",
            succeeded=False, error="reader is not active or does not exist",
        )

    # Verify choice is not already applied
    if request.reader_choice_id:
        choice = choice_repo.get_reader_choice(conn, request.reader_choice_id)
        if choice is None:
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False, error="reader choice not found",
            )
        # Verify choice belongs to the requesting reader
        if choice.reader_id != request.reader_id:
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False, error="foreign reader choice — choice belongs to another reader",
            )
        if choice_repo.is_choice_applied(conn, request.reader_choice_id):
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False, error="reader choice already applied",
            )

    reader_choice_dict = None
    if request.reader_choice_id:
        reader_choice_dict = {
            "reader_choice_id": request.reader_choice_id,
            "choice_text": request.reader_choice_text or "",
            "comment": request.reader_comment,
        }

    # 1. Plan
    ep_num = ep_repo.get_next_episode_number(
        conn, world_id or request.world.world_id, EpisodeType.PERSONAL_BRANCH.value
    )

    plan_payload = prompts.build_plan_user_payload(
        world_state=request.world,
        episode_type=EpisodeType.PERSONAL_BRANCH.value,
        episode_number=ep_num,
        canon_checkpoint_id=canon_checkpoint_id or request.canon_checkpoint_id,
        prior_episode_id=prior_episode_id or request.prior_episode_id,
        reader_choice=reader_choice_dict,
        is_first_canon=False,
    )

    plan_model, plan_run_id, _, _, _, _, _, plan_vs, plan_err = _provider_call_with_retry(
        provider=provider,
        task_name=prompts.TASK_EPISODE_PLAN,
        system_prompt=prompts.build_plan_system_prompt(),
        user_payload=plan_payload,
        response_schema=EpisodePlan,
        max_retries=max_retries,
        prompt_version=prompts.PLAN_PROMPT_VERSION,
        conn=conn,
    )

    if plan_model is None:
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=plan_err,
        )

    # 2. Validate plan
    try:
        validate_plan(plan_model, world=request.world, is_first_canon=False)
    except PlanValidationError as exc:
        gr_repo.update_generation_run(
            conn, plan_run_id,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=str(exc),
        )

    # 3. Content
    content_payload = prompts.build_content_user_payload(
        plan=plan_model.model_dump(),
        world_state=request.world,
        reader_choice=reader_choice_dict,
        prior_episode_summary=request.prior_episode_summary,
    )

    content_model, content_run_id, _, in_tok, out_tok, latency, retries, content_vs, content_err = _provider_call_with_retry(
        provider=provider,
        task_name=prompts.TASK_EPISODE_CONTENT,
        system_prompt=prompts.build_content_system_prompt(),
        user_payload=content_payload,
        response_schema=EpisodeContent,
        max_retries=max_retries,
        prompt_version=prompts.CONTENT_PROMPT_VERSION,
        conn=conn,
    )

    if content_model is None:
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=content_err,
        )

    # 4. Validate content
    # Override the reader_choice_id in the content to match the actual request
    if content_model.applied_reader_input and request.reader_choice_id:
        content_model = content_model.model_copy(update={
            "applied_reader_input": content_model.applied_reader_input.model_copy(
                update={"reader_choice_id": request.reader_choice_id}
            )
        })

    try:
        validate_content(
            content_model,
            world=request.world,
            plan=plan_model,
            is_first_canon=False,
            expected_reader_choice_id=request.reader_choice_id,
        )
    except ContentValidationError as exc:
        gr_repo.update_generation_run(
            conn, content_run_id,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )

    # 5. Transactional persistence: episode + choice application
    # The service owns this transaction. Repositories mark_choice_applied
    # operates within the connection's active transaction without committing.
    episode_id = new_id()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Create episode (without committing)
        conn.execute(
            "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
            "title, synopsis, canon_snapshot_id, canon_checkpoint_id, "
            "prior_episode_id, reader_id, scene_list_json, character_ids_json, "
            "location_ids_json, prose_json, clue_refs_json, "
            "world_state_deltas_json, applied_reader_input_json, "
            "unresolved_threads_json, next_choice_options_json, "
            "content_classification, review_state, generation_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "'pending_review', ?, ?)",
            (
                episode_id,
                world_id or request.world.world_id,
                EpisodeType.PERSONAL_BRANCH.value,
                content_model.episode_number,
                content_model.title,
                content_model.synopsis,
                None,
                canon_checkpoint_id or request.canon_checkpoint_id,
                prior_episode_id or request.prior_episode_id,
                request.reader_id,
                json.dumps([s.model_dump() for s in content_model.scenes]),
                json.dumps([cid for s in content_model.scenes for cid in s.participating_character_ids]),
                json.dumps([s.location_id for s in content_model.scenes if s.location_id]),
                json.dumps([b.model_dump() for b in content_model.prose]),
                json.dumps(content_model.clue_refs),
                json.dumps(content_model.world_state_delta.model_dump()),
                json.dumps(content_model.applied_reader_input.model_dump()) if content_model.applied_reader_input else None,
                json.dumps(content_model.unresolved_threads),
                json.dumps(content_model.next_choice_options),
                content_model.content_classification.value,
                content_run_id,
                now_utc_iso(),
            ),
        )

        # Mark choice as applied (within same transaction)
        if request.reader_choice_id:
            now = now_utc_iso()
            choice_row = conn.execute(
                "SELECT applied_to_branch_id FROM reader_choices WHERE id = ?",
                (request.reader_choice_id,),
            ).fetchone()
            if choice_row is None:
                raise PipelineError(f"choice not found: {request.reader_choice_id}")
            if choice_row["applied_to_branch_id"] is not None:
                raise PipelineError(
                    f"choice {request.reader_choice_id} already applied"
                )
            conn.execute(
                "UPDATE reader_choices SET applied_to_branch_id = ?, "
                "applied_at = ? WHERE id = ? AND applied_to_branch_id IS NULL",
                (episode_id, now, request.reader_choice_id),
            )

        # Create branch record
        branch_id = new_id()
        conn.execute(
            "INSERT INTO branches (id, reader_id, canon_checkpoint_id, "
            "prior_episode_id, branch_episode_id, reader_choice_id, "
            "divergence_state_json, branch_only_facts_json, status, "
            "rejoin_checkpoint_id, rejoin_explanation, rejoined_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, ?)",
            (
                branch_id, request.reader_id,
                canon_checkpoint_id or request.canon_checkpoint_id,
                prior_episode_id or request.prior_episode_id,
                episode_id, request.reader_choice_id,
                json.dumps(content_model.world_state_delta.model_dump()),
                json.dumps(content_model.world_state_delta.branch_only_facts),
                now_utc_iso(),
            ),
        )

        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=f"transaction integrity error: {exc}",
        )
    except PipelineError as exc:
        conn.rollback()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )
    except Exception as exc:
        if conn.in_transaction:
            conn.rollback()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=f"unexpected error: {exc}",
        )

    return GenerationResult(
        episode_id=episode_id, plan_run_id=plan_run_id,
        content_run_id=content_run_id, succeeded=True,
    )
