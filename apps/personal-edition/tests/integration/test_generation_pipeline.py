"""Integration tests for the full Phase 3 generation pipeline.

These tests use a real in-memory SQLite database, apply migrations, create
participants and inputs, load file-backed fixture bundles, and run the entire
GenerationService pipeline end-to-end.
"""

import json
import uuid

import pytest

from app import (
    edition_repository as ed_repo,
    feedback_repository as fb_repo,
    input_repository as input_repo,
    participant_repository as pt_repo,
)
from app.ai.mock import MockProvider
from app.db import apply_migrations, get_connection
from app.domain.enums import ProviderErrorCategory
from app.pipeline.errors import VALIDATION_PASSED, VALIDATION_FAILED
from app.pipeline.fixtures import inject_feedback_id, load_bundle
from app.pipeline.service import (
    GenerationRequest,
    GenerationService,
    StageOutcome,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db():
    conn = get_connection(":memory:")
    apply_migrations(conn, "migrations")
    return conn


def _create_participant(conn, pid="p1", lang="ko"):
    pt_repo.create_participant(
        conn,
        participant_id=pid,
        display_name="Test User",
        preferred_language=lang,
    )


def _create_input(conn, pid="p1", raw_text="Some input text."):
    return input_repo.create_input(
        conn,
        participant_id=pid,
        raw_text=raw_text,
    )


def _assert_successful_first_edition(result, conn, pid):
    assert result.succeeded is True
    assert result.edition_id is not None
    assert result.plan_run.success is True
    assert result.plan_run.validation_status == VALIDATION_PASSED
    assert result.draft_run.success is True
    assert result.draft_run.validation_status == VALIDATION_PASSED

    edition = ed_repo.get_edition_by_id(conn, result.edition_id)
    assert edition is not None
    assert edition.participant_id == pid
    assert edition.edition_number == 1
    assert edition.generation_status == "pending_review"
    assert edition.publication_state == "pending"
    assert edition.structured_content is not None
    content = json.loads(edition.structured_content)
    assert isinstance(content, dict)
    assert "publication_title" in content
    assert "sections" in content

    runs = gr_repo_list(conn, "editorial_plan")
    assert len(runs) >= 1


def gr_repo_list(conn, task_type):
    from app.generation_run_repository import get_generation_runs_by_task_type
    return get_generation_runs_by_task_type(conn, task_type)


# ---------------------------------------------------------------------------
# Successful first edition generation
# ---------------------------------------------------------------------------

class TestFirstEditionGeneration:
    def test_korean_founder_success(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
        )
        result = service.generate_edition(conn, request=request)
        _assert_successful_first_edition(result, conn, "p1")
        conn.close()

    def test_english_travel_success(self):
        bundle = load_bundle("english_travel")
        conn = _setup_db()
        _create_participant(conn, lang="en")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
        )
        result = service.generate_edition(conn, request=request)
        _assert_successful_first_edition(result, conn, "p1")
        conn.close()

    def test_edition_has_correct_edition_number(self):
        conn = _setup_db()
        _create_participant(conn)
        bundle = load_bundle("korean_founder")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn, request=GenerationRequest(participant_id="p1", input_id=inp.id)
        )
        assert result.succeeded is True
        edition = ed_repo.get_edition_by_id(conn, result.edition_id)
        assert edition.edition_number == 1
        conn.close()

    def test_generation_run_accounting(self):
        conn = _setup_db()
        _create_participant(conn)
        bundle = load_bundle("korean_founder")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn, request=GenerationRequest(participant_id="p1", input_id=inp.id)
        )
        assert result.succeeded is True
        runs = gr_repo_list(conn, "editorial_plan")
        assert len(runs) >= 1
        successful_runs = [r for r in runs if r.success == 1]
        assert len(successful_runs) >= 1
        conn.close()


# ---------------------------------------------------------------------------
# Follow-up edition generation (feedback loop)
# ---------------------------------------------------------------------------

class TestFollowUpEdition:
    def test_two_edition_loop(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        # First edition
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert first_result.succeeded is True

        # Create feedback for first edition
        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

        # Follow-up edition with feedback
        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
            is_follow_up=True,
            prior_edition_id=first_result.edition_id,
            feedback_id=fb.id,
            feedback_directions=bundle.feedback_directions,
            feedback_free_text=bundle.feedback_free_text,
        )
        follow_up_result = service2.generate_edition(conn, request=follow_up_request)
        assert follow_up_result.succeeded is True
        assert follow_up_result.edition_id is not None

        # Assert edition_number = 2
        fu_edition = ed_repo.get_edition_by_id(conn, follow_up_result.edition_id)
        assert fu_edition.edition_number == 2
        assert fu_edition.prior_edition_id == first_result.edition_id
        assert fu_edition.generation_status == "pending_review"

        # Assert feedback was marked applied
        feedback_record = fb_repo.get_feedback_by_id(conn, fb.id)
        assert feedback_record.applied_to_next_edition == 1
        conn.close()


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------

