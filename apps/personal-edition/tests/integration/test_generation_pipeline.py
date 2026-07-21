"""Integration tests for the full Phase 3 generation pipeline.

These tests use a real in-memory SQLite database (or file-backed SQLite for
persistence tests), apply migrations, create participants and inputs, load
file-backed fixture bundles, and run the entire GenerationService pipeline
end-to-end.
"""

import json
import os
import tempfile

import pytest

from app import (
    edition_repository as ed_repo,
    feedback_repository as fb_repo,
    generation_run_repository as gr_repo,
    input_repository as input_repo,
    participant_repository as pt_repo,
)
from app.ai.mock import MockProvider
from app.db import apply_migrations, get_connection
from app.domain.enums import ProviderErrorCategory
from app.feedback_repository import FeedbackValidationError
from app.pipeline.errors import (
    NOT_ATTEMPTED,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
)
from app.pipeline.fixtures import inject_feedback_id, load_bundle
from app.pipeline.service import (
    GenerationRequest,
    GenerationService,
    StageOutcome,
    count_words,
    MAX_INPUT_WORDS,
    MIN_INPUT_WORDS,
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


def _create_input(conn, pid="p1", raw_text=None, consent_confirmed=1):
    if raw_text is None:
        raw_text = "word " * 600
    return input_repo.create_input(
        conn,
        participant_id=pid,
        raw_text=raw_text,
        consent_confirmed=consent_confirmed,
    )


def _get_all_generation_runs(conn):
    rows = conn.execute(
        "SELECT id, task_type, provider, advertised_model, cost_class, "
        "prompt_version, started_at, completed_at, latency_seconds, "
        "success, validation_status, input_tokens, output_tokens, "
        "retry_count, error_category, error_message, "
        "human_correction_minutes, verified_upstream_status "
        "FROM generation_runs ORDER BY started_at"
    ).fetchall()
    return [
        gr_repo.GenerationRunRecord(
            id=r["id"],
            task_type=r["task_type"],
            provider=r["provider"],
            advertised_model=r["advertised_model"],
            verified_upstream_status=r["verified_upstream_status"],
            cost_class=r["cost_class"],
            prompt_version=r["prompt_version"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            latency_seconds=r["latency_seconds"],
            success=r["success"],
            validation_status=r["validation_status"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            retry_count=r["retry_count"],
            error_category=r["error_category"],
            error_message=r["error_message"],
            human_correction_minutes=r["human_correction_minutes"],
        )
        for r in rows
    ]


def _make_provider(bundle):
    return MockProvider(
        task_payloads={
            "editorial_plan": bundle.plan_payload,
            "edition_draft": bundle.draft_payload,
        }
    )


def _run_first_edition(conn, bundle, pid="p1"):
    _create_participant(conn, pid=pid, lang=bundle.language)
    inp = _create_input(conn, pid=pid, raw_text=bundle.input_text)
    provider = _make_provider(bundle)
    service = GenerationService(provider=provider)
    result = service.generate_edition(
        conn,
        request=GenerationRequest(
            participant_id=pid, input_id=inp.id, allow_short_sample=True
        ),
    )
    return result, inp


# ---------------------------------------------------------------------------
# Successful first edition generation
# ---------------------------------------------------------------------------

class TestFirstEditionGeneration:
    def test_korean_founder_success(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        result, _ = _run_first_edition(conn, bundle)

        assert result.succeeded is True
        assert result.edition_id is not None
        assert result.plan_run.success is True
        assert result.plan_run.validation_status == VALIDATION_PASSED
        assert result.draft_run.success is True
        assert result.draft_run.validation_status == VALIDATION_PASSED

        edition = ed_repo.get_edition_by_id(conn, result.edition_id)
        assert edition is not None
        assert edition.participant_id == "p1"
        assert edition.generation_status == "pending_review"
        assert edition.publication_state == "pending"
        assert edition.structured_content is not None
        content = json.loads(edition.structured_content)
        assert isinstance(content, dict)
        assert "publication_title" in content
        assert "sections" in content
        conn.close()

    def test_english_travel_success(self):
        bundle = load_bundle("english_travel")
        conn = _setup_db()
        result, _ = _run_first_edition(conn, bundle)

        assert result.succeeded is True
        assert result.edition_id is not None
        assert result.plan_run.success is True
        assert result.plan_run.validation_status == VALIDATION_PASSED
        assert result.draft_run.success is True
        assert result.draft_run.validation_status == VALIDATION_PASSED

        edition = ed_repo.get_edition_by_id(conn, result.edition_id)
        assert edition is not None
        assert edition.participant_id == "p1"
        assert edition.generation_status == "pending_review"
        assert edition.publication_state == "pending"
        conn.close()

    def test_edition_has_correct_edition_number(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        result, _ = _run_first_edition(conn, bundle)

        assert result.succeeded is True
        edition = ed_repo.get_edition_by_id(conn, result.edition_id)
        assert edition.edition_number == 1
        conn.close()

    def test_generation_run_accounting(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        result, _ = _run_first_edition(conn, bundle)

        assert result.succeeded is True

        all_runs = _get_all_generation_runs(conn)
        assert len(all_runs) == 2

        plan_runs = [r for r in all_runs if r.task_type == "editorial_plan"]
        draft_runs = [r for r in all_runs if r.task_type == "edition_draft"]
        assert len(plan_runs) == 1
        assert len(draft_runs) == 1

        plan_run = plan_runs[0]
        draft_run = draft_runs[0]

        assert plan_run.success == 1
        assert plan_run.completed_at is not None
        assert plan_run.latency_seconds is not None
        assert plan_run.latency_seconds >= 0
        assert plan_run.provider is not None
        assert plan_run.advertised_model is not None
        assert plan_run.cost_class is not None

        assert draft_run.success == 1
        assert draft_run.completed_at is not None
        assert draft_run.latency_seconds is not None
        assert draft_run.latency_seconds >= 0
        assert draft_run.provider is not None
        assert draft_run.advertised_model is not None
        assert draft_run.cost_class is not None

        assert result.plan_run.run_id == plan_run.id
        assert result.draft_run.run_id == draft_run.id
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

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert first_result.succeeded is True

        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

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
            allow_short_sample=True,
        )
        follow_up_result = service2.generate_edition(conn, request=follow_up_request)
        assert follow_up_result.succeeded is True
        assert follow_up_result.edition_id is not None

        fu_edition = ed_repo.get_edition_by_id(conn, follow_up_result.edition_id)
        assert fu_edition.edition_number == 2
        assert fu_edition.prior_edition_id == first_result.edition_id
        assert fu_edition.generation_status == "pending_review"

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
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is True
        assert result.plan_run.success is True
        assert result.plan_run.retry_count == 1

        all_runs = _get_all_generation_runs(conn)
        plan_runs = [r for r in all_runs if r.task_type == "editorial_plan"]
        assert len(plan_runs) == 1
        assert plan_runs[0].retry_count == 1
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
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
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
            allow_short_sample=True,
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
            allow_short_sample=True,
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
            allow_short_sample=True,
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
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
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
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
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
            raw_text="word " * 600,
            consent_confirmed=0,
        )

        provider = MockProvider(fixture_payload={"key": "val"})
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        conn.close()


# ---------------------------------------------------------------------------
# Request length policy
# ---------------------------------------------------------------------------

class TestRequestLengthPolicy:
    def test_input_too_short_rejected(self):
        conn = _setup_db()
        _create_participant(conn)
        short_text = "one two three four five"
        assert count_words(short_text, "en") < MIN_INPUT_WORDS
        inp = _create_input(conn, raw_text=short_text)

        bundle = load_bundle("korean_founder")
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.plan_run.error_message == "input too short"
        assert result.draft_run.error_message == "input too short"
        conn.close()

    def test_input_too_short_with_override_allowed(self):
        conn = _setup_db()
        _create_participant(conn)
        short_text = "one two three four five"
        assert count_words(short_text, "en") < MIN_INPUT_WORDS
        inp = _create_input(conn, raw_text=short_text)

        bundle = load_bundle("korean_founder")
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert result.plan_run.error_message != "input too short"
        assert result.draft_run.error_message != "input too short"
        conn.close()

    def test_input_too_long_rejected(self):
        conn = _setup_db()
        _create_participant(conn)
        long_text = "word " * (MAX_INPUT_WORDS + 1)
        assert count_words(long_text, "en") > MAX_INPUT_WORDS
        inp = _create_input(conn, raw_text=long_text)

        bundle = load_bundle("korean_founder")
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is False
        assert result.edition_id is None
        assert result.plan_run.error_message == "input too long"
        assert result.draft_run.error_message == "input too long"
        conn.close()

    def test_max_length_not_bypassed_by_short_sample(self):
        conn = _setup_db()
        _create_participant(conn)
        long_text = "word " * (MAX_INPUT_WORDS + 1)
        inp = _create_input(conn, raw_text=long_text)

        bundle = load_bundle("korean_founder")
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert result.succeeded is False
        assert result.plan_run.error_message == "input too long"
        conn.close()

    def test_korean_word_count(self):
        conn = _setup_db()
        _create_participant(conn, lang="ko")
        korean_text = "안녕하세요 " * 600
        assert count_words(korean_text, "ko") >= MIN_INPUT_WORDS
        inp = _create_input(conn, raw_text=korean_text)

        bundle = load_bundle("korean_founder")
        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.plan_run.error_message != "input too short"
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

        result1 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result1.succeeded is True
        ed1 = ed_repo.get_edition_by_id(conn, result1.edition_id)
        assert ed1.edition_number == 1

        result2 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
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
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is False
        msg = result.plan_run.error_message or ""
        assert bundle.input_text[:20] not in msg
        conn.close()


# ---------------------------------------------------------------------------
# Atomic persistence
# ---------------------------------------------------------------------------

class TestAtomicPersistence:
    def test_feedback_applied_atomically(self):
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
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert first_result.succeeded is True

        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )
        assert fb.applied_to_next_edition == 0

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_result = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_result.edition_id,
                feedback_id=fb.id,
                allow_short_sample=True,
            ),
        )
        assert follow_up_result.succeeded is True

        edition = ed_repo.get_edition_by_id(conn, follow_up_result.edition_id)
        assert edition is not None
        assert edition.edition_number == 2

        feedback_after = fb_repo.get_feedback_by_id(conn, fb.id)
        assert feedback_after.applied_to_next_edition == 1
        conn.close()

    def test_foreign_feedback_rejected(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()

        _create_participant(conn, pid="p1", lang=bundle.language)
        inp1 = _create_input(conn, pid="p1", raw_text=bundle.input_text)

        _create_participant(conn, pid="p2", lang=bundle.language)
        inp2 = _create_input(conn, pid="p2", raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)

        result_p1 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp1.id, allow_short_sample=True),
        )
        assert result_p1.succeeded is True

        result_p2 = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p2", input_id=inp2.id, allow_short_sample=True),
        )
        assert result_p2.succeeded is True

        ed_repo.update_edition_publication(
            conn, result_p1.edition_id, "published"
        )
        ed_repo.update_edition_publication(
            conn, result_p2.edition_id, "published"
        )

        fb_p2 = fb_repo.create_feedback(
            conn,
            participant_id="p2",
            edition_id=result_p2.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb_p2.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb_p2.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_result = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp1.id,
                is_follow_up=True,
                prior_edition_id=result_p1.edition_id,
                feedback_id=fb_p2.id,
                allow_short_sample=True,
            ),
        )
        assert follow_up_result.succeeded is False
        assert follow_up_result.edition_id is None

        fb_after = fb_repo.get_feedback_by_id(conn, fb_p2.id)
        assert fb_after.applied_to_next_edition == 0

        p1_editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(p1_editions) == 1
        conn.close()


