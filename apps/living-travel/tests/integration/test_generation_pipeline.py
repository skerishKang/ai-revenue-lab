"""Integration tests for generation pipeline."""

import json
from pathlib import Path

import pytest

from app.ai.mock import MockProvider
from app.db import apply_migrations, get_connection
from app.domain.enums import EditionGenerationStatus
from app.edition_repository import get_edition_by_id, get_editions_by_traveler
from app.feedback_repository import create_feedback, mark_feedback_applied
from app.generation_run_repository import count_generation_runs_by_edition
from app.pipeline.errors import PipelineError
from app.pipeline.service import GenerationService
from app.source_repository import create_source
from app.traveler_repository import create_traveler

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_SOURCE_IDS = {"src_busan_tourism", "src_gukje_market", "src_haegyeolri"}

FIRST_PLAN = {
    "plan_version": "1.0",
    "language": "ko",
    "central_theme": "부산 동네 산책",
    "sections": [
        {"section_id": "sec_morning_gukje", "title": "국제시장 근처", "description": "아침 산책"},
        {"section_id": "sec_haegyeolri", "title": "합성동", "description": "로컬 카페"},
        {"section_id": "sec_practical", "title": "실용 정보", "description": "날씨와 이동"},
    ],
}

SECOND_PLAN = {
    "plan_version": "1.0",
    "language": "ko",
    "central_theme": "부산 조용한 로컬",
    "sections": [
        {"section_id": "sec_quiet_morning", "title": "조용한 아침", "description": "아침 산책"},
        {"section_id": "sec_local_food", "title": "로컬 밥상", "description": "음식"},
        {"section_id": "sec_low_effort", "title": "적은 이동", "description": "코스"},
    ],
}

EMPTY_PLAN = {
    "plan_version": "1.0",
    "language": "ko",
    "central_theme": "부산",
    "sections": [],
}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


@pytest.fixture
def busan_sources(conn):
    sources = []
    for src in _load_fixture("busan_solo_traveler.json")["sources"]:
        s = create_source(
            conn,
            source_url=src["source_url"],
            publisher=src["publisher"],
            source_type=src["source_type"],
            destination=src["destination"],
            locality=src.get("locality", ""),
            category=src["category"],
            claims=src.get("claims", []),
            confidence=src.get("confidence", "approximate"),
            publication_date=src.get("publication_date", ""),
            access_date=src.get("access_date", ""),
        )
        sources.append(s)
    return sources


@pytest.fixture
def traveler(conn):
    prefs = _load_fixture("busan_solo_traveler.json")["traveler"]
    prefs["display_name"] = "Busan Solo Tester"
    return create_traveler(conn, **prefs)


@pytest.fixture
def source_dicts(busan_sources):
    return [
        {"source_id": s.id, "publisher": s.publisher, "category": s.category}
        for s in busan_sources
    ]


class TestFirstEditionGeneration:
    def test_generates_pending_review(self, conn, traveler, source_dicts):
        draft_fixture = _load_fixture("source_bundle.json")["first_edition_fixture"]

        provider = MockProvider(
            task_payloads={
                "editorial_plan": FIRST_PLAN,
                "edition_draft": draft_fixture,
            }
        )
        service = GenerationService(conn, provider)

        content = service.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산", "interests": ["food"]},
            source_items=source_dicts,
            source_ids=FIXTURE_SOURCE_IDS,
        )

        assert content.publication_title
        assert len(content.sections) == 3

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 1
        assert editions[0].generation_status == EditionGenerationStatus.pending_review

        runs = count_generation_runs_by_edition(conn, editions[0].id)
        assert runs == 2

    def test_provider_error_triggers_retry(self, conn, traveler, source_dicts):
        draft_fixture = _load_fixture("source_bundle.json")["first_edition_fixture"]

        provider = MockProvider(
            responses=[
                EMPTY_PLAN,
                FIRST_PLAN,
                draft_fixture,
            ]
        )
        service = GenerationService(conn, provider)

        content = service.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
            source_ids=FIXTURE_SOURCE_IDS,
        )
        assert content.publication_title


class TestSecondEditionGeneration:
    def test_feedback_drives_material_change(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]

        provider = MockProvider(
            task_payloads={
                "editorial_plan": FIRST_PLAN,
                "edition_draft": first_draft,
            }
        )
        service = GenerationService(conn, provider)

        first_content = service.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
            source_ids=FIXTURE_SOURCE_IDS,
        )

        fb = create_feedback(
            conn,
            traveler_id=traveler.id,
            edition_id=get_editions_by_traveler(conn, traveler.id)[0].id,
            direction_choices=["quieter_places", "slower_pace", "more_local_food"],
            free_text="더 조용하고 느린 코스로",
        )

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": SECOND_PLAN,
                "edition_draft": second_draft,
            }
        )
        service2 = GenerationService(conn, provider2)

        second_content = service2.generate_second_edition(
            traveler_id=traveler.id,
            prior_edition=first_content,
            traveler_preferences={"destination": "부산", "pace": "slow"},
            source_items=source_dicts,
            source_ids=FIXTURE_SOURCE_IDS,
        )

        assert second_content.publication_title != first_content.publication_title
        assert len(second_content.applied_feedback) > 0

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 2

        from app.feedback_repository import get_unapplied_feedback_for_traveler
        unapplied = get_unapplied_feedback_for_traveler(conn, traveler.id)
        assert len(unapplied) == 0


class TestValidationRejection:
    def test_duplicate_section_ids_rejected(self, conn, traveler, source_dicts):
        bad_plan = {
            "plan_version": "1.0",
            "language": "ko",
            "central_theme": "X",
            "sections": [
                {"section_id": "s1", "title": "T", "description": "D"},
            ],
        }
        bad_draft = _load_fixture("adversarial_payloads.json")["adversarial_duplicate_ids"]
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bad_plan,
                "edition_draft": bad_draft,
            }
        )
        service = GenerationService(conn, provider)

        with pytest.raises((PipelineError, Exception)):
            service.generate_first_edition(
                traveler_id=traveler.id,
                input_id=None,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
                source_ids=FIXTURE_SOURCE_IDS,
            )


class TestMarkupRejection:
    def test_unsafe_content_raises(self, conn, traveler, source_dicts):
        bad_plan = {
            "plan_version": "1.0",
            "language": "ko",
            "central_theme": "X",
            "sections": [
                {"section_id": "s1", "title": "T", "description": "D"},
            ],
        }
        bad_draft = _load_fixture("adversarial_payloads.json")["adversarial_markup"]
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bad_plan,
                "edition_draft": bad_draft,
            }
        )
        service = GenerationService(conn, provider)

        with pytest.raises((PipelineError, Exception)):
            service.generate_first_edition(
                traveler_id=traveler.id,
                input_id=None,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
                source_ids=FIXTURE_SOURCE_IDS,
            )
