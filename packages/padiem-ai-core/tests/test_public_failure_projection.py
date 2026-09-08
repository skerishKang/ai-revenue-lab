"""Core tests for the shared public-safe execution failure projection (#1558)."""

from __future__ import annotations

import hashlib
import re

import pytest

from padiem_ai_core.public_failure_projection import (
    AUTOMATIC_REDISPATCH,
    AUTOMATIC_RESUME,
    AUTOMATIC_RETRY,
    PUBLIC_FAILURE_AUTHORITY_MINTING,
    SHARED_FAILURE_STAGE_CATEGORY,
    PublicFailureCategory,
    PublicFailureProjection,
    StageFailureReceipt,
    StageOutcome,
    project_stage_failure,
)

_PLAN_ID = "plan-1558-a"
_FINGERPRINT = hashlib.sha256(b"plan-material").hexdigest()


def receipt(**overrides) -> StageFailureReceipt:
    values = {
        "plan_id": _PLAN_ID,
        "plan_fingerprint": _FINGERPRINT,
        "stage_id": "agent_execution",
        "outcome": StageOutcome.FAILED,
        "summary_code": "agent.step.failed",
        "event_id": "evt-1",
        "evidence_ref": "ev-1",
    }
    values.update(overrides)
    return StageFailureReceipt(**values)


def project(receipt_value: StageFailureReceipt) -> PublicFailureProjection:
    return project_stage_failure(
        receipt_value,
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
    )


def test_all_required_public_categories_exist() -> None:
    assert {item.value for item in PublicFailureCategory} == {
        "policy_or_admission_failed",
        "repository_materialization_failed",
        "sandbox_or_computer_failed",
        "agent_execution_failed",
        "verification_failed",
        "artifact_or_output_failed",
        "teardown_failed",
    }


@pytest.mark.parametrize(
    ("stage_id", "category"),
    [
        ("admission", PublicFailureCategory.POLICY_OR_ADMISSION_FAILED),
        ("repository_materialization", PublicFailureCategory.REPOSITORY_MATERIALIZATION_FAILED),
        ("sandbox", PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED),
        ("computer", PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED),
        ("agent_execution", PublicFailureCategory.AGENT_EXECUTION_FAILED),
        ("verification", PublicFailureCategory.VERIFICATION_FAILED),
        ("artifact", PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED),
        ("teardown", PublicFailureCategory.TEARDOWN_FAILED),
    ],
)
def test_stage_category_mapping_is_fixed(stage_id: str, category: PublicFailureCategory) -> None:
    projection = project(receipt(stage_id=stage_id, summary_code="stage.failed"))
    assert projection.category is category
    assert projection.to_public_dict()["category"] == category.value


def test_only_failed_state_projects() -> None:
    for outcome in (StageOutcome.SUCCEEDED, StageOutcome.SKIPPED):
        with pytest.raises(ValueError, match="only a failed stage receipt"):
            project(receipt(outcome=outcome))


def test_non_receipt_input_fails_closed() -> None:
    with pytest.raises(ValueError, match="must be a StageFailureReceipt"):
        project_stage_failure(
            {"stage": "teardown"},
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=_FINGERPRINT,
        )


def test_exact_plan_identity_binding_required() -> None:
    with pytest.raises(ValueError, match="does not bind the expected plan"):
        project_stage_failure(
            receipt(),
            expected_plan_id="plan-other",
            expected_plan_fingerprint=_FINGERPRINT,
        )
    with pytest.raises(ValueError, match="does not bind the expected plan"):
        project_stage_failure(
            receipt(),
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=hashlib.sha256(b"other").hexdigest(),
        )


@pytest.mark.parametrize(
    "raw_text",
    [
        "ProviderError: 503 from api.vendor.example.com/v1/chat",
        "Traceback (most recent call last):",
        "C:\\Users\\secret\\workspace\\repo\\file.py",
        "https://internal-endpoint.example/keys?token=abc",
        "Authorization: Bearer sk-super-secret-value",
        "x" * 200,
        "UPPER_CASE_CODE",
        "has space",
        "",
    ],
)
def test_raw_provider_error_or_text_is_never_accepted(raw_text: str) -> None:
    with pytest.raises(ValueError, match="bounded server-owned public-safe code"):
        receipt(summary_code=raw_text)


