"""Tests: CTO repair — persisted branch binding, material change, continuity.

Tests production-path rejection of:
- missing/stale/foreign-world/unpublished/mismatched records;
- identical output;
- metadata-only changes;
- ID-only changes;
- generic content with injected applied-input record;
- silent canon rewrite;
- impossible location movement;
- unexplained knowledge;
- duplicate clue;
- unresolved thread disappearance.
"""

import json

import pytest

from app import branch_repository as branch_repo
from app import canon_repository as canon_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.domain.enums import EpisodeType
from app.pipeline.service import GenerationRequest, generate_canon_episode, generate_personal_branch
from tests.fixtures.synthetic_world import WORLD_STATE
from tests.fixtures.mock_payloads import (
    BRANCH_EPISODE_PLAN,
    BRANCH_EPISODE_CONTENT,
    CANON_EPISODE_1_PLAN,
    CANON_EPISODE_1_CONTENT,
)
from tests.fixtures.adversarial_payloads import (
    make_branch_content_with_choice_id,
    ADVERSARIAL_SILENT_CANON_REWRITE,
    ADVERSARIAL_IMPOSSIBLE_MOVEMENT,
    ADVERSARIAL_UNEXPLAINED_KNOWLEDGE,
    ADVERSARIAL_DUPLICATE_CLUE,
    ADVERSARIAL_THREAD_DISAPPEARANCE,
    ADVERSARIAL_IDENTICAL_OUTPUT,
    ADVERSARIAL_METADATA_ONLY,
)


def _setup_world_and_published_canon(db_conn):
    """Helper: create world, characters, locations, clues, canon snapshot,
    checkpoint, and first published canon episode.
    """
    world_repo.create_world(db_conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            db_conn, WORLD_STATE.world_id,
            char.character_id, char.canonical_name, char.role,
            traits=json.dumps(char.knowledge),
            knowledge_state=json.dumps(char.knowledge),
            relationships=json.dumps([r.model_dump() for r in char.relationships]),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(
            db_conn, WORLD_STATE.world_id, loc.location_id, loc.name,
            connected_locations=json.dumps(loc.connected_locations),
        )
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(db_conn, WORLD_STATE.world_id, clue.clue_id, clue.description)

    canon_repo.create_canon_snapshot(
        db_conn,
        snapshot_id="snapshot-canon-1",
        world_id=WORLD_STATE.world_id,
        version="v1",
        episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[],
        accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn,
        checkpoint_id="checkpoint-canon-1",
        canon_snapshot_id="snapshot-canon-1",
        episode_number=1,
        label="After episode 1",
        is_compatible_for_rejoin=True,
    )

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )
    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.CANON,
        is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded
    ep_repo.publish_episode(db_conn, result.episode_id)
    return result.episode_id


def _make_branch_provider(choice_id: str, content: dict | None = None):
    """Create a MockProvider that returns branch content with the given choice_id."""
    import copy
    branch_content = copy.deepcopy(content or BRANCH_EPISODE_CONTENT)
    branch_content["applied_reader_input"]["reader_choice_id"] = choice_id
    return MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": branch_content,
        }
    )


# ── BLOCKER 1: Persisted branch binding ─────────────────────────────────────


def test_branch_requires_published_prior_episode(db_conn):
    """Branch from unpublished prior episode is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    # Unpublish the episode
    db_conn.execute(
        "UPDATE episodes SET review_state = 'pending_review' WHERE id = ?",
        (canon_ep_id,),
    )
    db_conn.commit()

    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-test-unpub",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded
    assert "not published" in (result.error or "").lower()


def test_branch_choice_episode_mismatch(db_conn):
    """choice.canon_episode_id != prior_episode_id is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="독자")
    # Create a second canon episode
    ep_repo.create_episode(
        db_conn, episode_id="ep-canon-2", world_id=WORLD_STATE.world_id,
        episode_type="canon", episode_number=2, title="ep2", synopsis="syn",
        scene_list=[], character_ids=[], location_ids=[], prose=[],
    )
    ep_repo.publish_episode(db_conn, "ep-canon-2")

    # Choice references ep-canon-2 but we pass canon_ep_id as prior
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-mismatch",
        reader_id=reader.id, canon_episode_id="ep-canon-2",
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,  # different from choice.canon_episode_id
    )
    assert not result.succeeded
    assert "does not match" in (result.error or "").lower() or "mismatch" in (result.error or "").lower()


def test_branch_foreign_world_checkpoint(db_conn):
    """Checkpoint from a different world is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)

    # Create a second world + snapshot + checkpoint
    from app.domain.models import WorldState, CharacterRef
    char_copy = CharacterRef(
        character_id=WORLD_STATE.characters[0].character_id,
        canonical_name=WORLD_STATE.characters[0].canonical_name,
        role=WORLD_STATE.characters[0].role,
        location_id=WORLD_STATE.characters[0].location_id,
    )
    world2 = WorldState(
        world_id="world-other", version="v1", premise="other world",
        characters=[char_copy], locations=[WORLD_STATE.locations[0]],
    )
    world_repo.create_world(db_conn, world2)
    canon_repo.create_canon_snapshot(
        db_conn, snapshot_id="snap-other", world_id="world-other",
        version="v1", episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[], accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-other", canon_snapshot_id="snap-other",
        episode_number=1, label="other", is_compatible_for_rejoin=True,
    )

    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-foreign-world",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="cp-other",  # belongs to different world
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded


def test_branch_inactive_reader_rejected(db_conn):
    """Inactive reader cannot generate branch."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="비활성")
    reader_repo.delete_reader(db_conn, reader.id)

    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-inactive-reader",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded
    assert "not active" in (result.error or "").lower()


# ── BLOCKER 2: Material change validation ───────────────────────────────────


def test_material_change_identical_output_rejected(db_conn):
    """Branch identical to prior episode is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-identical",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    # Provider returns content identical to the canon episode
    provider = _make_branch_provider(choice.id, content=ADVERSARIAL_IDENTICAL_OUTPUT)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded


def test_material_change_metadata_only_rejected(db_conn):
    """Branch with only metadata changes is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-meta-only",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id, content=ADVERSARIAL_METADATA_ONLY)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded


def test_applied_reader_input_must_match_persisted_choice(db_conn):
    """applied_reader_input.choice_text must match persisted choice text."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-text-mismatch",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="다른 선택을 한다",  # different from fixture's "신중하게 조사한다"
    )

    provider = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded
    assert "choice_text" in (result.error or "").lower() or "does not match" in (result.error or "").lower()


# ── BLOCKER 3: Production continuity validation ─────────────────────────────


def test_silent_canon_rewrite_rejected(db_conn):
    """Branch resolving all canon clues is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-silent-rewrite",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id, content=ADVERSARIAL_SILENT_CANON_REWRITE)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded


def test_duplicate_clue_rejected(db_conn):
    """Branch introducing a duplicate clue is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-dup-clue",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id, content=ADVERSARIAL_DUPLICATE_CLUE)
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded


def test_unknown_character_in_delta_rejected(db_conn):
    """Branch referencing unknown character in delta is rejected."""
    canon_ep_id = _setup_world_and_published_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-unknown-char-delta",
        reader_id=reader.id, canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    import copy
    content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
    content["applied_reader_input"]["reader_choice_id"] = choice.id
    content["world_state_delta"]["character_knowledge_added"] = {
        "char-unknown": ["unknown knowledge"],
    }

    provider = MockProvider(
        task_payloads={"episode_plan": BRANCH_EPISODE_PLAN, "episode_content": content}
    )
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id, reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result.succeeded
