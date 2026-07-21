"""Blocker A â€” production service concurrency contracts.

These tests intentionally make exactly one service call per concurrent caller.
They reject client-owned polling/retry workarounds and require the service plus
SQLite persistence layer to provide idempotent replay and distinct durable
episode-number reservations.
"""
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
from app.domain.models import (
    CharacterRef,
    LocationRef,
    ProviderResult,
    ProviderUsage,
    WorldState,
)


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _seed_world(conn: sqlite3.Connection) -> None:
    now = "2026-07-21T00:00:00Z"
    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at) "
        "VALUES ('reader-1', 'Reader', 'active', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO worlds "
        "(id, version, premise, genre, world_rules, canonical_timeline, "
        "unresolved_global_questions, created_at) "
        "VALUES ('world-1', '1.0', 'Synthetic test world', 'urban_mystery', "
        "'[]', '[]', '[]', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO locations "
        "(id, world_id, name, connected_locations, created_at) "
        "VALUES ('loc-1', 'world-1', 'Station', '[]', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO characters "
        "(id, world_id, canonical_name, role, traits, age_category, status, "
        "location_id, created_at) "
        "VALUES ('char-1', 'world-1', 'Mira', 'protagonist', '[]', 'adult', "
        "'active', 'loc-1', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO canon_snapshots "
        "(id, world_id, version, episode_number, accepted, world_state_json, "
        "character_states_json, location_states_json, clue_states_json, "
        "unresolved_threads_json, created_at) "
        "VALUES ('snap-1', 'world-1', '1.0', 1, 1, '{}', '{}', '{}', '{}', "
        "'[]', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO episodes "
        "(id, world_id, episode_type, episode_number, title, synopsis, "
        "scene_list_json, character_ids_json, location_ids_json, prose_json, "
        "clue_refs_json, world_state_deltas_json, unresolved_threads_json, "
        "next_choice_options_json, content_classification, review_state, created_at) "
        "VALUES ('ep-1', 'world-1', 'canon', 1, 'Opening', 'Opening', '[]', "
        "'[]', '[]', '[]', '[]', '{}', '[]', '[]', 'adult', 'published', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO canon_checkpoints "
        "(id, canon_snapshot_id, episode_number, label, created_at) "
        "VALUES ('checkpoint-1', 'snap-1', 1, 'opening', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO reader_choices "
        "(id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES ('choice-1', 'reader-1', 'ep-1', 'Inspect the station carefully', ?)",
        (now,),
    )
    conn.commit()


def _world() -> WorldState:
    return WorldState(
        world_id="world-1",
        version="1.0",
        premise="Caller value is not authoritative",
        characters=[
            CharacterRef(
                character_id="char-1",
                canonical_name="Mira",
                role="protagonist",
                location_id="loc-1",
            )
        ],
        locations=[LocationRef(location_id="loc-1", name="Station")],
    )


def _plan_payload(episode_number: int) -> dict:
    return {
        "plan_version": "v1",
        "world_id": "world-1",
        "world_version": "1.0",
        "episode_type": "personal_branch",
        "episode_number": episode_number,
        "title": f"Branch {episode_number}",
        "synopsis": "The reader-directed investigation continues.",
        "scenes": [
            {
                "scene_id": f"scene-{episode_number}",
                "title": "Inspection",
                "purpose": "Apply the stored reader choice",
                "participating_character_ids": ["char-1"],
                "location_id": "loc-1",
            }
        ],
        "participating_character_ids": ["char-1"],
        "location_ids": ["loc-1"],
        "clue_refs": [],
        "next_choice_options": ["Continue cautiously"],
        "content_classification": "adult",
    }


