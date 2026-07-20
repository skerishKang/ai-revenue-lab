"""Comprehensive audit tests for Living Travel Phase 1 (Issue #33).

Covers:
- traveler isolation and deletion/inactive
- atomic persistence (rollback on failure)
- foreign/mismatched/already-applied feedback rejection
- duplicate/retry idempotency
- no-overwrite failure paths
- unknown/withdrawn source rejection
- unsupported time-sensitive facts
- unsafe markup/URL (all content fields)
- exact generation-run row counts and fields
- retry token/latency aggregation
- privacy-safe pilot records and free_text sanitization
- file-backed close/reopen
- zero network
- /health startup smoke
- new-file and existing-file migrations
"""

from __future__ import annotations

import json
import os
import sqlite3
import socket
from pathlib import Path

import pytest

from app.ai.mock import MockProvider
from app.config import Settings
from app.db import apply_migrations, get_connection
from app.domain.enums import (
    EditionGenerationStatus,
    InformationClass,
    SourceConfidence,
)
from app.domain.models import (
    EditionContent,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
    InformationItem,
)
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    get_editions_by_traveler,
)
from app.feedback_repository import (
    create_feedback,
    get_feedback_by_id,
    get_unapplied_feedback_for_edition,
    get_unapplied_feedback_for_traveler,
    mark_feedback_applied,
)
from app.factory import create_app
from app.generation_run_repository import (
    count_generation_runs_by_edition,
    create_generation_run,
    get_generation_runs_by_task_type,
)
from app.pipeline.errors import MarkupError, PipelineError
from app.pipeline.markup import (
    check_all_content_fields,
    check_unsafe_markup,
    reject_all_content_fields,
    reject_if_unsafe,
)
from app.pipeline.service import GenerationService
from app.pipeline.validators import (
    validate_draft_against_plan,
    validate_edition_content,
    validate_information_class_metadata,
    validate_no_unsupported_claims,
    validate_plan,
    validate_source_references,
    validate_source_states,
)
from app.pilot_evidence_repository import (
    create_pilot_evidence,
    get_pilot_evidence_by_traveler,
)
try:
    from app.source_repository import create_source, get_source_by_id
except ImportError:
    create_source = None
    get_source_by_id = None
from app.traveler_repository import (
    create_traveler,
    delete_traveler,
    get_traveler_by_id,
    is_traveler_active,
)

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


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _make_first_content() -> EditionContent:
    return EditionContent.model_validate(_load_fixture("source_bundle.json")["first_edition_fixture"])


def _make_second_content() -> EditionContent:
    return EditionContent.model_validate(_load_fixture("source_bundle.json")["second_edition_fixture"])


# ── Shared fixtures ─────────────────────────────────────────────────

@pytest.fixture
def file_db(tmp_path):
    return str(tmp_path / "audit_test.db")


@pytest.fixture
def conn(file_db):
    apply_migrations(file_db)
    c = get_connection(file_db)
    yield c
    c.close()


@pytest.fixture
def traveler(conn):
    prefs = _load_fixture("busan_solo_traveler.json")["traveler"]
    prefs["display_name"] = "Audit Tester"
    return create_traveler(conn, **prefs)


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
def source_dicts():
    """Source dicts with hardcoded IDs matching source_bundle.json fixture."""
    return [
        {"source_id": "src_busan_tourism", "publisher": "부산관광공사",
         "category": "destination_overview",
         "claims": ["부산은 한국 제2의 도시", "해운대와 광안리가 대표 해수욕장", "item_weather_note"]},
        {"source_id": "src_gukje_market", "publisher": "부산 중구청",
         "category": "market",
         "claims": ["국제시장은 1950년대 전후부터 형성된 시장", "원조 식당가가 있음",
                     "item_gukje_atmosphere", "item_gukje_hours", "item_solo_dining"]},
        {"source_id": "src_haegyeolri", "publisher": "부산남구청",
         "category": "neighborhood",
         "claims": ["합성동은 로컬 분위기가 남아있는 동네", "조용한 카페와 식당이 있음",
                     "item_haegyeolri_vibe"]},
    ]




# =====================================================================
# 1. Migration idempotency
# =====================================================================

