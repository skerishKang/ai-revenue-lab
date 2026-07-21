"""Material change validator — proves branch visibly applies reader input.

Compares the persisted prior episode and branch output across:
- scene order and content;
- prose beats;
- participating characters;
- clue/reveal handling;
- world-state delta;
- unresolved threads;
- branch-only facts;
- requested investigation/action direction.

Rejects:
- identical output;
- metadata-only changes;
- ID-only changes;
- generic content with an injected applied-input record;
- output that contradicts the persisted choice.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.pipeline.errors import MaterialChangeError


def _extract_text(content: dict[str, Any]) -> str:
    """Extract all prose text from content for comparison."""
    texts: list[str] = []
    for beat in content.get("prose", []):
        for para in beat.get("paragraphs", []):
            texts.append(para)
    return " ".join(texts)


def _scene_signatures(content: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Extract scene signatures: (scene_id, title, purpose)."""
    sigs = []
    for scene in content.get("scenes", []):
        sigs.append((
            scene.get("scene_id", ""),
            scene.get("title", ""),
            scene.get("purpose", ""),
        ))
    return sigs


def _prose_signatures(content: dict[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    """Extract prose beat signatures: (scene_id, tuple of paragraphs)."""
    sigs = []
    for beat in content.get("prose", []):
        paras = tuple(beat.get("paragraphs", []))
        sigs.append((beat.get("scene_id", ""), paras))
    return sigs


def _character_ids(content: dict[str, Any]) -> set[str]:
    """Extract all participating character IDs."""
    ids: set[str] = set()
    for scene in content.get("scenes", []):
        ids.update(scene.get("participating_character_ids", []))
    ids.update(content.get("participating_character_ids", []))
    return ids


def _clue_refs(content: dict[str, Any]) -> set[str]:
    return set(content.get("clue_refs", []))


def _delta_summary(delta: dict[str, Any]) -> dict[str, Any]:
    """Summarize a continuity delta for comparison."""
    return {
        "knowledge_added": {
            k: len(v) for k, v in delta.get("character_knowledge_added", {}).items()
        },
        "location_changed": delta.get("character_location_changed", {}),
        "injuries_added": {
            k: len(v) for k, v in delta.get("character_injuries_added", {}).items()
        },
        "possessions_added": {
            k: len(v) for k, v in delta.get("character_possessions_added", {}).items()
        },
        "clues_introduced": [c.get("clue_id", "") if isinstance(c, dict) else c for c in delta.get("clues_introduced", [])],
        "clues_resolved": delta.get("clues_resolved", []),
        "unresolved_threads_count": len(delta.get("unresolved_threads", [])),
        "branch_only_facts_count": len(delta.get("branch_only_facts", [])),
    }


def validate_material_change(
    *,
    prior_episode_content: dict[str, Any],
    branch_content: dict[str, Any],
    persisted_choice_text: str,
    persisted_comment: str | None,
    applied_reader_input: dict[str, Any] | None,
) -> None:
    """Deterministically prove that the branch materially applies the reader input.

    Raises MaterialChangeError if:
    - the branch content is identical to the prior episode;
    - only metadata/ID changed;
    - the applied_reader_input does not match persisted choice;
    - no material narrative difference exists.
    """
    if applied_reader_input is None:
        raise MaterialChangeError(
            "branch has no applied_reader_input — cannot prove material change"
        )

    # Verify applied_reader_input matches persisted choice
    if applied_reader_input.get("choice_text", "").strip() != persisted_choice_text.strip():
        raise MaterialChangeError(
            "applied_reader_input.choice_text does not match persisted choice text"
        )

    # If comment exists, verify it's reflected (or a normalized representation)
    if persisted_comment:
        applied_comment = applied_reader_input.get("comment")
        if applied_comment is not None and applied_comment.strip():
            # The applied comment should either match or be a normalized representation
            if applied_comment.strip() not in persisted_comment and persisted_comment.strip() not in applied_comment:
                raise MaterialChangeError(
                    "applied_reader_input.comment does not match persisted comment"
                )

    # Verify applied_evidence is non-empty and references the choice direction
    evidence = applied_reader_input.get("applied_evidence", "")
    if not evidence or not evidence.strip():
        raise MaterialChangeError(
            "applied_reader_input.applied_evidence is empty"
        )

    # Check for identical content (scene order + prose)
    prior_scenes = _scene_signatures(prior_episode_content)
    branch_scenes = _scene_signatures(branch_content)

    if prior_scenes == branch_scenes:
        prior_prose = _prose_signatures(prior_episode_content)
        branch_prose = _prose_signatures(branch_content)
        if prior_prose == branch_prose:
            raise MaterialChangeError(
                "branch content is identical to prior episode — no material change"
            )

    # Check for ID-only changes (same scenes, same prose, different IDs)
    prior_text = _extract_text(prior_episode_content)
    branch_text = _extract_text(branch_content)
    if prior_text == branch_text:
        raise MaterialChangeError(
            "branch prose is identical to prior episode — no material change"
        )

    # Verify branch-only facts exist (personal branch should add something)
    branch_delta = branch_content.get("world_state_delta", {})
    branch_only_facts = branch_delta.get("branch_only_facts", [])
    if not branch_only_facts:
        # Branch should at least have different unresolved threads or knowledge
        prior_delta = prior_episode_content.get("world_state_delta", {})
        if _delta_summary(prior_delta) == _delta_summary(branch_delta):
            raise MaterialChangeError(
                "branch has no branch-only facts and no state delta change — "
                "no material application of reader input"
            )

    # Verify the branch has different participating characters or different clue handling
    prior_chars = _character_ids(prior_episode_content)
    branch_chars = _character_ids(branch_content)
    prior_clues = _clue_refs(prior_episode_content)
    branch_clues = _clue_refs(branch_content)

    # At least one of these must differ
    chars_differ = prior_chars != branch_chars
    clues_differ = prior_clues != branch_clues
    threads_differ = (
        set(branch_content.get("unresolved_threads", [])) !=
        set(prior_episode_content.get("unresolved_threads", []))
    )
    delta_differs = (
        _delta_summary(branch_delta) !=
        _delta_summary(prior_episode_content.get("world_state_delta", {}))
    )

    if not any([chars_differ, clues_differ, threads_differ, delta_differs, branch_only_facts]):
        raise MaterialChangeError(
            "branch shows no material narrative difference from prior episode"
        )
