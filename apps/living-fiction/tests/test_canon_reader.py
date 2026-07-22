"""Tests: reader, world, canon snapshot immutability, first canon generation."""

import json

import pytest

from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app import canon_repository as canon_repo
from app import episode_repository as ep_repo
from app.ai.mock import MockProvider
from app.domain.enums import EpisodeType
from app.pipeline.service import GenerationRequest, generate_canon_episode
from tests.fixtures.synthetic_world import WORLD_STATE
from tests.fixtures.mock_payloads import CANON_EPISODE_1_PLAN, CANON_EPISODE_1_CONTENT


def test_create_reader(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="테스트 독자")
    assert reader.status == "active"
    assert reader.deleted_at is None
    assert reader_repo.is_reader_active(db_conn, reader.id) is True


def test_inactive_reader_cannot_create_choice(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="비활성 독자")
    reader_repo.delete_reader(db_conn, reader.id)
    assert reader_repo.is_reader_active(db_conn, reader.id) is False


def test_deleted_reader_inactive(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="삭제될 독자")
    assert reader_repo.delete_reader(db_conn, reader.id) is True
    assert reader_repo.is_reader_active(db_conn, reader.id) is False


def test_create_world_and_characters(db_conn):
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

    assert world_repo.get_world(db_conn, WORLD_STATE.world_id) is not None
    assert world_repo.get_character(db_conn, "char-mina-seo") is not None
    assert world_repo.get_location(db_conn, "loc-municipal-archive") is not None
    assert world_repo.get_clue(db_conn, "clue-ledger") is not None


def test_canon_snapshot_immutable(db_conn):
    """Accepted canon snapshots are immutable."""
    world_repo.create_world(db_conn, WORLD_STATE)
    snapshot = canon_repo.create_canon_snapshot(
        db_conn,
        snapshot_id="snapshot-1",
        world_id=WORLD_STATE.world_id,
        version="v1",
        episode_number=1,
        world_state={"premise": "test"},
        character_states={},
        location_states={},
        clue_states={},
        unresolved_threads=["thread-1"],
        accepted=True,
    )
    assert snapshot.accepted is True

    # Attempt to mutate should raise
    with pytest.raises(canon_repo.CanonValidationError, match="immutable"):
        canon_repo.try_mutate_canon_snapshot(db_conn, "snapshot-1")


def test_unaccepted_snapshot_mutable(db_conn):
    """Unaccepted snapshots can be modified."""
    world_repo.create_world(db_conn, WORLD_STATE)
    canon_repo.create_canon_snapshot(
        db_conn,
        snapshot_id="snapshot-2",
        world_id=WORLD_STATE.world_id,
        version="v1",
        episode_number=1,
        world_state={},
        character_states={},
        location_states={},
        clue_states={},
        unresolved_threads=[],
        accepted=False,
    )
    # Should succeed without raising
    canon_repo.try_mutate_canon_snapshot(db_conn, "snapshot-2")


def test_canon_snapshot_versioned(db_conn):
    """Canon snapshots are versioned."""
    world_repo.create_world(db_conn, WORLD_STATE)
    canon_repo.create_canon_snapshot(
        db_conn,
        snapshot_id="snapshot-v1",
        world_id=WORLD_STATE.world_id,
        version="v1",
        episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[],
        accepted=True,
    )
    canon_repo.create_canon_snapshot(
        db_conn,
        snapshot_id="snapshot-v2",
        world_id=WORLD_STATE.world_id,
        version="v2",
        episode_number=2,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[],
        accepted=True,
    )
    latest = canon_repo.get_latest_canon_snapshot(db_conn, WORLD_STATE.world_id)
    assert latest is not None
    assert latest.version == "v2"
    assert latest.episode_number == 2


def test_first_canon_generation(db_conn):
    """First canon episode generates to pending_review with no applied reader input."""
    world_repo.create_world(db_conn, WORLD_STATE)

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
    assert result.succeeded is True
    assert result.episode_id is not None

    episode = ep_repo.get_episode_by_id(db_conn, result.episode_id)
    assert episode is not None
    assert episode.review_state == "pending_review"
    assert episode.episode_type == "canon"
    assert episode.episode_number == 1
    assert episode.applied_reader_input_json is None  # no applied reader input


def test_first_canon_has_no_applied_input(db_conn):
    """First canon episode must not have applied reader input in the content model."""
    from app.domain.models import EpisodeContent
    content = EpisodeContent.model_validate(CANON_EPISODE_1_CONTENT)
    assert content.applied_reader_input is None
