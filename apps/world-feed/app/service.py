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

import re
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

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")
_EVIDENCE_DETAIL_MAX = 200


class BriefGenerationError(RuntimeError):
    def __init__(self, run_id: str, message: str):
        self.run_id = run_id
        self.message = message
        super().__init__(message)


class NoEligibleEventsError(RuntimeError):
    pass


class BriefUnchangedError(RuntimeError):
    pass


class AlreadyAppliedFeedbackError(RuntimeError):
    pass


class ForeignFeedbackError(RuntimeError):
    pass


class MismatchedPriorBriefError(RuntimeError):
    pass


class FirstBriefMissingError(RuntimeError):
    pass


class SourceGroundingError(RuntimeError):
    pass


class EvidenceValidationError(RuntimeError):
    pass


class WorldFeedService:
    def __init__(self, provider: Any, settings: Any):
        self.provider = provider
        self.settings = settings

    # ---- ingestion -------------------------------------------------------

    def ingest_source_card(self, conn, card: SourceCard):
        return source_repository.create_source(conn, card)

    def resolve_canonical_events(self, conn) -> int:
        sources = source_repository.list_sources(conn)
        groups: dict[str, list] = {}
        for s in sources:
            groups.setdefault(s.canonical_key, []).append(s)

        count = 0
        for canonical_key, group in groups.items():
            view = summarize_source_states(group)
            primary = view["primary_source"]
            canonical_event_repository.upsert_canonical_event(
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

        if feedback.reader_id != reader_id:
            raise ForeignFeedbackError(
                "feedback belongs to a different reader"
            )

        if feedback.applied_to_brief_id is not None:
            raise AlreadyAppliedFeedbackError(
                "feedback has already been applied"
            )

        first_brief = brief_repository.get_latest_by_reader_sequence(
            conn, reader_id, BriefSequence.FIRST.value
        )
        if first_brief is None:
            raise FirstBriefMissingError(
                "no first brief exists for this reader"
            )

        if feedback.prior_brief_id is None:
            raise MismatchedPriorBriefError(
                "feedback must reference a prior first brief"
            )

        prior_brief = brief_repository.get_brief_by_id(
            conn, feedback.prior_brief_id
        )
        if prior_brief is None:
            raise MismatchedPriorBriefError(
                "referenced prior brief does not exist"
            )
        if prior_brief.reader_id != reader_id:
            raise MismatchedPriorBriefError(
                "referenced prior brief belongs to a different reader"
            )
        if prior_brief.sequence != BriefSequence.FIRST.value:
            raise MismatchedPriorBriefError(
                "referenced prior brief is not the first brief"
            )

        first_signature = self._load_brief_signature(conn, first_brief.id)

        return self._generate_brief(
            conn,
            reader,
            sequence=BriefSequence.SECOND,
            task_type=GenerationTaskType.GENERATE_SECOND_MICROBRIEF,
            feedback=feedback,
            prior_signature=first_signature,
        )

    # ---- pilot evidence --------------------------------------------------

    def record_pilot_evidence(self, conn, evidence: PilotEvidenceInput):
        reader = reader_repository.get_reader_by_id(conn, evidence.reader_id)
        if reader is None:
            raise EvidenceValidationError(
                f"reader not found: {evidence.reader_id}"
            )
        brief = brief_repository.get_brief_by_id(conn, evidence.brief_id)
        if brief is None:
            raise EvidenceValidationError(
                f"brief not found: {evidence.brief_id}"
            )
        if brief.reader_id != evidence.reader_id:
            raise EvidenceValidationError(
                "brief does not belong to the specified reader"
            )
        detail = self._sanitize_evidence_detail(evidence.detail)
        sanitized = PilotEvidenceInput(
            reader_id=evidence.reader_id,
            brief_id=evidence.brief_id,
            evidence_type=evidence.evidence_type,
            anonymous_token=evidence.anonymous_token,
            detail=detail,
        )
        return pilot_evidence_repository.record_evidence(conn, sanitized)

    # ---- internals -------------------------------------------------------

    def _generate_brief(
        self,
        conn,
        reader,
        *,
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
        selected_ids = select_top(ranked, self.settings.default_brief_size)
        if not selected_ids:
            raise NoEligibleEventsError("ranking produced no selected events")

        selected_map = {e.id: e for e in events if e.id in set(selected_ids)}

        run = generation_run_repository.create_generation_run(
            conn,
            task_type=task_type.value,
            provider="pending",
            advertised_model="pending",
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
        actual_provider = result.provider
        actual_model = result.advertised_model
        actual_cost = result.cost_class.value

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
        except Exception as exc:
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

        ok, reason = self._validate_source_grounding(
            content, selected_map, conn
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

        signature = self._brief_signature(content)
        if prior_signature is not None and signature == prior_signature:
            generation_run_repository.update_generation_run(
                conn,
                run.id,
                completed_at=completed_at,
                latency_seconds=total_latency,
                success=1,
                validation_status="unchanged",
                retry_count=retry_count,
                input_tokens=agg_usage.input_tokens,
                output_tokens=agg_usage.output_tokens,
                total_tokens=agg_usage.total_tokens,
            )
            raise BriefUnchangedError(
                "second brief is materially identical to the first"
            )

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
                provider=actual_provider,
                advertised_model=actual_model,
                cost_class=actual_cost,
            )
            if feedback is not None:
                feedback_repository.mark_applied(conn, feedback.id, brief.id)
        return brief

    def _atomic(self, conn):
        from app.db import atomic

        return atomic(conn)

    @staticmethod
    def _brief_signature(content: BriefContent) -> tuple:
        items = tuple(
            (it.event_id, it.headline, it.explanation, tuple(it.source_ids))
            for it in content.items
        )
        return (content.brief_title, content.deck, items)

    def _load_brief_signature(self, conn, brief_id: str) -> tuple:
        brief = brief_repository.get_brief_by_id(conn, brief_id)
        if brief is None:
            return ()
        import json
        body = json.loads(brief.body_json)
        content = BriefContent.model_validate(body)
        return self._brief_signature(content)

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
            u = self._normalize_usage(result.usage)
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

    @staticmethod
    def _normalize_usage(usage: ProviderUsage) -> ProviderUsage:
        it = usage.input_tokens
        ot = usage.output_tokens
        tt = usage.total_tokens
        if tt is None and it is not None and ot is not None:
            tt = it + ot
        return ProviderUsage(input_tokens=it, output_tokens=ot, total_tokens=tt)

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

    def _validate_source_grounding(self, content: BriefContent, selected_map, conn):
        for item in content.items:
            ev = selected_map.get(item.event_id)
            if ev is None:
                return False, f"brief cites unknown event {item.event_id}"
            event_source_ids = set(ev.source_ids)
            if not item.source_ids:
                return (
                    False,
                    f"item for {item.event_id} has empty source_ids",
                )
            seen = set()
            for sid in item.source_ids:
                if sid in seen:
                    return (
                        False,
                        f"duplicate source_id {sid} in item for {item.event_id}",
                    )
                seen.add(sid)
                if sid not in event_source_ids:
                    return (
                        False,
                        f"source_id {sid} not part of cited event {item.event_id}",
                    )
                src = source_repository.get_source_by_id(conn, sid)
                if src is not None and src.source_state in (
                    SourceState.WITHDRAWN.value,
                    SourceState.SUPERSEDED.value,
                ):
                    return (
                        False,
                        f"source_id {sid} is {src.source_state} and cannot be cited",
                    )
        return True, "ok"

    @staticmethod
    def _sanitize_evidence_detail(detail: str) -> str:
        if len(detail) > _EVIDENCE_DETAIL_MAX:
            detail = detail[:_EVIDENCE_DETAIL_MAX]
        detail = _EMAIL_RE.sub("[redacted]", detail)
        detail = _PHONE_RE.sub("[redacted]", detail)
        return detail
