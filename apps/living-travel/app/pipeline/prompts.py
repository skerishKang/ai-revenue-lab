"""Versioned prompt contracts for Living Travel planning and drafting."""

from __future__ import annotations

PLAN_PROMPT_VERSION = "lt-plan-v1"
DRAFT_PROMPT_VERSION = "lt-draft-v1"


def build_plan_prompt(
    *,
    language: str = "ko",
    traveler_preferences: dict,
    source_summaries: list[dict],
) -> tuple[str, str]:
    system = (
        f"Living Travel editorial planner v{PLAN_PROMPT_VERSION}\n"
        f"Language: {language}\n"
        "Produce a structured editorial plan for a travel edition. "
        "Use only the provided source summaries. Do not invent facts. "
        "Classify each planned item as inspiration, stable_reference, or time_sensitive."
    )
    user = {
        "traveler_preferences": traveler_preferences,
        "source_summaries": source_summaries,
    }
    return system, str(user)


def build_draft_prompt(
    *,
    language: str = "ko",
    plan: dict,
    traveler_preferences: dict,
    source_items: list[dict],
    applied_feedback: list[dict] | None = None,
    prior_edition_summary: str = "",
) -> tuple[str, str]:
    system = (
        f"Living Travel edition drafter v{DRAFT_PROMPT_VERSION}\n"
        f"Language: {language}\n"
        "Write a polished travel edition from the editorial plan and source items. "
        "Each place, food, or operational statement must cite its source. "
        "Classify each item's information class. "
        "For time_sensitive items include as_of_date, source_ref, confidence, verify_before_use. "
        "Do not use raw HTML, script tags, or event handlers."
    )
    user = {
        "plan": plan,
        "traveler_preferences": traveler_preferences,
        "source_items": source_items,
        "applied_feedback": applied_feedback or [],
        "prior_edition_summary": prior_edition_summary,
    }
    return system, str(user)