def _content_payload(episode_number: int, choice_id: str, choice_text: str) -> dict:
    scene_id = f"scene-{episode_number}"
    return {
        "content_version": "v1",
        "world_id": "world-1",
        "episode_type": "personal_branch",
        "episode_number": episode_number,
        "title": f"Branch {episode_number}",
        "synopsis": "The reader-directed investigation continues.",
        "scenes": [
            {
                "scene_id": scene_id,
                "title": "Inspection",
                "purpose": "Apply the stored reader choice",
                "participating_character_ids": ["char-1"],
                "location_id": "loc-1",
            }
        ],
        "prose": [
            {
                "scene_id": scene_id,
                "paragraphs": [
                    f"Mira follows the instruction to {choice_text.lower()} and changes her route."
                ],
            }
        ],
        "clue_refs": [],
        "world_state_delta": {
            "character_knowledge_added": {},
            "character_knowledge_sources": {},
            "character_location_changed": {},
            "character_movement_explanations": {},
            "character_injuries_added": {},
            "character_injuries_removed": {},
            "character_possessions_added": {},
            "character_possessions_removed": {},
            "character_relationship_changes": {},
            "clues_introduced": [],
            "clues_resolved": [],
            "canon_clue_resolution_explanations": {},
            "unresolved_threads": [],
            "thread_resolutions": {},
            "branch_only_facts": [f"reader-directed-route-{episode_number}"],
        },
        "applied_reader_input": {
            "reader_choice_id": choice_id,
            "choice_text": choice_text,
            "comment": None,
            "applied_evidence": f"The scene explicitly follows: {choice_text}",
        },
        "unresolved_threads": [],
        "next_choice_options": ["Continue cautiously"],
        "content_classification": "adult",
    }


class _BlockingCountingProvider:
    """Thread-safe provider whose latency keeps the first claim pending."""

    def __init__(self, delay: float = 0.12):
        self._delay = delay
        self._lock = threading.Lock()
        self.plan_calls = 0
        self.content_calls = 0

    @property
    def provider_name(self) -> str:
        return "concurrency-contract"

    @property
    def model(self) -> str:
        return "concurrency-model"

    @property
    def cost_class(self) -> CostClass:
        return CostClass.FREE

    def generate_structured(
        self, *, task_name, system_prompt, user_payload, response_schema, request_id
    ) -> ProviderResult:
        del system_prompt
        with self._lock:
            if task_name == "episode_plan":
                self.plan_calls += 1
            elif task_name == "episode_content":
                self.content_calls += 1
            else:
                raise AssertionError(f"unexpected task: {task_name}")
        time.sleep(self._delay)

        if task_name == "episode_plan":
            payload = _plan_payload(int(user_payload["episode_number"]))
        else:
            choice = user_payload["reader_choice"]
            payload = _content_payload(
                int(user_payload["plan"]["episode_number"]),
                str(choice["reader_choice_id"]),
                str(choice["choice_text"]),
            )

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self.provider_name,
            advertised_model=self.model,
            cost_class=self.cost_class,
            latency_seconds=self._delay,
            retry_count=0,
            payload=validated.model_dump(),
            request_id=request_id,
            success=True,
            usage=ProviderUsage(input_tokens=20, output_tokens=30, total_tokens=50),
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


def _call_once(
    db_path: str,
    provider: _BlockingCountingProvider,
    *,
    barrier: threading.Barrier,
    key: str,
    choice_id: str,
):
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    conn = _make_conn(db_path)
    try:
        request = GenerationRequest(
            world=_world(),
            episode_type=EpisodeType.PERSONAL_BRANCH,
            reader_id="reader-1",
            reader_choice_id=choice_id,
            idempotency_key=key,
        )
        barrier.wait(timeout=5)
        return generate_personal_branch(
            conn,
            provider,
            request,
            max_retries=0,
            world_id="world-1",
            canon_checkpoint_id="checkpoint-1",
            prior_episode_id="ep-1",
            idempotency_wait_timeout=5.0,
            idempotency_poll_interval=0.01,
        )
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def test_concurrent_same_key_waits_inside_service_and_replays(db_path):
    """Two callers each invoke the service once and receive the same result."""
    provider = _BlockingCountingProvider()
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _call_once,
            db_path,
            provider,
            barrier=barrier,
            key="same-key",
            choice_id="choice-1",
        )
        second = executor.submit(
            _call_once,
            db_path,
            provider,
            barrier=barrier,
            key="same-key",
            choice_id="choice-1",
        )
        results = [first.result(timeout=15), second.result(timeout=15)]

    assert all(result.succeeded for result in results), [r.error for r in results]
    assert results[0].episode_id == results[1].episode_id
    assert provider.plan_calls == 1
    assert provider.content_calls == 1

    conn = _make_conn(db_path)
    try:
        counts = conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM episodes WHERE episode_type='personal_branch') AS episodes, "
            "(SELECT COUNT(*) FROM branches) AS branches, "
            "(SELECT COUNT(*) FROM branch_generation_requests WHERE status='completed') AS completed, "
            "(SELECT COUNT(*) FROM branch_generation_requests WHERE status='pending') AS pending"
        ).fetchone()
        assert dict(counts) == {
            "episodes": 1,
            "branches": 1,
            "completed": 1,
            "pending": 0,
        }
    finally:
        conn.close()


