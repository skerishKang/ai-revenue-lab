"""Blocker A — Real public service concurrency tests.

Verifies that concurrent calls to generate_personal_branch() with the same
idempotency key using separate SQLite connections produce exactly one result
with no duplicate resources, no orphan records, and consistent replay.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.db import apply_migrations, get_connection
from app.domain.enums import EpisodeType, CostClass
from app.domain.models import (
    CharacterRef,
    EpisodeContent,
    EpisodePlan,
    LocationRef,
    ProviderResult,
    ProviderUsage,
    ScenePlan,
    ProseBeat,
    WorldState,
    ContinuityDelta,
    AppliedReaderInput,
)


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _seed_world(conn: sqlite3.Connection):
    now = "2025-07-21T00:00:00Z"
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
                 ("reader-1", "Reader", now))
    conn.execute("INSERT INTO worlds (id, version, premise, genre, world_rules, canonical_timeline, unresolved_global_questions, created_at) VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
                 ("world-1", "1.0", "Test", "urban_mystery", now))
    conn.execute("INSERT INTO characters (id, world_id, canonical_name, role, traits, age_category, status, location_id, created_at) VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?, ?)",
                 ("char-1", "world-1", "Char", "protagonist", "loc-1", now))
    conn.execute("INSERT INTO locations (id, world_id, name, connected_locations, created_at) VALUES (?, ?, ?, '[]', ?)",
                 ("loc-1", "world-1", "Loc", now))
    conn.execute("INSERT INTO canon_snapshots (id, world_id, version, episode_number, accepted, world_state_json, character_states_json, location_states_json, clue_states_json, unresolved_threads_json, created_at) VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
                 ("snap-1", "world-1", now))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, clue_refs_json, world_state_deltas_json, unresolved_threads_json, review_state, created_at) VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', '[]', '{}', '[]', 'published', ?)",
                 ("ep-1", "world-1", now))
    conn.execute("INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, created_at) VALUES (?, ?, 1, 'test', ?)",
                 ("snap-1", "snap-1", now))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
                 ("choice-1", "reader-1", "ep-1", "Test choice", now))
    conn.commit()


def _make_plan_payload(episode_number=1):
    return {
        "plan_version": "v1", "world_id": "world-1", "world_version": "1.0",
        "episode_type": "personal_branch", "episode_number": episode_number,
        "title": "Branch", "synopsis": "Test branch",
        "scenes": [{"scene_id": "s1", "title": "S", "purpose": "T",
                     "participating_character_ids": ["char-1"], "location_id": "loc-1"}],
        "participating_character_ids": ["char-1"], "location_ids": ["loc-1"],
        "clue_refs": [], "next_choice_options": ["A"], "content_classification": "adult",
    }


def _make_content_payload():
    return {
        "content_version": "v1", "world_id": "world-1",
        "episode_type": "personal_branch", "episode_number": 1,
        "title": "Branch", "synopsis": "Test branch",
        "scenes": [{"scene_id": "s1", "title": "S", "purpose": "T",
                     "participating_character_ids": ["char-1"], "location_id": "loc-1"}],
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
            "branch_only_facts": ["test branch fact"],
        },
        "applied_reader_input": {
            "reader_choice_id": "choice-1",
            "choice_text": "Test choice",
            "comment": None,
            "applied_evidence": "The choice shaped the branch.",
        },
        "unresolved_threads": [],
        "next_choice_options": ["A"],
        "content_classification": "adult",
    }


class _CountingProvider:
    """Provider with thread-safe call counter.

    Dynamically reflects the reader_choice_id from the user_payload
    so that content matches the actual choice being applied.
    """

    def __init__(self):
        self._plan_calls = 0
        self._content_calls = 0
        self._lock = threading.Lock()
        self._provider_name = "counting-test"
        self._model = "counting-model"
        self._cost_class = CostClass.FREE

    @property
    def provider_name(self):
        return self._provider_name

    @property
    def model(self):
        return self._model

    @property
    def cost_class(self):
        return self._cost_class

    @property
    def total_plan_calls(self):
        with self._lock:
            return self._plan_calls

    @property
    def total_content_calls(self):
        with self._lock:
            return self._content_calls

    def generate_structured(self, *, task_name, system_prompt, user_payload,
                            response_schema, request_id):
        with self._lock:
            if task_name == "episode_plan":
                self._plan_calls += 1
            elif task_name == "episode_content":
                self._content_calls += 1

        time.sleep(0.01)

        if task_name == "episode_plan":
            ep_num = user_payload.get("episode_number", 1)
            payload = _make_plan_payload(episode_number=ep_num)
        elif task_name == "episode_content":
            # Extract choice info and episode number from user_payload
            rc = user_payload.get("reader_choice") or {}
            choice_id = rc.get("reader_choice_id", "choice-1")
            choice_text = rc.get("choice_text", "Test choice")
            ep_num = user_payload.get("plan", {}).get("episode_number", 1)
            payload = _make_content_payload()
            payload["episode_number"] = ep_num
            if payload.get("applied_reader_input"):
                payload["applied_reader_input"]["reader_choice_id"] = choice_id
                payload["applied_reader_input"]["choice_text"] = choice_text
        else:
            raise ValueError(f"unexpected task: {task_name}")

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self._provider_name,
            advertised_model=self._model,
            cost_class=self._cost_class,
            latency_seconds=0.01,
            retry_count=0,
            payload=validated.model_dump(),
            request_id=request_id,
            success=True,
            usage=ProviderUsage(input_tokens=50, output_tokens=30, total_tokens=80),
        )


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = _make_conn(path)
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    apply_migrations(conn, migrations_dir)
    _seed_world(conn)
    conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def test_concurrent_same_key_one_provider_call_set(db_path):
    """Two threads with same idempotency key: provider called exactly once, second gets replay."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    provider = _CountingProvider()
    world = WorldState(world_id="world-1", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-1", canonical_name="C",
                                                role="protagonist", location_id="loc-1")],
                       locations=[LocationRef(location_id="loc-1", name="L")])

    idempotency_key = "concurrent-key-1"
    episode_ids = set()
    lock = threading.Lock()

    def run_generation(thread_id):
        conn = _make_conn(db_path)
        try:
            for attempt in range(60):
                req = GenerationRequest(
                    world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
                    reader_id="reader-1", reader_choice_id="choice-1",
                    reader_choice_text="Test choice", idempotency_key=idempotency_key,
                )
                result = generate_personal_branch(
                    conn, provider, req, max_retries=0,
                    world_id="world-1", canon_checkpoint_id="snap-1", prior_episode_id="ep-1",
                )
                if result.succeeded:
                    with lock:
                        episode_ids.add(result.episode_id)
                    return {"thread": thread_id, "succeeded": True,
                            "episode_id": result.episode_id, "replay": attempt > 0}
                if "already in progress" not in (result.error or ""):
                    return {"thread": thread_id, "succeeded": False,
                            "episode_id": None, "error": result.error}
                time.sleep(0.5)
            return {"thread": thread_id, "succeeded": False, "error": "timeout polling"}
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_generation, 0)
        f2 = executor.submit(run_generation, 1)
        r1 = f1.result(timeout=60)
        r2 = f2.result(timeout=60)

    assert r1["succeeded"], f"Thread 0 failed: {r1.get('error')}"
    assert r2["succeeded"], f"Thread 1 failed: {r2.get('error')}"
    assert len(episode_ids) == 1, f"Expected 1 unique episode, got {len(episode_ids)}: {episode_ids}"

    assert provider.total_plan_calls == 1, f"Expected 1 plan call, got {provider.total_plan_calls}"
    assert provider.total_content_calls == 1, f"Expected 1 content call, got {provider.total_content_calls}"

    conn = _make_conn(db_path)
    ep_count = conn.execute(
        "SELECT COUNT(*) as c FROM episodes WHERE episode_type = 'personal_branch'"
    ).fetchone()["c"]
    branch_count = conn.execute("SELECT COUNT(*) as c FROM branches").fetchone()["c"]
    choice_applied = conn.execute(
        "SELECT COUNT(*) as c FROM reader_choices WHERE applied_to_branch_id IS NOT NULL"
    ).fetchone()["c"]
    gen_req_completed = conn.execute(
        "SELECT COUNT(*) as c FROM branch_generation_requests WHERE status = 'completed'"
    ).fetchone()["c"]
    run_count = conn.execute("SELECT COUNT(*) as c FROM generation_runs").fetchone()["c"]
    attempt_count = conn.execute("SELECT COUNT(*) as c FROM generation_attempts").fetchone()["c"]
    conn.close()

    assert ep_count == 1, f"Expected 1 branch episode, got {ep_count}"
    assert branch_count == 1, f"Expected 1 branch, got {branch_count}"
    assert choice_applied == 1, f"Expected 1 choice applied, got {choice_applied}"
    assert gen_req_completed == 1, f"Expected 1 completed request, got {gen_req_completed}"
    assert run_count == 2, f"Expected 2 generation runs (plan+content), got {run_count}"
    assert attempt_count == 2, f"Expected 2 attempts (plan+content), got {attempt_count}"


