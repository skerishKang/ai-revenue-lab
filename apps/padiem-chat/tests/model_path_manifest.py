"""#5002: execution path of every Chat/Claw/B66 test module.

The four categories describe the boundary a test proves, not where it ran.
A module in ``MOCK`` substitutes the model or engine response and therefore
proves a product logic contract only. None of these categories is a live
end-to-end verdict: live Chat/Claw/B66 evidence belongs to the product
ledgers (#4317/#3936/#4316) and live B14 evidence to #4318.
"""

from __future__ import annotations

BYOK_DIRECT = "BYOK_DIRECT"
B14_MANAGED = "B14_MANAGED"
NO_MODEL = "NO_MODEL"
MOCK = "MOCK"

CATEGORIES = (BYOK_DIRECT, B14_MANAGED, NO_MODEL, MOCK)
DEFAULT_CATEGORY = NO_MODEL

MARKER_BY_CATEGORY = {
    BYOK_DIRECT: "byok_direct",
    B14_MANAGED: "b14_managed",
    NO_MODEL: "no_model",
    MOCK: "mock",
}

# Product -> customer-owned provider directly; no B14 client or route.
BYOK_DIRECT_MODULES = frozenset({
    "test_5121_byok_chat_direct.py",
})

# Product -> B14 managed selection/route/fallback/transport boundary.
# The contract test also fails when a new module imports app.b14_client and
# is missing here, so a new B14-coupled test cannot silently default to
# NO_MODEL. Transport may be substituted; that still proves the B14 boundary
# rather than a live provider call.
B14_MANAGED_MODULES = frozenset({
    "test_2550_stream_fail_taxonomy.py",
    "test_3977_provider_default_temperature_bridge.py",
    "test_4379_full_reference_model_context.py",
    "test_4379_local5_chat_core_integration.py",
    "test_4483_final_dispatch_guard.py",
    "test_admin_model_select_261018.py",
    "test_attachments.py",
    "test_auto_grounding.py",
    "test_b62_2544_completed_timeout.py",
    "test_b66_3906_reasoning_level.py",
    "test_b66_3977_core_reasoning_transport.py",
    "test_b66_ai_chat_routes_4466.py",
    "test_b66_ai_conversation_routes_4412.py",
    "test_b66_dispatch_kst_preinstruction_4465.py",
    "test_b66_experiential_direct_pilot.py",
    "test_b66_kira_direct_pilot.py",
    "test_b66_quote_execution_guards.py",
    "test_b66_quote_upstream_class_diagnostics.py",
    "test_b66_real_b14_source_authority.py",
    "test_b66_registered_model_boundary.py",
    "test_core_text_execution_boundary.py",
    "test_neutral_mock_copy.py",
    "test_owner_tier_fallback_dispatch_261015.py",
    "test_private_auto_stream_client.py",
    "test_private_stream_client.py",
    "test_product_tier_identity.py",
    "test_public_streaming.py",
    "test_runtime.py",
    "test_service_binding.py",
    "test_skills.py",
    "test_tier_route_consumer_coverage.py",
    "test_unassigned_profile_gate.py",
    "test_upstream_busy_diagnostics.py",
    "test_upstream_error_mapping.py",
})

# A fake engine/interpreter/relay stands in for model execution.
# ``"delivery":"live"`` in a relay module is the product SSE protocol value;
# it is not evidence that a real model call happened.
MOCK_MODULES = frozenset({
    "test_3930_b54_live_sse_relay.py",
    "test_3936_b54_p01_conversation_authority_seam.py",
    "test_b54_claw_general_hold_quota_and_evidence.py",
    "test_b54_claw_general_model_hold.py",
    "test_b54_claw_general_p01_routing.py",
    "test_b66_b14_free_first_resolver.py",
    "test_b66_manual_model_choice_contract.py",
    "test_b66_quote_runtime.py",
})

MODULE_CATEGORIES = {
    **{name: BYOK_DIRECT for name in BYOK_DIRECT_MODULES},
    **{name: B14_MANAGED for name in B14_MANAGED_MODULES},
    **{name: MOCK for name in MOCK_MODULES},
}

_overlap = (
    (BYOK_DIRECT_MODULES & B14_MANAGED_MODULES)
    | (BYOK_DIRECT_MODULES & MOCK_MODULES)
    | (B14_MANAGED_MODULES & MOCK_MODULES)
)
if _overlap:
    raise RuntimeError(f"test module has more than one model path: {sorted(_overlap)}")


def path_for_module(module_name: str) -> str:
    """Return the boundary category; unlisted modules have no model boundary."""
    return MODULE_CATEGORIES.get(module_name, DEFAULT_CATEGORY)


def marker_for_module(module_name: str) -> str:
    return MARKER_BY_CATEGORY[path_for_module(module_name)]
