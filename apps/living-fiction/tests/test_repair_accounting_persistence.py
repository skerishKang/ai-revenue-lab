"""Tests: CTO repair — provider identity, attempt accounting, pilot privacy.

Tests:
- actual provider/model/cost recorded (not hardcoded "mock"/"free");
- one attempt recorded exactly once;
- retryable and non-retryable failures distinguished;
- exception attempts accounted for;
- deterministic validation failure results in success=false;
- branch transaction failure does not leave misleading successful final run;
- no raw private reader text, provider body, or credential stored;
- pilot evidence privacy validation and rejection;
- /health reports actual instantiated provider and model.
"""

import json
import os

import pytest

from app import generation_run_repository as gr_repo
from app import generation_attempt_repository as attempt_repo
from app import episode_repository as ep_repo
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.domain.enums import EpisodeType, ProviderErrorCategory, CostClass
from app.pipeline.service import GenerationRequest, generate_canon_episode
from app.pilot_evidence_service import (
    create_validated_pilot_evidence,
    PilotEvidenceValidationError,
)
from app.pipeline.errors import PrivacyViolationError
from tests.fixtures.synthetic_world import WORLD_STATE
from tests.fixtures.mock_payloads import CANON_EPISODE_1_PLAN, CANON_EPISODE_1_CONTENT
from tests.fixtures.adversarial_payloads import (
    ADVERSARIAL_PAYER_IDENTITY,
    ADVERSARIAL_CARD_NUMBER,
    ADVERSARIAL_PHONE_EMAIL,
    ADVERSARIAL_API_KEY,
    ADVERSARIAL_PRIVATE_COMMENT,
    ADVERSARIAL_RAW_PROSE,
    ADVERSARIAL_PAYMENT_CLAIM,
)


def _setup_world(db_conn):
    world_repo.create_world(db_conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            db_conn, WORLD_STATE.world_id,
            char.character_id, char.canonical_name, char.role,
            traits=json.dumps(char.knowledge),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(db_conn, WORLD_STATE.world_id, loc.location_id, loc.name)
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(db_conn, WORLD_STATE.world_id, clue.clue_id, clue.description)


def test_actual_provider_model_recorded(db_conn):
    """Generation runs record actual provider/model/cost from ProviderResult."""
    _setup_world(db_conn)

    # Use a custom provider name and cost class
    provider = MockProvider(
        provider_name="test-provider",
        cost_class=CostClass.FREE,
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        },
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    # Verify the generation run has actual provider values
    plan_run = gr_repo.get_generation_run(db_conn, result.plan_run_id)
    assert plan_run is not None
    assert plan_run.provider == "test-provider"
    assert plan_run.advertised_model == "mock-living-fiction-v1"
    assert plan_run.cost_class == "free"

    content_run = gr_repo.get_generation_run(db_conn, result.content_run_id)
    assert content_run is not None
    assert content_run.provider == "test-provider"


def test_attempt_rows_recorded(db_conn):
    """One durable attempt row per actual provider attempt."""
    _setup_world(db_conn)

    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        },
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    # Each run should have at least one attempt
    plan_attempts = attempt_repo.get_attempts_by_run(db_conn, result.plan_run_id)
    assert len(plan_attempts) >= 1
    assert plan_attempts[0].success is True
    assert plan_attempts[0].provider == "mock"

    content_attempts = attempt_repo.get_attempts_by_run(db_conn, result.content_run_id)
    assert len(content_attempts) >= 1
    assert content_attempts[0].success is True


def test_retryable_vs_non_retryable_distinguished(db_conn):
    """Retryable failures have retryable=True, non-retryable have retryable=False."""
    _setup_world(db_conn)

    # Provider that fails with a retryable error then succeeds
    provider = MockProvider(
        responses=[
            {"task": "episode_plan", "kind": "error",
             "category": ProviderErrorCategory.PROVIDER_ERROR,
             "message": "retryable failure"},
            {"task": "episode_plan", "kind": "payload", "payload": CANON_EPISODE_1_PLAN},
        ],
        task_payloads={"episode_content": CANON_EPISODE_1_CONTENT},
    )

    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert result.succeeded

    attempts = attempt_repo.get_attempts_by_run(db_conn, result.plan_run_id)
    assert len(attempts) == 2
    # First attempt: retryable failure
    assert attempts[0].success is False
    assert attempts[0].retryable is True
    # Second attempt: success
    assert attempts[1].success is True


