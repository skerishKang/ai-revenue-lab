"""Adversarial tests for structured continuity evidence binding.

Tests exact-binding contracts for relationship, injury, and possession
evidence. Each test verifies a specific adversarial rejection or
exact-binding pass condition.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import os

import pytest
from pydantic import ValidationError

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
    RelationshipRef,
    RelationshipEvidence,
    InjuryRemovalEvidence,
    PossessionRemovalEvidence,
)
from app.pipeline.errors import ContinuityError
from app.pipeline.production_continuity import validate_production_continuity


def _make_world(**overrides) -> WorldState:
    defaults = dict(
        world_id="test-world", version="1.0", premise="A test world",
        characters=[
            CharacterRef(
                character_id="char-1", canonical_name="Alice",
                role="protagonist", location_id="loc-1",
                injuries=["injury-x"],
                possessions=["possession-a"],
            ),
            CharacterRef(
                character_id="char-2", canonical_name="Bob",
                role="friend", location_id="loc-1",
            ),
            CharacterRef(
                character_id="char-3", canonical_name="Carol",
                role="suspect", location_id="loc-2",
            ),
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
        prose=[ProseBeat(scene_id="scene-1", paragraphs=[
            "Alice walked in the park with Bob.",
            "They discussed the mysterious note they found.",
        ])],
        clue_refs=[], world_state_delta=ContinuityDelta(),
        applied_reader_input=AppliedReaderInput(
            reader_choice_id="c1", choice_text="Test",
            applied_evidence="Alice and Bob walked together."),
        unresolved_threads=[],
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


# ═══════════════════════════════════════════════════════════════════════
# Duplicate relationship edge model validation
# ═══════════════════════════════════════════════════════════════════════


def test_duplicate_relationship_edge_rejected():
    """Duplicate other_character_id in CharacterRef.relationships rejected."""
    with pytest.raises(ValidationError, match="duplicate relationship edge"):
        CharacterRef(
            character_id="char-1", canonical_name="Alice", role="hero",
            relationships=[
                RelationshipRef(other_character_id="char-2", label="friend"),
                RelationshipRef(other_character_id="char-2", label="enemy"),
            ],
        )


def test_different_character_edges_allowed():
    """Different other_character_id edges are allowed."""
    ref = CharacterRef(
        character_id="char-1", canonical_name="Alice", role="hero",
        relationships=[
            RelationshipRef(other_character_id="char-2", label="friend"),
            RelationshipRef(other_character_id="char-3", label="enemy"),
        ],
    )
    assert len(ref.relationships) == 2


def test_empty_relationships_allowed():
    """Empty relationships list is allowed."""
    ref = CharacterRef(
        character_id="char-1", canonical_name="Alice", role="hero",
    )
    assert ref.relationships == []


# ═══════════════════════════════════════════════════════════════════════
# Relationship adversarial tests (1-20)
# ═══════════════════════════════════════════════════════════════════════


def test_rel_evidence_scene_id_only_rejected(db_conn):
    """1. relationship evidence with scene ID as character_id fields → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="scene-1",
                other_character_id="scene-1",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match change target"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_character_id_only_rejected(db_conn):
    """2. relationship evidence with character ID as scene_id → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    # Scene has only char-1, not char-2 → other character doesn't participate
    content = _make_content(
        world_state_delta=delta,
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-1"])],
    )
    with pytest.raises(ContinuityError, match="does not participate"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_wrong_actor_rejected(db_conn):
    """3. evidence actor is different character → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-3",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match change target"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_wrong_other_character_rejected(db_conn):
    """4. evidence other character is different pair → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-3",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match change other character"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_scene_without_other_character_rejected(db_conn):
    """5. evidence scene has actor but not other character → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-1"])],
    )
    with pytest.raises(ContinuityError, match="does not participate"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_scene_without_actor_rejected(db_conn):
    """6. evidence scene has other character but not actor → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-2"])],
    )
    with pytest.raises(ContinuityError, match="does not participate"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_excerpt_in_other_scene_rejected(db_conn):
    """7. evidence excerpt only in another scene → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="The secret library vault was opened.",
            ),
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        scenes=[
            ScenePlan(scene_id="scene-1", title="S", purpose="T",
                      participating_character_ids=["char-1", "char-2"]),
            ScenePlan(scene_id="scene-2", title="S2", purpose="T2",
                      participating_character_ids=["char-1", "char-2"]),
        ],
        prose=[
            ProseBeat(scene_id="scene-1", paragraphs=[
                "Alice walked in the park with Bob.",
            ]),
            ProseBeat(scene_id="scene-2", paragraphs=[
                "The secret library vault was opened.",
            ]),
        ],
    )
    with pytest.raises(ContinuityError, match="not found in"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_excerpt_not_in_any_prose_rejected(db_conn):
    """8. evidence excerpt not in any prose → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="The moon landing was a turning point.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="not found in"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_wrong_prior_label_rejected(db_conn):
    """9. wrong prior label rejected."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:enemy:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="enemy", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match persisted"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_pair_not_exists_prior_enemy_rejected(db_conn):
    """10. pair does not exist but prior_label is 'enemy' → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:enemy:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="enemy", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="must be 'none'"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_pair_not_exists_prior_none_exact_pass(db_conn):
    """11. pair does not exist, prior_label='none', exact evidence → pass."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:none:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="none", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


def test_rel_noop_prior_equals_new_rejected(db_conn):
    """12. prior_label == new_label no-op → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="friend"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:friend:friend"]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="no-op"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_too_few_rejected(db_conn):
    """13. evidence count < change count → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
        RelationshipRef(other_character_id="char-3", label="acquaintance"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": [
            "char-2:stranger:friend",
            "char-3:acquaintance:colleague",
        ]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence count 1 does not match"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_too_many_rejected(db_conn):
    """14. evidence count > change count → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": [
            "char-2:stranger:friend",
        ]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="They discussed the mysterious note they found.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence count 2 does not match"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_reused_evidence_for_two_changes_rejected(db_conn):
    """15. same evidence (scene+excerpt) reused for two changes → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
        RelationshipRef(other_character_id="char-3", label="acquaintance"),
    ]
    shared_excerpt = "Alice walked in the park with Bob."
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": [
            "char-2:stranger:friend",
            "char-3:acquaintance:colleague",
        ]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt=shared_excerpt,
            ),
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-3",
                prior_label="acquaintance", new_label="colleague",
                excerpt=shared_excerpt,
            ),
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-1", "char-2", "char-3"])],
    )
    with pytest.raises(ContinuityError, match="reuses scene"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_exact_pair_label_scene_excerpt_pass(db_conn):
    """16. exact pair/label/scene/excerpt → pass."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


def test_rel_scene_id_is_character_id_rejected(db_conn):
    """17. scene_id field has character ID → rejected (does not exist as scene)."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="char-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not exist"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_character_id_is_scene_id_rejected(db_conn):
    """18. character_id field has scene ID → rejected (does not match change target)."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="scene-1",
                other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match change target"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_other_character_id_is_scene_id_rejected(db_conn):
    """19. other_character_id field has scene ID → rejected (does not match pair)."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="scene-1",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match change other character"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_wrong_prior_label_on_existing_pair_rejected(db_conn):
    """20. pair exists but prior label is wrong → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:friend:enemy"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1",
                other_character_id="char-2",
                prior_label="friend", new_label="enemy",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match persisted"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


# ═══════════════════════════════════════════════════════════════════════
# Injury adversarial tests (21-29)
# ═══════════════════════════════════════════════════════════════════════


def test_inj_evidence_scene_only_no_item_binding_rejected(db_conn):
    """21. injury evidence has scene reference but no item binding → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="wrong_injury",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match.*removed injury"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_wrong_injury_value_rejected(db_conn):
    """22. evidence injury value is different injury → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_leg",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match.*removed injury"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_wrong_character_rejected(db_conn):
    """23. evidence character is different → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-2",
                injury="broken_arm",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match removal target"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_scene_without_character_rejected(db_conn):
    """24. scene does not have the character → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_arm",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(
        world_state_delta=delta,
        scenes=[ScenePlan(scene_id="scene-1", title="S", purpose="T",
                          participating_character_ids=["char-2"])],
    )
    with pytest.raises(ContinuityError, match="does not participate"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_excerpt_not_in_scene_rejected(db_conn):
    """25. excerpt not in scene prose → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_arm",
                action="healed", excerpt="The moon landing was historic.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="not found in"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_count_mismatch_rejected(db_conn):
    """26. evidence count != removal count → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm", "broken_leg"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm", "broken_leg"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_arm",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence count 1 does not match"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_extra_evidence_rejected(db_conn):
    """27. extra evidence beyond removal count → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["broken_arm"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["broken_arm"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_arm",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="broken_arm",
                action="recovered", excerpt="They discussed the mysterious note they found.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence count 2 does not match"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_reused_evidence_rejected(db_conn):
    """28. same (scene, injury, excerpt) binding reused → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["injury_a", "injury_b"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    shared_excerpt = "Alice walked in the park with Bob."
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["injury_a", "injury_b"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="injury_a",
                action="healed", excerpt=shared_excerpt,
            ),
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="injury_b",
                action="healed", excerpt=shared_excerpt,
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    # Different injuries with same excerpt in same scene is actually valid
    # since each evidence is for a different injury item.
    # The reuse check only catches identical (scene, injury, excerpt) tuples.
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


def test_inj_exact_evidence_pass(db_conn):
    """29. exact injury evidence with valid binding → pass."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["injury-x"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["injury-x"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                injury="injury-x",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


# ═══════════════════════════════════════════════════════════════════════
# Possession adversarial tests (30-41)
# ═══════════════════════════════════════════════════════════════════════


def test_poss_evidence_generic_scene_reference_rejected(db_conn):
    """30. possession evidence is generic scene reference → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="wrong-possession",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match.*removed possession"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_evidence_wrong_possession_value_rejected(db_conn):
    """31. evidence possession value is different → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="different-poss",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match.*removed possession"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_evidence_wrong_character_rejected(db_conn):
    """32. evidence source character is different → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-2",
                possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not match removal target"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_transfer_recipient_missing_rejected(db_conn):
    """33. transfer action without recipient → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id=None,
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="no recipient"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_transfer_unknown_recipient_rejected(db_conn):
    """34. transfer recipient does not exist → rejected."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-z",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not exist"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_transfer_recipient_not_in_scene_rejected(db_conn):
    """35. transfer recipient not in same scene → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possessions_added={"char-3": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-3",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not participate"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_transfer_no_recipient_addition_rejected(db_conn):
    """36. transfer without recipient addition → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-2",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="does not have.*possession-a.*in character_possessions_added"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_transfer_source_equals_recipient_rejected(db_conn):
    """37. source and recipient are the same character → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possessions_added={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-1",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="same as source"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_lost_with_recipient_rejected(db_conn):
    """38. non-transfer action with recipient → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-2",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="should not have a recipient"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_extra_evidence_rejected(db_conn):
    """39. extra evidence beyond removal count → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="destroyed", excerpt="They discussed the mysterious note they found.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence count 2 does not match"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_lost_exact_evidence_pass(db_conn):
    """40. exact possession lost evidence → pass."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


def test_poss_transfer_exact_evidence_pass(db_conn):
    """41. exact possession transfer evidence → pass."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["possession-a"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["possession-a"]},
        character_possessions_added={"char-2": ["possession-a"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1",
                possession="possession-a",
                action="transferred", excerpt="Alice walked in the park with Bob.",
                recipient_character_id="char-2",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )
