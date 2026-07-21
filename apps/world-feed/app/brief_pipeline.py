"""Brief generation pipeline: ranking through provider call."""

from __future__ import annotations

import json
from typing import Any

from app.brief_persist import accept_or_persist
from app.domain.enums import BriefSequence, GenerationTaskType
from app.domain.models import BriefContent, ProviderUsage, ReaderPreferences
from app.errors import BriefGenerationError, NoEligibleEventsError, UsageAccountingError
from app.provider_runtime import build_payload, call_with_retries, finalize_run
from app.ranking import rank_event_ids, select_top
from app.repositories import brief_repository, canonical_event_repository, generation_run_repository
from app.repositories.common import now_utc_iso


def brief_signature(content: BriefContent) -> tuple:
    items = tuple(
        (it.event_id, it.headline, it.explanation, tuple(it.source_ids))
        for it in content.items
    )
    return (content.brief_title, content.deck, items)


def load_brief_signature(conn, brief_id: str) -> tuple:
    brief = brief_repository.get_brief_by_id(conn, brief_id)
    if brief is None:
        return ()
    body = json.loads(brief.body_json)
    return brief_signature(BriefContent.model_validate(body))


def generate_brief(
    *,
    provider: Any,
    settings: Any,
    conn,
    reader,
    sequence: BriefSequence,
    task_type: GenerationTaskType,
    feedback=None,
    prior_signature=None,
):
    events = canonical_event_repository.list_eligible_events(conn)
    if not events:
        raise NoEligibleEventsError(
            "no eligible canonical events to build a brief"
        )

    prefs = ReaderPreferences(**reader.preferences)
    feedback_actions = [feedback.action] if feedback else []
    ranked = rank_event_ids(events, prefs, feedback_actions)
    selected_ids = select_top(ranked, settings.default_brief_size)
    if not selected_ids:
        raise NoEligibleEventsError("ranking produced no selected events")

    selected_map = {e.id: e for e in events if e.id in set(selected_ids)}
    run = generation_run_repository.create_generation_run(
        conn,
        task_type=task_type.value,
        provider="pending",
        advertised_model="pending",
        cost_class="free",
        prompt_version=settings.prompt_version,
    )
    user_payload = build_payload(reader, selected_map, feedback, sequence)

    try:
        result, retry_count, total_latency, agg_usage = call_with_retries(
            provider,
            settings,
            task_type.value,
            "You are a World Feed editor. Produce a Korean microbrief from the "
            "supplied eligible events only. Never invent events.",
            user_payload,
            BriefContent,
            run.id,
        )
    except UsageAccountingError as exc:
        finalize_run(
            conn,
            run.id,
            success=0,
            retry_count=0,
            latency_seconds=0.0,
            usage=ProviderUsage(),
            provider=getattr(provider, "provider", "unknown"),
            advertised_model=getattr(provider, "model", "unknown"),
            cost_class="free",
            validation_status="failed",
            error_category="schema_mismatch",
            error_message=str(exc),
        )
        raise BriefGenerationError(run_id=run.id, message=str(exc)) from exc

    return accept_or_persist(
        conn,
        reader=reader,
        run_id=run.id,
        result=result,
        retry_count=retry_count,
        total_latency=total_latency,
        agg_usage=agg_usage,
        selected_ids=selected_ids,
        selected_map=selected_map,
        sequence=sequence,
        feedback=feedback,
        prior_signature=prior_signature,
        completed_at=now_utc_iso(),
        actual=(
            result.provider,
            result.advertised_model,
            result.cost_class.value,
        ),
        signature_fn=brief_signature,
    )
