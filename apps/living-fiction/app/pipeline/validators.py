"""Deterministic continuity validators for episode plans and content.

These validators run after the provider returns a structured payload and
before any episode row is persisted. They are purely deterministic: given
the same world state, plan, and content, they always accept or reject.

Validation layers:
1. reference integrity — every character/location/clue ID must exist in the
   known world state;
2. structural integrity — unique scene IDs, required fields, no duplicates;
3. continuity rules — first canon has no applied reader input; personal
   branch must visibly apply reader input; character location/knowledge/
   injury consistency;
4. markup + safety — delegated to dedicated modules.
"""

from __future__ import annotations

from typing import Iterable

from app.domain.enums import EpisodeType
from app.domain.models import (
    ContinuityDelta,
    EpisodeContent,
    EpisodePlan,
    WorldState,
)
from app.pipeline.errors import (
    ContinuityError,
    ContentValidationError,
    PlanValidationError,
)
from app.pipeline.markup import check_payload
from app.pipeline.safety import IdentifierPolicy


def _known_character_ids(world: WorldState) -> set[str]:
    return {c.character_id for c in world.characters}


def _known_location_ids(world: WorldState) -> set[str]:
    return {l.location_id for l in world.locations}


def _known_clue_ids(world: WorldState) -> set[str]:
    return {c.clue_id for c in world.clues}


def validate_plan(
    plan: EpisodePlan,
    *,
    world: WorldState,
    is_first_canon: bool = False,
) -> None:
    """Validate an EpisodePlan against the known world state."""
    if not isinstance(plan, EpisodePlan):
        raise PlanValidationError("plan must be an EpisodePlan instance")

    known_chars = _known_character_ids(world)
    known_locs = _known_location_ids(world)

    # Check scene character refs
    for scene in plan.scenes:
        for cid in scene.participating_character_ids:
            if cid not in known_chars:
                raise PlanValidationError(
                    f"scene {scene.scene_id} references unknown character: {cid}"
                )
        if scene.location_id and scene.location_id not in known_locs:
            raise PlanValidationError(
                f"scene {scene.scene_id} references unknown location: {scene.location_id}"
            )

    # Check participating character refs
    for cid in plan.participating_character_ids:
        if cid not in known_chars:
            raise PlanValidationError(
                f"plan references unknown character: {cid}"
            )

    # Check location refs
    for lid in plan.location_ids:
        if lid not in known_locs:
            raise PlanValidationError(
                f"plan references unknown location: {lid}"
            )

    # Check clue refs
    known_clues = _known_clue_ids(world)
    for clid in plan.clue_refs:
        if clid not in known_clues:
            raise PlanValidationError(
                f"plan references unknown clue: {clid}"
            )

    # First canon: no applied reader input, no canon_checkpoint
    if is_first_canon:
        if plan.episode_type != EpisodeType.CANON:
            raise PlanValidationError(
                "first canon episode must be type 'canon'"
            )
        if plan.episode_number != 1:
            raise PlanValidationError(
                "first canon episode must be number 1"
            )
        if plan.canon_checkpoint_id is not None:
            raise PlanValidationError(
                "first canon episode must not reference a prior checkpoint"
            )
        if plan.prior_episode_id is not None:
            raise PlanValidationError(
                "first canon episode must not reference a prior episode"
            )

    # Markup + safety
    check_payload(plan.model_dump())
    policy = IdentifierPolicy()
    policy.check_payload(plan.model_dump())


