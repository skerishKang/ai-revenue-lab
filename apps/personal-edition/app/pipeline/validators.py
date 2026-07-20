"""Deterministic editorial-plan and edition-draft validation.

Contract references:
- PERSONAL_EDITION_MVP_CONTRACT.md sections 6, 7, 8, 9
- PERSONAL_EDITION_MVP_ARCHITECTURE.md section 9 (generation pipeline stages 1-3)

These validators run after the provider returns a structured payload and before
any edition row is persisted. They are purely deterministic: given the same
segments, plan, and draft, they always accept or always reject. They never call
a model or a network.

Validation layers:
1. reference integrity: every section references only known segment ids, and
   draft section ids must match plan section ids;
2. structural integrity: required sections, unique ids, no missing fields;
3. continuity rules: a first edition cannot claim prior continuity or applied
   feedback; a follow-up edition with feedback must carry an applied_feedback
   record whose affected sections are real plan sections;
4. grounding + markup: delegated to the dedicated modules.
"""

from __future__ import annotations

from typing import Iterable

from app.domain.models import (
    AppliedFeedback,
    EditionContent,
    EditorialPlan,
    EditorialPlanSection,
    InputSegment,
)
from app.pipeline.errors import (
    DraftValidationError,
    PlanValidationError,
)

_MIN_SECTIONS = 2
_MAX_SECTIONS = 4

# Publication/rendering length bounds enforced deterministically. These are
# intentionally lenient (the contract allows language-specific thresholds) but
# must be tested deterministically.
MAX_TITLE_CHARS = 80
MAX_DECK_CHARS = 180
MAX_QUESTION_CHARS = 200
MAX_PARAGRAPHS_PER_SECTION = 4
MAX_PARAGRAPH_CHARS = 1200
MIN_OPENING_CHARS = 20


def _segment_id_set(segments: Iterable[InputSegment]) -> set[str]:
    seen: set[str] = set()
    for seg in segments:
        if seg.segment_id in seen:
            raise PlanValidationError(
                "duplicate segment_id in supplied input: " + seg.segment_id
            )
        seen.add(seg.segment_id)
    return seen


def validate_plan(
    plan: EditorialPlan,
    *,
    segments: list[InputSegment],
    is_follow_up: bool,
    feedback_id: str | None = None,
) -> None:
    """Validate an EditorialPlan against the supplied segments and continuity.

    Raises PlanValidationError on any reference gap, duplicate, or continuity
    violation. A first-edition plan (is_follow_up=False) must not carry prior
    continuity or a feedback action; a follow-up plan must identify the
    applicable feedback action.
    """
    if not isinstance(plan, EditorialPlan):
        raise PlanValidationError("plan must be an EditorialPlan instance")
    if not segments:
        raise PlanValidationError("segments must be a non-empty list")

    known_segments = _segment_id_set(segments)

    if not (_MIN_SECTIONS <= len(plan.sections) <= _MAX_SECTIONS):
        raise PlanValidationError(
            "plan must have between "
            + str(_MIN_SECTIONS)
            + " and "
            + str(_MAX_SECTIONS)
            + " sections"
        )

    section_ids: set[str] = set()
    for section in plan.sections:
        _validate_plan_section(section, known_segments, section_ids)
        section_ids.add(section.section_id)

    continuity = plan.continuity or {}
    prior_refs = continuity.get("prior_edition_references", [])
    applied_feedback_in_plan = continuity.get("applied_feedback")

    if not is_follow_up:
        # First edition: no prior continuity, no applied feedback, no feedback action.
        if prior_refs:
            raise PlanValidationError(
                "first-edition plan must not reference prior editions"
            )
        if applied_feedback_in_plan is not None:
            raise PlanValidationError(
                "first-edition plan must not claim applied feedback"
            )
        for section in plan.sections:
            if section.feedback_action is not None:
                raise PlanValidationError(
                    "first-edition plan section "
                    + section.section_id
                    + " must not carry a feedback_action"
                )
    else:
        # Follow-up: must identify the applicable feedback action in at least
        # one section, and must carry an applied_feedback continuity record
        # pointing at the real feedback id.
        has_feedback_action = any(
            s.feedback_action is not None and s.feedback_action.strip()
            for s in plan.sections
        )
        if not has_feedback_action:
            raise PlanValidationError(
                "follow-up plan must identify the applicable feedback action"
            )
        if not isinstance(applied_feedback_in_plan, dict):
            raise PlanValidationError(
                "follow-up plan must carry an applied_feedback continuity record"
            )
        plan_fb_id = applied_feedback_in_plan.get("feedback_id")
        if feedback_id is None or not isinstance(plan_fb_id, str):
            raise PlanValidationError(
                "follow-up plan applied_feedback must reference a feedback id"
            )
        if plan_fb_id != feedback_id:
            raise PlanValidationError(
                "follow-up plan applied_feedback references a mismatched feedback id"
            )


def _validate_plan_section(
    section: EditorialPlanSection,
    known_segments: set[str],
    seen_ids: set[str],
) -> None:
    if section.section_id in seen_ids:
        raise PlanValidationError(
            "duplicate section_id in plan: " + section.section_id
        )
    if not section.source_segment_ids:
        raise PlanValidationError(
            "section " + section.section_id + " references no segments"
        )
    for ref in section.source_segment_ids:
        if ref not in known_segments:
            raise PlanValidationError(
                "section "
                + section.section_id
                + " references unknown segment id"
            )


