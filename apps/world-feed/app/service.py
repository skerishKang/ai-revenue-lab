"""World Feed service: synthetic source -> personalized microbrief.

Orchestrates the product loop:

    synthetic source cards
    -> normalize / validate provenance & state
    -> deterministic personalized ranking
    -> first Korean microbrief
    -> persisted explicit feedback
    -> materially changed second microbrief
    -> pending_review
    -> privacy-safe pilot evidence

Every generated brief stays ``pending_review``; publication is never automatic.
Multi-step writes run inside explicit transactions so a failure rolls back
cleanly and never overwrites the last valid brief.
"""

from typing import Any

from app.domain.enums import (
    BriefSequence,
    BriefStatus,
    GenerationTaskType,
    SourceState,
)
from app.domain.models import (
    BriefContent,
    FeedbackInput,
    PilotEvidenceInput,
    ProviderUsage,
    ReaderPreferences,
    ReaderProfileInput,
    SourceCard,
)
from app.ranking import rank_event_ids, select_top
from app.repositories import (
    brief_repository,
    canonical_event_repository,
    feedback_repository,
    generation_run_repository,
    pilot_evidence_repository,
    reader_repository,
    source_repository,
)
from app.repositories.common import (
    NotFoundError,
    now_utc_iso,
)
from app.validators import summarize_source_states


class BriefGenerationError(RuntimeError):
    def __init__(self, run_id: str, message: str):
        self.run_id = run_id
        self.message = message
        super().__init__(message)


class NoEligibleEventsError(RuntimeError):
    pass


