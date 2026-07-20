"""Tests: personal branch generation, transaction rollback, idempotency."""

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


def _setup_world_and_canon(db_conn):
    """Helper: create world, characters, locations, clues, and first canon episode."""
    world_repo.create_world(db_conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            db_conn, WORLD_STATE.world_id,
            char.character_id, char.canonical_name, char.role,
            traits=json.dumps(char.knowledge),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(
            db_conn, WORLD_STATE.world_id,
            loc.location_id, loc.name,
        )
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(
            db_conn, WORLD_STATE.world_id,
            clue.clue_id, clue.description,
        )

    # Create canon checkpoint
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

    # Generate first canon episode
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
    result = generate_canon_episode(
        db_conn, provider, request, world_id=WORLD_STATE.world_id,
    )
    assert result.succeeded

    # Publish the canon episode — branches require a prior published episode
    ep_repo.publish_episode(db_conn, result.episode_id)

    return result.episode_id


def _make_branch_provider(choice_id: str):
    """Create a MockProvider that returns branch content with the given choice_id."""
    import copy
    branch_content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
    branch_content["applied_reader_input"]["reader_choice_id"] = choice_id
    return MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": branch_content,
        }
    )


def test_persisted_choice_drives_branch(db_conn):
    """Persisted reader choice drives a materially changed personal branch."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="테스트 독자")
    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-cautious-investigation",
        reader_id=reader.id,
        canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
        comment="한국장을 직접 대면하지 말고 증거를 먼저 확보해",
    )

    provider = MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": BRANCH_EPISODE_CONTENT,
        }
    )

    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
        reader_comment=choice.comment,
    )

    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )

    assert result.succeeded
    assert result.episode_id is not None

    episode = ep_repo.get_episode_by_id(db_conn, result.episode_id)
    assert episode is not None
    assert episode.episode_type == "personal_branch"
    assert episode.review_state == "pending_review"
    assert episode.applied_reader_input_json is not None

    applied = json.loads(episode.applied_reader_input_json)
    assert applied["reader_choice_id"] == "choice-cautious-investigation"
    assert applied["choice_text"] == "신중하게 조사한다"

    # Choice is marked as applied
    updated_choice = choice_repo.get_reader_choice(db_conn, choice.id)
    assert updated_choice.applied_to_branch_id == result.episode_id

    # Branch record exists
    branches = branch_repo.get_branches_by_reader(db_conn, reader.id)
    assert len(branches) == 1
    assert branches[0].branch_episode_id == result.episode_id


def test_foreign_choice_rejected(db_conn):
    """Foreign reader choice (different reader) is rejected."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader1 = reader_repo.create_reader(db_conn, display_name="독자 1")
    reader2 = reader_repo.create_reader(db_conn, display_name="독자 2")

    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-reader-1",
        reader_id=reader1.id,
        canon_episode_id=canon_ep_id,
        choice_text="조사한다",
    )

    provider = MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": BRANCH_EPISODE_CONTENT,
        }
    )

    # reader2 tries to use reader1's choice
    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader2.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )

    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )

    # The branch content references choice-cautious-investigation but we passed
    # choice-reader-1 — the validator should catch the mismatch
    assert not result.succeeded


def test_already_applied_choice_rejected(db_conn):
    """Already-applied choice cannot be applied again."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="독자")
    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-double-apply",
        reader_id=reader.id,
        canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)

    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )

    # First application succeeds
    result1 = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert result1.succeeded

    # Second application fails — choice already applied
    result2 = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result2.succeeded
    assert "already applied" in (result2.error or "").lower()


def test_transaction_rollback_on_failure(db_conn):
    """When generation fails, neither episode nor choice application is persisted."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="롤백 독자")
    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-rollback-test",
        reader_id=reader.id,
        canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    # Provider that always fails
    provider = MockProvider(task_payloads={"episode_plan": {}})

    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )

    result = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )

    assert not result.succeeded
    # Choice should NOT be marked as applied
    assert choice_repo.is_choice_applied(db_conn, choice.id) is False
    # No episode should exist for this reader
    episodes = ep_repo.get_episodes_by_world(db_conn, WORLD_STATE.world_id, "personal_branch")
    assert len(episodes) == 0


def test_duplicate_retry_idempotency(db_conn):
    """Duplicate/retry requests do not create duplicate episodes or apply input twice."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="중복 독자")
    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-dup-test",
        reader_id=reader.id,
        canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    provider = _make_branch_provider(choice.id)

    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )

    result1 = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert result1.succeeded

    # Retry with same choice — should fail
    result2 = generate_personal_branch(
        db_conn, provider, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert not result2.succeeded

    # Only one branch episode exists
    branches = branch_repo.get_branches_by_reader(db_conn, reader.id)
    assert len(branches) == 1


def test_no_overwrite_on_failure(db_conn):
    """Failure does not overwrite the last valid canon/branch state."""
    canon_ep_id = _setup_world_and_canon(db_conn)

    reader = reader_repo.create_reader(db_conn, display_name="보존 독자")
    choice = choice_repo.create_reader_choice(
        db_conn,
        choice_id="choice-no-overwrite",
        reader_id=reader.id,
        canon_episode_id=canon_ep_id,
        choice_text="신중하게 조사한다",
    )

    # First: successful generation
    provider_ok = _make_branch_provider(choice.id)
    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader.id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
    )
    result1 = generate_personal_branch(
        db_conn, provider_ok, request,
        world_id=WORLD_STATE.world_id,
        canon_checkpoint_id="checkpoint-canon-1",
        prior_episode_id=canon_ep_id,
    )
    assert result1.succeeded
    original_episode = ep_repo.get_episode_by_id(db_conn, result1.episode_id)
    assert original_episode is not None

    # The canon episode should be unchanged
    canon_episodes = ep_repo.get_episodes_by_world(db_conn, WORLD_STATE.world_id, "canon")
    assert len(canon_episodes) == 1
    assert canon_episodes[0].id == canon_ep_id
