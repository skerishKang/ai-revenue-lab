"""#6838: the BYOK reasoning choice rides the engine->B14 hop, never into Core."""
from __future__ import annotations

import pytest

from app.byok_passthrough import REASONING_FIELD, b14_body, credential_scope, split_credential


def _payload(reasoning_effort=None):
    policy = {
        "model": "fixture/model",
        "max_retries": 0,
        "user_credential_required": True,
        "byok_selection": {"provider": "fixture", "model": "fixture/model"},
    }
    if reasoning_effort is not None:
        policy["reasoning_effort"] = reasoning_effort
    return {
        "app_id": "padiem-chat",
        "subject_id": "owner_fixture",
        "user_credential_ref": "opaque-reference-not-json-unit-only",
        "agent": {"model_policy": policy},
    }


def test_split_holds_the_reasoning_choice_for_the_b14_hop():
    # Like user_credential_required/byok_selection, the choice rides the
    # policy to the runtime boundary; core_request strips it before Core.
    payload, ref = split_credential(_payload(reasoning_effort="high"))
    assert ref == "opaque-reference-not-json-unit-only"
    publisher = payload["agent"]["model_policy"]
    assert publisher["reasoning_effort"] == "high"
    assert publisher["user_credential_required"] is True
    assert publisher["byok_selection"] == {"provider": "fixture", "model": "fixture/model"}


def test_b14_body_injects_the_users_reasoning_effort():
    _payload_out, _ref = split_credential(_payload(reasoning_effort="high"))
    import json

    raw = json.dumps({"model": "fixture/model", "messages": []}).encode()
    assert "reasoning_effort" not in json.loads(raw.decode())
    # split_credential stored the choice; b14_body attaches it to the wire body.
    with credential_scope(_ref):
        data = json.loads(b14_body(raw).decode())
    assert data["user_credential_ref"] == "opaque-reference-not-json-unit-only"
    assert data[REASONING_FIELD] == "high"


def test_no_reasoning_field_is_injected_when_the_user_chose_none():
    import json

    _payload_out, _ref = split_credential(_payload())
    raw = json.dumps({"model": "fixture/model", "messages": []}).encode()
    with credential_scope(_ref):
        data = json.loads(b14_body(raw).decode())
    assert "reasoning_effort" not in data


def test_managed_requests_keep_their_exact_bytes():
    import json

    payload = {"app_id": "padiem-chat", "agent": {"model_policy": {"model": "fixture/model"}}}
    out, ref = split_credential(payload)
    assert ref is None
    raw = json.dumps(payload).encode()
    assert b14_body(raw) == raw
