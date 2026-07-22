"""Production concurrency contracts: one service call per concurrent caller."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import apply_migrations
from app.domain.enums import CostClass, EpisodeType
from app.domain.models import CharacterRef, LocationRef, ProviderResult, ProviderUsage, WorldState


def _conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    now = "2026-07-21T00:00:00Z"
    conn.executescript(f"""
        INSERT INTO readers(id, display_name, status, created_at)
        VALUES ('reader-1', 'Reader', 'active', '{now}');
        INSERT INTO worlds(id, version, premise, genre, world_rules, canonical_timeline,
                           unresolved_global_questions, created_at)
        VALUES ('world-1', '1.0', 'Synthetic', 'urban_mystery', '[]', '[]', '[]', '{now}');
        INSERT INTO locations(id, world_id, name, connected_locations, created_at)
        VALUES ('loc-1', 'world-1', 'Station', '[]', '{now}');
        INSERT INTO characters(id, world_id, canonical_name, role, traits, age_category,
                               status, location_id, created_at)
        VALUES ('char-1', 'world-1', 'Mira', 'protagonist', '[]', 'adult',
                'active', 'loc-1', '{now}');
        INSERT INTO canon_snapshots(id, world_id, version, episode_number, accepted,
            world_state_json, character_states_json, location_states_json,
            clue_states_json, unresolved_threads_json, created_at)
        VALUES ('snap-1', 'world-1', '1.0', 1, 1, '{{}}', '{{}}', '{{}}', '{{}}', '[]', '{now}');
        INSERT INTO episodes(id, world_id, episode_type, episode_number, title, synopsis,
            scene_list_json, character_ids_json, location_ids_json, prose_json,
            clue_refs_json, world_state_deltas_json, unresolved_threads_json,
            next_choice_options_json, content_classification, review_state, created_at)
        VALUES ('ep-1', 'world-1', 'canon', 1, 'Opening', 'Opening', '[]', '[]', '[]',
                '[]', '[]', '{{}}', '[]', '[]', 'adult', 'published', '{now}');
        INSERT INTO canon_checkpoints(id, canon_snapshot_id, episode_number, label, created_at)
        VALUES ('checkpoint-1', 'snap-1', 1, 'opening', '{now}');
        INSERT INTO reader_choices(id, reader_id, canon_episode_id, choice_text, submitted_at)
        VALUES ('choice-1', 'reader-1', 'ep-1', 'Inspect carefully', '{now}');
    """)
    conn.commit()


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = _conn(path)
    apply_migrations(conn, os.path.join(os.path.dirname(__file__), "..", "migrations"))
    _seed(conn)
    conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _world() -> WorldState:
    return WorldState(
        world_id="world-1",
        version="1.0",
        premise="Caller value is not authoritative",
        characters=[CharacterRef(
            character_id="char-1", canonical_name="Mira",
            role="protagonist", location_id="loc-1",
        )],
        locations=[LocationRef(location_id="loc-1", name="Station")],
    )


def _plan(number: int) -> dict:
    return {
        "plan_version": "v1", "world_id": "world-1", "world_version": "1.0",
        "episode_type": "personal_branch", "episode_number": number,
        "title": f"Branch {number}", "synopsis": "Reader-directed branch",
        "scenes": [{
            "scene_id": f"scene-{number}", "title": "Inspection",
            "purpose": "Apply choice", "participating_character_ids": ["char-1"],
            "location_id": "loc-1",
        }],
        "participating_character_ids": ["char-1"], "location_ids": ["loc-1"],
        "clue_refs": [], "next_choice_options": ["Continue"],
        "content_classification": "adult",
    }


def _content(number: int, choice_id: str, choice_text: str) -> dict:
    return {
        "content_version": "v1", "world_id": "world-1",
        "episode_type": "personal_branch", "episode_number": number,
        "title": f"Branch {number}", "synopsis": "Reader-directed branch",
        "scenes": [{
            "scene_id": f"scene-{number}", "title": "Inspection",
            "purpose": "Apply choice", "participating_character_ids": ["char-1"],
            "location_id": "loc-1",
        }],
        "prose": [{"scene_id": f"scene-{number}", "paragraphs": [
            f"Mira follows the instruction to {choice_text.lower()} and changes her route."
        ]}],
        "clue_refs": [],
        "world_state_delta": {
            "character_knowledge_added": {}, "character_knowledge_sources": {},
            "character_location_changed": {}, "character_movement_explanations": {},
            "character_injuries_added": {}, "character_injuries_removed": {},
            "character_possessions_added": {}, "character_possessions_removed": {},
            "character_relationship_changes": {}, "clues_introduced": [],
            "clues_resolved": [], "canon_clue_resolution_explanations": {},
            "unresolved_threads": [], "thread_resolutions": {},
            "branch_only_facts": [f"reader-route-{number}"],
        },
        "applied_reader_input": {
            "reader_choice_id": choice_id, "choice_text": choice_text, "comment": None,
            "applied_evidence": f"The scene follows: {choice_text}",
        },
        "unresolved_threads": [], "next_choice_options": ["Continue"],
        "content_classification": "adult",
    }


class _Provider:
    def __init__(self):
        self.lock = threading.Lock()
        self.plan_calls = 0
        self.content_calls = 0

    provider_name = "concurrency-contract"
    model = "concurrency-model"
    cost_class = CostClass.FREE

    def generate_structured(self, *, task_name, system_prompt, user_payload,
                            response_schema, request_id):
        del system_prompt
        with self.lock:
            if task_name == "episode_plan":
                self.plan_calls += 1
            else:
                self.content_calls += 1
        time.sleep(0.12)
        if task_name == "episode_plan":
            payload = _plan(int(user_payload["episode_number"]))
        else:
            choice = user_payload["reader_choice"]
            payload = _content(
                int(user_payload["plan"]["episode_number"]),
                str(choice["reader_choice_id"]), str(choice["choice_text"]),
            )
        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self.provider_name, advertised_model=self.model,
            cost_class=self.cost_class, latency_seconds=0.12, retry_count=0,
            payload=validated.model_dump(), request_id=request_id, success=True,
            usage=ProviderUsage(input_tokens=20, output_tokens=30, total_tokens=50),
        )


def _once(path: str, provider: _Provider, barrier: threading.Barrier,
          key: str, choice_id: str):
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _conn(path)
    try:
        request = GenerationRequest(
            world=_world(), episode_type=EpisodeType.PERSONAL_BRANCH,
            reader_id="reader-1", reader_choice_id=choice_id, idempotency_key=key,
        )
        barrier.wait(timeout=5)
        return generate_personal_branch(
            conn, provider, request, max_retries=0,
            world_id="world-1", canon_checkpoint_id="checkpoint-1",
            prior_episode_id="ep-1", idempotency_wait_timeout=5.0,
            idempotency_poll_interval=0.01,
        )
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def _parallel(path: str, provider: _Provider, calls: list[tuple[str, str]]):
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_once, path, provider, barrier, key, choice)
                   for key, choice in calls]
        return [future.result(timeout=15) for future in futures]


def test_same_key_waits_inside_service_and_replays(db_path):
    provider = _Provider()
    results = _parallel(db_path, provider, [("same-key", "choice-1")] * 2)
    assert all(result.succeeded for result in results), [r.error for r in results]
    assert results[0].episode_id == results[1].episode_id
    assert (provider.plan_calls, provider.content_calls) == (1, 1)

    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM episodes WHERE episode_type='personal_branch') episodes, "
            "(SELECT COUNT(*) FROM branches) branches, "
            "(SELECT COUNT(*) FROM branch_generation_requests WHERE status='completed') completed, "
            "(SELECT COUNT(*) FROM branch_generation_requests WHERE status='pending') pending"
        ).fetchone()
        assert tuple(row) == (1, 1, 1, 0)
    finally:
        conn.close()


def test_different_keys_both_succeed_with_distinct_reserved_numbers(db_path):
    conn = _conn(db_path)
    now = "2026-07-21T00:00:00Z"
    conn.executemany(
        "INSERT INTO reader_choices(id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, 'reader-1', 'ep-1', ?, ?)",
        [("choice-a", "Inspect east", now), ("choice-b", "Inspect west", now)],
    )
    conn.commit()
    conn.close()

    provider = _Provider()
    results = _parallel(db_path, provider, [("key-a", "choice-a"), ("key-b", "choice-b")])
    assert all(result.succeeded for result in results), [r.error for r in results]
    assert results[0].episode_id != results[1].episode_id
    assert (provider.plan_calls, provider.content_calls) == (2, 2)

    conn = _conn(db_path)
    try:
        numbers = [row[0] for row in conn.execute(
            "SELECT episode_number FROM episodes WHERE episode_type='personal_branch' "
            "ORDER BY episode_number"
        )]
        assert numbers == [1, 2]
        states = list(conn.execute(
            "SELECT status, COUNT(*) FROM branch_generation_requests GROUP BY status"
        ))
        assert [tuple(row) for row in states] == [("completed", 2)]
        next_number = conn.execute(
            "SELECT next_episode_number FROM episode_number_sequences "
            "WHERE world_id='world-1' AND episode_type='personal_branch'"
        ).fetchone()[0]
        assert next_number == 3
    finally:
        conn.close()