def test_summary_code_is_bounded_lowercase_identifier() -> None:
    ok = receipt(summary_code="a1.b2-c3")
    assert ok.summary_code == "a1.b2-c3"
    assert len("a" * 96) == 96
    assert receipt(summary_code="a" * 96).summary_code
    with pytest.raises(ValueError):
        receipt(summary_code="a" * 97)


def test_retryable_defaults_false_and_is_server_owned_boolean() -> None:
    default = project(receipt(summary_code="stage.failed"))
    assert default.retryable is False
    explicit = project(receipt(summary_code="stage.failed", retryable=True))
    assert explicit.retryable is True
    with pytest.raises(ValueError, match="server-owned boolean"):
        receipt(retryable="yes")
    with pytest.raises(ValueError, match="server-owned boolean"):
        receipt(retryable=1)


def test_receipt_rejects_invalid_identity_fields() -> None:
    with pytest.raises(ValueError, match="plan_id"):
        receipt(plan_id="bad plan id")
    with pytest.raises(ValueError, match="stage_id"):
        receipt(stage_id="../../etc/passwd")
    with pytest.raises(ValueError, match="SHA-256"):
        receipt(plan_fingerprint="not-a-digest")
    with pytest.raises(ValueError, match="StageOutcome"):
        receipt(outcome="exploded")


def test_unknown_stage_fails_closed_without_default_category() -> None:
    with pytest.raises(ValueError, match="no public failure category mapping"):
        project(receipt(stage_id="mystery_stage"))


def test_product_supplied_stage_mapping_is_honored_and_validated() -> None:
    mapping = {"product_stage": PublicFailureCategory.VERIFICATION_FAILED}
    projection = project_stage_failure(
        receipt(stage_id="product_stage"),
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
        stage_categories=mapping,
    )
    assert projection.category is PublicFailureCategory.VERIFICATION_FAILED
    with pytest.raises(ValueError, match="must be a PublicFailureCategory"):
        project_stage_failure(
            receipt(stage_id="product_stage"),
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=_FINGERPRINT,
            stage_categories={"product_stage": "verification_failed"},
        )


def test_teardown_failure_is_separately_visible() -> None:
    teardown = project(receipt(stage_id="teardown", summary_code="teardown.resource.leak"))
    assert teardown.category is PublicFailureCategory.TEARDOWN_FAILED
    public = teardown.to_public_dict()
    assert public["stage"] == "teardown"
    assert public["category"] == "teardown_failed"


def test_public_projection_carries_no_free_form_or_leak_fields() -> None:
    public = project(receipt()).to_public_dict()
    assert set(public) == {
        "contract_version",
        "plan_id",
        "plan_fingerprint",
        "stage",
        "category",
        "summary_code",
        "retryable",
        "raw_provider_error",
        "raw_terminal_output",
        "tool_args",
        "tool_results",
        "raw_diff",
        "filesystem_path",
        "provider_endpoint",
        "credentials",
        "hidden_reasoning",
        "internal_runtime_payload",
        "automatic_retry",
        "automatic_redispatch",
        "automatic_resume",
    }
    leak_flags = {
        key: value
        for key, value in public.items()
        if key
        in {
            "raw_provider_error",
            "raw_terminal_output",
            "tool_args",
            "tool_results",
            "raw_diff",
            "filesystem_path",
            "provider_endpoint",
            "credentials",
            "hidden_reasoning",
            "internal_runtime_payload",
            "automatic_retry",
            "automatic_redispatch",
            "automatic_resume",
        }
    }
    assert set(leak_flags.values()) == {False}
    assert PUBLIC_FAILURE_AUTHORITY_MINTING is False
    assert (AUTOMATIC_RETRY, AUTOMATIC_REDISPATCH, AUTOMATIC_RESUME) == (False, False, False)
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", public["summary_code"])


def test_receipt_fingerprint_is_stable_and_distinct_per_event() -> None:
    base = receipt()
    assert base.fingerprint == receipt().fingerprint
    assert base.fingerprint != receipt(event_id="evt-2").fingerprint


def test_shared_stage_map_covers_all_categories() -> None:
    assert set(SHARED_FAILURE_STAGE_CATEGORY.values()) == set(PublicFailureCategory)
