"""Versioned episode-plan and episode-content prompt contracts.

Prompt versions are recorded in generation_runs.prompt_version and in
accepted episodes. The system prompts instruct the provider to return
structured JSON only, ground every claim in known world-state references,
and refuse unsafe markup.
"""

from __future__ import annotations

from typing import Any

from app.domain.models import WorldState

PLAN_PROMPT_VERSION = "living-fiction-plan-v1"
CONTENT_PROMPT_VERSION = "living-fiction-content-v1"

TASK_EPISODE_PLAN = "episode_plan"
TASK_EPISODE_CONTENT = "episode_content"


def build_plan_system_prompt() -> str:
    return (
        "You are a narrative planner for a Korean serialized urban mystery. "
        "Return ONLY valid JSON matching the EpisodePlan schema. "
        "Every scene must reference known character IDs and location IDs from "
        "the supplied world state. Never invent unknown characters, locations, "
        "or clues. A canon episode must not carry applied reader input. "
        "A personal branch must reference the reader's choice. "
        "Do not include any HTML, script, event handler, or unsafe markup. "
        "Write all human-readable text in Korean."
    )


def build_content_system_prompt() -> str:
    return (
        "You are a narrative writer for a Korean serialized urban mystery. "
        "Return ONLY valid JSON matching the EpisodeContent schema. "
        "Every prose beat must reference a valid scene_id from the plan. "
        "Never invent unknown characters, locations, or clues. "
        "A canon episode must not carry applied reader input. "
        "A personal branch must visibly apply the reader's stored choice. "
        "Maintain character continuity: location, knowledge, injuries, "
        "possessions, and relationships. "
        "Do not include any HTML, script, event handler, javascript URL, "
        "or unsafe markup. Write all prose in Korean."
    )


def build_plan_user_payload(
    *,
    world_state: WorldState,
    episode_type: str,
    episode_number: int,
    canon_checkpoint_id: str | None,
    prior_episode_id: str | None,
    reader_choice: dict[str, Any] | None,
    is_first_canon: bool,
) -> dict[str, Any]:
    return {
        "prompt_version": PLAN_PROMPT_VERSION,
        "world_state": world_state.model_dump(),
        "episode_type": episode_type,
        "episode_number": episode_number,
        "canon_checkpoint_id": canon_checkpoint_id,
        "prior_episode_id": prior_episode_id,
        "reader_choice": reader_choice,
        "is_first_canon": is_first_canon,
    }


def build_content_user_payload(
    *,
    plan: dict[str, Any],
    world_state: WorldState,
    reader_choice: dict[str, Any] | None,
    prior_episode_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "prompt_version": CONTENT_PROMPT_VERSION,
        "plan": plan,
        "world_state": world_state.model_dump(),
        "reader_choice": reader_choice,
        "prior_episode_summary": prior_episode_summary,
    }