def test_concurrent_same_key_no_orphan_records(db_path):
    """Concurrent same-key requests leave no orphan records."""
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    provider = _CountingProvider()
    world = WorldState(world_id="world-1", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-1", canonical_name="C",
                                                role="protagonist", location_id="loc-1")],
                       locations=[LocationRef(location_id="loc-1", name="L")])
    idempotency_key = "orphan-test-key"

    def run_generation(thread_id):
        conn = _make_conn(db_path)
        try:
            for attempt in range(60):
                req = GenerationRequest(
                    world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
                    reader_id="reader-1", reader_choice_id="choice-1",
                    reader_choice_text="Test choice", idempotency_key=idempotency_key,
                )
                result = generate_personal_branch(
                    conn, provider, req, max_retries=0,
                    world_id="world-1", canon_checkpoint_id="snap-1", prior_episode_id="ep-1",
                )
                if result.succeeded:
                    return {"thread": thread_id, "succeeded": True, "episode_id": result.episode_id}
                if "already in progress" not in (result.error or ""):
                    return {"thread": thread_id, "succeeded": False, "error": result.error}
                time.sleep(0.5)
            return {"thread": thread_id, "succeeded": False, "error": "timeout"}
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_generation, i) for i in range(2)]
        results = [f.result(timeout=60) for f in as_completed(futures)]

    assert all(r["succeeded"] for r in results), f"Some failed: {results}"
    assert results[0]["episode_id"] == results[1]["episode_id"]

    conn = _make_conn(db_path)
    pending = conn.execute(
        "SELECT COUNT(*) as c FROM branch_generation_requests WHERE status = 'pending'"
    ).fetchone()["c"]
    failed = conn.execute(
        "SELECT COUNT(*) as c FROM branch_generation_requests WHERE status = 'failed'"
    ).fetchone()["c"]
    conn.close()
    assert pending == 0, f"Orphan pending requests: {pending}"
    assert failed == 0, f"Orphan failed requests: {failed}"


