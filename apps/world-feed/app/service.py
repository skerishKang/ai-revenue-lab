"""World Feed service: synthetic source -> personalized microbrief."""

from __future__ import annotations

from typing import Any

from app.brief_pipeline import generate_brief
from app.deletion import delete_reader as revoke_reader
from app.domain.enums import BriefSequence, GenerationTaskType
from app.domain.models import (
    FeedbackInput,
    PilotEvidenceInput,
    ReaderProfileInput,
    SourceCard,
)
from app.errors import (
    AlreadyAppliedFeedbackError,
    BriefGenerationError,
    BriefUnchangedError,
    EvidenceValidationError,
    FirstBriefMissingError,
    ForeignFeedbackError,
    IdempotencyConflictError,
    MismatchedPriorBriefError,
    NoEligibleEventsError,
    SourceGroundingError,
    UsageAccountingError,
)
from app.feedback_flow import (
    apply_feedback as persist_reader_feedback,
    generate_second_brief as run_second_brief,
)
from app.privacy import ECONOMIC_HYPOTHESIS, export_safe_evidence, sanitize_evidence_detail
from app.repositories import (
    brief_repository,
    canonical_event_repository,
    pilot_evidence_repository,
    reader_repository,
    source_repository,
)
from app.validators import summarize_source_states

__all__ = [
    "WorldFeedService",
    "BriefGenerationError",
    "NoEligibleEventsError",
    "BriefUnchangedError",
    "AlreadyAppliedFeedbackError",
    "ForeignFeedbackError",
    "MismatchedPriorBriefError",
    "FirstBriefMissingError",
    "SourceGroundingError",
    "EvidenceValidationError",
    "IdempotencyConflictError",
    "UsageAccountingError",
    "ECONOMIC_HYPOTHESIS",
]


class WorldFeedService:
    def __init__(self, provider: Any, settings: Any):
        self.provider = provider
        self.settings = settings

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

    def create_reader(self, conn, profile: ReaderProfileInput):
        return reader_repository.create_reader(conn, profile)

    def set_reader_active(self, conn, reader_id: str, active: bool):
        return reader_repository.set_reader_active(conn, reader_id, active)

    def delete_reader(self, conn, reader_id: str) -> dict:
        return revoke_reader(conn, reader_id)

    def generate_first_brief(self, conn, reader_id: str, request_key=None):
        reader = reader_repository.require_active_reader(conn, reader_id)
        existing = brief_repository.get_latest_by_reader_sequence(
            conn, reader_id, BriefSequence.FIRST.value
        )
        if existing is not None:
            return existing
        return generate_brief(
            provider=self.provider,
            settings=self.settings,
            conn=conn,
            reader=reader,
            sequence=BriefSequence.FIRST,
            task_type=GenerationTaskType.GENERATE_FIRST_MICROBRIEF,
        )

    def apply_feedback(self, conn, feedback: FeedbackInput):
        return persist_reader_feedback(conn, feedback)

    def generate_second_brief(
        self, conn, reader_id: str, *, feedback_idempotency_key: str, request_key=None
    ):
        return run_second_brief(
            self, conn, reader_id, feedback_idempotency_key=feedback_idempotency_key
        )

    def record_pilot_evidence(self, conn, evidence: PilotEvidenceInput):
        reader = reader_repository.get_reader_by_id(conn, evidence.reader_id)
        if reader is None:
            raise EvidenceValidationError(f"reader not found: {evidence.reader_id}")
        brief = brief_repository.get_brief_by_id(conn, evidence.brief_id)
        if brief is None:
            raise EvidenceValidationError(f"brief not found: {evidence.brief_id}")
        if brief.reader_id != evidence.reader_id:
            raise EvidenceValidationError(
                "brief does not belong to the specified reader"
            )
        sanitized = PilotEvidenceInput(
            reader_id=evidence.reader_id,
            brief_id=evidence.brief_id,
            evidence_type=evidence.evidence_type,
            anonymous_token=evidence.anonymous_token,
            detail=sanitize_evidence_detail(evidence.detail),
        )
        return pilot_evidence_repository.record_evidence(conn, sanitized)

    def export_evidence(self, conn, evidence_id: str) -> dict:
        rec = pilot_evidence_repository.get_evidence_by_id(conn, evidence_id)
        if rec is None:
            raise EvidenceValidationError(f"evidence not found: {evidence_id}")
        return export_safe_evidence(rec)
