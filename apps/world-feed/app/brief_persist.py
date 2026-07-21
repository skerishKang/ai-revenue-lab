"""Validate and atomically persist a successful brief generation."""

from __future__ import annotations

from app.domain.enums import BriefStatus
from app.domain.models import BriefContent
from app.errors import BriefGenerationError, BriefUnchangedError
from app.grounding import (
    validate_content_against_selection,
    validate_source_grounding,
)
from app.provider_runtime import finalize_run
from app.repositories import (
    brief_repository,
    feedback_repository,
    generation_run_repository,
)


def accept_or_persist(
    conn,
    *,
    reader,
    run_id,
    result,
    retry_count,
    total_latency,
    agg_usage,
    selected_ids,
    selected_map,
    sequence,
    feedback,
    prior_signature,
    completed_at,
    actual,
    signature_fn,
):
    actual_provider, actual_model, actual_cost = actual
    common = dict(
        retry_count=retry_count,
        latency_seconds=total_latency,
        usage=agg_usage,
        provider=actual_provider,
        advertised_model=actual_model,
        cost_class=actual_cost,
        completed_at=completed_at,
    )

    if not result.success:
        finalize_run(
            conn,
            run_id,
            success=0,
            error_category=(
                result.error_category.value if result.error_category else None
            ),
            error_message=result.error_message,
            **common,
        )
        raise BriefGenerationError(
            run_id=run_id,
            message=result.error_message or "provider generation failed",
        )

    try:
        content = BriefContent.model_validate(result.payload)
    except Exception as exc:
        finalize_run(
            conn,
            run_id,
            success=0,
            validation_status="failed",
            error_category="schema_mismatch",
            error_message=str(exc),
            **common,
        )
        raise BriefGenerationError(
            run_id=run_id, message="brief content validation failed"
        ) from exc

    for validator in (
        lambda: validate_content_against_selection(content, selected_map),
        lambda: validate_source_grounding(content, selected_map, conn),
    ):
        ok, reason = validator()
        if not ok:
            finalize_run(
                conn,
                run_id,
                success=0,
                validation_status="failed",
                error_category="schema_mismatch",
                error_message=reason,
                **common,
            )
            raise BriefGenerationError(run_id=run_id, message=reason)

    if prior_signature is not None and signature_fn(content) == prior_signature:
        finalize_run(
            conn, run_id, success=1, validation_status="unchanged", **common
        )
        raise BriefUnchangedError(
            "second brief is materially identical to the first"
        )

    from app.db import atomic

    with atomic(conn):
        brief = brief_repository.create_brief(
            conn,
            reader_id=reader.reader_id,
            language=reader.language,
            generation_run_id=run_id,
            sequence=sequence.value,
            status=BriefStatus.PENDING_REVIEW.value,
            title=content.brief_title,
            deck=content.deck,
            body_json=content.model_dump_json(),
            selected_event_ids=selected_ids,
            feedback_id=feedback.id if feedback else None,
            validation_status="passed",
        )
        generation_run_repository.update_generation_run(
            conn,
            run_id,
            completed_at=completed_at,
            latency_seconds=total_latency,
            success=1,
            validation_status="passed",
            retry_count=retry_count,
            input_tokens=agg_usage.input_tokens,
            output_tokens=agg_usage.output_tokens,
            total_tokens=agg_usage.total_tokens,
            provider=actual_provider,
            advertised_model=actual_model,
            cost_class=actual_cost,
        )
        if feedback is not None:
            feedback_repository.mark_applied(conn, feedback.id, brief.id)
    return brief
