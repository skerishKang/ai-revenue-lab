"""Edge-case correctness tests for structured continuity evidence.

Tests cover:
- Legacy relationship fail-closed in world_repository
- Injury/possession evidence reuse rejection (scene_id, excerpt)
- Orphan evidence key enforcement
- Relationship referential integrity in WorldState model
- Relationship change parsing strict 3-part
- PossessionRemovalEvidence.recipient_character_id PatternStr
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
# Fix 1: Legacy relationship fail-closed
# ═══════════════════════════════════════════════════════════════════════


def _make_db_with_rels(relationships_json: str):
    """Create a temp DB with a world and character with given relationships JSON."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS worlds (
            id TEXT PRIMARY KEY, version TEXT, premise TEXT, genre TEXT,
            world_rules TEXT, canonical_timeline TEXT,
            unresolved_global_questions TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY, world_id TEXT, canonical_name TEXT, aliases TEXT,
            role TEXT, traits TEXT, knowledge_state TEXT, relationships TEXT,
            location_id TEXT, status TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY, world_id TEXT, name TEXT, physical_properties TEXT,
            access_rules TEXT, known_history TEXT, connected_locations TEXT,
            current_state TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS clues (
            id TEXT PRIMARY KEY, world_id TEXT, description TEXT,
            introduced_in_episode TEXT, resolved INTEGER, created_at TEXT
        );
    """)
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO worlds VALUES (?, '1.0', 'test', 'urban_mystery', '[]', '[]', '[]', ?)",
        ("world-1", now),
    )
    conn.execute(
        "INSERT INTO characters VALUES (?, 'world-1', 'Alice', NULL, 'hero', "
        "'[]', '[]', ?, 'loc-1', 'active', ?)",
        ("char-1", relationships_json, now),
    )
    conn.execute(
        "INSERT INTO characters VALUES (?, 'world-1', 'Bob', NULL, 'friend', "
        "'[]', '[]', '[]', 'loc-1', 'active', ?)",
        ("char-2", now),
    )
    conn.execute(
        "INSERT INTO locations VALUES (?, 'world-1', 'Park', NULL, NULL, NULL, '[]', '', ?)",
        ("loc-1", now),
    )
    conn.commit()
    conn.close()
    return path


def _safe_unlink(path):
    try:
        os.unlink(path)
    except (PermissionError, OSError):
        pass


def test_legacy_valid_structured_json_roundtrip():
    """Valid structured DB JSON round-trip."""
    rels = json.dumps([{"other_character_id": "char-2", "label": "friend"}])
    path = _make_db_with_rels(rels)
    try:
        from app.world_repository import load_world_state
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        world = load_world_state(conn, "world-1")
        conn.close()
        assert world is not None
        assert len(world.characters[0].relationships) == 1
        assert world.characters[0].relationships[0].other_character_id == "char-2"
        assert world.characters[0].relationships[0].label == "friend"
    finally:
        _safe_unlink(path)


def test_legacy_valid_colon_format_conversion():
    """Valid legacy 'char-2:friend' conversion."""
    rels = json.dumps(["char-2:friend"])
    path = _make_db_with_rels(rels)
    try:
        from app.world_repository import load_world_state
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        world = load_world_state(conn, "world-1")
        conn.close()
        assert world is not None
        assert len(world.characters[0].relationships) == 1
        assert world.characters[0].relationships[0].other_character_id == "char-2"
        assert world.characters[0].relationships[0].label == "friend"
    finally:
        _safe_unlink(path)


def test_legacy_bare_label_rejected():
    """Bare legacy 'friend' (no colon) → WorldValidationError."""
    from app.world_repository import WorldValidationError, load_world_state
    rels = json.dumps(["friend"])
    path = _make_db_with_rels(rels)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        with pytest.raises(WorldValidationError, match="bare legacy"):
            load_world_state(conn, "world-1")
        conn.close()
    finally:
        _safe_unlink(path)


def test_legacy_freeform_string_rejected():
    """Free-form legacy 'Alice's manager' (no colon) → WorldValidationError."""
    from app.world_repository import WorldValidationError, load_world_state
    rels = json.dumps(["Alice's manager"])
    path = _make_db_with_rels(rels)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        with pytest.raises(WorldValidationError, match="bare legacy"):
            load_world_state(conn, "world-1")
        conn.close()
    finally:
        _safe_unlink(path)