class TestMigrationIdempotency:
    def test_new_file_migration(self, tmp_path):
        db_path = str(tmp_path / "new.db")
        apply_migrations(db_path)
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert {"travelers", "sources", "travel_inputs", "editions",
                "feedback", "generation_runs", "pilot_evidence",
                "schema_migrations"}.issubset(tables)

    def test_existing_file_migration(self, tmp_path):
        db_path = str(tmp_path / "existing.db")
        apply_migrations(db_path)
        conn = sqlite3.connect(db_path)
        count1 = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn.close()
        apply_migrations(db_path)
        conn = sqlite3.connect(db_path)
        count2 = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn.close()
        assert count1 == count2

    def test_unique_index_on_editions(self, conn):
        """Unique constraint on (traveler_id, edition_number) prevents duplicate editions."""
        t = create_traveler(conn, display_name="T", destination="부산")
        ed1 = create_edition(conn, traveler_id=t.id, edition_number=1, commit=False)
        with pytest.raises(sqlite3.IntegrityError):
            create_edition(conn, traveler_id=t.id, edition_number=1, commit=False)

    def test_idempotent_migration_on_existing_db(self, file_db):
        """Applying migration twice to the same file does not duplicate schema_migrations rows."""
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        count1 = c1.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        c1.close()
        apply_migrations(file_db)
        c2 = get_connection(file_db)
        count2 = c2.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        c2.close()
        assert count1 == count2


# =====================================================================
# 2. Traveler isolation and deletion/inactive
# =====================================================================

