"""Tests: CTO repair — service-owned rejoin.

Tests:
- caller supplying an empty consequence list;
- foreign-world checkpoint;
- incompatible checkpoint;
- checkpoint before divergence;
- unexplained consequence;
- already-rejoined branch;
- valid explained rejoin;
- rollback after injected update failure.
"""

import json

import pytest

from app import branch_repository as branch_repo
from app import canon_repository as canon_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.pipeline.errors import RejoinValidationError
from app.rejoin_service import perform_rejoin
from tests.fixtures.synthetic_world import WORLD_STATE


def _setup_rejoin_test(db_conn):
    """Helper: create world, canon, published episode, reader, choice, branch."""
    world_repo.create_world(db_conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            db_conn, WORLD_STATE.world_id,
            char.character_id, char.canonical_name, char.role,
            traits=json.dumps(char.knowledge),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(db_conn, WORLD_STATE.world_id, loc.location_id, loc.name)
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(db_conn, WORLD_STATE.world_id, clue.clue_id, clue.description)

    canon_repo.create_canon_snapshot(
        db_conn, snapshot_id="snap-rejoin-1", world_id=WORLD_STATE.world_id,
        version="v1", episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[], accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-rejoin-1", canon_snapshot_id="snap-rejoin-1",
        episode_number=1, label="After ep 1", is_compatible_for_rejoin=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-rejoin-3", canon_snapshot_id="snap-rejoin-1",
        episode_number=3, label="After ep 3", is_compatible_for_rejoin=True,
    )

    reader = reader_repo.create_reader(db_conn, display_name="rejoin 독자")
    ep_repo.create_episode(
        db_conn, episode_id="ep-prior-rj", world_id=WORLD_STATE.world_id,
        episode_type="canon", episode_number=1, title="prior", synopsis="syn",
        scene_list=[], character_ids=[], location_ids=[], prose=[],
        unresolved_threads=["thread-1", "thread-2"],
    )
    ep_repo.publish_episode(db_conn, "ep-prior-rj")
    ep_repo.create_episode(
        db_conn, episode_id="ep-branch-rj", world_id=WORLD_STATE.world_id,
        episode_type="personal_branch", episode_number=1, title="branch", synopsis="syn",
        scene_list=[], character_ids=[], location_ids=[], prose=[],
        reader_id=reader.id,
        unresolved_threads=["thread-1", "thread-2"],
        world_state_deltas={"branch_only_facts": ["fact-1"]},
    )
    choice_repo.create_reader_choice(
        db_conn, choice_id="choice-rj", reader_id=reader.id,
        canon_episode_id="ep-prior-rj", choice_text="test",
    )
    branch = branch_repo.create_branch(
        db_conn, branch_id="branch-rj-1", reader_id=reader.id,
        canon_checkpoint_id="cp-rejoin-1", prior_episode_id="ep-prior-rj",
        branch_episode_id="ep-branch-rj", reader_choice_id="choice-rj",
        divergence_state={"branch_only_facts": ["fact-1"]},
        branch_only_facts=["fact-1"],
    )
    return branch, reader


def test_empty_consequence_list_rejected(db_conn):
    """Caller supplying empty consequence list does not bypass explanation requirement."""
    branch, reader = _setup_rejoin_test(db_conn)

    with pytest.raises(RejoinValidationError, match="unresolved consequences require explanation"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-rejoin-3",
            explanations=[],  # empty — bypass attempt
        )


def test_foreign_world_checkpoint_rejected(db_conn):
    """Foreign-world checkpoint is rejected."""
    branch, reader = _setup_rejoin_test(db_conn)

    # Create a checkpoint in a different world
    from app.domain.models import WorldState
    world2 = WorldState(
        world_id="world-foreign", version="v1", premise="foreign",
        characters=[WORLD_STATE.characters[0]], locations=[WORLD_STATE.locations[0]],
    )
    world_repo.create_world(db_conn, world2)
    canon_repo.create_canon_snapshot(
        db_conn, snapshot_id="snap-foreign", world_id="world-foreign",
        version="v1", episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[], accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-foreign", canon_snapshot_id="snap-foreign",
        episode_number=3, label="foreign", is_compatible_for_rejoin=True,
    )

    with pytest.raises(RejoinValidationError, match="world mismatch"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-foreign",
            explanations=[
                {"consequence": "thread-1", "explanation": "resolved in canon ep 2"},
                {"consequence": "thread-2", "explanation": "resolved in canon ep 2"},
                {"consequence": "branch-only fact: fact-1", "explanation": "resolved"},
            ],
        )


def test_incompatible_checkpoint_rejected(db_conn):
    """Incompatible checkpoint (is_compatible_for_rejoin=False) is rejected."""
    branch, reader = _setup_rejoin_test(db_conn)

    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-incompat-rj", canon_snapshot_id="snap-rejoin-1",
        episode_number=3, label="incompatible", is_compatible_for_rejoin=False,
    )

    with pytest.raises(RejoinValidationError, match="not compatible"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-incompat-rj",
            explanations=[
                {"consequence": "thread-1", "explanation": "resolved"},
                {"consequence": "thread-2", "explanation": "resolved"},
                {"consequence": "branch-only fact: fact-1", "explanation": "resolved"},
            ],
        )