def test_concurrent_different_keys_both_succeed_with_distinct_reserved_numbers(db_path):
    """Independent requests must both succeed; one-success-only is unacceptable."""
    conn = _make_conn(db_path)
    now = "2026-07-21T00:00:00Z"
    conn.executemany(
        "INSERT INTO reader_choices "
        "(id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, 'reader-1', 'ep-1', ?, ?)",
        [
            ("choice-a", "Inspect the east platform", now),
            ("choice-b", "Inspect the west platform", now),
        ],
    )
    conn.commit()
    conn.close()

    provider = _BlockingCountingProvider()
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _call_once,
            db_path,
            provider,
            barrier=barrier,
            key="key-a",
            choice_id="choice-a",
        )
        second = executor.submit(
            _call_once,
            db_path,
            provider,
            barrier=barrier,
            key="key-b",
           ÚÚXÙWÚYH˜ÚÚXÙKXˆ‹ˆ
Bˆ™\İ[ÈHÙš\œİœ™\İ[
[Y[İ]LMJKÙXÛÛ™œ™\İ[
[Y[İ]LMJWB‚ˆ\ÜÙ\[
™\İ[œİXØÙYYY›Üˆ™\İ[[ˆ™\İ[ÊKÜ‹™\œ›Üˆ›Üˆˆ[ˆ™\İ[×Bˆ\ÜÙ\™\İ[ÖÌK™\\ÛÙWÚYOH™\İ[ÖÌWK™\\ÛÙWÚYˆ\ÜÙ\›İšY\‹œ[—ØØ[ÈOH‚ˆ\ÜÙ\›İšY\‹˜ÛÛ[ØØ[ÈOH‚‚ˆÛÛ›ˆHÛXZÙWØÛÛ›Š—Ü]
BˆN‚ˆ›İÜÈHÛÛ›‹™^Xİ]Jˆ”ÑSPÕY\\ÛÙWÛ[X™\ˆ”“ÓH\\ÛÙ\È‚ˆ•ÒT‘H\\ÛÙWİ\OIÜ\œÛÛ˜[Øœ˜[˜Ú	ÈÔ‘Tˆ–H\\ÛÙWÛ[X™\ˆ‚ˆ
K™™]Ú[

Bˆ\ÜÙ\Ü›İÖÈ™\\ÛÙWÛ[X™\ˆ—H›Üˆ›İÈ[ˆ›İÜ×HOHÌK—Bˆ\ÜÙ\[ŠÜ›İÖÈšY—H›Üˆ›İÈ[ˆ›İÜßJHOH‚‚ˆİ]\ÈHÛÛ›‹™^Xİ]Jˆ”ÑSPÕİ]\ËÓÕS•

ŠHTÈÛİ[”“ÓHœ˜[˜ÚÙÙ[™\˜][Û—Ü™\]Y\İÈ‚ˆ‘Ô“ÕT–Hİ]\ÈÔ‘Tˆ–Hİ]\È‚ˆ
K™™]Ú[

Bˆ\ÜÙ\Ê›İÖÈœİ]\È—K›İÖÈ˜Ûİ[—JH›Üˆ›İÈ[ˆİ]\×HOHÊ˜ÛÛ\]Y‹ŠWB‚ˆÙ\]Y[˜ÙHHÛÛ›‹™^Xİ]Jˆ”ÑSPÕ™^Ù\\ÛÙWÛ[X™\ˆ”“ÓH\\ÛÙWÛ[X™\—ÜÙ\]Y[˜Ù\È‚ˆ•ÒT‘HÛÜ›ÚYIİÛÜ›LIÈS‘\\ÛÙWİ\OIÜ\œÛÛ˜[Øœ˜[˜Ú	È‚ˆ
K™™]ÚÛ™J
Bˆ\ÜÙ\Ù\]Y[˜ÙVÈ›™^Ù\\ÛÙWÛ[X™\ˆ—HOHÂˆš[˜[N‚ˆÛÛ›‹˜ÛÜÙJ
B