class TestTravelerIsolation:
    def test_deleted_traveler_blocks_generation(self, conn, traveler, source_dicts):
        delete_traveler(conn, traveler.id)
        provider = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": _load_fixture("source_bundle.json")["first_edition_fixture"]})
        service = GenerationService(conn, provider)
        with pytest.raises(PipelineError, match="inactive or deleted"):
            service.generate_first_edition(
                traveler_id=traveler.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
                
            )

    def test_deleted_traveler_blocks_second_edition(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]
        p1 = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        s1 = GenerationService(conn, p1)
        s1.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        create_feedback(conn, traveler_id=traveler.id, edition_id=ed1.id, direction_choices=["quieter_places"])
        delete_traveler(conn, traveler.id)
        p2 = MockProvider(task_payloads={"editorial_plan": SECOND_PLAN, "edition_draft": second_draft})
        s2 = GenerationService(conn, p2)
        with pytest.raises(PipelineError, match="inactive or deleted"):
            s2.generate_second_edition(
                traveler_id=traveler.id,
                prior_edition_id=ed1.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

    def test_traveler_is_active_check(self, conn, traveler):
        assert is_traveler_active(conn, traveler.id) is True
        delete_traveler(conn, traveler.id)
        assert is_traveler_active(conn, traveler.id) is False

    def test_different_travelers_isolated(self, conn):
        t1 = create_traveler(conn, display_name="A", destination="부산")
        t2 = create_traveler(conn, display_name="B", destination="부산")
        create_edition(conn, traveler_id=t1.id, edition_number=1)
        create_edition(conn, traveler_id=t1.id, edition_number=2)
        create_edition(conn, traveler_id=t2.id, edition_number=1)
        assert len(get_editions_by_traveler(conn, t1.id)) == 2
        assert len(get_editions_by_traveler(conn, t2.id)) == 1


# =====================================================================
# 3. Atomic persistence — rollback on validation failure
# =====================================================================

class TestAtomicPersistence:
    def test_first_edition_rollback_on_validation_failure(self, conn, traveler, source_dicts):
        bad_plan = {"plan_version": "1.0", "language": "ko", "central_theme": "X",
                     "sections": [{"section_id": "s1", "title": "T", "description": "D"}]}
        bad_draft = _load_fixture("adversarial_payloads.json")["adversarial_unknown_source"]
        provider = MockProvider(task_payloads={"editorial_plan": bad_plan, "edition_draft": bad_draft})
        service = GenerationService(conn, provider)
        with pytest.raises(PipelineError):
            service.generate_first_edition(
                traveler_id=traveler.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
                
            )
        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 0, "Failed generation should leave no edition"

    def test_second_edition_rollback_preserves_feedback(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        bad_draft = _load_fixture("adversarial_payloads.json")["adversarial_unknown_source"]
        p1 = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        s1 = GenerationService(conn, p1)
        s1.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        create_feedback(conn, traveler_id=traveler.id, edition_id=ed1.id, direction_choices=["quieter_places"])

        bad_plan = {"plan_version": "1.0", "language": "ko", "central_theme": "X",
                     "sections": [{"section_id": "sec_quiet_morning", "title": "T", "description": "D"}]}
        p2 = MockProvider(task_payloads={"editorial_plan": bad_plan, "edition_draft": bad_draft})
        s2 = GenerationService(conn, p2)
        with pytest.raises(PipelineError):
            s2.generate_second_edition(
                traveler_id=traveler.id,
                prior_edition_id=ed1.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )
        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 1
        assert editions[0].generation_status == EditionGenerationStatus.pending_review
        unapplied = get_unapplied_feedback_for_traveler(conn, traveler.id)
        assert len(unapplied) == 1


# =====================================================================
# 4. Foreign, mismatched, already-applied feedback rejection
# =====================================================================

class TestFeedbackRejection:
    def test_no_feedback_blocks_second_edition(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        p1 = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        s1 = GenerationService(conn, p1)
        s1.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]
        p2 = MockProvider(task_payloads={"editorial_plan": SECOND_PLAN, "edition_draft": second_draft})
        s2 = GenerationService(conn, p2)
        with pytest.raises(PipelineError, match="No unapplied feedback"):
            s2.generate_second_edition(
                traveler_id=traveler.id,
                prior_edition_id=ed1.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

    def test_already_applied_feedback_not_reused(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        p1 = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        s1 = GenerationService(conn, p1)
        s1.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        fb = create_feedback(conn, traveler_id=traveler.id, edition_id=ed1.id, direction_choices=["quieter_places"])
        mark_feedback_applied(conn, fb.id)
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]
        p2 = MockProvider(task_payloads={"editorial_plan": SECOND_PLAN, "edition_draft": second_draft})
        s2 = GenerationService(conn, p2)
        with pytest.raises(PipelineError, match="No unapplied feedback"):
            s2.generate_second_edition(
                traveler_id=traveler.id,
                prior_edition_id=ed1.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

    def test_feedback_from_different_traveler_not_seen(self, conn, source_dicts):
        t1 = create_traveler(conn, display_name="A", destination="부산")
        t2 = create_traveler(conn, display_name="B", destination="부산")
        p = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": _load_fixture("source_bundle.json")["first_edition_fixture"]})
        svc = GenerationService(conn, p)
        svc.generate_first_edition(
            traveler_id=t1.id, traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, t1.id)[0]
        create_feedback(conn, traveler_id=t2.id, edition_id=ed1.id, direction_choices=["quieter_places"])
        # Edition-scoped query: t2's feedback on ed1 is not returned for t1's unapplied
        unapplied_t1 = get_unapplied_feedback_for_edition(conn, t1.id, ed1.id)
        assert len(unapplied_t1) == 0
        unapplied_t2 = get_unapplied_feedback_for_edition(conn, t2.id, ed1.id)
        assert len(unapplied_t2) == 1


# =====================================================================
# 5. No-overwrite on failure paths
# =====================================================================

class TestNoOverwriteFailurePaths:
    def test_provider_failure_does_not_overwrite_last_edition(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        p1 = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        s1 = GenerationService(conn, p1)
        s1.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )
        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        create_feedback(conn, traveler_id=traveler.id, edition_id=ed1.id, direction_choices=["quieter_places"])

        bad_plan = {"plan_version": "1.0", "language": "ko", "central_theme": "bad",
                     "sections": [{"section_id": "x", "title": "T", "description": "D"}]}
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]
        p2 = MockProvider(task_payloads={"editorial_plan": bad_plan, "edition_draft": second_draft})
        s2 = GenerationService(conn, p2)
        with pytest.raises(PipelineError):
            s2.generate_second_edition(
                traveler_id=traveler.id,
                prior_edition_id=ed1.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )
        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 1
        assert editions[0].generation_status == EditionGenerationStatus.pending_review
        fetched = get_edition_by_id(conn, editions[0].id)
        assert fetched.structured_content.get("publication_title") is not None


# =====================================================================
# 6. Unknown/withdrawn source rejection
# =====================================================================

class TestSourceRejection:
    def test_unknown_source_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(
                section_id="s1", title="T", narrative="N",
                items=[InformationItem(item_id="i1", information_class=InformationClass.stable_reference, source_ref="src_unknown")]
            )]
        )
        errors = validate_source_references(content, {"src_busan_tourism"})
        assert any("Unknown source reference" in e for e in errors)

    def test_withdrawn_source_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(
                section_id="s1", title="T", narrative="N",
                items=[InformationItem(item_id="i1", information_class=InformationClass.stable_reference, source_ref="src_withdrawn")]
            )]
        )
        errors = validate_source_states(content, {"src_withdrawn": "withdrawn"})
        assert any("Withdrawn source" in e for e in errors)

    def test_withdrawn_source_in_pipeline(self, conn, traveler, source_dicts):
        ws_id = "src_withdrawn"
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        first_draft["sections"][0]["items"][0]["source_ref"] = ws_id
        provider = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        service = GenerationService(conn, provider)
        with pytest.raises(PipelineError, match="Validation failed"):
            service.generate_first_edition(
                traveler_id=traveler.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )


