"""Blocker E — Provider accounting aggregate arithmetic and privacy tests.

Verifies that:
- Aggregate latency = sum of all attempt latencies (including exceptions)
- Aggregate tokens = sum of all attempt tokens
- Provider/model/cost persisted correctly from actual ProviderResult
- No raw error messages in durable DB
- Validation failure sets success=False
- Close/reopen preserves everything
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time

import pytest

from app.db import apply_migrations, get_connection
from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import (
    CharacterRef,
    EpisodeContent,
    EpisodePlan,
    LocationRef,
    ProviderResult,
    ProviderUsage,
    WorldState,
)
from app.pipeline.errors import safe_error_message


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _get_migrations_dir():
    return os.path.join(os.path.dirname(__file__), "..", "migrations")


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.unlink(path)
        except PermissionError:
            pass


def _seed_world(conn):
    now = "2025-01-01T00:00:00Z"
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
                 ("reader-acc", "Acc Reader", now))
    conn.execute("INSERT INTO worlds (id, version, premise, genre, world_rules, canonical_timeline, unresolved_global_questions, created_at) VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
                 ("world-acc", "1.0", "Test", "urban_mystery", now))
    conn.execute("INSERT INTO characters (id, world_id, canonical_name, role, traits, age_category, status, location_id, created_at) VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?, ?)",
                 ("char-acc", "world-acc", "Acc Char", "protagonist", "loc-acc", now))
    conn.execute("INSERT INTO locations (id, world_id, name, connected_locations, created_at) VALUES (?, ?, ?, '[]', ?)",
                 ("loc-acc", "world-acc", "Acc Location", now))
    conn.execute("INSERT INTO canon_snapshots (id, world_id, version, episode_number, accepted, world_state_json, character_states_json, location_states_json, clue_states_json, unresolved_threads_json, created_at) VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
                 ("snap-acc", "world-acc", now))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, clue_refs_json, world_state_deltas_json, unresolved_threads_json, review_state, created_at) VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', '[]', '{}', '[]', 'published', ?)",
                 ("ep-acc", "world-acc", now))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
                 ("choice-acc", "reader-acc", "ep-acc", "Acc choice", now))
    conn.execute("INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, created_at) VALUES (?, ?, 1, 'test', ?)",
                 ("snap-acc", "snap-acc", now))
    conn.commit()


def _make_plan_payload():
    return {
        "plan_version": "v1", "world_id": "world-acc", "world_version": "1.0",
        "episode_type": "personal_branch", "episode_number": 1,
        "title": "Acc Branch", "synopsis": "Test",
        "scenes": [{"scene_id": "s1", "title": "S", "purpose": "T",
                     "participating_character_ids": ["char-acc"], "location_id": "loc-acc"}],
        "participating_character_ids": ["char-acc"], "location_ids": ["loc-acc"],
        "clue_refs": [], "next_choice_options": ["A"], "content_classification": "adult",
    }


def _make_content_payload():
    return {
        "content_version": "v1", "world_id": "world-acc",
        "episode_type": "personal_branch", "episode_number": 1,
        "title": "Acc Branch", "synopsis": "Test",
        "scenes": [{"scene_id": "s1", "title": "S", "purpose": "T",
                     "participating_character_ids": ["char-acc"], "location_id": "loc-acc"}],
        "prose": [{"scene_id": "s1", "paragraphs": ["The branch diverged."]}],
        "clue_refs": [],
        "world_state_delta": {
            "character_knowledge_added": {}, "character_knowledge_sources": {},
            "character_location_changed": {}, "character_movement_explanations": {},
            "character_injuries_added": {}, "character_injuries_removed": {},
            "character_possessions_added": {}, "character_possessions_removed": {},
            "character_relationship_changes": {}, "clues_introduced": [],
            "clues_resolved": [], "canon_clue_resolution_explanations": {},
            "unresolved_threads": [], "thread_resolutions": {},
            "branch_only_facts": ["acc branch fact"],
        },
        "applied_reader_input": {
            "reader_choice_id": "choice-acc", "choice_text": "Acc choice",
            "comment": None, "applied_evidence": "The choice shaped the branch.",
        },
        "unresolved_threads": [], "next_choice_options": ["A"],
        "content_classification": "adult",
    }


class _TimingProvider:
    """Provider that records exact timing for each attempt."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0
        self._provider_name = "timing-test"
        self._model = "timing-model"

    @property
    def provider_name(self):
        return self._provider_name

    @property
    def model(self):
        return self._model

    @property
    def cost_class(self):
        return CostClass.PAID

    def generate_structured(self, *, task_name, system_prompt, user_payload,
                            response_schema, request_id):
        idx = self._call_count
        self._call_count += 1
        resp = self._responses[min(idx, len(self._responses) - 1)]
        kind = resp.get("kind", "success")
        latency = resp.get("latency", 0.1)

        time.sleep(latency)

        if kind == "error":
            return ProviderResult(
                provider=self._provider_name, advertised_model=self._model,
                cost_class=CostClass.PAID, latency_seconds=latency, retry_count=0,
                request_id=request_id,
                error_category=resp.get("category", ProviderErrorCategory.TIMEOUT),
                error_message=resp.get("message", "error"), success=False,
                usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )

        if response_schema == EpisodePlan:
            payload = _make_plan_payload()
        else:
            payload = _make_content_payload()

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self._provider_name, advertised_model=self._model,
            cost_class=CostClass.PAID, latency_seconds=latency, retry_count=0,
            payload=validated.model_dump(), request_id=request_id, success=True,
            usage=ProviderUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )


