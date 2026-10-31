from __future__ import annotations

from pathlib import Path
import sys

import pytest

from app import model_policy as model_policy_module
from app.model_policy import (
    FREE_B14_MODEL_ID,
    PADIEM_FREE,
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    EXECUTABLE_B14_MODEL_IDS,
    HIGH_B14_MODEL_ID,
    LOW_B14_MODEL_ID,
    MAX_HOLD_MODEL_ID,
    MEDIUM_B14_MODEL_ID,
    MODEL_CAPABILITIES,
    PADIEM_MAX,
    PADIEM_PLUS,
    PADIEM_PRO,
    PRODUCT_TIER_NAMES,
    PROFILE_MODEL_IDS,
    RETIRED_B14_MODEL_IDS,
    ModelPolicyError,
    model_policy_is_executable,
    model_profile_is_assigned,
    model_supports,
    product_tier_name,
    request_tier_context,
    resolve_model_policy,
    resolve_request_model_policy,
    resolve_tier_policy,
)
from padiem_control_plane import product_tier_routes as tier_routes
from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID as CONTRACT_MAX_HOLD_MODEL_ID,
    TEST_PHASE_PRIMARY_B14_MODEL_ID,
    PLUS_HOLD_MODEL_ID as CONTRACT_PLUS_HOLD_MODEL_ID,
    PRO_HOLD_MODEL_ID as CONTRACT_PRO_HOLD_MODEL_ID,
    ProductTierLabel,
    active_route_for,
)


def _declared_executable_model_ids() -> frozenset[str]:
    """The executable set the canonical declaration implies, derived not restated.

    #3767: this module used to assert ``EXECUTABLE_B14_MODEL_IDS == frozenset()``,
    which encodes today's empty-route state rather than a durable contract and
    would have to be edited -- or silently missed -- the moment an owner selects
    a model. The product-side set must instead agree with the declaration,
    whichever state the declaration is in.
    """

    return frozenset(
        route.model_id
        for label in ProductTierLabel
        if (route := active_route_for(label)) is not None and route.model_id
    )


def _module_tier_identity(label: ProductTierLabel) -> str:
    """The Chat product identity the module derives for one tier."""

    return {
        ProductTierLabel.PLUS: LOW_B14_MODEL_ID,
        ProductTierLabel.PRO: MEDIUM_B14_MODEL_ID,
        ProductTierLabel.MAX: HIGH_B14_MODEL_ID,
    }[label]


def test_free_beam_and_paid_google_primaries_derive_from_the_shared_contract() -> None:
    policy=resolve_model_policy([{"role":"user","content":"안녕하세요"}])
    assert DEFAULT_CHAT_PROFILE=="free"
    assert policy.profile=="free"
    assert policy.model_id==DEFAULT_B14_MODEL_ID==FREE_B14_MODEL_ID==active_route_for(ProductTierLabel.FREE).model_id
    assert {LOW_B14_MODEL_ID,MEDIUM_B14_MODEL_ID,HIGH_B14_MODEL_ID}=={TEST_PHASE_PRIMARY_B14_MODEL_ID}
    assert model_policy_is_executable(policy.model_id)
    assert EXECUTABLE_B14_MODEL_IDS==_declared_executable_model_ids() | {FREE_B14_MODEL_ID}
    assert PRODUCT_TIER_NAMES[CONTRACT_PLUS_HOLD_MODEL_ID]==PADIEM_PLUS
    assert PRODUCT_TIER_NAMES[CONTRACT_PRO_HOLD_MODEL_ID]==PADIEM_PRO
    assert PRODUCT_TIER_NAMES[CONTRACT_MAX_HOLD_MODEL_ID]==PADIEM_MAX

def test_ordinary_chat_uses_executable_free_catjam() -> None:
    policy=resolve_model_policy([{"role":"user","content":"안녕하세요"}])
    assert policy.model_id==FREE_B14_MODEL_ID
    assert policy.profile=="free"