class TestRetry:
    def test_retry_then_success(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "payload", "task": "editorial_plan",
                 "payload": bundle.plan_payload},
            ],
            task_payloads={"edition_draft": bundle.draft_payload},
        )
        service = GenerationService(provider=provider, max_retries=2)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is True
        assert result.plan_run.success is True
        assert result.plan_run.retry_count == 1

        runs = gr_repo_list(conn, "editorial_plan")
        assert len(runs) >= 1
        conn.close()

    def test_retry_exhaustion_fails(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
            task_payloads={"edition_draft": bundle.draft_payload},
        )
        service = GenerationService(provider=provider, max_retries=2)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.plan_run.success is False
        assert result.draft_run.success is False
        conn.close()


# ---------------------------------------------------------------------------
# Adversarial: deterministic validation failures
# ---------------------------------------------------------------------------

class TestAdversarialInputs:
    def test_grounding_detection(self):
        bundle = load_bundle("adversarial_spouse")
        conn = _setup_db()
        _create_participant(conn, lang="en")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
            prohibited_inferences=tuple(bundle.prohibited_inventions),
        )
        result = service.generate_edition(conn, request=request)
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.draft_run.success is False
        assert result.draft_run.validation_status == VALIDATION_FAILED
        conn.close()

    def test_markup_detection(self):
        bundle = load_bundle("adversarial_markup")
        conn = _setup_db()
        _create_participant(conn, lang="en")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
            prohibited_inferences=tuple(bundle.prohibited_inventions),
        )
        result = service.generate_edition(conn, request=request)
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.draft_run.success is False
        assert result.draft_run.validation_status == VALIDATION_FAILED
        conn.close()

    def test_invalid_segment_references(self):
        bundle = load_bundle("adversarial_refs")
        conn = _setup_db()
        _create_participant(conn, lang="en")
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        request = GenerationRequest(
            participant_id="p1",
            input_id=inp.id,
            prohibited_inferences=tuple(bundle.prohibited_inventions),
        )
        result = service.generate_edition(conn, request=request)
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.draft_run.success is False
        assert result.draft_run.validation_status == VALIDATION_FAILED
        conn.close()


# ---------------------------------------------------------------------------
# Edge cases: participant / input constraints
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_participant_not_active(self):
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn)
        pt_repo.delete_participant(conn, "p1")

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()

    def test_input_not_found(self):
        conn = _setup_db()
        _create_participant(conn)

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1", input_id="nonexistent"
            ),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()

    def test_input_belongs_to_another_participant(self):
        conn = _setup_db()
        _create_participant(conn, "p1")
        _create_participant(conn, "p2")
        inp = _create_input(conn, pid="p1")

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p2", input_id=inp.id
            ),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()

    def test_input_is_deleted(self):
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn)
        input_repo.delete_input(conn, inp.id)

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()

    def test_consent_not_confirmed(self):
        conn = _setup_db()
        _create_participant(conn)
        inp = input_repo.create_input(
            conn,
            participant_id="p1",
            raw_text="Some text",
            consent_confirmed=0,
        )

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()


# ---------------------------------------------------------------------------
# No-overwrite invariant
# ---------------------------------------------------------------------------

class TestNoOverwrite:
    def test_concurrent_generation_creates_new_edition(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)

        # Run twice — each call should create a distinct edition
        result1 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result1.succeeded is True
        ed1 = ed_repo.get_edition_by_id(conn, result1.edition_id)
        assert ed1.edition_number == 1

        result2 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result2.succeeded is True
        ed2 = ed_repo.get_edition_by_id(conn, result2.edition_id)
        assert ed2.edition_number == 2
        assert ed2.id != ed1.id
        conn.close()


# ---------------------------------------------------------------------------
# Privacy-safe error messages
# ---------------------------------------------------------------------------

class TestErrorMessages:
    def test_error_message_contains_no_raw_text(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            responses=[
                {"kind": "schema_mismatch", "task": "editorial_plan"},
                {"kind": "schema_mismatch", "task": "editorial_plan"},
                {"kind": "schema_mismatch", "task": "editorial_plan"},
            ],
            task_payloads={"edition_draft": bundle.draft_payload},
        )
        service = GenerationService(provider=provider, max_retries=2)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        msg = result.plan_run.error_message or ""
        assert bundle.input_text[:20] not in msg
        conn.close()