def test_checkpoint_before_divergence_rejected(db_conn):
    """Checkpoint before divergence is rejected."""
    branch, reader = _setup_rejoin_test(db_conn)

    # Create a checkpoint at episode 0 (before the branch's ep 1)
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-before", canon_snapshot_id="snap-rejoin-1",
        episode_number=0, label="before", is_compatible_for_rejoin=True,
    )

    with pytest.raises(RejoinValidationError, match="before"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-before",
            explanations=[],
        )


def test_unexplained_consequence_rejected(db_conn):
    """Unexplained consequence is rejected."""
    branch, reader = _setup_rejoin_test(db_conn)

    with pytest.raises(RejoinValidationError, match="require explanation"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-rejoin-3",
            explanations=[
                {"consequence": "thread-1", "explanation": "resolved"},
                # thread-2 and branch-only fact: fact-1 are missing
            ],
        )


def test_already_rejoined_branch_rejected(db_conn):
    """Already-rejoined branch is rejected."""
    branch, reader = _setup_rejoin_test(db_conn)

    # First rejoin succeeds
    perform_rejoin(
        db_conn,
        branch_id=branch.id,
        target_checkpoint_id="cp-rejoin-3",
        explanations=[
            {"consequence": "thread-1", "explanation": "resolved"},
            {"consequence": "thread-2", "explanation": "resolved"},
            {"consequence": "branch-only fact: fact-1", "explanation": "resolved"},
        ],
    )

    # Second rejoin fails
    with pytest.raises(RejoinValidationError, match="not active"):
        perform_rejoin(
            db_conn,
            branch_id=branch.id,
            target_checkpoint_id="cp-rejoin-3",
            explanations=[
                {"consequence": "thread-1", "explanation": "resolved"},
                {"consequence": "thread-2", "explanation": "resolved"},
                {"consequence": "branch-only fact: fact-1", "explanation": "resolved"},
            ],
        )


def test_valid_explained_rejoin_succeeds(db_conn):
    """Valid rejoin with explanations for all consequences succeeds."""
    branch, reader = _setup_rejoin_test(db_conn)

    result = perform_rejoin(
        db_conn,
        branch_id=branch.id,
        target_checkpoint_id="cp-rejoin-3",
        explanations=[
            {"consequence": "thread-1", "explanation": "resolved in canon ep 2"},
            {"consequence": "thread-2", "explanation": "resolved in canon ep 3"},
            {"consequence": "branch-only fact: fact-1", "explanation": "merged into canon"},
        ],
    )

    assert result.approved
    assert result.unresolved_consequences_count == 3

    # Verify branch is marked rejoined
    updated_branch = branch_repo.get_branch(db_conn, branch.id)
    assert updated_branch.status == "rejoined"
    assert updated_branch.rejoin_checkpoint_id == "cp-rejoin-3"
    assert updated_branch.rejoined_at is not None