@pytest.mark.parametrize("slash_text", ["/plus", "/pro", "/max", "/kilo"])
def test_slash_tier_text_is_ordinary_prompt_and_keeps_default_tier(slash_text: str) -> None:
    plain = resolve_model_policy([{"role":"user","content":"테스트 질문입니다"}])
    message = f"{slash_text} 테스트 질문입니다"
    policy=resolve_model_policy([{"role":"user","content":message}])
    assert policy.model_id==plain.model_id==DEFAULT_B14_MODEL_ID==FREE_B14_MODEL_ID
    assert policy.profile==plain.profile=="free"
    assert policy.messages[-1]=={"role":"user","content":message}
    assert model_policy_is_executable(policy.model_id)

def test_hidden_tier_alias_symbols_are_gone() -> None:
    assert not hasattr(model_policy_module, "MODEL_ALIASES")
    assert not hasattr(model_policy_module, "_strip_hidden_tier_alias")

@pytest.mark.parametrize("slash_text", ["/plus", "/pro", "/max", "/kilo", "/poolside", "/unknown"])
def test_slash_prefixed_text_without_a_prompt_is_ordinary_text(slash_text: str) -> None:
    policy=resolve_model_policy([{"role":"user","content":slash_text}])
    assert policy.model_id==DEFAULT_B14_MODEL_ID
    assert policy.profile=="free"
    assert policy.messages[-1]=={"role":"user","content":slash_text}

@pytest.mark.parametrize("content", ["/foo 질문", "/poolside 질문", "/agnes 질문", "/openrouter 질문", "/unknown 질문"])
def test_unknown_slash_text_is_accepted_as_ordinary_text(content: str) -> None:
    policy=resolve_model_policy([{"role":"user","content":content}])
    assert policy.model_id==DEFAULT_B14_MODEL_ID
    assert policy.profile=="free"
    assert policy.messages[-1]=={"role":"user","content":content}

def test_poolside_is_not_executable_from_slash_text() -> None:
    assert EXECUTABLE_B14_MODEL_IDS == _declared_executable_model_ids() | {FREE_B14_MODEL_ID}
    assert model_policy_is_executable("poolside/laguna-s-2.1") is False

def test_slash_text_is_not_rewritten_with_a_provider_hint() -> None:
    policy=resolve_model_policy([{"role":"user","content":"/unknown 질문"}])
    message = policy.messages[-1]["content"].lower()
    for hidden_name in ("poolside", "nvidia", "tencent", "kilo", "nemotron", "hy3", "laguna"):
        assert hidden_name not in message


def test_historical_hold_sentinels_claim_no_executable_capabilities() -> None:
    # A2/A3/B1: the three compatibility names are gone from the module; the
    # retired ids themselves must still claim no capability if an old client sends them.
    for gone in ("AUTO_B14_MODEL_ID", "KILO_B14_MODEL_ID", "UNASSIGNED_B14_MODEL_ID"):
        assert not hasattr(model_policy_module, gone)
    for model_id in (CONTRACT_PLUS_HOLD_MODEL_ID,CONTRACT_PRO_HOLD_MODEL_ID,CONTRACT_MAX_HOLD_MODEL_ID,"b14/auto","padiem-profile/medium-unassigned"):
        assert model_supports(model_id,"chat") is False
        assert model_supports(model_id,"image") is False
        assert model_policy_is_executable(model_id) is False

def test_raw_provider_ids_are_not_capability_catalog_rows() -> None:
    # B8: capability rows are keyed by product-tier identity only. A raw
    # provider model id must not reappear as a selectable catalog row.
    for provider_id in (
        "google/gemini-3.5-flash-lite",
        "opencode-go/muse-spark-1.2-contributor",
        "opencode-go/muse-spark-1.3-contributor",
    ):
        assert provider_id not in MODEL_CAPABILITIES
        assert model_supports(provider_id, "chat") is False
        assert model_supports(provider_id, "coding") is False
        assert model_supports(provider_id, "image") is False