class WorldFeedService:
    def __init__(self, provider: Any, settings: Any):
        self.provider = provider
        self.settings = settings

    # ---- ingestion -------------------------------------------------------

    def ingest_source_card(self, conn, card: SourceCard):
        # Pydantic already validated provenance/dates/markup at the edge.
        return source_repository.create_source(conn, card)

    def resolve_canonical_events(self, conn) -> int:
        """Group accepted source cards into deduplicated canonical events.

        Multiple source cards that share a ``canonical_key`` occupy exactly one
        canonical-event slot; the UNIQUE constraint enforces this.
        """
        sources = source_repository.list_sources(conn)
        groups: dict[str, list[SourceCard]] = {}
        for s in sources:
            groups.setdefault(s.canonical_key, []).append(s)

        count = 0
        for canonical_key, group in groups.items():
            view = summarize_source_states(group)
            primary = view["primary_source"]
            upsert = canonical_event_repository.upsert_canonical_event(
                conn,
                canonical_key=canonical_key,
                country=primary.country,
                locality=primary.locality,
                title_original=primary.title,
                title_localized=primary.title,
                category=primary.category,
                start_date=None,
                end_date=None,
                organizer=primary.publisher_name,
                status=view["status"].value,
                uncertainty_note=view["uncertainty_note"],
                source_ids=view["source_ids"],
                conflicting_source_ids=view["conflicting_source_ids"],
                eligible=view["eligible"],
            )
            count += 1
        return count

    # ---- readers ---------------------------------------------------------

    def create_reader(self, conn, profile: ReaderProfileInput):
        return reader_repository.create_reader(conn, profile)

    def set_reader_active(self, conn, reader_id: str, active: bool):
        return reader_repository.set_reader_active(conn, reader_id, active)

    # ---- brief generation ------------------------------------------------

    def generate_first_brief(self, conn, reader_id: str, request_key: str | None = None):
        reader = reader_repository.require_active_reader(conn, reader_id)
        existing = brief_repository.get_latest_by_reader_sequence(
            conn, reader_id, BriefSequence.FIRST.value
        )
        if existing is not None:
            return existing
        return self._generate_brief(
            conn,
            reader,
            sequence=BriefSequence.FIRST,
            task_type=GenerationTaskType.GENERATE_FIRST_MICROBRIEF,
            feedback=None,
        )

    def apply_feedback(self, conn, feedback: FeedbackInput):
        return feedback_repository.persist_feedback(conn, feedback)

    def generate_second_brief(
        self,
        conn,
        reader_id: str,
        *,
        feedback_idempotency_key: str,
        request_key: str | None = None,
    ):
        reader = reader_repository.require_active_reader(conn, reader_id)
        feedback = feedback_repository.get_feedback_by_idempotency_key(
            conn, feedback_idempotency_key
        )
        if feedback is None:
            raise NotFoundError(
                f"feedback not found: {feedback_idempotency_key}"
            )
        # Idempotency: a second brief already produced for this feedback is
        # returned rather than generated again (no duplicate application).
        existing = brief_repository.get_latest_by_reader_sequence(
            conn, reader_id, BriefSequence.SECOND.value
        )
        if existing is not None and existing.feedback_id == feedback.id:
            return existing

        brief = self._generate_brief(
            conn,
            reader,
            sequence=BriefSequence.SECOND,
            task_type=GenerationTaskType.GENERATE_SECOND_MICROBRIEF,
            feedback=feedback,
        )
        # Mark feedback applied exactly once to the produced brief.
        feedback_repository.mark_applied(conn, feedback.id, brief.id)
        return brief

    # ---- pilot evidence --------------------------------------------------

    def record_pilot_evidence(self, conn, evidence: PilotEvidenceInput):
        return pilot_evidence_repository.record_evidence(conn, evidence)

    # ---- internals -------------------------------------------------------

    def _generate_brief(
        self,
        conn,
        reader,
        *,
        sequence: BriefSequence,
        task_type: GenerationTaskType,
        feedback=None,
    ):
        events = canonical_event_repository.list_eligible_events(conn)
        if not events:
            raise NoEligibleEventsError(
                "no eligible canonical events to build a brief"
            )

        prefs = ReaderPreferences(**reader.preferences)
        feedback_actions = [feedback.action] if feedback else []
        ranked = rank_event_ids(events, prefs, feedback_actions)
        selected_ids = select_top(ranked, self.settings.default_brief_size)
        if not selected_ids:
            raise NoEligibleEventsError("ranking produced no selected events")

        selected_map = {e.id: e for e in events if e.id in set(selected_ids)}

        run = generation_run_repository.create_generation_run(
            conn,
            task_type=task_type.value,
            provider="mock",
            advertised_model=self.settings.ai_model,
            cost_class="free",
            prompt_version=self.settings.prompt_version,
        )

        user_payload = self._build_payload(
            reader, selected_map, feedback, sequence
        )
        result, retry_count, total_latency, agg_usage = self._call_with_retries(
            task_type.value,
            "You are a World Feed editor. Produce a Korean microbrief from the "
            "supplied eligible events only. Never invent events.",
            user_payload,
            BriefContent,
            run.id,
        )

        completed_at = now_utc_iso()

        if not result.success:
            generation_run_repository.update_generation_run(
                conn,
                run.id,
                completed_at=completed_at,
                latency_seconds=total_latency,
                success=0,
                retry_count=retry_count,
                input_tokens=agg_usage.input_tokens,
                output_tokens=agg_usage.output_tokens,
                total_tokens=agg_usage.total_tokens,
                error_category=(
                    result.error_category.value if result.error_category else None
                ),
                error_message=result.error_message,
            )
            raise BriefGenerationError(
                run_id=run.id,
                message=result.error_message or "provider generation failed",
            )

        try:
            content = BriefContent.model_validate(result.payload)
        except Exception as exc:  # ValidationError or similar
            generation_run_repository.update_generation_run(
                conn,
                run.id,
                completed_at=completed_at,
                latency_seconds=total_latency,
                success=0,
                validation_status="failed",
                retry_count=retry_count,
                input_tokens=agg_usage.input_tokens,
                output_tokens=agg_usage.output_tokens,
                total_tokens=agg_usage.total_tokens,
                error_category="schema_mismatch",
                error_message=str(exc),
            )
            raise BriefGenerationError(
                run_id=run.id, message="brief content validation failed"
            ) from exc

        ok, reason = self._validate_content_against_selection(
            content, selected_map
        )
        if not ok:
            generation_run_repository.update_generation_run(
                conn,
                run.id,
                completed_at=completed_at,
                latency_seconds=total_latency,
                success=0,
                validation_status="failed",
                retry_count=retry_count,
                input_tokens=agg_usage.input_tokens,
                output_tokens=agg_usage.output_tokens,
                total_tokens=agg_usage.total_tokens,
                error_category="schema_mismatch",
                error_message=reason,
            )
            raise BriefGenerationError(run_id=run.id, message=reason)

        # Success: insert brief and finalize the run atomically.
        with self._atomic(conn):
            brief = brief_repository.create_brief(
                conn,
                reader_id=reader.reader_id,
                language=reader.language,
                generation_run_id=run.id,
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
                run.id,
                completed_at=completed_at,
                latency_seconds=total_latency,
                success=1,
                validation_status="passed",
                retry_count=retry_count,
                input_tokens=agg_usage.input_tokens,
                output_tokens=agg_usage.output_tokens,
                total_tokens=agg_usage.total_tokens,
            )
        return brief

    def _atomic(self, conn):
        from app.db import atomic

        return atomic(conn)

    def _build_payload(self, reader, selected_map, feedback, sequence) -> dict:
        items = []
        for eid, ev in selected_map.items():
            items.append(
                {
                    "event_id": eid,
                    "title": ev.title_localized,
                    "category": ev.category,
                    "status": ev.status,
                    "uncertainty": ev.uncertainty_note,
                }
            )
        return {
            "reader_id": reader.reader_id,
            "language": reader.language,
            "sequence": sequence.value,
            "eligible_events": items,
            "feedback": (
                {
                    "action": feedback.action,
                    "detail": feedback.detail,
                }
                if feedback
                else None
            ),
        }

    def _call_with_retries(
        self, task_name, system_prompt, user_payload, schema, request_id
    ):
        total_latency = 0.0
        total_input = 0
        total_output = 0
        total_tokens = 0
        last = None
        attempt = 0
        max_retries = self.settings.ai_max_retries
        while attempt <= max_retries:
            attempt += 1
            result = self.provider.generate_structured(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=schema,
                request_id=f"{request_id}-attempt-{attempt}",
            )
            total_latency += result.latency_seconds
            u = result.usage
            total_input += u.input_tokens or 0
            total_output += u.output_tokens or 0
            total_tokens += u.total_tokens or 0
            if result.success:
                return (
                    result,
                    attempt - 1,
                    total_latency,
                    ProviderUsage(
                        input_tokens=total_input,
                        output_tokens=total_output,
                        total_tokens=total_tokens,
                    ),
                )
            last = result
        return (
            last,
            attempt - 1,
            total_latency,
            ProviderUsage(
                input_tokens=total_input,
                output_tokens=total_output,
                total_tokens=total_tokens,
            ),
        )

    def _validate_content_against_selection(self, content: BriefContent, selected_map):
        cited = {item.event_id for item in content.items}
        if not cited.issubset(set(selected_map.keys())):
            return False, "brief cites an event outside the selected set"
        for item in content.items:
            ev = selected_map.get(item.event_id)
            if ev is None:
                return False, "brief cites unknown event"
            if ev.status in (SourceState.WITHDRAWN, SourceState.SUPERSEDED):
                return False, "brief cites a non-eligible event"
        conflicting_ids = {
            eid
            for eid, ev in selected_map.items()
            if ev.status == SourceState.CONFLICTING
        }
        if conflicting_ids:
            joined = " ".join(content.uncertainty_notes)
            for item in content.items:
                if item.event_id in conflicting_ids and item.event_id not in joined:
                    return (
                        False,
                        "conflicting event cited without an uncertainty note",
                    )
        return True, "ok"