# ---------------------------------------------------------------------------
# Issue #42: provider capability error accounting through the real pipeline
# ---------------------------------------------------------------------------

class TestProviderCapabilityErrorAccounting:
    """Durable accounting for RESPONSE_FORMAT_UNSUPPORTED and SCHEMA_REJECTED.

    Each category gets its own isolated file-backed SQLite DB to prove:
    - exactly 1 provider call
    - exactly 1 generation_run row
    - retry_count == 0
    - privacy-safe static error message
    - data survives close/reopen
    """

    def _make_capability_provider(self, error_category):
        from app.domain.models import ProviderResult
        from app.domain.enums import CostClass

        class CapProvider:
            provider = "external"
            model = "test-model"
            call_count = 0

            def generate_structured(self, **kwargs):
                self.call_count += 1
                return ProviderResult(
                    provider="external",
                    advertised_model="test-model",
                    cost_class=CostClass.FREE,
                    latency_seconds=0.1,
                    retry_count=0,
                    request_id=kwargs.get("request_id", "r"),
                    error_category=error_category,
                    error_message=str(error_category.value),
                    success=False,
                )

        return CapProvider()

    def _run_and_verify(self, tmp_path, expected_category):
        from app.pipeline.errors import is_retryable, safe_error_message

        db_path = str(tmp_path / "capability_test.db")
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")

        _create_participant(conn)
        inp = _create_input(conn)

        provider = self._make_capability_provider(expected_category)
        assert is_retryable(expected_category) is False

        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=False,
                allow_short_sample=True,
            ),
        )
        assert result.succeeded is False

        expected_message = safe_error_message(expected_category, "ignored raw text")

        # --- Verify on first connection ---
        assert provider.call_count == 1

        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_runs"
        ).fetchone()
        assert count_row["count"] == 1

        row = conn.execute(
            "SELECT success, retry_count, validation_status, "
            "error_category, error_message FROM generation_runs LIMIT 1"
        ).fetchone()
        assert row["success"] == 0
        assert row["retry_count"] == 0
        assert row["validation_status"] == "provider_failed"
        assert row["error_category"] == expected_category.value
        assert row["error_message"] == expected_message

        forbidden = ("api_key", "bearer", "authorization", "https://", "http://", "raw_body", "ignored raw text")
        for kw in forbidden:
            assert kw not in (row["error_message"] or "")

        conn.close()

        # --- Reopen same file DB and re-verify ---
        reopened = get_connection(db_path)

        count_row2 = reopened.execute(
            "SELECT COUNT(*) AS count FROM generation_runs"
        ).fetchone()
        assert count_row2["count"] == 1

        row2 = reopened.execute(
            "SELECT success, retry_count, validation_status, "
            "error_category, error_message FROM generation_runs LIMIT 1"
        ).fetchone()
        assert row2["success"] == 0
        assert row2["retry_count"] == 0
        assert row2["validation_status"] == "provider_failed"
        assert row2["error_category"] == expected_category.value
        assert row2["error_message"] == expected_message

        reopened.close()
        os.unlink(db_path)

    def test_response_format_unsupported_durable_accounting(self, tmp_path):
        self._run_and_verify(
            tmp_path, ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED
        )

    def test_schema_rejected_durable_accounting(self, tmp_path):
        self._run_and_verify(
            tmp_path, ProviderErrorCategory.SCHEMA_REJECTED
        )

    def test_pending_prior_edition_rejected(self):
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
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert first_result.succeeded is True

        first_edition = ed_repo.get_edition_by_id(conn, first_result.edition_id)
        assert first_edition.publication_state == "pending"

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_result = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_result.edition_id,
                feedback_id=fb.id,
                allow_short_sample=True,
            ),
        )
        assert follow_up_result.succeeded is False
        assert follow_up_result.edition_id is None

        fb_after = fb_repo.get_feedback_by_id(conn, fb.id)
        assert fb_after.applied_to_next_edition == 0

        p1_editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(p1_editions) == 1
        conn.close()

    def test_already_applied_feedback_rejected(self):
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
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert first_result.succeeded is True

        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        first_follow_up = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_result.edition_id,
                feedback_id=fb.id,
                allow_short_sample=True,
            ),
        )
        assert first_follow_up.succeeded is True

        fb_after = fb_repo.get_feedback_by_id(conn, fb.id)
        assert fb_after.applied_to_next_edition == 1

        ed_repo.update_edition_publication(
            conn, first_follow_up.edition_id, "published"
        )

        fb2 = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_follow_up.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )
        fb_repo.mark_feedback_applied(conn, fb2.id)
        fb2_after = fb_repo.get_feedback_by_id(conn, fb2.id)
        assert fb2_after.applied_to_next_edition == 1

        provider3 = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service3 = GenerationService(provider=provider3)
        second_follow_up = service3.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_follow_up.edition_id,
                feedback_id=fb2.id,
                allow_short_sample=True,
            ),
        )
        assert second_follow_up.succeeded is False
        assert second_follow_up.edition_id is None
        assert "already been applied" in (
            second_follow_up.plan_run.error_message or ""
        )
        conn.close()

    def test_feedback_mark_failure_no_edition(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        ed1 = ed_repo.create_edition(
            conn,
            participant_id="p1",
            edition_number=1,
            input_id=inp.id,
            structured_content=json.dumps({"test": True}),
            rendered_title="Test Edition",
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed1.id,
            direction_choices=json.dumps(list(bundle.feedback_directions)),
            free_text=bundle.feedback_free_text,
        )
        assert fb.applied_to_next_edition == 0

        fb_repo.mark_feedback_applied(conn, fb.id)
        fb_after = fb_repo.get_feedback_by_id(conn, fb.id)
        assert fb_after.applied_to_next_edition == 1

        with pytest.raises(FeedbackValidationError):
            ed_repo.create_edition_with_feedback_applied(
                conn,
                participant_id="p1",
                edition_number=2,
                prior_edition_id=ed1.id,
                input_id=inp.id,
                structured_content=json.dumps({"test": True}),
                rendered_title="Test Edition 2",
                feedback_id=fb.id,
            )

        p1_editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(p1_editions) == 1
        conn.close()


# ---------------------------------------------------------------------------
# File-backed database persistence
# ---------------------------------------------------------------------------

class TestFileBackedDatabase:
    def test_file_backed_first_edition_close_reopen(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")

        bundle = load_bundle("korean_founder")
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is True
        edition_id = result.edition_id

        conn.close()

        conn2 = get_connection(db_path)
        edition = ed_repo.get_edition_by_id(conn2, edition_id)
        assert edition is not None
        assert edition.participant_id == "p1"
        assert edition.edition_number == 1
        assert edition.generation_status == "pending_review"
        assert edition.publication_state == "pending"
        assert edition.structured_content is not None
        assert edition.rendered_title is not None

        all_runs = _get_all_generation_runs(conn2)
        assert len(all_runs) == 2
        plan_runs = [r for r in all_runs if r.task_type == "editorial_plan"]
        draft_runs = [r for r in all_runs if r.task_type == "edition_draft"]
        assert len(plan_runs) == 1
        assert len(draft_runs) == 1

        conn2.close()

    def test_file_backed_two_edition_loop_close_reopen(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")

        bundle = load_bundle("korean_founder")
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert first_result.succeeded is True

        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(
                list(bundle.feedback_directions)
            ),
            free_text=bundle.feedback_free_text,
        )

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_result = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_result.edition_id,
                feedback_id=fb.id,
                allow_short_sample=True,
            ),
        )
        assert follow_up_result.succeeded is True

        first_edition_id = first_result.edition_id
        follow_up_edition_id = follow_up_result.edition_id

        conn.close()

        conn2 = get_connection(db_path)

        ed1 = ed_repo.get_edition_by_id(conn2, first_edition_id)
        assert ed1 is not None
        assert ed1.edition_number == 1
        assert ed1.publication_state == "published"

        ed2 = ed_repo.get_edition_by_id(conn2, follow_up_edition_id)
        assert ed2 is not None
        assert ed2.edition_number == 2
        assert ed2.prior_edition_id == first_edition_id
        assert ed2.generation_status == "pending_review"

        fb_after = fb_repo.get_feedback_by_id(conn2, fb.id)
        assert fb_after.applied_to_next_edition == 1

        all_runs = _get_all_generation_runs(conn2)
        assert len(all_runs) == 4
        plan_runs = [r for r in all_runs if r.task_type == "editorial_plan"]
        draft_runs = [r for r in all_runs if r.task_type == "edition_draft"]
        assert len(plan_runs) == 2
        assert len(draft_runs) == 2

        conn2.close()

    def test_file_backed_accounting_fields(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")

        bundle = load_bundle("korean_founder")
        _create_participant(conn)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(participant_id="p1", input_id=inp.id, allow_short_sample=True),
        )
        assert result.succeeded is True

        conn.close()

        conn2 = get_connection(db_path)
        all_runs = _get_all_generation_runs(conn2)
        assert len(all_runs) == 2

        for run in all_runs:
            assert run.completed_at is not None
            assert run.latency_seconds is not None
            assert run.latency_seconds >= 0
            assert run.provider is not None and run.provider != ""
            assert run.advertised_model is not None and run.advertised_model != ""
            assert run.cost_class is not None and run.cost_class != ""
            assert run.id is not None

        assert result.plan_run.run_id == all_runs[0].id
        assert result.draft_run.run_id == all_runs[1].id

        conn2.close()


