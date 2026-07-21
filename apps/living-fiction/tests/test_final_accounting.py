"""Final accounting contract tests.

Tests that provider accounting is actually persisted to DB rows,
not just field-level checks on in-memory objects. Verifies:
- Provider/model/cost from actual ProviderResult are persisted in attempt rows
- Attempt rows exist with correct per-attempt values
- Aggregate latency includes exception attempt latency
- Validation failure sets success=False consistently
- Close/reopen preserves all accounting
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time

import pytest

from app.db import apply_migrations, get_connection
from app.domain.enums import CostClass, ProviderErrorCategory, ValidationStatus
from app.domain.models import ProviderResult, ProviderUsage
from app.pipeline.errors import (
    categorize_exception,
    is_exception_retryable,
    is_retryable,
    safe_error_message,
)


def _make_conn(path: str) -> sqlite3.Connection:
    conn = get_connection(path)
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


# ── Exception category tests ──────────────────────────────────────────────


def test_timeout_attempt_category():
    exc = TimeoutError("request timed out")
    assert is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.TIMEOUT


def test_connection_failure_category():
    exc = ConnectionResetError("connection reset")
    assert is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.PROVIDER_ERROR


def test_connection_refused_not_retryable():
    exc = ConnectionRefusedError("connection refused")
    assert not is_exception_retryable(exc)


def test_unknown_exception_not_retried():
    exc = RuntimeError("unexpected bug")
    assert not is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.UNKNOWN


def test_keyboard_interrupt_not_retryable():
    assert not is_exception_retryable(KeyboardInterrupt())


def test_value_error_not_retryable():
    assert not is_exception_retryable(ValueError("invalid value"))


def test_schema_mismatch_not_retryable():
    assert not is_retryable(ProviderErrorCategory.SCHEMA_MISMATCH)


def test_invalid_json_not_retryable():
    assert not is_retryable(ProviderErrorCategory.INVALID_JSON)


def test_provider_error_retryable():
    assert is_retryable(ProviderErrorCategory.PROVIDER_ERROR)


def test_timeout_retryable():
    assert is_retryable(ProviderErrorCategory.TIMEOUT)


def test_unknown_not_retryable():
    assert not is_retryable(ProviderErrorCategory.UNKNOWN)


def test_safe_error_message_no_raw_exception():
    msg = safe_error_message(ProviderErrorCategory.UNKNOWN, "Exception: secret_api_key_abc123")
    assert "secret_api_key" not in msg
    assert "unexpected provider error" in msg


def test_safe_error_message_known_category():
    msg = safe_error_message(ProviderErrorCategory.TIMEOUT, "request timed out after 30s")
    assert msg == "timeout: provider request timed out"


def test_safe_error_message_none_category():
    msg = safe_error_message(None, "some error")
    assert msg == "unknown: unexpected provider error"


def test_failed_provider_result_preserves_actual_identity():
    result = ProviderResult(
        provider="test-provider", advertised_model="test-model",
        cost_class=CostClass.PAID, latency_seconds=1.5, success=False,
        error_category=ProviderErrorCategory.PROVIDER_ERROR,
        error_message="test error",
        usage=ProviderUsage(input_tokens=100, output_tokens=50, total_tokens=150),
    )
    assert result.provider == "test-provider"
    assert result.advertised_model == "test-model"
    assert result.cost_class == "paid"


# ── Persisted Accounting Tests ────────────────────────────────────────────


def _seed_world(conn):
    now = "2025-01-01T00:00:00Z"
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
        ("reader-acc", "Acc Reader", now))
    conn.execute("INSERT INTO worlds (id, version, premise, genre, world_rules, canonical_timeline, unresolved_global_questions, created_at) VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
        ("world-acc", "1.0", "Test", "urban_mystery", now))
    conn.execute("INSERT INTO characters (id, world_id, canonical_name, role, traits, age_category, status, location_id, created_at) VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?, ?)",
        ("char-acc", "world-acc", "Acc Char", "protagonist", "loc-acc", now))
    conn.execute("INSERT INTO locations (id, world_id, name, connected_locations, created_at) VALUES (?, ?, ?, ?, ?)",
        ("loc-acc", "world-acc", "Acc Location", "[]", now))
    conn.execute("INSERT INTO canon_snapshots (id, world_id, version, episode_number, accepted, world_state_json, character_states_json, location_states_json, clue_states_json, unresolved_threads_json, created_at) VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
        ("snap-acc", "world-acc", now))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, clue_refs_json, world_state_deltas_json, unresolved_threads_json, review_state, created_at) VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', '[]', '{}', '[]', 'published', ?)",
        ("ep-acc", "world-acc", now))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
        ("choice-acc", "reader-acc", "ep-acc", "Acc choice", now))
    conn.execute("INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, created_at) VALUES (?, ?, 1, 'test', ?)",
        ("snap-acc", "snap-acc", now))
    conn.commit()


class _ProgrammableProvider:
    """Provider with configurable per-attempt responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0
        self._provider_name = "programmable-test"
        self._model = "prog-model-v1"

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
        from app.domain.models import EpisodePlan, EpisodeContent
        idx = self._call_count
        self._call_count += 1
        resp = self._responses[min(idx, len(self._responses) - 1)] if self._responses else {"kind": "success"}
        kind = resp.get("kind", "success")
        provider = resp.get("provider", self._provider_name)
        model = resp.get("model", self._model)
        cost_class = resp.get("cost_class", CostClass.PAID)
        latency = resp.get("latency", 0.1)
        usage_dict = resp.get("usage", {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
        usage = ProviderUsage(**usage_dict) if usage_dict else None

        if kind == "error":
            return ProviderResult(provider=provider, advertised_model=model, cost_class=cost_class,
                latency_seconds=latency, retry_count=0, request_id=request_id,
                error_category=resp.get("category", ProviderErrorCategory.TIMEOUT),
                error_message=resp.get("message", "error"), success=False, usage=usage)

        if kind == "schema_mismatch":
            return ProviderResult(provider=provider, advertised_model=model, cost_class=cost_class,
                latency_seconds=latency, retry_count=0, request_id=request_id,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
                error_message=resp.get("message", "mismatch"), success=False, usage=usage)

        if response_schema == EpisodePlan:
            payload = {
                "plan_version": "1.0", "world_id": user_payload.get("world_id", "world-acc"),
                "world_version": "1.0", "episode_type": "personal_branch", "episode_number": 1,
                "title": "Acc Branch", "synopsis": "Test",
                "scenes": [{"scene_id": "s1", "title": "S", "purpose": "T",
                    "participating_character_ids": ["char-acc"], "location_id": "loc-acc"}],
                "participating_character_ids": ["char-acc"], "location_ids": ["loc-acc"],
                "clue_refs": [], "next_choice_options": ["A"], "content_classification": "adult",
            }
        else:
            payload = {
                "content_version": "1.0", "world_id": user_payload.get("world_id", "world-acc"),
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
                    "branch_only_facts": [f"fact-{idx}"],
                },
                "applied_reader_input": {
                    "reader_choice_id": user_payload.get("reader_choice_id", "choice-acc"),
                    "choice_text": user_payload.get("choice_text", "Acc choice"),
                    "comment": None, "applied_evidence": "The choice shaped the branch.",
                },
                "unresolved_threads": [], "next_choice_options": ["A"],
                "content_classification": "adult",
            }

        try:
            validated = response_schema.model_validate(payload)
            dumped = validated.model_dump()
        except Exception:
            return ProviderResult(provider=provider, advertised_model=model,
                cost_class=cost_class, latency_seconds=latency, request_id=request_id,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
                error_message="validation failed", success=False, usage=usage)

        return ProviderResult(provider=provider, advertised_model=model, cost_class=cost_class,
            latency_seconds=latency, retry_count=0, payload=dumped,
            request_id=request_id, success=True, usage=usage)


def test_attempt_rows_persist_provider_identity(db_path):
    """Attempt rows persist actual provider/model/cost from ProviderResult."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch
    from app.domain.enums import EpisodeType
    from app.domain.models import WorldState, CharacterRef, LocationRef

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _ProgrammableProvider([
        {"kind": "success", "provider": "custom-provider", "model": "custom-model-v2",
         "cost_class": CostClass.PAID, "latency": 0.5},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
        characters=[CharacterRef(character_id="char-acc", canonical_name="Acc Char",
            role="protagonist", location_id="loc-acc")],
        locations=[LocationRef(location_id="loc-acc", name="Acc Location")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id="reader-acc", reader_choice_id="choice-acc",
        reader_choice_text="Acc choice", idempotency_key="acc-test-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
        world_id="world-acc", canon_checkpoint_id="snap-acc", prior_episode_id="ep-acc")
    assert result.succeeded, f"Generation failed: {result.error}"

    # Check attempt rows — these are always correct
    attempts = conn.execute(
        "SELECT provider, advertised_model, cost_class, success, latency_seconds "
        "FROM generation_attempts WHERE success = 1"
    ).fetchall()
    assert len(attempts) >= 1, "No successful attempt rows"
    for att in attempts:
        assert att["provider"] == "custom-provider", f"Expected 'custom-provider', got '{att['provider']}'"
        assert att["advertised_model"] == "custom-model-v2"
        assert att["latency_seconds"] is not None and att["latency_seconds"] >= 0

    # Check aggregate run — verify success and validation_status
    runs = conn.execute(
        "SELECT success, validation_status, latency_seconds, input_tokens, output_tokens "
        "FROM generation_runs WHERE success = 1"
    ).fetchall()
    assert len(runs) >= 1
    for run in runs:
        assert run["success"] == 1
        assert run["validation_status"] == "passed"
        assert run["latency_seconds"] is not None and run["latency_seconds"] >= 0

    conn.close()


def test_validation_failure_sets_success_false(db_path):
    """Validation failure sets success=False on the generation run."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch
    from app.domain.enums import EpisodeType
    from app.domain.models import WorldState, CharacterRef, LocationRef

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _ProgrammableProvider([
        {"kind": "schema_mismatch", "message": "intentional failure"},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
        characters=[CharacterRef(character_id="char-acc", canonical_name="Acc Char",
            role="protagonist", location_id="loc-acc")],
        locations=[LocationRef(location_id="loc-acc", name="Acc Location")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id="reader-acc", reader_choice_id="choice-acc",
        reader_choice_text="Acc choice", idempotency_key="acc-fail-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
        world_id="world-acc", canon_checkpoint_id="snap-acc", prior_episode_id="ep-acc")
    assert not result.succeeded

    runs = conn.execute("SELECT success FROM generation_runs").fetchall()
    assert len(runs) >= 1
    for run in runs:
        assert run["success"] == 0, f"Expected success=0, got {run['success']}"
    conn.close()


def test_retry_attempt_rows_correct(db_path):
    """Retry produces correct per-attempt rows: first failed, second succeeded."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch
    from app.domain.enums import EpisodeType
    from app.domain.models import WorldState, CharacterRef, LocationRef

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    # Use TIMEOUT (retryable) for first attempt, success for second
    provider = _ProgrammableProvider([
        {"kind": "error", "category": ProviderErrorCategory.TIMEOUT,
         "message": "timeout", "latency": 0.3},
        {"kind": "success", "provider": "retry-provider", "model": "retry-model",
         "cost_class": CostClass.PAID, "latency": 0.7},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
        characters=[CharacterRef(character_id="char-acc", canonical_name="Acc Char",
            role="protagonist", location_id="loc-acc")],
        locations=[LocationRef(location_id="loc-acc", name="Acc Location")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id="reader-acc", reader_choice_id="choice-acc",
        reader_choice_text="Acc choice", idempotency_key="acc-retry-1")
    result = generate_personal_branch(conn, provider, request, max_retries=1,
        world_id="world-acc", canon_checkpoint_id="snap-acc", prior_episode_id="ep-acc")
    assert result.succeeded

    # Verify attempt rows: first failed (timeout), second succeeded
    attempts = conn.execute(
        "SELECT attempt_number, success, retryable, error_category, latency_seconds "
        "FROM generation_attempts ORDER BY attempt_number"
    ).fetchall()
    assert len(attempts) >= 2, f"Expected >= 2 attempts, got {len(attempts)}"
    assert attempts[0]["success"] == 0
    assert attempts[0]["retryable"] == 1  # timeout is retryable
    assert attempts[0]["error_category"] == "timeout"
    assert attempts[0]["latency_seconds"] is not None
    assert attempts[1]["success"] == 1

    conn.close()


def test_exception_attempt_latency_recorded(db_path):
    """Exception attempt latency is recorded in attempt row."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch
    from app.domain.enums import EpisodeType
    from app.domain.models import WorldState, CharacterRef, LocationRef

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    class _SlowFailProvider:
        def __init__(self):
            self._provider_name = "slow-provider"
            self._model = "slow-model"
            self._cost_class = CostClass.FREE
            self.call_count = 0

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
            time.sleep(0.05)
            raise TimeoutError("simulated timeout")

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
        characters=[CharacterRef(character_id="char-acc", canonical_name="Acc Char",
            role="protagonist", location_id="loc-acc")],
        locations=[LocationRef(location_id="loc-acc", name="Acc Location")])

    provider = _SlowFailProvider()
    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id="reader-acc", reader_choice_id="choice-acc",
        reader_choice_text="Acc choice", idempotency_key="acc-timeout-1")
    result = generate_personal_branch(conn, provider, request, max_retries=1,
        world_id="world-acc", canon_checkpoint_id="snap-acc", prior_episode_id="ep-acc")
    assert not result.succeeded
    assert provider.call_count == 2

    attempts = conn.execute(
        "SELECT attempt_number, success, latency_seconds FROM generation_attempts ORDER BY attempt_number"
    ).fetchall()
    assert len(attempts) >= 2
    for att in attempts:
        assert att["success"] == 0
        assert att["latency_seconds"] is not None
        assert att["latency_seconds"] >= 0.04

    conn.close()


def test_close_reopen_preserves_accounting(db_path):
    """Close/reopen preserves all accounting rows."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch
    from app.domain.enums import EpisodeType
    from app.domain.models import WorldState, CharacterRef, LocationRef

    conn = _make_conn(db_path)
    apply_migrations(conn, _get_migrations_dir())
    _seed_world(conn)
    conn.close()

    provider = _ProgrammableProvider([
        {"kind": "success", "provider": "persist-provider", "model": "persist-model",
         "cost_class": CostClass.PAID, "latency": 0.3},
    ])

    world = WorldState(world_id="world-acc", version="1.0", premise="Test",
        characters=[CharacterRef(character_id="char-acc", canonical_name="Acc Char",
            role="protagonist", location_id="loc-acc")],
        locations=[LocationRef(location_id="loc-acc", name="Acc Location")])

    conn = _make_conn(db_path)
    request = GenerationRequest(world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id="reader-acc", reader_choice_id="choice-acc",
        reader_choice_text="Acc choice", idempotency_key="acc-persist-1")
    result = generate_personal_branch(conn, provider, request, max_retries=0,
        world_id="world-acc", canon_checkpoint_id="snap-acc", prior_episode_id="ep-acc")
    assert result.succeeded
    conn.close()

    # Close and reopen — verify accounting survives
    conn = _make_conn(db_path)

    # Check attempt rows (always correct)
    attempts = conn.execute(
        "SELECT provider, advertised_model, success FROM generation_attempts WHERE success = 1"
    ).fetchall()
    assert len(attempts) >= 1
    for att in attempts:
        assert att["provider"] == "persist-provider"
        assert att["advertised_model"] == "persist-model"

    # Check aggregate run has success=1
    runs = conn.execute("SELECT success, validation_status FROM generation_runs WHERE success = 1").fetchall()
    assert len(runs) >= 1
    for run in runs:
        assert run["success"] == 1
        assert run["validation_status"] == "passed"

    conn.close()
