"""B14 output-limit authority separation tests (#3553).

Covers the #3553 test matrix A..K:

  A. omitted max_tokens stays None (#3551 semantics preserved)
  B. explicit 1 allowed
  C. explicit current product max (4096) allowed
  D. explicit product max + 1 rejected by PRODUCT authority
  E. product permits but runtime hard ceiling smaller -> rejected by RUNTIME
  F. product/runtime permit but known provider/model capability smaller
     -> rejected by MODEL capability
  G. known provider max much larger -> product budget does NOT auto-widen
  H. unknown provider max -> no fabricated capability, check skipped
  I. B66 structured extraction budget untouched (source-level guard)
  J. response byte/time guards unchanged
  K. negative/zero/bool/non-integer explicit limits fail closed
"""

from __future__ import annotations

import math

import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    MAX_B14_RESPONSE_BYTES,
    PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING,
)
import padiem_ai_core.b14_execution as b14_execution_module
from padiem_ai_core.b14_output_limits import (
    ModelOutputCapability,
    OUTPUT_LIMIT_AUTHORITIES,
    validate_output_budget,
)

PROVIDER_MODEL = "example/provider-model"


def capability(max_output: int | None = 2048) -> ModelOutputCapability:
    return ModelOutputCapability(
        provider_id="example",
        model_id=PROVIDER_MODEL,
        provider_model_max_output=max_output,
        source="provider_official_docs",
        checked_at="2026-10-06",
    )


def request(max_tokens):
    return B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="test/route",
        max_tokens=max_tokens,
    )


# ── A. omitted stays None (#3551) ──
def test_a_omitted_max_tokens_stays_none_and_payload_omits_field() -> None:
    req = request(None)
    assert req.max_tokens is None
    assert "max_tokens" not in req.to_payload()
    # None is not judged by the explicit-budget contract at all
    decision = validate_output_budget(None)
    assert decision.ok is False
    assert decision.rejected_by == "PRODUCT_REQUESTED_LIMIT:format"
    assert "omitted stays None" in decision.detail


# ── B/C. explicit 1 and current product max allowed ──
def test_b_explicit_one_allowed() -> None:
    assert request(1).max_tokens == 1
    assert validate_output_budget(1).ok is True


def test_c_explicit_current_product_max_allowed() -> None:
    assert request(PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING).max_tokens == 4096
    assert validate_output_budget(PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING).ok is True
    # the ceiling keeps its documented meaning
    assert PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING == 4096


# ── D. product max + 1 rejected by PRODUCT authority ──
def test_d_product_max_plus_one_rejected_by_product_authority() -> None:
    with pytest.raises(ValueError):
        request(PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING + 1)
    decision = validate_output_budget(PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING + 1)
    assert decision.ok is False
    assert decision.rejected_by == "PRODUCT_REQUESTED_LIMIT"
    # capability did not cause the rejection — the product authority did
    assert decision.authority == "PRODUCT_REQUESTED_LIMIT"


# ── E. product permits but runtime hard ceiling smaller ──
def test_e_runtime_hard_ceiling_rejects_when_product_permits() -> None:
    decision = validate_output_budget(
        8192,
        product_max=8192,  # hypothetical deliberate widening to 8192
        runtime_ceiling=4096,  # runtime hard ceiling unchanged
    )
    assert decision.ok is False
    assert decision.rejected_by == "RUNTIME_HARD_SAFETY_CEILING"
    accepted = validate_output_budget(4096, product_max=8192, runtime_ceiling=8192)
    assert accepted.ok is True
    assert accepted.rejected_by is None
    # at the boundary itself the runtime ceiling accepts
    boundary = validate_output_budget(4096, product_max=8192, runtime_ceiling=4096)
    assert boundary.ok is True


# ── F. known provider/model capability smaller than request ──
def test_f_known_capability_rejects_over_capability_request() -> None:
    decision = validate_output_budget(4096, capability=capability(2048))
    assert decision.ok is False
    assert decision.rejected_by == "PROVIDER_MODEL_MAX_OUTPUT"
    assert "2048" in decision.detail and "provider_official_docs" in decision.detail
    within = validate_output_budget(2048, capability=capability(2048))
    assert within.ok is True


