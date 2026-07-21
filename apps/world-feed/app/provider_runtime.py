"""Provider retry loop and generation-run finalization helpers."""

from __future__ import annotations

from typing import Any

from app.domain.models import BriefContent, ProviderUsage
from app.repositories import generation_run_repository
from app.repositories.common import now_utc_iso
from app.usage_accounting import aggregate_usage, normalize_usage


def finalize_run(
    conn,
    run_id: str,
    *,
    success: int,
    retry_count: int,
    latency_seconds: float,
    usage: ProviderUsage,
    provider: str,
    advertised_model: str,
    cost_class: str,
    validation_status: str | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
    completed_at: str | None = None,
):
    generation_run_repository.update_generation_run(
        conn,
        run_id,
        completed_at=completed_at or now_utc_iso(),
        latency_seconds=latency_seconds,
        success=success,
        validation_status=validation_status,
        retry_count=retry_count,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        provider=provider,
        advertised_model=advertised_model,
        cost_class=cost_class,
        error_category=error_category,
        error_message=error_message,
    )


def call_with_retries(
    provider: Any,
    settings: Any,
    task_name: str,
    system_prompt: str,
    user_payload: dict,
    schema,
    request_id: str,
):
    parts: list[ProviderUsage] = []
    total_latency = 0.0
    last = None
    attempt = 0
    max_retries = settings.ai_max_retries
    while attempt <= max_retries:
        attempt += 1
        result = provider.generate_structured(
            task_name=task_name,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_schema=schema,
            request_id=f"{request_id}-attempt-{attempt}",
        )
        total_latency += result.latency_seconds
        parts.append(normalize_usage(result.usage))
        if result.success:
            return result, attempt - 1, total_latency, aggregate_usage(parts)
        last = result
    return last, attempt - 1, total_latency, aggregate_usage(parts)


def build_payload(reader, selected_map, feedback, sequence) -> dict:
    items = [
        {
            "event_id": eid,
            "title": ev.title_localized,
            "category": ev.category,
            "status": ev.status,
            "uncertainty": ev.uncertainty_note,
        }
        for eid, ev in selected_map.items()
    ]
    return {
        "reader_id": reader.reader_id,
        "language": reader.language,
        "sequence": sequence.value,
        "eligible_events": items,
        "feedback": (
            {"action": feedback.action, "detail": feedback.detail}
            if feedback
            else None
        ),
    }


# Keep BriefContent import used by call sites for schema typing.
__all__ = [
    "BriefContent",
    "finalize_run",
    "call_with_retries",
    "build_payload",
]