# ---------------------------------------------------------------------------
# Regression: 4 blocking issues from strategic review
# ---------------------------------------------------------------------------

class TestPriorEditionSummaryFromDB:
    def test_continuity_derived_from_persisted_edition(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn, lang=bundle.language)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider1 = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service1 = GenerationService(provider=provider1)
        first_result = service1.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert first_result.succeeded is True
        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(list(bundle.feedback_directions)),
            free_text=bundle.feedback_free_text,
        )

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)
        follow_up_result = service2.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                is_follow_up=True,
                prior_edition_id=first_result.edition_id,
                feedback_id=fb.id,
                allow_short_sample=True,
            ),
        )
        assert follow_up_result.succeeded is True
        assert follow_up_result.edition_id is not None

        plan_runs = [
            r for r in _get_all_generation_runs(conn)
            if r.task_type == "editorial_plan"
        ]
        assert len(plan_runs) == 2

        first_edition = ed_repo.get_edition_by_id(conn, first_result.edition_id)
        assert first_edition.structured_content is not None
        conn.close()


class TestRetryTokenAccumulation:
    def test_tokens_accumulated_across_retries(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn, lang=bundle.language)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            responses=[
                {
                    "kind": "error",
                    "task": "editorial_plan",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                {
                    "kind": "payload",
                    "task": "editorial_plan",
                    "payload": bundle.plan_payload,
                    "usage": {"input_tokens": 120, "output_tokens": 60},
                },
            ],
            task_payloads={"edition_draft": bundle.draft_payload},
        )
        service = GenerationService(provider=provider, max_retries=2)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert result.succeeded is True
        assert result.plan_run.retry_count == 1

        plan_runs = [
            r for r in _get_all_generation_runs(conn)
            if r.task_type == "editorial_plan"
        ]
        assert len(plan_runs) == 1
        plan_run = plan_runs[0]
        assert plan_run.input_tokens == 100 + 120
        assert plan_run.output_tokens == 50 + 60
        conn.close()

    def test_tokens_exhaustion_totals(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn, lang=bundle.language)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            responses=[
                {
                    "kind": "error",
                    "task": "editorial_plan",
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                },
                {
                    "kind": "error",
                    "task": "editorial_plan",
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                },
                {
                    "kind": "error",
                    "task": "editorial_plan",
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                },
            ],
            task_payloads={"edition_draft": bundle.draft_payload},
        )
        service = GenerationService(provider=provider, max_retries=2)
        result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert result.succeeded is False

        plan_runs = [
            r for r in _get_all_generation_runs(conn)
            if r.task_type == "editorial_plan"
        ]
        assert len(plan_runs) == 1
        plan_run = plan_runs[0]
        assert plan_run.input_tokens == 80 * 3
        assert plan_run.output_tokens == 30 * 3
        assert plan_run.success == 0
        conn.close()