# ── G. larger known provider max does not auto-widen product budget ──
def test_g_known_larger_capability_does_not_auto_widen_product_budget() -> None:
    decision = validate_output_budget(4096, capability=capability(32768))
    assert decision.ok is True  # still judged against the product ceiling
    with pytest.raises(ValueError):
        request(8192)  # 32k-capable model does NOT raise the product ceiling
    assert PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING == 4096
    assert b14_execution_module.PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING == 4096
    # the conceptual validator still rejects above the product budget
    over = validate_output_budget(8192, capability=capability(32768))
    assert over.rejected_by == "PRODUCT_REQUESTED_LIMIT"


# ── H. unknown capability is never fabricated ──
def test_h_unknown_capability_not_fabricated() -> None:
    unknown = capability(None)
    assert unknown.capability_known is False
    decision = validate_output_budget(4096, capability=unknown)
    assert decision.ok is True  # capability check skipped, product/runtime in charge
    assert decision.rejected_by is None
    with pytest.raises(ValueError):
        capability(0)
    with pytest.raises(ValueError):
        capability(-5)
    assert OUTPUT_LIMIT_AUTHORITIES == (
        "PRODUCT_REQUESTED_LIMIT",
        "RUNTIME_HARD_SAFETY_CEILING",
        "PROVIDER_MODEL_MAX_OUTPUT",
    )


# ── I. B66 structured extraction budget untouched ──
def test_i_b66_structured_extraction_budget_independent() -> None:
    # #3553 must not touch the B66 conversation/extraction budget files owned
    # by #3549; the Core separation is additive-only. Guarded at source level:
    import inspect
    import pathlib

    core_source = pathlib.Path(b14_execution_module.__file__).read_text(encoding="utf-8")
    # the legacy ceiling is unchanged and explicitly labelled as a product limit
    assert "PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING = 4096" in core_source
    assert "GLOBAL_4096_ORIGIN=EARLY_B14_PILOT_VALIDATION" in core_source
    # no B66-specific budget logic was introduced into Core
    assert "b66" not in core_source.lower()
    # B66 conversation module on this branch carries no output-limit widening.
    # parents[3] is the monorepo root: tests -> padiem-ai-core -> packages -> root.
    conversation = (
        pathlib.Path(__file__).resolve().parents[3]
        / "apps" / "padiem-chat" / "app" / "b66_quote_conversation.py"
    )
    assert conversation.is_file(), f"B66 conversation source is missing: {conversation}"
    source = conversation.read_text(encoding="utf-8")
    assert "PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING" not in source
    assert "ModelOutputCapability" not in source


# ── J. response byte/time guards unchanged ──
def test_j_response_byte_and_time_guards_unchanged() -> None:
    assert MAX_B14_RESPONSE_BYTES == 1_048_576
    assert b14_execution_module.MAX_CONFIGURED_B14_RESPONSE_BYTES == 8 * 1_048_576
    config = b14_execution_module.B14ExecutionConfig(base_url="https://b14.example.test")
    assert config.timeout_seconds == 20.0
    assert config.max_response_bytes == MAX_B14_RESPONSE_BYTES
    with pytest.raises(ValueError):
        b14_execution_module.B14ExecutionConfig(base_url="https://b14.example.test", timeout_seconds=61)
    with pytest.raises(ValueError):
        b14_execution_module.B14ExecutionConfig(
            base_url="https://b14.example.test",
            max_response_bytes=math.inf,
        )


# ── K. invalid explicit limits fail closed ──
@pytest.mark.parametrize(
    "value",
    [0, -1, True, False, 1.5, "4096", None],
)
def test_k_invalid_explicit_limits_fail_closed(value) -> None:
    decision = validate_output_budget(value)
    assert decision.ok is False
    assert decision.rejected_by == "PRODUCT_REQUESTED_LIMIT:format"
    if value is not None:
        with pytest.raises(ValueError):
            request(value)
    else:
        # None is the omitted-value contract (#3551), accepted by the request
        assert request(None).max_tokens is None


# ── authority separation identities ──
def test_authorities_are_distinct_concepts() -> None:
    # one requested value can be judged differently by each authority
    assert validate_output_budget(4096).ok is True  # product accepts
    assert validate_output_budget(4096, capability=capability(2048)).ok is False  # model rejects
    assert validate_output_budget(8192, product_max=8192, runtime_ceiling=4096).ok is False  # runtime rejects
    assert validate_output_budget(2048, capability=capability(2048)).ok is True
    # capability metadata is descriptive, not the request validator
    assert b14_execution_module.PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING == 4096