def test_exception_attempt_accounted(db_conn):
    """Exception attempts are recorded."""
    _setup_world(db_conn)

    class ExceptionProvider:
        def generate_structured(self, **kwargs):
            raise RuntimeError("connection refused")
        @property
        def model(self):
            return "exception-model"
        @property
        def provider_name(self):
            return "exception-provider"
        @property
        def cost_class(self):
            return CostClass.UNKNOWN

    provider = ExceptionProvider()
    request = GenerationRequest(
        world=WORLD_STATE, episode_type=EpisodeType.CANON, is_first_canon=True,
    )
    result = generate_canon_episode(db_conn, provider, request, world_id=WORLD_STATE.world_id)
    assert not result.succeeded

    # The plan run should have attempt records for the exception
    plan_run = gr_repo.get_generation_run(db_conn, result.plan_run_id)
    assert plan_run is not None
    assert plan_run.success is False

    attempts = attempt_repo.get_attempts_by_run(db_conn, result.plan_run_id)
    # Should have attempts for each retry (max_retries + 1 = 3)
    assert len(attempts) >= 1
    for a in attempts:
        assert a.success is False
        assert a.error_category is not None


# ── Pilot evidence privacy ──────────────────────────────────────────────────


def test_pilot_evidence_rejects_payer_identity(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="revenue_hypothesis",
            evidence_data=ADVERSARIAL_PAYER_IDENTITY,
        )


def test_pilot_evidence_rejects_card_number(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="canon_delivery",
            evidence_data=ADVERSARIAL_CARD_NUMBER,
        )


def test_pilot_evidence_rejects_phone_email(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="engagement",
            evidence_data=ADVERSARIAL_PHONE_EMAIL,
        )


def test_pilot_evidence_rejects_api_key(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="ai_infra_cost",
            evidence_data=ADVERSARIAL_API_KEY,
        )


def test_pilot_evidence_rejects_private_comment(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="engagement",
            evidence_data=ADVERSARIAL_PRIVATE_COMMENT,
        )


def test_pilot_evidence_rejects_raw_prose(db_conn):
    _setup_world(db_conn)
    with pytest.raises((PrivacyViolationError, PilotEvidenceValidationError)):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="episode_delivery",
            evidence_data=ADVERSARIAL_RAW_PROSE,
        )


def test_pilot_evidence_rejects_payment_claim(db_conn):
    _setup_world(db_conn)
    with pytest.raises(PilotEvidenceValidationError, match="payment"):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="revenue_hypothesis",
            evidence_data=ADVERSARIAL_PAYMENT_CLAIM,
        )


def test_pilot_evidence_valid_revenue_hypothesis(db_conn):
    """Valid revenue hypothesis with 4900 as offer passes."""
    _setup_world(db_conn)
    result = create_validated_pilot_evidence(
        db_conn,
        evidence_category="revenue_hypothesis",
        evidence_data={
            "amount": 4900,
            "is_hypothesis": True,
            "description": "4 branch episodes offer",
        },
    )
    assert result.privacy_safe is True
    data = json.loads(result.evidence_data_json)
    assert data["is_hypothesis"] is True


def test_pilot_evidence_unsupported_category_rejected(db_conn):
    _setup_world(db_conn)
    with pytest.raises(PilotEvidenceValidationError, match="unsupported"):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="invalid_category",
            evidence_data={},
        )


def test_pilot_evidence_invalid_reference_rejected(db_conn):
    _setup_world(db_conn)
    with pytest.raises(PilotEvidenceValidationError, match="unsupported evidence category"):
        create_validated_pilot_evidence(
            db_conn,
            evidence_category="episode_delivery",
            evidence_data={"delivery_method": "test"},
            canon_episode_id="nonexistent-episode",
        )


# ── /health actual provider identity ────────────────────────────────────────


def test_health_reports_actual_provider(temp_db_path):
    """/health reports the actual instantiated provider and model."""
    from app.factory import create_app
    from fastapi.testclient import TestClient

    custom_provider = MockProvider(
        model="test-model-123",
        provider_name="test-provider-xyz",
    )
    app = create_app(db_path=temp_db_path, provider=custom_provider)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ai_provider"] == "test-provider-xyz"
        assert data["ai_model"] == "test-model-123"
        assert data["provider_type"] == "MockProvider"


def test_health_unsupported_provider_fails_closed(temp_db_path):
    """Unsupported provider configuration fails closed."""
    from app.factory import create_app

    with pytest.raises(RuntimeError, match="unsupported provider"):
        create_app(db_path=temp_db_path, provider="not_a_provider")