def validate_content(
    content: EpisodeContent,
    *,
    world: WorldState,
    plan: EpisodePlan,
    is_first_canon: bool = False,
    expected_reader_choice_id: str | None = None,
) -> None:
    """Validate EpisodeContent against the plan and world state."""
    if not isinstance(content, EpisodeContent):
        raise ContentValidationError("content must be an EpisodeContent instance")

    known_chars = _known_character_ids(world)
    known_locs = _known_location_ids(world)
    known_clues = _known_clue_ids(world)

    # Scene consistency
    plan_scene_ids = {s.scene_id for s in plan.scenes}
    for scene in content.scenes:
        if scene.scene_id not in plan_scene_ids:
            raise ContentValidationError(
                f"content scene {scene.scene_id} not in plan"
            )
        for cid in scene.participating_character_ids:
            if cid not in known_chars:
                raise ContentValidationError(
                    f"content references unknown character: {cid}"
                )
        if scene.location_id and scene.location_id not in known_locs:
            raise ContentValidationError(
                f"content references unknown location: {scene.location_id}"
            )

    # Prose beats must match plan scenes
    for beat in content.prose:
        if beat.scene_id not in plan_scene_ids:
            raise ContentValidationError(
                f"prose references unknown scene_id: {beat.scene_id}"
            )

    # Clue refs
    for clid in content.clue_refs:
        if clid not in known_clues:
            raise ContentValidationError(
                f"content references unknown clue: {clid}"
            )

    # Continuity delta — check added knowledge/locations reference known chars
    delta = content.world_state_delta
    for char_id in delta.character_knowledge_added:
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {char_id}"
            )
    for char_id in delta.character_location_changed:
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {char_id}"
            )
        new_loc = delta.character_location_changed[char_id]
        if new_loc not in known_locs:
            raise ContinuityError(
                f"delta moves character {char_id} to unknown location: {new_loc}"
            )
    for char_id in delta.character_injuries_added:
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {char_id}"
            )
    for char_id in delta.character_possessions_added:
        if char_id not in known_chars:
            raise ContinuityError(
                f"delta references unknown character: {char_id}"
            )
    for clue in delta.clues_introduced:
        if clue.clue_id in known_clues:
            raise ContinuityError(
                f"delta introduces duplicate clue: {clue.clue_id}"
            )

    # First canon: no applied reader input
    if is_first_canon:
        if content.applied_reader_input is not None:
            raise ContinuityError(
                "first canon episode must not have applied reader input"
            )

    # Personal branch: must have applied reader input with matching choice ID
    if content.episode_type == EpisodeType.PERSONAL_BRANCH:
        if content.applied_reader_input is None:
            raise ContinuityError(
                "personal branch must have applied reader input"
            )
        if expected_reader_choice_id is not None:
            if content.applied_reader_input.reader_choice_id != expected_reader_choice_id:
                raise ContinuityError(
                    "personal branch applied reader input references "
                    "mismatched choice id"
                )

    # Markup + safety
    check_payload(content.model_dump())
    policy = IdentifierPolicy()
    policy.check_payload(content.model_dump())


def validate_continuity_delta(
    delta: ContinuityDelta,
    *,
    world: WorldState,
    is_branch: bool = False,
) -> None:
    """Validate that a continuity delta is internally consistent with the world."""
    known_chars = _known_character_ids(world)
    known_locs = _known_location_ids(world)
    known_clues = _known_clue_ids(world)

    for char_id in delta.character_knowledge_added:
        if char_id not in known_chars:
            raise ContinuityError(f"unknown character in delta: {char_id}")
    for char_id, loc_id in delta.character_location_changed.items():
        if char_id not in known_chars:
            raise ContinuityError(f"unknown character in delta: {char_id}")
        if loc_id not in known_locs:
            raise ContinuityError(f"unknown location in delta: {loc_id}")
    for char_id in delta.character_injuries_added:
        if char_id not in known_chars:
            raise ContinuityError(f"unknown character in delta: {char_id}")
    for char_id in delta.character_possessions_added:
        if char_id not in known_chars:
            raise ContinuityError(f"unknown character in delta: {char_id}")
    for clue in delta.clues_introduced:
        if clue.clue_id in known_clues:
            raise ContinuityError(
                f"delta introduces duplicate clue: {clue.clue_id}"
            )
    for clid in delta.clues_resolved:
        if clid not in known_clues:
            raise ContinuityError(
                f"delta resolves unknown clue: {clid}"
            )
    if not is_branch and delta.branch_only_facts:
        raise ContinuityError(
            "canon delta must not contain branch-only facts"
        )