def validate_draft(
    draft: EditionContent,
    *,
    plan: EditorialPlan,
    segments: list[InputSegment],
    is_follow_up: bool,
    feedback_id: str | None = None,
) -> None:
    """Validate an EditionContent draft against the accepted plan and segments.

    Raises DraftValidationError (or GroundingError / UnsafeMarkupError from the
    delegated modules) on any failure. Provenance is required. A first edition
    cannot claim prior continuity or applied feedback.
    """
    if not isinstance(draft, EditionContent):
        raise DraftValidationError("draft must be an EditionContent instance")
    if not isinstance(plan, EditorialPlan):
        raise DraftValidationError("plan must be an EditorialPlan instance")
    if not segments:
        raise DraftValidationError("segments must be a non-empty list")

    known_segments = _segment_id_set(segments)
    plan_section_ids = {s.section_id for s in plan.sections}

    if not (_MIN_SECTIONS <= len(draft.sections) <= _MAX_SECTIONS):
        raise DraftValidationError(
            "draft must have between "
            + str(_MIN_SECTIONS)
            + " and "
            + str(_MAX_SECTIONS)
            + " sections"
        )

    # Provenance is required by the contract and by the EditionContent model;
    # double-check here so a future schema relaxation cannot silently drop it.
    if not draft.provenance_note or not draft.provenance_note.strip():
        raise DraftValidationError("provenance_note is required")

    draft_section_ids: set[str] = set()
    for section in draft.sections:
        if section.section_id in draft_section_ids:
            raise DraftValidationError(
                "duplicate section_id in draft: " + section.section_id
            )
        if section.section_id not in plan_section_ids:
            raise DraftValidationError(
                "draft section "
                + section.section_id
                + " is not in the accepted plan"
            )
        if not section.source_segment_ids:
            raise DraftValidationError(
                "draft section " + section.section_id + " references no segments"
            )
        for ref in section.source_segment_ids:
            if ref not in known_segments:
                raise DraftValidationError(
                    "draft section "
                    + section.section_id
                    + " references unknown segment id"
                )
        if len(section.paragraphs) > MAX_PARAGRAPHS_PER_SECTION:
            raise DraftValidationError(
                "draft section "
                + section.section_id
                + " exceeds the paragraph limit"
            )
        for para in section.paragraphs:
            if len(para) > MAX_PARAGRAPH_CHARS:
                raise DraftValidationError(
                    "draft section "
                    + section.section_id
                    + " contains an oversized paragraph"
                )
        draft_section_ids.add(section.section_id)

    # Every plan section must appear in the draft (no missing required sections).
    missing = plan_section_ids - draft_section_ids
    if missing:
        raise DraftValidationError(
            "draft is missing plan sections: " + ", ".join(sorted(missing))
        )

    # Continuity rules.
    if not is_follow_up:
        if draft.continuity_note is not None and draft.continuity_note.strip():
            raise DraftValidationError(
                "first edition must not claim prior continuity"
            )
        if draft.applied_feedback is not None:
            raise DraftValidationError(
                "first edition must not claim applied feedback"
            )
    else:
        af = draft.applied_feedback
        if af is None:
            raise DraftValidationError(
                "follow-up edition with feedback must contain an "
                "applied_feedback record"
            )
        _validate_applied_feedback(af, draft_section_ids, feedback_id)

    # Length bounds on visible scalar fields.
    _check_length(draft.publication_title, "publication_title", MAX_TITLE_CHARS)
    _check_length(draft.edition_title, "edition_title", MAX_TITLE_CHARS)
    _check_length(draft.deck, "deck", MAX_DECK_CHARS)
    if len(draft.opening) < MIN_OPENING_CHARS:
        raise DraftValidationError("opening is too short")
    if draft.next_edition_prompt is not None:
        _check_length(
            draft.next_edition_prompt.question,
            "next_edition_prompt.question",
            MAX_QUESTION_CHARS,
        )


def _validate_applied_feedback(
    af: AppliedFeedback,
    draft_section_ids: set[str],
    expected_feedback_id: str | None,
) -> None:
    if expected_feedback_id is None or af.feedback_id != expected_feedback_id:
        raise DraftValidationError(
            "applied_feedback references a mismatched feedback id"
        )
    for affected in af.affected_section_ids:
        if affected not in draft_section_ids:
            raise DraftValidationError(
                "applied_feedback references an unknown affected section"
            )
    if not af.action.strip() or not af.evidence.strip():
        raise DraftValidationError(
            "applied_feedback action and evidence must be non-empty"
        )


def _check_length(value: str, field_name: str, maximum: int) -> None:
    if not isinstance(value, str):
        raise DraftValidationError(field_name + " must be a string")
    if len(value) > maximum:
        raise DraftValidationError(
            field_name + " exceeds the maximum length of " + str(maximum)
        )


def collect_visible_fields(draft: EditionContent) -> dict[str, str]:
    """Return the visible string fields of a draft for grounding/markup checks.

    Section paragraphs are joined with a newline so a prohibited token cannot
    hide by being split across paragraphs.
    """
    fields: dict[str, str] = {
        "publication_title": draft.publication_title,
        "edition_title": draft.edition_title,
        "deck": draft.deck,
        "opening": draft.opening,
        "highlighted_insight": draft.highlighted_insight,
        "provenance_note": draft.provenance_note,
    }
    if draft.continuity_note is not None:
        fields["continuity_note"] = draft.continuity_note
    if draft.applied_feedback is not None:
        fields["applied_feedback.action"] = draft.applied_feedback.action
        fields["applied_feedback.evidence"] = draft.applied_feedback.evidence
    if draft.next_edition_prompt is not None:
        fields["next_edition_prompt.question"] = draft.next_edition_prompt.question
        for choice in draft.next_edition_prompt.choices:
            fields.setdefault("next_edition_prompt.choices", "")
            fields["next_edition_prompt.choices"] += "\n" + choice
    for section in draft.sections:
        key = "section." + section.section_id
        fields[key + ".title"] = section.title
        fields[key + ".paragraphs"] = "\n".join(section.paragraphs)
    return fields