def test_legacy_malformed_json_rejected():
    """Malformed relationship JSON → WorldValidationError."""
    from app.world_repository import WorldValidationError, load_world_state
    path = _make_db_with_rels("{invalid json")
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        with pytest.raises(WorldValidationError, match="malformed relationship JSON"):
            load_world_state(conn, "world-1")
        conn.close()
    finally:
        _safe_unlink(path)


def test_legacy_invalid_dict_rejected():
    """Invalid dict (missing required fields) → WorldValidationError."""
    from app.world_repository import WorldValidationError, load_world_state
    rels = json.dumps([{"other_character_id": "char-2"}])
    path = _make_db_with_rels(rels)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        with pytest.raises(WorldValidationError, match="invalid relationship"):
            load_world_state(conn, "world-1")
        conn.close()
    finally:
        _safe_unlink(path)


def test_legacy_empty_string_skipped():
    """Empty string in relationship list → skipped (allowed)."""
    rels = json.dumps(["", "  "])
    path = _make_db_with_rels(rels)
    try:
        from app.world_repository import load_world_state
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        world = load_world_state(conn, "world-1")
        conn.close()
        assert world is not None
        assert len(world.characters[0].relationships) == 0
    finally:
        _safe_unlink(path)


def test_snapshot_malformed_relationship_rejected():
    """Malformed relationship in canon snapshot → WorldValidationError."""
    from app.world_repository import WorldValidationError, load_world_state
    import app.world_repository as world_repo
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    from app.db import apply_migrations
    apply_migrations(conn, os.path.join(os.path.dirname(__file__), "..", "migrations"))
    from app.domain.models import WorldState, CharacterRef, LocationRef
    w = WorldState(
        world_id="w1", version="v1", premise="test",
        characters=[CharacterRef(character_id="c1", canonical_name="A", role="r", location_id="l1")],
        locations=[LocationRef(location_id="l1", name="L")],
    )
    world_repo.create_world(conn, w)
    world_repo.create_character(conn, "w1", "c1", "A", "r", location_id="l1",
                               relationships=json.dumps([{"other_character_id": "c1", "label": "self"}]))
    # Create a snapshot with malformed relationship
    conn.execute(
        "INSERT INTO canon_snapshots "
        "(id, world_id, version, episode_number, accepted, world_state_json, "
        "character_states_json, location_states_json, clue_states_json, "
        "unresolved_threads_json, created_at) "
        "VALUES (?, 'w1', 'v1', 1, 1, '{}', ?, '{}', '{}', '[]', '2026-01-01')",
        ("snap-bad", json.dumps({"c1": {"relationships": ["bare-label"]}})),
    )
    conn.commit()
    try:
        with pytest.raises(WorldValidationError, match="bare legacy"):
            load_world_state(conn, "w1", canon_snapshot_id="snap-bad")
    finally:
        conn.close()
        _safe_unlink(path)


# ═══════════════════════════════════════════════════════════════════════
# Fix 2: Injury/Possession evidence reuse rejection
# ═══════════════════════════════════════════════════════════════════════