def test_model_id_is_not_an_identity_for_four_distinct_product_grades() -> None:
    assert PROFILE_MODEL_IDS["free"]==FREE_B14_MODEL_ID
    assert model_policy_is_executable(PROFILE_MODEL_IDS["free"])
    for profile in ("low","medium","high"):
        assert PROFILE_MODEL_IDS[profile]==TEST_PHASE_PRIMARY_B14_MODEL_ID
        assert model_policy_is_executable(PROFILE_MODEL_IDS[profile])
    for model_id in ("b14/auto","padiem-profile/medium-unassigned"):
        assert not model_profile_is_assigned(model_id)
        assert not model_policy_is_executable(model_id)

def test_all_profile_routes_are_derived_from_the_shared_contract() -> None:
    assert LOW_B14_MODEL_ID==active_route_for(ProductTierLabel.PLUS).model_id
    assert MEDIUM_B14_MODEL_ID==active_route_for(ProductTierLabel.PRO).model_id
    assert HIGH_B14_MODEL_ID==active_route_for(ProductTierLabel.MAX).model_id
    assert {LOW_B14_MODEL_ID,MEDIUM_B14_MODEL_ID,HIGH_B14_MODEL_ID}=={TEST_PHASE_PRIMARY_B14_MODEL_ID}

