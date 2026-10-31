"""The b14/auto lane is retired: no auto stream client, no scorer-era routing options (B4·B5·B7)."""
import dataclasses

import padiem_ai_core.b14_streaming as b14_streaming
from padiem_ai_core.b14_execution import B14RoutingOptions
from padiem_ai_core.execution_runtime import _MODEL_POLICY_FIELDS


def test_auto_stream_client_is_gone():
    assert not hasattr(b14_streaming.B14StreamingClient, "stream_auto")
    assert not hasattr(b14_streaming.B14StreamingClient, "auto_stream_preview_url")
    assert not hasattr(b14_streaming, "B14_AUTO_STREAM_PREVIEW_PATH")
    assert not hasattr(b14_streaming, "_validate_auto_stream_request")


def test_routing_options_have_no_scorer_era_fields():
    fields = {f.name for f in dataclasses.fields(B14RoutingOptions)}
    assert not ({"task_type", "optimize_for", "allow_external_fallback", "provider_order"} & fields)
    assert {"required_capabilities", "max_retries", "product_tier"} <= fields


def test_model_policy_contract_has_no_fallback_knob():
    assert "allow_external_fallback" not in _MODEL_POLICY_FIELDS
    assert "provider_order" not in _MODEL_POLICY_FIELDS