def test_injury_same_scene_excerpt_different_items_rejected(db_conn):
    """injury_a and injury_b with same scene/excerpt → reject."""
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
                scene_id="scene-1", character_id="char-1", injury="injury_a",
                action="healed", excerpt=shared_excerpt,
            ),
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1", injury="injury_b",
                action="recovered", excerpt=shared_excerpt,
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="reuses scene"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_possession_same_scene_excerpt_different_items_rejected(db_conn):
    """possession_a and possession_b with same scene/excerpt → reject."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_possessions_added": {"char-1": ["poss_a", "poss_b"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    shared_excerpt = "Alice walked in the park with Bob."
    delta = ContinuityDelta(
        character_possessions_removed={"char-1": ["poss_a", "poss_b"]},
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1", possession="poss_a",
                action="lost", excerpt=shared_excerpt,
            ),
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1", possession="poss_b",
                action="destroyed", excerpt=shared_excerpt,
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="reuses scene"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_injury_different_exact_excerpt_pass(db_conn):
    """Different excerpts for different injuries → pass."""
    db_conn.execute(
        "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'prior-1'",
        (json.dumps({"character_injuries_added": {"char-1": ["injury_a", "injury_b"]}}),),
    )
    db_conn.commit()
    world = _make_world()
    delta = ContinuityDelta(
        character_injuries_removed={"char-1": ["injury_a", "injury_b"]},
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1", injury="injury_a",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1", injury="injury_b",
                action="recovered", excerpt="They discussed the mysterious note they found.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


# ═══════════════════════════════════════════════════════════════════════
# Fix 3: Orphan evidence key enforcement
# ═══════════════════════════════════════════════════════════════════════


def test_rel_evidence_only_no_change_known_char_rejected(db_conn):
    """Known character with relationship evidence but no change → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1", other_character_id="char-2",
                prior_label="none", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without changes"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_evidence_only_no_change_unknown_char_rejected(db_conn):
    """Unknown character with relationship evidence but no change → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_evidence={"char-z": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-z", other_character_id="char-2",
                prior_label="none", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without changes"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_only_no_removal_known_char_rejected(db_conn):
    """Known character with injury evidence but no removal → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_injury_removal_evidence={"char-1": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-1", injury="injury-x",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without removals"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_inj_evidence_only_no_removal_unknown_char_rejected(db_conn):
    """Unknown character with injury evidence but no removal → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_injury_removal_evidence={"char-z": [
            InjuryRemovalEvidence(
                scene_id="scene-1", character_id="char-z", injury="injury-x",
                action="healed", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without removals"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_evidence_only_no_removal_known_char_rejected(db_conn):
    """Known character with possession evidence but no removal → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_possession_removal_evidence={"char-1": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-1", possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without removals"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_poss_evidence_only_no_removal_unknown_char_rejected(db_conn):
    """Unknown character with possession evidence but no removal → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_possession_removal_evidence={"char-z": [
            PossessionRemovalEvidence(
                scene_id="scene-1", character_id="char-z", possession="possession-a",
                action="lost", excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without removals"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_mismatched_keys_rejected(db_conn):
    """Mutation key != evidence key → reject."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-3": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-3", other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="evidence for characters without changes"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_exact_matching_keys_pass(db_conn):
    """Exact matching key sets → pass."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1", other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


# ═══════════════════════════════════════════════════════════════════════
# Fix 4: Relationship referential integrity in WorldState model
# ═══════════════════════════════════════════════════════════════════════


def test_rel_unknown_target_rejected():
    """Unknown relationship target → rejected."""
    with pytest.raises(ValidationError, match="does not exist"):
        WorldState(
            world_id="w", version="v", premise="p",
            characters=[
                CharacterRef(character_id="c1", canonical_name="A", role="r", location_id="l1",
                             relationships=[RelationshipRef(other_character_id="c99", label="friend")]),
            ],
            locations=[LocationRef(location_id="l1", name="L")],
        )


def test_rel_self_relationship_rejected():
    """Self relationship edge → rejected."""
    with pytest.raises(ValidationError, match="self relationship"):
        WorldState(
            world_id="w", version="v", premise="p",
            characters=[
                CharacterRef(character_id="c1", canonical_name="A", role="r", location_id="l1",
                             relationships=[RelationshipRef(other_character_id="c1", label="friend")]),
            ],
            locations=[LocationRef(location_id="l1", name="L")],
        )


def test_rel_valid_target_pass():
    """Valid target → pass."""
    world = WorldState(
        world_id="w", version="v", premise="p",
        characters=[
            CharacterRef(character_id="c1", canonical_name="A", role="r", location_id="l1",
                         relationships=[RelationshipRef(other_character_id="c2", label="friend")]),
            CharacterRef(character_id="c2", canonical_name="B", role="r", location_id="l1"),
        ],
        locations=[LocationRef(location_id="l1", name="L")],
    )
    assert len(world.characters[0].relationships) == 1


def test_rel_forward_reference_pass():
    """Target character listed later in array → pass (forward reference)."""
    world = WorldState(
        world_id="w", version="v", premise="p",
        characters=[
            CharacterRef(character_id="c1", canonical_name="A", role="r", location_id="l1",
                         relationships=[RelationshipRef(other_character_id="c2", label="friend")]),
            CharacterRef(character_id="c2", canonical_name="B", role="r", location_id="l1"),
        ],
        locations=[LocationRef(location_id="l1", name="L")],
    )
    assert world.characters[0].relationships[0].other_character_id == "c2"


# ═══════════════════════════════════════════════════════════════════════
# Fix 5: Relationship change parsing strict 3-part
# ═══════════════════════════════════════════════════════════════════════


def test_rel_2part_change_rejected(db_conn):
    """2-part change → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:friend"]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="must be 'other_char:prior_label:new_label'"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_4part_change_rejected(db_conn):
    """4-part change → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:none:friend:extra"]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="must be 'other_char:prior_label:new_label'"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_empty_prior_label_rejected(db_conn):
    """Empty prior label → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2::friend"]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="empty prior or new label"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_empty_new_label_rejected(db_conn):
    """Empty new label → reject."""
    world = _make_world()
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:none:"]},
    )
    content = _make_content(world_state_delta=delta)
    with pytest.raises(ContinuityError, match="empty prior or new label"):
        validate_production_continuity(
            content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
        )


def test_rel_exact_3part_change_pass(db_conn):
    """Exact 3-part change → pass."""
    world = _make_world()
    world.characters[0].relationships = [
        RelationshipRef(other_character_id="char-2", label="stranger"),
    ]
    delta = ContinuityDelta(
        character_relationship_changes={"char-1": ["char-2:stranger:friend"]},
        character_relationship_evidence={"char-1": [
            RelationshipEvidence(
                scene_id="scene-1", character_id="char-1", other_character_id="char-2",
                prior_label="stranger", new_label="friend",
                excerpt="Alice walked in the park with Bob.",
            ),
        ]},
    )
    content = _make_content(world_state_delta=delta)
    validate_production_continuity(
        content, world=world, conn=db_conn, prior_episode_id="prior-1", is_branch=True,
    )


# ═══════════════════════════════════════════════════════════════════════
# Fix 6: PossessionRemovalEvidence.recipient_character_id PatternStr
# ═══════════════════════════════════════════════════════════════════════


def test_possession_recipient_must_be_pattern():
    """recipient_character_id must match PatternStr pattern."""
    with pytest.raises(ValidationError):
        PossessionRemovalEvidence(
            scene_id="scene-1", character_id="char-1", possession="key",
            action="transferred", excerpt="test",
            recipient_character_id="has spaces!",
        )


def test_possession_recipient_valid_pattern():
    """Valid PatternStr recipient → accepted."""
    ev = PossessionRemovalEvidence(
        scene_id="scene-1", character_id="char-1", possession="key",
        action="transferred", excerpt="test",
        recipient_character_id="char-2",
    )
    assert ev.recipient_character_id == "char-2"


def test_possession_recipient_none_allowed():
    """None recipient → accepted."""
    ev = PossessionRemovalEvidence(
        scene_id="scene-1", character_id="char-1", possession="key",
        action="lost", excerpt="test",
    )
    assert ev.recipient_character_id is None