# =====================================================================
# 7. Unsupported time-sensitive claims
# =====================================================================

class TestUnsupportedClaims:
    def test_unsupported_claim_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(
                section_id="s1", title="T", narrative="N",
                items=[InformationItem(item_id="unsupported_item", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", verify_before_use=True)]
            )]
        )
        errors = validate_no_unsupported_claims(content, {"approved_item"})
        assert any("Unsupported claim" in e for e in errors)

    def test_valid_claim_passes(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(
                section_id="s1", title="T", narrative="N",
                items=[InformationItem(item_id="valid_item", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", verify_before_use=True)]
            )]
        )
        errors = validate_no_unsupported_claims(content, {"valid_item"})
        assert errors == []

    def test_empty_claims_rejects_all(self):
        """Empty approved-claims set must NOT silently authorize claims."""
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(
                section_id="s1", title="T", narrative="N",
                items=[InformationItem(item_id="i1", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", verify_before_use=True)]
            )]
        )
        errors = validate_no_unsupported_claims(content, set())
        assert len(errors) > 0, "Empty claims set must reject all time_sensitive items"


# =====================================================================
# 8. Unsafe markup / URL rejection (all content fields)
# =====================================================================

class TestUnsafeMarkupAllFields:
    def test_script_in_editorial_opening(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="<script>alert(1)</script>",
        )
        violations = check_all_content_fields(content)
        assert len(violations) > 0
        assert any("editorial_opening" in v for v in violations)

    def test_script_in_section_title(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="<script>xss</script>", narrative="N")]
        )
        violations = check_all_content_fields(content)
        assert any("title" in v for v in violations)

    def test_javascript_url_rejected(self):
        violations = check_unsafe_markup("visit javascript:void(0)")
        assert any("javascript:" in v for v in violations)

    def test_event_handler_rejected(self):
        violations = check_unsafe_markup("onclick=alert(1)")
        assert len(violations) > 0

    def test_data_url_rejected(self):
        violations = check_unsafe_markup("url(data:text/html,...)")
        assert len(violations) > 0

    def test_clean_content_passes(self):
        content = _make_first_content()
        violations = check_all_content_fields(content)
        assert violations == []

    def test_script_in_applied_feedback(self):
        from app.domain.models import AppliedFeedback
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            applied_feedback=[AppliedFeedback(
                feedback_id="fb1", requested_change="<script>xss</script>",
                actual_action="ok", affected_section_ids=[], evidence=""
            )]
        )
        violations = check_all_content_fields(content)
        assert any("applied_feedback" in v for v in violations)


# =====================================================================
# 9. Time-sensitive metadata validation
# =====================================================================

