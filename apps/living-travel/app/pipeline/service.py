"""Generation service orchestrator for Living Travel."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from app.ai.base import AIProvider
from app.domain.enums import (
    EditionGenerationStatus,
    InformationClass,
    PilotEvidenceType,
    SourceConfidence,
)
from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditorialPlan,
    EditionSection,
    InformationItem,
    ProviderResult,
)
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    update_edition_content,
    update_edition_generation_status,
)
from app.feedback_repository import (
    get_unapplied_feedback_for_edition,
    mark_feedback_applied,
)
from app.generation_run_repository import create_generation_run
from app.pilot_evidence_repository import (
    create_pilot_evidence,
    get_pilot_evidence_by_id,
)
from app.pipeline.errors import PipelineError, MarkupError
from app.pipeline.markup import reject_all_content_fields
from app.pipeline.prompts import (
    DRAFT_PROMPT_VERSION,
    PLAN_PROMPT_VERSION,
    build_draft_prompt,
    build_plan_prompt,
)
from app.pipeline.validators import (
    validate_draft_against_plan,
    validate_edition_content,
    validate_no_unsupported_claims,
    validate_plan,
)
from app.traveler_repository import is_traveler_active


# ---------------------------------------------------------------------------
# Content-signature helpers for material-change enforcement
# ---------------------------------------------------------------------------

def _edition_signature(content: EditionContent) -> str:
    """Deterministic signature covering meaningful content fields."""
    parts: list[str] = []
    parts.append(f"pub={content.publication_title}")
    parts.append(f"title={content.edition_title}")
    parts.append(f"opening={content.editorial_opening}")
    parts.append(f"dest={content.destination}")
    parts.append(f"frame={content.trip_frame}")
    for i, sec in enumerate(content.sections):
        parts.append(f"sec[{i}]={sec.section_id}|{sec.title}|{sec.narrative[:200]}")
        for item in sec.items:
            parts.append(
                f"item={item.item_id}|{item.information_class}|{item.source_ref}"
            )
    for af in content.applied_feedback:
        parts.append(f"fb={af.feedback_id}|{af.actual_action}|{af.affected_section_ids}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _is_materially_different(prior: EditionContent, generated: EditionContent) -> bool:
    """Check if the generated edition differs meaningfully from the prior."""
    if _edition_signature(prior) == _edition_signature(generated):
        return False
    # Check that at least one section title or narrative changed
    prior_sections = {s.section_id: (s.title, s.narrative) for s in prior.sections}
    gen_sections = {s.section_id: (s.title, s.narrative) for s in generated.sections}
    if prior_sections == gen_sections:
        # Only metadata changed (or section order rearranged with same content) — reject
        return False
    return True


# ---------------------------------------------------------------------------
# Source-grounding helpers
# ---------------------------------------------------------------------------

def _collect_approved_claims(source_items: list[dict]) -> set[str]:
    """Collect approved claim IDs from persisted source items."""
    claims: set[str] = set()
    for src in source_items:
        for claim in src.get("claims", []):
            claims.add(claim)
    return claims


def _build_source_states(source_items: list[dict]) -> dict[str, str]:
    """Build source_id → state mapping from source items."""
    states: dict[str, str] = {}
    for src in source_items:
        sid = src.get("source_id", "")
        if sid:
            states[sid] = src.get("state", "single_source")
    return states


# ---------------------------------------------------------------------------
# Pilot evidence validation
# ---------------------------------------------------------------------------

_ALLOWED_EVIDENCE_TYPES = {
    PilotEvidenceType.free_sample,
    PilotEvidenceType.paid_edition,
}

_SENSITIVE_PAYMENT_PATTERNS = [
    "\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}",  # credit card
    "(?i)(password|passwd|pwd)\\s*[:=]\\s*\\S+",
    "(?i)(token|secret|bearer)\\s*[:=]\\s*\\S+",
    "\\b(sk-|ak-|pk-)[A-Za-z0-9]{20,}",  # API keys
]


def _redact_sensitive(text: str) -> str:
    """Redact sensitive patterns from text."""
    import re
    result = text
    for pat in _SENSITIVE_PAYMENT_PATTERNS:
        result = re.sub(pat, "[REDACTED]", result)
    return result


class GenerationService:
    MAX_RETRIES = 3

    def __init__(self, conn: sqlite3.Connection, provider: AIProvider) -> None:
        self.conn = conn
        self.provider = provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_first_edition(
        self,
        *,
        traveler_id: str,
        input_id: str | None = None,
        traveler_preferences: dict,
        source_items: list[dict],
    ) -> EditionContent:
        if not is_traveler_active(self.conn, traveler_id):
            raise PipelineError("Traveler is inactive or deleted")

        # Build source states and approved claims from persisted source items
        source_states = _build_source_states(source_items)
        valid_claims = _collect_approved_claims(source_items)

        # Batch ID for failure accounting (survives edition rollback)

        # Record runs outside savepoint so they survive rollback
        all_runs: list[tuple[ProviderResult, str]] = []

        self.conn.execute("SAVEPOINT sp_first")
        try:
            edition = create_edition(
                self.conn,
                traveler_id=traveler_id,
                edition_number=1,
                input_id=input_id,
                commit=False,
            )
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_pending,
                commit=False,
            )

            plan_content = self._generate_plan(
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                run_sink=all_runs,
            )

            content = self._generate_draft(
                plan=plan_content,
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                run_sink=all_runs,
            )

            # Record ALL generation runs for accounting
            self._record_run_batch(all_runs, edition.id, commit=False)

            # Validate with service-owned source grounding and claims
            errors = validate_edition_content(
                content,
                valid_source_ids=set(source_states.keys()),
                valid_claims=valid_claims,
                source_states=source_states,
            )
            if errors:
                raise PipelineError("Validation failed: " + "; ".join(errors))

            reject_all_content_fields(content)

            update_edition_content(self.conn, edition.id, content.model_dump(), commit=False)
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.pending_review,
                commit=False,
            )
            self.conn.execute("RELEASE SAVEPOINT sp_first")
            self.conn.commit()
            return content
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT sp_first")
            self.conn.execute("RELEASE SAVEPOINT sp_first")
            # Record failed runs outside the rollback so accounting survives
            if all_runs:
                self._record_run_batch(all_runs, "", commit=True)
            raise

    def generate_second_edition(
        self,
        *,
        traveler_id: str,
        prior_edition_id: str,
        traveler_preferences: dict,
        source_items: list[dict],
    ) -> EditionContent:
        """Generate second edition with persisted prior-edition binding.

        Accepts a prior_edition_id (not caller-supplied content), loads the
        persisted record, verifies ownership/status, and derives continuity
        from the persisted structured_content only.
        """
        if not is_traveler_active(self.conn, traveler_id):
            raise PipelineError("Traveler is inactive or deleted")

        # Load and verify persisted prior edition
        prior_record = get_edition_by_id(self.conn, prior_edition_id)
        if prior_record is None:
            raise PipelineError(f"Prior edition not found: {prior_edition_id}")
        if prior_record.traveler_id != traveler_id:
            raise PipelineError("Prior edition belongs to a different traveler")
        if prior_record.generation_status not in ("pending_review", "published"):
            raise PipelineError(
                f"Prior edition has invalid status: {prior_record.generation_status}"
            )
        if not prior_record.structured_content:
            raise PipelineError("Prior edition has no structured content")

        # Deserialize prior content from persisted data (not caller-provided)
        prior_content = EditionContent.model_validate(prior_record.structured_content)

        # Load feedback ONLY for this exact prior edition
        feedback_records = get_unapplied_feedback_for_edition(
            self.conn, traveler_id, prior_edition_id
        )
        if not feedback_records:
            raise PipelineError("No unapplied feedback for edition")

        # Validate each feedback row
        for fb in feedback_records:
            if fb.traveler_id != traveler_id:
                raise PipelineError(f"Feedback {fb.id} belongs to different traveler")
            if fb.edition_id != prior_edition_id:
                raise PipelineError(f"Feedback {fb.id} not bound to prior edition {prior_edition_id}")

        applied_feedback_list: list[dict] = []
        for fb in feedback_records:
            applied_feedback_list.append(
                {
                    "feedback_id": fb.id,
                    "direction": fb.direction_choices,
                    "free_text": fb.free_text,
                }
            )

        # Build source states and approved claims
        source_states = _build_source_states(source_items)
        valid_claims = _collect_approved_claims(source_items)

        next_number = prior_record.edition_number + 1

        all_runs: list[tuple[ProviderResult, str]] = []

        self.conn.execute("SAVEPOINT sp_second")
        try:
            edition = create_edition(
                self.conn,
                traveler_id=traveler_id,
                edition_number=next_number,
                prior_edition_id=prior_record.id,
                commit=False,
            )
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.generation_pending,
                commit=False,
            )

            plan_content = self._generate_plan(
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                applied_feedback=applied_feedback_list,
                run_sink=all_runs,
            )

            prior_summary = self._edition_summary(prior_content)

            content = self._generate_draft(
                plan=plan_content,
                traveler_preferences=traveler_preferences,
                source_items=source_items,
                edition_id=edition.id,
                applied_feedback=applied_feedback_list,
                prior_edition_summary=prior_summary,
                run_sink=all_runs,
            )

            # Record ALL generation runs for accounting
            self._record_run_batch(all_runs, edition.id, commit=False)

            # Validate with service-owned source grounding and claims
            errors = validate_edition_content(
                content,
                valid_source_ids=set(source_states.keys()),
                valid_claims=valid_claims,
                source_states=source_states,
            )
            if errors:
                raise PipelineError("Validation failed: " + "; ".join(errors))

            reject_all_content_fields(content)

            # Material-change enforcement: reject identical/superficial output
            if not _is_materially_different(prior_content, content):
                raise PipelineError(
                    "Generated edition is not materially different from prior edition"
                )

            update_edition_content(self.conn, edition.id, content.model_dump(), commit=False)
            update_edition_generation_status(
                self.conn, edition.id, EditionGenerationStatus.pending_review,
                commit=False,
            )
            # Mark only the validated feedback rows as applied
            for fb in feedback_records:
                mark_feedback_applied(self.conn, fb.id, commit=False)
            self.conn.execute("RELEASE SAVEPOINT sp_second")
            self.conn.commit()
            return content
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT sp_second")
            self.conn.execute("RELEASE SAVEPOINT sp_second")
            # Record failed runs outside the rollback so accounting survives
            if all_runs:
                self._record_run_batch(all_runs, "", commit=True)
            raise

    # ------------------------------------------------------------------
    # Pilot evidence validation
    # ------------------------------------------------------------------

    def create_pilot_evidence_validated(
        self,
        *,
        evidence_type: PilotEvidenceType,
        traveler_id: str,
        edition_id: str,
        offer_description: str,
        price_krw: int = 0,
        consent_recorded: bool = False,
        payment_evidence: str = "",
    ) -> "PilotEvidenceRecord":
        """Validated pilot evidence creation with ownership and privacy checks."""
        from app.traveler_repository import get_traveler_by_id

        # Verify traveler exists and is active
        traveler = get_traveler_by_id(self.conn, traveler_id)
        if traveler is None:
            raise PipelineError("Traveler not found or inactive")

        # Verify edition exists and belongs to traveler
        edition = get_edition_by_id(self.conn, edition_id)
        if edition is None:
            raise PipelineError("Edition not found")
        if edition.traveler_id != traveler_id:
            raise PipelineError("Edition belongs to a different traveler")

        # Validate evidence type
        if evidence_type not in _ALLOWED_EVIDENCE_TYPES:
            raise PipelineError(f"Invalid evidence type: {evidence_type}")

        # Validate price/status combinations
        if evidence_type == PilotEvidenceType.free_sample and price_krw != 0:
            raise PipelineError("Free sample must have price_krw=0")
        if evidence_type == PilotEvidenceType.paid_edition and price_krw <= 0:
            raise PipelineError("Paid edition must have positive price_krw")

        # Consent required for paid editions
        if evidence_type == PilotEvidenceType.paid_edition and not consent_recorded:
            raise PipelineError("Paid edition requires consent_recorded=true")

        # Bound offer description length
        if len(offer_description) > 500:
            raise PipelineError("offer_description exceeds 500 characters")

        # Redact sensitive content from payment_evidence
        redacted_payment = _redact_sensitive(payment_evidence)
        redacted_offer = _redact_sensitive(offer_description)

        return create_pilot_evidence(
            self.conn,
            evidence_type=evidence_type,
            traveler_id=traveler_id,
            edition_id=edition_id,
            offer_description=redacted_offer,
            price_krw=price_krw,
            consent_recorded=consent_recorded,
            payment_evidence=redacted_payment,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_plan(
        self,
        *,
        traveler_preferences: dict,
        source_items: list[dict],
        edition_id: str,
        applied_feedback: list[dict] | None = None,
        run_sink: list[tuple[ProviderResult, str]] | None = None,
    ) -> EditorialPlan:
        system, user = build_plan_prompt(
            traveler_preferences=traveler_preferences,
            source_summaries=source_items,
        )

        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_plan_{attempt}"
            result = self.provider.generate_structured(
                task_name="editorial_plan",
                system_prompt=system,
                user_payload={"prompt": user, "applied_feedback": applied_feedback or []},
                response_schema=EditorialPlan,
                request_id=request_id,
            )
            entry = (result, PLAN_PROMPT_VERSION)
            if run_sink is not None:
                run_sink.append(entry)
            if result.success:
                plan = EditorialPlan.model_validate(result.payload)
                plan_errors = validate_plan(plan)
                if not plan_errors:
                    return plan
            if attempt == self.MAX_RETRIES - 1:
                raise PipelineError(
                    f"Plan generation failed after {self.MAX_RETRIES} attempts"
                )

        raise PipelineError("Plan generation exhausted retries")

    def _generate_draft(
        self,
        *,
        plan: EditorialPlan,
        traveler_preferences: dict,
        source_items: list[dict],
        edition_id: str,
        applied_feedback: list[dict] | None = None,
        prior_edition_summary: str = "",
        run_sink: list[tuple[ProviderResult, str]] | None = None,
    ) -> EditionContent:
        system, user = build_draft_prompt(
            plan=plan.model_dump(),
            traveler_preferences=traveler_preferences,
            source_items=source_items,
            applied_feedback=applied_feedback,
            prior_edition_summary=prior_edition_summary,
        )

        for attempt in range(self.MAX_RETRIES):
            request_id = f"{edition_id}_draft_{attempt}"
            result = self.provider.generate_structured(
                task_name="edition_draft",
                system_prompt=system,
                user_payload={"prompt": user},
                response_schema=EditionContent,
                request_id=request_id,
            )
            entry = (result, DRAFT_PROMPT_VERSION)
            if run_sink is not None:
                run_sink.append(entry)
            if result.success:
                content = EditionContent.model_validate(result.payload)
                draft_errors = validate_draft_against_plan(content, plan)
                if not draft_errors:
                    return content
            if attempt == self.MAX_RETRIES - 1:
                raise PipelineError(
                    f"Draft generation failed after {self.MAX_RETRIES} attempts"
                )

        raise PipelineError("Draft generation exhausted retries")

    def _record_run_batch(
        self,
        runs: list[tuple[ProviderResult, str]],
        edition_id: str,
        *, commit: bool = True,
    ) -> None:
        """Record all generation runs from a batch (including retries/failures)."""
        for result, prompt_version in runs:
            create_generation_run(
                self.conn,
                task_type="editorial_plan" if prompt_version == PLAN_PROMPT_VERSION else "edition_draft",
                provider=result.provider,
                advertised_model=result.model,
                cost_class=result.cost_class,
                prompt_version=prompt_version,
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                error_category=result.error_category or "",
                error_message=result.error_message,
                edition_id=edition_id,
                success=result.success,
                commit=commit,
            )

    def _edition_summary(self, content: EditionContent) -> str:
        parts = [content.edition_title, content.editorial_opening]
        for s in content.sections:
            parts.append(f"{s.title}: {s.narrative[:100]}")
        return " | ".join(parts)
