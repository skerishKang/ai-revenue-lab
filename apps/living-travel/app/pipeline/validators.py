"""Deterministic validators for Living Travel."""

from __future__ import annotations

from app.domain.enums import InformationClass, SourceConfidence
from app.domain.models import EditionContent, EditorialPlan, InformationItem
from app.pipeline.errors import ReferenceError_, ValidationError


def _collect_section_ids(content: EditionContent) -> set[str]:
    return {s.section_id for s in content.sections}


def _collect_item_ids(content: EditionContent) -> set[str]:
    ids: set[str] = set()
    for section in content.sections:
        for item in section.items:
            ids.add(item.item_id)
    return ids


def validate_source_references(
    content: EditionContent,
    valid_source_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for section in content.sections:
        for item in section.items:
            if item.source_ref and item.source_ref not in valid_source_ids:
                errors.append(f"Unknown source reference: {item.source_ref} in {item.item_id}")
    return errors


def validate_source_states(
    content: EditionContent,
    source_states: dict[str, str],
) -> list[str]:
    """Reject references to withdrawn or unknown sources."""
    errors: list[str] = []
    for section in content.sections:
        for item in section.items:
            if item.source_ref:
                state = source_states.get(item.source_ref)
                if state is None:
                    errors.append(f"Unknown source: {item.source_ref} in {item.item_id}")
                elif state == "withdrawn":
                    errors.append(f"Withdrawn source: {item.source_ref} in {item.item_id}")
    return errors


def validate_information_class_metadata(
    content: EditionContent,
) -> list[str]:
    errors: list[str] = []
    for section in content.sections:
        for item in section.items:
            # Both stable_reference and time_sensitive require a source_ref
            if item.information_class in (
                InformationClass.time_sensitive,
                InformationClass.stable_reference,
            ):
                if not item.source_ref:
                    errors.append(
                        f"{item.information_class} item {item.item_id} missing source_ref"
                    )
            if item.information_class == InformationClass.time_sensitive:
                if not item.as_of_date:
                    errors.append(
                        f"time_sensitive item {item.item_id} missing as_of_date"
                    )
                if not item.verify_before_use:
                    errors.append(
                        f"time_sensitive item {item.item_id} missing verify_before_use=true"
                    )
                if item.confidence in (SourceConfidence.withdrawn, SourceConfidence.uncertain):
                    errors.append(
                        f"time_sensitive item {item.item_id} has confidence={item.confidence}"
                    )
    return errors


def validate_no_unsupported_claims(
    content: EditionContent,
    valid_claims: set[str],
) -> list[str]:
    """Reject items whose item_id is not in the approved claims set.

    An empty approved-claims set means NO claims are approved, so all
    stable_reference and time_sensitive items must be rejected.
    Pass None to skip claims validation entirely.
    """
    errors: list[str] = []
    for section in content.sections:
        for item in section.items:
            if item.information_class in (
                InformationClass.time_sensitive,
                InformationClass.stable_reference,
            ):
                if item.item_id not in valid_claims:
                    errors.append(
                        f"Unsupported claim: {item.item_id} not in approved claims"
                    )
    return errors


def validate_section_ids_unique(content: EditionContent) -> list[str]:
    ids = [s.section_id for s in content.sections]
    if len(ids) != len(set(ids)):
        dupes = [i for i in ids if ids.count(i) > 1]
        return [f"Duplicate section IDs: {set(dupes)}"]
    return []


def validate_item_ids_unique(content: EditionContent) -> list[str]:
    ids = _collect_item_ids(content)
    id_list = []
    for section in content.sections:
        for item in section.items:
            id_list.append(item.item_id)
    if len(id_list) != len(set(id_list)):
        dupes = [i for i in id_list if id_list.count(i) > 1]
        return [f"Duplicate item IDs: {set(dupes)}"]
    return []


def validate_feedback_references(
    content: EditionContent,
    feedback_section_ids: list[str],
) -> list[str]:
    valid = _collect_section_ids(content)
    errors: list[str] = []
    for sid in feedback_section_ids:
        if sid and sid not in valid:
            errors.append(f"Feedback references unknown section: {sid}")
    return errors


def validate_edition_content(
    content: EditionContent,
    valid_source_ids: set[str] | None = None,
    valid_claims: set[str] | None = None,
    source_states: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_section_ids_unique(content))
    errors.extend(validate_item_ids_unique(content))
    if valid_source_ids is not None:
        errors.extend(validate_source_references(content, valid_source_ids))
    if source_states is not None:
        errors.extend(validate_source_states(content, source_states))
    errors.extend(validate_information_class_metadata(content))
    if valid_claims is not None:
        errors.extend(validate_no_unsupported_claims(content, valid_claims))
    return errors


def validate_plan(plan: EditorialPlan) -> list[str]:
    errors: list[str] = []
    if not plan.central_theme.strip():
        errors.append("Plan missing central_theme")
    if len(plan.sections) < 1:
        errors.append("Plan must have at least 1 section")
    seen: list[str] = []
    for s in plan.sections:
        if s.section_id in seen:
            errors.append(f"Duplicate plan section ID: {s.section_id}")
        seen.append(s.section_id)
    return errors


def validate_draft_against_plan(
    content: EditionContent, plan: EditorialPlan
) -> list[str]:
    errors: list[str] = []
    plan_ids = {s.section_id for s in plan.sections}
    content_ids = {s.section_id for s in content.sections}
    missing = plan_ids - content_ids
    if missing:
        errors.append(f"Draft missing plan sections: {missing}")
    return errors