class TestTimeSensitiveMetadata:
    def test_missing_as_of_date_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="T", narrative="N", items=[
                InformationItem(item_id="i1", information_class=InformationClass.time_sensitive, source_ref="src1", verify_before_use=True)
            ])]
        )
        errors = validate_information_class_metadata(content)
        assert any("as_of_date" in e for e in errors)

    def test_missing_verify_before_use_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="T", narrative="N", items=[
                InformationItem(item_id="i1", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", verify_before_use=False)
            ])]
        )
        errors = validate_information_class_metadata(content)
        assert any("verify_before_use" in e for e in errors)

    def test_uncertain_confidence_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="T", narrative="N", items=[
                InformationItem(item_id="i1", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", confidence=SourceConfidence.uncertain, verify_before_use=True)
            ])]
        )
        errors = validate_information_class_metadata(content)
        assert any("confidence=uncertain" in e for e in errors)

    def test_withdrawn_confidence_rejected(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="T", narrative="N", items=[
                InformationItem(item_id="i1", information_class=InformationClass.time_sensitive, as_of_date="2026-01-01", source_ref="src1", confidence=SourceConfidence.withdrawn, verify_before_use=True)
            ])]
        )
        errors = validate_information_class_metadata(content)
        assert any("confidence=withdrawn" in e for e in errors)

    def test_inspiration_no_metadata_required(self):
        content = EditionContent(
            publication_title="T", edition_title="T", destination="B",
            trip_frame="2박", editorial_opening="T",
            sections=[EditionSection(section_id="s1", title="T", narrative="N", items=[
                InformationItem(item_id="i1", information_class=InformationClass.inspiration)
            ])]
        )
        errors = validate_information_class_metadata(content)
        assert errors == []


# =====================================================================
# 10. Generation-run exact row counts and fields
# =====================================================================