class TestPersistenceFailureNormalization:
    def test_persistence_failure_updates_draft_row(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn, lang=bundle.language)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)

        original_create = ed_repo.create_edition

        def failing_create(*args, **kwargs):
            raise RuntimeError("simulated persistence failure")

        ed_repo.create_edition = failing_create
        try:
            result = service.generate_edition(
                conn,
                request=GenerationRequest(
                    participant_id="p1",
                    input_id=inp.id,
                    allow_short_sample=True,
                ),
            )
        finally:
            ed_repo.create_edition = original_create

        assert result.succeeded is False
        assert result.edition_id is None

        draft_runs = [
            r for r in _get_all_generation_runs(conn)
            if r.task_type == "edition_draft"
        ]
        assert len(draft_runs) == 1
        draft_run = draft_runs[0]
        assert draft_run.success == 0
        assert draft_run.validation_status == "validation_failed"
        assert draft_run.error_category == "schema_mismatch"
        assert draft_run.error_message is not None

        plan_runs = [
            r for r in _get_all_generation_runs(conn)
            if r.task_type == "editorial_plan"
        ]
        assert len(plan_runs) == 1
        assert plan_runs[0].success == 1

        p1_editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(p1_editions) == 0
        conn.close()

    def test_persistence_failure_no_feedback_consumed(self):
        bundle = load_bundle("korean_founder")
        conn = _setup_db()
        _create_participant(conn, lang=bundle.language)
        inp = _create_input(conn, raw_text=bundle.input_text)

        provider = MockProvider(
            task_payloads={
                "editorial_plan": bundle.plan_payload,
                "edition_draft": bundle.draft_payload,
            }
        )
        service = GenerationService(provider=provider)
        first_result = service.generate_edition(
            conn,
            request=GenerationRequest(
                participant_id="p1",
                input_id=inp.id,
                allow_short_sample=True,
            ),
        )
        assert first_result.succeeded is True
        ed_repo.update_edition_publication(
            conn, first_result.edition_id, "published"
        )

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=first_result.edition_id,
            direction_choices=json.dumps(list(bundle.feedback_directions)),
            free_text=bundle.feedback_free_text,
        )
        assert fb.applied_to_next_edition == 0

        fu_plan = inject_feedback_id(bundle.follow_up_plan_payload, fb.id)
        fu_draft = inject_feedback_id(bundle.follow_up_draft_payload, fb.id)

        provider2 = MockProvider(
            task_payloads={
                "editorial_plan": fu_plan,
                "edition_draft": fu_draft,
            }
        )
        service2 = GenerationService(provider=provider2)

        original_create = ed_repo.create_edition_with_feedback_applied

        def failing_create(*args, **kwargs):
            raise RuntimeError("simulated persistence failure")

        ed_repo.create_edition_with_feedback_applied = failing_create
        try:
            follow_up_result = service2.generate_edition(
                conn,
                request=GenerationRequest(
                    participant_id="p1",
                    input_id=inp.id,
                    is_follow_up=True,
                    prior_edition_id=first_result.edition_id,
                    feedback_id=fb.id,
                    allow_short_sample=True,
                ),
            )
        finally:
            ed_repo.create_edition_with_feedback_applied = original_create

        assert follow_up_result.succeeded is False
        assert follow_up_result.edition_id is None

        fb_after = fb_repo.get_feedback_by_id(conn, fb.id)
        assert fb_after.applied_to_next_edition == 0

        p1_editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(p1_editions) == 1
        conn.close()
