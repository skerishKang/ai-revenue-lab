"""#3977: B62->Core->B14 never invents 0.2 for an unchosen model setting.

This is a network-free source-contract regression for both text and multimodal.
It does NOT assert the provider accepts any undocumented native option.
"""
from __future__ import annotations

from app.b14_client import _execution_request, _multimodal_execution_request
from app.task_modes import get_task_mode
from padiem_ai_core.b14_execution import B14ChatRequest
from padiem_ai_core.b14_multimodal import B14MultimodalChatRequest
from padiem_ai_core.execution_runtime import _normalize_model_policy


MODEL_ID = "google/gemini-3.1-flash-lite"
MESSAGES = [{"role": "user", "content": "synthetic contract test"}]
MULTIMODAL_MESSAGES = [{
    "role": "user",
    "content": [
        {"type": "text", "text": "synthetic image test"},
        {"type": "image_url", "image_url": {"url": (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
        )}},
    ],
}]


def _profile_and_temperature(agent):
    assert agent.model_policy["model"] == MODEL_ID
    assert "temperature" not in agent.model_policy
    assert agent.model_policy["allow_external_fallback"] is False
    assert agent.model_policy["max_attempts"] == 1
    model, temperature, routing = _normalize_model_policy(agent)
    assert model == MODEL_ID
    assert temperature is None
    return temperature, routing


def test_text_task_omits_unrequested_temperature_through_core_wire():
    req = _execution_request(
        MESSAGES,
        skill=get_task_mode(),
        model=MODEL_ID,
        required_capabilities=("chat",),
        additional_system_context=None,
    )
    temperature, routing = _profile_and_temperature(req.agent)
    body = B14ChatRequest(
        model=MODEL_ID,
        messages=tuple(req.messages),
        temperature=temperature,
        max_tokens=req.agent.max_tokens,
        routing=routing,
    ).to_payload()
    assert "temperature" not in body
    assert body["model"] == MODEL_ID
    assert body["messages"] == MESSAGES
    if req.agent.max_tokens is None:
        assert "max_tokens" not in body
    else:
        assert body["max_tokens"] == req.agent.max_tokens


def test_multimodal_task_omits_unrequested_temperature_through_core_wire():
    req = _multimodal_execution_request(
        MULTIMODAL_MESSAGES,
        skill=get_task_mode(),
        model=MODEL_ID,
        additional_system_context=None,
    )
    temperature, routing = _profile_and_temperature(req.agent)
    body = B14MultimodalChatRequest(
        model=MODEL_ID,
        messages=tuple(req.messages),
        temperature=temperature,
        max_tokens=req.agent.max_tokens,
        routing=routing,
    ).to_payload()
    assert "temperature" not in body
    assert body["model"] == MODEL_ID
    assert body["messages"] == MULTIMODAL_MESSAGES


def test_user_explicit_temperature_still_passes_unchanged():
    req = _execution_request(
        MESSAGES, skill=get_task_mode(), model=MODEL_ID,
        required_capabilities=("chat",), additional_system_context=None,
    )
    explicit_policy = dict(req.agent.model_policy)
    explicit_policy["temperature"] = 0.7
    from padiem_ai_core import AgentProfile
    agent = AgentProfile(
        id=req.agent.id, title=req.agent.title,
        description=req.agent.description,
        system_instruction=req.agent.system_instruction,
        task_type=req.agent.task_type, optimize_for=req.agent.optimize_for,
        max_tokens=req.agent.max_tokens,
        required_capabilities=req.agent.required_capabilities,
        model_policy=explicit_policy,
    )
    model, temp, routing = _normalize_model_policy(agent)
    assert model == MODEL_ID
    assert temp == 0.7
    wire = B14ChatRequest(messages=tuple(req.messages), model=model,
                          temperature=temp, routing=routing).to_payload()
    assert wire["temperature"] == 0.7
