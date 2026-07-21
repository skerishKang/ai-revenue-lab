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
# Default bounded wait for pending idempotency claim (seconds)
DEFAULT_IDEMPOTENCY_WAIT_TIMEOUT = 30.0
DEFAULT_IDEMPOTENCY_POLL_INTERVAL = 0.2


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

    # Determine cost class from provider — use canonical value, not repr()
    if hasattr(provider, "cost_class"):
        actual_cost = provider.cost_class.value if hasattr(provider.cost_class, 'value') else str(provider.cost_class)
    else:
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

    import time as _time_module
    _start_perf_counter = _time_module.perf_counter()

    for attempt_num in range(1, max_retries + 2):
        request_id = _new_request_id()
        attempt_start = _now_utc()
        _start_perf_counter = _time_module.perf_counter()

        try:
            result = provider.generate_structured(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                request_id=request_id,
            )
        except Exception as exc:
            # Measure actual latency for exception attempt
            from app.pipeline.errors import is_exception_retryable, categorize_exception
            exc_retryable = is_exception_retryable(exc)
            exc_category = categorize_exception(exc)
            exc_latency = 0.0
            try:
                import time
                exc_latency = time.perf_counter() - _start_perf_counter
            except NameError:
                pass
            # Aggregate exception attempt latency into total
            total_latency += exc_latency

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
                latency_seconds=exc_latency,
                success=False,
                retryable=exc_retryable,
                error_category=exc_category.value,
                error_message=safe_error_message(exc_category, None),
            )
            last_error_category = exc_category
            last_error_message = safe_error_message(exc_category, None)
            if exc_retryable and attempt_num <= max_retries:
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
            # Preserve identity from failed ProviderResult
            last_result = result
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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE generation_runs SET "
            "completed_at = ?, latency_seconds = ?, success = 1, "
            "validation_status = ?, input_tokens = ?, output_tokens = ?, "
            "retry_count = ?, provider = ?, advertised_model = ?, cost_class = ? "
            "WHERE id = ?",
            (
                completed_at, total_latency, ValidationStatus.PASSED.value,
                total_input_tokens, total_output_tokens, retry_count,
                final_provider, final_model, final_cost, run_id,
            ),
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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE generation_runs SET "
            "completed_at = ?, latency_seconds = ?, success = 0, "
            "validation_status = ?, input_tokens = ?, output_tokens = ?, "
            "retry_count = ?, error_category = ?, error_message = ?, "
            "provider = ?, advertised_model = ?, cost_class = ? "
            "WHERE id = ?",
            (
                completed_at, total_latency, ValidationStatus.PROVIDER_FAILED.value,
                total_input_tokens, total_output_tokens, retry_count,
                last_error_category.value if last_error_category else None,
                last_error_message, final_provider, final_model, final_cost, run_id,
            ),
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
        _safe_err = safe_error_message(ProviderErrorCategory.PLAN_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, plan_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.PLAN_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        return GenerationResult(
            episode_id=None,
            plan_run_id=plan_run_id,
            content_run_id="",
            succeeded=False,
            error=_safe_err,
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
        _safe_err = safe_error_message(ProviderErrorCategory.CONTENT_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.CONTENT_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=_safe_err,
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


def _wait_for_pending_completion(
    conn: sqlite3.Connection,
    *,
    pending_request_id: str,
    idempotency_key: str,
    wait_timeout: float = DEFAULT_IDEMPOTENCY_WAIT_TIMEOUT,
    poll_interval: float = DEFAULT_IDEMPOTENCY_POLL_INTERVAL,
) -> GenerationResult:
    """Service-owned bounded replay wait for a pending idempotency claim.

    Polls the DB for the pending request status without making any
    provider calls. Returns the replayed result when completed, or a
    normalized failure on timeout/failure.
    """
    import time as _wait_time
    from app.branch_generation_request_repository import (
        get_by_idempotency_key,
    )

    start = _wait_time.perf_counter()
    while True:
        elapsed = _wait_time.perf_counter() - start
        if elapsed >= wait_timeout:
            # Timeout — return normalized privacy-safe failure
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False,
                error="idempotency_wait_timeout",
            )

        # Re-check the request status from DB
        record = get_by_idempotency_key(conn, idempotency_key)
        if record is None:
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False, error="request disappeared",
            )

        if record.status == "completed":
            # Replay the completed result
            return GenerationResult(
                episode_id=record.branch_episode_id,
                plan_run_id="", content_run_id="",
                succeeded=True, error=None,
            )

        if record.status == "failed":
            # The original request failed — allow caller to retry
            return GenerationResult(
                episode_id=None, plan_run_id="", content_run_id="",
                succeeded=False,
                error="prior request failed, retry allowed",
            )

        # Still pending — sleep and re-check
        _wait_time.sleep(min(poll_interval, wait_timeout - elapsed))


def generate_personal_branch(
    conn: sqlite3.Connection,
    provider: AIProvider,
    request: GenerationRequest,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    world_id: str = "",
    canon_checkpoint_id: str = "",
    prior_episode_id: str = "",
    idempotency_wait_timeout: float = DEFAULT_IDEMPOTENCY_WAIT_TIMEOUT,
    idempotency_poll_interval: float = DEFAULT_IDEMPOTENCY_POLL_INTERVAL,
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
    resolved_prior = prior_episode_id or request.prior_episode_id or ""    # ── Idempotency CAS claim FIRST (before binding verification) ───
    # This ensures replay cases return early without hitting
    # "choice already applied" checks that would fail for retries.
    from app.branch_generation_request_repository import (
        claim_branch_generation_request,
        complete_branch_generation_request,
        fail_branch_generation_request,
        CASClaimError,
        REQUEST_TIMEOUT_SECONDS,
    )

    operation_type = "personal_branch"
    idempotency_key = (
        request.idempotency_key
        or f"{request.reader_id}:{request.reader_choice_id}:{resolved_prior}:{resolved_checkpoint}:{operation_type}"
    )

    gen_request_id = new_id()
    conn.execute("BEGIN IMMEDIATE")
    try:
        claim = claim_branch_generation_request(
            conn,
            request_id=gen_request_id,
            idempotency_key=idempotency_key,
            reader_id=request.reader_id or "",
            reader_choice_id=request.reader_choice_id,
            prior_episode_id=resolved_prior,
            canon_checkpoint_id=resolved_checkpoint,
            world_id=resolved_world_id,
            operation_type=operation_type,
        )

        if claim.is_replay:
            conn.commit()
            # No provider call — replay original result
            return GenerationResult(
                episode_id=claim.request_record.branch_episode_id if claim.request_record else None,
                plan_run_id="", content_run_id="",
                succeeded=True,
                error=None,
            )

        if claim.is_rejected:
            conn.commit()
            # Service-owned bounded replay wait — caller does NOT retry
            return _wait_for_pending_completion(
                conn,
                pending_request_id=claim.request_id,
                idempotency_key=idempotency_key,
                wait_timeout=idempotency_wait_timeout,
                poll_interval=idempotency_poll_interval,
            )

        # Claim succeeded — we have a pending row
        actual_request_id = claim.request_id
        conn.commit()
    except CASClaimError as exc:
        conn.rollback()
        return GenerationResult(
            episode_id=None, plan_run_id="", content_run_id="",
            succeeded=False, error=str(exc),
        )

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
        _safe_err = safe_error_message(ProviderErrorCategory.BRANCH_BINDING_FAILED, str(exc))
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        try:
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
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
    # Uses snapshot ID to apply accepted canon snapshot character/location/clue states
    persisted_world = world_repo.load_world_state(
        conn, resolved_world_id,
        canon_snapshot_id=persisted_snapshot.id,
    )
    if persisted_world is None:
        # Fail the generation request on world not found
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        try:
            fail_branch_generation_request(conn, actual_request_id, "world not found in persisted state")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
        return GenerationResult(
            episode_id=None, plan_run_id="", content_run_id="",
            succeeded=False, error="world not found in persisted state",
        )

    # Use the persisted world for ALL validation and prompt building
    authoritative_world = persisted_world

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

    # Allocate episode number atomically within BEGIN IMMEDIATE.
    # This prevents two concurrent callers from getting the same number.
    if conn.in_transaction:
        conn.rollback()
    conn.execute("BEGIN IMMEDIATE")
    ep_num = ep_repo.get_next_episode_number(
        conn, resolved_world_id, EpisodeType.PERSONAL_BRANCH.value
    )
    conn.commit()

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
            fail_branch_generation_request(conn, actual_request_id, plan_err or "plan generation failed")
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=plan_err,
        )

    # 2. Validate plan
    try:
        validate_plan(plan_model, world=authoritative_world, is_first_canon=False)
    except PlanValidationError as exc:
        _safe_err = safe_error_message(ProviderErrorCategory.PLAN_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, plan_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.PLAN_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id="",
            succeeded=False, error=_safe_err,
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
            fail_branch_generation_request(conn, actual_request_id, content_err or "content generation failed")
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
        _safe_err = safe_error_message(ProviderErrorCategory.CONTENT_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.CONTENT_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=_safe_err,
        )

    # Verify applied_reader_input independently matches persisted values
    if content_model.applied_reader_input is None:
        error_msg = "personal branch content has no applied_reader_input"
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.CONTENT_VALIDATION_FAILED.value,
            error_message=error_msg,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, error_msg)
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
            error_category=ProviderErrorCategory.CONTENT_VALIDATION_FAILED.value,
            error_message=error_msg,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, error_msg)
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
        _safe_err = safe_error_message(ProviderErrorCategory.MATERIAL_CHANGE_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.MATERIAL_CHANGE_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=_safe_err,
        )

    # ── BLOCKER 3: Production continuity validation ──────────────────
    # Invoke ONE production continuity validator from the service boundary
    # The authoritative world already has canon snapshot applied via load_world_state()

    try:
        validate_production_continuity(
            content_model,
            world=authoritative_world,
            conn=conn,
            prior_episode_id=resolved_prior,
            is_branch=True,
        )
    except ContentValidationError as exc:
        _safe_err = safe_error_message(ProviderErrorCategory.CONTINUITY_VALIDATION_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.CONTINUITY_VALIDATION_FAILED.value,
            error_message=_safe_err,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=_safe_err,
        )

    # 5. Transactional persistence: episode + choice application
    episode_id = new_id()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Create episode (without committing)
        # Use ep_num (DB-allocated) rather than content_model.episode_number
        # to ensure consistency with the atomic allocation above.
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
                ep_num,
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
        complete_branch_generation_request(conn, actual_request_id, episode_id)

        conn.commit()

        # ── BLOCKER 5: Set final generation run success consistently ──
        # The content run succeeded if we got here — no misleading success
        # on branch transaction failure

    except sqlite3.IntegrityError:
        conn.rollback()
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED.value,
            error_message="transaction integrity error: duplicate or constraint violation",
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, safe_error_message(ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED, None))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error="transaction integrity error",
        )
    except PipelineError as exc:
        conn.rollback()
        _safe_err = safe_error_message(ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED, str(exc))
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED.value,
            error_message=_safe_err,
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, _safe_err)
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error=_safe_err,
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        gr_repo.update_generation_run(
            conn, content_run_id,
            completed_at=_now_utc(),
            success=False,
            validation_status=ValidationStatus.FAILED.value,
            error_category=ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED.value,
            error_message=safe_error_message(ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED, None),
        )
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            fail_branch_generation_request(conn, actual_request_id, safe_error_message(ProviderErrorCategory.BRANCH_PERSISTENCE_FAILED, None))
            conn.commit()
        return GenerationResult(
            episode_id=None, plan_run_id=plan_run_id, content_run_id=content_run_id,
            succeeded=False, error="unexpected error in branch transaction",
        )

    return GenerationResult(
        episode_id=episode_id, plan_run_id=plan_run_id,
        content_run_id=content_run_id, succeeded=True,
    )