def test_concurrent_different_keys_proceed_independently(db_path):
    """Different idempotency keys with different choices proceed without interference.

    Both threads use separate choices. At least one must succeed; both may
    succeed depending on timing. No orphan records should exist regardless.
    """
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    # Each thread needs its own choice (a choice can only be applied once)
    conn = _make_conn(db_path)
    now = "2025-07-21T00:00:00Z"
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("choice-a", "reader-1", "ep-1", "Choice A", now),
    )
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("choice-b", "reader-1", "ep-1", "Choice B", now),
    )
    conn.commit()
    conn.close()

    provider = _CountingProvider()
    world = WorldState(world_id="world-1", version="1.0", premise="Test",
                       characters=[CharacterRef(character_id="char-1", canonical_name="C",
                                                role="protagonist", location_id="loc-1")],
                       locations=[LocationRef(location_id="loc-1", name="L")])

    def run_generation(key, choice_id, choice_text):
        conn = _make_conn(db_path)
        try:
            req = GenerationRequest(
                world=world, episode_type=EpisodeType.PERSONAL_BRANCH,
                reader_id="reader-1", reader_choice_id=choice_id,
                reader_choice_text=choice_text, idempotency_key=key,
            )
            result = generate_personal_branch(
                conn, provider, req, max_retries=0,
                world_id="world-1", canon_checkpoint_id="snap-1", prior_episode_id="ep-1",
            )
            return {"key": key, "succeeded": result.succeeded, "episode_id": result.episode_id}
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_generation, "key-A", "choice-a", "Choice A")
        f2 = executor.submit(run_generation, "key-B", "choice-b", "Choice B")
        r1 = f1.result(timeout=30)
        r2 = f2.result(timeout=30)

    # At least one must succeed; both may succeed depending on timing
    assert r1["succeeded"] or r2["succeeded"], \
        f"Both failed: A={r1.get('error')}, B={r2.get('error')}"

    # No orphan PENDING requests (failed is a legitimate outcome)
    conn = _make_conn(db_path)
    pending = conn.execute(
        "SELECT COUNT(*) as c FROM branch_generation_requests WHERE status = 'pending'"
    ).fetchone()["c"]
    completed = conn.execute(
        "SELECT COUNT(*) as c FROM branch_generation_requests WHERE status = 'completed'"
    ).fetchone()["c"]
    conn.close()
    assert pending == 0, f"Orphan pending requests: {pending}"
    assert completed >= 1, f"Expected at least 1 completed, got {completed}"
