"""Blocker D — Per-item knowledge evidence binding tests.

Verifies that the continuity validator enforces 1:1 knowledge-to-source
binding and rejects adversarial payloads.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from app.domain.enums import EpisodeType
from app.domain.models import (
    ContinuityDelta,
    EpisodeContent,
    ScenePlan,
    ProseBeat,
    WorldState,
    CharacterRef,
    LocationRef,
    ClueRef,
    AppliedReaderInput,
)
from app.pipeline.errors import ContinuityError
from app.pipeline.production_continuity import validate_production_continuity


def _make_world(**overrides) -> WorldState:
    defaults = dict(
        world_id="test-world", version="1.0", premise="A test world",
        characters=[
            CharacterRef(character_id="char-1", canonical_name="Alice",
                         role="protagonist", location_id="loc-1"),
            CharacterRef(character_id="char-2", canonical_name="Bob",
                         role="friend", location_id="loc-1"),
            CharacterRef(character_id="char-3", canonical_name="Carol",
                         role="suspect", location_id="loc-2"),
        ],
        locations=[
            LocationRef(location_id="loc-1", name="Park", connected_locations=["loc-2"]),
            LocationRef(location_id="loc-2", name="Library", connected_locations=["loc-1"]),
        ],
        clues=[
            ClueRef(clue_id="clue-1", description="A mysterious note", resolved=False),
        ],
    )
    defaults.update(overrides)
    return WorldState(**defaults)


def _make_content(**overrides) -> EpisodeContent:
    defaults = dict(
        content_version="1.0", world_id="test-world",
        episode_type=EpisodeType.PERSONAL_BRANCH, episode_number=1,
        title="Test", synopsis="Test",
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-1", "char-2"])],
        prose=[ProseBeat(scene_id="scene-1", paragraphs=["Alice walked in the park."])],
        clue_refs=[], world_state_delta=ContinuityDelta(),
        applied_reader_input=AppliedReaderInput(
            reader_choice_id="c1", choice_text="Test",
            applied_evidence="Evidence"), unresolved_threads=[],
    )
    defaults.update(overrides)
    return EpisodeContent(**defaults)


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS episodes ("
        "id TEXT PRIMARY KEY, scene_list_json TEXT, character_ids_json TEXT, "
        "location_ids_json TEXT, prose_json TEXT, clue_refs_json TEXT, "
        "world_state_deltas_json TEXT, applied_reader_input_json TEXT, "
        "unresolved_threads_json TEXT, world_id TEXT, episode_type TEXT, "
        "episode_number INTEGER, review_state TEXT, title TEXT, synopsis TEXT, "
        "canon_snapshot_id TEXT, canon_checkpoint_id TEXT, prior_episode_id TEXT, "
        "reader_id TEXT, next_choice_options_json TEXT, content_classification TEXT, "
        "generation_run_id TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO episodes (id, unresolved_threads_json, episode_type, "
        "episode_number, review_state) "
        "VALUES ('prior-1', '[]', 'canon', 1, 'published')"
    )
    conn.commit()
    yield conn
    conn.close()


# ── Per-item knowledge binding (1:1) ───────────────────────────────


def test_source_for_item1_does_not_validate_item2(db_conn):
    """Source for knowledge[0] cannot validate knowledge[1].

    Knowledge[0] gets validated by its own source (scene-1).
    Knowledge[1] has an empty source and no prose match — must be rejected.
    """
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Alice discovered something in the park today",
            "Alice learned about the secret vault underground",
        ]},
        character_knowledge_sources={"char-1": [
            "scene-1: Alice observed the park",
            "",  # Empty source for second item — must not reuse item1's source
        ]},
    )
    # Prose only mentions park, not vault
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1",
                         paragraphs=["Alice walked in the park today."])],
        applied_reader_input=None,
        episode_type=EpisodeType.CANON,
    )
    with pytest.raises(ContinuityError, match="unexplained knowledge"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_per_item_source_must_reference_scene_character(db_conn):
    """Per-item source must reference a character in the scene."""
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Alice learned something",
        ]},
        character_knowledge_sources={"char-1": [
            "completely unrelated source text about weather",
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1", paragraphs=["Alice walked in the park."])],
        applied_reader_input=None,
        episode_type=EpisodeType.CANON,
    )
    with pytest.raises(ContinuityError, match="unexplained knowledge"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_valid_per_item_source_binding_passes(db_conn):
    """Each knowledge item with a valid source passes."""
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Alice learned about the park",
            "Alice learned about the library",
        ]},
        character_knowledge_sources={"char-1": [
            "scene-1 char-1: observed the park directly",
            "scene-1 char-2: Bob told Alice about the library",
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1", paragraphs=["Alice walked in the park."])],
    )
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_cross_character_knowledge_rejected(db_conn):
    """Knowledge for char-1 cannot be validated by char-3's source."""
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Alice knows something secret",
        ]},
        character_knowledge_sources={"char-1": [
            "char-3 Carol observed something",  # Wrong character (not in scene)
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1", paragraphs=["Alice walked in the park."])],
        applied_reader_input=None,
        episode_type=EpisodeType.CANON,
    )
    with pytest.raises(ContinuityError, match="unexplained knowledge"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_prose_observed_knowledge_passes(db_conn):
    """Knowledge that appears in prose passes without needing a source."""
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Alice knows the park is empty",
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1",
                         paragraphs=["Alice realized the park is empty today."])],
    )
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_scene_id_in_source_validates_knowledge(db_conn):
    """Source referencing a known scene ID validates the knowledge."""
    world = _make_world()
    delta = ContinuityDelta(
        character_knowledge_added={"char-1": [
            "Something was observed in the archive",
        ]},
        character_knowledge_sources={"char-1": [
            "scene-1: observed during the scene",
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        prose=[ProseBeat(scene_id="scene-1", paragraphs=["Alice walked."])],
        applied_reader_input=None,
        episode_type=EpisodeType.CANON,
    )
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


# ── Relationship pair binding ──────────────────────────────────────


def test_relationship_change_requires_exact_pair(db_conn):
    """Relationship change must reference the exact character pair."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": [
            "char-2:stranger:friend"
        ]},
        character_relationship_evidence={"char-1": [
            "scene-1: Alice and Bob became friends at the park"
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_relationship_noop_rejected(db_conn):
    """No-op relationship change (prior == new) is rejected."""
    world = _make_world()
    world.characters[0].relationships = ["char-2:friend"]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": [
            "char-2:friend:friend"
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="no-op"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


# ── Injury/Possession/Location transitions ─────────────────────────


def test_silent_injury_removal_rejected(db_conn):
    """Injury removed from prior state without explicit delta is rejected."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()

    world = _make_world()
    # broken_arm from prior is NOT in delta's added or removed
    # It should persist by omission — no error
    delta = ContinuityDelta(
        character_injuries_added={"char-1": ["bruised_leg"]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_impossible_location_transition_rejected(db_conn):
    """Location change to non-connected location without explanation rejected."""
    world = _make_world()
    # char-1 is at loc-1. loc-1 IS connected to loc-2, so this should pass.
    delta = ContinuityDelta(
        character_location_changed={"char-1": "loc-2"},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_nonadjacent_movement_without_explanation_rejected(db_conn):
    """Non-adjacent movement without explanation is rejected."""
    world = _make_world()
    # char-3 is at loc-2. loc-2 is connected to loc-1 only.
    # loc-3 is connected to loc-1 only.
    # Moving char-3 from loc-2 to loc-3 requires going through loc-1.
    # Without explanation, this is rejected.
    world.locations.append(LocationRef(
        location_id="loc-3", name="Hospital", connected_locations=["loc-1"]))
    delta = ContinuityDelta(
        character_location_changed={"char-3": "loc-3"},
        character_movement_explanations={},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="impossible location movement"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


# ── Thread/Clue resolution ─────────────────────────────────────────


def test_unresolved_thread_partial_drop_rejected(db_conn):
    """Dropping one thread but keeping another without resolution is rejected."""
    db_conn.execute(
        "UPDATE episodes SET unresolved_threads_json = ? WHERE id = 'prior-1'",
        (json.dumps(["Thread A", "Thread B"]),),
    )
    db_conn.commit()

    world = _make_world()
    delta = ContinuityDelta(
        thread_resolutions={"Thread A": "Resolved"},
    )
    content = _make_content(
        world_state_delta=delta,
        unresolved_threads=["Thread B"],
    )
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_unresolved_thread_drop_without_resolution_rejected(db_conn):
    """Dropping a thread without resolution is rejected."""
    db_conn.execute(
        "UPDATE episodes SET unresolved_threads_json = ? WHERE id = 'prior-1'",
        (json.dumps(["Thread A", "Thread B"]),),
    )
    db_conn.commit()

    world = _make_world()
    delta = ContinuityDelta()
    content = _make_content(
        world_state_delta=delta,
        unresolved_threads=["Thread A"],
    )
    with pytest.raises(ContinuityError, match="dropped without resolution"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_valid_clue_resolution_with_evidence(db_conn):
    """Canon clue resolution with explanation passes."""
    world = _make_world()
    delta = ContinuityDelta(
        clues_resolved=["clue-1"],
        canon_clue_resolution_explanations={"clue-1": "Alice found the note"},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)


def test_clue_resolution_without_explanation_rejected(db_conn):
    """Canon clue resolved without explanation is rejected."""
    world = _make_world()
    delta = ContinuityDelta(
        clues_resolved=["clue-1"],
        canon_clue_resolution_explanations={},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="without explanation"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True)
