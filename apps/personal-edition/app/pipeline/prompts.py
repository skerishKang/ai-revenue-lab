"""Versioned editorial-plan and edition-draft prompt contracts.

Contract (PERSONAL_EDITION_MVP_CONTRACT.md section 14): prompt versions, plan
schemas, and content schemas are versioned independently. A published edition
stores the versions used to create it.

This module exposes:
- PLAN_PROMPT_VERSION and DRAFT_PROMPT_VERSION: the version strings recorded
  in generation_runs.prompt_version and in published editions;
- build_plan_system_prompt / build_draft_system_prompt: deterministic, safe
  system prompts that instruct the provider to return structured JSON only, to
  ground every claim in a supplied segment id, and to refuse unsafe markup;
- build_plan_user_payload / build_draft_user_payload: the structured user
  payload passed through the provider boundary (never the raw participant
  token, never full credentials).
"""

from __future__ import annotations

from typing import Any

from app.domain.models import EditorialPlan, InputSegment, ParticipantPreferences

PLAN_PROMPT_VERSION = "personal-edition-plan-v1"
DRAFT_PROMPT_VERSION = "personal-edition-draft-v1"

# Task names recorded in generation_runs.task_type. These are also the keys the
# MockProvider uses to select a fixture response.
TASK_EDITORIAL_PLAN = "editorial_plan"
TASK_EDITION_DRAFT = "edition_draft"
TASK_EDITION_REPAIR = "edition_repair"

REPAIR_PROMPT_VERSION = "personal-edition-repair-v1"


def build_plan_system_prompt(language: str) -> str:
    lang_label = "Korean" if language == "ko" else "English"
    return (
        "You are a careful editorial planner for a personal publication. "
        "Return ONLY valid JSON matching the EditorialPlan schema. "
        "Every section must reference at least one supplied segment id. "
        "Never invent personal facts, relationships, places, dates, amounts, "
        "diagnoses, intentions, or events. Interpretations must be explicitly "
        "labeled and traceable to supplied segments. Do not include any HTML, "
        "script, or unsafe markup. Write the plan in " + lang_label + "."
    )


def build_draft_system_prompt(language: str) -> str:
    lang_label = "Korean" if language == "ko" else "English"
    return (
        "You are a careful edition writer for a personal publication. "
        "Return ONLY valid JSON matching the EditionContent schema. "
        "Every section must reference at least one supplied segment id and at "
        "least one plan section id. Never invent personal facts, "
        "relationships, places, dates, amounts, diagnoses, intentions, or "
        "events. A first edition must not claim prior continuity or applied "
        "feedback. A follow-up edition with feedback must include an "
        "applied_feedback record that names the real feedback id and the "
        "affected sections. Do not include any HTML, script, event handler, "
        "javascript URL, or unsafe markup. Write the edition in "
        + lang_label + "."
    )


def build_plan_user_payload(
    *,
    participant_id: str,
    segments: list[InputSegment],
    preferences: ParticipantPreferences,
    language: str,
    is_follow_up: bool,
    feedback_id: str | None,
    feedback_directions: list[str],
    feedback_free_text: str | None,
    prior_edition_summary: dict[str, Any] | None,
    prohibited_inferences: list[str],
) -> dict[str, Any]:
    """Build the structured user payload for an editorial-plan call.

    Only internal identifiers and segment text are sent. No raw participant
    token, token hash, or credential is ever included.
    """
    return {
        "prompt_version": PLAN_PROMPT_VERSION,
        "language": language,
        "participant_id": participant_id,
        "preferences": preferences.model_dump(),
        "segments": [
            {
                "segment_id": s.segment_id,
                "start_offset": s.start_offset,
                "end_offset": s.end_offset,
                "text": s.text,
            }
            for s in segments
        ],
        "is_follow_up": is_follow_up,
        "feedback_id": feedback_id,
        "feedback_directions": feedback_directions,
        "feedback_free_text": feedback_free_text,
        "prior_edition_summary": prior_edition_summary,
        "prohibited_inferences": prohibited_inferences,
    }


def build_draft_user_payload(
    *,
    participant_id: str,
    segments: list[InputSegment],
    plan: EditorialPlan,
    language: str,
    is_follow_up: bool,
    feedback_id: str | None,
    prohibited_inferences: list[str],
) -> dict[str, Any]:
    """Build the structured user payload for an edition-draft call."""
    return {
        "prompt_version": DRAFT_PROMPT_VERSION,
        "language": language,
        "participant_id": participant_id,
        "plan": plan.model_dump(),
        "segments": [
            {
                "segment_id": s.segment_id,
                "text": s.text,
            }
            for s in segments
        ],
        "is_follow_up": is_follow_up,
        "feedback_id": feedback_id,
        "prohibited_inferences": prohibited_inferences,
    }


def build_repair_system_prompt(language: str) -> str:
    lang_label = "Korean" if language == "ko" else "English"
    return (
        "You are a careful edition repairer for a personal publication. "
        "You are given a previously generated candidate edition that failed "
        "deterministic validation, the normalized validator findings, and a "
        "concise repair instruction. Return ONLY valid JSON matching the "
        "EditionContent schema that fixes every reported finding while "
        "preserving the original intent. Never invent personal facts, "
        "relationships, places, dates, amounts, diagnoses, intentions, or "
        "events. Every section must reference at least one valid supplied "
        "segment id and at least one plan section id. Do not include any HTML, "
        "script, event handler, javascript URL, or unsafe markup. Write the "
        "edition in " + lang_label + "."
    )


def build_repair_user_payload(
    *,
    corrupted_candidate: dict[str, Any],
    validator_findings: list[dict[str, Any]],
    repair_instruction: str,
    correlation_id: str,
    attempt_id: str,
    prohibited_inferences: list[str],
    language: str,
) -> dict[str, Any]:
    """Build the privacy-safe structured user payload for a repair call.

    Contains only the (synthetic) corrupted candidate, normalized validator
    findings, a concise repair instruction, and correlation/attempt identifiers.
    It deliberately excludes raw participant input text and derived segment
    text: the provider receives no private participant material.
    """
    return {
        "prompt_version": REPAIR_PROMPT_VERSION,
        "language": language,
        "correlation_id": correlation_id,
        "attempt_id": attempt_id,
        "repair_instruction": repair_instruction,
        "validator_findings": validator_findings,
        "corrupted_candidate": corrupted_candidate,
        "prohibited_inferences": prohibited_inferences,
    }
