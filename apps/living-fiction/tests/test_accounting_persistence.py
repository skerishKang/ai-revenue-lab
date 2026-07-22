"""Tests: generation-run accounting, retry token/latency, pilot evidence privacy, file-backed persistence, no-network."""

import json
import os

import pytest

from app import generation_run_repository as gr_repo
from app import pilot_evidence_repository as pe_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.domain.enums import EpisodeType, ProviderErrorCategory, ValidationStatus
from app.pipeline.service import GenerationRequest, generate_canon_episode
from app.utils import new_id, now_utc_iso
from tests.fixtures.synthetic_world import WORLD_STATE
from tests.fixtures.mock_payloads import CANON_EPISODE_1_PLAN, CANON_EPISODE_1_CONTENT


def _setup_world(db_conn):
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


def test_exact_generation_run_rows(db_conn):
    """Generation-run records accurately store provider, model, prompt version, task, etc."""
    _setup_world(db_conn)

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    # Two generation runs: plan + content
    all_runs = gr_repo.get_all_generation_runs(db_conn)
    assert len(all_runs) == 2

    plan_run = gr_repo.get_generation_run(db_conn, result.plan_run_id)
    assert plan_run is not None
    assert plan_run.task_type == "episode_plan"
    assert plan_run.provider == "mock"
    assert plan_run.advertised_model == "mock-living-fiction-v1"
    assert plan_run.prompt_version == "living-fiction-plan-v1"
    assert plan_run.success is True
    assert plan_run.validation_status == "passed"
    assert plan_run.completed_at is not None
    assert plan_run.latency_seconds is not None and plan_run.latency_seconds >= 0

    content_run = gr_repo.get_generation_run(db_conn, result.content_run_id)
    assert content_run is not None
    assert content_run.task_type == "episode_content"
    assert content_run.prompt_version == "living-fiction-content-v1"
    assert content_run.success is True


def test_retry_token_latency_accounting(db_conn):
    """Retry usage/latency is aggregated correctly."""
    _setup_world(db_conn)

    # Provider that fails once then succeeds for plan
    provider = MockProvider(
        responses=[
            {"task": "episode_plan", "kind": "error",
             "category": ProviderErrorCategory.PROVIDER_ERROR,
             "message": "first attempt fails"},
            {"task": "episode_plan", "kind": "payload", "payload": CANON_EPISODE_1_PLAN,
             "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300}},
        ],
        task_payloads={"episode_content": CANON_EPISODE_1_CONTENT},
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    plan_run = gr_repo.get_generation_run(db_conn, result.plan_run_id)
    assert plan_run is not None
    assert plan_run.retry_count == 1  # one retry after first failure
    assert plan_run.latency_seconds is not None and plan_run.latency_seconds >= 0
    # Token usage from successful attempt
    assert plan_run.input_tokens == 100
    assert plan_run.output_tokens == 200


def test_no_double_recording_same_attempt(db_conn):
    """Same provider attempt is not recorded as both success and failure."""
    _setup_world(db_conn)

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    all_runs = gr_repo.get_all_generation_runs(db_conn)
    # Exactly 2 runs, one per stage (plan + content)
    assert len(all_runs) == 2
    # Each run has exactly one final status
    for run in all_runs:
        assert run.success is True
        assert run.validation_status == "passed"


def test_pilot_evidence_privacy(db_conn):
    """Pilot evidence records are privacy-safe."""
    _setup_world(db_conn)

    evidence = pe_repo.create_pilot_evidence(
        db_conn,
        evidence_id=new_id(),
        evidence_category="episode_delivery",
        evidence_data={
            "canon_episode_number": 1,
            "delivery_method": "file-backed",
            "cost_class": "free",
        },
    )
    assert evidence.privacy_safe is True
    # No payer identity, account/card data, credentials in evidence
    data = json.loads(evidence.evidence_data_json)
    assert "payer" not in data
    assert "card" not in data
    assert "credential" not in data


def test_pilot_evidence_categories(db_conn):
    """All evidence categories can be stored."""
    _setup_world(db_conn)

    categories = [
        "invitation", "consent", "episode_delivery", "explicit_choice",
        "engagement", "correction_time", "ai_infra_cost", "revenue_hypothesis",
    ]
    for cat in categories:
        pe_repo.create_pilot_evidence(
            db_conn,
            evidence_id=new_id(),
            evidence_category=cat,
            evidence_data={"category": cat},
        )

    all_evidence = pe_repo.get_all_pilot_evidence(db_conn)
    assert len(all_evidence) == len(categories)
    stored_categories = {e.evidence_category for e in all_evidence}
    assert stored_categories == set(categories)


def test_file_backed_close_reopen(temp_db_path):
    """File-backed close/reopen preserves canon, branch, and accounting state."""
    from app.db import apply_migrations, get_connection
    from app import episode_repository as ep_repo

    # Session 1: create data
    conn1 = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    apply_migrations(conn1, migrations_dir)
    _setup_world(conn1)

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(conn1, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    runs_before = gr_repo.get_all_generation_runs(conn1)
    episodes_before = ep_repo.get_episodes_by_world(conn1, WORLD_STATE.world_id)

    conn1.close()

    # Session 2: reopen and verify persistence
    conn2 = get_connection(temp_db_path)
    # No re-migration needed — already applied
    apply_migrations(conn2, migrations_dir)  # idempotent

    runs_after = gr_repo.get_all_generation_runs(conn2)
    episodes_after = ep_repo.get_episodes_by_world(conn2, WORLD_STATE.world_id)

    assert len(runs_after) == len(runs_before)
    assert len(episodes_after) == len(episodes_before)
    assert episodes_after[0].id == episodes_before[0].id
    assert episodes_after[0].review_state == "pending_review"

    conn2.close()


def test_no_network(db_conn):
    """MockProvider never opens a socket or performs I/O."""
    _setup_world(db_conn)

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )

    # The provider has no network attributes or methods
    assert not hasattr(provider, "_socket")
    assert not hasattr(provider, "_connection")
    assert not hasattr(provider, "http_client")

    # Generate successfully without any network
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded


def test_generation_accounting_after_retry(db_conn):
    """Generation-run records store retry count and aggregated latency."""
    _setup_world(db_conn)

    # Provider that fails twice then succeeds for plan
    provider = MockProvider(
        responses=[
            {"task": "episode_plan", "kind": "error"},
            {"task": "episode_plan", "kind": "error"},
            {"task": "episode_plan", "kind": "payload", "payload": CANON_EPISODE_1_PLAN},
        ],
        task_payloads={"episode_content": CANON_EPISODE_1_CONTENT},
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    plan_run = gr_repo.get_generation_run(db_conn, result.plan_run_id)
    assert plan_run is not None
    assert plan_run.retry_count == 2
    assert plan_run.success is True