def test_a_declared_route_is_the_only_thing_that_makes_a_tier_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executability derivation follows the canonical declaration.

    A test-controlled declaration is injected here. No production route is
    registered, no model is registered, and no provider lane is named: the point
    is that the derivation answers the declaration rather than the state that
    happened to hold when this module was written (#3767).
    """

    assert EXECUTABLE_B14_MODEL_IDS == _declared_executable_model_ids() | {FREE_B14_MODEL_ID}

    synthetic_route = tier_routes.ProductTierRoute(
        route_id="test.plus.synthetic.v1",
        status=tier_routes.ProductRouteStatus.EXECUTABLE,
        model_family="test",
        provider_id="test",
        model_id=CONTRACT_PLUS_HOLD_MODEL_ID,
        evidence="test-only synthetic Plus route (#3767)",
    )

    def _active_route_for(label: tier_routes.ProductTierLabel):
        return synthetic_route if label is tier_routes.ProductTierLabel.PLUS else None

    monkeypatch.setattr(tier_routes, "active_route_for", _active_route_for)
    monkeypatch.setattr(model_policy_module, "active_route_for", _active_route_for)
    monkeypatch.setattr(sys.modules[__name__], "active_route_for", _active_route_for)

    assert model_policy_module._contract_executable_ids() == frozenset(
        {synthetic_route.model_id}
    )
    assert _declared_executable_model_ids() == frozenset({synthetic_route.model_id})
    assert model_policy_module._contract_route_or_hold_id(
        tier_routes.ProductTierLabel.PLUS, CONTRACT_PLUS_HOLD_MODEL_ID
    ) == synthetic_route.model_id
    # Only Plus is declared: a tier without a route keeps its HOLD identity.
    assert model_policy_module._contract_route_or_hold_id(
        tier_routes.ProductTierLabel.MAX, CONTRACT_MAX_HOLD_MODEL_ID
    ) == CONTRACT_MAX_HOLD_MODEL_ID


def test_model_policy_source_contains_no_provider_route_literals() -> None:
    source = Path(model_policy_module.__file__).read_text(encoding="utf-8")
    assert '"kilo/' not in source
    assert "'kilo/" not in source
    assert '"padiem-profile/plus-hold"' not in source
    assert '"padiem-profile/pro-hold"' not in source
    assert '"padiem-profile/max-hold"' not in source
    assert "EXECUTABLE_B14_MODEL_IDS = _contract_executable_ids()" in source


def test_product_profiles_follow_the_canonical_route_declaration() -> None:
    assert EXECUTABLE_B14_MODEL_IDS == _declared_executable_model_ids() | {FREE_B14_MODEL_ID}
    assert DEFAULT_B14_MODEL_ID==FREE_B14_MODEL_ID
    assert DEFAULT_CHAT_PROFILE=="free"
    assert model_policy_is_executable(DEFAULT_B14_MODEL_ID)
    assert RETIRED_B14_MODEL_IDS==frozenset({"kilo/minimax-minimax-m3-free","kilo/tencent-hy3-free"})

@pytest.mark.parametrize(
    ("tier_id", "expected_model", "expected_profile"),
    [
        ("plus", LOW_B14_MODEL_ID, "low"),
        ("pro", MEDIUM_B14_MODEL_ID, "medium"),
        ("max", HIGH_B14_MODEL_ID, "high"),
    ],
)
def test_browser_tier_identity_resolves_without_execution(
    tier_id: str,
    expected_model: str,
    expected_profile: str,
) -> None:
    messages = [{"role": "user", "content": "브라우저 등급 선택 테스트"}]
    policy = resolve_tier_policy(messages, tier_id, require_executable=False)
    assert policy.model_id == expected_model
    assert policy.profile == expected_profile
    assert policy.messages == messages


@pytest.mark.parametrize(
    ("tier_id", "module_identity"),
    [
        ("plus", LOW_B14_MODEL_ID),
        ("pro", MEDIUM_B14_MODEL_ID),
        ("max", HIGH_B14_MODEL_ID),
    ],
)
def test_browser_tier_fails_closed_until_its_route_is_executable(
    tier_id: str,
    module_identity: str,
) -> None:
    messages = [{"role": "user", "content": "HOLD 등급 테스트"}]
    if module_identity in EXECUTABLE_B14_MODEL_IDS:
        # An owner declared this tier's route, so the browser tier must resolve
        # to that exact identity instead of failing closed.
        assert resolve_tier_policy(messages, tier_id).model_id == module_identity
        return
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy(messages, tier_id)
    assert info.value.code == "tier_unavailable"


@pytest.mark.parametrize("tier_id", ["", "auto", "fast", "balanced", "deep", "unknown"])
def test_browser_tier_rejects_non_product_values(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "질문"}], tier_id)
    assert info.value.code == "unknown_product_tier"


def test_request_tier_context_is_scoped_to_the_selected_grade() -> None:
    msgs=[{"role":"user","content":"등급 컨텍스트 테스트"}]
    assert resolve_request_model_policy(msgs).profile=="free"
    with request_tier_context("plus"):
        result=resolve_request_model_policy(msgs)
        assert result.model_id==TEST_PHASE_PRIMARY_B14_MODEL_ID
        assert result.profile=="low"
    assert resolve_request_model_policy(msgs).profile=="free"

def test_b62_free_is_the_beam_primary_and_paid_grades_use_google() -> None:
    msgs=[{"role":"user","content":"질문"}]
    free=resolve_tier_policy(msgs,"free")
    assert free.model_id==FREE_B14_MODEL_ID==active_route_for(ProductTierLabel.FREE).model_id
    assert free.profile=="free"
    assert model_policy_is_executable(free.model_id)
    for tier in (ProductTierLabel.PLUS,ProductTierLabel.PRO,ProductTierLabel.MAX):
        assert active_route_for(tier).model_id==TEST_PHASE_PRIMARY_B14_MODEL_ID

def test_free_exact_model_is_not_browser_overridable() -> None:
    with pytest.raises(ModelPolicyError) as exc:
        resolve_tier_policy([{"role": "user", "content": "x"}], "free/custom-model")
    assert exc.value.code == "unknown_product_tier"
    assert model_policy_is_executable(active_route_for(ProductTierLabel.PLUS).model_id) is True
