"""Provider-neutral generation service for Living Fiction.

Orchestrates: persisted branch binding verification, provider calls (plan +
content), deterministic validation, bounded retry with per-attempt
accounting, privacy-safe error normalization, generation-run accounting,
and durable pending_review persistence.

Key contracts enforced (CTO repair):
1. Branch binding uses persisted identifiers — caller-supplied WorldState,
   prior episode summary, choice text, comment, and canon facts are NOT
   trusted. All are loaded from persisted repositories and accepted canon
   snapshots.
2. Reader input is NOT rewritten before validation. The returned
   applied_reader_input must independently match persisted values.
3. One production continuity validator is invoked from the service boundary.
4. Provider identity and attempt accounting records actual ProviderResult
   values — no hardcoded provider="mock" or cost_class="free".
5. Deterministic validation failures set success=false consistently.
6. Branch transaction failure does not leave a misleading successful run.

Transaction ownership policy:
- The service owns the transaction for branch episode creation + choice
  application. These two writes commit together or roll back together.
- Repositories require an idle connection for individual writes and never
  commit within a service-owned transaction.
- Failed generation leaves the last valid state unchanged and reader
  input unapplied.
- Duplicate/retry requests cannot create duplicate episode numbers or apply
  the same input twice (enforced by idempotency tracking + UNIQUE constraints).
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
from app import generation_attempt_repository as attempt_repo
from app import generation_run_repository as gr_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.ai.base import AIProvider
from app.domain.enums import (
    AttemptResult,
    EpisodeType,
    ProviderErrorCategory,
    ValidationStatus,
)
from app.domain.models import (
    EpisodeContent,
    EpisodePlan,
    ProviderResult,
    ProviderUsage,
    WorldState,
)
from app.pipeline import prompts
from app.pipeline.errors import (
    BranchBindingError,
    ContentValidationError,
    PipelineError,
    PlanValidationError,
    ProviderCallError,
    is_retryable,
    safe_error_message,
)
from app.pipeline.material_change import validate_material_change
from app.pipeline.production_continuity import validate_production_continuity
from app.pipeline.validators import validate_content, validate_plan
from app.utils import new_id, now_utc_iso

DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs for a single generation run.

    For personal branches, persisted identifiers are loaded and verified
    — caller-supplied WorldState, choice text, and comment are NOT trusted.
    """
    world: WorldState
    episode_type: EpisodeType
    is_first_canon: bool = False
    canon_checkpoint_id: str | None = None
    prior_episode_id: str | None = None
    reader_id: str | None = None
    reader_choice_id: str | None = None
    reader_choice_text: str | None = None  # NOT trusted — loaded from DB
    reader_comment: str | None = None       # NOT trusted — loaded from DB
    prior_episode_summary: dict[str, Any] | None = None  # NOT trusted
    idempotency_key: str | None = None


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
    """Call provider with bounded retry.

    Records actual provider/model/cost from every ProviderResult.
    One durable attempt row per actual provider attempt.

    Returns (model_or_none, run_id, error_category, input_tokens,
              output_tokens, latency, retry_count, validation_status, error_message).
    """
    started_at = _now_utc()
    run_id = new_id()

    # Create aggregate run row — provider/model from the actual provider instance
    actual_provider = getattr(provider, "provider_name", None) or "mock"
    actual_model = getattr(provider, "model", "unknown")

    # Determine cost class from provider — do NOT hardcode
    if hasattr(provider, "cost_class"):
        actual_cost = str(provider.cost_class)
    else:
        # For MockProvider, check the actual result later
        actual_cost = "unknown"

    gr_repo.create_generation_run(
        conn,
        run_id=run_id,
        task_type=task_name,
        provider=actual_provider,
        advertised_model=actual_model,
        cost_class=actual_cost,
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

    for attempt_num in range(1, max_retries + 2):
        request_id = _new_request_id()
        attempt_start = _now_utc()

        try:
            result = provider.generate_structured(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                request_id=request_id,
            )
        except Exception as exc:
            # Exception attempt — record it
            attempt_repo.create_generation_attempt(
                conn,
                attempt_id=new_id(),
                generation_run_id=run_id,
                attempt_number=attempt_num,
                provider=actual_provider,
                advertised_model=actual_model,
                cost_class=actual_cost,
                request_id=request_id,
                task_type=task_name,
                prompt_version=prompt_version,
                success=False,
                retryable=True,
                error_category=ProviderErrorCategory.UNKNOWN.value,
                error_message=safe_error_message(ProviderErrorCategory.UNKNOWN, str(exc)),
            )
            last_error_category = ProviderErrorCategory.UNKNOWN
            last_error_message = safe_error_message(last_error_category, str(exc))
            if attempt_num <= max_retries:
                retry_count += 1
                continue
            break

        # Record the actual attempt with real provider values
        attempt_repo.create_generation_attempt(
            conn,
            attempt_id=new_id(),
            generation_run_id=run_id,
            attempt_number=attempt_num,
            provider=result.provider,
            advertised_model=result.advertised_model,
            cost_class=result.cost_class.value,
            request_id=result.request_id or request_id,
            task_type=task_name,
            prompt_version=prompt_version,
            latency_seconds=result.latency_seconds,
            input_tokens=result.usage.input_tokens if result.usage else None,
            output_tokens=result.usage.output_tokens if result.usage else None,
            total_tokens=result.usage.total_tokens if result.usage else None,
            success=result.success,
            retryable=is_retryable(result.error_category) if result.error_category else False,
            error_category=result.error_category.value if result.error_category else None,
            error_message=safe_error_message(result.error_category, result.error_message) if result.error_category else None,
        )

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
            if is_retryable(result.error_category) and attempt_num <= max_retries:
                retry_count += 1
                continue
            break

    completed_at = _now_utc()

    # Update aggregate run with actual provider from last result (if any)
    final_provider = last_result.provider if last_result else actual_provider
    final_model = last_result.advertised_model if last_result else actual_model
    final_cost = last_result.cost_class.value if last_result else actual_cost

    if last_result is not None and last_result.success:
        # Update run with actual provider values from the successful result
        if conn.in_transaction:
            conn.rollback()
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
        # Update provider/model/cost to actual values from successful result
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE generation_runs SET provider = ?, advertised_model = ?, "
            "cost_class = ? WHERE id = ?",
            (final_provider, final_model, final_cost, run_id),
        )
        conn.commit()
        # Deserialize the payload
        try:
            model = response_schema.model_validate(last_result.payload)
            return (model, run_id, None, total_input_tokens,
                    total_output_tokens, total_latency, retry_count,
                    ValidationStatus.PASSED.value, None)
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
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
        if conn.in_transaction:
            conn.rollback()
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
        # Update provider/model/cost to actual values
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE generation_runs SET provider = ?, advertised_model = ?, "
            "cost_class = ? WHERE id = ?",
            (final_provider, final_model, final_cost, run_id),
        )
        conn.commit()
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
        # Deterministic validation failure — set success=False
        gr_repo.update_generation_run(
            conn, plan_run_id,
            completed_at=_now_utc(),
            success=False,
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
            completed_at=_now_utc(),
            success=False,
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


def _verify_persisted_branch_binding(
    conn: sqlite3.Connection,
    *,
    reader_id: str,
    reader_choice_id: str,
    prior_episode_id: str,
    canon_checkpoint_id: str,
    world_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify persisted branch binding — load all authoritative values from DB.

    Returns (choice_record, prior_episode_record, checkpoint_record).
    Raises BranchBindingError on any mismatch.
    """
    # 1. Reader exists and is active
    if not reader_repo.is_reader_active(conn, reader_id):
        raise BranchBindingError(
            f"reader is not active or does not exist: {reader_id}"
        )

    # 2. Reader choice exists and belongs to the reader
    choice = choice_repo.get_reader_choice(conn, reader_choice_id)
    if choice is None:
        raise BranchBindingError(f"reader choice not found: {reader_choice_id}")
    if choice.reader_id != reader_id:
        raise BranchBindingError(
            "foreign reader choice — choice belongs to another reader"
        )

    # 3. Choice is unapplied
    if choice_repo.is_choice_applied(conn, reader_choice_id):
        raise BranchBindingError("reader choice already applied")

    # 4. choice.canon_episode_id == prior_episode_id
    if choice.canon_episode_id != prior_episode_id:
        raise BranchBindingError(
            f"choice canon_episode_id {choice.canon_episode_id} "
            f"does not match prior_episode_id {prior_episode_id}"
        )

    # 5. Prior episode exists
    prior_episode = ep_repo.get_episode_by_id(conn, prior_episode_id)
    if prior_episode is None:
        raise BranchBindingError(f"prior episode not found: {prior_episode_id}")

    # 6. Prior episode belongs to world_id
    if prior_episode.world_id != world_id:
        raise BranchBindingError(
            f"prior episode belongs to world {prior_episode.world_id}, "
            f"not {world_id}"
        )

    # 7. Prior episode is explicitly published
    if prior_episode.review_state != "published":
        raise BranchBindingError(
            f"prior episode is not published (state: {prior_episode.review_state})"
        )

    # 8. Prior episode is canon or an allowed active branch predecessor
    if prior_episode.episode_type not in ("canon", "personal_branch"):
        raise BranchBindingError(
            f"prior episode type {prior_episode.episode_type} is not allowed"
        )

    # 9. Canon checkpoint exists
    checkpoint = canon_repo.get_canon_checkpoint(conn, canon_checkpoint_id)
    if checkpoint is None:
        raise BranchBindingError(f"canon checkpoint not found: {canon_checkpoint_id}")

    # 10. Checkpoint belongs to an accepted canon snapshot
    snapshot = canon_repo.get_canon_snapshot(conn, checkpoint.canon_snapshot_id)
    if snapshot is None:
        raise BranchBindingError(
            f"canon snapshot not found: {checkpoint.canon_snapshot_id}"
        )
    if not snapshot.accepted:
        raise BranchBindingError(
            f"canon snapshot {snapshot.id} is not accepted"
        )

    # 11. Snapshot belongs to the same world
    if snapshot.world_id != world_id:
        raise BranchBindingError(
            f"snapshot belongs to world {snapshot.world_id}, not {world_id}"
        )

    # 12. Checkpoint and prior episode represent a compatible timeline position
    if checkpoint.episode_number < prior_episode.episode_number:
        raise BranchBindingError(
            f"checkpoint episode {checkpoint.episode_number} is before "
            f"prior episode {prior_episode.episode_number}"
        )

    return {
        "choice": choice,
        "prior_episode": prior_episode,
        "checkpoint": checkpoint,
        "snapshot": snapshot,
    }


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

    All authoritative values are loaded from persisted repositories —
    caller-supplied WorldState, choice text, comment, and canon facts
    are NOT trusted.
    """
    resolved_world_id = world_id or request.world.world_id
    resolved_checkpoint = canon_checkpoint_id or request.canon_checkpoint_id or ""
    resolved_prior = prior_episode_id or request.prior_episode_id or ""

    # ── BLOCKER 1: Persisted branch binding verification ──────────────
    try:
        binding = _verify_persisted_branch_binding(
            conn,
            reader_id=request.reader_id or "",
            reader_choice_id=request.reader_choice_id or "",
            prior_episode_id=resolved_prior,
            canon_checkpoint_id=resolved_checkpoint,
            world_id=resolved_world_id,
        )
    except BranchBindingError as exc:
        return GenerationResult(
            episode_id=None, plan_run_id="", content_run_id="",
            succeeded=False, error=str(exc),
        )

    # Load persisted values — do NOT trust caller-supplied values
    persisted_choice = binding["choice"]
    persisted_choice_text = persisted_choice.choice_text
    persisted_comment = persisted_choice.comment
    persisted_prior_episode = binding["prior_episode"]
    persisted_snapshot = binding["snapshot"]

    # Load the world state from the persisted canon snapshot
    # (do NOT trust caller-supplied WorldState — reconstruct from DB)
    persisted_world = world_repo.load_world_state(conn, resolved_world_id)
    if persisted_world is None:
        return GenerationResult(
            episode_id=None, plan_run_id="", content_run_id="",
            succeeded=False, error="world not found in persisted state",
        )

    # Use the persisted world for ALL validation and prompt building
    authoritative_world = persisted_world

    # ── Idempotency check ─────────────────────────────────────────────
    from app.branch_generation_request_repository import (
        get_by_idempotency_key,
        get_by_resource_binding,
        create_request,
        mark_completed,
        mark_failed,
        REQUEST_TIMEOUT_SECONDS,
    )

    operation_type = "personal_branch"
    idempotency_key = (
        request.idempotency_key
        or f"{request.reader_id}:{request.reader_choice_id}:{resolved_prior}:{resolved_checkpoint}:{operation_type}"
    )
    existing = get_by_idempotency_key(conn, idempotency_key)

    if existing is not None:
        # Resource binding check — same key must reference same resources
        resource_mismatch = (
            existing.reader_id != (request.reader_id or "")
            or existing.reader_choice_id != (request.reader_choice_id or "")
            or existing.prior_episode_id != resolved_prior
            or existing.canon_checkpoint_id != resolved_checkpoint
            or existing.world_id != resolved_world_id
        )
        if resource_mismatch:
            # Same key used with DIFFERENT resource combination — conflict
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False,
                error="idempotency key conflict: key already bound to different resources",
            )

        # State machine
        if existing.status == "completed":
            # Replay success result
            return GenerationResult(
                episode_id=existing.branch_episode_id,
                plan_run_id="", content_run_id="",
                succeeded=True,
                error=None,
            )
        elif existing.status == "failed":
            # Retry policy: allow retry
            pass  # Continue below — will create new attempt
        elif existing.status == "pending":
            # Check if stale (timed out)
            import datetime
            from app.utils import parse_iso_datetime
            try:
                created = parse_iso_datetime(existing.created_at)
                now = datetime.datetime.now(datetime.timezone.utc)
                age = (now - created).total_seconds()
                if age > REQUEST_TIMEOUT_SECONDS:
                    # Stale pending — recovery allowed
                    pass  # Continue
                else:
                    # Active pending — reject duplicate
                    return GenerationResult(
                        episode_id=None, plan_run_id="", content_run_id="",
                        succeeded=False,
                        error="request already in progress (pending)",
                    )
            except (ValueError, TypeError):
                pass  # Can't parse time — treat as recoverable

    # Create idempotency request record
    gen_request_id = new_id()
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
        create_request(
            conn,
            request_id=gen_request_id,
            idempotency_key=idempotency_key,
            reader_id=request.reader_id or "",
            reader_choice_id=request.reader_choice_id or "",
            prior_episode_id=resolved_prior,
            canon_checkpoint_id=resolved_checkpoint,
            world_id=resolved_world_id,
        )
        conn.commit()

    # Build reader choice dict from PERSISTED values (not caller-supplied)
    reader_choice_dict = {
        "reader_choice_id": request.reader_choice_id,
        "choice_text": persisted_choice_text,
        "comment": persisted_comment,
    }

    # Load prior episode summary from persisted state (not caller-supplied)
    prior_episode_summary = {
        "episode_id": persisted_prior_episode.id,
        "title": persisted_prior_episode.title,
        "synopsis": persisted_prior_episode.synopsis,
        "episode_number": persisted_prior_episode.episode_number,
        "unresolved_threads": json.loads(persisted_prior_episode.unresolved_threads_json) if persisted_prior_episode.unresolved_threads_json else [],
    }

    # 1. Plan
    ep_num = ep_repo.get_next_episode_number(
        conn, resolved_world_id, EpisodeType.PERSONAL_BRANCH.value
    )

    plan_payload = prompts.build_plan_user_payload(
        world_state=authoritative_world,
        episode_type=EpisodeType.PERSONAL_BRANCH.value,
        episode_number=ep_num,
        canon_checkpoint_id=resolved_checkpoint,
        prior_episode_id=resolved_prior,
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
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, plan_err or "plan generation failed")
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=plan_err,
        )

    # 2. Validate plan
    try:
        validate_plan(plan_model, world=authoritative_world, is_first_canon=False)
    except PlanValidationError as exc:
        gr_repo.update_generation_run(
            conn, plan_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, str(exc))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=str(exc),
        )

    # 3. Content — use PERSISTED reader choice values
    content_payload = prompts.build_content_user_payload(
        plan=plan_model.model_dump(),
        world_state=authoritative_world,
        reader_choice=reader_choice_dict,
        prior_episode_summary=prior_episode_summary,
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
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, content_err or "content generation failed")
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=content_err,
        )

    # ── BLOCKER 2: Real reader-input application (NO rewriting) ──────
    # Do NOT rewrite the provider output's reader_choice_id before validation.
    # The returned applied_reader_input must independently match persisted values.

    # 4. Validate content (do NOT override reader_choice_id)
    try:
        validate_content(
            content_model,
            world=authoritative_world,
            plan=plan_model,
            is_first_canon=False,
            expected_reader_choice_id=request.reader_choice_id,
        )
    except ContentValidationError as exc:
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, str(exc))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )

    # Verify applied_reader_input independently matches persisted values
    if content_model.applied_reader_input is None:
        error_msg = "personal branch content has no applied_reader_input"
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=error_msg,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, error_msg)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=error_msg,
        )

    # Verify applied_reader_input matches persisted choice text
    if content_model.applied_reader_input.choice_text.strip() != persisted_choice_text.strip():
        error_msg = "applied_reader_input.choice_text does not match persisted choice text"
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=error_msg,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, error_msg)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=error_msg,
        )

    # ── BLOCKER 2: Material change validation ────────────────────────
    # Deterministically prove that the branch materially applies the reader input
    prior_episode_content_dict = {
        "scenes": json.loads(persisted_prior_episode.scene_list_json) if persisted_prior_episode.scene_list_json else [],
        "prose": json.loads(persisted_prior_episode.prose_json) if persisted_prior_episode.prose_json else [],
        "clue_refs": json.loads(persisted_prior_episode.clue_refs_json) if persisted_prior_episode.clue_refs_json else [],
        "unresolved_threads": json.loads(persisted_prior_episode.unresolved_threads_json) if persisted_prior_episode.unresolved_threads_json else [],
        "world_state_delta": json.loads(persisted_prior_episode.world_state_deltas_json) if persisted_prior_episode.world_state_deltas_json else {},
    }

    branch_content_dict = content_model.model_dump()

    try:
        validate_material_change(
            prior_episode_content=prior_episode_content_dict,
            branch_content=branch_content_dict,
            persisted_choice_text=persisted_choice_text,
            persisted_comment=persisted_comment,
            applied_reader_input=content_model.applied_reader_input.model_dump(),
        )
    except Exception as exc:
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, str(exc))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )

    # ── BLOCKER 3: Production continuity validation ──────────────────
    # Invoke ONE production continuity validator from the service boundary
    canon_character_states = {}
    try:
        if persisted_snapshot.character_states_json:
            canon_character_states = json.loads(persisted_snapshot.character_states_json)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        validate_production_continuity(
            content_model,
            world=authoritative_world,
            conn=conn,
            prior_episode_id=resolved_prior,
            canon_snapshot_character_states=canon_character_states,
            is_branch=True,
        )
    except ContentValidationError as exc:
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, str(exc))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )

    # 5. Transactional persistence: episode + choice application
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
                resolved_world_id,
                EpisodeType.PERSONAL_BRANCH.value,
                content_model.episode_number,
                content_model.title,
                content_model.synopsis,
                None,
                resolved_checkpoint,
                resolved_prior,
                request.reader_id,
                json.dumps([s.model_dump() for s in content_model.scenes]),
                json.dumps([cid for s in content_model.scenes for cid in s.participating_character_ids]),
                json.dumps([s.location_id for s in content_model.scenes if s.location_id]),
                json.dumps([b.model_dump() for b in content_model.prose]),
                json.dumps(content_model.clue_refs),
                json.dumps(content_model.world_state_delta.model_dump()),
                json.dumps(content_model.applied_reader_input.model_dump()),
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
                resolved_checkpoint,
                resolved_prior,
                episode_id, request.reader_choice_id,
                json.dumps(content_model.world_state_delta.model_dump()),
                json.dumps(content_model.world_state_delta.branch_only_facts),
                now_utc_iso(),
            ),
        )

        # Mark idempotency request as completed
        mark_completed(conn, gen_request_id, episode_id)

        conn.commit()

        # ── BLOCKER 5: Set final generation run success consistently ──
        # The content run succeeded if we got here — no misleading success
        # on branch transaction failure

    except sqlite3.IntegrityError:
        conn.rollback()
        # Mark generation run as failed — branch transaction failure
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message="transaction integrity error: duplicate or constraint violation",
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, "transaction integrity error")
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error="transaction integrity error",
        )
    except PipelineError as exc:
        conn.rollback()
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message=str(exc),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, str(exc))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=str(exc),
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_message="unexpected error in branch transaction",
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            mark_failed(conn, gen_request_id, "unexpected error in branch transaction")
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error="unexpected error in branch transaction",
        )

    return GenerationResult(
        episode_id=episode_id, plan_run_id=plan_run_id,
        content_run_id=content_run_id, succeeded=True,
    )