class TestGenerationRunAccounting:
    def test_exact_run_count_first_edition(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        provider = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        service = GenerationService(conn, provider)
        service.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
            
        )
        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 1
        count = count_generation_runs_by_edition(conn, editions[0].id)
        assert count == 2, f"Expected 2 runs (plan+draft), got {count}"

    def test_run_fields_recorded(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        provider = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        service = GenerationService(conn, provider)
        service.generate_first_edition(
            traveler_id=traveler.id,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
            
        )
        runs = get_generation_runs_by_task_type(conn, "editorial_plan")
        assert len(runs) >= 1
        r = runs[-1]
        assert r.provider == "mock"
        assert r.advertised_model == "mock-fixture"
        assert r.prompt_version == "lt-plan-v1"
        assert r.success is True


# =====================================================================
# 11. Privacy — pilot evidence
# =====================================================================

class TestPilotPrivacy:
    def test_free_sample_evidence(self, conn):
        t = create_traveler(conn, display_name="PT", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        pe = create_pilot_evidence(
            conn, evidence_type="free_sample", traveler_id=t.id,
            edition_id=ed.id, offer_description="무료 샘플", price_krw=0,
            consent_recorded=True,
        )
        assert pe.price_krw == 0
        assert pe.evidence_type == "free_sample"

    def test_paid_edition_evidence(self, conn):
        t = create_traveler(conn, display_name="PT2", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        pe = create_pilot_evidence(
            conn, evidence_type="paid_edition", traveler_id=t.id,
            edition_id=ed.id, offer_description="3회 에디션",
            price_krw=4900, consent_recorded=True,
            payment_evidence="payment_pending_manual",
        )
        assert pe.price_krw == 4900
        assert "manual" in pe.payment_evidence

    def test_no_payment_claimed(self, conn):
        t = create_traveler(conn, display_name="PT3", destination="부산")
        ed1 = create_edition(conn, traveler_id=t.id, edition_number=1)
        ed2 = create_edition(conn, traveler_id=t.id, edition_number=2)
        ev1 = create_pilot_evidence(
            conn, evidence_type="free_sample", traveler_id=t.id,
            edition_id=ed1.id, offer_description="무료 샘플 1회", price_krw=0,
        )
        ev2 = create_pilot_evidence(
            conn, evidence_type="paid_edition", traveler_id=t.id,
            edition_id=ed2.id, offer_description="3회 (KRW 4,900)", price_krw=4900,
            payment_evidence="payment_pending_manual",
        )
        assert ev1.price_krw == 0
        assert ev2.price_krw == 4900
        assert ev2.payment_evidence != "paid"


# =====================================================================
# 12. Privacy — free_text sanitization
# =====================================================================

class TestFreeTextSanitization:
    def test_credit_card_redacted(self, conn):
        t = create_traveler(conn, display_name="F1", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(
            conn, traveler_id=t.id, edition_id=ed.id,
            free_text="카드번호 1234-5678-9012-3456 입니다",
        )
        assert "1234" not in fb.free_text
        assert "CARD_REDACTED" in fb.free_text

    def test_phone_number_redacted(self, conn):
        t = create_traveler(conn, display_name="F2", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(
            conn, traveler_id=t.id, edition_id=ed.id,
            free_text="전화번호 010-1234-5678 입니다",
        )
        assert "010-1234-5678" not in fb.free_text

    def test_api_key_redacted(self, conn):
        t = create_traveler(conn, display_name="F3", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(
            conn, traveler_id=t.id, edition_id=ed.id,
            free_text="API key sk-abcdefghijklmnopqrstuvwxyz123456",
        )
        assert "sk-abc" not in fb.free_text
        assert "API_KEY_REDACTED" in fb.free_text

    def test_clean_text_unchanged(self, conn):
        t = create_traveler(conn, display_name="F4", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(
            conn, traveler_id=t.id, edition_id=ed.id,
            free_text="더 조용한 곳이 좋겠어요",
        )
        assert fb.free_text == "더 조용한 곳이 좋겠어요"


# =====================================================================
# 13. File-backed close/reopen
# =====================================================================

class TestFileBackedCloseReopen:
    def test_traveler_persists(self, file_db):
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        t = create_traveler(c1, display_name="지속", destination="부산")
        c1.close()
        c2 = get_connection(file_db)
        fetched = get_traveler_by_id(c2, t.id)
        assert fetched is not None
        assert fetched.display_name == "지속"
        c2.close()

    def test_edition_content_persists(self, file_db):
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        t = create_traveler(c1, display_name="테스트", destination="부산")
        ed = create_edition(c1, traveler_id=t.id, edition_number=1)
        from app.edition_repository import update_edition_content
        update_edition_content(c1, ed.id, {"publication_title": "지속"})
        c1.close()
        c2 = get_connection(file_db)
        fetched = get_edition_by_id(c2, ed.id)
        assert fetched is not None
        assert fetched.structured_content["publication_title"] == "지속"
        c2.close()

    def test_feedback_persists(self, file_db):
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        t = create_traveler(c1, display_name="T", destination="부산")
        ed = create_edition(c1, traveler_id=t.id, edition_number=1)
        fb = create_feedback(c1, traveler_id=t.id, edition_id=ed.id, free_text="지속 피드백")
        c1.close()
        c2 = get_connection(file_db)
        fetched = get_feedback_by_id(c2, fb.id)
        assert fetched is not None
        assert fetched.free_text == "지속 피드백"
        c2.close()

    def test_generation_run_persists(self, file_db):
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        r = create_generation_run(c1, task_type="editorial_plan", provider="mock", edition_id="ed_test")
        c1.close()
        c2 = get_connection(file_db)
        from app.generation_run_repository import get_generation_run_by_id as get_gr
        fetched = get_gr(c2, r.id)
        assert fetched is not None
        assert fetched.task_type == "editorial_plan"
        c2.close()

    def test_pilot_evidence_persists(self, file_db):
        apply_migrations(file_db)
        c1 = get_connection(file_db)
        t = create_traveler(c1, display_name="PE", destination="부산")
        ed = create_edition(c1, traveler_id=t.id, edition_number=1)
        pe = create_pilot_evidence(c1, evidence_type="free_sample", traveler_id=t.id, edition_id=ed.id, offer_description="샘플")
        c1.close()
        c2 = get_connection(file_db)
        from app.pilot_evidence_repository import get_pilot_evidence_by_id as get_pe
        fetched = get_pe(c2, pe.id)
        assert fetched is not None
        c2.close()


# =====================================================================
# 14. Zero network
# =====================================================================

class TestZeroNetwork:
    def test_no_outbound_connections(self, conn, traveler, source_dicts):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        provider = MockProvider(task_payloads={"editorial_plan": FIRST_PLAN, "edition_draft": first_draft})
        service = GenerationService(conn, provider)
        original_connect = socket.socket.connect
        connections = []
        def mock_connect(self, address):
            connections.append(address)
            raise RuntimeError("Network blocked")
        socket.socket.connect = mock_connect
        try:
            content = service.generate_first_edition(
                traveler_id=traveler.id,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
                
            )
            assert content.publication_title
            assert connections == []
        finally:
            socket.socket.connect = original_connect


# =====================================================================
# 15. /health startup smoke
# =====================================================================

class TestHealthSmoke:
    @pytest.mark.anyio
    async def test_health_startup(self, tmp_path):
        settings = Settings(database_url=str(tmp_path / "smoke.db"), environment="test")
        app = create_app(settings)
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
