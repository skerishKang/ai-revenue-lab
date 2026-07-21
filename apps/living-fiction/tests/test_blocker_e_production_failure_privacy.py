"""Production-path regression tests for Blocker E durable failures."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time

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

SECRET = "PRIVATE_READER_TEXT__DO_NOT_PERSIST"


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
        VALUES ('reader-e', 'Reader', 'active', '{now}');
        INSERT INTO worlds(
            id, version, premise, genre, world_rules, canonical_timeline,
            unresolved_global_questions, created_at
        ) VALUES ('world-e', '1.0', 'Synthetic', 'urban_mystery', '[]', '[]', '[]', '{now}');
        INSERT INTO locations(id, world_id, name, connected_locations, created_at)
        VALUES ('loc-e', 'world-e', 'Station', '[]', '{now}');
        INSERT INTO characters(
            id, world_id, canonical_name, role, traits, age_category, status,
            location_id, created_at
        ) VALUES ('char-e', 'world-e', 'Mira', 'protagonist', '[]', 'adult',
                  'active', 'loc-e', '{now}');
        INSERT INTO canon_snapshots(
            id, world_id, version, episode_number, accepted, world_state_json,
            character_states_json, location_states_json, clue_states_json,
            unresolved_threads_json, created_at
        ) VALUES ('snap-e', 'world-e', '1.0', 1, 1, '{{}}', '{{}}', '{{}}', '{{}}', '[]', '{now}');
        INSERT INTO episodes(
            id, world_id, episode_type, episode_number, title, synopsis,
            scene_list_json, character_ids_json, location_ids_json, prose_json,
            clue_refs_json, world_state_deltas_json, unresolved_threads_json,
            next_choice_options_json, content_classification, review_state, created_at
        ) VALUES ('ep-e', 'world-e', 'canon', 1, 'Opening', 'Opening', '[]', '[]',
                  '[]', '[]', '[]', '{{}}', '[]', '[]', 'adult', 'published', '{now}');
        INSERT INTO canon_checkpoints(id, canon_snapshot_id, episode_number, label, created_at)
        VALUES ('checkpoint-e', 'snap-e', 1, 'opening', '{now}');
        INSERT INTO reader_choices(id, reader_id, canon_episode_id, choice_text, submitted_at)
        VALUES ('choice-e', 'reader-e', 'ep-e', 'Inspect carefully', '{now}');
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
        world_id="world-e",
        version="1.0",
        premise="Caller content is not authoritative",
        characters=[
            CharacterRef(
                character_id="char-e",
                canonical_name="Mira",
                role="protagonist",
                location_id="loc-e",
            )
        ],
        locations=[LocationRef(location_id="loc-e", name="Station")],
    )


class _FailingPlanProvider:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "failure-contract-provider"

    @property
    def model(self) -> str:
        return "failure-contract-model"

    @property
    def cost_class(self) -> CostClass:
        return CostClass.FREE

    def generate_structured(
        self, *, task_name, system_prompt, user_payload, response_schema, request_id
    ):
        del system_prompt
        assert task_name == "episode_plan"
        self.calls += 1
        if self.mode == "exception":
            time.sleep(0.03)
            raise TimeoutError(f"provider saw {SECRET}")

        payload = {
            "plan_version": "v1",
            "world_id": "world-e",
            "world_version": "1.0",
            "episode_type": "personal_branch",
            "episode_number": int(user_payload["episode_number"]),
            "title": "Invalid branch",
            "synopsis": "Schema-valid but semantically invalid",
            "scenes": [{
                "scene_id": "scene-e",
                "title": "Inspection",
                "purpose": "Apply choice",
                "participating_character_ids": [f"unknown-{SECRET}"],
                "location_id": "loc-e",
            }],
            "participating_character_ids": [f"unknown-{SECRET}"],
            "location_ids": ["loc-e"],
            "clue_refs": [],
            "next_choice_options": ["Continue"],
            "content_classification": "adult",
        }
        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self.provider_name,
            advertised_model=self.model,
            cost_class=self.cost_class,
            latency_seconds=0.01,
            retry_count=0,
            payload=validated.model_dump(),
            request_id=request_id,
            success=True,
            usage=ProviderUsage(input_tokens=7, output_tokens=11, total_tokens=18),
        )


def _generate(conn, provider, key: str, retries: int):
    from app.pipeline.service import GenerationRequest, generate_personal_branch

    return generate_personal_branch(
        conn,
        provider,
        GenerationRequest(
            world=_world(),
            episode_type=EpisodeType.PERSONAL_BRANCH,
            reader_id="reader-e",
            reader_choice_id="choice-e",
            idempotency_key=key,
        ),
        max_retries=retries,
        world_id="world-e",
        canon_checkpoint_id="checkpoint-e",
        prior_episode_id="ep-e",
    )


def _messages(conn: sqlite3.Connection) -> list[str]:
    result: list[str] = []
    for table in ("generation_attempts", "generation_runs", "branch_generation_requests"):
        result.extend(
            row["error_message"]
            for row in conn.execute(
                f"SELECT error_message FROM {table} WHERE error_message IS NOT NULL"
            )
        )
    return result


def test_exception_latency_and_raw_text_are_verified_through_service(db_path):
    conn = _conn(db_path)
    provider = _FailingPlanProvider("exception")
    try:
        result = _generate(conn, provider, "exception-key", 1)
        assert not result.succeeded
        assert provider.calls == 2

        attempts = conn.execute(
            "SELECT latency_seconds, error_category FROM generation_attempts "
            "ORDER BY attempt_number"
        ).fetchall()
        assert len(attempts) == 2
        assert all(row["latency_seconds"] >= 0.02 for row in attempts)
        assert all(row["error_category"] == "timeout" for row in attempts)

        run = conn.execute(
            "SELECT latency_seconds, success, error_category FROM generation_runs"
        ).fetchone()
        assert run["success"] == 0
        assert run["error_category"] == "timeout"
        assert run["latency_seconds"] >= sum(r["latency_seconds"] for r in attempts) - 0.01

        messages = _messages(conn)
        assert messages
        assert all(SECRET not in message for message in messages)
        assert all("provider request timed out" in message for message in messages)
    finally:
        conn.close()


class _ContinuityViolationProvider:
    """Provider that generates valid plan+content but with a continuity violation.

    The content removes an injury without evidence, triggering
    continuity validation failure through generate_personal_branch().
    """

    def __init__(self):
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "continuity-violation-provider"

    @property
    def model(self) -> str:
        return "continuity-violation-model"

    @property
    def cost_class(self) -> CostClass:
        return CostClass.FREE

    def generate_structured(
        self, *, task_name, system_prompt, user_payload, response_schema, request_id
    ):
        del system_prompt
        self.calls += 1

        if task_name == "episode_plan":
            payload = {
                "plan_version": "v1",
                "world_id": "world-e",
                "world_version": "1.0",
                "episode_type": "personal_branch",
                "episode_number": int(user_payload["episode_number"]),
                "title": "Branch with silent injury removal",
                "synopsis": "Valid plan but content will violate continuity",
                "scenes": [{
                    "scene_id": "scene-e",
                    "title": "Hospital Visit",
                    "purpose": "Mira visits the hospital",
                    "participating_character_ids": ["char-e"],
                    "location_id": "loc-e",
                }],
                "participating_character_ids": ["char-e"],
                "location_ids": ["loc-e"],
                "clue_refs": [],
                "next_choice_options": ["Continue"],
                "content_classification": "adult",
            }
        else:
            # Content task — produce content that silently removes an injury
            # without evidence (continuity violation)
            payload = {
                "content_version": "v1",
                "world_id": "world-e",
                "episode_type": "personal_branch",
                "episode_number": int(user_payload.get("episode_number", 1)),
                "title": "Branch with silent injury removal",
                "synopsis": "Content removes injury without evidence",
                "scenes": [{
                    "scene_id": "scene-e",
                    "title": "Hospital Visit",
                    "purpose": "Mira visits the hospital",
                    "participating_character_ids": ["char-e"],
                    "location_id": "loc-e",
                }],
                "prose": [{
                    "scene_id": "scene-e",
                    "paragraphs": ["Mira felt much better after visiting the hospital."],
                }],
                "clue_refs": [],
                "world_state_delta": {
                    "character_knowledge_added": {},
                    "character_knowledge_sources": {},
                    "character_location_changed": {},
                    "character_movement_explanations": {},
                    "character_injuries_added": {},
                    "character_injuries_removed": {"char-e": ["broken_arm"]},
                    "character_injury_removal_evidence": {},
                    "character_possessions_added": {},
                    "character_possessions_removed": {},
                    "character_possession_removal_evidence": {},
                    "character_relationship_changes": {},
                    "character_relationship_evidence": {},
                    "clues_introduced": [],
                    "clues_resolved": [],
                    "canon_clue_resolution_explanations": {},
                    "unresolved_threads": [],
                    "thread_resolutions": {},
                    "branch_only_facts": [],
                },
                "applied_reader_input": {
                    "reader_choice_id": "choice-e",
                    "choice_text": "Inspect carefully",
                    "applied_evidence": "Mira went to the hospital and felt better.",
                },
                "unresolved_threads": [],
                "next_choice_options": ["Continue"],
                "content_classification": "adult",
                "review_state": "pending_review",
            }

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider=self.provider_name,
            advertised_model=self.model,
            cost_class=self.cost_class,
            latency_seconds=0.01,
            retry_count=0,
            payload=validated.model_dump(),
            request_id=request_id,
            success=True,
            usage=ProviderUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        )


def test_continuity_violation_fails_through_service(db_path):
    """Continuity failure (silent injury removal) returns succeeded=False
    through generate_personal_branch() with proper error category.

    Verifies:
    - GenerationResult.succeeded is False
    - Error category is continuity_validation_failed
    - Idempotency request transitions to 'failed'
    - No episode or branch created
    - Durable error does not contain private text
    """
    # First, seed the prior episode with an injury in its world_state_delta
    import json as _json
    seed_conn = _conn(db_path)
    try:
        prior_delta = {"character_injuries_added": {"char-e": ["broken_arm"]}}
        seed_conn.execute(
            "UPDATE episodes SET world_state_deltas_json = ? WHERE id = 'ep-e'",
            (_json.dumps(prior_delta),),
        )
        seed_conn.commit()
    finally:
        seed_conn.close()

    conn = _conn(db_path)
    provider = _ContinuityViolationProvider()
    try:
        result = _generate(conn, provider, "continuity-key", 0)

        # 1. GenerationResult returns succeeded=False
        assert not result.succeeded
        assert result.episode_id is None

        # 2. Error category is continuity_validation_failed
        # Query the LAST generation run (content run), not the first (plan run)
        run = conn.execute(
            "SELECT success, validation_status, error_category, error_message "
            "FROM generation_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert run["success"] == 0
        assert run["validation_status"] == "validation_failed"
        assert run["error_category"] == "continuity_validation_failed"

        # 3. Idempotency request transitions to 'failed'
        request = conn.execute(
            "SELECT status, error_message FROM branch_generation_requests"
        ).fetchone()
        assert request["status"] == "failed"

        # 4. No episode or branch created
        episodes = conn.execute(
            "SELECT COUNT(*) as cnt FROM episodes WHERE episode_type = 'personal_branch'"
        ).fetchone()
        assert episodes["cnt"] == 0
        branches = conn.execute(
            "SELECT COUNT(*) as cnt FROM branches"
        ).fetchone()
        assert branches["cnt"] == 0

        # 5. Durable error does not contain private text
        messages = _messages(conn)
        assert messages
        assert all(SECRET not in message for message in messages)

    finally:
        conn.close()


def test_semantic_failure_persists_static_category_not_validator_detail(db_path):
    conn = _conn(db_path)
    try:
        result = _generate(conn, _FailingPlanProvider("invalid"), "invalid-key", 0)
        assert not result.succeeded
        assert SECRET not in (result.error or "")

        run = conn.execute(
            "SELECT success, validation_status, error_category, error_message "
            "FROM generation_runs"
        ).fetchone()
        assert run["success"] == 0
        assert run["validation_status"] == "validation_failed"
        assert run["error_category"] == "plan_validation_failed"
        assert run["error_message"] == "plan_validation_failed: plan validation failed"

        request = conn.execute(
            "SELECT status, error_message FROM branch_generation_requests"
        ).fetchone()
        assert request["status"] == "failed"
        assert request["error_message"] == "plan_validation_failed: plan validation failed"
        assert SECRET not in " ".join(_messages(conn))
    finally:
        conn.close()