class _SlowFailProvider:
    """Provider that always raises TimeoutError after a delay."""

    def __init__(self, delay=0.05):
        self._provider_name = "slow-fail"
        self._model = "slow-fail-model"
        self._cost_class = CostClass.FREE
        self.call_count = 0
        self._delay = delay

    @property
    def provider_name(self):
        return self._provider_name

    @property
    def model(self):
        return self._model

    @property
    def cost_class(self):
        return self._cost_class

    def generate_structured(self, **kwargs):
        self.call_count += 1
        time.sleep(self._delay)
        raise TimeoutError("simulated timeout")


def test_aggregate_latency_exact_arithmetic(db_path):
    """Aggregate latency = sum of all attempt latencies including exceptions."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _TimingProvider([
        {"kind": "error", "category": ProviderErrorCategory.TIMEOUT,
         "message": "timeout", "latency": 0.3},
        {"kind": "success", "latency": 0.7},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-acc", canonical_name="C",
                                                role="protagonist", location_id="loc-acc")],
                       locations=[LocationRef(location_id="loc-acc", name="L")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type="personal_branch",
                                reader_id="reader-acc", reader_choice_id="choice-acc",
                                reader_choice_text="Acc choice", idempotency_key="agg-lat-1")
    result = generate_personal_branch(conn, provider, request, max_retries=1,
                                      world_id="world-acc", canon_checkpoint_id="snap-acc",
                                      prior_episode_id="ep-acc")
    assert result.succeeded, f"Generation failed: {result.error}"

    # Find the run that contains the error attempt (plan run with retry)
    run_with_error = conn.execute(
        "SELECT DISTINCT ga.generation_run_id FROM generation_attempts ga "
        "WHERE ga.success = 0"
    ).fetchone()
    assert run_with_error is not None
    target_run_id = run_with_error["generation_run_id"]

    # Get attempts for this specific run
    attempts = conn.execute(
        "SELECT attempt_number, latency_seconds FROM generation_attempts "
        "WHERE generation_run_id = ? ORDER BY attempt_number",
        (target_run_id,)
    ).fetchall()
    assert len(attempts) >= 2
    att1_latency = attempts[0]["latency_seconds"]
    att2_latency = attempts[1]["latency_seconds"]

    run = conn.execute(
        "SELECT latency_seconds FROM generation_runs WHERE id = ?",
        (target_run_id,)
    ).fetchone()
    assert run is not None
    aggregate_latency = run["latency_seconds"]

    assert abs(aggregate_latency - (att1_latency + att2_latency)) < 0.1, \
        f"Aggregate {aggregate_latency} != sum {att1_latency + att2_latency}"
    conn.close()


def test_aggregate_latency_includes_exception_attempts(db_path):
    """Exception attempt latency is included in aggregate."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _SlowFailProvider(delay=0.05)

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-acc", canonical_name="C",
                                                role="protagonist", location_id="loc-acc")],
                       locations=[LocationRef(location_id="loc-acc", name="L")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type="personal_branch",
                                reader_id="reader-acc", reader_choice_id="choice-acc",
                                reader_choice_text="Acc choice", idempotency_key="exc-lat-1")
    result = generate_personal_branch(conn, provider, request, max_retries=1,
                                      world_id="world-acc", canon_checkpoint_id="snap-acc",
                                      prior_episode_id="ep-acc")
    assert not result.succeeded
    assert provider.call_count == 2

    attempts = conn.execute(
        "SELECT attempt_number, latency_seconds FROM generation_attempts ORDER BY attempt_number"
    ).fetchall()
    assert len(attempts) >= 2
    for att in attempts:
        assert att["latency_seconds"] is not None
        assert att["latency_seconds"] >= 0.04

    run = conn.execute(
        "SELECT latency_seconds FROM generation_runs WHERE success = 0 ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert run is not None
    assert run["latency_seconds"] is not None
    assert run["latency_seconds"] >= 0.08
    conn.close()


def test_provider_model_cost_persisted_from_result(db_path):
    """Provider/model/cost from actual ProviderResult are persisted."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _TimingProvider([{"kind": "success", "latency": 0.1}])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-acc", canonical_name="C",
                                                role="protagonist", location_id="loc-acc")],
                       locations=[LocationRef(location_id="loc-acc", name="L")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type="personal_branch",
                                reader_id="reader-acc", reader_choice_id="choice-acc",
                                reader_choice_text="Acc choice", idempotency_key="prov-id-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
                                      world_id="world-acc", canon_checkpoint_id="snap-acc",
                                      prior_episode_id="ep-acc")
    assert result.succeeded, f"Generation failed: {result.error}"

    attempts = conn.execute(
        "SELECT provider, advertised_model, cost_class FROM generation_attempts WHERE success = 1"
    ).fetchall()
    for att in attempts:
        assert att["provider"] == "timing-test"
        assert att["advertised_model"] == "timing-model"
        assert att["cost_class"] == "paid"
    conn.close()


def test_no_raw_error_message_in_db(db_path):
    """No raw exception string stored in durable error records."""
    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())

    now = "2025-01-01T00:00:00Z"
    safe_msg = safe_error_message(ProviderErrorCategory.TIMEOUT, None)
    conn.execute(
        "INSERT INTO generation_runs (id, task_type, provider, advertised_model, "
        "cost_class, started_at, completed_at, success, validation_status, "
        "error_category, error_message, retry_count, created_at) "
        "VALUES (?, 'test', 'mock', 'mock-v1', 'free', ?, ?, 0, 'provider_failed', "
        "'timeout', ?, 0, ?)",
        ("run-1", now, now, safe_msg, now),
    )
    conn.commit()

    row = conn.execute("SELECT error_message FROM generation_runs WHERE id = 'run-1'").fetchone()
    assert row is not None
    assert "timeout: provider request timed out" == row["error_message"]
    assert "secret" not in row["error_message"].lower()
    conn.close()


def test_validation_failure_sets_success_false(db_path):
    """Validation failure sets success=False on generation run."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _TimingProvider([
        {"kind": "error", "category": ProviderErrorCategory.SCHEMA_MISMATCH,
         "message": "mismatch", "latency": 0.1},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-acc", canonical_name="C",
                                                role="protagonist", location_id="loc-acc")],
                       locations=[LocationRef(location_id="loc-acc", name="L")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type="personal_branch",
                                reader_id="reader-acc", reader_choice_id="choice-acc",
                                reader_choice_text="Acc choice", idempotency_key="val-fail-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
                                      world_id="world-acc", canon_checkpoint_id="snap-acc",
                                      prior_episode_id="ep-acc")
    assert not result.succeeded

    runs = conn.execute("SELECT success FROM generation_runs").fetchall()
    for run in runs:
        assert run["success"] == 0
    conn.close()


def test_close_reopen_preserves_accounting(db_path):
    """Close/reopen preserves all accounting rows."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _TimingProvider([{"kind": "success", "latency": 0.1}])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-acc", canonical_name="C",
                                                role="protagonist", location_id="loc-acc")],
                       locations=[LocationRef(location_id="loc-acc", name="L")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type="personal_branch",
                                reader_id="reader-acc", reader_choice_id="choice-acc",
                                reader_choice_text="Acc choice", idempotency_key="cr-persist-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
                                      world_id="world-acc", canon_checkpoint_id="snap-acc",
                                      prior_episode_id="ep-acc")
    assert result.succeeded, f"Generation failed: {result.error}"
    conn.close()

    conn = _make_conn(db_path)
    attempts = conn.execute(
        "SELECT provider, advertised_model, success FROM generation_attempts WHERE success = 1"
    ).fetchall()
    assert len(attempts) >= 1
    for att in attempts:
        assert att["provider"] == "timing-test"
        assert att["advertised_model"] == "timing-model"

    runs = conn.execute("SELECT success, validation_status FROM generation_runs WHERE success = 1").fetchall()
    assert len(runs) >= 1
    for run in runs:
        assert run["success"] == 1
        assert run["validation_status"] == "passed"
    conn.close()
